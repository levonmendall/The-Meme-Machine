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

    def native_context(self,profile):
        from meme_machine.lanes.pons.immutable_rpc import EvidenceStore
        from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
        store=EvidenceStore(self.root/'profile-native-cache.sqlite')
        self.addCleanup(store.db.close)
        return SelectiveEvidenceContext(None,parent_port=self.port,
            immutable_store=store,native_profile=profile)

    async def test_real_native_callmany_batch_keeps_independent_first_parity_and_disabled_shape(self):
        import asyncio
        from meme_machine.lanes.pons.abi import calldata
        profile=self.receive(self.configured())
        context=self.native_context(profile)
        def word(data):return '0x'+data[2:10].ljust(64,'0')
        physical=self.physical
        def provider(request,timeout):
            calls=json.loads(request.data)
            rows=calls if type(calls) is list else [calls]
            def value(call):
                if call['method']=='eth_chainId':return hex(4663)
                if call['method']=='eth_callMany':
                    txs=call['params'][0][0]['transactions']
                    return [[dict(value=word(tx['input'])) for tx in txs]]
                return word(call['params'][0]['data'])
            reply=[dict(jsonrpc='2.0',id=call['id'],result=value(call)) for call in rows]
            physical.body=json.dumps(reply if type(calls) is list else reply[0]).encode()
            return physical(request,timeout)
        self.http.opener=provider
        target='0x'+'1'*40
        calls=[('eth_call',[dict(to=target,data=calldata(name)),'0xa']) for name in ('token()','getReserves()')]
        self.assertNotIn('parity_verified',context.view_batch_state)
        actual=await asyncio.to_thread(context.batch,calls,'pons_natural')
        self.assertEqual(actual,[word(call[1][0]['data']) for call in calls])
        self.assertTrue(context.view_batch_state['parity_verified'])
        batches=[call for call in physical.calls if type(call) is list]
        self.assertEqual([[row['method'] for row in batch] for batch in batches],
            [['eth_callMany','eth_call','eth_call']])
        value=row()
        for method in value['methods'].values():method['supported']=False
        disabled=self.native_context(self.receive(self.configured(value)))
        self.assertFalse(disabled.view_batch_state['supported'])
        self.assertEqual(await asyncio.to_thread(disabled.batch,calls,'pons_natural'),actual)
        self.assertEqual([row['method'] for row in physical.calls[-1]],['eth_call','eth_call'])
        self.assertIsNone(disabled.rpc.shared_quote_resources)
        self.assertEqual(disabled.rpc.hash_state_supported,set())

    async def test_real_native_dense_selector_uses_only_complete_bound_block_receipts(self):
        import asyncio,time
        profile=self.receive(self.configured())
        context=self.native_context(profile);context.deadline=time.monotonic()+10
        bh='0x'+'a'*64;txs=['0x'+format(i,'064x') for i in range(25)]
        header=dict(hash=bh,number='0xa',transactions=txs)
        receipts=[dict(transactionHash=tx,transactionIndex=hex(i),blockHash=bh,
            blockNumber='0xa',status='0x1',logs=[],**{'from':'0x'+'1'*40}) for i,tx in enumerate(txs)]
        physical=self.physical
        def provider(request,timeout):
            calls=json.loads(request.data);rows=calls if type(calls) is list else [calls]
            reply=[dict(jsonrpc='2.0',id=c['id'],result=hex(4663) if c['method']=='eth_chainId'
                else receipts) for c in rows]
            physical.body=json.dumps(reply if type(calls) is list else reply[0]).encode()
            return physical(request,timeout)
        self.http.opener=provider
        actual=await asyncio.to_thread(context.acquire_dense_receipts,[(tx,bh) for tx in txs],
            headers={bh:header},scope='pons_selective_v4')
        self.assertEqual(set(actual),{(tx,bh) for tx in txs})
        self.assertEqual(context.receipt_acquisition_counts['selected_block_receipts'],1)
        calls=[r for body in physical.calls for r in (body if type(body) is list else [body])]
        self.assertEqual([r['method'] for r in calls],['eth_chainId','eth_getBlockReceipts'])
        self.assertEqual(calls[-1]['params'],[bh])
        # The unchanged native selector refuses a block without a complete size
        # witness; a support receipt cannot make a missing header canonical.
        self.assertEqual(await asyncio.to_thread(context.acquire_dense_receipts,
            [(tx,bh) for tx in txs],headers={},scope='pons_selective_v4'),{})

    async def test_real_native_rpc_hash_pins_and_original_shared_quote_resources(self):
        import asyncio
        profile=self.receive(self.configured())
        context=self.native_context(profile)
        physical=self.physical
        def provider(request,timeout):
            calls=json.loads(request.data);rows=calls if type(calls) is list else [calls]
            reply=[dict(jsonrpc='2.0',id=c['id'],result=hex(4663) if c['method']=='eth_chainId'
                else '0x'+'0'*64) for c in rows]
            physical.body=json.dumps(reply if type(calls) is list else reply[0]).encode()
            return physical(request,timeout)
        self.http.opener=provider
        rpc=await asyncio.to_thread(context.acquire,1,'pons_natural')
        expected=dict(row()['methods']['native_quote_batch']['observed_limits'],
            provider_fingerprint=self.port.source.endpoint_identity)
        self.assertEqual(rpc.shared_quote_resources,expected)
        self.assertEqual(rpc.hash_state_supported,{'eth_call','eth_getCode'})
        bh='0x'+'b'*64;rpc.evidence_pins={'0xa':bh}
        call=('eth_call',[dict(to='0x'+'1'*40,data='0x12345678'),'0xa'])
        first=await asyncio.to_thread(rpc.batch,[call],scope='pons_natural')
        second=await asyncio.to_thread(rpc.batch,[call],scope='pons_natural')
        self.assertEqual(first,second)
        self.assertEqual(physical.calls[-1][0]['params'][-1],dict(blockHash=bh))
        self.assertIsNone(getattr(rpc,'last_canonical_read',None))
        self.assertEqual(len(physical.calls),2) # Genuinechainauth+onehash-boundphysicalread.


if __name__=='__main__':unittest.main()
