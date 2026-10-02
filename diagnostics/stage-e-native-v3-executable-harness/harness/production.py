"""A and B native production adapter. Contains no run381 contention imports.

The service owns the unchanged two-worker pool, single archive flight, source
transactions, archive preparation, fsync, retirement and local IPC. The adapter
supplies immutable input bytes, real cadence and the approved common reads.
"""
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time
import traceback
from unittest.mock import patch

import bound_runtime as bound
from core import REAL_NS, S, canonical, file_sha, require, sha, workload
from preserve import persist
from tape import Reader

SCOPES = ('program:meteora', 'program:pump', 'program:pumpswap')
ENDPOINT = 'https://solana-mainnet.g.alchemy.com/v2/offline-test'


def read_snapshot(path):
    if not Path(path).exists():
        return None
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, isolation_level=None)) as db:
        db.execute('PRAGMA query_only=ON')
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'records', 'counters', 'service_health', 'gaps', 'meta'}.issubset(names):
            return None
        db.execute('BEGIN')
        try:
            counters = dict(db.execute('SELECT key,value FROM counters'))
            health = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM service_health')}
            hot = db.execute('SELECT MIN(COALESCE(market_time,first_seen)) FROM records WHERE body IS NOT NULL').fetchone()[0]
            retained = db.execute('SELECT MIN(COALESCE(market_time,first_seen)) FROM records INDEXED BY records_scope_time').fetchone()[0]
            gaps = [list(r) for r in db.execute('SELECT scope,lo,hi,reason FROM gaps WHERE repaired IS NULL ORDER BY scope,lo')]
            floors = dict(db.execute("SELECT key,value FROM meta WHERE key LIKE 'retention_floor:%'"))
            progress = [list(r) for r in db.execute('SELECT * FROM maintenance_progress ORDER BY scope,side')]
            episodes = [list(r) for r in db.execute('SELECT * FROM maintenance_episodes ORDER BY scope,side')]
            scope_rows = [dict(scope=s, hot=h, archived_pending=a) for s, h, a in db.execute(
                'SELECT scope,SUM(body IS NOT NULL),SUM(body IS NULL) FROM records GROUP BY scope')]
            row = dict(counters=counters, health=health, oldest_hot=hot, oldest_retained=retained,
                       gaps=gaps, floors=floors, progress=progress, episodes=episodes,
                       retained_by_scope=scope_rows, wall=time.time(), real_monotonic_ns=REAL_NS())
        finally:
            db.execute('ROLLBACK')
    row['hot_bytes'] = sum(p.stat().st_size for p in (Path(path), Path(str(path)+'-wal')) if p.exists())
    row['source_lag'] = max((row['wall']-health.get('finalized_frontier:'+scope, {}).get('time', row['wall'])
                             for scope in SCOPES), default=0)
    row['hot_age'] = max(0, row['wall']-hot) if hot is not None else 0
    row['retained_age'] = max(0, row['wall']-retained) if retained is not None else 0
    return row


def safety_errors(row):
    errors = []
    for key, limit in [('source_lag', 45), ('hot_age', 240), ('retained_age', 240), ('hot_bytes', 2*1024**3)]:
        value = row[key]
        if not 0 <= value < limit:
            errors.append('strict_'+key)
    if row['gaps']:
        errors.append('runtime_gap')
    if any(v for k, v in row['counters'].items() if k.startswith('disconnect:') or k == 'capacity_stops'):
        errors.append('native_capacity_or_disconnect')
    return errors


class CommonControl:
    def __init__(self):
        self.path = None
        self.stopping = False
        self.metrics = dict(urgent_acks=0, urgent_errors=[])

    async def acknowledgements(self):
        from meme_machine.solana_evidence_runtime import RuntimeEvidence
        while not self.stopping:
            if self.path is not None:
                def acknowledge():
                    with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
                        counters = dict(db.execute('SELECT key,value FROM counters'))
                    if counters.get('stream_accepted_messages', 0) < 10:
                        return False
                    plane = RuntimeEvidence(self.path, owner='meteora')
                    try:
                        top = plane.frontier('program:meteora')
                        plane.command(op='ack', owner='meteora:combined-pressure', scope='program:meteora', slot=top)
                        return True
                    finally:
                        plane.close()
                try:
                    if await asyncio.to_thread(acknowledge):
                        self.metrics['urgent_acks'] += 1
                except Exception as exc:
                    if not self.stopping:
                        self.metrics['urgent_errors'].append(type(exc).__name__)
                        return
            await asyncio.sleep(1)


class TapeWire:
    def __init__(self, params, *, landmark=None):
        self.params = params
        self.frames = params['frames']
        self.acks = asyncio.Queue()
        self.sent = 0
        self.first_release = None
        self.samples = []
        self.landmark = landmark
        self.landmark_task = None
        self.landmark_done = set()
        self.reader = None
        self.raw_hashes = []
        self.prebuilt = params.get('prebuilt')
        if self.prebuilt is None:
            expected = next(m for m in workload(params['kind'])['tape_binding']['members'] if m['id'] == params['member'])
            self.reader = Reader(params['tape_path'], expected)
            self.pending, _ = self.reader.next()
        else:
            require(len(self.prebuilt) == self.frames, 'full_shape_frame_count')
            self.pending = self.prebuilt[0]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def send(self, raw):
        request = json.loads(raw)
        await self.acks.put(canonical(dict(id=request['id'], result=request['id'])))

    async def recv(self, decode=None):
        if not self.acks.empty():
            return await self.acks.get()
        if self.sent >= self.frames:
            return await self.acks.get()
        if self.landmark and self.sent in (800, 1400) and self.sent not in self.landmark_done:
            if self.landmark_task is None:
                self.landmark_task = asyncio.create_task(asyncio.to_thread(self.landmark, self.sent))
            # Cancellation of the native .5s recv poll cannot duplicate a sample.
            await asyncio.shield(self.landmark_task)
            self.landmark_task = None
            self.landmark_done.add(self.sent)
        cadence = self.params['cadence_us'] * 1000
        if self.first_release is not None:
            due = self.first_release + self.sent*cadence
            await asyncio.sleep(max(0, (due-REAL_NS())/10**9))
        bound.ensure_release()
        raw = self.pending
        if raw is None:
            raw = self.prebuilt[self.sent] if self.prebuilt is not None else self.reader.next()[0]
        self.pending = None
        if self.first_release is None:
            self.first_release = bound.CLOCK.activate()
        # Byte identities only: event/blockTime/signature/economic bytes stay intact.
        self.raw_hashes.append(dict(number=self.sent, sha256=sha(raw), bytes=len(raw),
                                   released_real_monotonic_ns=REAL_NS()))
        self.sent += 1
        if self.sent == 1 or self.sent % 100 == 0 or self.sent == self.frames:
            self.samples.append(dict(frames=self.sent, **bound.CLOCK.sample()))
        return raw

    def receipt(self):
        tape = self.reader.close(strict=False) if self.reader else dict(valid=True, frames=self.sent,
            prebuilt_sha256=sha(canonical([sha(raw) for raw in self.prebuilt])))
        return dict(version='v3-source-receipt', member=self.params['member'], kind=self.params['kind'],
            mode=self.params['mode'], tape=tape, source_frames_released=self.sent,
            first_release_real_monotonic_ns=self.first_release, immutable_semantic_wall_epoch=1800000000,
            immutable_semantic_monotonic_epoch=100, cadence_us=self.params['cadence_us'],
            retiming_calls=0, raw_release_hashes=self.raw_hashes, clock_samples=self.samples,
            declaration_sha256=self.params['declaration_sha256'])


def native_archive_proof(path):
    import gzip
    from meme_machine.solana_evidence_plane import digest
    rows = []
    for archive in sorted(Path(path).parent.glob('*.archive/*.gz')):
        require(file_sha(archive) == archive.name.split('.')[0], 'native_archive_content_hash')
        count = 0
        with gzip.open(archive, 'rt') as source:
            for line in source:
                row = json.loads(line)
                require(digest(row['body']) == row['hash'] and row['lineage'], 'native_archive_body_or_lineage')
                count += 1
        rows.append(dict(path=str(archive), sha256=file_sha(archive), records=count))
    return rows


async def run_member():
    # This function is imported only after isolated bootstrap authorization.
    from meme_machine import solana_evidence_service as service
    from meme_machine.solana_evidence_runtime import RuntimeEvidence
    from verify import production_member_errors, observer_sample_errors
    params = dict(bound.PARAMS)
    output = Path(params['output'])
    path = Path(params['runtime'])/'db'
    path.parent.mkdir(parents=True, exist_ok=False)
    require(len(str(path)+'.sock') < 108, 'unix_socket_path_length')
    observed = params['kind'] == 'B' and params['mode'] == 'observed'
    shape = params.get('shape')
    seeds = ()
    if shape:
        from certification.stage_e_native_v2 import fixtures
        spec = fixtures.spec(shape)
        params.update(frames=spec['frames'], cadence_us=spec['cadence_us'],
                      prebuilt=tuple(fixtures.build_frame(shape, n) for n in range(spec['frames'])))
        if shape == 'run379':
            seeds = tuple(fixtures.build_frame(shape, n, historical_seed=True) for n in range(100))
    control = CommonControl()
    observer = None
    if observed and params['member'] == 'recovery-1':
        from certification import cleanup_recovery, lifecycle_capacity
        cleanup_recovery.PLAN_PATH = Path(params['assembly'])/'source/certification/stagee24_qualification_plan.json'
        observer = lifecycle_capacity.LifecycleObserver(output)
    landmarks = []
    def landmark(number):
        from certification.combined_observer import read_current
        counters, eligible = read_current(path)
        landmarks.append(dict(frame=number, source_seconds=number*.27, counters=counters, eligible=eligible,
                              real_monotonic_ns=REAL_NS()))
    wire = TapeWire(params, landmark=landmark if observed else None)
    native_state = service.ServiceState
    setup = {}
    class State(native_state):
        def __init__(self, dbpath, config):
            super().__init__(dbpath, config)
            control.path = Path(dbpath)
            if seeds:
                from certification.stage_e_native_v2.native import source, empty_frame
                for raw in seeds:
                    # Historical availability stays historical, including first_seen.
                    at = json.loads(raw)['params']['result']['value']['block']['blockTime']
                    class Availability:
                        def time(self):
                            return at+1
                    source(self, raw, Availability())
                source(self, empty_frame(1100, 1800000000), bound.CLOCK)
            setup.update(counters=dict(self.writer.db.execute('SELECT key,value FROM counters')),
                         seed_frames=len(seeds), seed_sha256=[sha(raw) for raw in seeds],
                         setup_elapsed_ns=bound.CLOCK.elapsed_ns(), historical_availability_unchanged=True)
            if observer:
                observer.attach(dbpath)
            setup['complete'] = True
        def close(self):
            if observer:
                observer.stop.set()
            return super().close()
    # Construction/setup binding only. The actual source_batch method and all
    # worker/commit/archive/retention functions are inherited without overrides.
    stop = asyncio.Event()
    runner = None
    ack = asyncio.create_task(control.acknowledgements())
    queries = []
    pending_query = None
    last_query = None
    rows = []
    errors = []
    archived_before_finish = False
    commands = None
    live_shape_candidate = None
    def candidate():
        plane = RuntimeEvidence(path, owner='meteora')
        try:
            top = plane.frontier('program:meteora')
            plane.command(op='ack', owner='meteora:run381', scope='program:meteora', slot=top)
            counts = {scope: len(plane.reader.window(scope, top, top, as_of=time.time())) for scope in SCOPES}
            require(counts['program:meteora'] == 128 and counts['program:pump'] > 0
                    and counts['program:pumpswap'] > 0, 'candidate_source_progress')
            return counts
        finally:
            plane.close()
    def shape_controls():
        plane = RuntimeEvidence(path, owner='pump')
        try:
            for _ in range(25):
                plane.command(op='counter', key='pump.run379_control_probe', count=1)
        finally:
            plane.close()
    started = REAL_NS()
    try:
        with patch.object(service, 'ServiceState', State), patch('websockets.asyncio.client.connect', return_value=wire):
            runner = asyncio.create_task(service.serve(path, ENDPOINT, stop=stop))
            while True:
                require(not bound.ADMISSION_ERRORS, 'native_thread_admission_failed')
                if runner.done():
                    await runner
                    raise ValueError('native_service_terminated_early')
                row = await asyncio.to_thread(read_snapshot, path)
                if row and setup.get('complete'):
                    rows.append(row)
                    failures = safety_errors(row)
                    require(not failures, 'native_safety:' + ','.join(failures))
                    accepted = row['counters'].get('stream_accepted_messages', 0)-setup.get('counters', {}).get('stream_accepted_messages', 0)
                    if shape == 'run379':
                        archived_before_finish |= accepted < params['frames'] and row['counters'].get('archived_records', 0) > 0
                        if accepted >= 5 and commands is None:
                            commands = asyncio.create_task(asyncio.to_thread(shape_controls))
                    if not shape and accepted > 10:
                        if pending_query is not None and pending_query.done():
                            queries.append(await pending_query)
                            pending_query = None
                        if pending_query is None and (last_query is None or REAL_NS()-last_query >= 10*10**9):
                            pending_query = asyncio.create_task(asyncio.to_thread(candidate))
                            last_query = REAL_NS()
                    if accepted >= params['frames']:
                        if shape == 'run379':
                            plane = RuntimeEvidence(path, owner='pump')
                            try:
                                live_shape_candidate = len(plane.reader.window('program:meteora',1219,1219,as_of=time.time()))
                            finally:
                                plane.close()
                        break
                require(REAL_NS()-started <= (params['frames']*params['cadence_us']/1e6+120)*1e9, 'native_member_deadline')
                await asyncio.sleep(.25)
            if pending_query:
                queries.append(await pending_query)
                pending_query = None
            if commands:
                await commands
    except BaseException as exc:
        errors.append(type(exc).__name__+':'+str(exc))
    finally:
        stop.set()
        if runner:
            try:
                await runner
            except BaseException as exc:
                errors.append('native:'+type(exc).__name__+':'+str(exc))
        if pending_query:
            await asyncio.gather(pending_query, return_exceptions=True)
        if commands:
            await asyncio.gather(commands, return_exceptions=True)
        control.stopping = True
        await asyncio.gather(ack, return_exceptions=False)
        if observer:
            observer.close()
    final = read_snapshot(path)
    require(final is not None, 'native_raw_database_missing')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        integrity = [r[0] for r in db.execute('PRAGMA integrity_check')]
        coverage = {}
        if shape in ('run373', 'run380'):
            from meme_machine.solana_evidence_plane import EvidenceReader
            reader = EvidenceReader(path)
            try:
                scope, end = ('program:pumpswap', 1012) if shape == 'run373' else ('program:meteora', 1238)
                coverage[scope] = reader.covered(scope, 1000, end, as_of=time.time())
            finally:
                reader.close()
    archives = native_archive_proof(path)
    source_receipt = wire.receipt()
    row = dict(version='stage-e-native-v3-member', kind=params['kind'], member=params['member'], shape=shape,
        mode=params['mode'], candidate_sha=S, frames=params['frames'], cadence_us=params['cadence_us'],
        source_seconds=params['frames']*params['cadence_us']/1e6, declaration_sha256=params['declaration_sha256'],
        setup=setup, safety_samples=rows, final=final, errors=errors, integrity=integrity,
        ipc=final['health'].get('ipc', {}), counters=final['counters'], archives=archives,
        candidate_checks=queries, common_control=control.metrics,
        artificial_contention=workload('A')['artificial_contention'], provider_attempts=list(bound.PROVIDER_ATTEMPTS),
        runtime_path=str(path), source_receipt=source_receipt,
        observer_samples=observer.samples if observer else [], observer_errors=observer.errors if observer else [],
        qualification_snapshots=landmarks, coverage=coverage, archived_before_finish=archived_before_finish)
    row['live_shape_candidate_records'] = live_shape_candidate
    if observer:
        # All reads, assessment and persistence are inside the measured child.
        row['original_stress_assessment'] = lifecycle_capacity.assessment(observer.samples, observer.errors)
    if bound.ADMISSION_ERRORS:
        row['errors'].extend(bound.ADMISSION_ERRORS)
    failures = production_member_errors(row)
    if observed:
        failures += observer_sample_errors(row)
    row['valid'] = not failures
    row['verification_errors'] = failures
    persist(output/'SOURCE_RECEIPT.json', source_receipt)
    persist(output/'MEMBER_RESULT.json', row)
    require(not failures, 'production_member_invalid:' + ','.join(failures))


def main():
    asyncio.run(run_member())
