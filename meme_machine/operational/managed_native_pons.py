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


# Exact committed native BoundaryError literals only. Never emit an arbitrary
# exception message, provider response, transaction identity or credential.
# This allowlist is diagnostic; it changes no native failure/scheduling outcome.
SAFE_NATIVE_FAILURE_REASONS = frozenset({
    'abi_address_padding',
    'abi_argument_range',
    'abi_bool_range',
    'abi_integer_range',
    'adjacent_candidate_header_identity',
    'candidate_canonical_membership_disagreement',
    'candidate_generation_superseded',
    'candidate_identity_disagreement',
    'confirmed_candidate_reorged',
    'conflicting_immutable_evidence',
    'conflicting_logs',
    'conflicting_receipt_log',
    'curve_closed_pending_or_completed_graduation',
    'curve_compiled_bytecode_disagreement',
    'curve_factory_disagreement',
    'curve_factory_provenance',
    'curve_immutable_disagreement',
    'curve_launch_terms_disagreement',
    'curve_runtime_length',
    'curve_source_template_invalid',
    'duplicate_block_transaction',
    'event_data_length',
    'event_topic_count',
    'event_topic_length',
    'evidence_checksum_mismatch',
    'evidence_store_page_capacity',
    'factory_record_shape',
    'followup_block_hash_disagreement',
    'future_current_head',
    'future_event',
    'future_evidence',
    'future_evidence_observation',
    'graduation_not_completed',
    'graduation_transaction_disagreement',
    'impossible_full_position_exit',
    'incorrect_log_identity',
    'ingest_capacity',
    'insufficient_output',
    'invalid_block_identity',
    'invalid_buy_fee_sum',
    'invalid_current_snipe_bps',
    'invalid_curve_launch_time',
    'invalid_curve_state',
    'invalid_evidence_latency_limit',
    'invalid_snipe_state',
    'invalid_storage_bound',
    'malformed_abi_words',
    'missing_block_coverage',
    'missing_evidence',
    'missing_evidence_observation_wall_time',
    'missing_or_duplicate_receipts',
    'missing_or_unexpected_logs',
    'missing_recipient_or_amount',
    'missing_snipe_or_amount',
    'mixed_evidence_kind',
    'natural_call_shape',
    'natural_event_capacity',
    'natural_followup_capacity',
    'natural_non_native_quote_not_supported',
    'natural_rejection_capacity',
    'natural_report_capacity',
    'natural_reserve_shape',
    'no_current_authenticated_pons_candidate',
    'pons_current_recheck_head_identity',
    'pons_current_recheck_no_recent_canonical_buy',
    'pons_current_window_anchor_identity',
    'pons_current_window_log_conflict',
    'pons_current_window_log_identity',
    'pons_current_window_range_incomplete',
    'raw_event_identity_disagreement',
    'receipt_block_disagreement',
    'record_payload_capacity',
    'removed_log_reorg',
    'reorg_parent_conflict',
    'sample_gas_units_bounds',
    'sample_invalid_gas_price',
    'scout_adaptive_page_identity',
    'scout_journal_corruption',
    'scout_log_array_required',
    'scout_log_batch_shape',
    'scout_log_conflict',
    'scout_log_filter_identity',
    'scout_public_boundary_identity',
    'scout_public_reorg',
    'scout_response_saturation',
    'selective_cached_header_hash_conflict',
    'selective_cached_header_number_conflict',
    'selective_cached_header_shape',
    'selective_cached_receipt_identity',
    'selective_cached_transaction_identity',
    'selective_canonical_membership_identity',
    'selective_evidence_batch_incomplete',
    'selective_evidence_request_bound',
    'selective_nomination_not_buy',
    'selective_window_header_disagreement',
    'sequencer_discovery_block_disagreement',
    'sequencer_discovery_start_timeout',
    'solidity_uint256_overflow',
    'source_artifact_unavailable_or_invalid',
    'stale_evidence_acquisition',
    'stale_state',
    'storage_capacity_stop_admission',
    'strategy_horizon_expired',
    'trajectory_block_identity',
    'trajectory_header_time_regression',
    'trajectory_history_incomplete',
    'unfinalized_state',
    'unknown_confirmation',
    'unknown_evidence_kind',
    'unrelated_v4_or_lineage_disagreement',
    'unsupported_abi_type',
    'unsupported_dynamic_event',
    'unsupported_event_signature',
    'v1_factory_record_disagreement',
    'v1_v3_currency_disagreement',
    'v1_v3_event_identity',
    'v1_v3_pool_disagreement',
    'v1_v3_protocol_identity',
    'v1_v3_token_order_disagreement',
    'v1_v3_transaction_disagreement',
    'wrong_chain',
    'wrong_graduation_deployment',
    'wrong_v1_v3_deployment',
    'zero_sell',
})
MAX_FAILURE_EXAMPLES = 8


def native_failure_example(error):
    from meme_machine.lanes.pons import BoundaryError
    from .managed_capacity_evidence import failure_site
    reason = 'unclassified_native_failure'
    if (type(error) is BoundaryError and len(error.args) == 1 and
            type(error.args[0]) is str and error.args[0] in SAFE_NATIVE_FAILURE_REASONS):
        reason = error.args[0]
    return dict(reason_code=reason, origin=failure_site(error))


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
        'survivor.sqlite','survivor.sqlite-wal','survivor.sqlite-shm',
        'telemetry.json', 'result.json', 'telemetry.json.new', 'result.json.new',
        'drained.json', 'drained.json.new'}
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
        for name in ('managed-pons.lock','native.sqlite','provider.sqlite','evidence.sqlite','survivor.sqlite'):
            fd = os.open(self.root/name,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
            os.close(fd)
        self.owner = (self.root/'managed-pons.lock').open('a')
        fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.counts = Counter(); self.failure_counts = Counter()
        self.candidate_outcomes = Counter()
        self.failure_examples = []; self.failure_examples_dropped = 0
        self.closed = False; self.started = time.time(); self.latest = None
        self.head_sample_at = -float('inf'); self.future = None
        self.future_work = None; self.future_started = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pons-capacity-current')
        self.survivor_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='pons-capacity-survivor')
        self.survivor_reader=None;self.survivor_future=None;self.survivor_next=0.
        self.survivor_snapshot=dict(available=False,allocation_authority=False)
        self.survivor_replay=None
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
            self.survivor_pool.shutdown(wait=False,cancel_futures=True)
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

    def record_failure_example(self, stage, error):
        require(stage in {'qualification', 'survivor', 'acquisition'}, 'failure_stage')
        example = dict(stage=stage, **native_failure_example(error))
        for previous in self.failure_examples:
            if all(previous[key] == value for key, value in example.items()):
                previous['count'] += 1
                return
        if len(self.failure_examples) < MAX_FAILURE_EXAMPLES:
            self.failure_examples.append(dict(example, count=1))
        else:
            self.failure_examples_dropped += 1

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
                from meme_machine.lanes.pons import BoundaryError
                from meme_machine.lanes.pons.pons_selective_acquisition import authenticated_early_rejection
                from meme_machine.runtime.robinhood.provider_authority import failure_class
                # Match the production Current cohort's native boundary contract.
                # Only committed fixed native reasons cross the diagnostic boundary;
                # arbitrary exception/provider text retains its existing redaction.
                reason = (error.args[0] if isinstance(error, BoundaryError) and
                    len(error.args) == 1 and type(error.args[0]) is str and
                    error.args[0] in SAFE_NATIVE_FAILURE_REASONS else failure_class(error))
                evidence = self.context.boundary_evidence if isinstance(error, BoundaryError) else None
                screen = authenticated_early_rejection(reason, evidence)
                with self.plane.lock:
                    # Plane.finish's bool means canonical evidence completed;
                    # an ordinary rejection also commits but returns False.
                    # Read this attempt's new native audit outcome while holding
                    # the same owner lock, rather than inventing a classifier.
                    before = self.plane.db.execute('SELECT MAX(seq) FROM transitions').fetchone()[0] or 0
                    self.broker.failure(work, reason, screen=screen, evidence=evidence)
                    recorded = self.plane.db.execute('SELECT kind FROM transitions WHERE seq>? '
                        'AND candidate=? AND generation=? ORDER BY seq DESC LIMIT 1',
                        (before, work['key'], work['work']['generation'])).fetchone()
                    outcome = recorded[0] if recorded is not None else 'not_committed'
                self.candidate_outcomes[outcome] += 1
                if outcome == 'superseded':
                    self.counts['candidate_superseded'] += 1
                elif outcome not in ('strategy_rejected', 'structural_excluded'):
                    self.failure_counts['qualification:' + reason] += 1
                # Expected exclusions remain visible and never count as completed
                # native qualification, market coverage or financial authority.
                self.record_failure_example('qualification', error)
            finally:
                self.future = self.future_work = None
        if submit and self.future is None and not self.cancel():
            work = self.broker.pop()
            if work is not None:
                from meme_machine.lanes.pons.pons_selective_acquisition import evaluate_candidate
                from meme_machine.lanes.pons.pons_selective_paper import STRATEGY_CAPITAL_QUOTE
                self.context.boundary_evidence = None
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
            candidate_outcomes=dict(self.candidate_outcomes),
            failure_examples=[dict(row) for row in self.failure_examples],
            failure_examples_dropped=self.failure_examples_dropped,
            provider_usage=self.rpc.shared_admission.telemetry(),
            survivor=self.survivor_snapshot,
            storage_bytes=sum(p.stat().st_size for p in self.root.iterdir() if p.is_file()),
            scope=dict(managed_admission=True,native_batches=True,native_decode=True,
                native_current_history=True,native_current_history_persistence=True,
                current_qualification=True,complete_current_qualification=False,
                postgraduation_pool_discovery=True,survivor_qualification=True,
                complete_survivor_qualification=False,financial_entries=False,
                held_protection_live=False,
                sizing_input='unchanged_native_unfunded_reference_constant'),observed_at=time.time(),
            monotonic=time.monotonic(),authenticated_head_sample_monotonic=self.head_sample_at)

    def poll_survivor(self,*,submit=True):
        """Independent production three-second read turn; no financial Runtime."""
        if self.survivor_future is not None and self.survivor_future.done():
            try:self.survivor_snapshot=self.survivor_future.result()
            except Exception as error:
                from meme_machine.runtime.robinhood.provider_authority import failure_class
                reason=failure_class(error)
                self.failure_counts['survivor:'+reason]+=1
                self.record_failure_example('survivor', error)
                self.survivor_snapshot=dict(available=False,error_type=type(error).__name__,
                    reason=reason,allocation_authority=False,observed_at=time.time())
            finally:self.survivor_future=None
        if submit and self.survivor_future is None and not self.cancel() and self.latest is not None:
            from .managed_pons_survivor import SurvivorMarketReadSide
            if time.monotonic()<self.survivor_next:return
            self.survivor_next=time.monotonic()+SurvivorMarketReadSide.observation_interval_seconds
            def step(top=self.latest):
                if self.survivor_reader is None:
                    self.survivor_reader=SurvivorMarketReadSide(self.root/'survivor.sqlite',
                        self.endpoint,self.plane,self.scout,cancel=self.cancel)
                return self.survivor_reader.step(top)
            self.survivor_future=self.survivor_pool.submit(step)

    def finish_survivor(self, *, drain_callback=None):
        if self.survivor_future is not None:
            try:self.survivor_future.result()
            except Exception:pass
            self.poll_survivor(submit=False)
        if drain_callback is not None:
            drain_callback()
        def finish():
            if self.survivor_reader is None:return dict(verified=False,reason='survivor_not_started')
            try:return self.survivor_reader.replay()
            finally:self.survivor_reader.close()
        try:self.survivor_replay=self.survivor_pool.submit(finish).result()
        except Exception:
            self.survivor_replay=dict(verified=False,reason='survivor_replay_failed')
            raise
        finally:self.survivor_pool.shutdown(wait=True,cancel_futures=True)
        return self.survivor_replay

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
        if self.survivor_replay is None:self.finish_survivor()
        self.broker.close(); self.owner.close(); self.closed = True


def run_pons(root, duration, generation, *, sample_callback=None, cancel=None,sample_seconds=5,
             drain_callback=None):
    """Parent-callable lane; bounded runtime is independent of financial services."""
    require(type(duration) in (int,float) and math.isfinite(duration) and 0 < duration <= 7200,
            'duration')
    require(type(sample_seconds) in (int,float) and 1<=sample_seconds<=60,'sample_interval')
    stopped = threading.Event()
    deadline = time.monotonic() + duration
    external_cancel = cancel or (lambda: False)
    private_root(root,generation)
    require(os.environ.get('MM_PROVIDER_USAGE_DB'), 'production_usage_required')
    # Install the actual continuous provider accounting/resource wrappers before
    # constructing any RPC, even when this callable is invoked without a parent.
    from .bounded_provider import install
    install()
    # External cancellation closes NEW admissions at the loop boundary. An
    # admitted range and its existing workers retain their original deadlines
    # and finish before the internal safety cancellation is raised.
    lane = ManagedPonsLane(root,generation,cancel=stopped.is_set)
    error = None; replay = None;next_sample=0.
    try:
        lane.sample_head()
        while time.monotonic() < deadline and not external_cancel():
            lane.poll_candidate()
            lane.poll_survivor()
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
                    lane.record_failure_example('acquisition', failure)
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
            if time.monotonic()>=next_sample:
                snapshot = lane.snapshot(); atomic_json(Path(root)/'telemetry.json',snapshot)
                if sample_callback is not None: sample_callback(snapshot)
                next_sample=time.monotonic()+sample_seconds
    except Exception as failure:
        from meme_machine.runtime.robinhood.provider_authority import failure_class
        from .managed_capacity_evidence import failure_site
        error = dict(type=type(failure).__name__,reason=failure_class(failure),
                     origin=failure_site(failure))
    finally:
        if error is not None:stopped.set()
        lane.pool.shutdown(wait=True,cancel_futures=True)
        lane.poll_candidate(submit=False)
        try:survivor_replay=lane.finish_survivor(drain_callback=drain_callback)
        except Exception as failure:
            survivor_replay=dict(verified=False,error_type=type(failure).__name__)
            error=dict(type=type(failure).__name__,reason='survivor_native_replay_failed')
        stopped.set()
        try: replay = lane.replay()
        except Exception as failure: error = dict(type=type(failure).__name__,reason='native_replay_failed')
        result = lane.snapshot()
        result.update(error=error,replay=replay,elapsed_seconds=time.time()-lane.started,
                      survivor_replay=survivor_replay,
                      verdict='BLOCKED' if error else 'OBSERVED',production_acceptance=False)
        atomic_json(Path(root)/'telemetry.json',result)
        atomic_json(Path(root)/'result.json',result)
        lane.close()
    return result
