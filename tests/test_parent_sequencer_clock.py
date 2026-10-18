"""Actual native clock/parser over parent Nitro SDK, IPC and original ledger."""
import asyncio
from dataclasses import replace
import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.sequencer_feed import SequencerBlockClock,SequencerTransportError,_WebSocket
from meme_machine.operational.child_transport import ChildChannel,ChildTransportFailure
from meme_machine.operational.parent_channel import ParentChannel,serve_connected
from meme_machine.operational.parent_transport import ParentHTTP,NativeSourceBinding
from tests import test_parent_native_transport as fixtures
from tests.lanes.pons.test_sequencer_feed import row


def wire(body):
    body=body if type(body) is bytes else json.dumps(body).encode()
    size=len(body)
    return bytes((0x81,size)) + body if size<126 else bytes((0x81,126))+size.to_bytes(2,'big')+body


class _Socket:
    def __init__(self,frames):
        self.data=bytearray(b''.join(wire(frame) for frame in frames))
        self.condition=threading.Condition();self.closed=False

    def push(self,frame):
        with self.condition:self.data.extend(wire(frame));self.condition.notify_all()

    def recv(self,size):
        with self.condition:
            if not self.data and not self.closed:self.condition.wait(.01)
            if self.closed:raise OSError('offline socket stopped')
            if not self.data:raise socket.timeout()
            out=bytes(self.data[:size]);del self.data[:size];return out

    def shutdown(self,_):self.close()

    def close(self):
        with self.condition:self.closed=True;self.condition.notify_all()


class ParentSequencerClockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.ParentNativeTransportTests.asyncSetUp(self)

    async def connected(self,sessions):
        self.sockets=[]
        def connect(client):
            self.assertEqual(client.url,'wss://feed.mainnet.chain.robinhood.com')
            sock=_Socket(sessions[len(self.sockets)]);self.sockets.append(sock)
            client.sock=sock;client.socket_observer(sock)
            return client
        self.enterContext(patch.object(_WebSocket,'connect',connect))
        source=replace(self.pons,operation='pons_discovery')
        http=ParentHTTP(self.budget,[source],opener=self.physical)
        native=NativeSourceBinding(source,'robinhood_sequencer')
        channel=ParentChannel(http,native_sources=[native])
        parent,child=socket.socketpair()
        reader,writer=await asyncio.open_connection(sock=parent)
        serving=asyncio.create_task(serve_connected(reader,writer,channel))
        client=await asyncio.to_thread(ChildChannel,child)
        async def close():
            try:await asyncio.to_thread(client.close)
            finally:await asyncio.wait_for(serving,3)
        self.addAsyncCleanup(close)
        stream=await asyncio.to_thread(client.native_open,client.sources['pons'])
        clock=SequencerBlockClock(parent_stream=stream)
        self.addAsyncCleanup(asyncio.to_thread,clock.close)
        return clock,client,channel

    async def test_real_clock_observes_original_payload_and_preserves_native_authority(self):
        stamp=int(time.time())
        payload=dict(version=1,messages=[row(10,block=20,timestamp=stamp),row(11,block=21,timestamp=stamp)])
        clock,client,parent=await self.connected([[payload]])
        # Explicit parent path must never consult child provider environment.
        with patch('meme_machine.lanes.pons.sequencer_feed.feed_url',side_effect=AssertionError('child URL')):
            self.assertEqual(await asyncio.to_thread(clock.wait_for_after,9,timeout=.5),11)
        status=clock.status()
        self.assertEqual(status['authority'],'observation_only')
        self.assertFalse(status['canonical_evidence'])
        self.assertEqual(clock.state.latest_header_timestamp,stamp)
        self.assertEqual(status['messages'],2)
        self.assertEqual(self.budget.snapshot()['native_opens'],'1')
        self.assertEqual(self.budget.snapshot()['native_bytes'],str(len(json.dumps(payload).encode())))
        self.assertFalse(parent.contents)
        self.assertFalse(any('ack' in key.lower() for key in self.budget.snapshot()))

    async def test_idle_retains_original_pending_read_and_reconnect_opens_new_instance(self):
        first=dict(version=1,messages=[row(10,timestamp=int(time.time()))])
        second=dict(version=1,messages=[row(15,timestamp=int(time.time()))])
        clock,client,parent=await self.connected([[first],[second]])
        self.assertEqual(await asyncio.to_thread(clock.wait_for_after,9,timeout=.2),10)
        stream=clock._parent_stream
        self.assertIsNone(await asyncio.to_thread(clock.wait_for_after,10,timeout=.06))
        self.assertEqual(self.budget.snapshot()['native_opens'],'1')
        read_tokens=[c for c in parent.contents.values() if c.kind=='native']
        self.assertEqual(len(read_tokens),1)
        self.assertIsNone(await asyncio.to_thread(clock.wait_for_after,10,timeout=.06))
        self.assertEqual(len([c for c in parent.contents.values() if c.kind=='native']),1)
        self.sockets[0].push(dict(version=1,messages=[row(11,timestamp=int(time.time()))]))
        self.assertEqual(await asyncio.to_thread(clock.wait_for_after,10,timeout=.3),11)
        await asyncio.to_thread(clock.reconnect)
        self.assertTrue(stream.closed)
        self.assertNotEqual(stream.stream,clock._parent_stream.stream)
        self.assertEqual(self.budget.snapshot()['native_opens'],'2')
        self.assertEqual(await asyncio.to_thread(clock.wait_for_after,11,timeout=.3),15)
        self.assertEqual(clock.status()['reconnects'],1)
        self.assertEqual(clock.status()['aggregate_gap_events'],0)
        self.assertFalse(clock.status()['canonical_evidence'])
        self.assertEqual(clock.status()['session_history'][0]['last_sequence'],11)

    async def test_gap_payload_remains_native_fail_closed(self):
        clock,_,_=await self.connected([[dict(version=1,messages=[row(10),row(12)])]])
        with self.assertRaisesRegex(BoundaryError,'continuity_lost'):
            await asyncio.to_thread(clock.wait_for_after,9,timeout=.3)
        self.assertEqual(clock.status()['gap_events'],1)
        self.assertFalse(clock.status()['canonical_evidence'])
        self.assertEqual(self.budget.snapshot()['native_opens'],'1')

    async def test_malformed_payload_is_counted_without_qualification_or_new_reservation(self):
        clock,_,_=await self.connected([[b'not-json']])
        with self.assertRaisesRegex(BoundaryError,'continuity_lost'):
            await asyncio.to_thread(clock.wait_for_after,9,timeout=.3)
        self.assertEqual(clock.status()['malformed'],1)
        self.assertFalse(clock.status()['canonical_evidence'])
        self.assertEqual(self.budget.snapshot()['native_opens'],'1')

    async def test_parent_transport_loss_retains_native_reconnect_and_rpc_backfill_boundary(self):
        first=dict(version=1,messages=[row(10,timestamp=int(time.time()))])
        second=dict(version=1,messages=[row(15,timestamp=int(time.time()))])
        clock,_,_=await self.connected([[first],[second]])
        self.assertEqual(await asyncio.to_thread(clock.wait_for_after,9,timeout=.2),10)
        self.sockets[0].close()
        with self.assertRaises(SequencerTransportError):
            await asyncio.to_thread(clock.wait_for_after,10,timeout=.3)
        self.assertEqual(clock.state.last_sequence,10)
        self.assertEqual(clock.status()['transport_failures'],1)
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        await asyncio.to_thread(clock.reconnect)
        self.assertEqual(await asyncio.to_thread(clock.wait_for_after,10,timeout=.3),15)
        self.assertEqual(self.budget.snapshot()['native_opens'],'2')
        self.assertEqual(clock.status()['session_history'][0]['last_sequence'],10)
        self.assertFalse(clock.status()['canonical_evidence'])

    async def test_exact_owned_native_feed_refuses_ambient_url_and_rpc_substitution(self):
        clock,client,_=await self.connected([[]])
        with self.assertRaisesRegex(BoundaryError,'parent_url_forbidden'):
            SequencerBlockClock('wss://example.invalid',parent_stream=clock._parent_stream)
        with self.assertRaises(ChildTransportFailure):
            SequencerBlockClock(parent_stream=object())
        self.assertEqual(self.budget.snapshot()['native_opens'],'1')

    async def test_preconnect_startup_cleanup_closes_original_parent_reservation(self):
        clock,_,_=await self.connected([[]])
        self.assertIsNone(clock.client)
        self.assertGreater(int(self.budget.snapshot()['native_reserved']),0)
        await asyncio.to_thread(clock.close)
        self.assertTrue(clock._parent_stream.closed)
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        await asyncio.to_thread(clock.close)
        self.assertEqual(self.budget.snapshot()['native_opens'],'1')


if __name__=='__main__':unittest.main()
