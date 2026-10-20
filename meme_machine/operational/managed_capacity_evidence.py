"""Private, bounded evidence for fresh-generation managed capacity work.

This module opens no provider and grants no operational/financial authority.
Hash chains establish integrity; the protected host must independently attest
their provenance. A self-consistent local file is never an authenticated run.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

SCHEMA = 'managed-capacity-evidence-v1'
MAX_ROW = 2 * 1024**2
MAX_PART = 16 * 1024**2
MAX_TOTAL = 64 * 1024**2


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def write_all(fd, raw):
    offset = 0
    while offset < len(raw):
        count = os.write(fd, raw[offset:])
        if count <= 0:
            raise ValueError('capacity_short_write')
        offset += count


def atomic_json(path, value):
    path = Path(path)
    raw = canonical(value) + b'\n'
    if len(raw) > MAX_ROW:
        raise ValueError('capacity_record_bound')
    temporary = path.with_name(path.name + '.new')
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def private_directory(path, *, empty=False):
    path = Path(path).absolute()
    if path.resolve() != path:
        raise ValueError('capacity_directory_link')
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError('capacity_private_directory_required')
    if empty and any(path.iterdir()):
        raise ValueError('capacity_fresh_generation_required')
    return path


class Evidence:
    """One owner, create-only parts, fsync before acknowledging each sample."""
    def __init__(self, root, generation):
        self.root = private_directory(root)
        if type(generation) is not str or re.fullmatch('[0-9a-f]{32}', generation) is None:
            raise ValueError('capacity_generation_identity')
        self.generation = generation
        self.sequence = self.total = self.part_bytes = 0
        self.previous = '0' * 64
        self.parts = []
        self.fd = None
        self.closed = False

    def append(self, kind, value):
        if self.closed:
            raise ValueError('capacity_evidence_closed')
        body = dict(schema=SCHEMA, generation=self.generation, sequence=self.sequence + 1,
                    previous_sha256=self.previous, kind=kind, value=value)
        digest = hashlib.sha256(canonical(body)).hexdigest()
        raw = canonical(dict(body, row_sha256=digest)) + b'\n'
        if len(raw) > MAX_ROW or self.total + len(raw) > MAX_TOTAL:
            raise ValueError('capacity_evidence_bound')
        if self.fd is None or self.part_bytes + len(raw) > MAX_PART:
            self._close_part()
            path = self.root / ('evidence-%04d.jsonl' % len(self.parts))
            self.fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            self.parts.append(dict(name=path.name, bytes=0, rows=0))
            self.part_bytes = 0
        write_all(self.fd, raw)
        os.fsync(self.fd)
        self.sequence += 1
        self.previous = digest
        self.total += len(raw)
        self.part_bytes += len(raw)
        self.parts[-1]['bytes'] += len(raw)
        self.parts[-1]['rows'] += 1

    def _close_part(self):
        if self.fd is not None:
            os.fsync(self.fd)
            os.close(self.fd)
            self.fd = None
            path = self.root / self.parts[-1]['name']
            self.parts[-1]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

    def close(self):
        if self.closed:
            return
        self._close_part()
        self.closed = True
        atomic_json(self.root / 'evidence-manifest.json', dict(schema=SCHEMA,
            generation=self.generation, rows=self.sequence, bytes=self.total,
            terminal_sha256=self.previous, parts=self.parts,
            provenance_authenticated=False, financial_authority=False))


def read_json(path):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ROW or info.st_uid != os.geteuid():
            raise ValueError('capacity_record_identity')
        raw = os.read(fd, MAX_ROW + 1)
    finally:
        os.close(fd)
    if len(raw) != info.st_size:
        raise ValueError('capacity_record_changed')
    return json.loads(raw)


def verify(root, generation):
    """Check sealed parts in order without loading the whole observation."""
    root = private_directory(root)
    manifest = read_json(root / 'evidence-manifest.json')
    if (type(manifest) is not dict or manifest.get('schema') != SCHEMA
            or manifest.get('generation') != generation
            or manifest.get('provenance_authenticated') is not False
            or manifest.get('financial_authority') is not False
            or type(manifest.get('parts')) is not list or len(manifest['parts']) > 64):
        raise ValueError('capacity_manifest_identity')
    previous = '0' * 64
    total = sequence = 0
    names = []
    for index, part in enumerate(manifest['parts']):
        name = 'evidence-%04d.jsonl' % index
        if (type(part) is not dict or part.get('name') != name
                or type(part.get('bytes')) is not int or not 0 < part['bytes'] <= MAX_PART
                or type(part.get('rows')) is not int or not 0 < part['rows'] <= 65536):
            raise ValueError('capacity_part_identity')
        names.append(name)
        fd = os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW)
        digest = hashlib.sha256()
        size = rows = 0
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size != part['bytes']
                    or info.st_uid != os.geteuid()):
                raise ValueError('capacity_part_identity')
            while True:
                raw = handle.readline(MAX_ROW + 1)
                if not raw:
                    break
                if len(raw) > MAX_ROW or not raw.endswith(b'\n'):
                    raise ValueError('capacity_row_bound')
                row = json.loads(raw)
                row_hash = row.pop('row_sha256')
                if (set(row) != {'schema', 'generation', 'sequence', 'previous_sha256', 'kind', 'value'}
                        or row['schema'] != SCHEMA or row['generation'] != generation
                        or row['sequence'] != sequence + 1 or row['previous_sha256'] != previous
                        or hashlib.sha256(canonical(row)).hexdigest() != row_hash):
                    raise ValueError('capacity_row_integrity')
                digest.update(raw)
                sequence += 1
                rows += 1
                size += len(raw)
                total += len(raw)
                previous = row_hash
                if total > MAX_TOTAL:
                    raise ValueError('capacity_evidence_bound')
        if size != part['bytes'] or rows != part['rows'] or digest.hexdigest() != part['sha256']:
            raise ValueError('capacity_part_integrity')
    if sorted(p.name for p in root.glob('evidence-*.jsonl')) != names:
        raise ValueError('capacity_unlisted_part')
    if (manifest.get('rows') != sequence or manifest.get('bytes') != total
            or manifest.get('terminal_sha256') != previous):
        raise ValueError('capacity_manifest_integrity')
    return dict(integrity_verified=True, provenance_authenticated=False,
                rows=sequence, bytes=total, terminal_sha256=previous)


def host_sample(pids=()):
    """Kernel counters only; never read process command lines or environments."""
    result = dict(monotonic=time.monotonic(), wall=time.time(), processes={})
    result['cpu_ticks'] = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:]]
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            memory[key] = int(value.split()[0]) * 1024
    result['memory_bytes'] = memory
    result['diskstats'] = Path('/proc/diskstats').read_text().splitlines()
    result['network_counters'] = Path('/proc/net/dev').read_text().splitlines()[2:]
    fs = os.statvfs('/')
    result['root_disk'] = dict(free_bytes=fs.f_bavail * fs.f_frsize,
        used_bytes=(fs.f_blocks - fs.f_bfree) * fs.f_frsize)
    for pid in pids:
        try:
            process = Path('/proc') / str(pid)
            fields = (process / 'stat').read_text().rpartition(')')[2].split()
            io = dict((key, int(value)) for key, value in
                      (line.split(':', 1) for line in (process / 'io').read_text().splitlines()))
            result['processes'][str(pid)] = dict(start_ticks=int(fields[19]),
                user_ticks=int(fields[11]), system_ticks=int(fields[12]),
                rss_bytes=int(fields[21]) * os.sysconf('SC_PAGE_SIZE'), io=io)
        except (FileNotFoundError, ProcessLookupError):
            result['processes'][str(pid)] = dict(exited=True)
    return result
