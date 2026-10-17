"""Disposable Pons native observation projection, with explicit parity limits.

The real MarketScout, Broker, strict raw-event reader, economic normalizer and
SQLite Plane run on a fixed public-provider corpus. This does not construct a
cohort, sleeve, native paper book, shared authority or managed-provider client.
Public receipt/header agreement never becomes canonical acquisition authority.

The caller owns pacing, response/request/storage ceilings, cancellation and the
capture/replay corpus. Its RPC contract is ``call(endpoint, method, params)``.
Native logical batches become individual physical public reads here; this is
disclosed rather than represented as production batching or full capacity.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path
import stat
import time


ROBINHOOD = 'https://rpc.mainnet.chain.robinhood.com'
SCHEMA = 'isolated-native-pons-projection-v1'
MARKER = 'isolated-native-pons.json'
NAMESPACE = 'isolated_public_pons_economic'
MAX_EVENTS = 4096
MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_RANGE_BLOCKS = 40
PROVENANCE = dict(authority='public_receipt_header_consistency_only',
                  allocation_authority=False, canonical_completeness=False,
                  scope=SCHEMA)
OMISSIONS = (
    'managed canonical provider admission, pacing, HTTP 429 recovery and cache',
    'native physical JSON-RPC batches and sequencer websocket acquisition',
    'Current complete canonical window hydration and qualification',
    'CurrentHistory canonical range publication and Survivor canonical history',
    'native reservations, held-position protection, exits and financial recovery',
    'production historical replay, cold archive volume and sustained full-market capacity',
)


class PonsProjectionUnavailable(RuntimeError):
    """Sanitized failure preserving incomplete disposable work."""


def _require(condition, reason):
    if not condition:
        raise PonsProjectionUnavailable(reason)


class _PublicRpc:
    """Use root-owned bounded acquisition without constructing a native provider."""
    endpoint = ROBINHOOD
    canonical_authority = False
    METHODS = frozenset(('eth_getLogs', 'eth_getBlockByNumber',
                         'eth_getTransactionReceipt'))

    def __init__(self, rpc):
        self.rpc = rpc
        self.calls = 0

    def call(self, method, params, *, scope):
        _require(method in self.METHODS and type(params) is list,
                 'pons_public_method_refused')
        self.calls += 1
        return self.rpc.call(ROBINHOOD, method, params)

    def batch(self, calls, *, scope):
        _require(type(calls) is list and 1 <= len(calls) <= 4,
                 'pons_logical_batch_bound')
        return [self.call(method, params, scope=scope) for method, params in calls]


class PonsNativeProjection:
    """Real native discovery/candidate persistence on new, owned disposable state.

    ``consume(first,last,rpc,observed_at=...)`` captures native read requests via
    the caller's fixed-endpoint RPC. Supplying the same recorded responses and
    original observation clock permits exact corpus replay on another checkout.
    ``reopen()`` performs the actual Broker retained-candidate startup path.
    """
    def __init__(self, root):
        raw = Path(root).absolute()
        _require(not any(p.is_symlink() for p in (raw, *raw.parents)),
                 'pons_projection_symlink_refused')
        _require(not any((p / 'portfolio.sqlite').exists() or
                         (p / 'shared-capital.sqlite').exists()
                         for p in (raw, *raw.parents)),
                 'pons_projection_financial_ancestor_refused')
        if not raw.exists():
            raw.mkdir(mode=0o700)
        info = raw.stat()
        _require(raw.is_dir() and info.st_uid == os.geteuid() and
                 stat.S_IMODE(info.st_mode) == 0o700,
                 'pons_projection_private_owned_directory_required')
        self.root = raw.resolve()
        marker = self.root / MARKER
        allowed = {MARKER, 'projection.lock', 'candidates.sqlite',
                   'candidates.sqlite-wal', 'candidates.sqlite-shm',
                   'opportunity-pipeline.sqlite', 'opportunity-pipeline.sqlite-wal',
                   'opportunity-pipeline.sqlite-shm'}
        _require(all(p.name in allowed and p.is_file() and not p.is_symlink()
                     and p.stat().st_uid == os.geteuid() for p in self.root.iterdir()),
                 'pons_projection_foreign_state_refused')
        expected = dict(schema=SCHEMA, allocation_authority=False)
        if marker.exists():
            _require(json.loads(marker.read_text()) == expected,
                     'pons_projection_marker_mismatch')
        else:
            _require(not any(self.root.iterdir()), 'pons_projection_unmarked_state_refused')
            with marker.open('x') as handle:
                handle.write(json.dumps(expected, sort_keys=True))
        self._lock = (self.root / 'projection.lock').open('a')
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self._lock.close()
            raise
        self._closed = True
        self._clock = time.time()
        self.restore_seconds = []
        self.history_reads = 0
        self.native_request_calls = 0
        try:
            self._open()
        except BaseException:
            self._lock.close()
            raise

    def _open(self):
        from meme_machine.runtime.robinhood.pons import Broker
        from meme_machine.lanes.pons.pons_natural_observation import MarketScout
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        from meme_machine.lanes.pons.pipeline import Pipeline
        started = time.monotonic()
        self.broker = Broker(self.root / 'candidates.sqlite', POLICY_HASH,
            clock=lambda: self._clock, source=ROBINHOOD, config=SCHEMA)
        try:
            self.plane = self.broker.plane
            self.plane.db.execute('PRAGMA max_page_count=16384')
            self.scout = MarketScout(self.plane)
            self.pipeline = Pipeline(self.root / 'opportunity-pipeline.sqlite',
                                     'pons', POLICY_HASH)
            self.pipeline.db.execute('PRAGMA max_page_count=16384')
            self._closed = False
            self.restore_seconds.append(time.monotonic() - started)
            self._check_bounds()
        except BaseException:
            self.broker.close()
            raise

    def _check_bounds(self):
        for name in ('candidates.sqlite', 'opportunity-pipeline.sqlite'):
            path = self.root / name
            _require(sum(p.stat().st_size for p in
                (path, Path(str(path)+'-wal'), Path(str(path)+'-shm')) if p.exists())
                <= MAX_DATABASE_BYTES, 'pons_projection_storage_bound')
        count = self.plane.db.execute('SELECT COUNT(*) FROM evidence WHERE namespace=?',
                                     (NAMESPACE,)).fetchone()[0]
        _require(count <= MAX_EVENTS, 'pons_projection_event_bound')

    def consume(self, first, last, rpc, *, observed_at=None):
        """Keep native raw/candidate cursors distinct from receipt-linked decoding.

        A native MarketScout range can commit before public receipt acquisition
        fails. Only ``decoded_cursor`` covers completed economic projection;
        neither cursor asserts managed canonical completeness.
        """
        _require(not self._closed, 'pons_projection_closed')
        _require(type(first) is int and type(last) is int and
                 0 <= first <= last < 2**63 and last-first < MAX_RANGE_BLOCKS,
                 'pons_projection_range_bound')
        prior_cursor = self.plane.checkpoint_read('isolated_public_pons_decoded_cursor')
        _require(prior_cursor is None or first <= prior_cursor + 1,
                 'pons_projection_noncontiguous_range')
        stamp = time.time() if observed_at is None else observed_at
        _require(type(stamp) in (int, float) and math.isfinite(stamp) and stamp >= 0,
                 'pons_projection_observation_clock')
        self._clock = float(stamp)
        adapter = _PublicRpc(rpc)
        before = self.snapshot()
        observed = []

        def nominate(event, original_clock):
            self.broker.enqueue(event, now=original_clock,
                needs_work=event['topics'][0].lower() == self.scout.curve_topics[0])

        started = time.monotonic()
        try:
            # Exact native range filtering, saturated-page handling, durable
            # raw journaling, candidate generations and original deadlines.
            observed = self.scout.read_market(adapter, first, last, nominate=nominate)
            self.broker.report_to(self.pipeline, drain=True)
            headers, receipts = {}, {}
            from meme_machine.lanes.pons.pons import raw_event, curve_abi
            from meme_machine.lanes.pons.pons_selective_continuation import normalized_trade
            for event in observed:
                self._check_bounds()
                identity = self.broker.observation_id(event)
                old = self.plane.evidence(NAMESPACE, identity)
                if old is None:
                    count = self.plane.db.execute('SELECT COUNT(*) FROM evidence WHERE namespace=?',
                                                 (NAMESPACE,)).fetchone()[0]
                    _require(count < MAX_EVENTS, 'pons_projection_event_bound')
                block = event['blockNumber']
                if block not in headers:
                    headers[block] = adapter.call('eth_getBlockByNumber', [block, False],
                                                 scope='isolated_public_projection')
                tx = event['transactionHash']
                if tx not in receipts:
                    receipts[tx] = adapter.call('eth_getTransactionReceipt', [tx],
                                               scope='isolated_public_projection')
                authentic = raw_event(curve_abi(), event, address=event['address'],
                    receipt=receipts[tx], header=headers[block],
                    observed_at=old[0]['raw_event']['observed_at'] if old else int(stamp),
                    confirmation='confirmed')
                economic = normalized_trade(authentic['decoded'], identity=identity,
                                            event_at=authentic['event_at'])
                # This namespace is deliberately distinct from managed caches,
                # rolling canonical history, cohort and financial checkpoints.
                self.plane.put(NAMESPACE, identity,
                    dict(raw_event=authentic, economic=economic), PROVENANCE)
                self.history_reads += 1
                retained = self.plane.evidence(NAMESPACE, identity)
                _require(retained is not None and retained[1] == PROVENANCE,
                         'pons_projection_history_unverified')
                _require(retained[0]['economic'] == economic,
                         'pons_projection_history_mismatch')
            self.plane.checkpoint('isolated_public_pons_decoded_cursor',
                                 max(last, prior_cursor) if prior_cursor is not None else last)
            self.plane.checkpoint('isolated_public_pons_failure', None)
            self.scout.maintain()
            self._check_bounds()
        except BaseException as error:
            # Keep the native gap and all committed rows; never acknowledge an
            # incomplete range or erase a failed acquisition for a green report.
            self.plane.checkpoint('isolated_public_pons_failure',
                dict(first=first, last=last, error_type=type(error).__name__, complete=False))
            raise
        finally:
            self.native_request_calls += adapter.calls
        after = self.snapshot()
        return dict(first=first, last=last, native_curve_observations=len(observed),
                    durable_economic_added=after['durable_economic_events']-
                        before['durable_economic_events'],
                    seconds=time.monotonic()-started, snapshot=after)

    def snapshot(self):
        _require(not self._closed, 'pons_projection_closed')
        from meme_machine.runtime.journal import digest
        with self.plane.lock:
            count = self.plane.db.execute('SELECT COUNT(*) FROM evidence WHERE namespace=?',
                                         (NAMESPACE,)).fetchone()[0]
            pending = self.plane.db.execute("SELECT COUNT(*) FROM candidates WHERE lane='pons' AND pending=1").fetchone()[0]
            corpus = [(key, json.loads(body), json.loads(provenance)) for key, body, provenance
                in self.plane.db.execute('SELECT key,body,provenance FROM evidence WHERE namespace=? ORDER BY key',
                                        (NAMESPACE,))]
        return dict(schema=SCHEMA, verdict='PARTIAL', allocation_authority=False,
            production_equivalent=False, full_market_readiness_proven=False,
            canonical_completeness=False, parity_omissions=list(OMISSIONS),
            scout=self.scout.snapshot(), native_candidates=self.broker.telemetry(),
            native_pipeline=self.pipeline.snapshot(), pending_native_candidates=pending,
            durable_economic_events=count, economic_corpus_sha256=digest(corpus),
            history_reads_this_process=self.history_reads,
            native_request_calls_this_process=self.native_request_calls,
            restoration_seconds=list(self.restore_seconds),
            decoded_cursor=self.plane.checkpoint_read('isolated_public_pons_decoded_cursor'),
            incomplete=self.plane.checkpoint_read('isolated_public_pons_failure'))

    def reopen(self):
        """Restore exactly this disposable native candidate/history database."""
        _require(not self._closed, 'pons_projection_closed')
        self.pipeline.close()
        self.broker.close()
        self._closed = True
        self._open()
        with self.plane.lock:
            keys = [row[0] for row in self.plane.db.execute(
                'SELECT key FROM evidence WHERE namespace=? ORDER BY key', (NAMESPACE,))]
        for key in keys:
            retained = self.plane.evidence(NAMESPACE, key)
            _require(retained is not None and retained[1] == PROVENANCE,
                     'pons_projection_history_unverified')
            self.history_reads += 1
        return self.snapshot()

    def close(self):
        if not self._closed:
            try:
                self.pipeline.close()
            finally:
                self.broker.close()
                self._closed = True
        if not self._lock.closed:
            self._lock.close()

