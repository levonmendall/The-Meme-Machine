from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from operational.shared_acquisition_parity import account_union_plan,partition_snapshot,ordered_canonical_events,adaptive_receipt_plan
from meme_machine.lanes.pons import CHAIN_ID
from meme_machine.lanes.pons.immutable_rpc import EvidenceStore,Reuse
from meme_machine.lanes.pons.provider_topology import PacedRpc
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime.survivor_history import History
from meme_machine.lanes.pump.postgrad import PostGraduationAdapter,sell_quote
from tests.lanes.pump.test_postgrad_read_efficiency import MeteredRPC,MINT


class SharedPreparationTests(unittest.TestCase):
    def test_pons_cross_consumer_receipts_reuse_existing_native_store_by_block(self):
        capture=json.loads((Path(__file__).parent/'lanes/pons/fixtures/pons_lineage_35378762520.json').read_text())
        event=capture['v2']['graduation'];tx=event['transactionHash'];block=event['blockHash'];purchases=[]
        receipt=dict(transactionHash=tx,blockHash=block,logs=[event])
        def transport(method,params):
            purchases.append((method,params))
            if method=='eth_chainId':return hex(CHAIN_ID)
            return deepcopy(receipt)
        store=EvidenceStore()
        current=PacedRpc('https://fixture.invalid/key',role='test',requests_per_second=2,transport=transport)
        survivor=PacedRpc('https://fixture.invalid/key',role='test',requests_per_second=2,transport=transport)
        for rpc in (current,survivor):rpc.evidence_reuse=Reuse('https://fixture.invalid/key',store,'pons');rpc.verify_chain()
        a=current.receipt(tx,block,scope='current');b=survivor.receipt(tx,block,scope='survivor')
        self.assertEqual(a,b);self.assertEqual(sum(m=='eth_getTransactionReceipt' for m,_ in purchases),1)
        # A reorg/provider change is a different acquisition, never a shared fact.
        other=Reuse('https://fixture.invalid/other',store,'pons')
        self.assertFalse(other.lookup('eth_getTransactionReceipt',[tx],receipts={tx:block})[0])
        self.assertFalse(survivor.evidence_reuse.lookup('eth_getTransactionReceipt',[tx],receipts={tx:'changed'})[0])

    def test_captured_pons_common_history_has_independent_durable_cursors(self):
        capture=json.loads((Path(__file__).parent/'lanes/pons/fixtures/pons_lineage_35378762520.json').read_text())
        events=sorted([capture['v2'][k] for k in ('graduation','registration','initialization')],
            key=lambda e:tuple(int(e[k],16) for k in ('blockNumber','transactionIndex','logIndex')))
        ordered=ordered_canonical_events(events)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);shared=CandidateHistory(root/'shared',clock=lambda:1000)
            current=History(root/'current',policy='current');survivor=History(root/'survivor',policy='survivor')
            try:
                shared.observe('pons','captured-pool',surface='v4',observed_at=1000)
                for e in ordered:
                    shared.append_event('pons','captured-pool',identity=e['transactionHash']+':'+e['logIndex'],
                        slot=int(e['blockNumber'],16),transaction_index=int(e['transactionIndex'],16),event_index=int(e['logIndex'],16),
                        market_time=1000,kind='native_event',payload=e)
                baseline=list(ordered)
                self.assertEqual([r['payload'] for r in shared.events('pons','captured-pool')],baseline)
                current.set_meta('canonical_cursor',1);survivor.set_meta('canonical_cursor',3)
                current.close();current=History(root/'current',policy='current')
                self.assertEqual(current.get_meta('canonical_cursor'),1);self.assertEqual(survivor.get_meta('canonical_cursor'),3)
                self.assertEqual([r['payload'] for r in shared.events('pons','captured-pool')],baseline)
            finally:shared.close();current.close();survivor.close()
        with self.assertRaisesRegex(ValueError,'publication_order'):ordered_canonical_events(list(reversed(events)))
        with self.assertRaisesRegex(ValueError,'duplicate'):ordered_canonical_events([events[0],events[0]])

    def test_adaptive_receipts_require_authenticated_same_source_capability_and_deadline(self):
        identity=dict(provider_fingerprint='fixture',chain_id=CHAIN_ID,source_generation='captured',block_hash='block')
        capability=dict(identity,authenticated=True,eth_getBlockReceipts=True)
        self.assertEqual(adaptive_receipt_plan(25,40,identity=identity,capability=capability,remaining_seconds=2),'block_receipts')
        for cap,slack in ((None,2),(dict(capability,chain_id=1),2),(dict(capability,block_hash='other'),2),(capability,.9)):
            self.assertEqual(adaptive_receipt_plan(25,40,identity=identity,capability=cap,remaining_seconds=slack),'individual_receipts')
        self.assertEqual(adaptive_receipt_plan(1,100,identity=identity,capability=capability,remaining_seconds=2),'individual_receipts')

    def test_pump_union_views_repeat_every_native_validation_and_executable_quote(self):
        rpc=MeteredRPC();adapter=PostGraduationAdapter(rpc,scan_rpc=object())
        baseline=adapter.pumpswap_snapshot(MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        keys=[rpc.pool,MINT,rpc.base_key,rpc.quote_key,rpc.fee_key,rpc.curve_key]
        original=rpc.call('getMultipleAccounts',[keys,{}])
        metadata=dict(provider_fingerprint='fixture',source_generation='captured',commitment='finalized',slot=1001,available_at=101,deadline=106)
        plan=account_union_plan({k:dict(metadata,accounts=keys) for k in ('current','survivor')})
        self.assertEqual(len(plan['accounts']),6);views=partition_snapshot(plan,original,now=101)
        for consumer,quantity in (('current',10**9),('survivor',2*10**9)):
            class PartitionRPC(MeteredRPC):
                def call(self,method,params=None,priority=False):
                    if method=='getMultipleAccounts' and params[0]==keys:return deepcopy(views[consumer])
                    return super().call(method,params,priority)
            partition=PostGraduationAdapter(PartitionRPC(),scan_rpc=object()).pumpswap_snapshot(
                MINT,101,reuse_verified_pool=True,held_curve_inline=True)
            self.assertEqual(partition['state'],baseline['state']);self.assertEqual(partition['creator'],baseline['creator'])
            self.assertEqual(sell_quote(partition,quantity),sell_quote(baseline,quantity))
        views['current']['value'][0]['owner']='bad'
        self.assertEqual(views['survivor']['value'][0]['owner'],original['value'][0]['owner'])

    def test_union_scope_context_deadline_and_incomplete_data_preserve_complete_fallback(self):
        metadata=dict(provider_fingerprint='fixture',source_generation='captured',commitment='finalized',slot=10,available_at=100,deadline=105)
        views=dict(a=dict(metadata,accounts=['a','shared']),b=dict(metadata,accounts=['b','shared']))
        plan=account_union_plan(views);self.assertEqual(plan['accounts'],('a','shared','b'))
        for field in ('provider_fingerprint','source_generation','slot','deadline'):
            changed=deepcopy(views);changed['b'][field]='changed';self.assertIsNone(account_union_plan(changed))
        complete=dict(context=dict(slot=10),value=[{}, {}, {}])
        for response,now in ((dict(complete,value=[{},{}]),101),(dict(complete,value=[None,{},{}]),101),
                             (dict(complete,context=dict(slot=11)),101),(complete,106)):
            with self.assertRaisesRegex(ValueError,'original_fallback'):partition_snapshot(plan,response,now=now)
        # No account union plan contains or substitutes concentration research.
        self.assertNotIn('concentration',plan)
