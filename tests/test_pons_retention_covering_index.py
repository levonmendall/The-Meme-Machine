"""Native reporting/retention identity with compact covering access only."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime.robinhood.plane import Plane,canonical
from meme_machine.runtime.robinhood.pons import Broker
from meme_machine.runtime.operating_families import active_sql
from meme_machine.runtime.storage import audit_ring
from meme_machine.lanes.pons.pipeline import Pipeline
from tests.lanes.pons.test_pons_candidate_plane import event


INDEXES=('candidate_lane_identity','transition_retention_order')


def logical(db):
    tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {name:sorted((tuple(row) for row in db.execute('SELECT * FROM '+name)),key=repr) for name in tables}


class PonsRetentionCoveringIndexTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.enterContext(patch.dict(os.environ,MM_OPERATIONAL_PHASE='OFFLINE_INDEX_TEST',MM_MODE='PAPER'))

    def test_existing_database_installs_indexes_without_changing_any_native_rows_and_reopens(self):
        path=self.root/'plane.sqlite'
        broker=Broker(path,'offline-index-policy',clock=lambda:100.)
        try:
            for n in range(1,13):broker.enqueue(event(n))
            for name in INDEXES:broker.plane.db.execute('DROP INDEX '+name)
            before=logical(broker.plane.db)
        finally:broker.close()
        for _ in range(2):
            with closing(Plane(path,clock=lambda:100.)) as plane:
                self.assertEqual(logical(plane.db),before)
                definitions=dict(plane.db.execute("SELECT name,sql FROM sqlite_master WHERE name IN (?,?)",INDEXES))
                self.assertEqual(set(definitions),set(INDEXES))
                self.assertIn('candidates(lane,id)',definitions[INDEXES[0]])
                self.assertIn('transitions(seq,candidate)',definitions[INDEXES[1]])
                self.assertEqual(plane.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_original_native_retention_query_uses_both_covering_indexes(self):
        with closing(Plane(self.root/'plan.sqlite')) as plane:
            predicate='candidate NOT IN (SELECT id FROM candidates WHERE NOT ('+active_sql('lane')+'))'
            sql='SELECT seq FROM transitions WHERE '+predicate+' ORDER BY seq DESC LIMIT 1 OFFSET ?'
            plans=[r[3] for r in plane.db.execute('EXPLAIN QUERY PLAN '+sql,(4095,))]
            self.assertTrue(any('COVERING INDEX transition_retention_order' in p for p in plans),plans)
            self.assertTrue(any('COVERING INDEX candidate_lane_identity' in p for p in plans),plans)

    def test_same_native_publication_and_paused_orphan_null_retention_before_and_after_indexes(self):
        outcomes=[];coverages=[]
        for indexed in (False,True):
            path=self.root/('indexed.sqlite' if indexed else 'legacy.sqlite')
            broker=Broker(path,'offline-index-policy',clock=lambda:100.)
            pipeline=Pipeline(self.root/('indexed-pipeline.sqlite' if indexed else 'legacy-pipeline.sqlite'),'pons','offline-index-policy')
            try:
                plane=broker.plane
                if not indexed:
                    for name in INDEXES:plane.db.execute('DROP INDEX '+name)
                # A historical paused row is retained, not made operational.
                with patch.dict(os.environ,MM_OPERATIONAL_PHASE='',MM_PAPER_EPOCH=''):
                    plane.observe('ramses:historical','ramses','old-observation',dict(synthetic=True),
                        ordering=(1,),watermark={},interpretation={},observed=1,deadline=2,priority=4)
                paused=tuple(plane.db.execute("SELECT * FROM transitions WHERE candidate='ramses:historical'").fetchone())
                for n in range(1,9):broker.enqueue(event(n))
                broker.report_to(pipeline,drain=True)
                # Repeat native reporting: the source cursor and receiving
                # publication identities must remain idempotent.
                first=pipeline.snapshot();broker.report_to(pipeline,drain=True)
                self.assertEqual(pipeline.snapshot(),first)
                with plane.transaction():
                    seq=plane.db.execute('SELECT MAX(seq) FROM transitions').fetchone()[0]
                    plane.db.executemany('INSERT INTO transitions VALUES(?,?,?,?,?,?,?,?,?)',[
                        (seq+1,'retired:orphan',1,100.,'watching',None,'{}','{}',canonical(dict(synthetic=True))),
                        (seq+2,None,1,100.,'watching',None,'{}','{}',canonical(dict(synthetic=True)))])
                    where='candidate NOT IN (SELECT id FROM candidates WHERE NOT ('+active_sql('lane')+'))'
                    audit_ring(plane.db,'transitions','history_no_delete',limit=4,where=where)
                self.assertEqual(tuple(plane.db.execute("SELECT * FROM transitions WHERE candidate='ramses:historical'").fetchone()),paused)
                self.assertIsNotNone(plane.db.execute('SELECT 1 FROM transitions WHERE candidate IS NULL').fetchone())
                self.assertIsNotNone(plane.db.execute("SELECT 1 FROM transitions WHERE candidate='retired:orphan'").fetchone())
                self.assertEqual(plane.db.execute('SELECT COUNT(*) FROM transitions WHERE '+where).fetchone()[0],4)
                with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):
                    plane.db.execute('DELETE FROM transitions')
                with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):
                    plane.db.execute('UPDATE transitions SET kind=kind')
                outcomes.append(logical(plane.db));coverages.append(first)
            finally:pipeline.close();broker.close()
        self.assertEqual(outcomes[0],outcomes[1])
        # Debug timestamps differ between independently recorded Pipeline
        # publications; authoritative stage/class/candidate counts must agree.
        for coverage in coverages:coverage.pop('last_transition',None)
        self.assertEqual(coverages[0],coverages[1])


if __name__=='__main__':unittest.main()
