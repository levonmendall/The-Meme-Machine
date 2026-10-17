"""Standalone parent-owned read protocol; not installed in any runtime.

This enforces framing, immutable capabilities and bounded admission/deadlines.
It deliberately does not implement provider transport or metering. Only a trusted
parent adapter may own credentials, existing admission/governor/Budget objects,
physical I/O and cancellation-safe accounting. No adapter is selected by wire data.
"""
import asyncio
import base64
from dataclasses import dataclass
import hashlib
import json
import math
import re
import secrets
import struct
from types import MappingProxyType
from typing import Protocol

from engineering.solana_capacity.proof_limits import PUBLISHED

MAX_REQUEST = 64 * 1024
MAX_BODY = 256 * 1024
MAX_WIRE = 384 * 1024
MAX_RETAINED = 8 * 1024 * 1024
MAX_MESSAGES = 1024
READ_METHODS = MappingProxyType({k: frozenset(v) for k, v in PUBLISHED.items()})
_NAME = re.compile(r'[a-z][a-z0-9_-]{0,47}\Z')
_TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')
_FORBIDDEN = frozenset(('url', 'uri', 'endpoint', 'path', 'sql', 'allowance',
    'allowances', 'credentials', 'headers', 'callable', 'priority', 'deadline'))


class BridgeRejected(ValueError):
    """Fixed public rejection code; never an underlying transport exception."""


def _require(condition, code):
    if not condition:
        raise BridgeRejected(code)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate_field')
        result[key] = value
    return result


def _noninteger_number(_):
    # parse_constant alone misses exponent overflow (1e999 -> float('inf')).
    # Wire parameters are integer-only; reject floats before canonical hashing.
    raise BridgeRejected('noninteger_number')


def encode_frame(value):
    raw = _json(value)
    _require(0 < len(raw) <= MAX_WIRE, 'frame_bound')
    return struct.pack('!I', len(raw)) + raw


def decode_request(frame):
    _require(type(frame) is bytes and 4 <= len(frame) <= MAX_REQUEST + 4, 'frame_bound')
    size, = struct.unpack('!I', frame[:4])
    _require(0 < size <= MAX_REQUEST and len(frame) == size + 4, 'frame_length')
    try:
        value = json.loads(frame[4:].decode('utf-8'), object_pairs_hook=_unique,
                           parse_constant=_noninteger_number,
                           parse_float=_noninteger_number)
    except (UnicodeError, ValueError, RecursionError):
        raise BridgeRejected('invalid_json') from None
    _require(type(value) is dict, 'message_shape')
    return value


async def read_request_frame(reader):
    """Reject an oversized length before reading/allocating its declared body.

    The embedding parent must call Session.aclose() on EOF, malformed framing,
    write failure or child exit. This helper does not create a socket server.
    """
    prefix = await reader.readexactly(4)
    size, = struct.unpack('!I', prefix)
    _require(0 < size <= MAX_REQUEST, 'frame_length')
    return prefix + await reader.readexactly(size)


def _params(value, depth=0, counter=None):
    """JSON data only, with no authority-bearing options in nested params."""
    if counter is None:
        counter = [0]
    counter[0] += 1
    _require(depth <= 8 and counter[0] <= 2048, 'parameter_bound')
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        _require(-(2**63) <= value < 2**64, 'parameter_integer')
        return
    if type(value) is str:
        _require(len(value) <= 4096 and not value.lower().startswith(
            ('http:', 'https:', 'file:', '/', '\\')), 'parameter_string')
        return
    if type(value) is list:
        for item in value:
            _params(item, depth + 1, counter)
        return
    if type(value) is dict:
        for key, item in value.items():
            _require(type(key) is str and 0 < len(key) <= 64
                and key.lower() not in _FORBIDDEN, 'parameter_field')
            _params(item, depth + 1, counter)
        return
    raise BridgeRejected('parameter_type')


@dataclass(frozen=True)
class EndpointAlias:
    """Parent configuration only; no URL, credentials or mutable method set."""
    name: str
    family: str
    methods: frozenset[str]

    def __post_init__(self):
        methods = frozenset(self.methods)
        _require(type(self.name) is str and _NAME.fullmatch(self.name)
            and self.family in READ_METHODS and methods
            and methods <= READ_METHODS[self.family], 'alias_configuration')
        object.__setattr__(self, 'methods', methods)


@dataclass(frozen=True)
class ReadCall:
    method: str
    params_json: bytes


@dataclass(frozen=True)
class ParentAttempt:
    """Immutable parent assignment. Deadline is the parent's loop clock.

    A trusted adapter validates native method parameter policy, reconstructs fixed
    attribution, preserves single/batch semantics and retains original admission
    ordering. It reserves the *existing* Budget before physical I/O, commits bytes
    before returning Delivered, and records original success/429/error state once.
    A canceled attempt never gets a new deadline or a replacement allowance.
    """
    session: str
    token: str
    endpoint: EndpointAlias
    calls: tuple[ReadCall, ...]
    batch: bool
    deadline: float


@dataclass(frozen=True)
class Delivered:
    """Sanitized response bytes whose delivery accounting already committed.

    An adapter must not return headers, credential-bearing provider error bodies
    or exception strings. eof means genuine physical EOF, never inferred success.
    Partial responses (eof=False) are charged/cleaned but never handed to a child.
    """
    body: bytes
    eof: bool


class TrustedParentAdapter(Protocol):
    async def execute(self, attempt: ParentAttempt) -> Delivered: ...

    async def release(self, attempt: ParentAttempt, *, uncertain: bool) -> None:
        """Idempotent cleanup, including partial acquisition/accepted accounting.

        Must tolerate execute never starting; preserve charges, cooldown and debt.
        Await accepted accounting; mark unproven unread HTTP/native bytes uncertain.
        Parent PID orphan reaping cannot substitute for this per-attempt cleanup.
        """
        ...


@dataclass
class _State:
    attempt: ParentAttempt
    task: asyncio.Task | None = None
    status: str = 'running'
    body: bytes | None = None
    cancel_requested: bool = False


class Session:
    """One event-loop/channel capability. dispatch never waits for provider I/O.

    No global lock serializes Pump/Pons admission. Concurrent attempts are bounded;
    all share the injected parent's actual controls. Exact sequence replays return
    the original reply, never another physical attempt. Retention is never evicted:
    exhaustion closes the session rather than permitting a replay to execute again.
    """
    def __init__(self, aliases, adapter: TrustedParentAdapter, *, seconds=1800,
                 attempt_seconds=30, max_inflight=4, max_attempts=32):
        self._loop = asyncio.get_running_loop()
        _require(type(seconds) in (int, float) and math.isfinite(seconds)
            and 0 < seconds <= 1800, 'session_duration')
        _require(type(attempt_seconds) in (int, float) and math.isfinite(attempt_seconds)
            and 0 < attempt_seconds <= 30, 'attempt_duration')
        _require(type(max_inflight) is int and 1 <= max_inflight <= 8
            and type(max_attempts) is int and 1 <= max_attempts <= 64, 'session_capacity')
        configured = tuple(aliases)
        _require(configured and len(configured) <= 8
            and all(type(a) is EndpointAlias for a in configured)
            and len({a.name for a in configured}) == len(configured), 'aliases')
        self._aliases = MappingProxyType({a.name: a for a in configured})
        self._adapter = adapter
        self.session_id = secrets.token_urlsafe(32)
        self._deadline = self._loop.time() + seconds
        self._attempt_seconds = attempt_seconds
        self._max_inflight, self._max_attempts = max_inflight, max_attempts
        self._states, self._replies = {}, {}
        self._retained = 0
        self._next = 1
        self.closed = False
        self._timer = self._loop.call_at(self._deadline, self.close)

    def _check_loop(self):
        _require(asyncio.get_running_loop() is self._loop, 'session_loop')

    def _cancel(self, state):
        if state.status == 'running' and not state.cancel_requested:
            state.cancel_requested = True
            # _run must enter its finally before cancellation can reach it.
            if state.task is not None:
                self._loop.call_soon(state.task.cancel)

    def close(self):
        self._check_loop()
        self.closed = True
        self._timer.cancel()
        for state in self._states.values():
            self._cancel(state)

    async def aclose(self):
        """EOF/death fence: do not abandon accepted cleanup when caller cancels."""
        self.close()
        pending = asyncio.gather(*(s.task for s in self._states.values()),
                                 return_exceptions=True)
        canceled = False
        while True:
            try:
                await asyncio.shield(pending)
                break
            except asyncio.CancelledError:
                canceled = True
        if canceled:
            raise asyncio.CancelledError

    def dispatch(self, frame):
        """Accept exactly one frame; any protocol violation closes this session."""
        self._check_loop()
        try:
            message = decode_request(frame)
            seq = message.get('seq')
            _require(type(seq) is int and 1 <= seq <= MAX_MESSAGES, 'sequence')
            try:
                identity = hashlib.sha256(_json(message)).digest()
            except (ValueError, RecursionError, OverflowError):
                raise BridgeRejected('invalid_json') from None
            if seq in self._replies:
                old_identity, reply = self._replies[seq]
                _require(identity == old_identity, 'altered_replay')
                return reply
            _require(not self.closed and self._loop.time() < self._deadline, 'session_closed')
            _require(seq == self._next and message.get('session') == self.session_id,
                     'session_sequence')
            verb = message.get('verb')
            if verb == 'begin':
                _require(set(message) == {'session', 'seq', 'verb', 'alias', 'batch', 'calls'},
                         'begin_shape')
                body = self._begin(message)
            elif verb in ('poll', 'cancel'):
                _require(set(message) == {'session', 'seq', 'verb', 'token'}, 'token_shape')
                token = message['token']
                _require(type(token) is str and _TOKEN.fullmatch(token)
                    and token in self._states, 'foreign_token')
                state = self._states[token]
                if verb == 'cancel':
                    self._cancel(state)
                body = dict(token=token, status=state.status)
                if state.body is not None and not state.cancel_requested:
                    body['body_b64'] = base64.b64encode(state.body).decode('ascii')
            elif verb == 'close':
                _require(set(message) == {'session', 'seq', 'verb'}, 'close_shape')
                self.close()
                body = dict(status='closed')
            else:
                raise BridgeRejected('unknown_verb')
            reply = encode_frame(dict(session=self.session_id, seq=seq, **body))
            _require(self._retained + len(reply) <= MAX_RETAINED, 'retained_bound')
            self._retained += len(reply)
            self._replies[seq] = identity, reply
            self._next += 1
            return reply
        except BridgeRejected:
            self.close()
            raise

    def _begin(self, message):
        name, calls, batch = message['alias'], message['calls'], message['batch']
        _require(type(name) is str and name in self._aliases, 'unknown_alias')
        _require(type(batch) is bool and type(calls) is list and 1 <= len(calls) <= 200
            and (batch or len(calls) == 1), 'batch_shape')
        endpoint = self._aliases[name]
        frozen = []
        for call in calls:
            _require(type(call) is dict and set(call) == {'method', 'params'}, 'call_shape')
            _require(type(call['method']) is str and call['method'] in endpoint.methods,
                     'read_method')
            _require(type(call['params']) is list, 'params_shape')
            _params(call['params'])
            frozen.append(ReadCall(call['method'], _json(call['params'])))
        _require(len(self._states) < self._max_attempts
            and sum(s.status == 'running' for s in self._states.values()) < self._max_inflight,
            'attempt_capacity')
        token = secrets.token_urlsafe(32)
        attempt = ParentAttempt(self.session_id, token, endpoint, tuple(frozen), batch,
            min(self._deadline, self._loop.time() + self._attempt_seconds))
        state = _State(attempt)
        self._states[token] = state
        state.task = self._loop.create_task(self._run(state))
        return dict(token=token, status='accepted')

    async def _run(self, state):
        delivered = None
        outcome = 'failed'
        try:
            async with asyncio.timeout_at(state.attempt.deadline):
                if state.cancel_requested:
                    raise asyncio.CancelledError
                delivered = await self._adapter.execute(state.attempt)
                if self._loop.time() >= state.attempt.deadline:
                    raise TimeoutError
                _require(type(delivered) is Delivered and type(delivered.body) is bytes
                    and len(delivered.body) <= MAX_BODY and type(delivered.eof) is bool,
                    'adapter_delivery')
                _require(delivered.eof, 'incomplete_http_response')
                _require(self._retained + len(delivered.body) <= MAX_RETAINED,
                         'retained_bound')
                outcome = 'canceled' if state.cancel_requested else 'delivered'
        except asyncio.CancelledError:
            outcome = 'canceled'
        except TimeoutError:
            outcome = 'expired'
        except BaseException:
            # Budget stops inherit BaseException. Never let provider sanitizers
            # convert them to another retry, or expose exception text to a child.
            outcome = 'failed'
        finally:
            proven_eof = type(delivered) is Delivered and delivered.eof is True
            cleanup = self._loop.create_task(self._adapter.release(
                state.attempt, uncertain=not proven_eof))
            try:
                while True:
                    try:
                        await asyncio.shield(cleanup)
                        break
                    except asyncio.CancelledError:
                        if cleanup.done() and cleanup.cancelled():
                            raise BridgeRejected('cleanup_canceled') from None
                        outcome = 'canceled'
            except BaseException:
                outcome = 'accounting_failed'
            # No bytes become pollable until all accepted cleanup has completed.
            if outcome == 'delivered' and self._loop.time() >= state.attempt.deadline:
                outcome = 'expired'
            if outcome == 'delivered' and not state.cancel_requested and not self.closed:
                if self._retained + len(delivered.body) > MAX_RETAINED:
                    outcome = 'failed'
                else:
                    state.body = delivered.body
                    self._retained += len(state.body)
            state.status = outcome
            if outcome in ('failed', 'accounting_failed'):
                self.close()
