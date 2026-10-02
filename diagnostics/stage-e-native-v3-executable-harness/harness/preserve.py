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
