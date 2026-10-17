"""Protected native profile export, with real parent identity and fixed receipts."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest

from meme_machine.operational.child_transport import ChildRPCPort
from meme_machine.operational.parent_transport import ParentHTTP
from meme_machine.operational.pons_native_profile import (
    ParentPonsProfiles,ProfileFailure,parent_profile_response,profile_from_parent,require_profile,
)
from meme_machine.operational.transport_bridge import READ_METHODS as PUBLISHED_METHODS
from meme_machine.lanes.pons.provider import READ_METHODS
from tests import test_child_transport as fixtures
from tests.test_parent_native_transport import PONS


def row():
    domain=hashlib.sha256(('4663:'+PONS).encode()).hexdigest()
    return dict(chain_id=4663,provider_domain=domain,
        provider_fingerprint=hashlib.sha256(PONS.encode()).hexdigest(),methods={
            'eth_getBlockReceipts':dict(supported=True,observed_limits=dict(validated=True,
                max_response_bytes=100000,max_latency_seconds=.2,max_throughput_cu=500,max_transactions=32)),
            'eth_callMany':dict(supported=True),
            'eip1898_eth_call':dict(supported=True),'eip1898_eth_getCode':dict(supported=True),
            'native_quote_batch':dict(supported=True,observed_limits=dict(validated=True,
                max_response_bytes=25165,max_latency_seconds=.43,max_logical_elements=9,max_throughput_cu=216))})


class PonsNativeProfileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.ChildTransportTests.asyncSetUp(self)
        self.pons=replace(self.pons,alias=replace(self.pons.alias,methods=READ_METHODS&PUBLISHED_METHODS['robinhood']))
        self.http=ParentHTTP(self.budget,[self.sol,self.pons],opener=self.physical)
        self.addAsyncCleanup(self.http.aclose)
        self.channel,_=await fixtures.ChildTransportTests.connected(self)
        self.channel._pons_profiles={}
        self.port=ChildRPCPort(self.channel,'pons')

    def configured(self,value=None):
        value=row() if value is None else value
        path=self.root/'protected-capabilities.json'
        path.write_text(json.dumps(dict(endpoints={row()['provider_domain']:value})))
        path.chmod(0o600)
        return ParentPonsProfiles.configured(self.http,environ={
            'MM_RPC_CAPABILITIES':str(path),'MM_ROBINHOOD_READ_RPC_URL':PONS})

    def receive(self,profiles):
        public=parent_profile_response(profiles,self.http,self.channel.session,'pons')
        profile=profile_from_parent(self.channel,self.port.source,public)
        self.channel._pons_profiles['pons']=profile
        return profile

    async def test_actual_protected_profile_is_detached_source_session_bound_and_secretfree(self):
        profiles=self.configured()
        profile=self.receive(profiles)
        self.assertIs(require_profile(profile,self.port),profile)
        self.assertEqual(profile.status,'LOADED')
        self.assertEqual(profile.row(),row())
        public=profile.value()
        self.assertNotIn('offline-parent-secret',json.dumps(public))
        self.assertNotIn('https://',json.dumps(public))
        original=deepcopy(public)
        public['methods'].clear()
        self.assertEqual(profile.value(),original)
        with self.assertRaises(AttributeError):profile.status='ABSENT'
        self.assertFalse(self.physical.calls)

    async def test_absence_is_checked_and_cannot_be_confused_with_missing_parent_exporter(self):
        profiles=ParentPonsProfiles.configured(self.http,environ={})
        profile=self.receive(profiles)
        self.assertEqual(profile.status,'ABSENT')
        self.assertEqual(profile.row()['methods'],{})
        self.assertIs(require_profile(profile,self.port),profile)
        unavailable=self.receive(None)
        self.assertEqual(unavailable.status,'UNAVAILABLE')
        with self.assertRaises(ProfileFailure):require_profile(unavailable,self.port)

    async def test_foreign_file_endpoint_chain_domain_and_unsafe_paths_are_rejected(self):
        for field,value in [('chain_id',1),('provider_domain','f'*64),('provider_fingerprint','e'*64)]:
            changed=row();changed[field]=value
            with self.subTest(field=field),self.assertRaises(ProfileFailure):self.configured(changed)
        path=self.root/'protected-capabilities.json'
        self.configured();path.chmod(0o666)
        with self.assertRaises(ProfileFailure):
            ParentPonsProfiles.configured(self.http,environ={
                'MM_RPC_CAPABILITIES':str(path),'MM_ROBINHOOD_READ_RPC_URL':PONS})

    async def test_parent_profile_cannot_expand_an_alias_or_use_another_parent(self):
        self.pons=replace(self.pons,alias=replace(self.pons.alias,methods=frozenset({'eth_chainId'})))
        other=ParentHTTP(self.budget,[self.pons],opener=self.physical)
        self.addAsyncCleanup(other.aclose)
        path=self.root/'protected-capabilities.json';self.configured()
        with self.assertRaisesRegex(ProfileFailure,'method_not_granted'):
            ParentPonsProfiles.configured(other,environ={
                'MM_RPC_CAPABILITIES':str(path),'MM_ROBINHOOD_READ_RPC_URL':PONS})
        profiles=self.configured()
        with self.assertRaises(ProfileFailure):parent_profile_response(profiles,other,self.channel.session,'pons')
        with self.assertRaises(ProfileFailure):parent_profile_response(profiles,self.http,self.channel.session,'pump')

    async def test_unknown_profile_metadata_is_removed_and_bad_hints_do_not_gain_support(self):
        value=row();value['methods']['send_transaction']=dict(supported=True)
        value['methods']['eth_callMany']['parity_verified']=True
        value['methods']['native_quote_batch']['observed_limits']['private_url']=PONS
        value['methods']['eth_getBlockReceipts']['observed_limits']['max_latency_seconds']='secret'
        profile=self.receive(self.configured(value))
        self.assertNotIn('send_transaction',profile.row()['methods'])
        self.assertNotIn('parity_verified',profile.row()['methods']['eth_callMany'])
        self.assertNotIn('private_url',profile.row()['methods']['native_quote_batch']['observed_limits'])
        self.assertNotIn('observed_limits',profile.row()['methods']['eth_getBlockReceipts'])

    async def test_child_refuses_foreign_sessions_sources_and_unbounded_or_extra_fields(self):
        public=parent_profile_response(self.configured(),self.http,self.channel.session,'pons')
        changes=[dict(session='x'*43),dict(schema='unknown'),dict(command='anything'),
            dict(source=dict(public['source'],endpoint_identity='f'*64)),
            dict(methods=dict(eth_sendRawTransaction=dict(supported=True)))]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):
                profile_from_parent(self.channel,self.port.source,dict(public,**change))
        profile=self.receive(self.configured())
        self.channel._pons_profiles.clear()
        with self.assertRaises(ProfileFailure):require_profile(profile,self.port)


if __name__=='__main__':unittest.main()
