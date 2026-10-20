"""Isolated managed Pons acquisition, native history and qualification workload.

Run in its own protected child process. The caller supplies the existing managed
read credential, provider profile and a fresh generation directory. This module
never constructs a cohort, native book, sleeve, portfolio or financial authority.
It deliberately reports qualification failures separately from complete market
range persistence; a caught exception is never a completed range.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import threading
import time

from meme_machine.runtime.journal import canonical, digest

SCHEMA = 'isolated-managed-pons-v1'
MAX_STORAGE_BYTES = 512 * 1024**2
ENVIRONMENT = frozenset({
    'MM_ROBINHOOD_READ_RPC_URL', 'MM_ROBINHOOD_DLMM_RPC_URL',
    'MM_ROBINHOOD_STATE_DIR', 'MM_PROVIDER_DB', 'MM_RPC_CACHE_DB',
    'MM_RUNTIME_LANE', 'MM_PONS_OBSERVATION_ROUTE', 'MM_RPC_CAPABILITIES',
    'MM_PONS_LOG_CAPABILITY_FILE', 'MM_PROVIDER_OPERATION_MODE',
    'MM_CONTINUOUS_PROVIDER_ENVELOPE', 'MM_PROVIDER_USAGE_DB',
})


def require(condition, reason):
    if not condition:
        raise ValueError('managed_pons_' + reason)


def private_file(path, *, parent=None):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and
            not any(p.is_symlink() for p in (path,*path.parents)), 'private_file_path')
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
            info.st_nlink == 1 and not info.st_mode & 0o077, 'private_file_permissions')
    require(parent is None or path.parent == parent, 'private_file_parent')
    return path


def atomic_json(path, value):
    """Private, atomic evidence; never follow an inherited destination link."""
    path = Path(path)
    require(not path.is_symlink(), 'output_symlink')
    temporary = path.with_name(path.name + '.new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def private_root(root, generation):
    root = Path(root).absolute()
    require(type(generation) is str and 8 <= len(generation) <= 128 and
            all(c.isalnum() or c in '-_' for c in generation), 'generation_identity')
    require(root.is_dir() and root.resolve() == root and
            not any(p.is_symlink() for p in (root, *root.parents)), 'private_root')
    info = root.stat()
    require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
            'private_root_permissions')
    for ancestor in (root, *root.parents):
        require(not any((ancestor / name).exists() or (ancestor / name).is_symlink()
            for name in ('portfolio.sqlite', 'shared-capital.sqlite', 'native-genesis.json')),
            'financial_ancestor')
    require(not any(k.startswith('MM_') and k not in ENVIRONMENT for k in os.environ),
            'inherited_authority_environment')
    bindings = dict(MM_ROBINHOOD_STATE_DIR=root, MM_PROVIDER_DB=root/'provider.sqlite',
                    MM_RPC_CACHE_DB=root/'evidence.sqlite')
    for name, expected in bindings.items():
        require(os.environ.get(name) == str(expected), 'isolated_path_binding')
    usage = os.environ.get('MM_PROVIDER_USAGE_DB')
    if usage:
        private_file(usage,parent=root.parent)
    require(os.environ.get('MM_RUNTIME_LANE') == 'pons' and
            os.environ.get('MM_PONS_OBSERVATION_ROUTE') == 'canonical_primary',
            'managed_lane_binding')
    require(os.environ.get('MM_PROVIDER_OPERATION_MODE') == 'CONTINUOUS' and
            os.environ.get('MM_CONTINUOUS_PROVIDER_ENVELOPE'), 'production_profile_required')
    private_file(os.environ['MM_CONTINUOUS_PROVIDER_ENVELOPE'],parent=root.parent)
    marker = root/'managed-pons.json'
    expected = dict(schema=SCHEMA, generation=generation, allocation_authority=False)
    allowed = {'managed-pons.json', 'managed-pons.lock', 'native.sqlite',
        'native.sqlite-wal', 'native.sqlite-shm', 'provider.sqlite', 'provider.sqlite-wal',
        'provider.sqlite-shm', 'evidence.sqlite', 'evidence.sqlite-wal', 'evidence.sqlite-shm',
        'telemetry.json', 'result.json', 'telemetry.json.new', 'result.json.new'}
    if marker.exists():
        require(json.loads(marker.read_text()) == expected, 'generation_marker')
        require(all(p.name in allowed for p in root.iterdir()), 'foreign_state')
        for p in root.iterdir(): private_file(p,parent=root)
    else:
        require(not any(root.iterdir()), 'fresh_generation_required')
        atomic_json(marker, expected)
    return root


class ManagedPonsLane:
    """Production RPC/admission and native processing, with fresh storage only.

    One market writer and one native Current qualification worker share the
    real Broker lock and durable immutable cache. Qualification never dispatches
    lifecycle work. Raw authenticated ranges remain available for decode replay.
    """
    def __init__(self, root, generation, *, cancel=None):
        self.root = private_root(root, generation)
        self.generation = generation
        self.cancel = cancel or (lambda: False)
        # Independent library use also creates private SQLite files regardless
        # of the launching shell's umask. Existing files were authenticated above.
        for name in ('managed-pons.lock','native.sqlite','provider.sqlite','evidence.sqlite'):
            fd = os.open(self.root/name,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
            os.close(fd)
        self.owner = (self.root/'managed-pons.lock').open('a')
        fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.counts = Counter(); self.failure_counts = Counter()
        self.closed = False; self.started = time.time(); self.latest = None
        self.head_sample_at = -float('inf'); self.future = None
        self.future_work = None; self.future_started = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pons-capacity-current')
        from meme_machine.runtime.robinhood.provider_authority import reference
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        from meme_machine.runtime.robinhood.pons import Broker, durable_cache, shared_evidence_domain
        from meme_machine.lanes.pons.pons_natural_observation import MarketScout
        from meme_machine.lanes.pons.pons_current_history import CurrentHistory
        from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
        self.endpoint = reference()
        try:
            self.broker = Broker(self.root/'native.sqlite', POLICY_HASH, clock=time.time,
                source=self.endpoint, config=digest([SCHEMA, generation]), startup_cancel=self.cancel)
            self.plane = self.broker.plane
            self.scout = MarketScout(self.plane)
            self.history = CurrentHistory(self.plane, self.endpoint)
            domain = shared_evidence_domain(self.endpoint)
            self.cache = durable_cache(self.plane, domain)
            self.context = SelectiveEvidenceContext(self.endpoint, cache=self.cache)
            self.rpc = self._discovery()
            with self.plane.lock:
                self.plane.db.executescript('''
                    CREATE TABLE IF NOT EXISTS managed_ranges(
                        first INTEGER PRIMARY KEY,last INTEGER NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS managed_raw(
                        id TEXT PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS managed_heads(
                        seq INTEGER PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL);
                ''')
            self.baseline = self.plane.checkpoint_read('managed_baseline')
            self.cursor = self.plane.checkpoint_read('managed_durable_cursor')
            head = self.plane.db.execute('SELECT body,hash FROM managed_heads ORDER BY seq DESC LIMIT 1').fetchone()
            if head:
                body = json.loads(head[0]); require(digest(body) == head[1], 'retained_head_digest')
                self.latest = int(body['header']['number'],16)
        except BaseException:
            self.pool.shutdown(wait=False, cancel_futures=True)
            if hasattr(self, 'broker'): self.broker.close()
            self.owner.close(); raise

    def _check(self):
        require(not self.closed, 'closed')
        if self.cancel():
            raise InterruptedError('managed_pons_cancelled')
        require(sum(p.stat().st_size for p in self.root.iterdir() if p.is_file())
                <= MAX_STORAGE_BYTES, 'storage_bound')

    def _discovery(self):
        from meme_machine.lanes.pons.provider_topology import configured_discovery_rpc
        rpc = configured_discovery_rpc(self.endpoint, limit=200, per_scope=190, retries=1,
                                       timeout=5, max_response=2_000_000)
        rpc.verify_chain()
        return rpc

    def _batch(self, calls, scope):
        """Actual native physical batches; rotate only the existing session budget."""
        out = []
        for offset in range(0, len(calls), 50):
            self._check()
            group = calls[offset:offset+50]
            if self.rpc.used + len(group) > 190 or self.rpc.counts[scope] + len(group) > 180:
                receipt_pins = getattr(self.rpc,'evidence_receipts',{})
                self.rpc = self._discovery()
                self.rpc.evidence_receipts = receipt_pins
            result = self.rpc.batch(group, scope=scope)
            require(type(result) is list and len(result) == len(group), 'native_batch_shape')
            out.extend(result)
        return out

    def sample_head(self):
        self._check()
        header, = self._batch([('eth_getBlockByNumber', ['latest', False])], 'pons_selective_frontier')
        require(type(header) is dict and type(header.get('number')) is str and
                type(header.get('hash')) is str, 'head_identity')
        number = int(header['number'], 16)
        require(self.latest is None or number >= self.latest, 'head_rewind')
        body = dict(generation=self.generation, header=header, observed_at=time.time(),
                    monotonic=time.monotonic(), provider=self.endpoint)
        with self.plane.transaction():
            self.plane.db.execute('INSERT INTO managed_heads(body,hash) VALUES(?,?)',
                                  (canonical(body), digest(body)))
            if self.baseline is None:
                self.baseline = self.cursor = number
                self._checkpoint('managed_baseline', number)
                self._checkpoint('managed_durable_cursor', number)
        self.latest = number; self.head_sample_at = time.monotonic()
        return number

    def _checkpoint(self, key, value):
        self.plane.db.execute('INSERT INTO runtime VALUES(?,?) ON CONFLICT(key) '
            'DO UPDATE SET body=excluded.body', (key, canonical(value)))

    def consume(self, first, last):
        """Complete a contiguous managed market interval, including empty blocks."""
        self._check()
        # The unchanged production discovery coalescing bound is ten blocks.
        from meme_machine.lanes.pons.pons_natural_observation import DISCOVERY_MAX_BLOCKS
        require(type(first) is int and type(last) is int and self.cursor is not None and
                first == self.cursor+1 and first <= last <= self.latest and
                last-first < DISCOVERY_MAX_BLOCKS, 'contiguous_range')
        def nominate(event, observed):
            self.broker.enqueue(event, now=observed,
                needs_work=event['topics'][0].lower() == self.scout.curve_topics[0])
            # Hydration starts at the native nomination clock, while market
            # receipt persistence continues independently in the writer.
            self.poll_candidate()
        if self.rpc.used > 130 or self.rpc.counts['pons_scout_discovery'] > 120:
            self.rpc = self._discovery()
        raw = self.scout.read_market(self.rpc, first, last, nominate=nominate)
        # Fetch each immutable receipt/header once, then fence numeric membership
        # after receipt completion. Native decoder remains the evidence authority.
        blocks = dict.fromkeys(e['blockHash'] for e in raw)
        transactions = dict.fromkeys((e['transactionHash'], e['blockHash']) for e in raw)
        labels = []; calls = []; headers = {}; receipts = {}
        for bh in blocks:
            value = self.cache.header_by_hash(bh)
            if value is None:
                labels.append(('header', bh)); calls.append(('eth_getBlockByHash', [bh, False]))
            else: headers[bh] = value
        for tx, bh in transactions:
            value = self.cache.receipt(tx, bh)
            if value is None:
                labels.append(('receipt', (tx, bh)))
                calls.append(('eth_getTransactionReceipt', [tx]))
            else: receipts[(tx, bh)] = value
        self.rpc.evidence_receipts = {tx:bh for tx,bh in transactions}
        try:
            for (kind, key), value in zip(labels, self._batch(calls, 'pons_selective_window')):
                if kind == 'header': headers[key] = value
                else: receipts[key] = value
        finally:
            self.rpc.evidence_receipts = {}
        numbers = sorted({int(e['blockNumber'], 16) for e in raw} | {first, last})
        fences = self._batch([('eth_getBlockByNumber', [hex(n), False]) for n in numbers],
                             'pons_selective_window_coverage')
        canonical_headers = dict(zip(numbers, fences))
        for n, header in canonical_headers.items():
            require(type(header) is dict and header.get('number') == hex(n) and
                    type(header.get('hash')) is str, 'canonical_header_identity')
        require(canonical_headers[last]['hash'] ==
                self.plane.checkpoint_read('pons_scout_market_boundary')['hash'], 'range_end_membership')
        from meme_machine.lanes.pons.pons import raw_event, curve_abi
        from meme_machine.lanes.pons.pons_selective_continuation import normalized_trade
        rows = []; by_curve = {}
        observed = int(time.time())
        for event in raw:
            self._check()
            bh = event['blockHash']; n = int(event['blockNumber'], 16)
            require(headers[bh] == canonical_headers[n], 'event_canonical_membership')
            authentic = raw_event(curve_abi(), event, address=event['address'],
                receipt=receipts[(event['transactionHash'], bh)], header=headers[bh],
                observed_at=observed, confirmation='confirmed')
            identity = f"{n}:{event['transactionHash']}:{int(event['logIndex'],16)}"
            economic = normalized_trade(authentic['decoded'], identity=identity,
                                        event_at=authentic['event_at'])
            economic['canonical_order'] = [int(event[k], 16) for k in
                                          ('blockNumber','transactionIndex','logIndex')]
            body = dict(generation=self.generation, event=event, header=headers[bh],
                receipt=receipts[(event['transactionHash'], bh)], observed_at=observed,
                economic=economic, provider=self.endpoint)
            rows.append((identity, body)); by_curve.setdefault(event['address'].lower(), []).append(economic)
        lower = int(canonical_headers[first]['timestamp'], 16)
        end = canonical_headers[last]
        interval = dict(generation=self.generation, first=first, last=last,
            incoming_unit='robinhood_block', provider=self.endpoint,
            from_header=canonical_headers[first], through_header=end,
            event_ids=[identity for identity, _ in rows], events_sha256=digest(rows),
            observed_at=time.time(), complete=True)
        # Native rolling history keeps its existing independent transaction.
        # The authoritative measured frontier commits with its complete raw
        # replay corpus below. A crash may leave history/scout work ahead and
        # requires this same interval to be reauthenticated before completion.
        with self.plane.lock:
            curves = {row[0] for row in self.plane.db.execute(
                'SELECT curve FROM pons_current_history WHERE domain=?', (self.history.domain,))}
        for curve in sorted(curves | set(by_curve)):
            events = by_curve.get(curve, [])
            previous = self.history.get(curve)
            self.history.remember(curve, end, events, from_time=lower,
                delta_from=previous['block'] if previous and previous['block']==first-1 else None,
                coverage=dict(first_block=first,last_block=last,end_hash=end['hash'],
                              events_sha256=digest(events)))
        with self.plane.transaction():
            for identity, body in rows:
                old = self.plane.db.execute('SELECT body,hash FROM managed_raw WHERE id=?',
                                            (identity,)).fetchone()
                require(old is None or (digest(json.loads(old[0])) == old[1] and
                    json.loads(old[0]) == body), 'raw_conflict')
                self.plane.db.execute('INSERT OR IGNORE INTO managed_raw VALUES(?,?,?)',
                                      (identity, canonical(body), digest(body)))
            self.plane.db.execute('INSERT INTO managed_ranges VALUES(?,?,?,?)',
                                  (first, last, canonical(interval), digest(interval)))
            self._checkpoint('managed_durable_cursor', last)
            self._checkpoint('managed_incomplete', None)
        self.cursor = last; self.counts['economic_events'] += len(rows)
        for bh, header in headers.items(): self.cache.remember_header(header)
        for (tx, bh), receipt in receipts.items(): self.cache.remember_receipt(tx, bh, receipt)
        return interval

    def poll_candidate(self, *, submit=True):
        if self.future is not None and self.future.done():
            work = self.future_work
            try:
                evaluation = self.future.result()
                if self.broker.finish(work, evaluation, time.monotonic()-self.future_started):
                    self.broker.acknowledge(work)
                    self.counts['candidate_completed'] += 1
                    self.counts['candidate_qualified'] += bool(evaluation['vector'].get('current_threshold_pass'))
                else: self.counts['candidate_superseded'] += 1
            except Exception as error:
                from meme_machine.runtime.robinhood.provider_authority import failure_class
                reason = failure_class(error)
                self.broker.failure(work, reason)
                self.failure_counts['qualification:' + reason] += 1
            finally:
                self.future = self.future_work = None
        if submit and self.future is None and not self.cancel():
            work = self.broker.pop()
            if work is not None:
                from meme_machine.lanes.pons.pons_selective_acquisition import evaluate_candidate
                from meme_machine.lanes.pons.pons_selective_paper import STRATEGY_CAPITAL_QUOTE
                self.context.generation_guard = lambda: self.plane.current(work['work']) and not self.cancel()
                self.future_work = work; self.future_started = time.monotonic()
                observed_mono = time.monotonic() - max(0, time.time()-work['queued_at'])
                self.future = self.pool.submit(evaluate_candidate, self.endpoint, work['event'], [],
                    strategy_capital_quote=STRATEGY_CAPITAL_QUOTE,
                    evidence_observed_at=work['queued_at'], evidence_observed_monotonic=observed_mono,
                    evidence_context=self.context, canonical_refresh=work.get('canonical_refresh', False))

    def snapshot(self):
        with self.plane.lock:
            durable = self.plane.checkpoint_read('managed_durable_cursor')
            raw = self.plane.db.execute('SELECT COUNT(*) FROM managed_raw').fetchone()[0]
            ranges = self.plane.db.execute('SELECT COUNT(*) FROM managed_ranges').fetchone()[0]
            pending = self.plane.db.execute('SELECT COUNT(*) FROM candidates WHERE pending=1').fetchone()[0]
        return dict(schema=SCHEMA,generation=self.generation,allocation_authority=False,
            provider=self.endpoint,unit='robinhood_block',baseline=self.baseline,
            incoming_frontier=self.latest,durable_frontier=durable,
            incoming=None if self.latest is None else self.latest-self.baseline,
            durable=None if durable is None else durable-self.baseline,
            incoming_blocks=None if self.latest is None else self.latest-self.baseline,
            durable_blocks=None if durable is None else durable-self.baseline,
            backlog=None if self.latest is None else self.latest-durable,
            durable_ranges=ranges,economic_events=raw,pending_candidates=pending,
            candidate_worker_active=self.future is not None,
            counts=dict(self.counts),failures=dict(self.failure_counts),
            provider_usage=self.rpc.shared_admission.telemetry(),
            storage_bytes=sum(p.stat().st_size for p in self.root.iterdir() if p.is_file()),
            scope=dict(managed_admission=True,native_batches=True,native_decode=True,
                native_current_history=True,native_current_history_persistence=True,
                current_qualification=True,complete_current_qualification=False,
                survivor_qualification=False,financial_entries=False,
                held_protection_live=False,
                sizing_input='unchanged_native_unfunded_reference_constant'),observed_at=time.time())

    def replay(self):
        """Replay every authenticated economic row with the real native decoder."""
        from meme_machine.lanes.pons.pons import raw_event, curve_abi
        from meme_machine.lanes.pons.pons_selective_continuation import normalized_trade
        count = 0; corpus = []; cursor = self.baseline
        with self.plane.lock:
            require(self.plane.db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'sqlite_integrity')
            for identity, body, checksum in self.plane.db.execute('SELECT id,body,hash FROM managed_raw ORDER BY id'):
                row = json.loads(body); require(digest(row) == checksum, 'replay_raw_digest')
                decoded = raw_event(curve_abi(),row['event'],address=row['event']['address'],
                    receipt=row['receipt'],header=row['header'],observed_at=row['observed_at'],confirmation='confirmed')
                economic = normalized_trade(decoded['decoded'],identity=identity,event_at=decoded['event_at'])
                economic['canonical_order'] = [int(row['event'][k],16) for k in
                                               ('blockNumber','transactionIndex','logIndex')]
                require(economic == row['economic'], 'replay_economic_mismatch')
                corpus.append([identity, checksum]); count += 1
            for first, last, body, checksum in self.plane.db.execute('SELECT first,last,body,hash FROM managed_ranges ORDER BY first'):
                row = json.loads(body)
                require(digest(row) == checksum and first == cursor+1 and row['complete'] and
                        (row['first'],row['last']) == (first,last), 'replay_coverage_gap')
                members = []
                for identity in row['event_ids']:
                    raw = self.plane.db.execute('SELECT body FROM managed_raw WHERE id=?',(identity,)).fetchone()
                    require(raw is not None, 'replay_event_gap')
                    member = json.loads(raw[0]); members.append((identity,member))
                    require(first <= int(member['event']['blockNumber'],16) <= last, 'replay_event_range')
                require(digest(members) == row['events_sha256'], 'replay_range_digest')
                cursor = last
            require(cursor == self.cursor, 'replay_cursor')
        return dict(verified=True,economic_events=count,corpus_sha256=digest(corpus),
                    contiguous_through=cursor,allocation_authority=False)

    def close(self):
        if self.closed: return
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.poll_candidate(submit=False)
        self.broker.close(); self.owner.close(); self.closed = True


def run_pons(root, duration, generation, *, sample_callback=None, cancel=None):
    """Parent-callable lane; bounded runtime is independent of financial services."""
    require(type(duration) in (int,float) and math.isfinite(duration) and 0 < duration <= 7200,
            'duration')
    stopped = threading.Event()
    deadline = time.monotonic() + duration
    external_cancel = cancel or (lambda: False)
    private_root(root,generation)
    require(os.environ.get('MM_PROVIDER_USAGE_DB'), 'production_usage_required')
    # Install the actual continuous provider accounting/resource wrappers before
    # constructing any RPC, even when this callable is invoked without a parent.
    from .bounded_provider import install
    install()
    lane = ManagedPonsLane(root,generation,cancel=lambda:stopped.is_set() or external_cancel())
    error = None; replay = None
    try:
        lane.sample_head()
        while time.monotonic() < deadline and not external_cancel():
            lane.poll_candidate()
            if time.monotonic()-lane.head_sample_at >= 1:
                lane.sample_head()
            if lane.latest > lane.cursor:
                from meme_machine.lanes.pons.pons_natural_observation import DISCOVERY_MAX_BLOCKS
                try:
                    lane.consume(lane.cursor+1,min(lane.latest,lane.cursor+DISCOVERY_MAX_BLOCKS))
                except Exception as failure:
                    from meme_machine.runtime.robinhood.provider_authority import failure_class
                    reason = failure_class(failure)
                    lane.failure_counts['acquisition:'+reason] += 1
                    lane.plane.checkpoint('managed_incomplete',dict(first=lane.cursor+1,
                        last=lane.latest,reason=reason,complete=False))
                    # Only transient provider faults may use the existing retry
                    # and cooldown machinery; decoding/coverage failures stop.
                    if reason not in {'provider_http_429','provider_rpc_429','provider_transport_failure',
                        'provider_http_500','provider_http_502','provider_http_503','provider_http_504'}:
                        raise
                    stopped.wait(min(1,max(0,deadline-time.monotonic())))
            else:
                stopped.wait(min(.02,max(0,deadline-time.monotonic())))
            snapshot = lane.snapshot(); atomic_json(Path(root)/'telemetry.json',snapshot)
            if sample_callback is not None: sample_callback(snapshot)
    except Exception as failure:
        from meme_machine.runtime.robinhood.provider_authority import failure_class
        error = dict(type=type(failure).__name__,reason=failure_class(failure))
    finally:
        stopped.set()
        lane.pool.shutdown(wait=True,cancel_futures=True)
        lane.poll_candidate(submit=False)
        try: replay = lane.replay()
        except Exception as failure: error = dict(type=type(failure).__name__,reason='native_replay_failed')
        result = lane.snapshot()
        result.update(error=error,replay=replay,elapsed_seconds=time.time()-lane.started,
                      verdict='BLOCKED' if error else 'OBSERVED',production_acceptance=False)
        atomic_json(Path(root)/'result.json',result)
        lane.close()
    return result
