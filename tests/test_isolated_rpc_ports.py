"""Actual native RPC/cache contracts over offline, really metered parent IPC."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from meme_machine.operational.child_transport import ChildRPCPort, ChildTransportFailure
from meme_machine.operational.parent_transport import ParentHTTP
from tests import test_child_transport as child_fixtures
from tests import test_parent_native_transport as fixtures


class IsolatedRpcPortTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.ParentNativeTransportTests.asyncSetUp(self)
        self.sol=replace(self.sol,alias=replace(self.sol.alias,methods=frozenset((
            'getGenesisHash','getBlockTime','getMultipleAccounts','getTransaction'))))
        self.pons=replace(self.pons,alias=replace(self.pons.alias,methods=frozenset((
            'eth_chainId','eth_blockNumber','eth_getBlockByHash'))))
        physical=self.physical
        def provider(request,timeout):
            calls=json.loads(request.data)
            rows=calls if isinstance(calls,list) else [calls]
            def result(call):
                method=call['method']
                if method=='getGenesisHash':
                    from meme_machine.solana_provider_config import GENESIS
                    return GENESIS
                if method=='getBlockTime':return 1730000000+call['params'][0]
                if method=='eth_chainId':return hex(4663)
                if method=='eth_getBlockByHash':return dict(hash=call['params'][0],number='0x1')
                return '0x123'
            reply=[dict(jsonrpc='2.0',id=c['id'],result=result(c)) for c in rows]
            physical.body=json.dumps(reply if isinstance(calls,list) else reply[0]).encode()
            return physical(request,timeout)
        self.http=ParentHTTP(self.budget,[self.sol,self.pons],opener=provider)
        self.addAsyncCleanup(self.http.aclose)

    connected=child_fixtures.ChildTransportTests.connected

    def pump(self,port):
        from meme_machine.lanes.pump.solana_immutable_rpc import ImmutableReads
        from meme_machine.lanes.pump.solana_evidence_broker import EvidenceBroker
        from meme_machine.lanes.pump.solana_read_rpc import new_rpc
        path=self.root/'isolated-sol-cache.sqlite'
        reads=ImmutableReads(path,endpoint_identity=port.source.endpoint_identity)
        broker=EvidenceBroker(path)
        self.addCleanup(broker.db.close)
        return new_rpc(parent_port=port,shared_reads=reads,evidence_broker=broker,
            sleeper=lambda _:None)

    def store(self):
        from meme_machine.lanes.pons.immutable_rpc import EvidenceStore
        store=EvidenceStore(self.root/'isolated-pons-cache.sqlite')
        self.addCleanup(store.db.close)
        return store

    async def test_real_pump_rpc_no_url_or_child_governor_and_durable_genesis_reuse(self):
        from meme_machine.lanes.pump import solana_read_rpc
        client,_=await self.connected()
        port=ChildRPCPort(client,'pump')
        with patch.dict(os.environ,{'MM_PROVIDER_GOVERNOR_DB':'/forbidden/governor',
                'MM_SOLANA_EVIDENCE_BROKER_DB':'/forbidden/broker',
                'MM_SOLANA_EVIDENCE_PLANE_DB':'/forbidden/plane'}), \
             patch.object(solana_read_rpc,'primary_rpc_url',side_effect=AssertionError('URL resolution')), \
             patch('meme_machine.runtime.governor.Governor',side_effect=AssertionError('child governor')):
            rpc=self.pump(port)
            first=await asyncio.to_thread(rpc.call,'getGenesisHash',[])
            rpc.cache.clear();rpc.cache_bytes=0
            second=await asyncio.to_thread(rpc.call,'getGenesisHash',[])
        self.assertEqual(first,second)
        self.assertIs(rpc.url,port.source)
        self.assertEqual(len(self.physical.calls),1)
        self.assertEqual(sum(row.get('consumer_method:getGenesisHash',0)
            for row in self.http.purchases.snapshot()['operations']),2)
        with sqlite3.connect(self.root/'isolated-sol-cache.sqlite') as db:
            self.assertEqual(db.execute('SELECT endpoint FROM solana_immutable_reads').fetchone()[0],
                port.source.endpoint_identity)

    async def test_real_pump_native_call_many_preserves_one_physical_batch(self):
        client,_=await self.connected()
        rpc=self.pump(ChildRPCPort(client,'pump'))
        rpc._parent_reads.finalized(1000)
        values=await asyncio.to_thread(rpc.call_many,'getBlockTime',[[10],[11]],batch_size=8)
        self.assertEqual(values,[1730000010,1730000011])
        self.assertEqual(len(self.physical.calls),1)
        self.assertIsInstance(self.physical.calls[0],list)
        self.assertEqual(self.budget.snapshot()['rpc_elements'],'2')
        self.assertEqual(sum(row.get('consumer_method:getBlockTime',0)
            for row in self.http.purchases.snapshot()['operations']),2)
        repeated=await asyncio.to_thread(rpc.call_many,'getBlockTime',[[10],[11]],batch_size=8)
        self.assertEqual(repeated,values)
        self.assertEqual(len(self.physical.calls),1)
        self.assertEqual(sum(row.get('consumer_method:getBlockTime',0)
            for row in self.http.purchases.snapshot()['operations']),4)

    async def test_parent_port_requires_owned_source_and_explicit_native_cache(self):
        from meme_machine.lanes.pump.solana_read_rpc import new_rpc
        from meme_machine.lanes.pons.provider_topology import configured_rpc
        from meme_machine.lanes.pump.provider import RPC,Unavailable
        client,_=await self.connected()
        sol=ChildRPCPort(client,'pump');pons=ChildRPCPort(client,'pons')
        with self.assertRaises(Unavailable):new_rpc(parent_port=sol)
        with self.assertRaises(ValueError):RPC('https://invented.invalid',parent_port=sol)
        with self.assertRaises(ChildTransportFailure):new_rpc(parent_port=pons)
        with self.assertRaises(Exception):configured_rpc(parent_port=pons)
        self.assertFalse(self.physical.calls)

    async def test_real_pons_cache_hit_preserves_parent_logical_demand_and_chain_guard(self):
        from meme_machine.lanes.pons import provider_topology
        client,_=await self.connected()
        port=ChildRPCPort(client,'pons')
        with patch.object(provider_topology,'primary_endpoint',side_effect=AssertionError('URL resolution')), \
             patch('meme_machine.lanes.pons.provider_admission.configured',side_effect=AssertionError('child admission')), \
             patch('meme_machine.runtime.robinhood.provider_authority.paths',side_effect=AssertionError('shared state')):
            rpc=provider_topology.configured_rpc(parent_port=port,immutable_store=self.store(),retries=0)
            self.assertFalse(rpc.chain_verified)
            first=await asyncio.to_thread(rpc.call,'eth_getBlockByHash',['0xabc',False])
            second=await asyncio.to_thread(rpc.call,'eth_getBlockByHash',['0xabc',False])
            telemetry=rpc.telemetry()
        self.assertEqual(first,second)
        self.assertTrue(rpc.chain_verified)
        self.assertIs(rpc._endpoint,port.source)
        self.assertEqual(len(self.physical.calls),2) # earned chain identity + one header
        self.assertTrue(telemetry['shared_provider']['controlled_by_parent'])
        with sqlite3.connect(self.admission.path) as db:
            demand=dict(db.execute('SELECT method,n FROM logical_demand'))
        self.assertEqual(demand['eth_getBlockByHash'],2)
        self.assertEqual(demand['eth_chainId'],1)
        self.assertEqual(await asyncio.to_thread(rpc.shared_admission.activity_marker),
            self.admission.activity_marker())

    async def test_real_pons_batch_keeps_single_wire_request_and_existing_decoding(self):
        from meme_machine.lanes.pons.provider_topology import configured_rpc
        client,_=await self.connected()
        rpc=configured_rpc(parent_port=ChildRPCPort(client,'pons'),immutable_store=self.store(),retries=0)
        # Original explicit chain proof precedes a canonical nonidentity request.
        await asyncio.to_thread(rpc.verify_chain)
        before=len(self.physical.calls)
        values=await asyncio.to_thread(rpc.batch,[('eth_blockNumber',[]),('eth_blockNumber',[])])
        self.assertEqual(values,['0x123','0x123'])
        self.assertEqual(len(self.physical.calls)-before,1)
        self.assertIsInstance(self.physical.calls[-1],list)
        self.assertEqual(len(self.physical.calls[-1]),2)

    async def test_selective_context_rotates_actual_proxy_rpc_and_keeps_native_cache(self):
        from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
        client,_=await self.connected()
        port=ChildRPCPort(client,'pons')
        ctx=SelectiveEvidenceContext(None,parent_port=port,immutable_store=self.store())
        values=await asyncio.to_thread(ctx.batch,[('eth_getBlockByHash',['0xabc',False])],'pons_selective')
        self.assertEqual(values,[dict(hash='0xabc',number='0x1')])
        self.assertTrue(ctx.rpc.chain_verified)
        self.assertIs(ctx.rpc.parent_port,port)
        old=ctx.rpc
        ctx.rpc.used=200
        await asyncio.to_thread(ctx.acquire)
        self.assertIsNot(ctx.rpc,old)
        self.assertIs(ctx.rpc.parent_port,port)
        self.assertTrue(ctx.rpc.chain_verified)
        self.assertEqual(len(ctx.completed_sessions),1)
