"""Burst intake preserves every byte and FIFO fact before economic consumers."""
import asyncio
import threading
from collections import deque
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import sqlite3
import subprocess
import sys
from unittest.mock import AsyncMock,patch
import grpc
from meme_machine.operational.bounded_provider import Budget,NativeReadBuffer,MAX_FRAME,CeilingReached,NATIVE_READY_FRAMES,native_ledger_reader


class NativeUsageIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'usage.sqlite'
        self.budget=Budget.create(self.path,modeled_spend_limit='3')
        self.token=self.budget.stream_open('yellowstone');self.calls=[]

    def native(self,transport,size):
        self.calls.append(size);self.budget.native(transport,size,token=self.token)

    def test_changed_key_commits_match_legacy_totals_without_rewriting_configuration(self):
        old=Budget.create(Path(self.tmp.name)/'legacy.sqlite',modeled_spend_limit='3')
        # Exact prior persistence behavior, including its rollback-journal mode.
        with old.db() as db:db.execute('PRAGMA journal_mode=DELETE')
        def legacy_write(budget,db,state):
            db.executemany('UPDATE run SET value=? WHERE key=?',
                [(str(v),budget.prefix+k) for k,v in state.items()])
        original=self.budget.db;updates=[]
        def traced():
            db=original();db.set_trace_callback(lambda sql:updates.append(sql) if sql.startswith('UPDATE run') else None)
            return db
        with patch.object(Budget,'write',legacy_write):
            token=old.stream_open('yellowstone')
            for size in range(1,65):old.native('yellowstone',size,token=token)
            old.stream_close(token,unread_possible=True)
        with patch.object(self.budget,'db',traced):
            for size in range(1,65):self.budget.native('yellowstone',size,token=self.token)
        self.assertEqual(len(updates),64)
        self.assertTrue(all("key='native_bytes'" in sql for sql in updates))
        self.budget.stream_close(self.token,unread_possible=True)
        before=old.snapshot();after=Budget(self.path).snapshot()
        for field in ('rpc_cu','rpc_elements','http_attempts','native_bytes','native_reserved',
                'native_uncertain_bytes','native_opens','reason','limits','resource_configuration'):
            self.assertEqual(after[field],before[field],field)
        self.assertEqual(int(after['native_bytes']),sum(range(1,65)))

    def test_new_ledger_full_wal_commits_survive_ungraceful_worker_exit(self):
        with self.budget.db() as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'wal')
            self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0],2)
        code='''import os,sys
from meme_machine.operational.bounded_provider import Budget
b=Budget(sys.argv[1]);token=b.stream_open('yellowstone')
b.native('yellowstone',1234,token=token)
os._exit(0)
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.path)],capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        resumed=Budget(self.path)
        self.assertEqual(resumed.snapshot()['native_bytes'],'1234')
        self.assertEqual(resumed.snapshot()['native_opens'],'2')
        resumed.reap_orphans()
        state=resumed.snapshot()
        self.assertEqual(state['native_bytes'],'1234')
        self.assertEqual(state['native_uncertain_bytes'],str(4*MAX_FRAME))
        self.assertEqual(state['native_reserved'],str(4*MAX_FRAME))

    def test_failed_changed_counter_write_does_not_publish_or_partially_commit_usage(self):
        with self.budget.db() as db:
            db.execute("CREATE TRIGGER reject_usage BEFORE UPDATE OF value ON run WHEN NEW.key='native_bytes' BEGIN SELECT RAISE(ABORT,'offline storage fault'); END")
        before=self.budget.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):self.budget.native('yellowstone',99,token=self.token)
        self.assertEqual(self.budget.snapshot(),before)

    def test_stream_reader_keeps_wal_open_without_pinning_history_or_delaying_commits(self):
        reader=native_ledger_reader(self.budget);self.addCleanup(reader.close)
        self.assertIsNotNone(reader)
        for size in range(1,65):self.budget.native('yellowstone',size,token=self.token)
        self.assertTrue(Path(str(self.path)+'-wal').exists())
        self.assertEqual(Budget(self.path).snapshot()['native_bytes'],str(sum(range(1,65))))
        with self.budget.db() as db:
            # No read snapshot prevents ordinary checkpointing.
            self.assertEqual(db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0],0)
            self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0],2)
        with self.assertRaises(sqlite3.OperationalError):reader.execute("UPDATE run SET value='0' WHERE key='native_bytes'")
        reader.close()
        self.assertEqual(Budget(self.path).snapshot()['native_bytes'],str(sum(range(1,65))))

    def test_historical_delete_ledger_is_not_migrated_by_stream_reader(self):
        with self.budget.db() as db:db.execute('PRAGMA journal_mode=DELETE')
        before=self.budget.snapshot()
        self.assertIsNone(native_ledger_reader(self.budget))
        with self.budget.db() as db:self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'delete')
        self.assertEqual(self.budget.snapshot(),before)

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
        self.assertEqual(resumed['native_uncertain_bytes'],str(4*MAX_FRAME))

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

    def test_async_sdk_delivery_progresses_during_a_durable_write_without_returning_content(self):
        async def verify():
            entered=threading.Event();release=threading.Event();packets=deque((10,bytes([n%256])*10) for n in range(200))
            async def read():
                await asyncio.sleep(0)
                return packets.popleft() if packets else grpc.aio.EOF
            def native(transport,size):
                if not self.calls:
                    entered.set()
                    if not release.wait(2):raise RuntimeError('offline_release_missing')
                self.native(transport,size)
            buffer=NativeReadBuffer(read,SimpleNamespace(native=native),'yellowstone')
            first=asyncio.create_task(buffer.read())
            try:
                for _ in range(100):
                    if entered.is_set():break
                    await asyncio.sleep(.001)
                self.assertTrue(entered.is_set())
                await asyncio.sleep(.02)
                self.assertFalse(first.done())
                # One packet is in the uncommitted charged group; only the
                # remaining 199 can be in lookahead while that write waits.
                self.assertEqual(len(buffer.ready),min(199,NATIVE_READY_FRAMES))
                self.assertEqual(self.budget.snapshot()['native_bytes'],'0')
                release.set();output=[await first]
                output.extend(await self.consume(buffer,199))
                self.assertIs(await buffer.read(),grpc.aio.EOF)
                self.assertEqual(output,[bytes([n%256])*10 for n in range(200)])
                self.assertEqual(self.budget.snapshot()['native_bytes'],'2000')
                self.assertLess(len(self.calls),16)
            finally:
                release.set();await asyncio.gather(first,return_exceptions=True);buffer.cancel()
        asyncio.run(verify())

    def test_cancellation_retains_unread_ready_delivery_as_reserved_uncertainty(self):
        async def verify():
            buffer=self.buffer([(3,b'raw')]*200);buffer.start()
            await asyncio.sleep(0)
            self.assertEqual(len(buffer.ready),min(200,NATIVE_READY_FRAMES))
            self.assertEqual(self.budget.snapshot()['native_bytes'],'0')
            buffer.cancel();await asyncio.sleep(0)
            with self.assertRaises(asyncio.CancelledError):await buffer.read()
        asyncio.run(verify());self.budget.stream_close(self.token,unread_possible=True)
        state=Budget(self.path).snapshot()
        self.assertEqual(state['native_bytes'],'0')
        self.assertEqual(state['native_uncertain_bytes'],str(4*MAX_FRAME))

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
            self.assertLessEqual(buffer.ready_bytes,MAX_FRAME)
            self.assertLessEqual(sum(map(len,buffer.values))+buffer.ready_bytes,2*MAX_FRAME)
            self.assertEqual(self.budget.snapshot()['native_bytes'],str(len(raw)))
            self.assertEqual(await buffer.read(),raw)
            self.assertIs(await buffer.read(),grpc.aio.EOF)
        asyncio.run(verify());self.assertEqual(self.calls,[len(raw),len(raw)])
        self.assertEqual(self.budget.snapshot()['native_reserved'],str(4*MAX_FRAME))
        with self.assertRaisesRegex(CeilingReached,'native_frame_bound'):
            asyncio.run(self.buffer([(MAX_FRAME+1,b'invalid')]).read())
        self.assertEqual(self.budget.snapshot()['reason'],'native_frame_bound')

    def test_websocket_utf8_counts_are_equal_and_content_stays_fifo(self):
        rows=['price €','pool','成交'];packets=[(len(s.encode()),s) for s in rows]
        buffer=self.buffer(packets)
        self.assertEqual(asyncio.run(self.consume(buffer,len(rows))),rows)
        self.assertEqual(sum(self.calls),sum(len(s.encode()) for s in rows))

    def test_small_status_burst_preserves_count_and_byte_bounds_without_per_32_fsyncs(self):
        packets=[(93,bytes([n%256])*93) for n in range(1024)]
        buffer=self.buffer(packets)
        async def verify():
            buffer.start();await asyncio.sleep(0)
            self.assertEqual(len(buffer.ready),NATIVE_READY_FRAMES)
            self.assertLessEqual(buffer.ready_bytes,MAX_FRAME)
            output=await self.consume(buffer,1024)
            self.assertIs(await buffer.read(),grpc.aio.EOF)
            return output
        self.assertEqual(asyncio.run(verify()),[p[1] for p in packets])
        self.assertEqual(sum(self.calls),93*1024)
        self.assertEqual(len(self.calls),4)

    async def consume(self,buffer,count):return [await buffer.read() for _ in range(count)]


if __name__=='__main__':unittest.main()
