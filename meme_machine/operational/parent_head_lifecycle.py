"""Explicit parent-owned physical heads; no child, financial or coverage authority.

The owner must already hold its original parent startup/financial fences. This
adapter neither establishes those fences nor enables a runtime from environment
or wire data. ParentChannel owns optional tasks under its original drain fence.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time

from meme_machine.runtime.market_heads import _number, _quantity
from .transport_bridge import ParentAttempt, ReadCall, _require

FRESH_SECONDS = 5
REFRESH_SECONDS = 5
PROJECTION_BYTES = 4096
_now = time.monotonic


def _process():
    with Path('/proc/self/stat').open('rb') as stream:
        body = stream.read(4097)
    _require(len(body) <= 4096, 'parent_head_process_identity')
    head, tail = body.decode('ascii').rsplit(')', 1)
    pid, ticks = int(head.split('(', 1)[0]), int(tail.split()[19])
    _require(pid == os.getpid() and ticks > 0, 'parent_head_process_identity')
    return pid, ticks


def _source(approval, image):
    from .isolated_native_image import NativeImageApproval, source_objects
    from .isolated_native_launcher import _verify_image
    _require(type(approval) is NativeImageApproval and type(image) is dict
        and set(image) == {'root', 'manifest', 'manifest_sha256'}, 'parent_head_source_required')
    # Existing approval authenticates the expected source. The actual parent
    # checkout must match it; never bless whatever HEAD happens to be present.
    source_objects(approval)
    approved = approval.value()
    manifest = _verify_image(image['root'], image['manifest_sha256'])
    _require(manifest == image['manifest'] and all(manifest.get(key) == approved[key]
        for key in ('source_commit', 'source_tree', 'requirements_sha256')),
        'parent_head_image_source_mismatch')
    app = {row['path'][4:]: row['sha256'] for row in manifest['files']
           if row['path'].startswith('app/')}
    _require(app == dict(approved['source_files'], **{'requirements.txt': approved['requirements_sha256']}),
        'parent_head_image_source_mismatch')
    return dict(application_commit=approved['source_commit'], application_tree=approved['source_tree'],
                image_manifest_sha256=image['manifest_sha256'])


def _binding(binding):
    from .parent_transport import SourceBinding
    from meme_machine.runtime.governor import Governor
    from meme_machine.lanes.pons.provider_admission import Admission
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from meme_machine.runtime.robinhood import provider_authority
    _require(type(binding) is SourceBinding and type(binding.identity) is str
        and re.fullmatch('[0-9a-f]{64}', binding.identity), 'parent_head_provider_binding')
    if binding.alias.family == 'solana':
        _require(type(binding._config) is AlchemyEndpoint and isinstance(binding.governor, Governor)
            and binding.admission is None and binding._url == binding._config.http_url
            and binding.identity == binding._config.identity, 'parent_head_provider_binding')
    else:
        _require(isinstance(binding.admission, Admission) and binding.admission.offline_profile is None
            and binding.admission.endpoint == binding.identity and binding.admission.lane == 'pons'
            and binding.governor is None and binding._config is None
            and provider_authority.fingerprint(binding._url) == binding.identity,
            'parent_head_provider_binding')


class ParentHeadLifecycle:
    """One exact parent channel/session, actual transport, and joined tasks.

    The 43-character transport token is preserved with its actual type label.
    It is neither a Solana fence UUID nor the child's opaque _SourceGeneration.
    Network proof comes only from already purchased parent identity responses.
    """
    def __init__(self, channel, *, approval, image, refresh=True):
        from .parent_channel import ParentChannel
        from .parent_transport import ParentHTTP
        from meme_machine.runtime import provider_clock
        _require(type(channel) is ParentChannel and type(channel.http) is ParentHTTP
            and type(refresh) is bool and not channel.closed and not channel.stopped.is_set()
            and not channel.http._closed and getattr(channel, '_head_lifecycle', None) is None
            and getattr(channel.http, '_head_lifecycle', None) is None,
            'parent_head_owner_required')
        _require(type(channel.session) is str and re.fullmatch('[A-Za-z0-9_-]{43}', channel.session),
            'parent_head_transport_session')
        self.loop = asyncio.get_running_loop()
        _require(self.loop is channel._loop and abs(self.loop.time() - _now()) < .05,
            'parent_head_clock_domain')
        for binding in channel.http.sources.values(): _binding(binding)
        self.source = _source(approval, image)
        self.pid, self.ticks = _process()
        self.domain = provider_clock.current_identity()
        provider_clock._identity(self.domain)
        self.channel, self.http, self.session = channel, channel.http, channel.session
        self.sources = dict(self.http.sources)
        self.admission_sessions = {alias: binding.admission.session for alias, binding in self.sources.items()
                                   if binding.admission is not None}
        self.lock = threading.RLock(); self.stop_requested = asyncio.Event()
        self.owner_invalid = False
        self.stopped = False; self.tasks = []; self.active_tasks = set(); self.points = {}; self.first = {}
        self.pending_chains = set(); self.owned_attempts = set(); self.failed_tasks = set()
        self.proofs = {}; self.invalid_network = set(); self.failures = {}
        self.invalid = {}; self.discontinuities = {}; self.out_of_order = {}
        self.next_due = {}; self.inflight = set(); self.refresh_failures = {}
        self.providers = {}; self.refresh_sources = {}; self.refresh_enabled = refresh
        self.start_failed = False
        for chain, family in (('solana', 'solana'), ('pons', 'robinhood')):
            bindings = [b for b in self.http.sources.values() if b.alias.family == family]
            identities = {b.identity for b in bindings}
            self.providers[chain] = next(iter(identities)) if len(identities) == 1 else None
            method = 'getSlot' if chain == 'solana' else 'eth_getBlockByNumber'
            choices = [b for b in bindings if method in b.alias.methods and (
                b.operation == 'pump_history_receipt' and b.read_class == 'solana_evidence_2'
                if chain == 'solana' else b.operation == 'pons_discovery' and b.read_class == 'native')]
            self.refresh_sources[chain] = choices[0] if len(choices) == 1 and self.providers[chain] else None
        # Publish ownership only after every source/image/process check passed.
        channel._head_lifecycle = self; self.http._head_lifecycle = self
        if refresh:
            for chain in ('solana', 'pons'):
                coroutine = self._run(chain)
                try:
                    task = self.loop.create_task(coroutine, name='parent-head-' + chain)
                except BaseException:
                    coroutine.close(); self.start_failed = True
                    # Ownership remains published for the original close/drain.
                    # Retain every already scheduled task before another start.
                    self.stop()
                    raise
                self.tasks.append(task)

    def _current(self):
        from meme_machine.runtime import provider_clock
        if self.stopped or self.stop_requested.is_set() or self.owner_invalid: return False
        try:
            current = (_process() == (self.pid, self.ticks)
                and provider_clock.current_identity() == self.domain
                and self.channel.session == self.session and self.channel.http is self.http
                and self.channel._head_lifecycle is self and self.http._head_lifecycle is self
                and len(self.http.sources) == len(self.sources)
                and all(self.http.sources.get(alias) is binding for alias, binding in self.sources.items())
                and all(self.sources[alias].admission.session == session
                        for alias, session in self.admission_sessions.items())
                and _now() < self.channel.deadline
                and not self.channel.closed and not self.channel.stopped.is_set() and not self.http._closed)
        except Exception:
            current = False
        if not current: self.owner_invalid = True
        return current and not self.owner_invalid and not self.stopped and not self.stop_requested.is_set()

    def physical_response(self, http, state, binding, calls, rows, *, started, completed):
        """Only the original ParentHTTP calls this after its physical validation."""
        relevant = {'getGenesisHash', 'getSlot', 'eth_chainId', 'eth_getBlockByNumber'}
        if not any(row['method'] in relevant for row in calls): return
        with self.lock:
            chain = 'solana' if binding.alias.family == 'solana' else 'pons'
            try:
                _require(http is self.http and http.sources.get(binding.alias.name) is binding
                    and http._states.get((state.attempt.session, state.attempt.token)) is state
                    and state.attempt.session == self.session and state.attempt.endpoint == binding.alias
                    and self._current(), 'parent_head_owner_changed')
                _require(self.providers.get(chain) == binding.identity and _number(started)
                    and _number(completed) and started <= completed <= _now(), 'parent_head_physical_identity')
                by_id = {row['id']: row for row in rows}
                _require(len(by_id) == len(calls) and set(by_id) == {row['id'] for row in calls},
                    'parent_head_physical_identity')
                # First process identity members, independent of response order.
                for call in calls:
                    row = by_id[call['id']]
                    if 'error' in row or call['params'] != []: continue
                    identity = (chain == 'solana' and call['method'] == 'getGenesisHash'
                        or chain == 'pons' and call['method'] == 'eth_chainId')
                    if not identity: continue
                    from meme_machine.solana_provider_config import GENESIS
                    try:
                        valid = (row.get('result') == GENESIS if chain == 'solana'
                                 else _quantity(row.get('result')) == 4663)
                    except Exception: valid = False
                    if not valid: self.invalid_network.add(chain)
                    else: self.proofs[chain] = dict(method=call['method'],
                        physical_completed_monotonic=completed, source_alias=binding.alias.name)
                for call in calls:
                    kind = self._kind(chain, call['method'], call['params'])
                    row = by_id[call['id']]
                    if kind is None or 'error' in row: continue
                    try:
                        _require(chain in self.proofs and chain not in self.invalid_network,
                            'parent_head_network_unverified')
                        result = row.get('result')
                        height = result if chain == 'solana' else _quantity(result.get('number'))
                        _require(type(height) is int and 0 <= height < 2**63, 'parent_head_malformed')
                        header_hash = header_time = None
                        if chain == 'pons':
                            header_hash = result.get('hash'); header_time = _quantity(result.get('timestamp'))
                            _require(type(header_hash) is str and re.fullmatch('0x[0-9a-fA-F]{64}', header_hash),
                                'parent_head_malformed')
                            header_hash = header_hash.lower()
                        session = binding.admission.session if binding.admission is not None else None
                        if session is not None:
                            _require(type(session) is str and re.fullmatch('[0-9a-f]{32}', session),
                                'parent_head_admission_session')
                        physical_wall = time.time() - (_now() - completed)
                        _require(_number(physical_wall), 'parent_head_physical_clock')
                        point = dict(height=height, header_hash=header_hash, header_timestamp=header_time,
                            request_started_monotonic=started, physical_completed_monotonic=completed,
                            physical_completed_wall=physical_wall,
                            source_alias=binding.alias.name)
                        prior = self.points.get(kind)
                        if prior and (completed < prior['physical_completed_monotonic'] or
                                started < prior['request_started_monotonic'] and height <= prior['height']):
                            self.out_of_order[kind] = self.out_of_order.get(kind, 0) + 1
                            continue
                        if prior and (height < prior['height'] or chain == 'pons'
                                and height == prior['height'] and header_hash != prior['header_hash']):
                            self.discontinuities[kind] = self.discontinuities.get(kind, 0) + 1
                            raise ValueError('parent_head_discontinuity')
                        self.points[kind] = point; self.first.setdefault(kind, point)
                        self.failures.pop(kind, None)
                    except Exception:
                        self.failures[kind] = 'PHYSICAL_HEAD_UNAVAILABLE'
                        self.invalid[kind] = self.invalid.get(kind, 0) + 1
            except Exception:
                self.failures[chain] = 'PARENT_PHYSICAL_PROVENANCE_UNAVAILABLE'

    @staticmethod
    def _kind(chain, method, params):
        from meme_machine.runtime.market_heads import MarketHeads
        return MarketHeads._kind(chain, method, params)

    def _fresh(self, kind, now):
        point = self.points.get(kind)
        age = now - point['physical_completed_monotonic'] if point else None
        chain = 'solana' if kind == 'solana_finalized' else 'pons'
        return (self._current() and point is not None and _number(age) and age <= FRESH_SECONDS
            and kind not in self.failures and chain not in self.failures
            and chain not in self.invalid_network and not self.discontinuities.get(kind, 0))

    async def refresh_once(self, chain):
        _require(chain in ('solana', 'pons') and asyncio.get_running_loop() is self.loop,
            'parent_head_refresh_owner')
        with self.lock:
            if chain in self.pending_chains or not self._current(): return False
            self.pending_chains.add(chain)
        coroutine = self._refresh_once(chain)
        try:
            task = self.loop.create_task(coroutine, name='parent-head-attempt-' + chain)
        except BaseException:
            coroutine.close(); self.pending_chains.discard(chain)
            raise
        self.owned_attempts.add(task)
        caller_cancelled = False
        try:
            while True:
                try:
                    result = await asyncio.shield(task)
                    break
                except asyncio.CancelledError:
                    # Stop only this owned purchase, never the coordinator
                    # awaiting it or another legitimate native leader.
                    caller_cancelled |= asyncio.current_task().cancelling() > 0
                    if task.done() and task.cancelled():
                        result = False; break
                    task.cancel()
            if caller_cancelled: raise asyncio.CancelledError
            return result
        except BaseException as error:
            if not isinstance(error, asyncio.CancelledError):
                self.failed_tasks.add(task); self.owner_invalid = True
            raise
        finally:
            self.owned_attempts.discard(task); self.pending_chains.discard(chain)

    async def _refresh_once(self, chain):
        kind = 'solana_finalized' if chain == 'solana' else 'pons_latest'
        now = _now(); binding = self.refresh_sources[chain]
        with self.lock:
            if (not self._current() or now >= self.channel.deadline or chain in self.inflight
                    or now < self.next_due.get(chain, 0) or binding is None
                    or chain not in self.proofs or chain in self.invalid_network or self._fresh(kind, now)):
                return False
            self.inflight.add(chain)
            self.active_tasks.add(asyncio.current_task())
        attempt = None; delivered = None; failed = True
        try:
            method = 'getSlot' if chain == 'solana' else 'eth_getBlockByNumber'
            params = [dict(commitment='finalized')] if chain == 'solana' else ['latest', False]
            await self.http.demand(binding.alias.name, [method])
            if not self._current(): return False
            attempt = ParentAttempt(self.session, secrets.token_urlsafe(32), binding.alias,
                (ReadCall(method, json.dumps(params, separators=(',', ':')).encode()),), False,
                min(self.channel.deadline, self.loop.time() + min(8, self.channel.attempt_seconds)))
            delivered = await self.http.execute(attempt)
            with self.lock: failed = not self._fresh(kind, _now())
            return not failed
        except Exception:
            return False
        finally:
            try:
                if attempt is not None:
                    await self.http.release(attempt, uncertain=delivered is None or not delivered.eof)
            finally:
                with self.lock:
                    self.inflight.discard(chain); self.next_due[chain] = _now() + REFRESH_SECONDS
                    self.active_tasks.discard(asyncio.current_task())
                    if failed:
                        self.refresh_failures[kind] = self.refresh_failures.get(kind, 0) + 1
                        self.failures[kind] = 'GOVERNED_HEAD_REFRESH_UNAVAILABLE'

    async def _run(self, chain):
        while not self.stop_requested.is_set() and self._current() and _now() < self.channel.deadline:
            await self.refresh_once(chain)
            try: await asyncio.wait_for(self.stop_requested.wait(), .1)
            except TimeoutError: pass

    def stop(self):
        _require(asyncio.get_running_loop() is self.loop, 'parent_head_refresh_owner')
        self.stop_requested.set()
        for task in set(self.tasks) | self.active_tasks | self.owned_attempts | self.failed_tasks:
            if not task.done(): task.cancel()

    async def join(self, *, deadline):
        _require(asyncio.get_running_loop() is self.loop and self.stop_requested.is_set(),
            'parent_head_refresh_owner')
        tasks = set(self.tasks) | self.active_tasks | self.owned_attempts | self.failed_tasks
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=max(0, deadline - self.loop.time()))
            if pending:
                from .isolated_native_lifetime import NativeOwnerDrainFailure
                failure = NativeOwnerDrainFailure(dict(status='BLOCKED',
                    failure_code='parent_head_shutdown_incomplete', financial_authority=False,
                    normal_readiness=False, all_workers_joined=False))
                failure.retain(self, self.channel, self.http)
                raise failure
            # Retrieve task exceptions; a failed optional refresh never reports a
            # successful cleanup or terminates the economic source by itself.
            if any(not task.cancelled() and task.exception() is not None for task in tasks):
                from .parent_transport import ParentTransportFailure
                raise ParentTransportFailure('parent_head_worker_failed')
        with self.lock: self.stopped = True

    def snapshot(self):
        with self.lock:
            now = _now(); heads = {}
            for kind in ('solana_finalized', 'pons_latest', 'pons_finalized'):
                chain = 'solana' if kind == 'solana_finalized' else 'pons'
                last = self.points.get(kind)
                age = now - last['physical_completed_monotonic'] if last else None
                heads[kind] = dict(state='OBSERVED' if self._fresh(kind, now) else 'UNAVAILABLE',
                    method='getSlot' if chain == 'solana' else 'eth_getBlockByNumber',
                    commitment='finalized' if chain == 'solana' else kind.split('_', 1)[1],
                    age_seconds=age if _number(age) else None, first=self.first.get(kind), last=last,
                    invalid_responses=self.invalid.get(kind, 0), discontinuities=self.discontinuities.get(kind, 0),
                    out_of_order=self.out_of_order.get(kind, 0), failed_refreshes=self.refresh_failures.get(kind, 0))
            from meme_machine.solana_provider_config import GENESIS
            # Bindings are immutable for this owner. Deduplicate their actual
            # provenance instead of repeating it in every first/latest point.
            aliases = {point['source_alias'] for point in (*self.first.values(), *self.points.values(),
                                                          *self.proofs.values())}
            result = dict(schema='parent-physical-heads-v1', **self.source,
                source_pid=self.pid, source_process_start_ticks=self.ticks,
                source_clock_identity_sha256=hashlib.sha256(self.domain.encode()).hexdigest(),
                generation=dict(kind='PARENT_TRANSPORT_SESSION', value=self.session),
                canonical_source_generation=None, sampled_at_monotonic=now,
                bindings={alias: dict(family=self.sources[alias].alias.family,
                    operation=self.sources[alias].operation, read_class=self.sources[alias].read_class,
                    pons_admission_session=self.admission_sessions.get(alias)) for alias in sorted(aliases)},
                providers={chain: dict(identity=self.providers[chain],
                    expected_network=GENESIS if chain == 'solana' else 4663,
                    verified=chain in self.proofs and chain not in self.invalid_network,
                    identity_proof=self.proofs.get(chain),
                    refresh_capability='AVAILABLE' if self.refresh_sources[chain] else 'UNAVAILABLE_CAPABILITY')
                    for chain in ('solana', 'pons')}, heads=heads,
                collection_stopping=self.stop_requested.is_set(), collection_stopped=self.stopped,
                owner_current=self._current(), startup_complete=not self.start_failed,
                economic_arrival_count=None, canonical_coverage=False, normal_readiness=False,
                scope='ACTUAL_PARENT_PHYSICAL_HEADS_NOT_ECONOMIC_WORKLOAD_OR_COMPLETION')
            if len(json.dumps(result, separators=(',', ':'), allow_nan=False).encode()) > PROJECTION_BYTES:
                return dict(schema='parent-physical-heads-v1', state='UNAVAILABLE',
                    failure_code='HEAD_PROJECTION_BOUND', economic_arrival_count=None,
                    canonical_coverage=False, normal_readiness=False)
            # Detach retained dictionaries; external projection cannot change
            # clocks, proofs or freshness in this owner.
            return json.loads(json.dumps(result, allow_nan=False))
