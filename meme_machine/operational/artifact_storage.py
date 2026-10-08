"""Disk admission for engineering artifacts, separate from native PAPER safety."""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

GIB = 1024**3


class ArtifactStorageFull(RuntimeError):
    pass


@dataclass(frozen=True)
class Policy:
    warn_percent: float = 75
    block_percent: float = 85
    min_free_bytes: int = 5 * GIB
    scratch_max_bytes: int = GIB
    scratch_total_bytes: int = 2 * GIB
    snapshot_max_bytes: int = 2 * GIB
    snapshot_total_bytes: int = 4 * GIB

    @classmethod
    def environment(cls):
        value = cls(**{field: convert(os.environ.get(name, default)) for field, name, convert, default in (
            ('warn_percent', 'MM_STORAGE_WARN_PERCENT', float, 75),
            ('block_percent', 'MM_STORAGE_BLOCK_PERCENT', float, 85),
            ('min_free_bytes', 'MM_STORAGE_MIN_FREE_BYTES', int, 5 * GIB),
            ('scratch_max_bytes', 'MM_ENGINEERING_SCRATCH_MAX_BYTES', int, GIB),
            ('scratch_total_bytes', 'MM_ENGINEERING_SCRATCH_TOTAL_BYTES', int, 2 * GIB),
            ('snapshot_max_bytes', 'MM_ENGINEERING_SNAPSHOT_MAX_BYTES', int, 2 * GIB),
            ('snapshot_total_bytes', 'MM_ENGINEERING_SNAPSHOT_TOTAL_BYTES', int, 4 * GIB))})
        if not 0 < value.warn_percent < value.block_percent < 100 or any(
                getattr(value, field) <= 0 for field in ('min_free_bytes', 'scratch_max_bytes',
                'scratch_total_bytes', 'snapshot_max_bytes', 'snapshot_total_bytes')):
            raise ValueError('invalid_engineering_storage_policy')
        if value.scratch_max_bytes > value.scratch_total_bytes or value.snapshot_max_bytes > value.snapshot_total_bytes:
            raise ValueError('invalid_engineering_storage_quota')
        return value


def existing_parent(path):
    path = Path(path).absolute()
    while not path.exists():
        path = path.parent
    return path


def usage(path):
    path = existing_parent(path)
    fs = os.statvfs(path)
    used = (fs.f_blocks - fs.f_bfree) * fs.f_frsize
    free = fs.f_bavail * fs.f_frsize
    return dict(used_bytes=used, free_bytes=free, total_bytes=used + free,
                percent_used=100 * used / (used + free) if used + free else 100,
                device=path.stat().st_dev)


def tree_bytes(root, *, limit=None, reject_links=False):
    """Count allocation conservatively without following any symlinks."""
    total = 0
    entries = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            p = Path(directory) / name
            info = p.lstat()
            entries += 1
            if entries > 100000:
                raise ArtifactStorageFull('engineering_inventory_entry_bound')
            if stat.S_ISLNK(info.st_mode):
                if reject_links:
                    raise ValueError('engineering_snapshot_symlink_forbidden')
                continue
            if stat.S_ISREG(info.st_mode):
                total += max(info.st_size, info.st_blocks * 512)
            if limit is not None and total > limit:
                raise ArtifactStorageFull('engineering_artifact_byte_quota')
    return total


def headroom(destination, estimated_bytes=0, *, nonessential=True, policy=None, warn=True):
    policy = policy or Policy.environment()
    if isinstance(estimated_bytes, bool) or not isinstance(estimated_bytes, int) or estimated_bytes < 0:
        raise ValueError('engineering_copy_estimate_required')
    root = usage('/')
    target = usage(destination)
    if warn and root['percent_used'] >= policy.warn_percent:
        print('STORAGE WARNING: root %.1f%% used; %.2f GiB available; '
              'nonessential bulk operations block at %.1f%%.' %
              (root['percent_used'], root['free_bytes'] / GIB, policy.block_percent), file=sys.stderr)
    projected = root['used_bytes'] + (estimated_bytes if root['device'] == target['device'] else 0)
    if nonessential and (100 * projected / root['total_bytes'] >= policy.block_percent or
                         root['free_bytes'] < policy.min_free_bytes):
        raise ArtifactStorageFull('root_headroom_blocks_nonessential_artifact')
    if target['free_bytes'] < estimated_bytes + policy.min_free_bytes:
        raise ArtifactStorageFull('destination_copy_reserve_required')
    return dict(root=root, destination=target, estimated_bytes=estimated_bytes)


def admit_snapshot(root, parent, *, nonessential=True, policy=None):
    policy = policy or Policy.environment()
    estimate = tree_bytes(root, reject_links=True)
    if nonessential:
        if estimate > policy.snapshot_max_bytes:
            raise ArtifactStorageFull('engineering_snapshot_per_copy_quota')
        retained = tree_bytes(parent, limit=policy.snapshot_total_bytes) if Path(parent).exists() else 0
        if retained + estimate > policy.snapshot_total_bytes:
            raise ArtifactStorageFull('engineering_snapshot_retained_quota')
    headroom(parent, estimate, nonessential=nonessential, policy=policy)
    return estimate


def storage_conditions(sample, policy=None):
    policy = policy or Policy.environment()
    found = set()
    for path, disk in sample.get('host', {}).get('disks', {}).items():
        if path == '/' and disk.get('percent_used', 0) >= policy.warn_percent:
            found.add('storage_warning')
        if disk.get('percent_used', 0) >= policy.block_percent or disk.get('free_bytes', 0) < policy.min_free_bytes:
            found.add('storage_exhaustion_risk')
    return found


class Scratch:
    """Owned offline fixtures only. Successful scopes clean; failures retain evidence."""
    def __init__(self, parent=None, *, policy=None):
        self.policy = policy or Policy.environment()
        self.parent = Path(parent or os.environ.get('MM_ENGINEERING_TMPDIR', tempfile.gettempdir()))
        self.path = None
        self.success = False

    def __enter__(self):
        retained = 0
        for folder in self.parent.glob('mm-engineering-*'):
            if folder.is_symlink() or not folder.is_dir():
                continue
            # Unknown prefix matches are preserved and still count against quota.
            retained += tree_bytes(folder, limit=self.policy.scratch_total_bytes)
        if retained + self.policy.scratch_max_bytes > self.policy.scratch_total_bytes:
            raise ArtifactStorageFull('engineering_scratch_retained_quota')
        headroom(self.parent, self.policy.scratch_max_bytes, policy=self.policy)
        self.path = Path(tempfile.mkdtemp(prefix='mm-engineering-', dir=self.parent))
        self.previous_env = os.environ.get('TMPDIR')
        self.previous_tempdir = tempfile.tempdir
        os.environ['TMPDIR'] = str(self.path)
        tempfile.tempdir = str(self.path)
        self.mark('RUNNING')
        return self

    def mark(self, status):
        (self.path / 'engineering-artifact.json').write_text(json.dumps(dict(
            classification='DISPOSABLE_OFFLINE_FIXTURE', status=status,
            pid=os.getpid(), max_bytes=self.policy.scratch_max_bytes,
            purpose='offline tests only; never authoritative PAPER or recovery snapshots')) + '\n')

    def check(self):
        used=tree_bytes(self.path, limit=self.policy.scratch_max_bytes)
        headroom(self.path,max(0,self.policy.scratch_max_bytes-used),policy=self.policy,warn=False)

    def __exit__(self, kind, value, traceback):
        tempfile.tempdir = self.previous_tempdir
        if self.previous_env is None:
            os.environ.pop('TMPDIR', None)
        else:
            os.environ['TMPDIR'] = self.previous_env
        if kind is None and self.success:
            self.mark('VERIFIED_DISPOSABLE')
            shutil.rmtree(self.path)  # Only this newly created successful fixture scope.
        else:
            self.mark('FAILED_EVIDENCE_RETAINED')
            print('Offline failure evidence retained at ' + str(self.path), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--bytes', type=int)
    group.add_argument('--source', type=Path)
    args = parser.parse_args()
    try:
        estimate = args.bytes if args.source is None else tree_bytes(args.source, reject_links=True)
        policy = Policy.environment()
        if estimate > policy.snapshot_max_bytes:
            raise ArtifactStorageFull('engineering_snapshot_per_copy_quota')
        print(json.dumps(headroom(args.destination, estimate, policy=policy), sort_keys=True))
    except (OSError, ValueError, ArtifactStorageFull) as error:
        print(json.dumps(dict(passed=False, reason=str(error))), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
