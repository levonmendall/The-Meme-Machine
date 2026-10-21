"""Nonfinancial Pump read side over the actual native discovery/history readers.

The source remains the only canonical/CandidateHistory producer. This reader
owns one separate observation SQLite file; it never opens a book, sleeve,
portfolio, lifecycle, funding table, or CandidateHistory writer. A native cheap
screen is not reported as complete full qualification. In particular, missing
executable sizing or postgraduation evaluation stays explicitly unproven.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time


SCHEMA = 'managed-pump-qualification-v1'
PAGE = 64
EVIDENCE_SECONDS = 25


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class DecisionTarget:
    lamports: int
    native_value: object
    provenance: dict

    def validate(self, at):
        # Provider/admission waits never extend the original oracle lifetime.
        self.native_value.amount(1, int(at))


class FreshReferenceSizing:
    """Unfunded $1,000 reference input, with actual expiring SOL valuation.

    This is not a ledger or financial inception. No entries, costs or realized
    PnL can occur in the managed observation route. Its reference equity remains
    the explicit fresh simulation input while production's exact sizing floor
    and authenticated native conversion are evaluated for each admitted input.
    """
    def __init__(self, generation, *, clock=time.time, value_reader=None):
        from meme_machine.runtime.usd_valuation import native_reader
        self.generation, self.clock = generation, clock
        self.value_reader = value_reader if value_reader is not None else native_reader('pump')
        self.last = None

    def identity(self):
        from meme_machine.portfolio_accounting import PLANNED_SHARED_CAPITAL
        return dict(scope='fresh_nonfunded_reference_no_entries_costs_or_realized_pnl',
            generation=self.generation, reference_equity_usd=PLANNED_SHARED_CAPITAL,
            target_bps=500, actual_shared_ledger=False, financial_authority=False)

    def __call__(self, now):
        from fractions import Fraction
        from meme_machine.exact_money import money
        from meme_machine.portfolio_accounting import PLANNED_SHARED_CAPITAL
        from meme_machine.shared_capital.adapter import directional_native_target
        self.last = None
        at = max(int(now), int(self.clock()))
        value = self.value_reader(at)
        consumed_at = max(at, int(self.clock()))
        unit = value.amount(1, consumed_at)
        if value.asset != 'SOL' or value.decimals != 9:
            raise ValueError('managed_pump_native_sizing_asset_required')
        # USD/native reciprocals usually recur. Preserve production's positive
        # integer sizing floor with an exact rational quotient, without
        # rounding a rate or extending the canonical money envelope.
        native_equity = Fraction(money(PLANNED_SHARED_CAPITAL)) // Fraction(unit)
        size = directional_native_target(native_equity)
        if size['requested_native_units'] <= 0:
            raise ValueError('managed_pump_decision_target_required')
        result = DecisionTarget(size['requested_native_units'], value, dict(self.identity(),
            native_equity=size['native_equity'], target_lamports=size['requested_native_units'],
            consumed_at=consumed_at, valuation=dict(asset=value.asset, decimals=value.decimals,
                usd_per_unit=str(value.usd_per_unit), observed_at=value.observed_at,
                valid_until=value.valid_until, evidence_id=value.evidence_id,
                evidence_hash=value.evidence_hash)))
        self.last = result
        return result

    def available(self, now):
        if self.last is None:
            return False
        try:
            self.last.validate(now)
        except ValueError:
            return False
        return True


class MarketSnapshotProvider:
    """Production read-only RPC, pacing, caching and concentration semantics.

    One worker owns the session. Capacity and billing admission are installed by
    managed_native_pump before this object is constructed. No public fallback,
    new provider envelope, target capital, or execution authority is supplied.
    """
    def __init__(self):
        self.rpc = self.pump = self.reader = None

    def begin(self, now):
        from meme_machine.lanes.pump.concentration import ConcentrationReader
        from meme_machine.lanes.pump.provider import PumpAdapter
        from meme_machine.lanes.pump.solana_read_rpc import new_rpc
        if (self.rpc is None or self.rpc.calls + 25 > 190
                or self.reader.status().get('program_scan_logical_requests', 0) >= 28):
            pacer = None if self.rpc is None else self.rpc.read_pacer
            self.rpc = new_rpc(limit=240, pacer=pacer)
            self.rpc.evidence_kind = 'pump_current_qualification'
            self.pump = PumpAdapter(self.rpc)
            self.reader = ConcentrationReader(self.rpc)
        self.rpc.evidence_deadline = min(float(now) + EVIDENCE_SECONDS,
                                         float(self.rpc.clock()) + EVIDENCE_SECONDS)
        if self.reader.program_rpc is not None:
            self.reader.program_rpc.evidence_deadline = self.rpc.evidence_deadline
            self.reader.program_rpc.evidence_kind = 'pump_current_qualification'

    def snapshot(self, mint, now):
        self.begin(now)
        return self.pump.snapshot(mint, now, priority=True)

    def concentration(self, mint, snapshot):
        return self.reader.read(mint, snapshot, priority=True)[0]


def full_late_signal(creation, events, snapshot, concentration, confirmations, target):
    """The native late-curve vector with an explicit read-only decision target.

    `_late_signal` implicitly opens a financial sleeve for its target. Reuse its
    unchanged native feature builders and `_capacity(..., intended=target)`
    instead, avoiding both a financial open and the legacy $500 fallback. The
    production qualifier and every predicate remain the same functions.
    """
    if type(target) is not int or target <= 0:
        raise ValueError('managed_pump_decision_target_required')
    from meme_machine.lanes.pump import pump
    from meme_machine.lanes.pump.runner import (
        _capacity, _late_stream_signal, _volume_quality_attention)
    curve = pump.curve(snapshot['accounts'][0])
    origin = dict(creation, creator=str(creation.get('creator') or curve.creator))
    event = dict(mint=snapshot['mint'], market_time=snapshot['market_time'],
        real_token_reserves=curve.real_token, virtual_quote_reserves=curve.sol,
        virtual_token_reserves=curve.token)
    signal, trajectory, confirmation = _late_stream_signal(
        origin, events, event, confirmations)
    confirmation['volume_quality'] = _volume_quality_attention(events,
        int(snapshot['market_time']), confirmation, complete=True,
        progress=dict(stage='bonding_curve',
                      curve_progress_bps=trajectory['curve_progress_bps']))
    from meme_machine.lanes.pump.pump_acceleration_strategy import flow_metrics
    flow = flow_metrics(events, int(snapshot['market_time']),
        cluster_map=confirmation['cluster_map'],
        excluded_clusters=confirmation['excluded_clusters'])
    turnover = flow['gross_buy'] + flow['gross_sell']
    capacity, _ = _capacity(snapshot, turnover, intended=target)
    return replace(signal, concentration_bps=int(concentration),
        authenticated_recent_turnover=turnover,
        immediate_roundtrip_loss_bps=capacity.ordinary_loss_bps)


class QualificationReader:
    """One bounded native read turn and one separate durable observation owner."""
    def __init__(self, config, *, decision_target=None, clock=time.time,
                 provider=None):
        if decision_target is not None and not isinstance(decision_target, FreshReferenceSizing) and (
                type(decision_target) is not int or decision_target <= 0):
            raise ValueError('managed_pump_decision_target_required')
        if isinstance(decision_target, FreshReferenceSizing) and decision_target.generation != config.generation:
            raise ValueError('managed_pump_decision_target_generation')
        self.config, self.clock = config, clock
        self.target, self.provider = decision_target, provider
        self.history = self.plane = self.db = self.confirmations = None
        self.cancelled = threading.Event()

    @property
    def path(self):
        return Path(self.config.root) / 'qualification.sqlite'

    def _open(self):
        from .managed_native_pump import _owned_path
        from meme_machine.runtime.candidate_history import CandidateHistory
        from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
        from meme_machine.lanes.pump.solana_evidence_runtime import RuntimeEvidence
        from meme_machine.solana_selective_runtime import selective
        if self.db is not None:
            return True
        if not self.config.history.exists() or not self.config.evidence.exists():
            return False
        _owned_path(self.config.history)
        _owned_path(self.config.evidence)
        history = CandidateHistory.__new__(CandidateHistory)
        history.path, history.clock = self.config.history, self.clock
        history.db = sqlite3.connect(self.config.history.as_uri() + '?mode=ro',
                                     uri=True, isolation_level=None, timeout=.1)
        history.db.execute('PRAGMA query_only=ON')
        plane = RuntimeEvidence(self.config.evidence,
            owner='managed:pump:qualification:' + self.config.generation, clock=self.clock)
        try:
            if not selective(plane._selective_reader()):
                return False
            tables = {row[0] for row in history.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'events', 'canonical_event_refs', 'candidates'} <= tables:
                return False
            if self.path.exists():
                _owned_path(self.path)
            db = sqlite3.connect(self.path, isolation_level=None, timeout=.1)
            try:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('PRAGMA synchronous=FULL')
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS identity(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS observations(
                      sequence INTEGER PRIMARY KEY,identity TEXT NOT NULL UNIQUE,
                      candidate TEXT NOT NULL,slot INTEGER NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL,
                      stage TEXT NOT NULL,full_complete INTEGER NOT NULL);
                    CREATE INDEX IF NOT EXISTS observation_stages ON observations(stage);
                    CREATE INDEX IF NOT EXISTS observation_full ON observations(full_complete);
                    CREATE TABLE IF NOT EXISTS candidate_state(
                      mint TEXT PRIMARY KEY,last_evaluated INTEGER NOT NULL);
                    ''')
                reference = self.target if isinstance(self.target, FreshReferenceSizing) else None
                identity_value = dict(schema=SCHEMA,
                    generation=self.config.generation,
                    source_revision=self.config.source_revision,
                    decision_target_lamports=None if reference else self.target,
                    canonical=str(self.config.evidence), history=str(self.config.history))
                if reference is not None:
                    identity_value['decision_reference'] = reference.identity()
                identity = _canonical(identity_value)
                old = db.execute('SELECT body FROM identity WHERE id=1').fetchone()
                if old and old[0] != identity:
                    raise ValueError('managed_pump_qualification_identity_changed')
                db.execute('INSERT OR IGNORE INTO identity VALUES(1,?)', (identity,))
                confirmations = ConfirmationBook.from_files()
                # Rebuild the same prospectively known creator confirmations on
                # restart from authentic native lineage, never a prior epoch.
                for (raw,) in history.db.execute(
                        "SELECT body FROM canonical_event_refs WHERE lane='pump'"):
                    if json.loads(raw)['path'] != str(self.config.evidence):
                        raise ValueError('managed_pump_foreign_qualification_reference')
                for candidate in history.candidates(lane='pump', event_prefix='pump_',
                                                     cancelled=self.cancelled.is_set):
                    mint = candidate['candidate']
                    self._reference_scope(mint, kind='pump_create', history=history, plane=plane)
                    for row in history.events('pump', mint, kind='pump_create',
                                              cancelled=self.cancelled.is_set):
                        confirmations.observe_creation(row['payload'])
                    self._reference_scope(mint, kind='pump_migration', history=history, plane=plane)
                    for row in history.events('pump', mint, kind='pump_migration',
                                              cancelled=self.cancelled.is_set):
                        confirmations.observe_graduation(mint, row['market_time'])
            except BaseException:
                db.close()
                raise
            self.db, self.history, self.plane = db, history, plane
            self.confirmations = confirmations
            return True
        finally:
            if self.history is not history:
                history.close()
                plane.close()

    def _reference_scope(self, mint, identity=None, kind=None, *, history=None, plane=None):
        # Reject an external canonical locator BEFORE the native reader opens
        # it. Native hash/provenance authentication still runs after this check.
        sql = 'SELECT body FROM canonical_event_refs WHERE lane=? AND candidate=?'
        history = history or self.history
        plane = plane or self.plane
        args = ['pump', mint]
        if identity is not None:
            sql += ' AND identity=?'
            args.append(identity)
        if kind is not None:
            sql += ' AND kind=?'
            args.append(kind)
        for (raw,) in history.db.execute(sql, args):
            ref = json.loads(raw)
            if ref['path'] != str(self.config.evidence):
                raise ValueError('managed_pump_foreign_qualification_reference')
            archive = plane.reader.db.execute(
                'SELECT archive FROM canonical_evidence WHERE identity=?',
                (ref['canonical_identity'],)).fetchone()
            if archive and archive[0]:
                manifest = plane.reader.db.execute(
                    'SELECT path FROM scoped_cold_manifests WHERE id=?',
                    (archive[0],)).fetchone()
                if manifest is None:
                    raise ValueError('managed_pump_missing_qualification_archive')
                path = Path(manifest[0])
                from .managed_native_pump import _owned_path
                directory = self.config.evidence.with_suffix('.scoped-cold')
                if (path.parent != directory or len(path.name) != 69
                        or not path.name.endswith('.zlib')
                        or any(c not in '0123456789abcdef' for c in path.name[:-5])):
                    raise ValueError('managed_pump_foreign_qualification_archive')
                _owned_path(directory, directory=True)
                _owned_path(path)

    def _checked_reference(self, raw):
        """Guard a selected locator before the unchanged native authenticator.

        A selected reference belongs to this one read only. Nothing is cached
        across source/history commits or used to advance the native cursor.
        """
        ref = json.loads(raw)
        if ref['path'] != str(self.config.evidence):
            raise ValueError('managed_pump_foreign_qualification_reference')
        archive = self.plane.reader.db.execute(
            'SELECT archive FROM canonical_evidence WHERE identity=?',
            (ref['canonical_identity'],)).fetchone()
        if archive and archive[0]:
            manifest = self.plane.reader.db.execute(
                'SELECT path FROM scoped_cold_manifests WHERE id=?',
                (archive[0],)).fetchone()
            if manifest is None:
                raise ValueError('managed_pump_missing_qualification_archive')
            path = Path(manifest[0])
            from .managed_native_pump import _owned_path
            directory = self.config.evidence.with_suffix('.scoped-cold')
            if (path.parent != directory or len(path.name) != 69
                    or not path.name.endswith('.zlib')
                    or any(c not in '0123456789abcdef' for c in path.name[:-5])):
                raise ValueError('managed_pump_foreign_qualification_archive')
            _owned_path(directory, directory=True)
            _owned_path(path)
        return ref

    def _history_event(self, mint, identity):
        """Select a compact reference once, retaining legacy-event precedence."""
        from meme_machine.runtime.journal import digest
        reference = self.history.db.execute(
            'SELECT kind,body,hash FROM canonical_event_refs WHERE lane=? AND candidate=? AND identity=?',
            ('pump', mint, identity)).fetchone()
        ref = None if reference is None else self._checked_reference(reference[1])
        legacy = self.history.db.execute(
            'SELECT body,hash FROM events WHERE lane=? AND candidate=? AND identity=?',
            ('pump', mint, identity)).fetchone()
        if legacy is not None:
            body = json.loads(legacy[0])
            if digest(body) != legacy[1]:
                raise ValueError('candidate_history_corruption')
            return body
        if reference is None:
            return None
        if digest(ref) != reference[2]:
            raise ValueError('candidate_history_corruption')
        return self.history._reference_body('pump', mint, identity, reference[0], ref)

    def _creation_events(self, mint):
        """Read/guard creation references once, with native ordering/cancellation."""
        from meme_machine.runtime.journal import digest
        references = self.history.db.execute(
            'SELECT identity,kind,body,hash FROM canonical_event_refs WHERE lane=? AND candidate=? AND kind=?',
            ('pump', mint, 'pump_create')).fetchall()
        guarded = [(identity, kind, self._checked_reference(raw), checksum)
                   for identity, kind, raw, checksum in references]
        result = []
        with self.history._startup_read(self.cancelled.is_set) as check:
            # Preserve the original legacy query and both populations. A
            # reference does not suppress an independently retained legacy row.
            sql = '''SELECT body,hash FROM events WHERE lane=? AND candidate=? AND kind=?
                ORDER BY slot,(COALESCE(json_extract(body,'$.payload._economic_order'),transaction_index) IS NULL),COALESCE(json_extract(body,'$.payload._economic_order'),transaction_index),event_index,identity'''
            for raw, checksum in self.history.db.execute(sql, ('pump', mint, 'pump_create')):
                check()
                body = json.loads(raw)
                if digest(body) != checksum:
                    raise ValueError('candidate_history_corruption')
                result.append(body)
            archives = {}
            try:
                for identity, kind, ref, checksum in guarded:
                    check()
                    if digest(ref) != checksum:
                        raise ValueError('candidate_history_corruption')
                    result.append(self.history._reference_body('pump', mint, identity, kind, ref,
                        _archive_cache=archives, _check=check))
                result.sort(key=lambda r:(r['slot'],r['payload'].get('_economic_order',r['transaction_index']) is None,
                    r['payload'].get('_economic_order',r['transaction_index']) or 0,r['event_index'],r['identity']))
            finally:
                archives.clear()
        return result

    def _evaluate(self, row, record):
        from meme_machine.lanes.pump.runner import _late_stream_signal, _late_stream_prospect
        from meme_machine.lanes.pump.pump_acceleration_strategy import POLICY, qualify
        from meme_machine.lanes.pump.pump_acceleration_evidence import curve_progress_bps
        from meme_machine.lanes.pump.solana_evidence_runtime import PUMP_SCOPE
        from meme_machine.runtime.candidate_history import economic_event_cursor
        event, mint = record['payload'], record['candidate']
        observed = dict(schema=SCHEMA, source_identity=record['identity'],
            native_kind=record['kind'], full_qualification_complete=False,
            financial_authority=False)
        kind = event.get('event_type')
        if kind == 'create':
            self.confirmations.observe_creation(event)
            return dict(observed, stage='creation_observed'), None
        if kind == 'migration' or (kind == 'trade' and event.get('real_token_reserves') == 0):
            self.confirmations.observe_graduation(mint, int(event['market_time']))
            return dict(observed, stage='postgraduation_unproven'), None
        if kind != 'trade':
            return dict(observed, stage='native_observation_only'), None
        creations = self._creation_events(mint)
        if not creations:
            return dict(observed, stage='creation_unavailable'), None
        creation = creations[0]['payload']
        now = int(self.clock())
        last = self.db.execute('SELECT last_evaluated FROM candidate_state WHERE mint=?',
                               (mint,)).fetchone()
        if last and now - last[0] < 5:
            return dict(observed, stage='native_five_second_fairness'), None
        try:
            progress = curve_progress_bps(creation['initial_real_token_reserves'],
                                          event['real_token_reserves'])
            if progress < POLICY.min_curve_progress_bps:
                return dict(observed, stage='native_below_curve_attention'), None
            at = int(event['market_time'])
            events = [e for e in self.plane.pump_events(PUMP_SCOPE, mint, at-60, at,
                      upper_slot=int(event['slot']))
                      if e.get('event_type') not in ('create', 'migration')
                      and economic_event_cursor(e) <= economic_event_cursor(event)]
            signal, _, _ = _late_stream_signal(creation, events, event, self.confirmations)
            decision, reasons = _late_stream_prospect(signal)
            observed.update(prospect=asdict(decision), prospect_reasons=list(reasons))
            if reasons:
                return dict(observed, stage='native_prospect_screened'), now
            if self.target is None:
                return dict(observed, stage='decision_target_unavailable'), now
            sizing = self.target(now) if isinstance(self.target, FreshReferenceSizing) else None
            if isinstance(self.target, FreshReferenceSizing) and (not isinstance(sizing, DecisionTarget)
                    or type(sizing.lamports) is not int or sizing.lamports <= 0):
                raise ValueError('managed_pump_decision_target_required')
            target = self.target if sizing is None else sizing.lamports
            if sizing is not None:
                observed['decision_sizing'] = sizing.provenance
            provider = self.provider
            if provider is None:
                provider = self.provider = MarketSnapshotProvider()
            snapshot = provider.snapshot(mint, now)
            at = int(snapshot['market_time'])
            events = [e for e in self.plane.pump_events(PUMP_SCOPE, mint, at-60, at,
                      upper_slot=int(snapshot['slot']))
                      if e.get('event_type') not in ('create', 'migration')]
            if sizing is not None:
                sizing.validate(self.clock())
            optimistic = full_late_signal(creation, events, snapshot, 0,
                                          self.confirmations, target)
            qualification = qualify(optimistic)
            stage = 'native_optimistic_rejection'
            if qualification.qualified:
                concentration = provider.concentration(mint, snapshot)
                if sizing is not None:
                    sizing.validate(self.clock())
                qualification = qualify(full_late_signal(creation, events, snapshot,
                    concentration, self.confirmations, target))
                stage = 'native_full_qualification'
            if sizing is not None:
                sizing.validate(self.clock())
            return dict(observed, stage=stage, qualification=asdict(qualification),
                full_qualification_complete=True,
                snapshot_sha256=hashlib.sha256(_canonical(snapshot).encode()).hexdigest()), now
        except (KeyError, TypeError, ArithmeticError) as error:
            return dict(observed, stage='native_evidence_incomplete',
                        failure_type=type(error).__name__), now
        except Exception as error:
            from meme_machine.solana_evidence_plane import EvidenceUnavailable, EvidenceConflict
            from meme_machine.lanes.pump.solana_evidence_plane import EvidenceConflict as LaneConflict
            from meme_machine.lanes.pump.provider import Unavailable
            if isinstance(error, (EvidenceConflict, LaneConflict)):
                raise
            if not isinstance(error, (ValueError, EvidenceUnavailable, Unavailable)):
                raise
            # Provider/IPC exceptions may contain URLs or credentials. Retain
            # their class only; provider usage/failure journals own the detail.
            return dict(observed, stage='native_evidence_incomplete',
                        failure_type=type(error).__name__), now

    def step(self):
        """At most PAGE authenticated native inputs; commit before cursor advance."""
        if self.cancelled.is_set() or not self._open():
            return dict(schema=SCHEMA, initialization_pending=True,
                        full_qualification_proven=False, financial_authority=False)
        from meme_machine.solana_evidence_plane import decode_body
        sequence = self.db.execute('SELECT COALESCE(max(sequence),0) FROM observations').fetchone()[0]
        reader = self.plane._selective_reader()
        rows = reader.discovery(sequence, as_of=self.clock(), limit=PAGE)
        processed = 0
        with self.db:
            # FULL durability once per bounded native page, rather than one
            # fsync per trade. This private writer never owns a source lock.
            self.db.execute('BEGIN IMMEDIATE')
            for row in rows:
                if self.cancelled.is_set():
                    break
                canonical = decode_body(row[1], reader.db)
                mint, identity = canonical['payload']['event']['mint'], canonical['identity']
                history_identity = 'pump-source:' + identity
                record = self._history_event(mint, history_identity)
                if record is None:
                    # Canonical delivery precedes CandidateHistory publication.
                    # Keep this exact native cursor pending until publication.
                    break
                native_event = canonical['payload']['event']
                if (record['slot'] != canonical['slot'] or record['candidate'] != mint
                        or record['market_time'] != canonical['market_time']
                        or record['event_index'] != canonical['event_index']
                        or record['kind'] != 'pump_' + native_event['event_type']
                        or any(record['payload'].get(key) != value
                               for key, value in native_event.items())):
                    raise ValueError('managed_pump_qualification_source_identity')
                observed, evaluated = self._evaluate(row, record)
                encoded = _canonical(observed)
                self.db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)',
                    (row[0], identity, mint, record['slot'], encoded,
                     hashlib.sha256(encoded.encode()).hexdigest(), observed['stage'],
                     int(observed['full_qualification_complete'])))
                if evaluated is not None:
                    self.db.execute('INSERT OR REPLACE INTO candidate_state VALUES(?,?)',
                                    (mint, evaluated))
                processed += 1
        result = self.snapshot()
        result['processed_this_turn'] = processed
        return result

    def snapshot(self):
        if self.db is None:
            return dict(schema=SCHEMA, initialization_pending=True,
                        full_qualification_proven=False, financial_authority=False)
        reader = self.plane._selective_reader()
        incoming, latest = reader.db.execute("SELECT count(*),max(sequence) FROM candidate_outbox WHERE scope='program:pump'").fetchone()
        completed, cursor = self.db.execute('SELECT count(*),max(sequence) FROM observations').fetchone()
        stages = dict(self.db.execute('SELECT stage,count(*) FROM observations GROUP BY stage'))
        full = self.db.execute('SELECT count(*) FROM observations WHERE full_complete=1').fetchone()[0]
        return dict(schema=SCHEMA, incoming_native_events=incoming,
            durably_observed_native_events=completed, native_event_backlog=incoming-completed,
            latest_source_sequence=latest, durable_sequence=cursor, stages=stages,
            full_qualifications=full, full_qualification_proven=False,
            qualification_scope='pump_current_late_curve',
            postgraduation_and_survivor_qualification_proven=False,
            decision_reference=self.target.identity() if isinstance(self.target, FreshReferenceSizing) else None,
            decision_target_available=self.target.available(self.clock())
                if isinstance(self.target, FreshReferenceSizing) else self.target is not None,
            financial_authority=False)

    def close(self):
        if self.history is not None:
            self.history.close()
        if self.plane is not None:
            self.plane.close()
        if self.db is not None:
            self.db.close()


async def read_qualifications(config, stop, *, publish=None, decision_target=None):
    """One SQL/thread owner; cancellation joins its bounded native evidence turn."""
    worker = QualificationReader(config, decision_target=decision_target)
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pump-qualification')
    pending = None
    async def stop_admissions():
        await stop.wait()
        worker.cancelled.set()
    stopper = asyncio.create_task(stop_admissions())
    try:
        while not stop.is_set():
            pending = loop.run_in_executor(executor, worker.step)
            try:
                result = await asyncio.shield(pending)
            except BaseException as error:
                from meme_machine.solana_evidence_plane import EvidenceUnavailable, EvidenceConflict
                from meme_machine.runtime.stop import Shutdown
                if isinstance(error, Shutdown) and worker.cancelled.is_set():
                    pending = None
                    break
                code = getattr(error, 'sqlite_errorcode', 0) & 255
                if (isinstance(error, EvidenceConflict)
                        or not isinstance(error, EvidenceUnavailable)
                        and not isinstance(error, sqlite3.OperationalError)
                        or isinstance(error, sqlite3.OperationalError)
                        and code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
                                         sqlite3.SQLITE_INTERRUPT)):
                    raise
                result = dict(schema=SCHEMA, observation_unavailable=True,
                    failure_type=type(error).__name__,
                    full_qualification_proven=False, financial_authority=False)
            pending = None
            if publish is not None:
                publish(result)
            if result.get('processed_this_turn') == PAGE:
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(stop.wait(), .1)
            except TimeoutError:
                pass
    finally:
        worker.cancelled.set()
        stopper.cancel()
        await asyncio.gather(stopper, return_exceptions=True)
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        await loop.run_in_executor(executor, worker.close)
        executor.shutdown(wait=True)
