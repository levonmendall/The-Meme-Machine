"""Fsynced, exclusive evidence, exact inventories and verified redundant copies."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import shutil
import stat

from core import canonical, file_sha, read, relative, require, sha


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def persist(path, value):
    """Every receipt is immutable; a duplicate name is an error, never replacement."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(value) + b'\n'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
    finally:
        fsync_dir(path.parent)
    require(file_sha(path) == sha(data), 'receipt_readback_mismatch')
    return sha(data)


@contextmanager
def lock(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def inventory(root, *, exclude=()):
    root = Path(root).resolve()
    rows = []
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'evidence_symlink')
        name = path.relative_to(root).as_posix()
        if name in exclude:
            continue
        if path.is_file():
            mode = path.stat().st_mode
            require(stat.S_ISREG(mode), 'nonregular_evidence')
            with path.open('rb') as source:
                os.fsync(source.fileno())
            rows.append(dict(path=name, bytes=path.stat().st_size, sha256=file_sha(path)))
        elif not path.is_dir():
            raise ValueError('live_socket_or_special_file_in_evidence:' + name)
    for path in sorted((p for p in root.rglob('*') if p.is_dir()), reverse=True):
        fsync_dir(path)
    fsync_dir(root)
    return rows


def seal(root, *, name='RAW_INVENTORY.json'):
    rows = inventory(root, exclude=(name,))
    persist(Path(root) / name, dict(version='v3-preserved-raw-inventory', artifacts=rows,
                                  sole_copy_deleted=False))
    verify_inventory(root, name=name)
    return file_sha(Path(root) / name)


def verify_inventory(root, *, name='RAW_INVENTORY.json'):
    record = read(Path(root) / name)
    require(record['artifacts'] == inventory(root, exclude=(name,)), 'raw_evidence_inventory_mismatch')
    require(record['sole_copy_deleted'] is False, 'evidence_deletion')
    return record


def redundant_copy(root, destination, *, name='RAW_INVENTORY.json'):
    """Never remove the local copy. Publication/receipt runs outside B timing."""
    verify_inventory(root,name=name)
    destination = Path(destination)
    require(not destination.exists(), 'publication_destination_reused')
    required = sum(row['bytes'] for row in inventory(root))
    disk = os.statvfs(destination.parent)
    require(disk.f_bavail * disk.f_frsize >= required, 'publication_copy_space')
    shutil.copytree(root, destination, symlinks=False)
    require(inventory(root) == inventory(destination), 'publication_readback_bytes')
    verify_inventory(destination,name=name)
    return dict(destination=str(destination), inventory_sha256=file_sha(destination / name),
                local_copy_retained=True, independently_read_back=True)


def abandoned_ipc(root, termination):
    """Remove only known, abandoned native sockets after the entire tree exits.

    Regular evidence (including DB, WAL and logs) is never removed. Unknown
    special artifacts still refuse an acceptance seal and are recorded by the
    failure-only copier.
    """
    require(termination.get('all_native_helpers_terminated') is True
            and termination.get('trial_process_terminated') is True,
            'IPC_cleanup_requires_confirmed_process_termination')
    root = Path(root)
    removed = []
    for member in sorted(root.glob('m[0-9]*')):
        path = member/'d/db.sock'
        if not path.exists():
            continue
        require(not member.is_symlink() and not path.parent.is_symlink(), 'IPC_parent_symlink')
        info = path.lstat()
        require(stat.S_ISSOCK(info.st_mode), 'abandoned_IPC_is_not_socket')
        removed.append(dict(path=path.relative_to(root).as_posix(), device=info.st_dev,
                            inode=info.st_ino, mode=info.st_mode))
    # Durable intent precedes unlink; the socket itself contains no regular-file
    # evidence. Never silently exclude it from an acceptance inventory.
    if removed:
        persist(root/'ABANDONED_IPC.json', dict(termination=termination, artifacts=removed,
                regular_evidence_deleted=False, native_safety_credit=False))
        for item in removed:
            path = root/item['path']
            info = path.lstat()
            require(stat.S_ISSOCK(info.st_mode) and info.st_ino == item['inode']
                    and info.st_dev == item['device'], 'abandoned_IPC_changed_before_cleanup')
            path.unlink()
            fsync_dir(path.parent)
    return removed


def regular_evidence(root):
    """Failure inventory: enumerate every regular file without following links."""
    root = Path(root).resolve()
    rows, specials = [], []
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in sorted(folders + files):
            path = Path(directory)/name
            info = path.lstat()
            relative_name = path.relative_to(root).as_posix()
            if stat.S_ISREG(info.st_mode):
                with path.open('rb') as source:
                    os.fsync(source.fileno())
                rows.append(dict(path=relative_name, bytes=info.st_size, sha256=file_sha(path)))
            elif not stat.S_ISDIR(info.st_mode):
                specials.append(dict(path=relative_name, mode=info.st_mode,
                                     device=info.st_dev, inode=info.st_ino))
    return sorted(rows, key=lambda r:r['path']), sorted(specials, key=lambda r:r['path'])


def failure_copy(root, destination):
    """Publish all regular failure bytes even when a strict seal is impossible.

    This copy explicitly denies acceptance. Unsupported IPC/links/special files
    stay in the retained local directory and are itemized, never dereferenced.
    """
    root, destination = Path(root).resolve(), Path(destination)
    require(not destination.exists(), 'publication_destination_reused')
    rows, specials = regular_evidence(root)
    destination.mkdir(exist_ok=False)
    for item in rows:
        source, target = relative(root, item['path']), relative(destination, item['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as reader, target.open('xb') as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush(); os.fsync(writer.fileno())
        require(target.stat().st_size == item['bytes'] and file_sha(target) == item['sha256'],
                'failure_publication_readback_bytes')
    require(regular_evidence(root) == (rows, specials), 'failure_evidence_changed_during_copy')
    require(inventory(destination) == rows, 'failure_publication_regular_inventory')
    persist(destination/'FAILURE_COPY_RECEIPT.json', dict(version='v3-failure-only-preservation',
        artifacts=rows, nonregular_artifacts_retained_locally=specials, local_copy_retained=True,
        independently_read_back=True, native_safety_credit=False, acceptance_credit=False))
    fsync_dir(destination.parent)
    return dict(destination=str(destination), local_copy_retained=True,
                independently_read_back=True, acceptance_credit=False,
                receipt_sha256=file_sha(destination/'FAILURE_COPY_RECEIPT.json'))
