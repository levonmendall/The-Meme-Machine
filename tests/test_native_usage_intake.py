"""Burst intake preserves every byte and FIFO fact before economic consumers."""
import asyncio
from collections import deque
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock
import grpc
from meme_machine.operational.bounded_provider import Budget,NativeReadBuffer,MAX_FRAME,CeilingReached


class NativeUsageIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'usage.sqlite'
        self.budget=Budget.create(self.path,modeled_spend_limit='3')
        self.token=self.budget.stream_open('yellowstone');self.calls=[]

    def native(self,transport,size):
        self.calls.append(size);self.budget.native(transport,size,token=self.token)

    def buffer(self,packets):
        values=deque(packets)
        async def read():return values.popleft() if values else grpc.aio.EOF
        return NativeReadBuffer(read,SimpleNamespace(native=self.native,fail=self.budget.fail),'yellowstone')

    def test_burst_fifo_and_durable_totals_match_original_after_restart(self):
        packets=[(len(raw),raw) for raw in [bytes([n%256])*(1+n%13) for n in range(200)]]
        buffer=self.buffer(packets)
        async def verify():
            output=[]
            for _ in packets:
                value=await buffer.read();output.append(value)
                self.assertGreaterEqual(int(Budget(self.path).snapshot()['native_bytes']),sum(map(len,output)))
            self.assertIs(await buffer.read(),grpc.aio.EOF)
            return output
        self.assertEqual(asyncio.run(verify()),[p[1] for p in packets])
        self.assertEqual(int(self.budget.snapshot()['native_bytes']),sum(p[0] for p in packets))
        self.assertLessEqual(len(self.calls),7)
        self.budget.stream_close(self.token,unread_possible=True)
        resumed=Budget(self.path).snapshot()
        self.assertEqual(resumed['native_opens'],'1');self.assertEqual(resumed['native_reserved'],'0')
        self.assertEqual(resumed['native_uncertain_bytes'],str(3*MAX_FRAME))

    def test_live_frame_is_not_held_waiting_for_a_batch(self):
        async def verify():
            gate=asyncio.Event();count=0
            async def read():
                nonlocal count
                count+=1
                if count==1:return 4,b'live'
                await gate.wait();return grpc.aio.EOF
            buffer=NativeReadBuffer(read,SimpleNamespace(native=self.native),'yellowstone')
            self.assertEqual(await asyncio.wait_for(buffer.read(),.1),b'live')
            self.assertEqual(self.calls,[4]);buffer.cancel();await asyncio.sleep(0)
        asyncio.run(verify())

    def test_transport_error_follows_all_prior_paid_facts(self):
        error=OSError('offline fault');count=0;faults=[]
        async def read():
            nonlocal count
            count+=1
            if count<=2:return 2,bytes([count,count])
            raise error
        buffer=NativeReadBuffer(read,SimpleNamespace(native=self.native,provider_error=faults.append),'yellowstone')
        async def verify():
            self.assertEqual(await buffer.read(),b'\x01\x01')
            self.assertEqual(self.budget.snapshot()['native_bytes'],'4')
            self.assertEqual(await buffer.read(),b'\x02\x02')
            with self.assertRaises(OSError):await buffer.read()
        asyncio.run(verify());self.assertEqual(len(faults),1);self.assertEqual(self.calls,[4])

    def test_group_and_lookahead_are_inside_the_reserved_physical_bound(self):
        raw=b'x'*(9*1024**2);buffer=self.buffer([(len(raw),raw),(len(raw),raw)])
        async def verify():
            self.assertEqual(await buffer.read(),raw)
            self.assertEqual(sum(map(len,buffer.values)),0)
            self.assertIsNotNone(buffer.carry)
            self.assertEqual(self.budget.snapshot()['native_bytes'],str(len(raw)))
            self.assertEqual(await buffer.read(),raw)
            self.assertIs(await buffer.read(),grpc.aio.EOF)
        asyncio.run(verify());self.assertEqual(self.calls,[len(raw),len(raw)])
        self.assertEqual(self.budget.snapshot()['native_reserved'],str(3*MAX_FRAME))
        with self.assertRaisesRegex(CeilingReached,'native_frame_bound'):
            asyncio.run(self.buffer([(MAX_FRAME+1,b'invalid')]).read())
        self.assertEqual(self.budget.snapshot()['reason'],'native_frame_bound')

    def test_websocket_utf8_counts_are_equal_and_content_stays_fifo(self):
        rows=['price €','pool','成交'];packets=[(len(s.encode()),s) for s in rows]
        buffer=self.buffer(packets)
        self.assertEqual(asyncio.run(self.consume(buffer,len(rows))),rows)
        self.assertEqual(sum(self.calls),sum(len(s.encode()) for s in rows))

    async def consume(self,buffer,count):return [await buffer.read() for _ in range(count)]


if __name__=='__main__':unittest.main()
