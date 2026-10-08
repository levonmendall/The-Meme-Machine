import fcntl
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational import durable_acceptance as durable


class DurableAcceptance(unittest.TestCase):
    def test_failed_and_unknown_acceptance_evidence_is_not_pruned_with_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for n in range(5):
                p=root/str(n);p.mkdir();(p/'status.json').write_text(json.dumps(dict(status='PASS')))
            failed=root/'failure';failed.mkdir();(failed/'status.json').write_text(json.dumps(dict(status='FAIL')))
            unknown=root/'unknown';unknown.mkdir();(unknown/'unique').write_text('evidence')
            durable.retain_completed(root,keep=2)
            self.assertTrue(failed.is_dir());self.assertTrue((unknown/'unique').exists())
            self.assertEqual(len([p for p in root.iterdir() if p.is_dir()]),4)

    def test_storage_pressure_stops_engineering_child_and_retains_failure_record(self):
        from meme_machine.operational.artifact_storage import ArtifactStorageFull
        with tempfile.TemporaryDirectory() as td:
            with patch('meme_machine.operational.artifact_storage.headroom',side_effect=ArtifactStorageFull('root_headroom')):
                row=durable.run_child([sys.executable,'-c','import time;time.sleep(30)'],td,{'phase':'MECHANISM_PROBE'})
            self.assertEqual(row['status'],'FAIL');self.assertIsNotNone(row['exit_code'])
            self.assertIn('engineering_storage_headroom',row['observation_errors'])
            self.assertTrue((Path(td)/'status.json').exists())

    def test_real_child_exit_stdout_stderr_and_timestamps_persist(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            with patch.object(durable.time,'sleep',return_value=None):
                record=durable.run_child([sys.executable,'-c','import sys;print("probe stdout");print("probe stderr",file=sys.stderr);sys.exit(7)'],folder,{'phase':'MECHANISM_PROBE'})
            result=json.loads((folder/'status.json').read_text())
            self.assertEqual(record['exit_code'],7)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('probe stdout',(folder/'stdout.log').read_text())
            self.assertIn('probe stderr',(folder/'stderr.log').read_text())
            self.assertGreaterEqual(result['end_timestamp'],result['start_timestamp'])

    def test_successful_short_child_cannot_pass_full_duration(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(durable.time,'sleep',return_value=None):
                row=durable.run_child([sys.executable,'-c','pass'],td,{'phase':'MECHANISM_PROBE','required_seconds':129600})
            self.assertEqual(row['status'],'FAIL')
            self.assertFalse(row['full_duration_completed'])

    def test_other_phase_cannot_overlap_current_run(self):
        with tempfile.TemporaryDirectory() as td:
            with (Path(td)/'run.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaisesRegex(RuntimeError,'acceptance_already_running'):
                    durable.execute('RECOVERY',output=td)

    def test_systemd_kill_finalizes_as_failure_without_claiming_completion(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'run';folder.mkdir()
            pointer=Path(td)/'latest-AUTONOMY.json'
            pointer.write_text(json.dumps(dict(status='RUNNING',directory=str(folder),full_duration_completed=False)))
            durable.finalize('AUTONOMY',td)
            value=json.loads(pointer.read_text())
            self.assertEqual(value['status'],'FAIL')
            self.assertTrue(value['interrupted'])
            self.assertFalse(value['full_duration_completed'])

    def test_stale_observation_is_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td)/'latest.json').write_text(json.dumps(dict(timestamp=1,portfolio={'epoch_id':'paper-existing'})))
            with self.assertRaisesRegex(ValueError,'observation_stale_or_wrong_epoch'):
                durable.observed(td,'paper-existing',now=100)


if __name__=='__main__':unittest.main()
