"""Read-only Linux mount and existing PAPER inception check, before any writer."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess

DEFAULT_CONFIG = '/etc/meme-machine/storage.json'


class StorageGuardError(RuntimeError):
    pass


def device_identity(path):
    device = os.stat(path)
    if not stat.S_ISBLK(device.st_mode):
        raise StorageGuardError('persistent_volume_device_unavailable')
    return str(os.major(device.st_rdev)) + ':' + str(os.minor(device.st_rdev))


def bounded_json(path, limit=16384):
    with Path(path).open('rb') as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise StorageGuardError('storage_identity_bound')
    return json.loads(body)


def verify_storage(root, config=None):
    """Never mkdir, open a writer, migrate a schema, or initialize an epoch."""
    try:
        path = Path(config or os.environ.get('MM_STORAGE_GUARD_CONFIG', DEFAULT_CONFIG))
        permissions = path.stat()
        if permissions.st_uid != 0 or permissions.st_mode & 0o022:
            raise StorageGuardError('storage_configuration_permissions')
        expected = bounded_json(path)
        if set(expected) != {'mount_target', 'state_root', 'filesystem_uuid', 'volume_device',
                             'epoch_id', 'inception_sha256'}:
            raise StorageGuardError('storage_configuration_shape')
        root = Path(root)
        mount = Path(expected['mount_target'])
        if (not root.is_absolute() or str(root) != expected['state_root'] or
                root.resolve() != root or mount.resolve() != mount or
                mount not in root.parents):
            raise StorageGuardError('unexpected_state_path')
        # The kernel's mounted filesystem identity is required, not the presence
        # of a directory left on the root disk underneath an absent volume.
        response = subprocess.run(
            ['findmnt', '--json', '--target', str(root), '--output',
             'TARGET,FSTYPE,UUID,OPTIONS,MAJ:MIN'], capture_output=True, check=True,
            timeout=5, text=True)
        if len(response.stdout) > 16384:
            raise StorageGuardError('storage_mount_response_bound')
        rows = json.loads(response.stdout)['filesystems']
        if (len(rows) != 1 or rows[0]['target'] != str(mount) or
                rows[0]['uuid'] != expected['filesystem_uuid'] or
                rows[0]['maj:min'] != device_identity(expected['volume_device']) or
                rows[0]['fstype'] != 'ext4' or
                'rw' not in rows[0]['options'].split(',')):
            raise StorageGuardError('expected_persistent_volume_not_mounted')
        database = root / 'portfolio.sqlite'
        if not root.is_dir() or not database.is_file() or database.is_symlink():
            raise StorageGuardError('existing_portfolio_required')
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            db.execute('PRAGMA query_only=ON')
            row = db.execute('SELECT body,sha256 FROM portfolio_inception WHERE id=1').fetchone()
        if row is None:
            raise StorageGuardError('existing_portfolio_inception_required')
        receipt = json.loads(row[0])
        checksum = hashlib.sha256(json.dumps(receipt, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if (receipt.get('epoch_id') != expected['epoch_id'] or
                not expected['epoch_id'].startswith('paper-') or
                receipt.get('paper_only') is not True or
                row[1] != checksum or checksum != expected['inception_sha256']):
            raise StorageGuardError('existing_PAPER_epoch_identity_mismatch')
        return dict(epoch_id=expected['epoch_id'], inception_sha256=checksum,
                    mount_target=str(mount), filesystem_uuid=expected['filesystem_uuid'])
    except StorageGuardError:
        raise
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error,
            subprocess.SubprocessError):
        # Never expose environment values, third-party output, or secret URLs.
        raise StorageGuardError('storage_identity_unavailable') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=None)
    parser.add_argument('--state-root', default=os.environ.get('MM_STATE_ROOT'))
    args = parser.parse_args()
    if not args.state_root:
        parser.error('MM_STATE_ROOT is required')
    try:
        result = verify_storage(args.state_root, args.config)
    except StorageGuardError as error:
        print(json.dumps(dict(passed=False, reason=str(error))))
        return 1
    print(json.dumps(dict(passed=True, **result), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
