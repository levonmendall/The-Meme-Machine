"""Bounded, payload-free diagnostics for offline evidence pressure only.

No SQL text, paths, arguments, credentials or record bodies are retained.
Wall versus thread CPU separates storage/scheduling stalls from SQL CPU.
"""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import collections
import os
import resource
import sqlite3
import threading
import time


def environment(path):
    result = {'sqlite_version': sqlite3.sqlite_version}
    for label, filename in (
        ('process_io', '/proc/self/io'), ('memory', '/proc/meminfo'),
        ('process_status', '/proc/self/status'),
    ):
        try:
            allowed = {
                'rchar', 'wchar', 'syscr', 'syscw', 'read_bytes', 'write_bytes',
                'cancelled_write_bytes', 'MemAvailable', 'Dirty', 'Writeback',
                'Cached', 'VmRSS', 'VmHWM', 'Threads', 'FDSize',
            }
            result[label] = {key: int(value.strip().split()[0])
                for line in Path(filename).read_text().splitlines() if ':' in line
                for key, value in [line.split(':', 1)] if key in allowed}
        except (OSError, ValueError):
            result[label] = None
    for label, filename in (
        ('cpu_stat', '/sys/fs/cgroup/cpu.stat'),
        ('memory_current', '/sys/fs/cgroup/memory.current'),
        ('memory_max', '/sys/fs/cgroup/memory.max'),
        ('io_pressure', '/proc/pressure/io'),
        ('cpu_pressure', '/proc/pressure/cpu'),
        ('memory_pressure', '/proc/pressure/memory'),
    ):
        try:
            result[label] = Path(filename).read_text()[:1024].strip()
        except OSError:
            result[label] = None
    try:
        result['open_fds'] = len(list(Path('/proc/self/fd').iterdir()))
    except OSError:
        result['open_fds'] = None
    disk = os.statvfs(path)
    result['disk'] = dict(free_bytes=disk.f_bavail * disk.f_frsize,
                          total_bytes=disk.f_blocks * disk.f_frsize)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result['process'] = dict(user=usage.ru_utime, system=usage.ru_stime,
        minor_faults=usage.ru_minflt, major_faults=usage.ru_majflt,
        block_input=usage.ru_inblock, block_output=usage.ru_oublock,
        voluntary_switches=usage.ru_nvcsw, involuntary_switches=usage.ru_nivcsw)
    return result


def statement_class(sql):
    # Never normalize or time each record's INSERT/DELETE. Millions of timing
    # calls can become the measured contention rather than reveal its cause.
    if sql.startswith('PRAGMA wal_checkpoint'): return 'checkpoint'
    if sql.startswith('PRAGMA incremental_vacuum'): return 'vacuum'
    if sql in ('COMMIT', 'END'): return 'commit'
    if sql.startswith('SELECT MIN(COALESCE(market_time,first_seen)) FROM records'):
        return 'observer_retained_min'
    if sql.startswith('SELECT COALESCE(market_time,first_seen) FROM records'):
        return 'observer_hot_min'
    return None


class SQLTimings:
    def __init__(self, *, commit_latency_seconds=0):
        if not 0 <= commit_latency_seconds <= .1:
            raise ValueError('diagnostic_commit_latency_bound')
        self.commit_latency_seconds = commit_latency_seconds
        self.rows = collections.defaultdict(lambda: dict(calls=0, wall_us=0,
            cpu_us=0, peak_wall_us=0, errors=0))
        self.lock = threading.Lock()

    def measure(self, label, operation):
        start = time.monotonic_ns(); cpu = time.thread_time_ns(); failed = False
        try:
            return operation()
        except BaseException:
            failed = True
            raise
        finally:
            wall_us = (time.monotonic_ns() - start) // 1000
            cpu_us = (time.thread_time_ns() - cpu) // 1000
            with self.lock:
                row = self.rows[label]
                row['calls'] += 1; row['wall_us'] += wall_us; row['cpu_us'] += cpu_us
                row['peak_wall_us'] = max(row['peak_wall_us'], wall_us)
                row['errors'] += int(failed)

    def snapshot(self):
        with self.lock: return {k: dict(v) for k, v in self.rows.items()}

    @contextmanager
    def enabled(self):
        timings = self
        native_connect = sqlite3.connect

        class TimedConnection(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                if timings.commit_latency_seconds:
                    if sql.startswith('BEGIN'):
                        self.diagnostic_begin_changes = self.total_changes
                    elif sql == 'COMMIT' and self.total_changes != getattr(
                            self, 'diagnostic_begin_changes', self.total_changes):
                        timings.measure('injected_commit_wait',
                            lambda: time.sleep(timings.commit_latency_seconds))
                label=statement_class(sql)
                if label is None:
                    return super().execute(sql,*args,**kwargs)
                return timings.measure(label,
                    lambda: super(TimedConnection, self).execute(sql, *args, **kwargs))

        def connect(*args, **kwargs):
            kwargs.setdefault('factory', TimedConnection)
            return native_connect(*args, **kwargs)

        from meme_machine.solana_evidence_service import ServiceState
        storage_stage=ServiceState._storage_stage
        source_batch=ServiceState.source_batch
        health=ServiceState.publish_health
        def storage(state,name,fn):
            return timings.measure('stage_'+name,lambda:storage_stage(state,name,fn))
        def source(state,items):
            return timings.measure('stage_source',lambda:source_batch(state,items))
        def publish(state,*args):
            return timings.measure('stage_health',lambda:health(state,*args))
        with patch('sqlite3.connect', connect), \
             patch.object(ServiceState,'_storage_stage',storage), \
             patch.object(ServiceState,'source_batch',source), \
             patch.object(ServiceState,'publish_health',publish):
            yield self
