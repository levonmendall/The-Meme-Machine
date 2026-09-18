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
        event['topics']=[topic('CollectedProtocolFees(address,bytes32)'),event['topics'][1]]
        event['data']='0x'+'00'*32
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
