import copy
import json
from pathlib import Path
import unittest
from robinhood_research import BoundaryError
from robinhood_research.abi import topic
from robinhood_research.ramses import *


class NativeRamsesTests(unittest.TestCase):
    def setUp(self):
        self.capture=json.loads((Path(__file__).parent/'fixtures/ramses_capture_35370768683.json').read_text())

    def test_captured_60_second_terminal_equality(self):
        result=replay(self.capture)
        self.assertEqual(result['events'],10)
        self.assertEqual(result['transactions'],8)
        self.assertEqual(result['seconds'],60)
        self.assertTrue(result['terminal_equality'])
        self.assertIsNone(result['after_cost_return'])
        self.assertFalse(result['prospective_range'])

    def test_clone_identity_and_implementation(self):
        auth=authenticate_pool(self.capture['pool_code'],factory_member=True)
        self.assertEqual(auth['bin_step'],10)
        for code,member in [(self.capture['pool_code'],False),('0x00'+self.capture['pool_code'][4:],True)]:
            with self.assertRaises(BoundaryError):authenticate_pool(code,factory_member=member)

    def test_terminal_disagreement_not_patched(self):
        terminal=self.capture['states'][str(max(map(int,self.capture['states'])))]
        terminal['values']['getActiveId()']='0x'+f'{8367474:064x}'
        with self.assertRaisesRegex(BoundaryError,'terminal_state'):
            replay(self.capture)

    def test_duplicate_idempotent_and_missing_receipt_event(self):
        self.capture['logs'].append(copy.deepcopy(self.capture['logs'][0]))
        self.assertEqual(replay(self.capture)['events'],10)
        self.capture['logs']=self.capture['logs'][1:-1]
        with self.assertRaisesRegex(BoundaryError,'receipt_events'):
            replay(self.capture)

    def test_removed_log_is_reorg_boundary(self):
        event=self.capture['logs'][0];event['removed']=True
        for receipt in self.capture['receipts']:
            for e in receipt['logs']:
                if e['transactionHash']==event['transactionHash'] and e['logIndex']==event['logIndex']:e['removed']=True
        with self.assertRaisesRegex(BoundaryError,'removed_log'):
            replay(self.capture)

    def test_unsupported_mutation_cannot_bridge_terminal(self):
        event=self.capture['logs'][0]
        event['topics']=[topic('HooksParametersSet(address,bytes32)'),event['topics'][1]]
        event['data']='0x'+f'{1:064x}'
        for receipt in self.capture['receipts']:
            for i,e in enumerate(receipt['logs']):
                if e['transactionHash']==event['transactionHash'] and e['logIndex']==event['logIndex']:receipt['logs'][i]=copy.deepcopy(event)
        with self.assertRaisesRegex(BoundaryError,'unsupported_ramses_mutation'):
            replay(self.capture)

    def test_price_anchor_and_direction(self):
        self.assertEqual(price(1<<23,10),Q)
        self.assertGreater(price((1<<23)+1,10),Q)
        self.assertLess(price((1<<23)-1,10),Q)
        with self.assertRaises(BoundaryError):price(0,10)

    def test_fee_base_dynamic_and_protocol_split(self):
        static=[40000,30,600,5000,40000,500,350000]
        self.assertEqual(total_fee(static,0,10),4*10**15)
        self.assertEqual(total_fee(static,10000,10),4*10**15+4*10**12)
        q=swap_bin([1000000,1000000],bin_id=1<<23,step=10,gross_input=10000,for_y=True,fee_rate=10**16,protocol_share=500)
        self.assertEqual((q['total_fee'],q['protocol_fee'],q['lp_fee']),(100,5,95))
        self.assertEqual(q['after'],[1009995,990100])

    def test_full_and_partial_bin_traversal(self):
        a=swap_bin([0,100],bin_id=1<<23,step=1,gross_input=1000,for_y=True,fee_rate=0,protocol_share=0)
        self.assertEqual(a['after'],[100,0]);self.assertEqual(a['gross_input'],100)
        b=swap_bin([100,0],bin_id=1<<23,step=1,gross_input=50,for_y=False,fee_rate=0,protocol_share=0)
        self.assertEqual(b['after'],[50,50])

    def test_variable_fee_decay_reference(self):
        static=[40000,30,600,5000,40000,500,350000]
        self.assertEqual(update_volatility(static,[20000,10000,100,100],previous_active=101,active=102,timestamp=140),[20000,10000,101,140])
        self.assertEqual(update_volatility(static,[20000,10000,100,100],previous_active=101,active=101,timestamp=800),[0,0,101,800])

    def test_source_native_share_mint_and_burn(self):
        shares,effective=mint_shares([0,1000],1000,[0,100],bin_id=(1<<23)-1,step=10,active_id=1<<23)
        self.assertEqual(shares,100);self.assertEqual(effective,[0,100])
        self.assertEqual(burn_amounts([0,1100],1100,100),[0,100])
        with self.assertRaisesRegex(BoundaryError,'wrong_side'):
            mint_shares([0,1000],1000,[1,0],bin_id=(1<<23)-1,step=10,active_id=1<<23)

    def test_untouched_shares_and_compounded_fees(self):
        reserves=[100000,100000];before=list(reserves)
        self.assertEqual(burn_amounts(reserves,1000,100),[10000,10000])
        self.assertEqual(reserves,before)
        after=swap_bin(reserves,bin_id=1<<23,step=10,gross_input=10000,for_y=True,fee_rate=10**16,protocol_share=500)['after']
        self.assertEqual(burn_amounts(after,1000,100),[10999,9010])


    def _range_prestate(self):
        active=1<<23
        static=[40000,30,600,5000,40000,500,350000]
        variable=[0,0,active,1000]
        bins={}
        for bid in range(active-3,active+4):
            if bid<active: reserves=[0,10**18]
            elif bid>active: reserves=[10**18,0]
            else: reserves=[10**18,10**18]
            bins[bid]=dict(reserves=reserves,supply=10**18)
        return dict(active=active,step=10,reserves=[4*10**18,4*10**18],protocol=[0,0],
                    static=static,variable=variable,bins=bins)

    def test_active_bin_composition_fee_and_protocol_conservation(self):
        s=self._range_prestate();a=s['active']
        effect=mint_effect(s['bins'][a]['reserves'],s['bins'][a]['supply'],[10**17,0],
            bin_id=a,step=s['step'],active_id=a,static=s['static'],variable=s['variable'],timestamp=1040)
        self.assertGreater(effect['composition_fees'][0],0)
        self.assertEqual(effect['protocol_fees'][0],effect['composition_fees'][0]*500//10000)
        self.assertEqual(effect['deposited'][0]+effect['protocol_fees'][0],effect['amounts_in'][0])

    def test_add_liquidity_share_mint_exact(self):
        s=self._range_prestate();bid=s['active']-1;b=s['bins'][bid]
        effect=mint_effect(b['reserves'],b['supply'],[0,10**16],bin_id=bid,step=s['step'],
            active_id=s['active'],static=s['static'],variable=s['variable'],timestamp=1040)
        shares,effective=mint_shares(b['reserves'],b['supply'],[0,10**16],bin_id=bid,step=s['step'],active_id=s['active'])
        self.assertEqual((effect['shares'],effect['amounts_in']),(shares,effective))
        self.assertEqual(effect['composition_fees'],[0,0])

    def test_remove_liquidity_share_burn_exact(self):
        self.assertEqual(burn_amounts([10**18,2*10**18],10**18,10**17),[10**17,2*10**17])

    def test_dynamic_transfer_batch_event_decoder(self):
        abi=load('ramses_pool_implementation')['abi']
        sig='TransferBatch(address,address,address,uint256[],uint256[])'
        addr=lambda n:'0x'+f'{n:064x}'
        head=f'{64:064x}{160:064x}'
        arr1=f'{2:064x}{7:064x}{8:064x}'
        arr2=f'{2:064x}{11:064x}{12:064x}'
        event=dict(topics=[topic(sig),addr(1),addr(2),addr(3)],data='0x'+head+arr1+arr2)
        d=decode_ramses_event(abi,event)
        self.assertEqual(d['args']['ids'],[7,8])
        self.assertEqual(d['args']['amounts'],[11,12])

    def test_dynamic_deposit_event_decoder(self):
        abi=load('ramses_pool_implementation')['abi']
        sig='DepositedToBins(address,address,uint256[],bytes32[])'
        addr=lambda n:'0x'+f'{n:064x}'
        head=f'{64:064x}{160:064x}'
        arr1=f'{2:064x}{7:064x}{8:064x}'
        arr2=f'{2:064x}{pack([1,2]):064x}{pack([3,4]):064x}'
        event=dict(topics=[topic(sig),addr(1),addr(2)],data='0x'+head+arr1+arr2)
        d=decode_ramses_event(abi,event)
        self.assertEqual([unpack(x) for x in d['args']['amounts']],[[1,2],[3,4]])

    def test_frozen_ranges_share_identical_prestate(self):
        s=self._range_prestate();freeze=freeze_proposals(s,10**15,quote_side='y',entry_timestamp=1040)
        self.assertEqual([p['name'] for p in freeze['proposals']],['narrow','medium','wide'])
        self.assertTrue(freeze['frozen']);self.assertFalse(freeze['allocation_authority'])
        active=s['active']
        for p in freeze['proposals']:
            self.assertEqual(p['active_bin'],active)
            for a in p['allocations']:
                self.assertEqual(a['pre_reserves'],s['bins'][a['bin_id']]['reserves'])

    def test_frozen_range_hash_rejects_hindsight_edit(self):
        freeze=freeze_proposals(self._range_prestate(),10**15,quote_side='y',entry_timestamp=1040)
        verify_proposal_hash(freeze)
        freeze['proposals'][0]['bins'][0]-=1
        with self.assertRaisesRegex(BoundaryError,'frozen_range_modified'):
            verify_proposal_hash(freeze)

    def test_exact_paper_share_ownership(self):
        freeze=freeze_proposals(self._range_prestate(),10**15,quote_side='y',entry_timestamp=1040)
        pos=paper_position(freeze,0)
        self.assertEqual(pos['proposal_hash'],freeze['proposal_hash'])
        self.assertEqual(pos['owned_shares'],{str(a['bin_id']):a['shares'] for a in freeze['proposals'][0]['allocations']})
        self.assertFalse(pos['allocation_authority'])

    def test_untouched_range_removal(self):
        s=self._range_prestate();freeze=freeze_proposals(s,10**15,quote_side='y',entry_timestamp=1040)
        pos=paper_position(freeze,0);rem=paper_removal(pos,s)
        self.assertTrue(rem['amounts'][0] or rem['amounts'][1])
        self.assertEqual(set(rem['by_bin']),set(map(str,freeze['proposals'][0]['bins'])))

    def test_partially_touched_range_changes_inventory(self):
        s=self._range_prestate();freeze=freeze_proposals(s,10**15,quote_side='y',entry_timestamp=1040);pos=paper_position(freeze,0)
        terminal=copy.deepcopy(s);bid=s['active'];terminal['bins'][bid]['reserves'][0]+=10**17;terminal['bins'][bid]['reserves'][1]-=10**17
        self.assertNotEqual(paper_removal(pos,terminal),paper_removal(pos,s))

    def test_fully_traversed_range_remains_settleable(self):
        s=self._range_prestate();freeze=freeze_proposals(s,10**15,quote_side='y',entry_timestamp=1040);pos=paper_position(freeze,0)
        terminal=copy.deepcopy(s)
        for bid in freeze['proposals'][0]['bins']:
            b=terminal['bins'][bid]
            if bid<=s['active']: b['reserves']=[b['reserves'][0]+b['reserves'][1],0]
            else: b['reserves']=[0,b['reserves'][0]+b['reserves'][1]]
        self.assertTrue(any(paper_removal(pos,terminal)['amounts']))

    def test_unavailable_unwind_preserves_unresolved_inventory(self):
        s=self._range_prestate();pos=paper_position(freeze_proposals(s,10**15,quote_side='y',entry_timestamp=1040),0)
        out=paper_outcome(pos,s,costs={'remove_gas':0})
        self.assertIsNone(out['after_cost_result']);self.assertEqual(out['unresolved_inventory'],'unwind_liquidity_unavailable')

    def test_executable_unwind_and_after_cost_calculation(self):
        s=self._range_prestate();pos=paper_position(freeze_proposals(s,10**15,quote_side='y',entry_timestamp=1040),0)
        removal=paper_removal(pos,s)['amounts']
        unwind=dict(input_side='x',amount_in=removal[0],amount_in_left=0,amount_out=removal[0],slippage=0)
        out=paper_outcome(pos,s,unwind=unwind,costs={'entry_gas':10,'add_liquidity_gas':20,'remove_liquidity_gas':30,'unwind_gas':40})
        self.assertIsNotNone(out['gross_result']);self.assertEqual(out['total_costs'],100);self.assertIsNotNone(out['after_cost_result'])

    def test_exact_35_bps_hurdle_comparison(self):
        self.assertEqual(hurdle_comparison(34),'below')
        self.assertEqual(hurdle_comparison(35),'equal')
        self.assertEqual(hurdle_comparison(36),'above')
        self.assertEqual(hurdle_comparison(None),'unresolved')

    def test_preentry_economics_stay_unqualified_without_cost_evidence(self):
        freeze=freeze_proposals(self._range_prestate(),10**15,quote_side='y',entry_timestamp=1040)
        for p in freeze['proposals']:
            self.assertIsNone(p['projected_after_cost_result'])
            self.assertEqual(p['hurdle_comparison'],'unresolved')
            self.assertFalse(p['exceeds_hurdle'])

    def test_preentry_fee_metrics_use_only_supplied_history(self):
        s=self._range_prestate();a=s['active']
        history=[dict(id=a,amountsIn=hex(pack([10**12,0])),protocolFees=hex(pack([1,0])),totalFees=hex(pack([100,0])))]
        freeze=freeze_proposals(s,10**15,quote_side='y',entry_timestamp=1040,prehistory=history)
        self.assertGreater(freeze['proposals'][0]['recent_within_range_volume'],0)
        self.assertGreaterEqual(freeze['proposals'][0]['estimated_fee_capture'],0)

    def test_wrong_side_range_input_fails_closed(self):
        s=self._range_prestate();bid=s['active']-1;b=s['bins'][bid]
        with self.assertRaisesRegex(BoundaryError,'wrong_side'):
            mint_effect(b['reserves'],b['supply'],[1,0],bin_id=bid,step=s['step'],active_id=s['active'],
                static=s['static'],variable=s['variable'],timestamp=1040)

    def test_forced_decay_matches_verified_parameter_rule(self):
        static=[40000,30,600,5000,40000,500,350000];active=100
        self.assertEqual(forced_decay(static,[20000,10000,90,500],active),[20000,10000,100,500])

    def test_flash_and_protocol_fee_helpers_conserve_values(self):
        q=swap_bin([10**9,10**9],bin_id=1<<23,step=10,gross_input=10**6,for_y=True,fee_rate=10**16,protocol_share=500)
        self.assertEqual(q['total_fee'],q['protocol_fee']+q['lp_fee'])


    def test_paper_fee_capture_uses_event_time_supply(self):
        s=self._range_prestate();freeze=freeze_proposals(s,10**15,quote_side='y',entry_timestamp=1040);pos=paper_position(freeze,0)
        bid=s['active'];shares=int(pos['owned_shares'][str(bid)])
        event_fee=[1000,0]
        fake=dict(fee_events=[dict(kind='swap',bin_id=bid,lp_fee=event_fee,supply_before=10**18,event_at=1050)],
                  terminal_state=s)
        got=paper_fee_capture(pos,fake)
        self.assertEqual(got['amounts'][0],event_fee[0]*shares//(10**18+shares))
