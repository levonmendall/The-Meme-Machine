"""The isolated child's only external transport: an inherited anonymous channel.

This module cannot resolve provider URLs, open a listening socket or create a
provider ledger. Parent handoff acknowledgements only release transport memory;
the actual child Evidence/History owners still earn their own FULL/consumer ACKs.
The fixed bootstrap must enforce its OS boundary before constructing this port.
"""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import contextvars
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
UPLOAD_MAX=4*1024*1024
UPLOAD_CHUNK=32*1024
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


async def _settled(future):
    """Join an accepted operation despite repeated cancellation of its waiter."""
    while not future.done():
        try:await asyncio.shield(future)
        except asyncio.CancelledError:continue
        except BaseException:break
    return future.result()


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
    def __init__(self, connected, *, seconds=1800, cancelled=None,lifecycle=None):
        _require(type(connected) is socket.socket and connected.family == socket.AF_UNIX
            and connected.getsockopt(socket.SOL_SOCKET,socket.SO_TYPE) == socket.SOCK_STREAM
            and connected.getpeername() in ('', b'')
            and type(seconds) in (int, float) and 0 < seconds <= 1800
            and (cancelled is None or callable(cancelled)), 'child_channel_configuration')
        from .isolated_native_lifetime import NativeLifecycleObservation
        _require(lifecycle is None or type(lifecycle) is NativeLifecycleObservation,
            'child_lifecycle_observation')
        self._lifecycle=lifecycle
        self.socket = connected
        self.deadline = time.monotonic() + seconds
        self.cancelled = cancelled
        self.lock = threading.RLock()
        self.sequence = 1
        self.closed = False
        self._fault_lock=threading.Lock()
        self._first_abort=None
        self._read_lane=None
        self._native_reads={}
        self._read_owner=threading.local()
        try:
            hello = self._read(self.deadline)
            expected = {'session', 'protocol', 'sources', 'streams', 'chunk_bytes',
                'response_bytes', 'maximum_messages', 'replay', 'acknowledgements','maximum_streams',
                'upload_bytes','upload_chunk_bytes','upload_slots'}
            expected.add('http_workers')
            _require(type(hello) is dict and set(hello) == expected
                and hello['protocol'] == 'native-parent-transport-v4'
                and type(hello['http_workers']) is int and 1<=hello['http_workers']<=8
                and type(hello['upload_bytes']) is int and hello['upload_bytes']==UPLOAD_MAX
                and type(hello['upload_chunk_bytes']) is int and hello['upload_chunk_bytes']==UPLOAD_CHUNK
                and type(hello['upload_slots']) is int and hello['upload_slots']==1
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
            self.http_workers=hello['http_workers']
            self._http_slots=threading.BoundedSemaphore(self.http_workers)
            self._native_handles={}
            self._native_sources={}
            self._native_lock=threading.RLock()
            self._native_opening=0
            self._upload_lock=threading.Lock()
            self._pons_profiles={}
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
            # Idle native reads must never occupy asyncio's shared executor:
            # RPC, write and close operations still need that execution lane.
            self._read_lane=ThreadPoolExecutor(max_workers=self.maximum_streams,
                thread_name_prefix='isolated-native-read')
        except BaseException as error:
            self.abort(error,phase='CONTROL_EXCHANGE')
            raise

    def _remaining(self, deadline, *, draining=False):
        now=time.monotonic();remaining = min(self.deadline, deadline) - now
        closed=self.closed;cancel_checked=False;cancelled=None
        allowed=not closed and remaining>0
        if allowed and not draining:
            cancel_checked=True
            cancelled=bool(self.cancelled is not None and self.cancelled())
            allowed=not cancelled
        if not allowed:
            error=ChildTransportFailure('child_transport_stopped')
            error._remaining_observation=dict(monotonic=now,channel_deadline=self.deadline,
                operation_deadline=deadline,remaining_seconds=remaining,closed=closed,
                draining=draining,cancel_checked=cancel_checked,cancelled=cancelled,
                channel_expired=now>=self.deadline,operation_expired=now>=deadline)
            raise error
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
            draining=verb in ('poll','read','ack','cancel','native_close','close','native_upload_cancel')
            _require(draining or not(self.cancelled is not None and self.cancelled()),
                'child_transport_stopped')
            end = min(self.deadline, time.monotonic()+30 if deadline is None else deadline)
            # No byte or sequence has been sent. Local admission expiration
            # cannot make an unrelated accepted operation ambiguous.
            self._remaining(end,draining=draining)
            try:
                _require(type(verb) is str and not {'session', 'seq', 'verb'} & set(fields)
                    and self.sequence <= self.maximum_messages, 'child_request_shape')
                seq = self.sequence
                body = json.dumps(dict(session=self.session, seq=seq, verb=verb, **fields),
                    separators=(',', ':'), allow_nan=False).encode()
                _require(0 < len(body) <= MAX_REQUEST, 'child_request_bound')
            except BaseException as error:
                self.abort(error,phase='CONTROL_EXCHANGE')
                raise
            # Encoding or descheduling may consume the remaining admission
            # window. This final check is still before any socket mutation or
            # send; malformed shapes above retain their fail-closed behavior.
            remaining=self._remaining(end,draining=draining)
            try:
                self.socket.settimeout(min(1.0, remaining))
                self.socket.sendall(struct.pack('!I', len(body)) + body)
                response = self._read(end,draining=draining)
                _require(type(response) is dict and response.get('session') == self.session
                    and type(response.get('seq')) is int and response['seq'] == seq,
                    'child_reply_identity')
                self.sequence += 1
                return {key:value for key,value in response.items() if key not in ('session','seq')}
            except BaseException as error:
                self.abort(error,phase='CONTROL_EXCHANGE')
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
        except BaseException as error:
            # Ambiguous control loss closes the parent session, which owns the
            # real uncertain cleanup. Do not mint a replacement receipt/token.
            self.abort(error,phase='CONTENT_HANDOFF')
            raise

    def http(self, reference, calls, *, batch=False, deadline=None):
        _require(self.sources.get(reference.alias) is reference, 'child_source_owner')
        end = min(self.deadline, time.monotonic()+30 if deadline is None else deadline)
        while True:
            remaining=self._remaining(end)
            if self._http_slots.acquire(timeout=min(.05,remaining)):break
        try:
            self._remaining(end)
            accepted = self.request('http_begin', alias=reference.alias,
                calls=[dict(method=m, params=p) for m,p in calls], batch=batch, deadline=end)
            return self._content(accepted, deadline=end)
        finally:self._http_slots.release()

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

    def _run_native_read(self,stream,timeout):
        from meme_machine.runtime.isolated_native_execution import install_isolated_native_execution
        install_isolated_native_execution()
        self._read_owner.active=True
        try:return stream.read(timeout)
        finally:self._read_owner.active=False

    def _submit_native_read(self,stream,timeout):
        with self._native_lock:
            require_native_stream(stream)
            _require(stream.channel is self and stream.stream not in self._native_reads,
                'child_native_read_in_flight')
            _require(len(self._native_reads)<self.maximum_streams,'child_native_read_capacity')
            context=contextvars.copy_context()
            try:future=self._read_lane.submit(context.run,self._run_native_read,stream,timeout)
            except BaseException as error:
                # ThreadPoolExecutor may enqueue before starting a worker.
                # Refuse the whole channel, cancel its queued work and retain
                # the lane for the outer owner's real join after any failure.
                self.abort(error,phase='NATIVE_READ_SUBMIT')
                raise
            self._native_reads[stream.stream]=future
            return future

    def _release_native_read(self,stream,future):
        with self._native_lock:
            # The async owner releases this only after the accepted read and
            # any cancellation-triggered close have actually joined.
            if future.done() and self._native_reads.get(stream.stream) is future:
                del self._native_reads[stream.stream]

    def pons_profile(self,source):
        from .parent_transport import SourceReference
        from .pons_native_profile import profile_from_parent
        _require(type(source) is SourceReference and self.sources.get(source.alias) is source
            and source.family=='robinhood','child_pons_profile_source')
        with self.lock:
            if source.alias not in self._pons_profiles:
                reply=self.request('pons_profile',alias=source.alias)
                _require(set(reply)=={'profile'},'child_pons_profile_shape')
                self._pons_profiles[source.alias]=profile_from_parent(self,source,reply['profile'])
            return self._pons_profiles[source.alias]

    def _native_control(self, verb, terminal, *, deadline=None, accepted=None, cancelled=None, **fields):
        end=min(self.deadline,time.monotonic()+8 if deadline is None else deadline)
        reply=self.request(verb,deadline=end,**fields) if accepted is None else accepted
        token=reply.get('token')
        _require(reply.get('status')=='accepted' and type(token) is str and TOKEN.fullmatch(token),
            'child_native_control_token')
        while True:
            if cancelled is not None and cancelled():
                self.request('cancel',token=token,deadline=end)
                raise ChildTransportFailure('child_native_write_canceled')
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

    def _native_upload(self,stream,body,cancelled=None):
        end=min(self.deadline,time.monotonic()+8)
        _require(self._upload_lock.acquire(timeout=max(0,end-time.monotonic())),
            'child_upload_capacity_deadline')
        upload=None
        committed=False
        try:
            _require(cancelled is None or not cancelled(),'child_native_write_canceled')
            begin=self.request('native_upload_begin',stream=stream,bytes=len(body),
                sha256=hashlib.sha256(body).hexdigest(),deadline=end)
            upload=begin.get('upload')
            _require(set(begin)=={'upload','stream','status','next_offset'}
                and type(upload) is str and TOKEN.fullmatch(upload)
                and begin['stream']==stream and begin['status']=='uploading'
                and type(begin['next_offset']) is int and begin['next_offset']==0,'child_upload_begin')
            offset=0
            while offset<len(body):
                _require(cancelled is None or not cancelled(),'child_native_write_canceled')
                chunk=body[offset:offset+UPLOAD_CHUNK]
                reply=self.request('native_upload_chunk',upload=upload,stream=stream,offset=offset,
                    body_b64=base64.b64encode(chunk).decode(),deadline=end)
                offset+=len(chunk)
                _require(set(reply)=={'upload','stream','status','next_offset'}
                    and reply['upload']==upload and reply['stream']==stream
                    and reply['status']=='uploading' and type(reply['next_offset']) is int
                    and reply['next_offset']==offset,'child_upload_chunk')
            _require(cancelled is None or not cancelled(),'child_native_write_canceled')
            accepted=self.request('native_upload_commit',upload=upload,stream=stream,deadline=end)
            committed=True
            return self._native_control(None,'written',deadline=end,accepted=accepted,cancelled=cancelled)
        except BaseException as error:
            if upload is not None and not committed and not self.closed:
                try:self.request('native_upload_cancel',upload=upload,stream=stream,deadline=end)
                except BaseException as cleanup_error:self.abort(cleanup_error,phase='NATIVE_UPLOAD_CANCEL')
            elif committed and not self.closed and not isinstance(error,ChildParentFailure) \
                    and str(error)!='child_native_write_canceled':
                # A terminal parent failure has already joined stream cleanup;
                # any ambiguous commit/poll instead closes the sole capability.
                self.abort(error,phase='NATIVE_UPLOAD')
            raise
        finally:self._upload_lock.release()

    def abort_snapshot(self):
        with self._fault_lock:
            return None if self._first_abort is None else dict(self._first_abort)

    def abort(self,error=None,*,phase=None):
        if self._lifecycle is not None:
            from .isolated_native_lifetime import observe_lifecycle
            observe_lifecycle(self._lifecycle,'CHANNEL_ABORT_REQUESTED','CHANNEL_ABORT',
                reason='TRANSPORT_ERROR' if error is not None else 'NORMAL_CLOSE')
        if error is not None:
            try:
                from .transport_bridge import transport_fault
                fault=transport_fault(error,phase)
            except BaseException:
                fault=dict(phase='UNKNOWN',error_type='PROJECTION_UNAVAILABLE',
                    source_module=None,source_line=None,trace_complete=False)
            with self._fault_lock:
                if self._first_abort is None:self._first_abort=fault
        self.closed = True
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()
        if self._read_lane is not None:
            # request() may abort while holding the control lock, or from a read
            # worker itself. Joining here could deadlock that original failure.
            self._read_lane.shutdown(wait=False,cancel_futures=True)

    def abort_and_join(self):
        self.abort()
        _require(not getattr(self._read_owner,'active',False) and not self.lock._is_owned(),
            'child_native_read_owner_join_required')
        if self._read_lane is not None:
            self._read_lane.shutdown(wait=True,cancel_futures=True)
        with self._native_lock:
            _require(all(future.done() for future in self._native_reads.values()),
                'child_native_read_join_incomplete')
            self._native_reads.clear()

    def close(self):
        _require(not getattr(self._read_owner,'active',False),
            'child_native_read_owner_join_required')
        try:
            if not self.closed:
                _require(self.request('close') == {'status':'closed'}, 'child_close_reply')
        finally:self.abort_and_join()


class ChildNativeStream:
    """One actual parent-reserved stream, independently cancellable and bounded.

    A local idle timeout retains one existing read operation. It never opens a
    replacement stream, repeats the provider read or mints another reservation.
    """
    __slots__=('channel','source','stream','transport','observation_only','endpoint_identity',
        'closed','_pending','_state_lock','_read_lock','_write_lock','_write_cancel','_close_lock')

    def __init__(self,channel,source,stream,*,transport,observation_only,endpoint_identity,_issue=None):
        _require(_issue is _NATIVE_ISSUER and type(channel) is ChildChannel
            and channel.sources.get(source.alias) is source,'child_native_issuer_required')
        for name,value in dict(channel=channel,source=source,stream=stream,transport=transport,
                observation_only=observation_only,endpoint_identity=endpoint_identity,closed=False,
                _pending=None,_state_lock=threading.RLock(),_read_lock=threading.Lock(),
                _write_lock=threading.Lock(),_write_cancel=None,_close_lock=threading.Lock()).items():
            object.__setattr__(self,name,value)

    def __setattr__(self,name,value):
        raise AttributeError('immutable_child_native_stream')

    def _mark_closed(self,reason):
        observer=self.channel._lifecycle
        if observer is not None:
            from .isolated_native_lifetime import observe_lifecycle
            observe_lifecycle(observer,'STREAM_CLOSED','NATIVE_STREAM',reason=reason,
                stream_kind=self.transport,worker='pons' if self.transport=='robinhood_sequencer' else 'pump')
        object.__setattr__(self,'closed',True)

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
                        self._mark_closed('EOF')
                        return None
                    if reply.get('status')=='failed':
                        self.channel.request('cancel',token=self._pending)
                        object.__setattr__(self,'_pending',None)
                        self._mark_closed('PARENT_FAILED')
                        _parent_failure(reply)
                    _require(reply.get('status')=='running','child_native_read_state')
                time.sleep(min(.01,max(0,deadline-time.monotonic())))
        finally:
            self._read_lock.release()

    async def read_async(self,timeout=None):
        accepted=self.channel._submit_native_read(self,timeout)
        task=asyncio.wrap_future(accepted)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            failure=None
            closing=asyncio.create_task(self.close_async())
            try:await _settled(closing)
            except BaseException as error:failure=error
            try:await _settled(task)
            except BaseException:pass
            if failure is not None:raise failure
            raise
        finally:self.channel._release_native_read(self,accepted)

    def write(self,body):
        return self._write(body,None)

    def _write(self,body,cancelled):
        with self._write_lock:
            stopped=threading.Event()
            with self._state_lock:
                require_native_stream(self)
                maximum=UPLOAD_MAX if self.transport=='yellowstone' else 32768
                _require(not self.observation_only and type(body) is bytes and len(body)<=maximum,
                    'child_native_write')
                object.__setattr__(self,'_write_cancel',stopped)
            try:
                def stop():return stopped.is_set() or cancelled is not None and cancelled()
                # gRPC is duplex: source reads and their handoff ACKs must run
                # while this stream's subscription SDK write is pending.
                if self.transport=='yellowstone':reply=self.channel._native_upload(self.stream,body,stop)
                else:
                    reply=self.channel._native_control('native_write','written',stream=self.stream,
                        body_b64=base64.b64encode(body).decode(),cancelled=stop)
                _require(reply['stream']==self.stream,'child_native_stream_identity')
            finally:
                with self._state_lock:
                    if self._write_cancel is stopped:object.__setattr__(self,'_write_cancel',None)

    async def write_async(self,body):
        canceled=threading.Event()
        task=asyncio.create_task(asyncio.to_thread(self._write,body,canceled.is_set))
        try:await asyncio.shield(task)
        except asyncio.CancelledError:
            canceled.set()
            await asyncio.gather(task,return_exceptions=True)
            raise

    def close(self):
        with self._close_lock:self._close_owned()

    def _close_owned(self):
        with self._state_lock:
            if self.closed:
                return
            self._mark_closed('OWNER_CLOSE')
            if self._write_cancel is not None:self._write_cancel.set()
        # Signal under the state lock, then join outside it. Otherwise writer
        # finally/read drainage cannot take the state lock needed for teardown.
        with self._write_lock,self._state_lock:
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
