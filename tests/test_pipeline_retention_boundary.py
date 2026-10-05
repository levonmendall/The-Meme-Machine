"""Real old-schema pipeline history crosses retention without a foreign table."""
import importlib,tempfile,unittest
from pathlib import Path

class PipelineRetentionBoundaryTests(unittest.TestCase):
    def test_all_four_lanes_cross_retention_and_restart_with_monotone_sequence(self):
        for lane in ('pump','meteora','pons','ramses'):
            with self.subTest(lane=lane),tempfile.TemporaryDirectory() as td:
                Pipeline=importlib.import_module('meme_machine.lanes.'+lane+'.pipeline').Pipeline
                path=Path(td)/'pipeline.sqlite';pipeline=Pipeline(path,lane,'fixed-policy')
                pipeline.db.executemany('INSERT INTO progress(sequence,lane,policy_hash,candidate,stage,reason,classification,at,monotonic,details) VALUES(?,?,?,?,?,?,?,?,?,?)',[(i,lane,'fixed-policy','candidate:'+str(i),'observed',None,None,100,100,'{}') for i in range(1,8192)])
                pipeline.db.commit();pipeline.close()
                pipeline=Pipeline(path,lane,'fixed-policy')
                try:
                    pipeline.record('boundary','rejected','observed-rejection','strategy_rejection')
                    self.assertEqual(pipeline.db.execute('SELECT COUNT(*) FROM progress').fetchone()[0],4096)
                    self.assertEqual(pipeline.db.execute('SELECT MAX(sequence) FROM progress').fetchone()[0],8192)
                    pipeline.record('next','observed')
                    self.assertEqual(pipeline.db.execute('SELECT MAX(sequence) FROM progress').fetchone()[0],8193)
                    self.assertEqual(pipeline.snapshot()['unique_classes']['strategy_rejection'],1)
                finally:pipeline.close()
                pipeline=Pipeline(path,lane,'fixed-policy')
                try:
                    self.assertEqual(pipeline.snapshot()['raw_records'],4097)
                    self.assertEqual(pipeline.snapshot()['unique_classes']['strategy_rejection'],1)
                    pipeline.record('restart','observed')
                    self.assertEqual(pipeline.db.execute('SELECT MAX(sequence) FROM progress').fetchone()[0],8194)
                finally:pipeline.close()
