"""Native reporting reuses durable source identity without rescanning old prefixes."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime.robinhood.accounting import high_water, project
from meme_machine.runtime.robinhood.plane import Plane, digest
from meme_machine.lanes.pons.pipeline import Pipeline


class ProjectionSourceReuseTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,{},clear=True))
        self.temp=self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root=Path(self.temp)
        self.plane=Plane(self.root/'plane.sqlite',clock=lambda:100)
        self.addCleanup(lambda:self.plane.close())
        self.pipeline=Pipeline(self.root/'pipeline.sqlite','pons','offline-policy')
        self.addCleanup(lambda:self.pipeline.close())

    def observe(self,key='current',lane='pons',n=1):
        return self.plane.observe(key,lane,str(n),dict(synthetic=True,n=n),
            ordering=(n,),watermark=dict(block=n),interpretation=dict(policy='offline'),
            observed=100,deadline=105,priority=4)

    def statements(self,call):
        rows=[]
        self.plane.db.set_trace_callback(rows.append)
        try:result=call()
        finally:self.plane.db.set_trace_callback(None)
        return result,rows

    def assert_no_identity_scan_or_checkpoint_writer(self,rows):
        self.assertFalse(any('ORDER BY t.seq LIMIT 1' in row for row in rows),rows)
        self.assertFalse(any(row.startswith('BEGIN') or row.startswith('UPDATE runtime')
                             or row.startswith('INSERT INTO runtime') for row in rows),rows)

    def archive(self,sources):
        row=dict(schema='robinhood-window-history-v1',projection_sources=sources)
        row['chain_hash']=digest(row)
        self.plane.checkpoint('window_history_archive',row)

    def test_first_projection_uses_original_first_row_hash_then_idle_turn_avoids_scan_and_write(self):
        self.observe()
        first=self.plane.db.execute('SELECT * FROM transitions ORDER BY seq LIMIT 1').fetchone()
        expected='candidate-plane:'+hashlib.sha256(json.dumps(dict(first),sort_keys=True).encode()).hexdigest()
        count,first_sql=self.statements(lambda:project(self.plane,self.pipeline))
        self.assertEqual(count,1)
        self.assertTrue(any('ORDER BY t.seq LIMIT 1' in row for row in first_sql))
        self.assertEqual(self.plane.checkpoint_read('projection_source:pons'),expected)
        count,idle_sql=self.statements(lambda:project(self.plane,self.pipeline))
        self.assertEqual(count,0)
        self.assert_no_identity_scan_or_checkpoint_writer(idle_sql)

    def test_empty_uninitialized_source_returns_zero_without_inventing_identity(self):
        self.assertEqual(project(self.plane,self.pipeline),0)
        self.assertIsNone(self.plane.checkpoint_read('projection_source:pons'))
        self.assertEqual(self.pipeline.db.execute('SELECT COUNT(*) FROM progress').fetchone()[0],0)

    def test_retired_prefix_does_not_erase_receipts_or_repeat_old_source_discovery(self):
        self.observe('retired')
        project(self.plane,self.pipeline)
        source=self.plane.checkpoint_read('projection_source:pons')
        with self.plane.transaction():
            self.plane.db.execute("DELETE FROM candidates WHERE id='retired'")
        self.observe('new-current',n=2)
        count,rows=self.statements(lambda:project(self.plane,self.pipeline))
        self.assertEqual(count,1)
        self.assert_no_identity_scan_or_checkpoint_writer(rows)
        self.assertEqual(self.plane.checkpoint_read('projection_source:pons'),source)
        self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM transitions').fetchone()[0],2)
        self.assertEqual(self.pipeline.db.execute('SELECT COUNT(*) FROM progress_sources WHERE source=?',(source,)).fetchone()[0],2)

    def test_durable_source_with_all_candidates_retired_stays_idle_without_scan(self):
        self.observe()
        project(self.plane,self.pipeline)
        with self.plane.transaction():self.plane.db.execute('DELETE FROM candidates')
        count,rows=self.statements(lambda:project(self.plane,self.pipeline))
        self.assertEqual(count,0)
        self.assert_no_identity_scan_or_checkpoint_writer(rows)

    def test_restart_and_reset_pipeline_replay_same_source_idempotently(self):
        self.observe()
        project(self.plane,self.pipeline)
        source=self.plane.checkpoint_read('projection_source:pons')
        self.plane.close()
        self.plane=Plane(self.root/'plane.sqlite',clock=lambda:100)
        replacement=Pipeline(self.root/'replacement.sqlite','pons','offline-policy')
        try:
            count,rows=self.statements(lambda:project(self.plane,replacement))
            self.assertEqual(count,1)
            self.assert_no_identity_scan_or_checkpoint_writer(rows)
            self.assertEqual(project(self.plane,replacement),0)
            self.assertEqual(replacement.db.execute('SELECT DISTINCT source FROM progress_sources').fetchone()[0],source)
        finally:replacement.close()

    def test_verified_archive_source_is_reused_and_materialized_once_without_first_scan(self):
        self.observe()
        self.archive(dict(pons='candidate-plane:archived-offline-source'))
        count,rows=self.statements(lambda:project(self.plane,self.pipeline))
        self.assertEqual(count,1)
        self.assertFalse(any('ORDER BY t.seq LIMIT 1' in row for row in rows),rows)
        self.assertEqual(self.plane.checkpoint_read('projection_source:pons'),'candidate-plane:archived-offline-source')
        count,rows=self.statements(lambda:project(self.plane,self.pipeline))
        self.assertEqual(count,0)
        self.assert_no_identity_scan_or_checkpoint_writer(rows)

    def test_archive_corruption_fails_closed_even_after_durable_identity_established(self):
        self.observe()
        project(self.plane,self.pipeline)
        self.plane.checkpoint('window_history_archive',
            dict(schema='robinhood-window-history-v1',chain_hash='corrupt'))
        with self.assertRaisesRegex(ValueError,'archive_corruption'):
            project(self.plane,self.pipeline)

    def test_malformed_durable_source_fails_closed_without_replacing_identity(self):
        self.observe()
        project(self.plane,self.pipeline)
        with self.plane.transaction():
            self.plane.db.execute("UPDATE runtime SET body='not-json' WHERE key='projection_source:pons'")
        with self.assertRaises(json.JSONDecodeError):project(self.plane,self.pipeline)

    def test_independent_lanes_keep_distinct_sources_and_only_project_their_own_rows(self):
        self.observe('pons',lane='pons')
        self.observe('ramses',lane='ramses')
        other=Pipeline(self.root/'other.sqlite','ramses','offline-policy')
        try:
            self.assertEqual(project(self.plane,self.pipeline),1)
            self.assertEqual(project(self.plane,other),1)
            self.assertNotEqual(self.plane.checkpoint_read('projection_source:pons'),
                                self.plane.checkpoint_read('projection_source:ramses'))
            self.assertEqual(self.pipeline.db.execute('SELECT candidate FROM progress').fetchone()[0],'pons')
            self.assertEqual(other.db.execute('SELECT candidate FROM progress').fetchone()[0],'ramses')
        finally:other.close()

    def test_original_page_bound_and_captured_high_water_remain_exact(self):
        for n in range(1,6):self.observe('current',n=n)
        through=high_water(self.plane)
        self.observe('after-cut',n=6)
        observed=[]
        while True:
            count=project(self.plane,self.pipeline,through=through,batch_size=2)
            observed.append(count)
            if count<2:break
        # First discovery plus a superseded/watching pair for each new state.
        self.assertEqual(sum(observed),9)
        self.assertLessEqual(max(observed),2)
        self.assertEqual(project(self.plane,self.pipeline),1)
        with self.assertRaisesRegex(ValueError,'bound'):project(self.plane,self.pipeline,batch_size=257)

