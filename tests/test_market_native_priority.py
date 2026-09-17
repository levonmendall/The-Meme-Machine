import tempfile
import unittest
from pathlib import Path

from meme_machine import pump
from meme_machine.engine import Engine
from meme_machine.market_native_priority import (
    StreamFeasibility,
    choose_slot_candidate,
    priority_slot_seconds,
    snapshot_preflight,
    stream_feasibility,
)
from meme_machine.store import Store
from tests.support import MINT, SCOUT, evidence, event


class Tape:
    def __init__(self, rows):
        self.rows=list(rows)

    def window(self, mint, now):
        return [dict(x) for x in self.rows if x['mint']==mint and now-60 <= x['market_time'] <= now]


def candidate(now=100):
    return dict(mint=MINT, nomination=event(now=now, wallet=SCOUT, mint=MINT, id='anchor'))


def trade(wallet_byte, amount, buy=True, now=100, index=0):
    row=event(now=now, wallet=pump.b58(bytes([wallet_byte])*32), mint=MINT,
              id=f'{wallet_byte}-{index}', buy=buy)
    row['amount']=amount
    return row


class MarketNativePriority(unittest.TestCase):
    def test_slot_budget_is_spread_across_full_observation(self):
        self.assertEqual(priority_slot_seconds(3300,90),37)
        with self.assertRaisesRegex(ValueError,'invalid_priority_budget'):
            priority_slot_seconds(0,90)

    def test_evidence_capacity_is_rpc_free_guaranteed_rejection(self):
        rows=[]
        for i in range(101):
            rows.append(trade(20+(i%100),10_000_000,buy=True,index=i))
        result=stream_feasibility(candidate(),Tape(rows),100)
        self.assertFalse(result.possible)
        self.assertEqual(result.guaranteed_rejection,'evidence_capacity')
        self.assertEqual(result.evidence_events,101)
        self.assertTrue(result.research_only)
        self.assertFalse(result.order_authority)

    def test_too_few_possible_buyers_is_guaranteed_demand_rejection(self):
        rows=[
            trade(20,700_000_000,index=1),
            trade(21,700_000_000,index=2),
        ]
        result=stream_feasibility(candidate(),Tape(rows),100)
        self.assertFalse(result.possible)
        self.assertEqual(result.guaranteed_rejection,'independent_demand_impossible')
        self.assertEqual(result.possible_independent_buyers,2)

    def test_unknown_creator_uses_optimistic_net_bound_before_rejecting(self):
        rows=[
            trade(20,400_000_000,index=1),
            trade(21,300_000_000,index=2),
            trade(22,300_000_000,index=3),
            trade(23,100_000_000,buy=False,index=4),
        ]
        result=stream_feasibility(candidate(),Tape(rows),100)
        # Total is 0.9 SOL, but if the unknown creator is the 0.1 SOL net seller,
        # continuation-v1 could still see 1.0 SOL. The stream stage must not reject.
        self.assertTrue(result.possible)
        self.assertEqual(result.optimistic_independent_net_buy_lamports,1_000_000_000)

    def test_slot_selection_uses_policy_margin_not_wallet_identity(self):
        weak=StreamFeasibility(MINT,True,None,10,3,1_000_000_000,90,1000,100)
        strong=StreamFeasibility(pump.b58(bytes([17])*32),True,None,12,6,3_000_000_000,88,2000,101)
        selected=choose_slot_candidate([('weak',weak),('strong',strong)])
        self.assertEqual(selected[0],'strong')

    def test_snapshot_preflight_preserves_engine_and_has_no_authority(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(str(Path(td)/'priority.db'),'synthetic',100_000_000,
                        'market-native priority unit test')
            try:
                engine=Engine(store,[SCOUT])
                nomination=event(now=100,wallet=SCOUT,mint=MINT,id='anchor')
                ev=evidence(now=100,mint=MINT)
                result=snapshot_preflight(engine,nomination,ev['snapshot'],ev['events'],100)
                self.assertTrue(result['passes_non_concentration'])
                self.assertEqual(result['concentration_assumption'],'zero_for_prefilter_only')
                self.assertEqual(result['vector']['actual_reason'],'qualified')
                self.assertEqual(store.state['orders'],{})
                self.assertEqual(store.state['positions'],{})
                self.assertFalse(result['order_authority'])
            finally:
                store.close()


if __name__=='__main__':
    unittest.main()
