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
import secrets

from .bounded_provider import MAX_FRAME
from .parent_transport import ParentHTTP, ParentNativeStream, ParentTransportFailure, NativeSourceBinding
from .transport_bridge import (
    BridgeRejected, ParentAttempt, ReadCall, Delivered, _json, _params, _require,
    decode_request, encode_frame, read_request_frame,
)

CHUNK = 64 * 1024
MAX_MESSAGES = 1_000_000


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


class ParentChannel:
    """One bounded child capability, preserving concurrent parent I/O.

    Exact most-recent-message replay returns its original response. Older or
    altered sequences close the channel; no replay creates another acquisition.
    Content is separate from the bounded control replay cache. A whole HTTP/native
    response may reach MAX_FRAME, delivered in acknowledged 64-KiB chunks. Native
    buffering remains the original NativeReadBuffer, with one handoff in flight.
    """
    def __init__(self, http, *, streams=None, native_sources=(), seconds=1800, workers=4,
                 attempt_seconds=30):
        _require(type(http) is ParentHTTP and type(seconds) in (int, float)
            and 0 < seconds <= 1800 and type(workers) is int and 1 <= workers <= 8
            and workers <= http._workers
            and type(attempt_seconds) in (int, float) and 0 < attempt_seconds <= 30,
            'parent_channel_configuration')
        configured = {} if streams is None else dict(streams)
        _require(len(configured) <= 8 and all(type(k) is str and k in http.sources
            and type(v) is ParentNativeStream for k, v in configured.items()), 'parent_channel_streams')
        self.http, self.streams = http, configured
        bound = tuple(native_sources)
        _require(len(bound) <= 8 and all(type(s) is NativeSourceBinding
            and s.source.alias.name in http.sources and s.source == http.sources[s.source.alias.name]
            for s in bound) and len({s.source.alias.name for s in bound}) == len(bound),
            'parent_native_sources')
        self.native_sources = {s.source.alias.name: s for s in bound}
        self._native_busy = set()
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

    def hello(self):
        return dict(session=self.session, protocol='native-parent-transport-v1',
            sources=[s.receipt() for s in self.http.sources.values()],
            streams=sorted(set(self.streams)|set(self.native_sources)),
            chunk_bytes=CHUNK, response_bytes=MAX_FRAME,
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
                    self.contents.pop(token)
                    self.stream_contents.pop(token, None)
                if content.body is not None:
                    reply['bytes'] = len(content.body)
                if verb == 'poll' and content.kind == 'control' and content.status != 'running':
                    self.contents.pop(token)
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
            elif verb in ('native_open', 'native_close', 'native_write'):
                keys = {'session', 'seq', 'verb', 'alias'}
                if verb == 'native_write':
                    keys.add('body_b64')
                alias = message.get('alias')
                _require(set(message) == keys and type(alias) is str
                    and alias not in self._native_busy and len(self.contents) < 64,
                    'parent_native_control_shape')
                if verb == 'native_open':
                    _require(alias in self.native_sources and
                        (alias not in self.streams or self.streams[alias].cleanup_verified),
                        'parent_native_open')
                else:
                    _require(alias in self.streams and not self.streams[alias].closed,
                             'parent_native_control')
                body = None
                if verb == 'native_write':
                    _require(type(message['body_b64']) is str, 'parent_native_write_shape')
                    try:
                        body = base64.b64decode(message['body_b64'], validate=True)
                    except ValueError:
                        raise BridgeRejected('parent_native_write_encoding') from None
                token = secrets.token_urlsafe(32)
                content = _Content(None, 'control', alias=alias,
                    stream=self.streams.get(alias) if verb != 'native_open' else None)
                self.contents[token] = content
                self._native_busy.add(alias)
                content.task = asyncio.create_task(self._native_control(content, alias, verb, body))
                reply = dict(token=token, status='accepted')
            elif verb == 'native_read':
                _require(set(message) == {'session', 'seq', 'verb', 'alias'}
                    and message['alias'] in self.streams, 'parent_native_read_shape')
                alias = message['alias']
                _require(not self.streams[alias].closed and not any(
                    c.kind == 'native' and self.stream_contents[t] == alias
                    and c.status in ('running', 'delivered') for t, c in self.contents.items()),
                    'parent_native_backpressure')
                _require(len(self.contents) < 64, 'parent_attempt_count')
                token = secrets.token_urlsafe(32)
                content = _Content(None, 'native', alias=alias, stream=self.streams[alias])
                self.contents[token] = content
                self.stream_contents[token] = alias
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
            raise

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
        _require(len(self.contents) < 64 and outstanding < self.workers, 'parent_attempt_capacity')
        token = secrets.token_urlsafe(32)
        attempt = ParentAttempt(self.session, token, source.alias, tuple(frozen), batch,
            min(self.deadline, asyncio.get_running_loop().time()+self.attempt_seconds))
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
            content.status = 'failed'
            content.boundary = _native_boundary(error)
            if content.boundary is None:
                self.closed = True
                self.stopped.set()
            else:
                try:
                    await content.stream.aclose()
                except BaseException:
                    content.status = 'accounting_failed'
                    self.closed = True
                    self.stopped.set()

    async def _native_control(self, content, alias, verb, body):
        try:
            async with asyncio.timeout_at(min(self.deadline, asyncio.get_running_loop().time()+8)):
                if verb == 'native_open':
                    self.streams[alias] = await self.native_sources[alias].open(self.http.budget)
                    content.stream = self.streams[alias]
                    content.status = 'opened'
                elif verb == 'native_close':
                    await content.stream.aclose()
                    content.status = 'closed'
                else:
                    await content.stream.write(body)
                    content.status = 'written'
        except asyncio.CancelledError:
            content.status = 'canceled'
        except BaseException as error:
            content.status = 'failed'
            content.boundary = _native_boundary(error)
            if content.boundary is None:
                self.closed = True
                self.stopped.set()
        finally:
            self._native_busy.discard(alias)

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
        self.closed = True
        self.stopped.set()
        tasks = [c.task for c in self.contents.values() if c.task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        # Close native transport ownership while canceled accounting is joined.
        results = await asyncio.gather(*(s.aclose() for s in self.streams.values()),
                                      *tasks, return_exceptions=True)
        try:
            await self.http.aclose()
        finally:
            for content in self.contents.values():
                content.body, content.pending = None, None
        if any(isinstance(r, BaseException) for r in results):
            raise ParentTransportFailure('parent_channel_cleanup_failed')


def _native_boundary(error):
    import grpc
    from websockets.exceptions import ConnectionClosed
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
