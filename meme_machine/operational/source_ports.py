"""Secret-free adapters for the original native source's transport interfaces.

Every stream is a real parent-issued instance with its original reservation.
These adapters do not decode economics, earn source FULL/ACK, resolve URLs or
grant historical-recovery authority. Those duties stay with the native source.
"""
import asyncio
from dataclasses import dataclass

from .child_transport import ChildChannel, ChildParentFailure, ChildTransportFailure


@dataclass(frozen=True)
class SourceIdentity:
    identity: str
    provider: str = 'alchemy_solana_mainnet'
    network: str = 'solana-mainnet'

    def public(self, value):
        from meme_machine.solana_provider_config import public_value
        return public_value(value)


def native_reference(channel, transport):
    if type(channel) is not ChildChannel or channel.closed:
        raise ChildTransportFailure('source_parent_channel_required')
    rows=[row for row in channel.streams if row['transport']==transport
        and row['stream'] is None]
    if len(rows)!=1:
        raise ChildTransportFailure('source_native_capability_required')
    source=channel.sources[rows[0]['alias']]
    if source.family!='solana' or source.read_class!='native':
        raise ChildTransportFailure('source_native_identity')
    return source


def _grpc_failure(error):
    import grpc
    codes={
        'candidate_native_unavailable':grpc.StatusCode.UNAVAILABLE,
        'candidate_native_internal':grpc.StatusCode.INTERNAL,
        'candidate_native_deadline_exceeded':grpc.StatusCode.DEADLINE_EXCEEDED,
        'candidate_native_cancelled':grpc.StatusCode.CANCELLED,
        'candidate_native_resource_exhausted':grpc.StatusCode.RESOURCE_EXHAUSTED,
    }
    code=codes.get(str(error))
    if code is None:
        raise error
    # Only fixed classifications cross this adapter. No provider details/URL.
    return grpc.aio.AioRpcError(code,(),(),str(error))


class _GrpcCall:
    def __init__(self, channel, serializer, deserializer):
        self.owner=channel
        self.serializer=serializer
        self.deserializer=deserializer
        self.cancelled=False
        self.opening=asyncio.create_task(asyncio.to_thread(
            channel.channel.native_open,channel.source))
        self.closing=None

    async def _stream(self):
        try:
            stream=await asyncio.shield(self.opening)
        except ChildParentFailure as error:
            raise _grpc_failure(error) from None
        if self.cancelled:
            await stream.close_async()
            raise asyncio.CancelledError()
        return stream

    async def write(self, request):
        stream=await self._stream()
        body=self.serializer(request)
        if type(body) is not bytes:
            raise ChildTransportFailure('source_grpc_serialization')
        try:
            await stream.write_async(body)
        except ChildParentFailure as error:
            raise _grpc_failure(error) from None

    async def read(self):
        import grpc
        stream=await self._stream()
        try:
            body=await stream.read_async()
        except ChildParentFailure as error:
            raise _grpc_failure(error) from None
        return grpc.aio.EOF if body is None else self.deserializer(body)

    async def _close(self):
        try:
            stream=await asyncio.shield(self.opening)
        except Exception:
            # Failed parent opens own their original uncertain cleanup. There
            # is no issued child stream to close or fictional successful ACK.
            return
        await stream.close_async()

    def cancel(self):
        prior=self.cancelled
        self.cancelled=True
        if self.closing is None:
            self.closing=asyncio.create_task(self._close())
        return not prior

    async def aclose(self):
        self.cancel()
        await asyncio.shield(self.closing)


class NativeGrpcChannel:
    """The fixed original geyser stream method over parent-owned native I/O."""
    def __init__(self, channel):
        self.channel=channel
        self.source=native_reference(channel,'yellowstone')
        self.calls=[]
        self.closed=False

    async def __aenter__(self):
        if self.closed:
            raise ChildTransportFailure('source_grpc_channel_closed')
        return self

    async def __aexit__(self, kind, value, traceback):
        await self.close()

    def stream_stream(self, method, *, request_serializer, response_deserializer):
        if (self.closed or method!='/geyser.Geyser/Subscribe'
                or not callable(request_serializer) or not callable(response_deserializer)):
            raise ChildTransportFailure('source_grpc_method')
        def subscribe(*, metadata=()):
            if self.closed or metadata not in ((),None):
                raise ChildTransportFailure('source_grpc_metadata_forbidden')
            call=_GrpcCall(self,request_serializer,response_deserializer)
            # Closed native sessions need no lifelong parser/call retention.
            retained=[]
            for old in self.calls:
                if old.closing is not None and old.closing.done():
                    old.closing.result() # Never forget an unresolved cleanup.
                else:
                    retained.append(old)
            self.calls[:]=retained
            self.calls.append(call)
            return call
        return subscribe

    async def close(self):
        self.closed=True
        results=await asyncio.gather(*(call.aclose() for call in self.calls),return_exceptions=True)
        self.calls.clear()
        for result in results:
            if isinstance(result,BaseException):
                raise result


class NativeWebSocket:
    """Original logs websocket payloads, without an ambient child URL/socket."""
    def __init__(self, channel):
        self.channel=channel
        self.source=native_reference(channel,'solana_websocket')
        self.stream=None
        self.opening=None
        self.closed=False

    async def __aenter__(self):
        if self.closed or self.opening is not None:
            raise ChildTransportFailure('source_websocket_lifecycle')
        self.opening=asyncio.create_task(asyncio.to_thread(self.channel.native_open,self.source))
        try:
            self.stream=await asyncio.shield(self.opening)
            return self
        except BaseException:
            await self.close()
            raise

    async def __aexit__(self, kind, value, traceback):
        await self.close()

    async def send(self, body):
        if self.closed or self.stream is None or type(body) not in (str,bytes):
            raise ChildTransportFailure('source_websocket_write')
        await self.stream.write_async(body.encode('utf-8') if type(body) is str else body)

    async def recv(self):
        if self.closed or self.stream is None:
            raise ChildTransportFailure('source_websocket_lifecycle')
        try:
            body=await self.stream.read_async()
        except ChildParentFailure as error:
            if str(error) not in ('candidate_native_unavailable','candidate_native_cancelled',
                    'candidate_native_deadline_exceeded'):
                raise
            raise OSError('source_websocket_transport_lost') from None
        if body is None:
            from websockets.exceptions import ConnectionClosedOK
            from websockets.frames import Close
            raise ConnectionClosedOK(Close(1000,''),Close(1000,''),True)
        # Keep raw frame bytes. The original native logs decoder owns UTF-8,
        # JSON, source handlers, economic joins and their durable disposition.
        return body

    async def close(self):
        self.closed=True
        if self.opening is None:
            return
        try:
            stream=await asyncio.shield(self.opening)
        except Exception:
            return
        await stream.close_async()
