"""Exact parent-only offline factories, real reservations and anonymous IPC."""
import asyncio
from dataclasses import replace
import socket
import unittest
from unittest.mock import patch

from meme_machine.operational.child_transport import ChildChannel
from meme_machine.operational.parent_channel import ParentChannel,serve_connected
from meme_machine.operational.parent_transport import NativeFactoryMap,NativeSourceBinding,ParentHTTP
from meme_machine.operational.transport_bridge import BridgeRejected
from tests import test_parent_native_transport as fixtures


class NativeFactoryMapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.ParentNativeTransportTests.asyncSetUp(self)
        self.binding=NativeSourceBinding(self.sol,'yellowstone')

    async def test_actual_dynamic_stream_uses_exact_supplied_factory_and_original_budget(self):
        raw=fixtures._Native([b'fixed synthetic native bytes'])
        class Factory:
            def __bool__(self):return False
            async def __call__(self):return raw
        factories=NativeFactoryMap(self.http,[self.binding],{('pump','yellowstone'):Factory()})
        parent,child=socket.socketpair()
        reader,writer=await asyncio.open_connection(sock=parent)
        owner=ParentChannel(self.http,native_sources=[self.binding],native_factories=factories)
        with patch('meme_machine.operational.parent_transport.authenticated_native_factory',
                side_effect=AssertionError('external fallback attempted')):
            serving=asyncio.create_task(serve_connected(reader,writer,owner))
            channel=await asyncio.to_thread(ChildChannel,child)
            try:
                stream=await asyncio.to_thread(channel.native_open,channel.sources['pump'])
                self.assertEqual(await stream.read_async(),b'fixed synthetic native bytes')
                await stream.close_async()
            finally:
                await asyncio.to_thread(channel.close)
                await asyncio.wait_for(serving,3)
        self.assertTrue(raw.closed)
        self.assertEqual(self.budget.snapshot()['native_opens'],'1')
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        # Native open retains its original physical-attempt accounting even
        # though this fixed raw factory performs no HTTP/RPC acquisition.
        self.assertEqual(self.budget.snapshot()['http_attempts'],'1')
        self.assertEqual(self.budget.snapshot()['rpc_elements'],'0')
        self.assertFalse(self.physical.calls)
        self.assertFalse(owner.contents)

    async def test_partial_foreign_extra_and_untyped_maps_refuse_without_open(self):
        async def factory():raise AssertionError('refused map opened')
        for mapping in ({},{('foreign','yellowstone'):factory},
                {('pump','solana_websocket'):factory},{('pump','yellowstone'):None}):
            with self.subTest(keys=list(mapping)),self.assertRaises(BridgeRejected):
                NativeFactoryMap(self.http,[self.binding],mapping)
        mapping=NativeFactoryMap(self.http,[self.binding],{('pump','yellowstone'):factory})
        with self.assertRaises(AttributeError):mapping._http=None
        with self.assertRaises(BridgeRejected):mapping.factory(replace(self.binding))
        with self.assertRaises(BridgeRejected):
            ParentChannel(self.http,native_sources=[self.binding],native_factories={})
        foreign=ParentHTTP(self.budget,[self.sol,self.pons],opener=self.physical)
        try:
            with self.assertRaises(BridgeRejected):
                ParentChannel(foreign,native_sources=[self.binding],native_factories=mapping)
            with self.assertRaises(BridgeRejected):
                ParentChannel(self.http,native_sources=[replace(self.binding)],native_factories=mapping)
        finally:await foreign.aclose()
        self.assertEqual(self.budget.snapshot()['native_opens'],'0')


if __name__=='__main__':unittest.main()
