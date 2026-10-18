"""Bounded exact-SQLite3.45 source-acquisition A/B, not an AWS restore replay.

Run from the repository with --sqlite-library pointing at the authenticated
3.45.1 DSO and --output outside the disposable Scratch. The adapter exposes only
the sqlite APIs used by the actual reader; it never replaces production sqlite.
"""
import argparse
import ast
from contextlib import nullcontext
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine.operational.artifact_storage import Scratch
from meme_machine.runtime import candidate_restore_reads as pages
from operational.tests import network_guard

SOURCE = '780f4015efd9fba528e97223f8e8e3b1a7322e12'
LIBRARY_SHA256 = 'e6b6daa1908cc4ebb2a2275fd771c26ef13a23ace38f4681e4fcf7bb09075b09'


def source(path):
    return subprocess.check_output(['git', 'show', SOURCE + ':' + path], text=True)


def table(name, path):
    tree = ast.parse(source(path))
    value = next(ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
        and target.id == 'SCHEMA' for target in node.targets))
    found = re.search(r'CREATE TABLE IF NOT EXISTS ' + name + r'\([\s\S]*?\);', value)
    if found is None: raise ValueError('fixture_schema_missing')
    return found[0]


def method(path, class_name, name):
    tree = ast.parse(source(path))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)


def compile_method(node, globals):
    namespace = dict(globals)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<exact-source-method>', 'exec'), namespace)
    return namespace[node.name]


class Capture:
    def __init__(self): self.sql = []
    def execute(self, sql):
        if sql.startswith('SELECT 1 FROM sqlite_master'):
            return SimpleNamespace(fetchone=lambda: (1,))
        self.sql.append(sql)


def io():
    return {key: int(value) for key, value in (line.split(': ', 1) for line in
        Path('/proc/thread-self/io').read_text().splitlines())}


class SQLite345:
    """Single-threaded private C API owner, with original SQLite progress calls."""
    def __init__(self, library):
        if hashlib.sha256(library.read_bytes()).hexdigest() != LIBRARY_SHA256:
            raise ValueError('fixture_sqlite_library_hash')
        self.lib = ctypes.CDLL(str(library), mode=os.RTLD_NOW | os.RTLD_LOCAL | os.RTLD_DEEPBIND)
        self.P, self.I, self.T = ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p
        def api(name, result, *args):
            value = getattr(self.lib, 'sqlite3_' + name); value.restype = result; value.argtypes = list(args)
            return value
        P, I, T = self.P, self.I, self.T
        self.version = api('libversion', T)().decode()
        if self.version != '3.45.1': raise ValueError('fixture_sqlite_version')
        self.open = api('open_v2', I, T, ctypes.POINTER(P), I, T)
        self.close = api('close', I, P)
        self.prepare = api('prepare_v2', I, P, T, I, ctypes.POINTER(P), ctypes.POINTER(T))
        self.step = api('step', I, P); self.finalize = api('finalize', I, P)
        self.bind = api('bind_text', I, P, I, T, I, P)
        self.columns = api('column_count', I, P); self.kind = api('column_type', I, P, I)
        self.integer = api('column_int64', ctypes.c_longlong, P, I)
        self.value = api('column_blob', P, P, I); self.size = api('column_bytes', I, P, I)
        self.autocommit = api('get_autocommit', I, P)
        self.callback = ctypes.CFUNCTYPE(I, P)
        self.progress = api('progress_handler', None, P, I, self.callback, P)
        self.status = api('db_status', I, P, I, ctypes.POINTER(I), ctypes.POINTER(I), I)

    def connect(self, path, **unused):
        return Connection(self, Path(path.removeprefix('file:').split('?', 1)[0]))


class Cursor:
    def __init__(self, db, sql, args):
        self.db = db; self.handle = db.api.P()
        api = db.api
        if api.prepare(db.handle, sql.encode(), -1, ctypes.byref(self.handle), None):
            raise ValueError('fixture_prepare_failed')
        try:
            for index, arg in enumerate(args, 1):
                if api.bind(self.handle, index, arg.encode(), -1, api.P(-1)):
                    raise ValueError('fixture_bind_failed')
            # sqlite3.Connection.execute steps once before returning a cursor.
            # This is essential for real BEGIN/ROLLBACK and the same snapshot.
            self.first = self._advance()
            self.first_pending = True
        except BaseException:
            self.close(); raise

    def close(self):
        handle, self.handle = self.handle, None
        if handle: self.db.api.finalize(handle)

    def __del__(self): self.close()
    def __iter__(self): return self
    def __next__(self):
        if self.first_pending:
            self.first_pending = False
            row, self.first = self.first, None
        else:
            row = self._advance()
        if row is None: raise StopIteration
        return row

    def _advance(self):
        if not self.handle: return None
        api = self.db.api
        result = api.step(self.handle)
        if result == 101:
            self.close(); return None
        if result != 100:
            self.close()
            error = sqlite3.OperationalError('fixture_sqlite_step')
            error.sqlite_errorcode = result
            raise error
        row = []
        for index in range(api.columns(self.handle)):
            kind = api.kind(self.handle, index)
            if kind == 5: row.append(None)
            elif kind == 1: row.append(api.integer(self.handle, index))
            else:
                raw = ctypes.string_at(api.value(self.handle, index), api.size(self.handle, index))
                row.append(raw.decode() if kind == 3 else raw)
        return tuple(row)
    def fetchall(self): return list(self)
    def fetchone(self):
        try: return next(self)
        except StopIteration: return None


class Connection:
    def __init__(self, api, path):
        self.api = api; self.handle = api.P(); self.callback = None; self.queries = 0
        if api.open(os.fsencode(path), ctypes.byref(self.handle), 1, None):
            raise ValueError('fixture_readonly_open_failed')
        self.execute('PRAGMA query_only=ON').fetchall()
        self.execute('PRAGMA cache_size=-2048').fetchall()
    @property
    def in_transaction(self): return not self.api.autocommit(self.handle)
    def execute(self, sql, args=()):
        self.queries += 1
        return Cursor(self, sql, args)
    def set_progress_handler(self, callback, steps):
        self.callback = self.api.callback(lambda _: callback()) if callback is not None else self.api.callback()
        self.api.progress(self.handle, steps, self.callback, None)
    def cache(self):
        result = {}
        for name, code in (('hits', 7), ('misses', 8), ('writes', 9)):
            value, peak = self.api.I(), self.api.I()
            if self.api.status(self.handle, code, ctypes.byref(value), ctypes.byref(peak), 0):
                raise ValueError('fixture_cache_status')
            result[name] = value.value
        return result
    def close(self):
        if self.handle and self.api.close(self.handle): raise ValueError('fixture_close_failed')
        self.handle = None


def result_hash(items):
    result = []
    for item in items:
        row = item.row
        body = None if row[0] is None else dict(type=type(row[0]).__name__,
            sha256=hashlib.sha256(row[0].encode() if isinstance(row[0], str) else row[0]).hexdigest())
        result.append((item.identity, body, row[1:], item.manifest, item.fallback))
    return hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()


def run(library, output):
    network_guard(); os.environ['MM_OPERATION_COST_DIAGNOSTICS'] = '0'
    api = SQLite345(library)
    capture = Capture()
    compile_method(method('meme_machine/solana_rolling_history.py', 'RollingHistory', 'install_views'), {}) (
        SimpleNamespace(db=capture, history=SimpleNamespace(writer=SimpleNamespace(transaction=nullcontext))))
    view = next(sql for sql in capture.sql if sql.lstrip().startswith('CREATE VIEW canonical_evidence'))
    before = compile_method(method('meme_machine/runtime/candidate_restore_reads.py', 'RestoreReferenceReader', '_source_rows'), {})
    after = pages.RestoreReferenceReader._source_rows
    with Scratch() as scratch:
        path = scratch.path / 'canonical.sqlite'
        with sqlite3.connect(path) as db:
            for name, filename in (
                ('records', 'meme_machine/solana_evidence_plane.py'),
                ('shared_history_cache', 'meme_machine/solana_selective_history.py'),
                ('rolling_economic_events', 'meme_machine/solana_rolling_history.py'),
                ('scoped_cold_records', 'meme_machine/solana_scoped_retirement.py')):
                db.execute(table(name, filename))
            db.execute('CREATE TABLE scoped_cold_manifests(id TEXT PRIMARY KEY,path TEXT,hash TEXT)')
            db.execute(view)
            for key, body in (('rich-blob', b'x' * (8 * 1024 * 1024)),
                              ('rich-text', '\u2603' * (8 * 1024 * 1024 // 3)), ('cold', None)):
                db.execute('INSERT INTO rolling_economic_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (key, 'program:pump', 100, 'sig', 'program', 100, 0, 0, 'event', body,
                     'f' * 64, 100., 'manifest' if body is None else None))
            db.execute('INSERT INTO scoped_cold_manifests VALUES(?,?,?)', ('manifest', '/fixture/cold.zlib', 'a' * 64))
        fixture_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        ids = ['rich-blob', 'rich-text', 'cold'] * 42 + ['rich-blob', 'cold']
        history = SimpleNamespace(_reference_path=lambda _: path)
        results = []
        for label, acquire in (('before', before), ('after', after), ('after_warm', after), ('before_warm', before)):
            with patch.object(pages, 'connect', api.connect), pages.RestoreReferenceReader(history, lambda:False, {}) as reader:
                db = reader._database(path)
                items = [pages._Lookup(reader, 'pump', 'candidate', str(n), 'pump_transaction',
                    dict(path=str(path), canonical_identity=key)) for n, key in enumerate(ids)]
                started_io = io(); started_cpu = time.thread_time(); started = time.monotonic()
                remaining = acquire(reader, items, pages.PAGE_BYTES)
                wall = time.monotonic() - started; cpu = time.thread_time() - started_cpu
                ended_io = io()
                results.append(dict(label=label, wall_seconds=wall, thread_cpu_seconds=cpu,
                    thread_io_delta={key: ended_io[key] - value for key, value in started_io.items()},
                    pager=db.cache(), queries=db.queries, remaining_bytes=remaining,
                    output_sha256=result_hash(items), snapshot_released=not db.in_transaction))
            scratch.check()
        if len({row['output_sha256'] for row in results}) != 1: raise ValueError('fixture_acquisition_changed')
        if len({row['remaining_bytes'] for row in results}) != 1: raise ValueError('fixture_budget_changed')
        if hashlib.sha256(path.read_bytes()).hexdigest() != fixture_hash: raise ValueError('fixture_changed')
        receipt = dict(schema='pump-source-metadata-345-cost-v1', baseline_source=SOURCE,
            source_view_sha256=hashlib.sha256(view.encode()).hexdigest(),
            reader_sha256=hashlib.sha256(Path(pages.__file__).read_bytes()).hexdigest(),
            probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            sqlite_version=api.version, library_sha256=LIBRARY_SHA256, file_bytes=path.stat().st_size,
            fixture_sha256=fixture_hash, references=len(ids), unique_keys=len(set(ids)), results=results,
            scope='EXACT_SOURCE_ACQUISITION_SYNTHETIC_RICH_BODY_COLD_METADATA_NOT_NATIVE_DECODE_OR_AWS_PARITY',
            same_outputs=True, same_budget=True, fixture_unchanged=True,
            provider_requests=0, authoritative_writes=0, actual_retained_geometry_reproduced=False,
            actual_fallback_frequency_verified=False, physical_cache_cold_proven=False)
        output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
        scratch.check(); scratch.success = True
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sqlite-library', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.sqlite_library.resolve(), args.output.resolve())
