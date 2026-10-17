"""Actual anonymous IPC and real parent ledgers; offline physical I/O only."""
import asyncio
import json
import socket
import sqlite3
import struct
import threading
import time
import unittest

from meme_machine.operational.child_transport import (
    ChildChannel, ChildParentFailure, ChildRPCPort, ChildTransportFailure, require_rpc_port,
)
from meme_machine.operational.parent_channel import ParentChannel, serve_connected
from meme_machine.operational.parent_transport import ParentNativeStream,NativeSourceBinding
from unittest.mock import patch
from tests import test_parent_native_transport as fixtures


class ChildTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.ParentNativeTransportTests.asyncSetUp(self)

    async def connected(self, *, streams=None, cancelled=None,native_sources=()):
        parent, child = socket.socketpair()
        reader, writer = await asyncio.open_connection(sock=parent)
        channel = ParentChannel(self.http, streams=streams,native_sources=native_sources)
        task = asyncio.create_task(serve_connected(reader, writer, channel))
        port = await asyncio.to_thread(ChildChannel, child, cancelled=cancelled)
        async def close():
            try:
                await asyncio.to_thread(port.close)
            finally:
                await asyncio.wait_for(task, 3)
        self.addAsyncCleanup(close)
        return port, channel

    async def test_actual_large_scalar_roundtrip_identity_and_real_accounting(self):
        expected = 'x' * (300 * 1024)
        self.physical.body = json.dumps(dict(jsonrpc='2.0', id=1, result=expected)).encode()
        client, parent = await self.connected()
        port = ChildRPCPort(client, 'pump')
        reply,delivery = await asyncio.to_thread(port.envelope_delivered,
            dict(jsonrpc='2.0', id=912, method='getSlot', params=[]))
        self.assertEqual(reply, dict(jsonrpc='2.0', id=912, result=expected))
        handed=json.dumps(dict(jsonrpc='2.0',id=1,result=expected),
            sort_keys=True,separators=(',',':')).encode()
        self.assertEqual(delivery,dict(bytes=len(handed)))
        self.assertNotEqual(delivery['bytes'],len(self.physical.body))
        self.assertEqual(port.source.endpoint_identity, self.sol.identity)
        self.assertIs(require_rpc_port(port, 'solana'), port)
        self.assertFalse(hasattr(port.source, '_url'))
        self.assertEqual(len(self.physical.calls), 1)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '1')
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')
        self.assertEqual(self.budget.snapshot()['http_bytes'], str(len(self.physical.body)))
        self.assertFalse(parent.contents)
        with self.assertRaises(AttributeError):
            port.source = client.sources['pons']

    async def test_original_batch_ids_order_one_physical_request_and_demand(self):
        self.physical.body = json.dumps([
            dict(jsonrpc='2.0', id=2, result='second'),
            dict(jsonrpc='2.0', id=1, result='first')]).encode()
        client, parent = await self.connected()
        port = ChildRPCPort(client, 'pons')
        await asyncio.to_thread(port.demand, ['eth_chainId', 'eth_blockNumber'])
        reply = await asyncio.to_thread(port.envelope, [
            dict(jsonrpc='2.0', id=78, method='eth_chainId', params=[]),
            dict(jsonrpc='2.0', id=23, method='eth_blockNumber', params=[])])
        self.assertEqual([row['id'] for row in reply], [23,78])
        self.assertEqual([row['result'] for row in reply], ['second','first'])
        self.assertIsInstance(self.physical.calls[0], list)
        self.assertEqual(len(self.physical.calls), 1)
        self.assertEqual(self.budget.snapshot()['rpc_elements'], '2')
        self.assertFalse(parent.contents)
        marker = await asyncio.to_thread(port.activity_marker)
        self.assertEqual(marker, self.admission.activity_marker())

    async def test_pump_and_pons_progress_concurrently_without_control_lock_wait(self):
        client, _ = await self.connected()
        self.physical.gate.clear()
        tasks = [asyncio.create_task(asyncio.to_thread(ChildRPCPort(client, alias).envelope,
            dict(jsonrpc='2.0', id=1, method=method, params=[])))
            for alias,method in [('pump','getSlot'),('pons','eth_chainId')]]
        try:
            async with asyncio.timeout(2):
                while len(self.physical.calls) < 2:
                    await asyncio.sleep(.01)
            self.assertEqual(len(self.physical.calls), 2)
        finally:
            self.physical.gate.set()
            result = await asyncio.gather(*tasks)
        self.assertEqual(len(result), 2)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '2')

    async def test_stop_closes_new_admission_and_drains_original_accepted_receipt(self):
        canceled = threading.Event()
        client, _ = await self.connected(cancelled=canceled.is_set)
        self.physical.gate.clear()
        task = asyncio.create_task(asyncio.to_thread(ChildRPCPort(client,'pump').envelope,
            dict(jsonrpc='2.0', id=1, method='getSlot', params=[])))
        try:
            await asyncio.to_thread(self.physical.entered.wait, 2)
            self.assertTrue(self.physical.entered.is_set())
            canceled.set()
            with self.assertRaisesRegex(ChildTransportFailure,'stopped'):
                await asyncio.to_thread(ChildRPCPort(client,'pump').envelope,
                    dict(jsonrpc='2.0',id=2,method='getSlot',params=[]))
            self.assertFalse(client.closed)
        finally:
            self.physical.gate.set()
        self.assertEqual((await asyncio.wait_for(task,2))['result'],'0x123')
        # Cleanup is parent-owned and completed by the connected-server drain.
        async with asyncio.timeout(2):
            while self.budget.snapshot()['http_reserved'] != '0':
                await asyncio.sleep(.01)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '1')

    async def test_source_and_envelope_forgery_refused_without_purchase(self):
        client, _ = await self.connected()
        with self.assertRaises(ChildTransportFailure):
            require_rpc_port(ChildRPCPort(client,'pump'), 'robinhood')
        port = ChildRPCPort(client,'pump')
        for request in [
            dict(jsonrpc='2.0', id=1, method='getSlot', params=[], url='https://bad.invalid'),
            [dict(jsonrpc='2.0', id=1, method='getSlot', params=[])] * 2,
            dict(jsonrpc='2.0', id=True, method='getSlot', params=[]),
        ]:
            with self.assertRaises(ChildTransportFailure):
                port.envelope(request)
        self.assertFalse(self.physical.calls)
        self.assertEqual(self.budget.snapshot()['http_attempts'], '0')

    async def test_native_actual_paid_handoff_never_acknowledges_child_history(self):
        body = b'native-economics' * 5000
        raw = fixtures._Native([body])
        async def factory():
            return raw
        stream = await ParentNativeStream.open(self.budget, 'yellowstone', factory, lambda _:None)
        client, parent = await self.connected(streams={'pump':stream})
        native=next(iter(client._native_handles.values()))
        value = await asyncio.to_thread(native.read)
        self.assertEqual(value, body)
        self.assertIsNone(stream.pending)
        self.assertFalse(parent.contents)
        self.assertEqual(self.budget.snapshot()['native_bytes'], str(len(body)))
        self.assertFalse(any('ack' in key.lower() for key in self.budget.snapshot()))

    async def test_oversized_control_length_rejected_before_body_allocation(self):
        parent, child = socket.socketpair()
        self.addCleanup(parent.close)
        parent.sendall(struct.pack('!I', 10 * 1024 * 1024))
        with self.assertRaisesRegex(ChildTransportFailure, 'control_bound'):
            await asyncio.to_thread(ChildChannel, child)
        self.assertEqual(child.fileno(), -1)

    async def test_unnamed_seqpacket_is_not_mistaken_for_stream_socket(self):
        parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        self.addCleanup(parent.close);self.addCleanup(child.close)
        with self.assertRaisesRegex(ChildTransportFailure,'channel_configuration'):
            await asyncio.to_thread(ChildChannel,child)

    async def test_rpc_nonfinite_or_duplicate_response_does_not_relabel_as_evidence(self):
        # Parent provider validation is the first boundary. The child parser
        # independently rejects invalid JSON that a future adapter could emit.
        from meme_machine.operational.child_transport import _json
        for body in (b'{"x":1,"x":2}', b'{"x":1e999}', b'{"x":NaN}'):
            with self.assertRaises(ChildTransportFailure):
                _json(body)

    async def test_native_idle_timeout_keeps_one_original_pending_read_and_reservation(self):
        raw=fixtures._Native()
        async def factory():return raw
        stream=await ParentNativeStream.open(self.budget,'yellowstone',factory,lambda _:None)
        client,parent=await self.connected(streams={'pump':stream})
        native=next(iter(client._native_handles.values()))
        with self.assertRaises(TimeoutError):
            await asyncio.to_thread(native.read,.02)
        token=native._pending
        self.assertEqual(len(parent.contents),1)
        self.assertEqual(self.budget.snapshot()['native_opens'],'1')
        raw.values.put_nowait(b'original-pending-economic-frame')
        self.assertEqual(await asyncio.to_thread(native.read,.5),b'original-pending-economic-frame')
        self.assertNotIn(token,parent.contents)
        self.assertEqual(self.budget.snapshot()['native_opens'],'1')
        await native.close_async()

    async def test_multiple_native_instances_share_source_and_keep_independent_paid_handles(self):
        raws=[]
        async def factory():
            raw=fixtures._Native([('instance-'+str(len(raws))).encode()])
            raws.append(raw);return raw
        client,parent=await self.connected(native_sources=[NativeSourceBinding(self.sol,'yellowstone')])
        with patch('meme_machine.operational.parent_transport.authenticated_native_factory',return_value=factory):
            streams=await asyncio.gather(*(asyncio.to_thread(client.native_stream,client.sources['pump'])
                for _ in range(3)))
        self.assertEqual(len({stream.stream for stream in streams}),3)
        self.assertEqual(self.budget.snapshot()['native_opens'],'3')
        self.assertEqual(set(await asyncio.gather(*(stream.read_async() for stream in streams))),
            {b'instance-0',b'instance-1',b'instance-2'})
        await streams[0].close_async()
        self.assertFalse(streams[1].closed)
        self.assertFalse(streams[2].closed)
        await asyncio.gather(*(stream.close_async() for stream in streams))
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        self.assertFalse(parent.contents)

    async def test_429_is_fixed_original_boundary_and_retains_parent_debt(self):
        self.physical.status = 429
        self.physical.fail_after = 0
        client, parent = await self.connected()
        with self.assertRaisesRegex(ChildParentFailure, '^provider_http_429$'):
            await asyncio.to_thread(ChildRPCPort(client,'pons').envelope,
                dict(jsonrpc='2.0', id=1, method='eth_chainId', params=[]))
        self.assertFalse(client.closed)
        self.assertFalse(parent.contents)
        self.assertEqual(len(self.physical.calls), 1)
        self.assertEqual(self.budget.snapshot()['http_reserved'], '0')
        with sqlite3.connect(self.admission.path) as db:
            self.assertGreater(db.execute('SELECT cooldown FROM limits').fetchone()[0], time.monotonic())


if __name__ == '__main__':
    unittest.main()
