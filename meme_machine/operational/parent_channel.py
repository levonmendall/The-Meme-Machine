"""Bounded, already-connected private IPC; no listener or filesystem endpoint.

The fixed bootstrap must pass an anonymous socketpair after source/OS checks.
Chunk acknowledgements release transport memory only. They never issue native
canonical/FULL/consumer ACK, financial disposition or readiness evidence.
"""
import asyncio
import base64
from dataclasses import dataclass
import hashlib
import json
import re
import secrets

from .bounded_provider import MAX_FRAME
from .parent_transport import ParentHTTP, ParentNativeStream, ParentTransportFailure, NativeSourceBinding, NativeFactoryMap
from .transport_bridge import (
    BridgeRejected, ParentAttempt, ReadCall, Delivered, _json, _params, _require,
    decode_request, encode_frame, read_request_frame,
)

CHUNK = 64 * 1024
MAX_MESSAGES = 1_000_000
UPLOAD_MAX = 4 * 1024 * 1024
UPLOAD_CHUNK = 32 * 1024


@dataclass
class _Upload:
    token: str
    stream_id: str
    size: int
    sha256: str
    deadline: float
    data: object
    digest: object
    offset: int = 0
    timer: object = None
    committed: bool = False


@dataclass
class _Content:
    task: object
    kind: str
    attempt: object = None
    body: bytes | None = None
    offset: int = 0
    pending: object = None
    status: str = 'running'
    sequence: int | None = None
    boundary: str | None = None
    alias: str | None = None
    stream: object = None
    stream_id: str | None = None


class ParentChannel:
    """One bounded child capability, preserving concurrent parent I/O.

    Exact most-recent-message replay returns its original response. Older or
    altered sequences close the channel; no replay creates another acquisition.
    Content is separate from the bounded control replay cache. A whole HTTP/native
    response may reach MAX_FRAME, delivered in acknowledged 64-KiB chunks. Native
    buffering remains the original NativeReadBuffer, with one handoff in flight.
    """
    def __init__(self, http, *, streams=None, native_sources=(), native_factories=None, pons_profiles=None, seconds=1800, workers=4,
                 attempt_seconds=30):
        from .pons_native_profile import ParentPonsProfiles
        _require(pons_profiles is None or type(pons_profiles) is ParentPonsProfiles
            and pons_profiles._http is http,'pons_profile_parent_owner')
        self.pons_profiles=pons_profiles
        _require(type(http) is ParentHTTP and type(seconds) in (int, float)
            and 0 < seconds <= 1800 and type(workers) is int and 1 <= workers <= 8
            and workers <= http._workers
            and type(attempt_seconds) in (int, float) and 0 < attempt_seconds <= 30,
            'parent_channel_configuration')
        configured = {} if streams is None else dict(streams)
        limits=http.budget.limits
        self.max_streams=min(32,limits['native_inflight_bytes']//(4*MAX_FRAME))
        _require(self.max_streams>=1 and len(configured) <= self.max_streams
            and all(type(k) is str and k in http.sources and type(v) is ParentNativeStream
                and v.budget is http.budget for k, v in configured.items()), 'parent_channel_streams')
        self.http,self.streams,self.stream_aliases=http,{},{}
        self._initial_streams=[]
        for alias,stream in configured.items():
            handle=secrets.token_urlsafe(32)
            self.streams[handle]=stream;self.stream_aliases[handle]=alias
            self._initial_streams.append(NativeSourceBinding(http.sources[alias],stream.transport).receipt(handle))
        bound = tuple(native_sources)
        _require(len(bound) <= 32 and all(type(s) is NativeSourceBinding
            and s.source.alias.name in http.sources and s.source == http.sources[s.source.alias.name]
            for s in bound) and len({s.source.alias.name for s in bound}) == len(bound),
            'parent_native_sources')
        self.native_sources = {s.source.alias.name: s for s in bound}
        _require(native_factories is None or type(native_factories) is NativeFactoryMap,
            'parent_native_factory_type')
        if native_factories is not None:native_factories.require_owner(http,bound)
        self._native_factories=native_factories
        self._native_busy = set()
        self._opening=set()
        self.max_operations=2*self.max_streams+workers+8
        self.session = secrets.token_urlsafe(32)
        self.deadline = asyncio.get_running_loop().time() + seconds
        self.attempt_seconds, self.workers = attempt_seconds, workers
        self.contents = {}
        self.stream_contents = {}
        self._previous = None
        self._next = 1
        self.closed = False
        self.stopped = asyncio.Event()
        self._closing = None
        self._upload = None
        self._head_lifecycle = None
        self._loop = asyncio.get_running_loop()

    def start_head_measurement(self, approval, image, *, refresh=True):
        """Explicit already-fenced parent call; never selected by child data."""
        _require(asyncio.get_running_loop() is self._loop, 'parent_head_refresh_owner')
        from .parent_head_lifecycle import ParentHeadLifecycle
        return ParentHeadLifecycle(self, approval=approval, image=image, refresh=refresh)

    def head_measurement(self):
        return self._head_lifecycle.snapshot() if self._head_lifecycle is not None else None

    def hello(self):
        return dict(session=self.session, protocol='native-parent-transport-v3',
            sources=[s.receipt() for s in self.http.sources.values()],
            streams=self._initial_streams+[s.receipt() for s in self.native_sources.values()],
            maximum_streams=self.max_streams,
            chunk_bytes=CHUNK, response_bytes=MAX_FRAME,
            upload_bytes=UPLOAD_MAX, upload_chunk_bytes=UPLOAD_CHUNK, upload_slots=1,
            maximum_messages=MAX_MESSAGES, replay='most_recent_only',
            acknowledgements='transport_memory_only; native owners retain source FULL/ACK')

    def _token(self, message):
        token = message['token']
        _require(type(token) is str and token in self.contents, 'parent_foreign_token')
        return token, self.contents[token]

    async def dispatch(self, frame):
        try:
            message = decode_request(frame)
            seq = message.get('seq')
            _require(type(seq) is int and 1 <= seq <= MAX_MESSAGES
                and message.get('session') == self.session, 'parent_sequence')
            identity = hashlib.sha256(_json(message)).digest()
            if self._previous is not None and seq == self._previous[0]:
                _require(identity == self._previous[1], 'parent_altered_replay')
                return self._previous[2]
            _require(not self.closed and asyncio.get_running_loop().time() < self.deadline
                and seq == self._next, 'parent_sequence')
            verb = message.get('verb')
            if verb == 'http_begin':
                _require(set(message) == {'session', 'seq', 'verb', 'alias', 'calls', 'batch'},
                         'parent_begin_shape')
                reply = self._begin(message)
            elif verb in ('poll', 'read', 'ack', 'cancel'):
                keys = {'session', 'seq', 'verb', 'token'}
                if verb in ('read', 'ack'):
                    keys.add('offset')
                if verb == 'ack':
                    keys.add('sha256')
                _require(set(message) == keys, 'parent_content_shape')
                token, content = self._token(message)
                reply = dict(token=token, status=content.status)
                if content.boundary is not None:
                    reply['boundary'] = content.boundary
                if content.stream_id is not None:
                    reply['stream']=content.stream_id
                if verb == 'read':
                    reply.update(self._read(content, message['offset']))
                elif verb == 'ack':
                    reply.update(self._ack(content, message['offset'], message['sha256']))
                    if content.status == 'consumed':
                        self.contents.pop(token)
                        self.stream_contents.pop(token, None)
                elif verb == 'cancel':
                    if content.task is not None and not content.task.done():
                        content.task.cancel()
                    content.body, content.pending = None, None
                    content.status = 'canceled'
                    reply['status'] = content.status
                    # Join first, so cancellation cannot create unmetered I/O
                    # or exceed the worker bound under a replacement token.
                    if content.task is not None:
                        await asyncio.gather(content.task, return_exceptions=True)
                    if content.stream is not None:
                        await content.stream.aclose()
                    if (self._upload is not None and self._upload.committed
                            and self._upload.stream_id==content.stream_id):
                        self._discard_upload(self._upload)
                        self._native_busy.discard(content.stream_id)
                    self.contents.pop(token)
                    self.stream_contents.pop(token, None)
                if content.body is not None:
                    reply['bytes'] = len(content.body)
                if verb == 'poll' and content.kind == 'control' and content.status != 'running':
                    self.contents.pop(token)
            elif verb=='pons_profile':
                _require(set(message)=={'session','seq','verb','alias'},'parent_pons_profile_shape')
                from .pons_native_profile import parent_profile_response
                reply=dict(profile=parent_profile_response(self.pons_profiles,self.http,self.session,message['alias']))
            elif verb in ('demand', 'activity'):
                keys = {'session', 'seq', 'verb', 'alias'}
                if verb == 'demand':
                    keys.add('methods')
                _require(set(message) == keys and message['alias'] in self.http.sources,
                         'parent_observation_shape')
                if verb == 'demand':
                    methods = message['methods']
                    _require(type(methods) is list and 1 <= len(methods) <= 200
                        and all(type(m) is str for m in methods), 'parent_demand_shape')
                    await self.http.demand(message['alias'], methods)
                    reply = dict(status='demand_committed')
                else:
                    reply = dict(activity_marker=await self.http.activity_marker(message['alias']))
            elif verb in ('native_upload_begin','native_upload_chunk','native_upload_commit','native_upload_cancel'):
                reply=self._upload_message(message)
            elif verb in ('native_open', 'native_close', 'native_write'):
                keys = {'session', 'seq', 'verb', 'alias' if verb=='native_open' else 'stream'}
                if verb == 'native_write':
                    keys.add('body_b64')
                _require(set(message) == keys and len(self.contents) < self.max_operations,
                    'parent_native_control_shape')
                if verb == 'native_open':
                    alias=message['alias']
                    _require(type(alias) is str and alias in self.native_sources
                        and len(self.streams)+len(self._opening)<1024
                        and sum(not s.cleanup_verified for s in self.streams.values())+len(self._opening)<self.max_streams,
                        'parent_native_capacity')
                    handle=secrets.token_urlsafe(32)
                    self._opening.add(handle)
                else:
                    handle=message['stream']
                    _require(type(handle) is str and handle in self.streams
                        and handle not in self._native_busy
                        and (verb=='native_close' or not self.streams[handle].closed),
                             'parent_native_control')
                    alias=self.stream_aliases[handle]
                body = None
                if verb == 'native_write':
                    _require(self.streams[handle].transport=='solana_websocket',
                        'parent_native_write_transport')
                    _require(type(message['body_b64']) is str, 'parent_native_write_shape')
                    try:
                        body = base64.b64decode(message['body_b64'], validate=True)
                    except ValueError:
                        raise BridgeRejected('parent_native_write_encoding') from None
                token = secrets.token_urlsafe(32)
                content = _Content(None, 'control', alias=alias,
                    stream=self.streams.get(handle) if verb != 'native_open' else None,
                    stream_id=handle)
                self.contents[token] = content
                self._native_busy.add(handle)
                content.task = asyncio.create_task(self._native_control(content, alias, verb, body))
                reply = dict(token=token, status='accepted')
            elif verb == 'native_read':
                handle=message.get('stream')
                _require(set(message) == {'session', 'seq', 'verb', 'stream'}
                    and type(handle) is str and handle in self.streams, 'parent_native_read_shape')
                alias=self.stream_aliases[handle]
                _require(not self.streams[handle].closed and not any(
                    c.kind == 'native' and c.stream_id == handle
                    and c.status in ('running', 'delivered') for t, c in self.contents.items()),
                    'parent_native_backpressure')
                _require(len(self.contents) < self.max_operations, 'parent_attempt_count')
                token = secrets.token_urlsafe(32)
                content = _Content(None, 'native', alias=alias, stream=self.streams[handle],stream_id=handle)
                self.contents[token] = content
                self.stream_contents[token] = handle
                content.task = asyncio.create_task(self._native(content, alias))
                reply = dict(token=token, status='accepted')
            elif verb == 'close':
                _require(set(message) == {'session', 'seq', 'verb'}, 'parent_close_shape')
                self.closed = True
                reply = dict(status='closed')
            else:
                raise BridgeRejected('parent_unknown_verb')
            result = encode_frame(dict(session=self.session, seq=seq, **reply))
            self._previous = seq, identity, result
            self._next += 1
            return result
        except BaseException:
            # dispatch may be canceled after accepted demand/accounting. The
            # caller must close, never retry it under a replacement sequence.
            self.closed = True
            self.stopped.set()
            self._discard_upload(self._upload)
            raise

    def _discard_upload(self,upload):
        if upload is None:return
        upload.data=None
        if upload.timer is not None and upload.timer is not asyncio.current_task():
            upload.timer.cancel()
        if not upload.committed:self._native_busy.discard(upload.stream_id)
        if self._upload is upload:self._upload=None

    async def _expire_upload(self,upload):
        await asyncio.sleep(max(0,upload.deadline-asyncio.get_running_loop().time()))
        if self._upload is upload and not upload.committed:
            self._discard_upload(upload)
            self.closed=True
            self.stopped.set()

    def _upload_message(self,message):
        verb=message['verb']
        keys={'session','seq','verb','stream'}
        keys.update({'bytes','sha256'} if verb=='native_upload_begin' else {'upload'})
        if verb=='native_upload_chunk':keys.update({'offset','body_b64'})
        handle=message.get('stream')
        _require(set(message)==keys and type(handle) is str and handle in self.streams,
            'parent_upload_shape')
        stream=self.streams[handle]
        _require(not stream.closed and stream.transport=='yellowstone','parent_upload_stream')
        now=asyncio.get_running_loop().time()
        if verb=='native_upload_begin':
            size,digest=message['bytes'],message['sha256']
            _require(self._upload is None and handle not in self._native_busy
                and len(self.contents)<self.max_operations
                and type(size) is int and 0<=size<=UPLOAD_MAX
                and type(digest) is str and re.fullmatch('[0-9a-f]{64}',digest) is not None,
                'parent_upload_capacity')
            self.http.budget.admission()
            # Independent fixed memory bound; never a new provider allowance,
            # native stream reservation or accounting receipt. One slot remains
            # owned through the joined SDK write, including its transient copy.
            upload=_Upload(secrets.token_urlsafe(32),handle,size,digest,
                min(self.deadline,now+8),bytearray(size),hashlib.sha256())
            self._upload=upload
            self._native_busy.add(handle)
            upload.timer=asyncio.create_task(self._expire_upload(upload))
            return dict(upload=upload.token,stream=handle,status='uploading',next_offset=0)
        upload=self._upload
        _require(upload is not None and not upload.committed
            and message['upload']==upload.token and handle==upload.stream_id
            and now<upload.deadline,'parent_upload_identity')
        if verb=='native_upload_cancel':
            self._discard_upload(upload)
            return dict(upload=upload.token,stream=handle,status='canceled')
        if verb=='native_upload_chunk':
            offset,encoded=message['offset'],message['body_b64']
            _require(type(offset) is int and offset==upload.offset and type(encoded) is str
                and 0<len(encoded)<=4*((UPLOAD_CHUNK+2)//3),'parent_upload_chunk')
            try:body=base64.b64decode(encoded,validate=True)
            except ValueError:raise BridgeRejected('parent_upload_encoding') from None
            _require(0<len(body)<=UPLOAD_CHUNK and offset+len(body)<=upload.size
                and base64.b64encode(body).decode()==encoded,'parent_upload_chunk')
            upload.data[offset:offset+len(body)]=body
            upload.digest.update(body)
            upload.offset+=len(body)
            return dict(upload=upload.token,stream=handle,status='uploading',next_offset=upload.offset)
        _require(upload.offset==upload.size and upload.digest.hexdigest()==upload.sha256,
            'parent_upload_digest')
        body=bytes(upload.data)
        upload.data=None
        upload.committed=True
        upload.timer.cancel()
        token=secrets.token_urlsafe(32)
        content=_Content(None,'control',alias=self.stream_aliases[handle],stream=stream,stream_id=handle)
        self.contents[token]=content
        content.task=asyncio.create_task(self._native_control(content,content.alias,'native_write',body,upload=upload))
        return dict(token=token,status='accepted')

    def _begin(self, message):
        _require(type(message['alias']) is str and message['alias'] in self.http.sources,
                 'parent_alias')
        source = self.http.sources[message['alias']]
        batch, calls = message['batch'], message['calls']
        _require(type(batch) is bool and type(calls) is list and 1 <= len(calls) <= 200
            and (batch or len(calls) == 1), 'parent_batch')
        frozen = []
        for call in calls:
            _require(type(call) is dict and set(call) == {'method', 'params'}
                and type(call['method']) is str and call['method'] in source.alias.methods
                and type(call['params']) is list, 'parent_call')
            _params(call['params'])
            frozen.append(ReadCall(call['method'], _json(call['params'])))
        # Reserve memory for every accepted HTTP maximum response. No eviction,
        # extra queue or unbounded spool can hide backpressure from the child.
        outstanding = sum(c.kind == 'http' and c.status in ('running', 'delivered')
                          for c in self.contents.values())
        _require(len(self.contents) < self.max_operations and outstanding < self.workers, 'parent_attempt_capacity')
        token = secrets.token_urlsafe(32)
        attempt_seconds=min(self.attempt_seconds,8) if source.read_class!='native' else self.attempt_seconds
        attempt = ParentAttempt(self.session, token, source.alias, tuple(frozen), batch,
            min(self.deadline, asyncio.get_running_loop().time()+attempt_seconds))
        content = _Content(None, 'http', attempt=attempt)
        self.contents[token] = content
        content.task = asyncio.create_task(self._http(content))
        return dict(token=token, status='accepted')

    async def _http(self, content):
        delivered = None
        try:
            delivered = await self.http.execute(content.attempt)
            _require(type(delivered) is Delivered and delivered.eof
                and type(delivered.body) is bytes and len(delivered.body) <= MAX_FRAME,
                'parent_delivery')
            content.body, content.status = delivered.body, 'delivered'
        except asyncio.CancelledError:
            content.status = 'canceled'
        except BaseException as error:
            content.status = 'failed'
            from meme_machine.runtime.robinhood.provider_authority import failure_class
            content.boundary = failure_class(error)
        finally:
            try:
                await self.http.release(content.attempt,
                    uncertain=not(type(delivered) is Delivered and delivered.eof))
            except BaseException:
                content.body, content.status = None, 'accounting_failed'
                self.closed = True
                self.stopped.set()
            if self.closed:
                content.body = None

    async def _native(self, content, alias):
        try:
            value = await content.stream.read()
            if value is None:
                content.status = 'eof'
            else:
                content.sequence, content.body = value
                content.status = 'delivered'
        except asyncio.CancelledError:
            content.status = 'canceled'
        except BaseException as error:
            content.boundary = _native_boundary(error)
            if content.boundary is None:
                content.status = 'failed'
                self.closed = True
                self.stopped.set()
            else:
                try:
                    await content.stream.aclose()
                except BaseException as cleanup_error:
                    if isinstance(cleanup_error,asyncio.CancelledError) and content.stream.cleanup_verified:
                        content.status='canceled'
                    else:
                        content.status = 'accounting_failed'
                        self.closed = True
                        self.stopped.set()
                else:
                    # A failed read becomes observable only after its original
                    # cleanup is joined. Early publication lets a child cancel
                    # this very cleanup as if the operation were already done.
                    content.status = 'failed'

    async def _native_control(self, content, alias, verb, body, *, upload=None):
        try:
            async with asyncio.timeout_at(min(self.deadline,upload.deadline if upload is not None
                    else asyncio.get_running_loop().time()+8)):
                if verb == 'native_open':
                    source=self.native_sources[alias]
                    factory=(None if self._native_factories is None else self._native_factories.factory(source))
                    content.stream=await source.open(self.http.budget,factory=factory)
                    self.streams[content.stream_id]=content.stream
                    self.stream_aliases[content.stream_id]=alias
                    content.status = 'opened'
                elif verb == 'native_close':
                    await content.stream.aclose()
                    for other in self.contents.values():
                        if other is not content and other.stream is content.stream and other.kind=='native':
                            other.body=None;other.pending=None
                            if other.task is not None and not other.task.done():other.task.cancel()
                            other.status='canceled'
                    content.status = 'closed'
                else:
                    await content.stream.write(body,deadline=upload.deadline if upload is not None else None)
                    content.status = 'written'
        except asyncio.CancelledError:
            if upload is not None:await self._failed_upload_cleanup(content)
            content.status = 'canceled'
        except BaseException as error:
            content.boundary = _native_boundary(error)
            if upload is not None:await self._failed_upload_cleanup(content)
            content.status = 'failed'
            if content.boundary is None:
                self.closed = True
                self.stopped.set()
        finally:
            if upload is not None:self._discard_upload(upload)
            self._native_busy.discard(content.stream_id)
            self._opening.discard(content.stream_id)

    async def _failed_upload_cleanup(self,content):
        # Failed/ambiguous SDK writes never publish terminal status before the
        # original stream's unread uncertainty and physical cleanup are joined.
        try:await content.stream.aclose()
        except BaseException:
            content.status='accounting_failed'
            self.closed=True
            self.stopped.set()
            raise

    def _read(self, content, offset):
        _require(type(offset) is int and offset == content.offset
            and content.status == 'delivered' and content.body is not None,
            'parent_chunk_offset')
        if content.pending is None:
            body = content.body[offset:offset+CHUNK]
            content.pending = (offset, len(body), hashlib.sha256(body).hexdigest())
        start, length, digest = content.pending
        return dict(offset=start, body_b64=base64.b64encode(content.body[start:start+length]).decode(),
            sha256=digest, final=start+length == len(content.body))

    def _ack(self, content, offset, digest):
        _require(type(offset) is int and type(digest) is str and content.pending is not None
            and offset == content.pending[0] and digest == content.pending[2], 'parent_chunk_ack')
        content.offset += content.pending[1]
        content.pending = None
        if content.offset == len(content.body):
            if content.kind == 'native':
                # This only releases the parent's paid byte buffer. It has no
                # access to the child's canonical owner or its consumer ACKs.
                content.stream.acknowledge_handoff(content.sequence)
            content.body, content.status = None, 'consumed'
        return dict(status=content.status, next_offset=content.offset)

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
                    raise ParentTransportFailure('parent_channel_cleanup_canceled') from None
                canceled = True
        if canceled:
            raise asyncio.CancelledError

    async def _close(self):
        head_owner = self._head_lifecycle
        # Same original native drain window, never a second grace interval.
        drain_deadline = asyncio.get_running_loop().time() + 65 if head_owner is not None else None
        if head_owner is not None: head_owner.stop()
        self.closed = True
        self.stopped.set()
        self._discard_upload(self._upload)
        tasks = [c.task for c in self.contents.values() if c.task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        # Close native transport ownership while canceled accounting is joined.
        joined = asyncio.gather(*(s.aclose() for s in self.streams.values()),
            *tasks, *([head_owner.join(deadline=drain_deadline)] if head_owner is not None else []),
            return_exceptions=True)
        if head_owner is not None:
            await self._head_bounded_join(joined, drain_deadline)
            results = joined.result()
            from .isolated_native_lifetime import NativeOwnerDrainFailure
            fatal = next((r for r in results if isinstance(r, NativeOwnerDrainFailure)), None)
            if fatal is not None: raise fatal
        else:
            results = await joined
        try:
            if head_owner is not None:
                http_close = asyncio.create_task(self.http.aclose())
                await self._head_bounded_join(http_close, drain_deadline)
                http_close.result()
            else:
                await self.http.aclose()
        finally:
            self._native_busy.clear()
            self._opening.clear()
            for content in self.contents.values():
                content.body, content.pending = None, None
        if any(isinstance(r, BaseException) for r in results):
            raise ParentTransportFailure('parent_channel_cleanup_failed')

    async def _head_bounded_join(self, task, deadline):
        done, _ = await asyncio.wait((task,), timeout=max(0, deadline - self._loop.time()))
        if done: return
        from .isolated_native_lifetime import NativeOwnerDrainFailure
        failure = NativeOwnerDrainFailure(dict(status='BLOCKED',
            failure_code='parent_head_shutdown_incomplete', financial_authority=False,
            normal_readiness=False, all_workers_joined=False))
        failure.retain(self, self.http, self._head_lifecycle, task)
        raise failure


def _native_boundary(error):
    import grpc
    from websockets.exceptions import ConnectionClosed
    from meme_machine.lanes.pons import BoundaryError
    if isinstance(error,OSError) or (isinstance(error,BoundaryError)
            and str(error) in ('sequencer_feed_connection_closed','sequencer_feed_not_connected',
                              'sequencer_feed_reserved_bits')):
        return 'candidate_native_unavailable'
    if isinstance(error, grpc.RpcError):
        try:
            return {
                grpc.StatusCode.UNAVAILABLE: 'candidate_native_unavailable',
                grpc.StatusCode.INTERNAL: 'candidate_native_internal',
                grpc.StatusCode.DEADLINE_EXCEEDED: 'candidate_native_deadline_exceeded',
                grpc.StatusCode.CANCELLED: 'candidate_native_cancelled',
                grpc.StatusCode.RESOURCE_EXHAUSTED: 'candidate_native_resource_exhausted',
            }.get(error.code())
        except Exception:
            return None
    if isinstance(error, ConnectionClosed):
        return 'candidate_native_unavailable'
    if isinstance(error, TimeoutError):
        return 'candidate_native_deadline_exceeded'
    return None


async def serve_connected(reader, writer, channel, *, child_exited=None):
    """Serve an inherited private connected channel; close on EOF/death/deadline.

    Source/OS authentication and socketpair descriptor validation are required
    before constructing this function's inputs. No process is spawned here.
    """
    async def exchange():
        writer.write(encode_frame(channel.hello()))
        await writer.drain()
        while not channel.closed:
            frame = await read_request_frame(reader)
            writer.write(await channel.dispatch(frame))
            await writer.drain()

    work = asyncio.create_task(exchange())
    death = asyncio.create_task(child_exited.wait()) if child_exited is not None else None
    stopped = asyncio.create_task(channel.stopped.wait())
    try:
        async with asyncio.timeout_at(channel.deadline):
            done, _ = await asyncio.wait((work, stopped, *([death] if death is not None else [])),
                return_when=asyncio.FIRST_COMPLETED)
            if work in done:
                await work
    except (asyncio.IncompleteReadError, ConnectionError, BridgeRejected, TimeoutError):
        pass
    finally:
        work.cancel()
        stopped.cancel()
        if death is not None:
            death.cancel()
        await asyncio.gather(work, stopped, *([death] if death is not None else []), return_exceptions=True)
        try:
            await channel.aclose()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
