"""Production startup must reject missing/wrong storage without creating state."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational.storage_guard import verify_storage, StorageGuardError
from meme_machine.operational.supervisor import Supervisor


class StorageStartup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mount = Path(self.tmp.name) / 'volume'
        self.root = self.mount / 'paper'
        self.root.mkdir(parents=True)
        receipt = {'epoch_id': 'paper-preserved', 'paper_only': True}
        body = json.dumps(receipt, sort_keys=True, separators=(',', ':'))
        checksum = hashlib.sha256(body.encode()).hexdigest()
        with sqlite3.connect(self.root/'portfolio.sqlite') as db:
            db.execute('CREATE TABLE portfolio_inception(id,body,sha256)')
            db.execute('INSERT INTO portfolio_inception VALUES(1,?,?)', (body, checksum))
        self.config = Path(self.tmp.name) / 'storage.json'
        self.expected = dict(mount_target=str(self.mount), state_root=str(self.root),
            volume_device='/dev/disk/by-id/expected-volume',
            filesystem_uuid='expected-filesystem', epoch_id='paper-preserved',
            inception_sha256=checksum)
        self.config.write_text(json.dumps(self.expected))
        self.config.chmod(0o644)
        self.mounted = dict(target=str(self.mount), uuid='expected-filesystem',
                            fstype='ext4', options='rw,noatime')
        self.mounted['maj:min'] = '8:0'
        device = patch('meme_machine.operational.storage_guard.device_identity',return_value='8:0')
        device.start(); self.addCleanup(device.stop)
        self.env = patch.dict(os.environ, MM_STORAGE_GUARD_CONFIG=str(self.config))
        self.env.start(); self.addCleanup(self.env.stop)

    def hashes(self):
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def run_mount(self, row):
        return patch('meme_machine.operational.storage_guard.subprocess.run',
                     return_value=SimpleNamespace(stdout=json.dumps({'filesystems': [row]})))

    def test_valid_existing_identity_is_read_only(self):
        before = self.hashes()
        with self.run_mount(self.mounted):
            self.assertEqual(verify_storage(self.root)['epoch_id'], 'paper-preserved')
        self.assertEqual(self.hashes(), before)

    def assert_startup_rejected(self, row, reason):
        before = self.hashes()
        with self.run_mount(row), patch('meme_machine.operational.supervisor.validate_environment'), \
                patch.object(Supervisor, 'account', side_effect=AssertionError('writer reached')):
            with self.assertRaisesRegex(StorageGuardError, reason):
                Supervisor(self.root).initialize()
        self.assertEqual(self.hashes(), before)
        self.assertFalse((self.root/'supervisor.lock').exists())

    def test_missing_mount_never_creates_replacement_epoch(self):
        self.root.joinpath('portfolio.sqlite').unlink()
        self.root.rmdir(); self.mount.rmdir()
        self.assert_startup_rejected(dict(self.mounted, target='/', uuid='root-disk'),
                                     'expected_persistent_volume_not_mounted')
        self.assertFalse(self.root.exists())

    def test_wrong_volume_rejected_before_any_writer(self):
        self.assert_startup_rejected(dict(self.mounted, uuid='wrong-filesystem'),
                                     'expected_persistent_volume_not_mounted')

    def test_nested_mount_rejected(self):
        self.assert_startup_rejected(dict(self.mounted, target=str(self.root)),
                                     'expected_persistent_volume_not_mounted')

    def test_cloned_filesystem_uuid_on_wrong_volume_is_rejected(self):
        self.assert_startup_rejected(dict(self.mounted, **{'maj:min':'8:1'}),
                                     'expected_persistent_volume_not_mounted')

    def test_readonly_mount_rejected(self):
        self.assert_startup_rejected(dict(self.mounted, options='ro,noatime'),
                                     'expected_persistent_volume_not_mounted')

    def test_observer_can_verify_readonly_mount_without_relaxing_startup(self):
        before = self.hashes()
        with self.run_mount(dict(self.mounted, options='ro,noatime')):
            self.assertEqual(verify_storage(self.root, require_writable=False)['epoch_id'],
                             'paper-preserved')
            with self.assertRaisesRegex(StorageGuardError, 'expected_persistent_volume_not_mounted'):
                verify_storage(self.root)
        self.assertEqual(self.hashes(), before)

    def test_readonly_observer_still_rejects_cloned_wrong_volume(self):
        before = self.hashes()
        with self.run_mount(dict(self.mounted, options='ro,noatime', **{'maj:min':'8:1'})):
            with self.assertRaisesRegex(StorageGuardError, 'expected_persistent_volume_not_mounted'):
                verify_storage(self.root, require_writable=False)
        self.assertEqual(self.hashes(), before)

    def test_missing_portfolio_cannot_reseed(self):
        (self.root/'portfolio.sqlite').unlink()
        self.assert_startup_rejected(self.mounted, 'existing_portfolio_required')

    def test_unbound_portfolio_cannot_reseed(self):
        with sqlite3.connect(self.root/'portfolio.sqlite') as db:
            db.execute('DELETE FROM portfolio_inception')
        self.assert_startup_rejected(self.mounted, 'existing_portfolio_inception_required')

    def test_wrong_epoch_leaves_valid_existing_database_untouched(self):
        self.expected['epoch_id'] = 'paper-another'
        self.config.write_text(json.dumps(self.expected))
        self.assert_startup_rejected(self.mounted, 'existing_PAPER_epoch_identity_mismatch')

    def test_missing_configuration_fails_before_directory_creation(self):
        self.config.unlink()
        self.assert_startup_rejected(self.mounted, 'storage_identity_unavailable')

    def test_service_requires_mount_and_checks_epoch_before_execstart(self):
        service = (Path(__file__).resolve().parents[1]/'deployment/meme-machine-paper.service').read_text()
        self.assertIn('BindsTo=mnt-volume_nyc1_1790918115030.mount', service)
        self.assertIn('RequiresMountsFor=/mnt/volume_nyc1_1790918115030/meme-machine-paper-v1', service)
        self.assertIn('AssertPathIsMountPoint=/mnt/volume_nyc1_1790918115030', service)
        self.assertIn('ExecStartPre=/opt/meme-machine/.venv/bin/python -m meme_machine.operational.storage_guard', service)


if __name__ == '__main__':
    unittest.main()
