"""Fixed protected profile capability over actual anonymous parent IPC."""
import asyncio
from dataclasses import replace
import json
import socket
import unittest
from unittest.mock import patch

from meme_machine.operational.child_transport import ChildChannel,ChildRPCPort,ChildTransportFailure
from meme_machine.operational.parent_channel import ParentChannel,serve_connected
from meme_machine.operational.parent_transport import ParentHTTP
from meme_machine.operational.pons_native_profile import ParentPonsProfiles,ProfileFailure,require_profile
from meme_machine.operational.transport_bridge import READ_METHODS as PUBLISHED_METHODS,BridgeRejected
from meme_machine.lanes.pons.provider import READ_METHODS
from tests import test_child_transport as fixtures
from tests import test_pons_native_profile as profiles


class PonsProfileChannelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.ChildTransportTests.asyncSetUp(self)
        self.pons=replace(self.pons,alias=replace(self.pons.alias,methods=READ_METHODS&PUBLISHED_METHODS['robinhood']))
        self.http=ParentHTTP(self.budget,[self.sol,self.pons],opener=self.physical)
        self.addAsyncCleanup(self.http.aclose)

    configured=profiles.PonsNativeProfileTests.configured

    async def connected(self,exporter):
        left,right=socket.socketpair()
        reader,writer=await asyncio.open_connection(sock=left)
        channel=ParentChannel(self.http,pons_profiles=exporter)
        serving=asyncio.create_task(serve_connected(reader,writer,channel))
        port=await asyncio.to_thread(ChildChannel,right)
        async def close():
            try:await asyncio.to_thread(port.close)
            finally:await asyncio.wait_for(serving,3)
        self.addAsyncCleanup(close)
        return port,channel

    async def test_actual_protected_loaded_profile_is_fetched_once_and_registered(self):
        exporter=self.configured()
        child,parent=await self.connected(exporter)
        with patch.object(parent,'dispatch',wraps=parent.dispatch) as dispatch:
            first=await asyncio.to_thread(child.pons_profile,child.sources['pons'])
            second=await asyncio.to_thread(child.pons_profile,child.sources['pons'])
        self.assertIs(first,second)
        self.assertIs(require_profile(first,ChildRPCPort(child,'pons')),first)
        self.assertEqual(first.row(),profiles.row())
        self.assertEqual(dispatch.call_count,1)
        self.assertEqual(self.budget.snapshot()['http_attempts'],'0')
        self.assertFalse(self.physical.calls)
        body=json.dumps(first.value())
        self.assertNotIn('https://',body)
        self.assertNotIn('offline-parent-secret',body)

    async def test_unconfigured_parent_stays_unavailable_while_checked_absent_is_admitted(self):
        for exporter,status in ((None,'UNAVAILABLE'),
                (ParentPonsProfiles.configured(self.http,environ={}),'ABSENT')):
            child,parent=await self.connected(exporter)
            profile=await asyncio.to_thread(child.pons_profile,child.sources['pons'])
            self.assertEqual(profile.status,status)
            if status=='UNAVAILABLE':
                with self.assertRaises(ProfileFailure):require_profile(profile,ChildRPCPort(child,'pons'))
            else:self.assertIs(require_profile(profile,ChildRPCPort(child,'pons')),profile)
            with self.assertRaisesRegex(ChildTransportFailure,'child_pons_profile_source'):
                child.pons_profile(child.sources['pump'])

    async def test_foreign_parent_exporter_or_wire_selected_source_paths_cannot_enter(self):
        exporter=self.configured()
        other=ParentHTTP(self.budget,[self.sol,self.pons],opener=self.physical)
        self.addAsyncCleanup(other.aclose)
        with self.assertRaisesRegex(BridgeRejected,'pons_profile_parent_owner'):
            ParentChannel(other,pons_profiles=exporter)
        child,parent=await self.connected(exporter)
        with self.assertRaises(ChildTransportFailure):
            await asyncio.to_thread(child.request,'pons_profile',alias='pons',path='/private/not-read')
        self.assertFalse(self.physical.calls)


if __name__=='__main__':unittest.main()
