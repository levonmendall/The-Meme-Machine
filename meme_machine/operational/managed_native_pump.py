"""Fresh-generation Pump acquisition using the production read-only owner.

Run in a dedicated child process. This module starts SelectiveSource and its
canonical/history delivery workers, never a lane runner, portfolio, or funding
authority. The caller supplies the installed continuous provider profile and
its independently initialized, shared usage journal; no capacity is invented.
"""
import asyncio
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

from meme_machine.solana_provider_config import AlchemyEndpoint

SCHEMA = 'managed-native-pump-v1'
MARKER = 'managed-native-pump.json'
SHUTDOWN_SECONDS = 65
FINANCIAL_NAMES = frozenset(('portfolio.sqlite', 'shared-capital.sqlite',
    'native-genesis.json', 'paper-journal.jsonl'))
_started = False


def _require(condition, reason):
    if not condition:
        raise ValueError('managed_pump_' + reason)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _owned_path(value, *, directory=False):
    path = Path(value)
    _require(path.is_absolute() and path.resolve(strict=True) == path
             and not path.is_symlink(), 'real_absolute_path_required')
    info = path.stat()
    _require(info.st_uid == os.geteuid() and
             (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
             and not info.st_mode & 0o077
             and (directory or info.st_nlink == 1), 'private_owned_path_required')
    return path


def _root(value):
    root = _owned_path(value, directory=True)
    for parent in (root, *root.parents):
        _require(not any((parent / name).exists() or (parent / name).is_symlink()
                         for name in FINANCIAL_NAMES), 'financial_ancestor_refused')
    return root


@dataclass(frozen=True)
class PumpManagedConfig:
    root: Path
    generation: str
    request_id: str
    source_revision: str
    endpoint: str = field(repr=False)
    provider_usage_db: Path
    continuous_provider_envelope: Path
    token: str | None = field(default=None, repr=False)

    @property
    def evidence(self):
        return Path(self.root) / 'shared' / 'solana-evidence.sqlite'

    @property
    def history(self):
        return Path(self.root) / 'shared' / 'solana-candidate-history.sqlite'

    def identity(self):
        root = _root(self.root)
        _require(re.fullmatch(r'[a-f0-9]{32}', self.generation or '') is not None,
                 'generation_required')
        _require(re.fullmatch(r'[A-Za-z0-9_-]{1,96}', self.request_id or '') is not None,
                 'request_identity_required')
        _require(re.fullmatch(r'[a-f0-9]{40}', self.source_revision or '') is not None,
                 'source_revision_required')
        config = AlchemyEndpoint.parse(self.endpoint)
        _require(self.token is None or isinstance(self.token, str)
                 and 8 <= len(self.token) <= 512 and not any(c.isspace() for c in self.token),
                 'native_credential_shape')
        usage = _owned_path(self.provider_usage_db)
        _root(usage.parent)
        envelope = _owned_path(self.continuous_provider_envelope)
        _require(root not in usage.parents and root not in envelope.parents,
                 'shared_provider_paths_required')
        _require(envelope.stat().st_size <= 16384, 'profile_byte_bound')
        return dict(schema=SCHEMA, generation=self.generation,
            request_id=self.request_id, source_revision=self.source_revision,
            provider_identity=config.identity, provider=config.provider,
            native_credential_identity=hashlib.sha256((self.token or config.credential).encode()).hexdigest(),
            native_host='solana-mainnet.streaming.alchemy.com:443',
            provider_usage_db=str(usage),
            profile_sha256=hashlib.sha256(envelope.read_bytes()).hexdigest(),
            root_device=root.stat().st_dev, root_inode=root.stat().st_ino,
            canonical_history_delivery=True, economic_strategy_evaluation=False,
            native_candidate_prospect_evaluation=True,
            full_candidate_qualification_proven=False,
            financial_authority=False, hot_store_limit_bytes=2 * 1024**3,
            finalized_head_sampling_seconds=5)

    def environment(self):
        return dict(MM_MODE='PAPER', MM_OPERATIONAL_PHASE='OBSERVATION',
            MM_SOLANA_HISTORY_SEPARATED='1',
            MM_SOLANA_EVIDENCE_PLANE_DB=str(self.evidence),
            MM_SOLANA_CANDIDATE_HISTORY_DB=str(self.history),
            MM_PROVIDER_GOVERNOR_DB=str(Path(self.root) / 'provider-governor.sqlite'),
            MM_SOLANA_READ_RPC_URL=self.endpoint,
            MM_PROVIDER_OPERATION_MODE='CONTINUOUS',
            MM_PROVIDER_USAGE_DB=str(self.provider_usage_db),
            MM_CONTINUOUS_PROVIDER_ENVELOPE=str(self.continuous_provider_envelope),
            MM_OPERATION_COST_DIAGNOSTICS='1', MM_SQLITE_DIAGNOSTIC_REQUIRED='1',
            **({'MM_SOLANA_YELLOWSTONE_TOKEN': self.token} if self.token else {}))


def prepare_generation(config, *, restart=False):
    """Create only empty state, or authenticate this exact isolated generation."""
    identity = config.identity()
    root = _root(config.root)
    marker = root / MARKER
    if restart:
        _owned_path(marker)
        _require(marker.stat().st_size <= 16384, 'marker_byte_bound')
        _require(json.loads(marker.read_text()) == identity, 'generation_identity_changed')
        for path in root.rglob('*'):
            _require(path.name not in FINANCIAL_NAMES, 'financial_state_refused')
            _owned_path(path, directory=path.is_dir())
    else:
        _require(not any(root.iterdir()), 'fresh_root_required')
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(_canonical(identity) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        (root / 'shared').mkdir(mode=0o700)
    return identity


@contextmanager
def production_environment(config):
    """A child must start with an empty MM namespace; no old state can leak in."""
    _require(not any(k.startswith('MM_') for k in os.environ),
             'inherited_production_environment_refused')
    values = config.environment()
    previous_umask = os.umask(0o077)
    os.environ.update(values)
    try:
        yield
    finally:
        for key in values:
            os.environ.pop(key, None)
        os.umask(previous_umask)


def production_components(config):
    """The same provider guards, governor, driver and SQL owner as production."""
    from .bounded_provider import install
    from .position_continuation import load_continuous
    profile = load_continuous(config.continuous_provider_envelope)
    _require(any(r.startswith('pump_') for r in profile['funding_regimes']),
             'pump_provider_capacity_missing')
    install()
    from meme_machine.runtime.governor import Governor
    from meme_machine.runtime.evidence_worker import RepairRPC
    from meme_machine.solana_selective_source import SelectiveSource
    from meme_machine.solana_evidence_service import serve
    rpc = RepairRPC(config.endpoint, Governor(os.environ['MM_PROVIDER_GOVERNOR_DB']))
    driver = SelectiveSource(rpc.config, rpc, token=config.token or rpc.config.credential)
    return rpc, driver, serve


class FinalizedHeadObserver:
    """Independent market frontier, charged by production RPC and governor.

    Joined frame admission is not market arrival. A finalized slot frontier
    includes skipped slots and cannot establish complete block coverage.
    """
    def __init__(self):
        self.last = None
        self.requests = self.failures = 0

    def sample(self, rpc):
        self.requests += 1
        started = time.monotonic()
        try:
            # This independently measured arrival frontier belongs to the same
            # foreground admission class as the native source's getSlot reads.
            # RepairRPC.call's boolean priority selects either position work (1)
            # or speculative work (4); neither describes this required sample.
            # Preserve the production physical clock, cooldown and eight-second
            # admission deadline, while leaving held/reserved work (0/1) first.
            slot, _ = rpc.call_delivered('getSlot', [dict(commitment='finalized')],
                                         priority=2)
        except Exception as error:
            self.failures += 1
            return dict(self.last or {}, fresh=False, requests=self.requests,
                failures=self.failures, error_type=type(error).__name__,
                last_request_latency_seconds=time.monotonic()-started)
        _require(type(slot) is int and 0 < slot < 2**63, 'authenticated_head_shape')
        _require(self.last is None or slot >= self.last['slot'], 'authenticated_head_regressed')
        self.last = dict(slot=slot, observed_monotonic=time.monotonic(), observed_at=time.time())
        return dict(self.last, fresh=True, requests=self.requests, failures=self.failures,
                    last_request_latency_seconds=time.monotonic()-started)


def install_nonfinancial_history(config):
    """Deny financial/strategy records at SQL admission, before any provider I/O."""
    from meme_machine.runtime.candidate_history import CandidateHistory
    with closing(CandidateHistory(config.history, write_wait_seconds=0)) as history:
        for table in ('funding', 'decisions'):
            _require(history.db.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0,
                     'financial_or_strategy_authority_detected')
            for action in ('INSERT', 'UPDATE', 'DELETE'):
                history.db.execute('CREATE TRIGGER IF NOT EXISTS managed_pump_deny_' +
                    table + '_' + action.lower() + ' BEFORE ' + action + ' ON ' + table +
                    " BEGIN SELECT RAISE(ABORT,'managed_pump_nonfinancial_history'); END")


@contextmanager
def _reader(path):
    _owned_path(path)
    with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True,
                                isolation_level=None, timeout=.1)) as db:
        db.execute('PRAGMA query_only=ON')
        until = time.monotonic() + .5
        db.set_progress_handler(lambda: int(time.monotonic() > until), 1000)
        db.execute('BEGIN')
        yield db
        db.execute('ROLLBACK')


def _has_tables(db, names):
    present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    return set(names) <= present


def pump_snapshot(config, *, driver=None):
    """Read each store on one bounded snapshot; never infer absent counters."""
    result = dict(schema=SCHEMA, generation=config.generation, observed_at=time.time(),
                  monotonic=time.monotonic(), financial_authority=False)
    if not config.evidence.exists():
        result['canonical'] = None
    else:
        with _reader(config.evidence) as db:
            if not _has_tables(db, ('service_health', 'stream_receipts', 'candidate_coverage',
                    'candidate_gaps', 'candidate_history_outbox', 'canonical_evidence')):
                return dict(result, canonical=None, history=None, initialization_pending=True)
            health = dict(db.execute('SELECT key,value FROM service_health'))
            wanted = ('provider', 'phase', 'heartbeat', 'ipc', 'owner_scheduler',
                      'source_drain', 'source_control_recovery', 'storage_maintenance')
            result['health'] = {k: json.loads(health[k]) for k in wanted if k in health}
            result['canonical'] = dict(
                finalized_blocks=db.execute("SELECT count(*) FROM stream_receipts WHERE scope='control:solana'").fetchone()[0],
                sealed_finalized_blocks=db.execute("SELECT count(*) FROM stream_receipts WHERE scope='control:solana' AND sealed=1").fetchone()[0],
                latest_finalized_slot=db.execute("SELECT max(slot) FROM stream_receipts WHERE scope='control:solana'").fetchone()[0],
                latest_sealed_slot=db.execute("SELECT max(slot) FROM stream_receipts WHERE scope='control:solana' AND sealed=1").fetchone()[0],
                coverage=list(db.execute('SELECT scope,min(lo),max(hi),count(*) FROM candidate_coverage GROUP BY scope')),
                unresolved_gaps=list(db.execute('SELECT scope,count(*),min(lo),max(hi) FROM candidate_gaps WHERE repaired IS NULL GROUP BY scope')),
                outbox=list(db.execute('SELECT kind,count(*),sum(consumed IS NOT NULL) FROM candidate_history_outbox GROUP BY kind')),
                canonical_events=db.execute("SELECT count(*) FROM canonical_evidence WHERE kind='event'").fetchone()[0])
    if not config.history.exists():
        result['history'] = None
    else:
        with _reader(config.history) as db:
            if not _has_tables(db, ('candidates', 'events', 'canonical_event_refs',
                                   'history_coverage', 'funding', 'decisions')):
                return dict(result, history=None, initialization_pending=True)
            counts = {name: db.execute('SELECT count(*) FROM ' + name).fetchone()[0]
                      for name in ('candidates', 'events', 'canonical_event_refs',
                                   'history_coverage', 'funding', 'decisions')}
            counts['source_receipts'] = (db.execute('SELECT count(*) FROM source_receipts').fetchone()[0]
                                         if _has_tables(db, ('source_receipts',)) else None)
            _require(counts['funding'] == counts['decisions'] == 0,
                     'financial_or_strategy_authority_detected')
            counts['latest_event_slot'] = db.execute('SELECT max(slot) FROM (SELECT slot FROM events UNION ALL SELECT slot FROM canonical_event_refs)').fetchone()[0]
            result['history'] = counts
    if driver is not None:
        result['pipeline'] = {k: dict(v) for k, v in driver.pipeline_metrics.items()}
        # Accepted/committed use the same native joined-frame unit, including
        # replay. Slot frontiers and coverage above independently expose gaps.
        result['source_frames'] = driver.drain_snapshot()
    qualification = Path(config.root) / 'qualification.sqlite'
    if qualification.exists():
        with _reader(qualification) as db:
            if _has_tables(db, ('observations',)):
                completed, cursor = db.execute('SELECT count(*),max(sequence) FROM observations').fetchone()
                stages = dict(db.execute('SELECT stage,count(*) FROM observations GROUP BY stage'))
                result['qualification'] = dict(durably_observed_native_events=completed,
                    durable_sequence=cursor, stages=stages,
                    full_qualification_proven=False,
                    postgraduation_and_survivor_qualification_proven=False,
                    financial_authority=False)
        if 'qualification' in result and config.evidence.exists():
            with _reader(config.evidence) as db:
                if _has_tables(db, ('candidate_outbox',)):
                    incoming = db.execute("SELECT count(*) FROM candidate_outbox WHERE scope='program:pump'").fetchone()[0]
                    result['qualification'].update(incoming_native_events=incoming,
                        native_event_backlog=incoming-completed)
    AlchemyEndpoint.parse(config.endpoint).public(result)
    if config.token:
        _require(config.token not in _canonical(result), 'native_credential_publication_refused')
    return result


def replay_pump(config, *, seconds=60):
    """Authenticate every retained candidate event through the native reader.

    Called after source shutdown. All SQLite handles are read-only, including
    the CandidateHistory facade; no schema install or checkpoint is performed.
    """
    _require(type(seconds) in (int, float) and 1 <= seconds <= 300,
             'replay_deadline_bound')
    from meme_machine.runtime.candidate_history import CandidateHistory
    _owned_path(config.history)
    until = time.monotonic() + seconds
    def check():
        _require(time.monotonic() < until, 'replay_deadline')
    def add(digest, value):
        raw = value if isinstance(value, bytes) else _canonical(value).encode()
        digest.update(len(raw).to_bytes(8, 'big'))
        digest.update(raw)
    def fingerprint():
        digest = hashlib.sha256()
        for path, tables in ((config.evidence, ('records', 'shared_history_cache',
                'candidate_coverage', 'candidate_history_outbox', 'candidate_gaps',
                'stream_receipts', 'rolling_economic_events', 'scoped_cold_records',
                'scoped_cold_addresses', 'scoped_cold_manifests', 'hot_chunks', 'hot_refs')),
                (config.history, ('candidates', 'events', 'canonical_event_refs',
                    'source_receipts', 'history_coverage', 'funding', 'decisions'))):
            with _reader(path) as db:
                db.set_progress_handler(lambda: int(time.monotonic() >= until), 1000)
                for table in tables:
                    add(digest, table)
                    if not _has_tables(db, (table,)):
                        add(digest, ['absent', table])
                        continue
                    order = 'identity,hash' if table == 'hot_refs' else 'rowid'
                    for row in db.execute('SELECT * FROM ' + table + ' ORDER BY ' + order):
                        check()
                        for value in row:
                            # Type labels distinguish a byte payload from text
                            # with the same UTF-8 encoding in the native store.
                            add(digest, type(value).__name__)
                            add(digest, value)
                if path == config.evidence and _has_tables(db, ('scoped_cold_manifests',)):
                    directory = config.evidence.with_suffix('.scoped-cold')
                    for locator, expected in db.execute('SELECT path,hash FROM scoped_cold_manifests ORDER BY id'):
                        check()
                        cold = Path(locator)
                        _require(cold.parent == directory and
                            re.fullmatch('[0-9a-f]{64}\\.zlib', cold.name) is not None,
                            'foreign_cold_reference_refused')
                        _owned_path(directory, directory=True)
                        _owned_path(cold)
                        payload = hashlib.sha256()
                        with cold.open('rb') as stream:
                            while block := stream.read(65536):
                                check()
                                payload.update(block)
                        _require(payload.hexdigest() == expected, 'cold_payload_corruption')
                        add(digest, ['cold', locator, payload.hexdigest()])
        return digest.hexdigest()
    before = fingerprint()
    history = CandidateHistory.__new__(CandidateHistory)
    history.path = config.history
    history.clock = time.time
    history.db = sqlite3.connect(config.history.as_uri() + '?mode=ro', uri=True,
                                 isolation_level=None, timeout=.1)
    history.db.execute('PRAGMA query_only=ON')
    events = candidates = 0
    logical = hashlib.sha256()
    try:
        for (raw,) in history.db.execute('SELECT body FROM canonical_event_refs'):
            check()
            _require(json.loads(raw)['path'] == str(config.evidence),
                     'foreign_canonical_reference_refused')
        for row in history.candidates(lane='pump', cancelled=lambda: time.monotonic() >= until):
            candidates += 1
            add(logical, ['candidate', row])
            for event in history.events('pump', row['candidate'],
                                        cancelled=lambda: time.monotonic() >= until):
                events += 1
                add(logical, ['event', event])
        check()
        expected = history.db.execute("SELECT (SELECT count(*) FROM events WHERE lane='pump') + (SELECT count(*) FROM canonical_event_refs WHERE lane='pump')").fetchone()[0]
        _require(events == expected, 'replay_population_mismatch')
        _require(history.db.execute('SELECT count(*) FROM funding').fetchone()[0] == 0
                 and history.db.execute('SELECT count(*) FROM decisions').fetchone()[0] == 0,
                 'financial_or_strategy_authority_detected')
    finally:
        history.close()
    after = fingerprint()
    _require(before == after, 'replay_mutated_native_history')
    return dict(verified=True, candidates=candidates, events=events,
                logical_sha256=logical.hexdigest(), read_only=True,
                native_state_sha256=after, canonical_source_path_isolated=True)


async def run_pump(config, stop, *, restart=False, sample_callback=None, sample_seconds=5,
                   decision_target_lamports=None, drain_callback=None):
    """Run until the parent's bounded stop; await production's original drain."""
    global _started
    _require(not _started, 'dedicated_child_process_required')
    _require(isinstance(stop, asyncio.Event), 'bounded_stop_event_required')
    _require(type(sample_seconds) in (int, float) and 1 <= sample_seconds <= 60,
             'sample_interval_bound')
    _require(decision_target_lamports is None or type(decision_target_lamports) is int
             and decision_target_lamports > 0, 'decision_target_required')
    # Check the inherited namespace before creating any state.
    _require(not any(k.startswith('MM_') for k in os.environ),
             'inherited_production_environment_refused')
    identity = prepare_generation(config, restart=restart)
    _started = True
    lock_path = Path(config.root) / '.process.lock'
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a+b') as lock, production_environment(config):
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        install_nonfinancial_history(config)
        rpc, driver, serve = production_components(config)
        await asyncio.to_thread(rpc.validate_network)
        from meme_machine.runtime.evidence_worker import owner_thread_fairness
        from .managed_pump_qualification import read_qualifications
        qualification_metrics = dict(initialization_pending=True,
            full_qualification_proven=False, financial_authority=False)
        head_observer = FinalizedHeadObserver()
        def publish_qualification(value):
            nonlocal qualification_metrics
            qualification_metrics = value
        async def samples():
            while not stop.is_set():
                if sample_callback is not None:
                    head = await asyncio.to_thread(head_observer.sample, rpc)
                    # SQLite reads leave the source event loop responsive.
                    # Process-local counters are copied on their owning loop.
                    try:
                        sample = await asyncio.to_thread(pump_snapshot, config)
                    except sqlite3.OperationalError as error:
                        code = getattr(error, 'sqlite_errorcode', 0) & 255
                        if code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_INTERRUPT):
                            raise
                        sample = dict(schema=SCHEMA, generation=config.generation,
                            observed_at=time.time(), monotonic=time.monotonic(),
                            observation_unavailable=code, financial_authority=False)
                    sample['pipeline'] = {k: dict(v) for k, v in driver.pipeline_metrics.items()}
                    sample['source_frames'] = driver.drain_snapshot()
                    sample['qualification_worker'] = dict(qualification_metrics)
                    sample['authenticated_finalized_head'] = head
                    sample_callback(sample)
                try:
                    await asyncio.wait_for(stop.wait(), sample_seconds)
                except TimeoutError:
                    pass
        sampler = asyncio.create_task(samples())
        workload = qualification = None
        drain_deadline = None
        async def drained():
            nonlocal drain_deadline
            if drain_deadline is None:
                drain_deadline = time.monotonic() + SHUTDOWN_SECONDS
            try:
                children = [t for t in (workload, qualification) if t is not None]
                _, pending = await asyncio.wait(children,
                    timeout=max(0, drain_deadline - time.monotonic()))
                if pending:
                    for child in pending:
                        child.cancel()
                    raise TimeoutError
                for child in children:
                    child.result()
            except TimeoutError:
                raise ValueError('managed_pump_source_shutdown_deadline') from None
        primary_error = None
        try:
            with owner_thread_fairness():
                workload = asyncio.create_task(serve(config.evidence, config.endpoint,
                    repair_rpc=rpc, stop=stop, source_driver=driver))
                qualification = asyncio.create_task(read_qualifications(config, stop,
                    publish=publish_qualification, decision_target=decision_target_lamports))
                done, _ = await asyncio.wait((workload, sampler, qualification), return_when=asyncio.FIRST_COMPLETED)
                if sampler in done and not stop.is_set():
                    stop.set()
                if workload in done and not stop.is_set():
                    workload.result()
                    raise ValueError('managed_pump_source_ended_before_stop')
                if qualification in done and not stop.is_set():
                    qualification.result()
                    raise ValueError('managed_pump_qualification_ended_before_stop')
                try:
                    if sampler.done():
                        sampler.result()
                finally:
                    await drained()
        except BaseException as error:
            primary_error = error
            raise
        finally:
            stop.set()
            # Parent cancellation must retain the environment and ownership
            # lock while the same production source finishes accepted work.
            try:
                if any(t is not None and not t.done() for t in (workload, qualification)):
                    try:
                        await drained()
                    except BaseException:
                        if primary_error is None:
                            raise
            finally:
                await asyncio.gather(sampler, return_exceptions=True)
        if drain_callback is not None:
            drain_callback()
        return dict(identity=identity, snapshot=pump_snapshot(config, driver=driver),
                    replay=replay_pump(config),
                    qualification_worker=qualification_metrics,
                    scope='native_acquisition_decoding_canonical_candidate_history_delivery_current_prospect_readside',
                    economic_strategy_evaluation=False, financial_authority=False)
