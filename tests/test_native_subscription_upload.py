"""Original subscription byte parity over real private IPC; fake physical I/O."""
import asyncio
import base64
import hashlib
import json
import threading
import unittest
from unittest.mock import patch

from meme_machine.operational.child_transport import ChildChannel,ChildRPCPort,ChildTransportFailure
from meme_machine.operational.parent_channel import UPLOAD_MAX,UPLOAD_CHUNK
from meme_machine.operational.parent_transport import NativeSourceBinding,ParentNativeStream,validate_subscription
from meme_machine.operational.transport_bridge import encode_frame
from tests import test_child_transport as child_fixtures
from tests import test_parent_native_transport as fixtures


class SubscriptionUploadTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.ParentNativeTransportTests.asyncSetUp
    connected=child_fixtures.ChildTransportTests.connected

    async def setup_streams(self,count=1,validator=lambda body:None,raw_type=fixtures._Native):
        raws=[];streams=[]
        async def factory():
            raw=raw_type();raws.append(raw);return raw
        client,parent=await self.connected(native_sources=[NativeSourceBinding(self.sol,'yellowstone')])
        with patch('meme_machine.operational.parent_transport.authenticated_native_factory',return_value=factory):
            natives=[await asyncio.to_thread(client.native_stream,client.sources['pump']) for _ in range(count)]
        streams=[parent.streams[native.stream] for native in natives]
        for stream in streams:stream.validator=validator
        return client,parent,natives,raws,streams

    async def begin(self,client,stream,body,digest=None):
        return await asyncio.to_thread(client.request,'native_upload_begin',stream=stream.stream,
            bytes=len(body),sha256=digest or hashlib.sha256(body).hexdigest())

    async def chunk(self,client,stream,upload,body,offset=0):
        return await asyncio.to_thread(client.request,'native_upload_chunk',stream=stream.stream,
            upload=upload,offset=offset,body_b64=base64.b64encode(body).decode())

    async def test_three_mib_real_subscription_reaches_sdk_once_only_after_full_digest(self):
        from meme_machine.yellowstone import geyser_pb2 as pb
        from meme_machine.solana_selective_history import PROGRAMS
        request=pb.SubscribeRequest()
        request.accounts['pump'].owner.append(PROGRAMS['pump'])
        request.accounts['pump'].account.extend([PROGRAMS['pump']]*71000)
        body=request.SerializeToString()
        self.assertGreater(len(body),3*1024*1024)
        self.assertLess(len(body),UPLOAD_MAX)
        client,parent,natives,raws,_=await self.setup_streams(
            validator=lambda body:validate_subscription('yellowstone',body))
        before=self.budget.snapshot()
        chunks=[]
        original=parent._upload_message
        def observe(message):
            if message['verb']!='native_upload_cancel':self.assertEqual(raws[0].writes,[])
            if message['verb']=='native_upload_chunk':
                chunks.append(len(base64.b64decode(message['body_b64'])))
                self.assertLess(len(json.dumps(message).encode()),65536)
            return original(message)
        with patch.object(parent,'_upload_message',side_effect=observe):
            await natives[0].write_async(body)
        self.assertTrue(raws[0].writes==[body],'exact subscription bytes reach SDK once')
        self.assertGreater(len(chunks),1)
        self.assertTrue(all(0<size<=UPLOAD_CHUNK for size in chunks))
        self.assertIsNone(parent._upload)
        after=self.budget.snapshot()
        for field in ('native_reserved','native_bytes','native_opens','http_attempts','rpc_elements'):
            self.assertEqual(before[field],after[field])

    async def test_original_exact_four_mib_send_and_oversize_rejected_before_purchase(self):
        client,parent,natives,raws,_=await self.setup_streams()
        await natives[0].write_async(b'x'*UPLOAD_MAX)
        self.assertEqual(len(raws[0].writes[0]),UPLOAD_MAX)
        with self.assertRaisesRegex(ChildTransportFailure,'child_native_write'):
            await natives[0].write_async(b'x'*(UPLOAD_MAX+1))
        self.assertEqual(len(raws[0].writes),1)
        self.assertIsNone(parent._upload)

    async def test_partial_upload_keeps_http_and_native_reads_live_then_cancel_discards(self):
        client,parent,natives,raws,streams=await self.setup_streams(2)
        body=b'x'*100000
        begun=await self.begin(client,natives[0],body)
        await self.chunk(client,natives[0],begun['upload'],body[:UPLOAD_CHUNK])
        self.assertEqual(parent._upload.offset,UPLOAD_CHUNK)
        self.assertEqual(raws[0].writes,[])
        raws[1].values.put_nowait(b'economic-frame')
        rpc=ChildRPCPort(client,'pump')
        read,http=await asyncio.gather(natives[1].read_async(),asyncio.to_thread(rpc.envelope,
            dict(jsonrpc='2.0',id=1,method='getSlot',params=[])))
        self.assertEqual(read,b'economic-frame')
        self.assertEqual(http['result'],'0x123')
        response=await asyncio.to_thread(client.request,'native_upload_cancel',
            stream=natives[0].stream,upload=begun['upload'])
        self.assertEqual(response['status'],'canceled')
        self.assertIsNone(parent._upload)
        self.assertFalse(streams[0].closed)
        self.assertEqual(raws[0].writes,[])

    async def test_hash_offset_foreign_scope_and_second_slot_fail_closed_without_write(self):
        for fault in ('digest','offset','stream','upload','slot','oversize','encoding','noncanonical'):
            with self.subTest(fault=fault):
                client,parent,natives,raws,streams=await self.setup_streams(2)
                body=b'x'
                begun=await self.begin(client,natives[0],body,digest='0'*64 if fault=='digest' else None)
                with self.assertRaises(ChildTransportFailure):
                    if fault=='slot':await self.begin(client,natives[1],body)
                    elif fault=='digest':
                        await self.chunk(client,natives[0],begun['upload'],body)
                        await asyncio.to_thread(client.request,'native_upload_commit',
                            stream=natives[0].stream,upload=begun['upload'])
                    else:
                        await asyncio.to_thread(client.request,'native_upload_chunk',
                            stream=natives[1 if fault=='stream' else 0].stream,
                            upload='a'*43 if fault=='upload' else begun['upload'],
                            offset=1 if fault=='offset' else 0,
                            body_b64='!!!!' if fault=='encoding' else 'eB==' if fault=='noncanonical' else
                                base64.b64encode(b'x'*(UPLOAD_CHUNK+1) if fault=='oversize' else body).decode())
                async with asyncio.timeout(2):
                    while not all(stream.cleanup_verified for stream in streams):await asyncio.sleep(.001)
                self.assertTrue(parent.closed)
                self.assertIsNone(parent._upload)
                self.assertTrue(all(raw.writes==[] for raw in raws))

    async def test_child_death_discards_partial_without_sdk_write(self):
        client,parent,natives,raws,streams=await self.setup_streams()
        await self.begin(client,natives[0],b'not-finished')
        client.abort()
        async with asyncio.timeout(2):
            while not streams[0].cleanup_verified:await asyncio.sleep(.001)
        self.assertIsNone(parent._upload)
        self.assertEqual(raws[0].writes,[])

    async def test_cancel_immediately_after_commit_before_sdk_task_starts_releases_slot(self):
        client,parent,natives,raws,streams=await self.setup_streams()
        begun=await self.begin(client,natives[0],b'x')
        await self.chunk(client,natives[0],begun['upload'],b'x')
        seq=client.sequence
        accepted=json.loads((await parent.dispatch(encode_frame(dict(session=parent.session,seq=seq,
            verb='native_upload_commit',stream=natives[0].stream,upload=begun['upload']))))[4:])
        await parent.dispatch(encode_frame(dict(session=parent.session,seq=seq+1,
            verb='cancel',token=accepted['token'])))
        self.assertIsNone(parent._upload)
        self.assertNotIn(natives[0].stream,parent._native_busy)
        self.assertEqual(raws[0].writes,[])
        self.assertTrue(streams[0].cleanup_verified)
        client.abort()

    async def test_legacy_small_write_cannot_bypass_yellowstone_upload_integrity(self):
        client,parent,natives,raws,streams=await self.setup_streams()
        with self.assertRaises(ChildTransportFailure):
            await asyncio.to_thread(client.request,'native_write',stream=natives[0].stream,
                body_b64=base64.b64encode(b'x').decode())
        self.assertEqual(raws[0].writes,[])

    async def test_original_validation_and_expired_deadline_precede_any_physical_write(self):
        raw=fixtures._Native();validated=[]
        async def factory():return raw
        stream=await ParentNativeStream.open(self.budget,'yellowstone',factory,validated.append)
        self.addAsyncCleanup(stream.aclose)
        with self.assertRaises(TimeoutError):
            await stream.write(b'complete-but-late',deadline=asyncio.get_running_loop().time()-1)
        self.assertEqual(validated,[b'complete-but-late'])
        self.assertEqual(raw.writes,[])

    async def test_original_websocket_parent_bound_remains_sixty_four_kib(self):
        raw=fixtures._Native()
        async def factory():return raw
        stream=await ParentNativeStream.open(self.budget,'solana_websocket',factory,lambda body:None)
        self.addAsyncCleanup(stream.aclose)
        await stream.write(b'x'*65536)
        with self.assertRaisesRegex(ValueError,'parent_subscription_bound'):
            await stream.write(b'x'*65537)
        self.assertEqual(len(raw.writes),1)
        self.assertEqual(len(raw.writes[0]),65536)

    async def test_upload_deadline_discards_buffer_and_preserves_failed_gate(self):
        client,parent,natives,raws,streams=await self.setup_streams()
        await self.begin(client,natives[0],b'not-finished')
        upload=parent._upload
        upload.timer.cancel()
        upload.deadline=asyncio.get_running_loop().time()
        await parent._expire_upload(upload)
        async with asyncio.timeout(2):
            while not streams[0].cleanup_verified:await asyncio.sleep(.001)
        self.assertIsNone(upload.data)
        self.assertIsNone(parent._upload)
        self.assertEqual(raws[0].writes,[])
        client.abort()

    async def test_exact_recent_commit_replay_does_not_repeat_sdk_write(self):
        client,parent,natives,raws,_=await self.setup_streams()
        begun=await self.begin(client,natives[0],b'x')
        await self.chunk(client,natives[0],begun['upload'],b'x')
        # Replay exactly the accepted commit while the original sequence is
        # still the server's sole replay cache; no replacement logical write.
        original=parent.dispatch
        commits=[]
        async def dispatch(frame):
            result=await original(frame)
            if json.loads(frame[4:])['verb']=='native_upload_commit':
                commits.append(frame)
                self.assertEqual(await original(frame),result)
            return result
        with patch.object(parent,'dispatch',side_effect=dispatch):
            accepted=await asyncio.to_thread(client.request,'native_upload_commit',
                stream=natives[0].stream,upload=begun['upload'])
        await asyncio.to_thread(client._native_control,None,'written',accepted=accepted)
        async with asyncio.timeout(2):
            while parent._upload is not None:await asyncio.sleep(.001)
        self.assertEqual(len(commits),1)
        self.assertEqual(raws[0].writes,[b'x'])

    async def test_sdk_failure_terminal_waits_for_original_uncertainty_cleanup(self):
        class Raw(fixtures._Native):
            def __init__(self):
                super().__init__();self.cleaning=asyncio.Event();self.release=asyncio.Event()
            async def write(self,body):raise OSError('offline-private-provider-error')
            async def aclose(self):
                self.cleaning.set();await self.release.wait();await super().aclose()
        client,parent,natives,raws,streams=await self.setup_streams(raw_type=Raw)
        task=asyncio.create_task(natives[0].write_async(b'x'))
        await asyncio.wait_for(raws[0].cleaning.wait(),2)
        content=next(content for content in parent.contents.values() if content.kind=='control')
        self.assertEqual(content.status,'running')
        self.assertIsNotNone(parent._upload)
        raws[0].release.set()
        with self.assertRaisesRegex(ChildTransportFailure,'candidate_native_unavailable'):await task
        self.assertTrue(streams[0].cleanup_verified)
        self.assertIsNone(parent._upload)

    async def test_async_cancel_before_commit_discards_without_sdk_write_or_channel_abort(self):
        client,parent,natives,raws,_=await self.setup_streams()
        entered=threading.Event();release=threading.Event()
        original=client.request
        def held(verb,**fields):
            reply=original(verb,**fields)
            if verb=='native_upload_chunk':entered.set();release.wait(2)
            return reply
        with patch.object(client,'request',side_effect=held):
            task=asyncio.create_task(natives[0].write_async(b'x'*100000))
            await asyncio.to_thread(entered.wait,2)
            self.assertTrue(entered.is_set())
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(raws[0].writes,[])
        self.assertIsNone(parent._upload)
        self.assertFalse(client.closed)
        self.assertFalse(parent.closed)

    async def test_async_cancel_after_commit_joins_original_sdk_and_stream_cleanup(self):
        class Raw(fixtures._Native):
            def __init__(self):super().__init__();self.entered=asyncio.Event();self.cancelled=False
            async def write(self,body):
                self.entered.set()
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:self.cancelled=True;raise
        client,parent,natives,raws,streams=await self.setup_streams(raw_type=Raw)
        task=asyncio.create_task(natives[0].write_async(b'x'))
        await asyncio.wait_for(raws[0].entered.wait(),2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
        self.assertTrue(raws[0].cancelled)
        self.assertTrue(streams[0].cleanup_verified)
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        self.assertIsNone(parent._upload)
        self.assertFalse(client.closed)

    async def test_concurrent_subscription_writers_backpressure_without_blocking_rpc(self):
        class Raw(fixtures._Native):
            def __init__(self):super().__init__();self.entered=asyncio.Event();self.release=asyncio.Event()
            async def write(self,body):
                self.entered.set();await self.release.wait();await super().write(body)
        client,parent,natives,raws,_=await self.setup_streams(2,raw_type=Raw)
        first=asyncio.create_task(natives[0].write_async(b'first'))
        await asyncio.wait_for(raws[0].entered.wait(),2)
        owner=parent._upload
        second=asyncio.create_task(natives[1].write_async(b'second'))
        await asyncio.sleep(.01)
        self.assertIs(parent._upload,owner)
        self.assertFalse(raws[1].entered.is_set())
        rpc=ChildRPCPort(client,'pump')
        result=await asyncio.wait_for(asyncio.to_thread(rpc.envelope,
            dict(jsonrpc='2.0',id=1,method='getSlot',params=[])),2)
        self.assertEqual(result['result'],'0x123')
        raws[0].release.set();raws[1].release.set()
        await asyncio.gather(first,second)
        self.assertEqual(raws[0].writes,[b'first'])
        self.assertEqual(raws[1].writes,[b'second'])
        self.assertIsNone(parent._upload)

    async def test_same_stream_sdk_write_can_require_real_read_and_handoff_ack(self):
        class Raw(fixtures._Native):
            def __init__(self):
                super().__init__([b'same-stream-economic-frame'])
                self.entered=asyncio.Event();self.acknowledged=asyncio.Event()
            async def write(self,body):
                self.entered.set();await self.acknowledged.wait();await super().write(body)
        client,parent,natives,raws,streams=await self.setup_streams(raw_type=Raw)
        writing=asyncio.create_task(natives[0].write_async(b'replace-subscription'))
        await asyncio.wait_for(raws[0].entered.wait(),2)
        value=await asyncio.wait_for(natives[0].read_async(),2)
        self.assertEqual(value,b'same-stream-economic-frame')
        self.assertIsNone(streams[0].pending)
        self.assertFalse(writing.done())
        raws[0].acknowledged.set()
        await asyncio.wait_for(writing,2)
        self.assertEqual(raws[0].writes,[b'replace-subscription'])

    async def test_close_signals_writer_then_all_closers_join_original_cleanup(self):
        class Raw(fixtures._Native):
            def __init__(self):
                super().__init__();self.entered=asyncio.Event()
                self.cleaning=asyncio.Event();self.release=asyncio.Event()
            async def write(self,body):self.entered.set();await asyncio.Event().wait()
            async def aclose(self):
                self.cleaning.set();await self.release.wait();await super().aclose()
        client,parent,natives,raws,streams=await self.setup_streams(raw_type=Raw)
        writing=asyncio.create_task(natives[0].write_async(b'replace-subscription'))
        await asyncio.wait_for(raws[0].entered.wait(),2)
        closing=asyncio.create_task(natives[0].close_async())
        await asyncio.wait_for(raws[0].cleaning.wait(),2)
        other=asyncio.create_task(natives[0].close_async())
        await asyncio.sleep(.01)
        self.assertFalse(closing.done())
        self.assertFalse(other.done())
        raws[0].release.set()
        await asyncio.wait_for(asyncio.gather(closing,other),2)
        with self.assertRaisesRegex(ChildTransportFailure,'child_native_write_canceled'):await writing
        self.assertTrue(streams[0].cleanup_verified)
        self.assertIsNone(parent._upload)
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')


if __name__=='__main__':unittest.main()
