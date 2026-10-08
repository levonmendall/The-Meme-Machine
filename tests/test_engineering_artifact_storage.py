"""Storage pressure must refuse new artifacts without losing existing state."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational import artifact_storage as storage


def disk(percent, device=1, total=100*storage.GIB):
    used=int(total*percent/100)
    return dict(used_bytes=used,free_bytes=total-used,total_bytes=total,
                percent_used=percent,device=device)


class Headroom(unittest.TestCase):
    def test_retained_snapshot_quota_preserves_old_failure_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'source';root.mkdir();(root/'native').write_bytes(b'x'*1024)
            parent=Path(td)/'points';parent.mkdir();evidence=parent/'unresolved-failure'
            evidence.write_bytes(b'y'*16384)
            policy=storage.Policy(snapshot_max_bytes=8192,snapshot_total_bytes=16384)
            with self.assertRaisesRegex(storage.ArtifactStorageFull,'retained_quota'):
                storage.admit_snapshot(root,parent,policy=policy)
            self.assertEqual(evidence.read_bytes(),b'y'*16384)
            storage.admit_snapshot(root,parent,policy=policy,nonessential=False)

    def test_snapshot_inventory_rejects_symlink_without_following_unique_source(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'source';root.mkdir();unique=Path(td)/'unique';unique.write_text('keep')
            (root/'alias').symlink_to(unique)
            with self.assertRaisesRegex(ValueError,'snapshot_symlink'):
                storage.admit_snapshot(root,Path(td)/'copies')
            self.assertEqual(unique.read_text(),'keep')

    def test_warning_and_exact_block_threshold_and_projected_growth(self):
        with patch.object(storage,'usage',return_value=disk(75)),patch('sys.stderr',new_callable=io.StringIO) as log:
            storage.headroom('/tmp',storage.GIB)
            self.assertIn('STORAGE WARNING',log.getvalue())
        for current,estimate in ((85,0),(84,storage.GIB)):
            with patch.object(storage,'usage',return_value=disk(current)):
                with self.assertRaisesRegex(storage.ArtifactStorageFull,'root_headroom'):
                    storage.headroom('/tmp',estimate,warn=False)

    def test_existing_volume_backup_uses_reserve_without_root_engineering_block(self):
        with patch.object(storage,'usage',side_effect=lambda path:disk(90) if str(path)=='/' else disk(40,device=2)):
            storage.headroom('/isolated-volume-point',storage.GIB,nonessential=False,warn=False)
            with self.assertRaisesRegex(storage.ArtifactStorageFull,'root_headroom'):
                storage.headroom('/isolated-volume-point',storage.GIB,warn=False)

    def test_reserve_still_required_for_essential_backup(self):
        with patch.object(storage,'usage',side_effect=lambda path:disk(50) if str(path)=='/' else disk(97,device=2)):
            with self.assertRaisesRegex(storage.ArtifactStorageFull,'destination_copy_reserve'):
                storage.headroom('/volume',storage.GIB,nonessential=False,warn=False)

    def test_configurable_policy_rejects_invalid_and_nonfinite_thresholds(self):
        with patch.dict(os.environ,{'MM_STORAGE_WARN_PERCENT':'70','MM_STORAGE_BLOCK_PERCENT':'80'}):
            self.assertEqual(storage.Policy.environment().block_percent,80)
        for value in ('75','nan','100'):
            with patch.dict(os.environ,{'MM_STORAGE_BLOCK_PERCENT':value}):
                with self.assertRaises(ValueError):storage.Policy.environment()


class OfflineScratch(unittest.TestCase):
    def policy(self):
        return storage.Policy(scratch_max_bytes=1024*1024,scratch_total_bytes=2*1024*1024)

    def test_success_cleans_only_owned_scope_and_restores_temp_environment(self):
        with tempfile.TemporaryDirectory() as parent:
            foreign=Path(parent)/'unrelated';foreign.mkdir();(foreign/'keep').write_text('unique')
            previous=os.environ.get('TMPDIR');old=tempfile.tempdir
            with storage.Scratch(parent,policy=self.policy()) as scope:
                self.assertEqual(tempfile.gettempdir(),str(scope.path))
                (scope.path/'fixture').write_text('repeatable')
                scope.check();scope.success=True
            self.assertFalse(scope.path.exists())
            self.assertEqual(os.environ.get('TMPDIR'),previous);self.assertEqual(tempfile.tempdir,old)
            self.assertEqual((foreign/'keep').read_text(),'unique')

    def test_failure_and_interrupt_preserve_evidence_and_stop_at_quota(self):
        with tempfile.TemporaryDirectory() as parent:
            with self.assertRaises(KeyboardInterrupt):
                with storage.Scratch(parent,policy=self.policy()) as scope:
                    (scope.path/'failure').write_text('diagnostic')
                    raise KeyboardInterrupt()
            self.assertEqual((scope.path/'failure').read_text(),'diagnostic')
            self.assertEqual(json.loads((scope.path/'engineering-artifact.json').read_text())['status'],'FAILED_EVIDENCE_RETAINED')
            (scope.path/'over-budget').write_bytes(b'x'*(2*1024*1024))
            with self.assertRaises(storage.ArtifactStorageFull):
                with storage.Scratch(parent,policy=self.policy()):self.fail('quota bypassed')
            self.assertTrue((scope.path/'failure').exists())

    def test_unknown_links_are_never_followed_or_pruned(self):
        with tempfile.TemporaryDirectory() as parent:
            foreign=Path(parent)/'unique';foreign.mkdir();(foreign/'keep').write_text('state')
            alias=Path(parent)/'mm-engineering-foreign';alias.symlink_to(foreign,target_is_directory=True)
            with storage.Scratch(parent,policy=self.policy()) as scope:scope.success=True
            self.assertTrue(alias.is_symlink());self.assertEqual((foreign/'keep').read_text(),'state')

    def test_per_scope_limit_detects_aggregate_growth(self):
        with tempfile.TemporaryDirectory() as parent:
            with storage.Scratch(parent,policy=self.policy()) as scope:
                (scope.path/'one').write_bytes(b'x'*600000)
                (scope.path/'two').write_bytes(b'x'*600000)
                with self.assertRaises(storage.ArtifactStorageFull):scope.check()
            self.assertTrue((scope.path/'one').exists())

    def test_parallel_scope_growth_cannot_bypass_retained_parent_budget(self):
        with tempfile.TemporaryDirectory() as parent:
            other=Path(parent)/'mm-engineering-other-job';other.mkdir()
            with storage.Scratch(parent,policy=self.policy()) as scope:
                (other/'concurrent-fixture').write_bytes(b'y'*1600000)
                (scope.path/'own-fixture').write_bytes(b'x'*600000)
                with self.assertRaisesRegex(storage.ArtifactStorageFull,'retained_quota'):
                    scope.check()
            self.assertTrue((other/'concurrent-fixture').exists())
            self.assertTrue((scope.path/'own-fixture').exists())


if __name__=='__main__':unittest.main()
