"""Old runtime ordering prefixes and full archived-window projections."""
from pathlib import Path
import tempfile
import unittest

from meme_machine.runtime.robinhood.plane import Plane,digest


class ArchiveSnapshotTests(unittest.TestCase):
    def test_runtime_maintenance_prefix_reopens_without_historical_window_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'plane.sqlite'
            plane=Plane(path,clock=lambda:100)
            plane.observe('pool','ramses','event',{},ordering=(1,),
                watermark={'hash':'h1'},interpretation={'policy':'frozen'},
                observed=100,deadline=None,priority=3)
            work=plane.claim(lane='ramses');plane.finish(work,result={'decision':{'qualified':False}})
            plane.consume('pool',work['generation']);plane.maintain()
            prefix=plane.history_archive()
            self.assertNotIn('windows',prefix)
            plane.close();plane=Plane(path,clock=lambda:100)
            try:
                before=plane.checkpoint_read('window_history_archive')
                snapshot=plane.snapshot()
                self.assertEqual(snapshot['unique_candidates'],1)
                self.assertEqual(snapshot['provider_jobs_claimed'],1)
                self.assertEqual(snapshot['history_archive'],dict(chain_hash=prefix['chain_hash'],
                    windows=None,transition_high_water=None,
                    reporting_scope='runtime_retired_ordering_prefix'))
                self.assertEqual(plane.checkpoint_read('window_history_archive'),before)
                self.assertEqual(plane.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            finally:plane.close()

    def test_historical_archive_projection_and_transition_sequence_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'plane.sqlite';plane=Plane(path,clock=lambda:100)
            prefix=dict(schema='robinhood-window-history-v1',windows=4,
                transition_high_water=17,reporting_scope='verified_predecessor_windows',
                retired_ordering={})
            prefix['chain_hash']=digest(prefix)
            plane.checkpoint('window_history_archive',prefix);plane.close()
            plane=Plane(path,clock=lambda:100)
            try:
                self.assertEqual(plane.snapshot()['history_archive'],
                    {key:prefix[key] for key in ('chain_hash','windows','transition_high_water','reporting_scope')})
                plane.observe('pool','ramses','event',{},ordering=(1,),
                    watermark={'hash':'h1'},interpretation={'policy':'frozen'},
                    observed=100,deadline=None,priority=3)
                self.assertEqual(plane.db.execute('SELECT MIN(seq) FROM transitions').fetchone()[0],18)
                plane.maintain()
                self.assertEqual(plane.history_archive(),prefix)
            finally:plane.close()

    def test_missing_observation_fields_do_not_waive_archive_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            plane=Plane(Path(directory)/'plane.sqlite')
            try:
                for prefix in ({'schema':'robinhood-window-history-v1','retired_ordering':{},'chain_hash':'invalid'},
                               {'schema':'wrong','retired_ordering':{}}):
                    plane.checkpoint('window_history_archive',prefix)
                    with self.assertRaisesRegex(ValueError,'robinhood_history_archive_corruption'):
                        plane.snapshot()
            finally:plane.close()
