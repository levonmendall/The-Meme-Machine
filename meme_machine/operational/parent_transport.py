"""Explicit trusted-parent transports for an isolated native child.

Not installed by the normal operational entrypoint. The parent supplies its
existing Budget/Governor/Admission and configured authenticated URLs. No ledger,
quota, credential, endpoint or held-priority capability is issued by the wire.
The OS sandbox, native owners and no-allocation bootstrap are separate work.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
import io
import json
import re
import threading
import time
from types import MappingProxyType
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from .bounded_provider import (
    Budget, PhaseBudget, MAX_FRAME, NativeReadBuffer, native_ledger_reader,
)
from .transport_bridge import (
    BridgeRejected, Delivered, EndpointAlias, ParentAttempt, _params, _require,
)
from meme_machine.runtime.provider_purchases import (
    ProviderPurchases, provider_work, purchase_started, purchase_received, _transport,
    work_label,
)


class ParentTransportFailure(ValueError):
    """A fixed classification; no URL, response body or exception text."""


_WORK = MappingProxyType({
    'pump_discovery': ('solana', 'pump', 'discovery', 'discovery', 10, 'discovery'),
    'pump_current_qualification': ('solana', 'pump', 'current', 'qualification', 10, 'final_qualification'),
    'pump_survivor_qualification': ('solana', 'pump', 'survivor', 'qualification', 20, 'final_qualification'),
    'pons_discovery': ('robinhood', 'pons', 'discovery', 'discovery', 10, 'discovery'),
    'pons_current_qualification': ('robinhood', 'pons', 'current', 'qualification', 10, 'final_qualification'),
    'pons_survivor_qualification': ('robinhood', 'pons', 'survivor', 'qualification', 20, 'final_qualification'),
})


@dataclass(frozen=True)
class SourceReference:
    """Secret-free provenance data, not a provider or financial capability.

    The fixed child bootstrap receives these from its authenticated parent hello.
    Native ports use this identity directly; they must not manufacture a URL to
    satisfy a legacy credential-bearing constructor. Parent bindings remain the
    authority for physical selection and fixed work attribution.
    """
    alias: str
    family: str
    endpoint_identity: str
    operation: str

    def __post_init__(self):
        _require(type(self.alias) is str and re.fullmatch(r'[a-z][a-z0-9_-]{0,47}', self.alias)
            and self.operation in _WORK and self.family == _WORK[self.operation][0]
            and type(self.endpoint_identity) is str
            and re.fullmatch(r'[0-9a-f]{64}', self.endpoint_identity), 'parent_source_reference')

    @classmethod
    def from_receipt(cls, row):
        _require(type(row) is dict and set(row) == {
            'alias', 'family', 'endpoint_identity', 'operation', 'authenticated'}
            and row['authenticated'] is True, 'parent_source_receipt')
        return cls(**{k: row[k] for k in ('alias', 'family', 'endpoint_identity', 'operation')})


@dataclass(frozen=True)
class SourceBinding:
    """Parent-only configuration; aliases publish an actual authenticated identity.

    Select from configured environment values once, before crossing the sandbox.
    The operation/priority is a fixed reviewed assignment, never request data.
    Existing controllers are injected, not initialized or copied here.
    """
    alias: EndpointAlias
    operation: str
    identity: str
    _url: str = field(repr=False)
    _config: object = field(repr=False)
    governor: object = field(default=None, repr=False)
    admission: object = field(default=None, repr=False)

    @classmethod
    def configured(cls, alias, operation, *, environ, governor=None, admission=None):
        from meme_machine.runtime.governor import Governor
        from meme_machine.lanes.pons.provider_admission import Admission
        _require(type(alias) is EndpointAlias and operation in _WORK
            and _WORK[operation][0] == alias.family, 'parent_work_binding')
        if alias.family == 'solana':
            from meme_machine.solana_provider_config import AlchemyEndpoint
            config = AlchemyEndpoint.parse(environ.get('MM_SOLANA_READ_RPC_URL'))
            _require(isinstance(governor, Governor) and admission is None,
                     'parent_governor_required')
            return cls(alias, operation, config.identity, config.http_url, config,
                       governor=governor)
        from meme_machine.runtime.robinhood import provider_authority as authority
        url = authority.endpoint(environ=environ)
        _require(isinstance(admission, Admission) and admission.offline_profile is None
            and admission.endpoint == authority.fingerprint(url)
            and admission.lane == 'pons' and governor is None,
            'parent_admission_identity')
        return cls(alias, operation, authority.fingerprint(url), url, None,
                   admission=admission)

    def receipt(self):
        return dict(alias=self.alias.name, family=self.alias.family,
                    endpoint_identity=self.identity, operation=self.operation,
                    authenticated=True)

    def public(self, value):
        if self._config is not None:
            return self._config.public(value)
        from meme_machine.runtime.robinhood.provider_authority import protect_response
        return protect_response(value, self._url)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        # A redirect would be an additional physical attempt without reservation.
        return None


@dataclass
class _HTTPState:
    attempt: ParentAttempt
    canceled: threading.Event = field(default_factory=threading.Event)
    future: object = None


@contextmanager
def _work(binding, purchases, methods, batch):
    """Rebuild fixed parent context; never inherit the dispatching caller's work."""
    from meme_machine.lanes.pons import provider_admission as pa
    from meme_machine.runtime.robinhood import provider_usage as usage
    from meme_machine.runtime import request_scheduling
    _, family, consumer, purpose, priority, category = _WORK[binding.operation]
    tokens = [(pa._position_work, pa._position_work.set(False)),
              (pa._decision_priority, pa._decision_priority.set(priority)),
              (pa._foreground_work, pa._foreground_work.set(False)),
              (pa._transport_dispatch, pa._transport_dispatch.set(None)),
              (usage._active, usage._active.set(None)),
              (request_scheduling.priority, request_scheduling.priority.set(priority))]
    try:
        with provider_work(binding.operation, family=family, consumer=consumer,
                           purpose=purpose), usage.evidence_work(category):
            current = dict(ledger=purchases, label=work_label(family=family),
                methods=methods, retry=0, started=False, response_bytes=0)
            token = _transport.set(current)
            failed = True
            try:
                yield priority
                failed = False
            finally:
                _transport.reset(token)
                if current['started']:
                    purchases.completed(current['label'], current['response_bytes'], failed=failed)
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


def _check(state):
    if state.canceled.is_set():
        raise ParentTransportFailure('parent_attempt_canceled')
    if time.monotonic() >= state.attempt.deadline:
        raise ParentTransportFailure('parent_attempt_deadline')


def _bind_read_timeout(raw, remaining):
    if isinstance(raw, io.BytesIO):
        return
    # Same raw-socket deadline rebinding used by the native Pons error reader.
    # Unknown wrappers and chunk-header read loops do not establish a bound.
    if getattr(raw, 'chunked', False):
        raise ParentTransportFailure('parent_chunked_deadline_unbounded')
    for path in (('fp', 'raw', '_sock'), ('raw', '_sock'), ('_sock',)):
        value = raw
        try:
            for name in path:
                value = getattr(value, name)
            value.settimeout(remaining)
            return
        except (AttributeError, OSError, ValueError):
            pass
    # Offline doubles must explicitly implement the same deadline binding.
    setter = getattr(raw, 'set_read_deadline', None)
    if callable(setter):
        setter(time.monotonic() + remaining)
        return
    raise ParentTransportFailure('parent_read_deadline_unavailable')


class ParentHTTP:
    """Actual physical HTTP accounting, independent bounded worker per attempt.

    The opener is a trusted parent-only dependency. The default has no redirects
    or proxies. Tests inject offline physical I/O, not replacement accounting.
    Child loss waits for accepted work and FULL accounting before receipt close.
    """
    def __init__(self, budget, sources, *, opener=None, workers=4):
        _require(isinstance(budget, (Budget, PhaseBudget)), 'parent_budget_required')
        configured = tuple(sources)
        _require(configured and len(configured) <= 8
            and all(type(s) is SourceBinding for s in configured)
            and len({s.alias.name for s in configured}) == len(configured), 'parent_sources')
        _require(type(workers) is int and 1 <= workers <= 8, 'parent_worker_bound')
        self.budget = budget
        self.sources = MappingProxyType({s.alias.name: s for s in configured})
        self.opener = opener or build_opener(ProxyHandler({}), _NoRedirect()).open
        self.purchases = ProviderPurchases()
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='native-parent')
        self._states = {}
        self._controls = set()
        self._workers = workers
        self._closed = False

    def _binding(self, attempt):
        binding = self.sources.get(attempt.endpoint.name)
        _require(binding is not None and attempt.endpoint == binding.alias
            and 1 <= len(attempt.calls) <= (50 if attempt.endpoint.family == 'robinhood' else 200)
            and (attempt.batch or len(attempt.calls) == 1), 'parent_attempt_binding')
        for call in attempt.calls:
            _require(call.method in binding.alias.methods, 'parent_read_method')
            params = json.loads(call.params_json)
            _require(type(params) is list, 'parent_params')
            _params(params)
        return binding

    async def execute(self, attempt):
        binding = self._binding(attempt)
        key = attempt.session, attempt.token
        _require(not self._closed and key not in self._states
            and len(self._states) < self._workers, 'parent_attempt_capacity')
        state = _HTTPState(attempt)
        self._states[key] = state
        state.future = asyncio.get_running_loop().run_in_executor(
            self._executor, self._execute, state, binding)
        canceled = False
        while True:
            try:
                value = await asyncio.shield(state.future)
                break
            except asyncio.CancelledError:
                canceled = True
                state.canceled.set()
            except BaseException:
                if canceled:
                    raise asyncio.CancelledError from None
                raise
        if canceled:
            raise asyncio.CancelledError
        return value

    def _execute(self, state, binding):
        calls = [dict(jsonrpc='2.0', id=i+1, method=c.method,
                      params=json.loads(c.params_json)) for i, c in enumerate(state.attempt.calls)]
        methods = [c['method'] for c in calls]
        body = json.dumps(calls if state.attempt.batch else calls[0],
                          separators=(',', ':'), allow_nan=False).encode()
        with _work(binding, self.purchases, methods, state.attempt.batch) as priority:
            _check(state)
            if binding.governor is not None:
                binding.governor.acquire('solana', 'pump', priority,
                    deadline_seconds=min(30, state.attempt.deadline-time.monotonic()),
                    methods=methods, cancelled=state.canceled.is_set)
            if binding.admission is not None:
                return binding.admission.invoke(
                    lambda: self._physical(state, binding, calls, body), methods,
                    binding.operation, deadline=state.attempt.deadline,
                    batch=state.attempt.batch, role='isolated_native_authenticated',
                    cancelled=state.canceled.is_set)
            return self._physical(state, binding, calls, body)

    def _physical(self, state, binding, calls, body):
        from meme_machine.runtime.robinhood.provider_usage import http_started, http_received
        from meme_machine.lanes.pons import BoundaryError
        _check(state)
        receipt = self.budget.reserve_http(binding._url, calls)
        raw = None
        try:
            _check(state)
            if binding.admission is not None:
                http_started(len(body))
            else:
                purchase_started(len(body))
            request = Request(binding._url, data=body, headers={'Content-Type': 'application/json'})
            status = 200
            try:
                raw = self.opener(request, timeout=min(8, state.attempt.deadline-time.monotonic()))
            except HTTPError as error:
                raw = error
                status = error.code
            status = getattr(raw, 'status', status)
            if status == 429 and binding.governor is not None:
                # Record essential throttle debt before optional body inspection.
                binding.governor.rate_limited('solana', [c['method'] for c in calls])
            pieces, count = [], 0
            try:
                while True:
                    _check(state)
                    _bind_read_timeout(raw, min(8, state.attempt.deadline-time.monotonic()))
                    reader = getattr(raw, 'read1', None) or raw.read
                    chunk = reader(min(65536, MAX_FRAME-count+1))
                    _require(type(chunk) is bytes, 'parent_response_type')
                    if not chunk:
                        receipt.eof = True
                        break
                    # FULL commit precedes every content publication, even on error.
                    receipt.http_delivery(len(chunk))
                    if binding.admission is not None:
                        http_received(len(chunk))
                    else:
                        purchase_received(len(chunk))
                    count += len(chunk)
                    if count > MAX_FRAME:
                        raise ParentTransportFailure('provider_response_capacity')
                    pieces.append(chunk)
            except Exception:
                if status != 200:
                    raise BoundaryError('provider_http_'+str(int(status))) from None
                raise
            if status != 200:
                raise BoundaryError('provider_http_'+str(int(status)))
            try:
                reply = json.loads(b''.join(pieces))
                rows = reply if state.attempt.batch else [reply]
                if (not isinstance(rows, list) or len(rows) != len(calls)
                    or any(type(r) is not dict or type(r.get('id')) is not int for r in rows)
                    or {r['id'] for r in rows} != set(range(1, len(calls)+1))):
                    raise ParentTransportFailure('provider_invalid_envelope')
                errors = [(r.get('error') or {}).get('code') for r in rows]
                limited = any(c in (429, -32005) for c in errors)
                if limited and binding.governor is not None:
                    binding.governor.rate_limited('solana', [c['method'] for c in calls])
                if any('error' in r for r in rows):
                    code = next((c for c in errors if type(c) is int and -999999 <= c <= 999999), None)
                    raise BoundaryError('provider_rpc_'+str(code) if code is not None else 'provider_invalid_envelope')
                if any('result' not in r for r in rows):
                    raise ParentTransportFailure('provider_invalid_envelope')
                binding.public(reply)
                clean = json.dumps(reply, separators=(',', ':'), allow_nan=False).encode()
                _require(len(clean) <= MAX_FRAME, 'parent_response_capacity')
            except (ValueError, TypeError, AttributeError, RecursionError, OverflowError) as error:
                if isinstance(error, (ParentTransportFailure, BoundaryError, BridgeRejected)):
                    raise
                raise ParentTransportFailure('provider_invalid_json') from None
            _check(state)
            if binding.governor is not None:
                binding.governor.succeeded('solana', [c['method'] for c in calls])
            return Delivered(clean, True)
        finally:
            try:
                if raw is not None:
                    raw.close()
            finally:
                receipt.close()

    async def release(self, attempt, *, uncertain):
        state = self._states.get((attempt.session, attempt.token))
        if state is None:
            return
        if uncertain:
            state.canceled.set()
        canceled = False
        while True:
            try:
                await asyncio.shield(state.future)
                break
            except asyncio.CancelledError:
                canceled = True
                state.canceled.set()
            except BaseException:
                break  # Physical worker's finally already closed its receipt.
        self._states.pop((attempt.session, attempt.token), None)
        if canceled:
            raise asyncio.CancelledError

    async def demand(self, alias, methods):
        from meme_machine.runtime.robinhood.provider_usage import demand
        _require(not self._closed and alias in self.sources, 'parent_control_closed')
        binding = self.sources[alias]
        _require(binding.admission is not None and methods
            and all(m in binding.alias.methods for m in methods), 'parent_demand')
        def committed():
            with _work(binding, self.purchases, methods, False):
                demand(binding.admission.path, binding.admission.endpoint, methods)
                self.purchases.consumer(methods, family='pons')
        await self._control(committed)

    async def activity_marker(self, alias):
        _require(not self._closed and alias in self.sources, 'parent_control_closed')
        binding = self.sources[alias]
        _require(binding.admission is not None, 'parent_activity')
        return await self._control(binding.admission.activity_marker)

    async def _control(self, function):
        # A caller canceled after SQLite accepted logical demand must join it;
        # the still-alive parent cannot rely on process-orphan cleanup.
        _require(not self._closed and len(self._controls) < self._workers, 'parent_control_capacity')
        task = asyncio.create_task(asyncio.to_thread(function))
        self._controls.add(task)
        canceled = False
        try:
            while True:
                try:
                    result = await asyncio.shield(task)
                    break
                except asyncio.CancelledError:
                    if task.done() and task.cancelled():
                        raise ParentTransportFailure('parent_control_canceled') from None
                    canceled = True
        finally:
            self._controls.discard(task)
        if canceled:
            raise asyncio.CancelledError
        return result

    async def aclose(self):
        self._closed = True
        for state in self._states.values():
            state.canceled.set()
        await asyncio.gather(*(self.release(s.attempt, uncertain=True)
                              for s in tuple(self._states.values())))
        await asyncio.gather(*(asyncio.shield(t) for t in tuple(self._controls)))
        self._executor.shutdown(wait=True)


class _StreamBudget:
    def __init__(self, budget, token):
        self.budget, self.token = budget, token

    def __getattr__(self, name):
        return getattr(self.budget, name)

    def native(self, transport, size):
        return self.budget.native(transport, size, token=self.token)


class ParentNativeStream:
    """Original reserved buffer plus one child handoff, not a source ACK.

    The trusted raw transport reads (size, bytes), writes validated subscription
    data and has async aclose(). Its factory remains parent-only. All byte and
    subscription bounds are checked before any delivery/write. The child cannot
    close the reservation or choose a transport URL, native token or allowance.
    """
    def __init__(self, budget, transport, raw, token, validator):
        self.budget, self.transport, self.raw, self.token = budget, transport, raw, token
        self.validator = validator
        self.ledger = native_ledger_reader(budget)
        async def checked_read():
            import grpc
            packet = await raw.read()
            if packet is grpc.aio.EOF:
                return packet
            _require(type(packet) is tuple and len(packet) == 2
                and type(packet[0]) is int and type(packet[1]) is bytes
                and packet[0] == len(packet[1]), 'parent_native_packet')
            return packet
        self.intake = NativeReadBuffer(checked_read, _StreamBudget(budget, token), transport)
        self.pending = None
        self.sequence = 0
        self.closed = False
        self.cleanup_verified = False
        self._read_task = None
        self._lock = asyncio.Lock()
        self._closing = None

    @classmethod
    async def open(cls, budget, transport, factory, validator):
        _require(isinstance(budget, (Budget, PhaseBudget)) and transport in
            ('yellowstone', 'solana_websocket') and callable(factory)
            and callable(validator), 'parent_stream_configuration')
        token = budget.stream_open(transport)
        raw = None
        try:
            raw = await factory()
            return cls(budget, transport, raw, token, validator)
        except BaseException:
            try:
                if raw is not None:
                    await raw.aclose()
            finally:
                budget.stream_close(token, transport=transport, unread_possible=True)
            raise

    async def write(self, body):
        _require(not self.closed and type(body) is bytes and len(body) <= 65536,
                 'parent_subscription_bound')
        self.validator(body)
        self.budget.admission()
        await self.raw.write(body)

    async def read(self):
        import grpc
        _require(not self._lock.locked(), 'parent_read_in_flight')
        async with self._lock:
            _require(not self.closed and self.pending is None, 'parent_handoff_pending')
            self._read_task = asyncio.create_task(self.intake.read())
            try:
                body = await self._read_task
            finally:
                self._read_task = None
            if body is grpc.aio.EOF:
                return None
            _require(type(body) is bytes and len(body) <= MAX_FRAME, 'parent_native_body')
            self.sequence += 1
            self.pending = (self.sequence, body)
            return self.pending

    def acknowledge_handoff(self, sequence):
        _require(not self.closed and self.pending is not None
            and type(sequence) is int and sequence == self.pending[0], 'parent_handoff_ack')
        self.pending = None

    async def aclose(self):
        if self._closing is None:
            self._closing = asyncio.create_task(self._close())
        canceled = False
        while True:
            try:
                await asyncio.shield(self._closing)
                break
            except asyncio.CancelledError:
                if self._closing.done() and self._closing.cancelled():
                    raise ParentTransportFailure('parent_stream_cleanup_canceled') from None
                canceled = True
        if canceled:
            raise asyncio.CancelledError

    async def _close(self):
        self.closed = True
        reading = self._read_task
        if reading is not None:
            reading.cancel()
            await asyncio.gather(reading, return_exceptions=True)
        receiving = self.intake.pending
        self.intake.cancel()
        if receiving is not None:
            await asyncio.gather(receiving, return_exceptions=True)
        try:
            await self.raw.aclose()
        finally:
            try:
                self.budget.stream_close(self.token, transport=self.transport, unread_possible=True)
            finally:
                if self.ledger is not None:
                    self.ledger.close()
                    self.ledger = None
                self.pending = None
        self.cleanup_verified = True


def validate_subscription(transport, body):
    """Fixed read subscription validation, retaining the original paused family."""
    from meme_machine.solana_selective_history import PROGRAMS
    if transport == 'yellowstone':
        from meme_machine.yellowstone import geyser_pb2 as pb
        try:
            request = pb.SubscribeRequest.FromString(body)
            known = pb.SubscribeRequest()
            known.CopyFrom(request)
            known.DiscardUnknownFields()
            _require(known.SerializeToString(deterministic=True)
                == request.SerializeToString(deterministic=True), 'parent_subscription_encoding')
            _require(sum(len(getattr(request, name)) for name in (
                'accounts', 'transactions', 'transactions_status', 'blocks', 'blocks_meta',
                'slots', 'entry')) <= 50, 'parent_subscription_capacity')
            _require(not request.blocks and not request.entry,
                     'parent_unbounded_block_subscription')
            _require(not request.block_footer, 'parent_subscription_shape')
            from meme_machine.pump import un58
            for subscription in list(request.transactions.values())+list(request.transactions_status.values()):
                _require(1 <= len(subscription.account_include)+len(subscription.account_required) <= 256
                    and not subscription.vote and all(len(un58(a)) == 32 for a in
                        list(subscription.account_include)+list(subscription.account_required)),
                    'parent_unfiltered_transactions')
            for subscription in request.accounts.values():
                _require(subscription.owner and set(subscription.owner) <= {
                    PROGRAMS['pump'], PROGRAMS['pumpswap']}, 'parent_account_owner')
            _require(not any(PROGRAMS['meteora'] in list(f.owner) for f in request.accounts.values())
                and not any(PROGRAMS['meteora'] in list(f.account_include)+list(f.account_required)
                    for f in list(request.transactions.values())+list(request.transactions_status.values())),
                'parent_paused_family')
        except BridgeRejected:
            raise
        except Exception:
            raise BridgeRejected('parent_subscription_shape') from None
        return
    try:
        from meme_machine.pump import un58
        value = json.loads(body)
        _require(type(value) is dict and set(value) == {'jsonrpc', 'id', 'method', 'params'}
            and value['jsonrpc'] == '2.0' and type(value['id']) is int,
            'parent_websocket_shape')
        if value['method'] == 'logsUnsubscribe':
            _require(type(value['params']) is list and len(value['params']) == 1
                and type(value['params'][0]) is int, 'parent_websocket_unsubscribe')
        else:
            _require(value['method'] == 'logsSubscribe' and type(value['params']) is list
                and len(value['params']) == 2 and value['params'][1] == {'commitment': 'finalized'},
                'parent_websocket_method')
            mention = value['params'][0]
            _require(type(mention) is dict and set(mention) == {'mentions'}
                and type(mention['mentions']) is list and len(mention['mentions']) == 1
                and len(un58(mention['mentions'][0])) == 32
                and mention['mentions'][0] != PROGRAMS['meteora'], 'parent_websocket_scope')
    except BridgeRejected:
        raise
    except Exception:
        raise BridgeRejected('parent_subscription_shape') from None


def authenticated_native_factory(binding, transport, *, token=None):
    """Build the actual fixed-source read transport in the credentialed parent.

    Not called on import or selected by child-supplied URL/path/credentials.
    Yellowstone's optional token is the parent's original configured token.
    """
    _require(type(binding) is SourceBinding and binding.alias.family == 'solana'
        and transport in ('yellowstone', 'solana_websocket'), 'parent_native_source')

    async def open_yellowstone():
        import grpc
        from engineering.solana_capacity.proof_limits import STREAM_HOST
        channel = grpc.aio.secure_channel(STREAM_HOST, grpc.ssl_channel_credentials(), options=(
            ('grpc.max_receive_message_length', MAX_FRAME), ('grpc.enable_retries', 0),
            ('grpc.http2.bdp_probe', 0), ('grpc.http2.initial_stream_window_size', MAX_FRAME),
            ('grpc.http2.initial_connection_window_size', MAX_FRAME)))
        call = channel.stream_stream('/geyser.Geyser/Subscribe', request_serializer=lambda v: v,
            response_deserializer=lambda v: v)(metadata=(('x-token', token or binding._config.credential),))

        class Raw:
            async def read(self):
                value = await call.read()
                if value is grpc.aio.EOF:
                    return value
                binding.public(value.decode('utf-8', errors='replace'))
                return len(value), value

            async def write(self, body):
                await call.write(body)

            async def aclose(self):
                call.cancel()
                await channel.close(grace=0)
        return Raw()

    async def open_websocket():
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosedOK
        import grpc
        ws = await connect(binding._config.stream_url, max_size=MAX_FRAME, max_queue=2,
            compression=None, open_timeout=8, close_timeout=1, proxy=None)

        class Raw:
            async def read(self):
                try:
                    value = await ws.recv()
                except ConnectionClosedOK:
                    return grpc.aio.EOF
                raw = value.encode() if isinstance(value, str) else value
                binding.public(raw.decode('utf-8', errors='replace'))
                return len(raw), raw

            async def write(self, body):
                await ws.send(body.decode('utf-8'))

            async def aclose(self):
                await ws.close()
        return Raw()

    return open_yellowstone if transport == 'yellowstone' else open_websocket


@dataclass(frozen=True)
class NativeSourceBinding:
    """Fixed parent-issued native alias, with original endpoint/token authority."""
    source: SourceBinding
    transport: str
    token: str | None = field(default=None, repr=False)

    def __post_init__(self):
        _require(type(self.source) is SourceBinding and self.source.alias.family == 'solana'
            and self.transport in ('yellowstone', 'solana_websocket')
            and (self.token is None or type(self.token) is str and 0 < len(self.token) <= 512),
            'parent_native_binding')

    async def open(self, budget, *, factory=None):
        # factory is trusted test dependency injection, never present on the wire.
        return await ParentNativeStream.open(budget, self.transport,
            factory or authenticated_native_factory(self.source, self.transport, token=self.token),
            lambda body: validate_subscription(self.transport, body))
