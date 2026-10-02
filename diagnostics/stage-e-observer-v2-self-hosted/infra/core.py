"""External observer infrastructure. Never copied into the reviewed assembly."""
import hashlib
import json
import os
from pathlib import Path
import time

S = '7a516a6a92be9347661ac0e7f560971c171a0931'
T = '9da7d1e1625ba04c1437c63606c90f5e293bdba7'
ASSEMBLY = '08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659'
MOUNT = Path('/mnt/volume_nyc1_1790918115030')
BASE = MOUNT/'meme-machine-observer-v2-7a516a6a'
PYTHON = '/workspace/stage-e-runtime/bin/python'
COHORT = [('combined-1',2223),('combined-2',2223),('combined-3',2223),('recovery-1',4445)]
MODES = ['baseline','observed','observed','baseline','baseline','observed']
REAL_NS = time.monotonic_ns
REAL_MONO = time.monotonic
PERF_NS = time.perf_counter_ns
INFRA = Path(__file__).resolve().parent


def canonical(row):
    return json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def persist(path,row):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    payload=canonical(row)+b'\n'
    temporary=path.with_name(path.name+'.tmp')
    with temporary.open('wb') as f:
        f.write(payload);f.flush();os.fsync(f.fileno())
    temporary.replace(path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return sha(payload)


def runtime_command(entry,*args):
    return [PYTHON,'-I','-S','-B','-X',f'pycache_prefix={BASE}/bytecode-disabled',str(INFRA/entry),*args]


def clean_env(params):
    environment=read(params)['environment']
    return dict(PATH='/usr/bin:/bin',LANG='C.UTF-8',TZ='UTC',MM_REAL_IPC_TESTS='1',
        LD_LIBRARY_PATH=str(Path(environment['stdlib']).parent),
        MM_OBSERVER_INFRA=str(INFRA),MM_OBSERVER_PARAMS=str(params),
        MM_OBSERVER_PARAMS_SHA=file_sha(params))


def storage():
    # Fixed headroom is checked before every member and recorded after each.
    if not MOUNT.is_mount():raise ValueError('persistent_volume_not_mounted')
    if (BASE/'bytecode-disabled').exists():raise ValueError('bytecode_cache_origin')
    disk=os.statvfs(MOUNT)
    row=dict(mount=str(MOUNT),device=os.stat(MOUNT).st_dev,
        free_bytes=disk.f_bavail*disk.f_frsize,total_bytes=disk.f_blocks*disk.f_frsize,
        required_free_bytes=12*1024**3)
    if row['free_bytes']<row['required_free_bytes']:raise ValueError('declared_disk_headroom')
    return row
