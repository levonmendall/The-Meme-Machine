import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from meme_machine.lanes.pons.pipeline import Pipeline

class OpportunityCoverageTests(unittest.TestCase):
    def test_unchanged_coverage_snapshots_do_not_repeat_retained_policy_scan(self):
        """Disposable operation count, not attribution of the live CPU sample."""
        with tempfile.TemporaryDirectory() as directory:
            pipeline=Pipeline(Path(directory)/'progress.sqlite','pons','frozen')
            try:
                for index in range(64):pipeline.record('candidate-'+str(index),'discovered')
                expected=pipeline.snapshot()
                queries=[];steps=[0]
                def executed(sql):
                    if 'GROUP BY policy_hash' in sql:queries.append(sql)
                def instruction():steps[0]+=1;return 0
                pipeline.db.set_trace_callback(executed)
                pipeline.db.set_progress_handler(instruction,1)
                try:
                    actual=[pipeline.snapshot() for _ in range(32)]
                finally:
                    pipeline.db.set_trace_callback(None);pipeline.db.set_progress_handler(None,0)
                self.assertTrue(all(row==expected for row in actual))
                encoded=json.dumps(expected,sort_keys=True)
                self.assertTrue(all(json.dumps(row,sort_keys=True)==encoded for row in actual))
                self.assertEqual(len(queries),0,
                    'unchanged reporting repeated retained-policy GROUP BY: '
                    +str(dict(grouped_scans=len(queries),sqlite_vm_steps=steps[0],snapshots=32,rows=64)))
                print('pons_pipeline_snapshot_operation_counts='+json.dumps(dict(
                    grouped_scans=len(queries),sqlite_vm_steps=steps[0],snapshots=32,rows=64),sort_keys=True))
                actual[0]['retained_policy_record_counts']['frozen']=999
                self.assertEqual(pipeline.snapshot()['retained_policy_record_counts'],{'frozen':64})
            finally:pipeline.close()

    def test_retained_policy_counts_observe_local_external_and_rolled_back_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'progress.sqlite'
            pipeline=Pipeline(path,'pons','frozen');other=Pipeline(path,'pons','frozen')
            try:
                pipeline.record('first','discovered')
                self.assertEqual(pipeline.snapshot()['retained_policy_record_counts'],{'frozen':1})
                pipeline.record('second','discovered')
                self.assertEqual(pipeline.snapshot()['retained_policy_record_counts'],{'frozen':2})
                other.record('external','discovered')
                self.assertEqual(pipeline.snapshot()['retained_policy_record_counts'],{'frozen':3})
                # Existing snapshot semantics include this caller's transaction
                # but must not reuse its uncommitted count after a rollback.
                pipeline.db.execute('BEGIN')
                try:
                    pipeline.db.execute("""INSERT INTO progress
                        (lane,policy_hash,candidate,stage,at,monotonic,details)
                        VALUES('pons','frozen','rolled-back','discovered',1,1,'{}')""")
                    self.assertEqual(pipeline.snapshot()['retained_policy_record_counts'],{'frozen':4})
                finally:pipeline.db.rollback()
                self.assertEqual(pipeline.snapshot()['retained_policy_record_counts'],{'frozen':3})
                other.close();other=Pipeline(path,'pons','frozen')
                self.assertEqual(other.snapshot()['retained_policy_record_counts'],{'frozen':3})
                # Seed only this disposable debug ring in one fixture commit.
                # Reopen through the real constructor, then cross its actual
                # 8192-row boundary and preserve the existing 4096-row pruning.
                with pipeline.db:
                    pipeline.db.executemany("""INSERT INTO progress
                        (lane,policy_hash,candidate,stage,at,monotonic,details)
                        VALUES('pons','frozen',?,'discovered',1,1,'{}')""",
                        (('retained-'+str(index),) for index in range(8188)))
                pipeline.close();pipeline=Pipeline(path,'pons','frozen')
                self.assertEqual(pipeline.snapshot()['retained_policy_record_counts'],{'frozen':8191})
                pipeline.record('retention-boundary','discovered')
                retained=pipeline.snapshot()
                self.assertEqual(retained['retained_policy_record_counts'],{'frozen':4096})
                self.assertEqual(retained['raw_records'],4096)
                self.assertEqual(other.snapshot()['retained_policy_record_counts'],{'frozen':4096})
            finally:other.close();pipeline.close()

    def test_external_commit_during_version_read_is_not_cached_as_current(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'progress.sqlite'
            pipeline=Pipeline(path,'pons','frozen');other=Pipeline(path,'pons','frozen')
            try:
                pipeline.record('first','discovered')
                self.assertEqual(pipeline.snapshot()['retained_policy_record_counts'],{'frozen':1})
                committed=[]
                def commit_during_read(sql):
                    if sql=='PRAGMA data_version' and not committed:
                        committed.append(True);other.record('concurrent','discovered')
                pipeline.db.set_trace_callback(commit_during_read)
                try:first=pipeline.snapshot()['retained_policy_record_counts']['frozen']
                finally:pipeline.db.set_trace_callback(None)
                # The first result may linearize before or after the commit;
                # the next snapshot must observe the committed generation.
                self.assertEqual(committed,[True]);self.assertIn(first,(1,2))
                self.assertEqual(pipeline.snapshot()['retained_policy_record_counts'],{'frozen':2})
            finally:other.close();pipeline.close()

    def test_unique_candidates_not_consumer_or_attempt_count_and_replay(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'progress.db'
            p=Pipeline(path,'pump','frozen')
            for _ in range(10):p.record('mint','evidence_requested')
            p.record('mint','terminal','queue_deadline','capacity_censored')
            p.record('mint','evidence_complete')
            p.record('other','discovered')
            expected=p.snapshot()
            self.assertEqual(expected['stages']['evidence_requested'],1)
            self.assertEqual(expected['unique_classes']['capacity_censored'],1)
            self.assertEqual(p.db.execute('SELECT COUNT(*) FROM progress').fetchone()[0],13)
            with self.assertRaises(sqlite3.IntegrityError):p.db.execute('DELETE FROM progress')
            p.close();q=Pipeline(path,'pump','frozen')
            self.assertEqual(q.snapshot(),expected);q.close()
            with self.assertRaisesRegex(ValueError,'namespace'):Pipeline(path,'meteora','frozen')
