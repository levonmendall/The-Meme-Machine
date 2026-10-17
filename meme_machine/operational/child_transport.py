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
from types import MappingProxyType


MAX_CONTROL = 384 * 1024
MAX_REQUEST = 64 * 1024
MAX_CONTENT = 16 * 1024 * 1024
CHUNK = 64 * 1024
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')
_NATIVE_ISSUER=object()


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


def _native_descriptor(row,sources):
    _require(type(row) is dict and set(row)=={
        'alias','transport','stream','observation_only','endpoint_identity'}
        and type(row['alias']) is str and row['alias'] in sources
        and row['transport'] in ('yellowstone','solana_websocket','robinhood_sequencer')
        and (row['stream'] is None or type(row['stream']) is str and TOKEN.fullmatch(row['stream']))
        and type(row['observation_only']) is bool and type(row['endpoint_identity']) is str,
        'child_native_descriptor')
    source=sources[row['alias']]
    observed=row['transport']=='robinhood_sequencer'
    if observed:
        from meme_machine.lanes.pons.provider_topology import SEQUENCER_FEED_URL
        identity=hashlib.sha256(SEQUENCER_FEED_URL.encode()).hexdigest()
        family='robinhood'
    else:
        identity=source.endpoint_identity;family='solana'
    _require(row['observation_only'] is observed and source.family==family
        and row['endpoint_identity']==identity,'child_native_source_identity')
    return dict(row)


class ChildChannel:
    """Bounded synchronous control exchanges; concurrent provider work is polled.

    The lock covers one request/reply only, never an admission or network wait.
    Pump and Pons may therefore have concurrent accepted parent operations. Any
    incomplete/malformed exchange closes the capability; there is no reconnect
    or request replay under a replacement sequence after ambiguous transport.
    """
    def __init__(self, connected, *, seconds=1800, cancelled=None):
        _require(type(connected) is socket.socket and connected.family == socket.AF_UNIX
            and connected.getsockopt(socket.SOL_SOCKET,socket.SO_TYPE) == socket.SOCK_STREAM
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
                'response_bytes', 'maximum_messages', 'replay', 'acknowledgements','maximum_streams'}
            _require(type(hello) is dict and set(hello) == expected
                and hello['protocol'] == 'native-parent-transport-v2'
                and type(hello['session']) is str and TOKEN.fullmatch(hello['session'])
                and hello['chunk_bytes'] == CHUNK and hello['response_bytes'] == MAX_CONTENT
                and type(hello['maximum_messages']) is int and 0 < hello['maximum_messages'] <= 1_000_000
                and hello['replay'] == 'most_recent_only'
                and hello['acknowledgements'] == 'transport_memory_only; native owners retain source FULL/ACK'
                and type(hello['sources']) is list and 1 <= len(hello['sources']) <= 32
                and type(hello['maximum_streams']) is int and 1 <= hello['maximum_streams'] <= 32
                and type(hello['streams']) is list and len(hello['streams']) <= 64,
                'child_hello')
            from .parent_transport import SourceReference
            refs = [SourceReference.from_receipt(row) for row in hello['sources']]
            self.sources = MappingProxyType({ref.alias: ref for ref in refs})
            _require(len(self.sources)==len(refs),'child_sources')
            self.maximum_streams=hello['maximum_streams']
            self._native_handles={}
            self._native_sources={}
            self._native_lock=threading.RLock()
            self._native_opening=0
            descriptors=[]
            for row in hello['streams']:
                descriptor=_native_descriptor(row,self.sources)
                descriptors.append(MappingProxyType(descriptor))
                if descriptor['stream'] is None:
                    _require(descriptor['alias'] not in self._native_sources,'child_native_descriptor')
                    self._native_sources[descriptor['alias']]=descriptor
                else:
                    self._issue_native(descriptor)
            _require(len(self._native_handles)<=self.maximum_streams,'child_native_capacity')
            self.streams=tuple(descriptors)
            self.session = hello['session']
            self.maximum_messages = hello['maximum_messages']
        except BaseException:
            self.abort()
            raise

    def _remaining(self, deadline, *, draining=False):
        remaining = min(self.deadline, deadline) - time.monotonic()
        _require(not self.closed and remaining > 0
            and (draining or not (self.cancelled is not None and self.cancelled())), 'child_transport_stopped')
        return remaining

    def _exact(self, count, deadline, *, draining=False):
        chunks = bytearray()
        while len(chunks) < count:
            self.socket.settimeout(min(.25, self._remaining(deadline,draining=draining)))
            try:
                value = self.socket.recv(count - len(chunks))
            except socket.timeout:
                continue
            _require(bool(value), 'child_parent_eof')
            chunks.extend(value)
        return bytes(chunks)

    def _read(self, deadline, *, draining=False):
        size, = struct.unpack('!I', self._exact(4, deadline,draining=draining))
        _require(0 < size <= MAX_CONTROL, 'child_control_bound')
        return _json(self._exact(size, deadline,draining=draining))

    def request(self, verb, *, deadline=None, **fields):
        with self.lock:
            draining=verb in ('poll','read','ack','cancel','native_close','close')
            _require(draining or not(self.cancelled is not None and self.cancelled()),
                'child_transport_stopped')
            try:
                end = min(self.deadline, time.monotonic()+30 if deadline is None else deadline)
                self._remaining(end,draining=draining)
                _require(type(verb) is str and not {'session', 'seq', 'verb'} & set(fields)
                    and self.sequence <= self.maximum_messages, 'child_request_shape')
                seq = self.sequence
                body = json.dumps(dict(session=self.session, seq=seq, verb=verb, **fields),
                    separators=(',', ':'), allow_nan=False).encode()
                _require(0 < len(body) <= MAX_REQUEST, 'child_request_bound')
                self.socket.settimeout(min(1.0, self._remaining(end,draining=draining)))
                self.socket.sendall(struct.pack('!I', len(body)) + body)
                response = self._read(end,draining=draining)
                _require(type(response) is dict and response.get('session') == self.session
                    and type(response.get('seq')) is int and response['seq'] == seq,
                    'child_reply_identity')
                self.sequence += 1
                return {key:value for key,value in response.items() if key not in ('session','seq')}
            except BaseException:
                self.abort()
                raise

    def _content(self, accepted, *, deadline, native=False, expected_stream=None):
        token = accepted.get('token')
        _require(type(token) is str and TOKEN.fullmatch(token)
            and accepted.get('status') == 'accepted', 'child_attempt_token')
        try:
            while True:
                reply = self.request('poll', token=token, deadline=deadline)
                _require(reply.get('token') == token, 'child_attempt_token')
                if expected_stream is not None:
                    _require(reply.get('stream')==expected_stream,'child_native_stream_identity')
                status = reply.get('status')
                if status == 'delivered':
                    break
                if status == 'eof' and native:
                    self.request('cancel', token=token, deadline=deadline)
                    return None
                if status == 'failed':
                    _parent_failure(reply)
                _require(status == 'running', 'child_parent_attempt_failed')
                time.sleep(min(.01, self._remaining(deadline,draining=True)))
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

    def _issue_native(self, descriptor):
        token=descriptor['stream']
        _require(type(token) is str and TOKEN.fullmatch(token)
            and token not in self._native_handles and len(self._native_handles)<1024,
            'child_native_stream_identity')
        value=ChildNativeStream(self,self.sources[descriptor['alias']],token,
            transport=descriptor['transport'],observation_only=descriptor['observation_only'],
            endpoint_identity=descriptor['endpoint_identity'],_issue=_NATIVE_ISSUER)
        self._native_handles[token]=value
        return value

    def native_open(self, reference):
        with self._native_lock:
            _require(self.sources.get(reference.alias) is reference
                and reference.alias in self._native_sources
                and self._native_opening+sum(not stream.closed for stream in self._native_handles.values())<self.maximum_streams,
                'child_native_source')
            descriptor=self._native_sources[reference.alias]
            self._native_opening+=1
        try:
            reply=self._native_control('native_open','opened',alias=reference.alias)
            with self._native_lock:
                return self._issue_native(dict(descriptor,stream=reply['stream']))
        finally:
            with self._native_lock:
                self._native_opening-=1

    def native_stream(self, reference):
        return self.native_open(reference)

    def _native_control(self, verb, terminal, **fields):
        end=min(self.deadline,time.monotonic()+8)
        reply=self.request(verb,deadline=end,**fields)
        token=reply.get('token')
        _require(reply.get('status')=='accepted' and type(token) is str and TOKEN.fullmatch(token),
            'child_native_control_token')
        while True:
            reply=self.request('poll',token=token,deadline=end)
            _require(reply.get('token')==token,'child_native_control_token')
            status=reply.get('status')
            if status==terminal:
                handle=reply.get('stream')
                _require(type(handle) is str and TOKEN.fullmatch(handle),'child_native_stream_identity')
                return reply
            if status=='failed':_parent_failure(reply)
            _require(status=='running','child_native_control_failed')
            time.sleep(min(.01,self._remaining(end,draining=True)))

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


class ChildNativeStream:
    """One actual parent-reserved stream, independently cancellable and bounded.

    A local idle timeout retains one existing read operation. It never opens a
    replacement stream, repeats the provider read or mints another reservation.
    """
    __slots__=('channel','source','stream','transport','observation_only','endpoint_identity',
        'closed','_pending','_state_lock','_read_lock')

    def __init__(self,channel,source,stream,*,transport,observation_only,endpoint_identity,_issue=None):
        _require(_issue is _NATIVE_ISSUER and type(channel) is ChildChannel
            and channel.sources.get(source.alias) is source,'child_native_issuer_required')
        for name,value in dict(channel=channel,source=source,stream=stream,transport=transport,
                observation_only=observation_only,endpoint_identity=endpoint_identity,closed=False,
                _pending=None,_state_lock=threading.RLock(),_read_lock=threading.Lock()).items():
            object.__setattr__(self,name,value)

    def __setattr__(self,name,value):
        raise AttributeError('immutable_child_native_stream')

    def read(self,timeout=None):
        _require(timeout is None or type(timeout) in (int,float) and 0<=timeout<=1800,
            'child_native_read_timeout')
        deadline=self.channel.deadline if timeout is None else min(self.channel.deadline,time.monotonic()+timeout)
        _require(self._read_lock.acquire(blocking=False),'child_native_read_in_flight')
        try:
            while True:
                with self._state_lock:
                    require_native_stream(self)
                    if self._pending is None:
                        _require(not (self.channel.cancelled is not None and self.channel.cancelled()),
                            'child_transport_stopped')
                        reply=self.channel.request('native_read',stream=self.stream)
                        token=reply.get('token')
                        _require(reply.get('status')=='accepted' and type(token) is str
                            and TOKEN.fullmatch(token),'child_native_read_token')
                        object.__setattr__(self,'_pending',token)
                    if time.monotonic()>=deadline:
                        raise TimeoutError('child_native_idle')
                    reply=self.channel.request('poll',token=self._pending)
                    _require(reply.get('token')==self._pending and reply.get('stream')==self.stream,
                        'child_native_read_identity')
                    if reply.get('status')=='delivered':
                        value=self.channel._content(dict(token=self._pending,status='accepted'),
                            deadline=min(self.channel.deadline,time.monotonic()+30),native=True,
                            expected_stream=self.stream)
                        object.__setattr__(self,'_pending',None)
                        return value
                    if reply.get('status')=='eof':
                        self.channel.request('cancel',token=self._pending)
                        object.__setattr__(self,'_pending',None)
                        object.__setattr__(self,'closed',True)
                        return None
                    if reply.get('status')=='failed':
                        self.channel.request('cancel',token=self._pending)
                        object.__setattr__(self,'_pending',None)
                        object.__setattr__(self,'closed',True)
                        _parent_failure(reply)
                    _require(reply.get('status')=='running','child_native_read_state')
                time.sleep(min(.01,max(0,deadline-time.monotonic())))
        finally:
            self._read_lock.release()

    async def read_async(self,timeout=None):
        task=asyncio.create_task(asyncio.to_thread(self.read,timeout))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await self.close_async()
            await asyncio.gather(task,return_exceptions=True)
            raise

    def write(self,body):
        with self._state_lock:
            require_native_stream(self)
            _require(not self.observation_only and type(body) is bytes and len(body)<=32768,
                'child_native_write')
            reply=self.channel._native_control('native_write','written',stream=self.stream,
                body_b64=base64.b64encode(body).decode())
            _require(reply['stream']==self.stream,'child_native_stream_identity')

    async def write_async(self,body):
        await asyncio.to_thread(self.write,body)

    def close(self):
        with self._state_lock:
            if self.closed:
                return
            object.__setattr__(self,'closed',True)
            if self.channel.closed:
                object.__setattr__(self,'_pending',None)
                return
            reply=self.channel._native_control('native_close','closed',stream=self.stream)
            _require(reply['stream']==self.stream,'child_native_stream_identity')
            if self._pending is not None:
                self.channel.request('cancel',token=self._pending)
                object.__setattr__(self,'_pending',None)

    async def close_async(self):
        task=asyncio.create_task(asyncio.to_thread(self.close))
        canceled=False
        while True:
            try:
                await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                canceled=True
        if canceled:
            raise asyncio.CancelledError


def require_native_stream(value,transport=None):
    _require(type(value) is ChildNativeStream and type(value.channel) is ChildChannel
        and not value.channel.closed and not value.closed
        and value.channel._native_handles.get(value.stream) is value
        and value.channel.sources.get(value.source.alias) is value.source
        and (transport is None or value.transport==transport),'child_native_stream_required')
    return value


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
        return self.envelope_delivered(request,deadline=deadline)[0]

    def envelope_delivered(self, request, *, deadline=None):
        """Return exact child handoff bytes, separately from parent socket usage."""
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
        return reply,dict(bytes=len(raw))

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
