"""The isolated child's only external transport: an inherited anonymous channel.

This module cannot resolve provider URLs, open a listening socket or create a
provider ledger. Parent handoff acknowledgements only release transport memory;
the actual child Evidence/History owners still earn their own FULL/consumer ACKs.
The fixed bootstrap must enforce its OS boundary before constructing this port.
"""
import asyncio
import base64
import hashlib
import json
import math
import re
import socket
import struct
import threading
import time


MAX_CONTROL = 384 * 1024
MAX_REQUEST = 64 * 1024
MAX_CONTENT = 16 * 1024 * 1024
CHUNK = 64 * 1024
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')


class ChildTransportFailure(ValueError):
    """Fixed classifications only; no provider text, URLs or payloads."""


class ChildParentFailure(ChildTransportFailure):
    pass


def _parent_failure(reply):
    value = reply.get('boundary')
    from meme_machine.runtime.robinhood.provider_authority import failure_class
    native = {'candidate_native_unavailable', 'candidate_native_internal',
        'candidate_native_deadline_exceeded', 'candidate_native_cancelled',
        'candidate_native_resource_exhausted'}
    if type(value) is str and (value in native or failure_class(ValueError(value)) == value):
        raise ChildParentFailure(value)
    raise ChildParentFailure('child_parent_attempt_failed')


def _require(condition, code):
    if not condition:
        raise ChildTransportFailure(code)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'child_duplicate_field')
        result[key] = value
    return result


def _number(raw):
    value = float(raw)
    _require(math.isfinite(value), 'child_nonfinite_number')
    return value


def _json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique, parse_float=_number,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ChildTransportFailure('child_nonfinite_number')))
    except (UnicodeError, RecursionError, ValueError):
        raise ChildTransportFailure('child_invalid_json') from None


class ChildChannel:
    """Bounded synchronous control exchanges; concurrent provider work is polled.

    The lock covers one request/reply only, never an admission or network wait.
    Pump and Pons may therefore have concurrent accepted parent operations. Any
    incomplete/malformed exchange closes the capability; there is no reconnect
    or request replay under a replacement sequence after ambiguous transport.
    """
    def __init__(self, connected, *, seconds=1800, cancelled=None):
        _require(type(connected) is socket.socket and connected.family == socket.AF_UNIX
            and connected.type & socket.SOCK_STREAM == socket.SOCK_STREAM
            and connected.getpeername() in ('', b'')
            and type(seconds) in (int, float) and 0 < seconds <= 1800
            and (cancelled is None or callable(cancelled)), 'child_channel_configuration')
        self.socket = connected
        self.deadline = time.monotonic() + seconds
        self.cancelled = cancelled
        self.lock = threading.RLock()
        self.sequence = 1
        self.closed = False
        try:
            hello = self._read(self.deadline)
            expected = {'session', 'protocol', 'sources', 'streams', 'chunk_bytes',
                'response_bytes', 'maximum_messages', 'replay', 'acknowledgements'}
            _require(type(hello) is dict and set(hello) == expected
                and hello['protocol'] == 'native-parent-transport-v1'
                and type(hello['session']) is str and TOKEN.fullmatch(hello['session'])
                and hello['chunk_bytes'] == CHUNK and hello['response_bytes'] == MAX_CONTENT
                and type(hello['maximum_messages']) is int and 0 < hello['maximum_messages'] <= 1_000_000
                and hello['replay'] == 'most_recent_only'
                and hello['acknowledgements'] == 'transport_memory_only; native owners retain source FULL/ACK'
                and type(hello['sources']) is list and 1 <= len(hello['sources']) <= 8
                and type(hello['streams']) is list and len(hello['streams']) <= 8,
                'child_hello')
            from .parent_transport import SourceReference
            refs = [SourceReference.from_receipt(row) for row in hello['sources']]
            self.sources = {ref.alias: ref for ref in refs}
            _require(len(self.sources) == len(refs)
                and len(set(hello['streams'])) == len(hello['streams'])
                and all(alias in self.sources for alias in hello['streams']), 'child_sources')
            self.streams = frozenset(hello['streams'])
            self.session = hello['session']
            self.maximum_messages = hello['maximum_messages']
        except BaseException:
            self.abort()
            raise

    def _remaining(self, deadline):
        remaining = min(self.deadline, deadline) - time.monotonic()
        _require(not self.closed and remaining > 0
            and not (self.cancelled is not None and self.cancelled()), 'child_transport_stopped')
        return remaining

    def _exact(self, count, deadline):
        chunks = bytearray()
        while len(chunks) < count:
            self.socket.settimeout(min(.25, self._remaining(deadline)))
            try:
                value = self.socket.recv(count - len(chunks))
            except socket.timeout:
                continue
            _require(bool(value), 'child_parent_eof')
            chunks.extend(value)
        return bytes(chunks)

    def _read(self, deadline):
        size, = struct.unpack('!I', self._exact(4, deadline))
        _require(0 < size <= MAX_CONTROL, 'child_control_bound')
        return _json(self._exact(size, deadline))

    def request(self, verb, *, deadline=None, **fields):
        with self.lock:
            try:
                end = min(self.deadline, time.monotonic()+30 if deadline is None else deadline)
                self._remaining(end)
                _require(type(verb) is str and not {'session', 'seq', 'verb'} & set(fields)
                    and self.sequence <= self.maximum_messages, 'child_request_shape')
                seq = self.sequence
                body = json.dumps(dict(session=self.session, seq=seq, verb=verb, **fields),
                    separators=(',', ':'), allow_nan=False).encode()
                _require(0 < len(body) <= MAX_REQUEST, 'child_request_bound')
                self.socket.settimeout(min(1.0, self._remaining(end)))
                self.socket.sendall(struct.pack('!I', len(body)) + body)
                response = self._read(end)
                _require(type(response) is dict and response.get('session') == self.session
                    and type(response.get('seq')) is int and response['seq'] == seq,
                    'child_reply_identity')
                self.sequence += 1
                return {key:value for key,value in response.items() if key not in ('session','seq')}
            except BaseException:
                self.abort()
                raise

    def _content(self, accepted, *, deadline, native=False):
        token = accepted.get('token')
        _require(type(token) is str and TOKEN.fullmatch(token)
            and accepted.get('status') == 'accepted', 'child_attempt_token')
        try:
            while True:
                reply = self.request('poll', token=token, deadline=deadline)
                _require(reply.get('token') == token, 'child_attempt_token')
                status = reply.get('status')
                if status == 'delivered':
                    break
                if status == 'eof' and native:
                    self.request('cancel', token=token, deadline=deadline)
                    return None
                if status == 'failed':
                    _parent_failure(reply)
                _require(status == 'running', 'child_parent_attempt_failed')
                time.sleep(min(.01, self._remaining(deadline)))
            size = reply.get('bytes')
            _require(type(size) is int and 0 <= size <= MAX_CONTENT, 'child_content_bound')
            body = bytearray()
            while True:
                offset = len(body)
                chunk = self.request('read', token=token, offset=offset, deadline=deadline)
                _require(chunk.get('token') == token and chunk.get('status') == 'delivered'
                    and type(chunk.get('offset')) is int and chunk['offset'] == offset
                    and type(chunk.get('body_b64')) is str and type(chunk.get('sha256')) is str
                    and type(chunk.get('final')) is bool, 'child_chunk_shape')
                try:
                    raw = base64.b64decode(chunk['body_b64'], validate=True)
                except ValueError:
                    raise ChildTransportFailure('child_chunk_encoding') from None
                _require(len(raw) <= CHUNK and len(body)+len(raw) <= size
                    and (raw or size == 0) and hashlib.sha256(raw).hexdigest() == chunk['sha256']
                    and chunk['final'] == (offset+len(raw) == size), 'child_chunk_integrity')
                body.extend(raw)
                ack = self.request('ack', token=token, offset=offset, sha256=chunk['sha256'], deadline=deadline)
                _require(ack.get('token') == token and ack.get('next_offset') == len(body)
                    and ack.get('status') == ('consumed' if chunk['final'] else 'delivered'),
                    'child_chunk_ack')
                if chunk['final']:
                    return bytes(body)
        except ChildParentFailure:
            if not self.closed:
                self.request('cancel', token=token, deadline=deadline)
            raise
        except BaseException:
            # Ambiguous control loss closes the parent session, which owns the
            # real uncertain cleanup. Do not mint a replacement receipt/token.
            self.abort()
            raise

    def http(self, reference, calls, *, batch=False, deadline=None):
        _require(self.sources.get(reference.alias) is reference, 'child_source_owner')
        end = min(self.deadline, time.monotonic()+30 if deadline is None else deadline)
        accepted = self.request('http_begin', alias=reference.alias,
            calls=[dict(method=m, params=p) for m,p in calls], batch=batch, deadline=end)
        return self._content(accepted, deadline=end)

    def demand(self, reference, methods):
        _require(self.sources.get(reference.alias) is reference, 'child_source_owner')
        reply = self.request('demand', alias=reference.alias, methods=list(methods))
        _require(reply == {'status':'demand_committed'}, 'child_demand_reply')

    def activity_marker(self, reference):
        _require(self.sources.get(reference.alias) is reference, 'child_source_owner')
        reply = self.request('activity', alias=reference.alias)
        marker = reply.get('activity_marker')
        _require(set(reply) == {'activity_marker'} and type(marker) is list and len(marker) == 2
            and all(type(value) in (int,float) and math.isfinite(value) and value >= 0
                for value in marker), 'child_activity_reply')
        return tuple(marker)

    def native_read(self, reference):
        _require(self.sources.get(reference.alias) is reference
            and reference.alias in self.streams, 'child_native_source')
        end = min(self.deadline, time.monotonic()+30)
        return self._content(self.request('native_read', alias=reference.alias, deadline=end),
            deadline=end, native=True)

    async def native_read_async(self, reference):
        task = asyncio.create_task(asyncio.to_thread(self.native_read, reference))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            self.abort()
            await asyncio.gather(task, return_exceptions=True)
            raise

    def native_write(self, reference, body):
        _require(self.sources.get(reference.alias) is reference and reference.alias in self.streams
            and type(body) is bytes and len(body) <= 32768, 'child_native_write')
        self._native_control(reference, 'native_write', 'written',
            body_b64=base64.b64encode(body).decode())

    def _native_control(self, reference, verb, terminal, **fields):
        _require(self.sources.get(reference.alias) is reference
            and reference.alias in self.streams, 'child_native_source')
        end = min(self.deadline, time.monotonic()+8)
        reply = self.request(verb, alias=reference.alias, deadline=end, **fields)
        token = reply.get('token')
        _require(reply.get('status') == 'accepted' and type(token) is str
            and TOKEN.fullmatch(token), 'child_native_control_token')
        while True:
            reply = self.request('poll', token=token, deadline=end)
            _require(reply.get('token') == token, 'child_native_control_token')
            status = reply.get('status')
            if status == terminal:
                return
            if status == 'failed':
                _parent_failure(reply)
            _require(status == 'running', 'child_native_control_failed')
            time.sleep(min(.01, self._remaining(end)))

    def native_open(self, reference):
        self._native_control(reference, 'native_open', 'opened')

    def native_close(self, reference):
        self._native_control(reference, 'native_close', 'closed')

    def abort(self):
        self.closed = True
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()

    def close(self):
        if not self.closed:
            try:
                _require(self.request('close') == {'status':'closed'}, 'child_close_reply')
            finally:
                self.abort()


class ChildRPCPort:
    """An immutable alias selected from this channel's authenticated hello.

    No callable, path, endpoint, credential, priority or allowance is accepted.
    Source references are authenticated by the protected parent/channel binding,
    not by hashing the child's copy. This object grants read transports only.
    """
    __slots__ = ('channel', 'source')

    def __init__(self, channel, alias):
        _require(type(channel) is ChildChannel and not channel.closed
            and type(alias) is str and alias in channel.sources, 'child_rpc_port')
        object.__setattr__(self, 'channel', channel)
        object.__setattr__(self, 'source', channel.sources[alias])

    def __setattr__(self, name, value):
        raise AttributeError('immutable_child_rpc_port')

    def envelope(self, request, *, deadline=None):
        batch = type(request) is list
        calls = request if batch else [request]
        _require(1 <= len(calls) <= 200 and all(type(row) is dict
            and set(row) == {'jsonrpc','id','method','params'} and row['jsonrpc'] == '2.0'
            and type(row['id']) is int and type(row['method']) is str
            and type(row['params']) is list for row in calls), 'child_rpc_request')
        identifiers = [row['id'] for row in calls]
        _require(len(set(identifiers)) == len(identifiers), 'child_rpc_identifiers')
        raw = self.channel.http(self.source, [(row['method'],row['params']) for row in calls],
            batch=batch, deadline=deadline)
        reply = _json(raw)
        rows = reply if batch else [reply]
        _require(type(rows) is list and len(rows) == len(calls)
            and all(type(row) is dict and row.get('jsonrpc') == '2.0'
                and type(row.get('id')) is int for row in rows), 'child_rpc_envelope')
        indices = [row['id'] for row in rows]
        _require(set(indices) == set(range(1,len(calls)+1))
            and len(set(indices)) == len(indices), 'child_rpc_identifiers')
        # Parent request identifiers are local to one original physical batch.
        # Preserve the caller's IDs and provider order for native parsing.
        for row in rows:
            row['id'] = identifiers[row['id']-1]
        from meme_machine.solana_provider_config import public_value
        public_value(reply)
        return reply

    def demand(self, methods):
        self.channel.demand(self.source, methods)

    def activity_marker(self):
        return self.channel.activity_marker(self.source)


def require_rpc_port(port, family):
    _require(type(port) is ChildRPCPort and type(port.channel) is ChildChannel
        and not port.channel.closed and port.source.family == family
        and port.channel.sources.get(port.source.alias) is port.source,
        'child_rpc_port_required')
    return port
