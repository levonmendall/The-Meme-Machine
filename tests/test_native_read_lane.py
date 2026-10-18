"""Actual idle parent streams cannot occupy native RPC/shutdown execution."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from meme_machine.operational.child_transport import ChildNativeStream,ChildRPCPort,ChildTransportFailure
from meme_machine.yellowstone import geyser_pb2 as pb
from tests import test_source_ports as fixtures


class NativeReadLaneTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.SourcePortsTests.asyncSetUp(self)
        self.default=ThreadPoolExecutor(max_workers=1,thread_name_prefix='test-small-default')
        asyncio.get_running_loop().set_default_executor(self.default)

    async def streams(self,count):
        source=self.channel.sources['yellowstone']
        return [await asyncio.to_thread(self.channel.native_open,source) for _ in range(count)]

    async def pending(self,count):
        async with asyncio.timeout(2):
            while len(self.parent.contents)<count:await asyncio.sleep(.005)

    async def test_idle_reads_leave_default_rpc_subscription_and_close_runnable(self):
        # Ten idle streams exceed the installed five-CPU default pool's nine
        # workers, while retaining every original parent byte/spend reserve.
        # maximum_streams is an upper bound, not a bypass of those other gates.
        count=min(10,self.channel.maximum_streams)
        streams=await self.streams(count)
        reads=[asyncio.create_task(stream.read_async()) for stream in streams]
        try:
            await self.pending(count)
            self.assertEqual(self.channel._read_lane._max_workers,self.channel.maximum_streams)
            self.assertEqual(len(self.channel._native_reads),count)
            self.assertLessEqual(len(self.channel._read_lane._threads),self.channel.maximum_streams)
            before=int(self.budget.snapshot()['http_attempts'])
            rpc=ChildRPCPort(self.channel,'current')
            reply=await asyncio.wait_for(asyncio.to_thread(rpc.envelope,
                dict(jsonrpc='2.0',id=91,method='getSlot',params=[])),2)
            self.assertEqual(reply['id'],91)
            self.assertEqual(int(self.budget.snapshot()['http_attempts']),before+1)
            request=pb.SubscribeRequest(commitment=pb.FINALIZED)
            request.slots['f'].filter_by_commitment=True
            await asyncio.wait_for(streams[0].write_async(request.SerializeToString()),2)
            self.assertEqual(self.sessions[0].writes,[request.SerializeToString()])
            await asyncio.wait_for(streams[0].close_async(),2)
            self.assertTrue(streams[0].closed)
        finally:
            for read in reads:read.cancel()
            await asyncio.gather(*reads,return_exceptions=True)
        self.assertFalse(self.channel._native_reads)
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        self.assertFalse(self.parent.contents)
        await asyncio.to_thread(self.channel.close)
        self.assertTrue(all(not thread.is_alive() for thread in self.channel._read_lane._threads))

    async def test_duplicate_async_read_refuses_before_another_parent_purchase(self):
        stream,=await self.streams(1)
        first=asyncio.create_task(stream.read_async())
        try:
            await self.pending(1)
            with self.assertRaisesRegex(ChildTransportFailure,'read_in_flight'):
                await stream.read_async()
            self.assertEqual(len(self.parent.contents),1)
            self.assertEqual(len(self.channel._native_reads),1)
            self.sessions[0].values.put_nowait(b'original accepted frame')
            self.assertEqual(await asyncio.wait_for(first,2),b'original accepted frame')
            self.assertFalse(self.channel._native_reads)
            self.assertFalse(self.parent.contents)
        finally:
            if not first.done():first.cancel()
            await asyncio.gather(first,return_exceptions=True)
            await stream.close_async()

    async def test_idle_timeout_reuses_original_pending_token_without_second_read(self):
        stream,=await self.streams(1)
        with self.assertRaises(TimeoutError):await stream.read_async(.02)
        token=stream._pending
        self.assertIsNotNone(token)
        self.assertFalse(self.channel._native_reads)
        second=asyncio.create_task(stream.read_async())
        try:
            await self.pending(1)
            self.assertEqual(stream._pending,token)
            self.sessions[0].values.put_nowait(b'late original frame')
            self.assertEqual(await asyncio.wait_for(second,2),b'late original frame')
            self.assertIsNone(stream._pending)
            self.assertFalse(self.parent.contents)
        finally:
            if not second.done():second.cancel()
            await asyncio.gather(second,return_exceptions=True)
            await stream.close_async()

    async def test_repeated_cancellation_keeps_read_charged_until_original_close_joins(self):
        stream,=await self.streams(1)
        entered=asyncio.Event();release=asyncio.Event()
        original=self.sessions[0].aclose
        async def slow_close():
            entered.set()
            await release.wait()
            await original()
        self.sessions[0].aclose=slow_close
        task=asyncio.create_task(stream.read_async())
        try:
            await self.pending(1)
            task.cancel()
            await asyncio.wait_for(entered.wait(),2)
            task.cancel()
            await asyncio.sleep(.02)
            self.assertFalse(task.done())
            self.assertIn(stream.stream,self.channel._native_reads)
            self.assertGreater(int(self.budget.snapshot()['native_reserved']),0)
        finally:
            release.set()
            with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
        self.assertFalse(self.channel._native_reads)
        self.assertFalse(self.parent.contents)
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')

    async def test_abort_signals_reads_without_self_join_and_owner_joins_all_threads(self):
        streams=await self.streams(2)
        reads=[asyncio.create_task(stream.read_async()) for stream in streams]
        await self.pending(2)
        await asyncio.wait_for(asyncio.to_thread(self.channel.abort_and_join),2)
        await asyncio.gather(*reads,return_exceptions=True)
        self.assertFalse(self.channel._native_reads)
        self.assertTrue(all(not thread.is_alive() for thread in self.channel._read_lane._threads))

    async def test_read_worker_cannot_join_its_own_lane(self):
        stream,=await self.streams(1)
        def wrong_owner(stream,timeout=None):stream.channel.abort_and_join()
        with patch.object(ChildNativeStream,'read',wrong_owner):
            with self.assertRaisesRegex(ChildTransportFailure,'read_owner_join_required'):
                await stream.read_async()
        await asyncio.to_thread(self.channel.abort_and_join)
        self.assertTrue(all(not thread.is_alive() for thread in self.channel._read_lane._threads))

    async def test_worker_start_failure_aborts_queued_read_and_retains_owned_lane_for_join(self):
        stream,=await self.streams(1)
        with patch.object(self.channel._read_lane,'_adjust_thread_count',
                side_effect=RuntimeError('fixed worker-start failure')):
            with self.assertRaisesRegex(RuntimeError,'fixed worker-start failure'):
                await stream.read_async()
        self.assertTrue(self.channel.closed)
        self.assertFalse(self.channel._native_reads)
        self.assertFalse(self.parent.contents)
        await asyncio.to_thread(self.channel.abort_and_join)
        self.assertTrue(all(not thread.is_alive() for thread in self.channel._read_lane._threads))

    async def test_join_under_control_lock_refuses_instead_of_deadlocking_original_read(self):
        stream,=await self.streams(1)
        task=asyncio.create_task(stream.read_async())
        await self.pending(1)
        with self.channel.lock:
            with self.assertRaisesRegex(ChildTransportFailure,'read_owner_join_required'):
                self.channel.abort_and_join()
        await asyncio.to_thread(self.channel.abort_and_join)
        await asyncio.gather(task,return_exceptions=True)
        self.assertFalse(self.channel._native_reads)

    async def test_read_abort_preserves_original_failure_and_denies_financial_construction(self):
        from meme_machine.runtime.isolated_native_execution import financial_writes_denied
        stream,=await self.streams(1)
        def failed(stream,timeout=None):
            self.assertTrue(financial_writes_denied())
            try:raise ChildTransportFailure('original_read_failure')
            except BaseException:
                stream.channel.abort()
                raise
        with patch.object(ChildNativeStream,'read',failed):
            with self.assertRaisesRegex(ChildTransportFailure,'^original_read_failure$'):
                await stream.read_async()
        await asyncio.to_thread(self.channel.abort_and_join)
        self.assertFalse(self.channel._native_reads)

