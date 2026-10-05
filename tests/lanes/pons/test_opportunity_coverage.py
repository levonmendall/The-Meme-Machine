import sqlite3
import tempfile
import unittest
from pathlib import Path
from meme_machine.lanes.pons.pipeline import Pipeline

class OpportunityCoverageTests(unittest.TestCase):
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
