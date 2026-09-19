from dataclasses import replace
import unittest
from unittest.mock import patch

from robinhood_research import BoundaryError
from robinhood_research.evidence import Stamp, Store
from robinhood_research.paper import Quote
from robinhood_research.pons_selective_ledger import SelectivePaper, STRATEGY_NAMESPACE
import robinhood_research.pons_selective_cohort as selective_cohort
from robinhood_research.pons import CurveState
from robinhood_research.pons_selective_continuation import (
    POLICY, POLICY_HASH, ENTRY_THRESHOLDS, POST_GRAD_THRESHOLDS, EXIT_POLICY,
    breakout_vector, demand_metrics, post_graduation_vector,
    qualification_vector, relative_strength_bps, runner_action,
    wallet_convergence,
)

ZERO="0x0000000000000000000000000000000000000000"
CREATOR="0x"+"11"*20


def state(**kw):
    base=CurveState(
        quote_reserve=2*10**18,
        token_reserve=800*10**24,
        real_quote=8*10**17,
        reserved_tokens=100*10**24,
        fee_bps=100,
        creator_tax_bps=50,
        graduated=False,
        launched_at=100,
        snipe_start_bps=9900,
        snipe_seconds=3,
        timestamp=200,
    )
    return replace(base,**kw)


def snapshots():
    return [
        dict(at=185,progress_bps=6500),
        dict(at=195,progress_bps=7400),
        dict(at=200,progress_bps=8000),
    ]


def trade(identity, group, quote, at, side="buy"):
    return dict(
        identity=identity,side=side,quote=quote,tokens=10**20,event_at=at,
        actor=group,recipient=group,group=group,
    )


def events():
    groups=["0x"+f"{i:040x}" for i in range(20,26)]
    rows=[
        trade("p0",groups[0],10**14,178),
        trade("p1",groups[1],10**14,180),
    ]
    for i,g in enumerate(groups):
        rows.append(trade(f"c{i}",g,10**15,190+i%3))
    return rows


def vector(**overrides):
    args=dict(
        state=state(),graduation_threshold=10**18,launch_at=100,
        snapshots=snapshots(),events=events(),creator_groups=(CREATOR,),
        current_snipe_bps=0,lifecycle_gas_quote=10**10,
        strategy_capital_quote=10**18,asof=200,evidence_available_at=202,
        pair_token=ZERO,wallet_histories=None,creator_history=dict(adverse=False),
    )
    args.update(overrides)
    return qualification_vector(**args)


class PonsSelectivePolicyTests(unittest.TestCase):
    def test_policy_is_distinct_and_frozen(self):
        self.assertEqual(POLICY,"pons-selective-continuation-v1")
        self.assertEqual(len(POLICY_HASH),64)
        self.assertEqual(ENTRY_THRESHOLDS["min_curve_progress_bps"],5500)
        self.assertEqual(ENTRY_THRESHOLDS["max_curve_progress_bps"],9200)
        self.assertEqual(ENTRY_THRESHOLDS["capital_size_bps"],25)
        self.assertEqual(EXIT_POLICY["first_profit_bps"],2500)
        self.assertEqual(EXIT_POLICY["max_total_hold_seconds"],900)

    def test_clean_late_curve_acceleration_can_qualify(self):
        v=vector()
        self.assertTrue(v["complete"])
        self.assertTrue(v["current_threshold_pass"],v["all_rejections"])
        self.assertEqual(v["trajectory"]["progress_15s_bps"],1500)
        self.assertTrue(v["trajectory"]["accelerating"])
        self.assertGreaterEqual(v["demand"]["independent_groups"],5)
        self.assertGreaterEqual(v["demand"]["new_independent_groups_15s"],3)
        self.assertEqual(v["current_snipe_bps"],0)
        self.assertGreater(v["proposed_size"]["amount_quote"],0)
        self.assertLessEqual(v["roundtrip_loss_bps"],500)

    def test_snipe_tax_must_be_actually_zero(self):
        v=vector(current_snipe_bps=1)
        self.assertIn("snipe_tax_nonzero",v["all_rejections"])
        self.assertFalse(v["current_threshold_pass"])

    def test_static_high_curve_does_not_qualify(self):
        flat=[
            dict(at=185,progress_bps=8000),
            dict(at=195,progress_bps=8050),
            dict(at=200,progress_bps=8100),
        ]
        v=vector(snapshots=flat)
        self.assertIn("curve_velocity",v["all_rejections"])

    def test_non_native_pair_is_research_only(self):
        v=vector(pair_token="0x"+"99"*20,quote_relative_strength_bps=321)
        self.assertIn("non_native_quote_allocation_disabled",v["all_rejections"])
        self.assertEqual(v["quote_relative_strength_bps"],321)

    def test_demand_uses_equal_recent_windows_and_concentration(self):
        m=demand_metrics(events(),asof=200,creator_groups=(CREATOR,))
        self.assertEqual(m["current_buy_quote"],6*10**15)
        self.assertEqual(m["prior_net_quote"],2*10**14)
        self.assertGreater(m["current_net_quote"],m["prior_net_quote"])
        self.assertLessEqual(m["largest_buyer_flow_bps"],2500)
        self.assertLessEqual(m["top3_buyer_flow_bps"],5500)

    def test_wallet_skill_is_point_in_time_overlay_not_authority(self):
        gs=list(demand_metrics(events(),asof=200)["current_net_by_group"])
        history=[
            dict(group=gs[0],complete=True,history_asof=199,completed_trades=25,
                 realized_after_cost_pnl=100,profitable_tokens=4,candidate_related=False),
            dict(group=gs[1],complete=True,history_asof=198,completed_trades=40,
                 realized_after_cost_pnl=200,profitable_tokens=6,candidate_related=False),
        ]
        w=wallet_convergence(history,gs,asof=200)
        self.assertTrue(w["converged"])
        self.assertFalse(w["qualification_authority"])
        with self.assertRaisesRegex(BoundaryError,"future_wallet_skill"):
            wallet_convergence([dict(history[0],history_asof=201)],gs,asof=200)

    def test_post_graduation_second_wave_gate(self):
        good=post_graduation_vector(
            observed_seconds=10,price_retention_bps=9500,new_independent_buyers=4,
            buy_quote=3_000,sell_quote=1_000,net_quote=2_000,
            preholder_sell_quote=200,largest_buyer_flow_bps_before=2400,
            largest_buyer_flow_bps_now=2000,
        )
        self.assertTrue(good["continuation_pass"])
        bad=post_graduation_vector(
            observed_seconds=10,price_retention_bps=9000,new_independent_buyers=1,
            buy_quote=1_000,sell_quote=2_000,net_quote=-1_000,
            preholder_sell_quote=1500,largest_buyer_flow_bps_before=2000,
            largest_buyer_flow_bps_now=4000,
        )
        self.assertFalse(bad["continuation_pass"])
        self.assertIn("price_retention",bad["all_rejections"])
        self.assertIn("second_wave_breadth",bad["all_rejections"])

    def test_profit_then_runner_is_asymmetric(self):
        first=runner_action(
            tokens=1000,partial_taken=False,after_cost_return_bps=2600,
            high_water_return_bps=2600,seconds_since_high=0,new_buyer_growth=2,
            buy_quote=10,sell_quote=2,
        )
        self.assertEqual((first["action"],first["exit_tokens"]),("partial_exit",500))
        trail=runner_action(
            tokens=500,partial_taken=True,after_cost_return_bps=2000,
            high_water_return_bps=4000,seconds_since_high=10,new_buyer_growth=1,
            buy_quote=10,sell_quote=2,
        )
        self.assertEqual(trail["reason"],"runner_trailing_stop")
        risk=runner_action(
            tokens=500,partial_taken=False,after_cost_return_bps=-1000,
            high_water_return_bps=0,seconds_since_high=0,new_buyer_growth=1,
            buy_quote=1,sell_quote=1,
        )
        self.assertEqual(risk["action"],"full_exit")

    def test_relative_strength_separates_quote_asset_move(self):
        # Token +10%, quote +8% -> +2% excess return in this simple feature.
        self.assertEqual(relative_strength_bps(
            token_usd_start=100,token_usd_now=110,
            quote_usd_start=100,quote_usd_now=108,
        ),200)

    def test_breakout_is_separate_and_never_has_allocation_authority(self):
        b=breakout_vector(
            seconds_after_graduation=60,pullback_bps=1000,
            current_price_index=12_000,consolidation_high_index=11_500,
            new_independent_buyers_15s=4,buy_quote_15s=3000,
            sell_quote_15s=1000,previous_buy_quote_15s=1500,
        )
        self.assertTrue(b["candidate"])
        self.assertFalse(b["allocation_authority"])



class SelectiveDiscoveryFrontierTests(unittest.TestCase):
    class Rpc:
        used=0
        def __init__(self,frontier):
            self.frontier=frontier
            self.last=None
        def call(self,method,params,scope=None):
            self.last=(method,params,scope)
            if method=="eth_blockNumber":
                return hex(self.frontier)
            raise AssertionError(method)
        def telemetry(self):
            return {}

    def test_provider_frontier_clamps_sequencer_range_without_advancing_past_it(self):
        rpc=self.Rpc(103)
        with patch.object(selective_cohort,"_next_discovery_end",return_value=105), \
             patch.object(
                 selective_cohort,"_current_curve_events",
                 side_effect=[BoundaryError("provider_rpc_-32602"),["e"]],
             ) as events:
            new_rpc,cursor,fresh=selective_cohort._poll(
                "https://unused",rpc,100,[],object(),[]
            )
        self.assertIs(new_rpc,rpc)
        self.assertEqual(cursor,103)
        self.assertEqual(fresh,["e"])
        self.assertEqual(events.call_args_list[0].args,(rpc,101,105))
        self.assertEqual(events.call_args_list[1].args,(rpc,101,103))
        self.assertEqual(rpc.last[0],"eth_blockNumber")

    def test_provider_frontier_behind_start_leaves_cursor_unchanged(self):
        rpc=self.Rpc(100)
        with patch.object(selective_cohort,"_next_discovery_end",return_value=105), \
             patch.object(
                 selective_cohort,"_current_curve_events",
                 side_effect=BoundaryError("provider_rpc_-32602"),
             ):
            _,cursor,fresh=selective_cohort._poll(
                "https://unused",rpc,100,[],object(),[]
            )
        self.assertEqual(cursor,100)
        self.assertEqual(fresh,[])

    def test_full_frontier_range_rejection_splits_exactly_by_block(self):
        rpc=self.Rpc(105)
        responses=[
            BoundaryError("provider_rpc_-32602"),
            ["101"],["102"],["103"],["104"],["105"],
        ]
        with patch.object(selective_cohort,"_next_discovery_end",return_value=105), \
             patch.object(
                 selective_cohort,"_current_curve_events",side_effect=responses
             ) as events:
            _,cursor,fresh=selective_cohort._poll(
                "https://unused",rpc,100,[],object(),[]
            )
        self.assertEqual(cursor,105)
        self.assertEqual(fresh,["101","102","103","104","105"])
        self.assertEqual(
            [call.args for call in events.call_args_list],
            [
                (rpc,101,105),(rpc,101,101),(rpc,102,102),
                (rpc,103,103),(rpc,104,104),(rpc,105,105),
            ],
        )

    def test_non_frontier_invalid_params_still_fails_closed(self):
        rpc=self.Rpc(105)
        with patch.object(selective_cohort,"_next_discovery_end",return_value=105), \
             patch.object(
                 selective_cohort,"_current_curve_events",
                 side_effect=BoundaryError("provider_rpc_-32602"),
             ):
            with self.assertRaisesRegex(BoundaryError,"provider_rpc_-32602"):
                selective_cohort._poll(
                    "https://unused",rpc,100,[],object(),[]
                )


class PartialPaperExitTests(unittest.TestCase):
    def _stamp(self,at):
        return Stamp(4663,at,f"h{at}",at,at,"finalized","natural")

    def _features(self,at,market):
        return dict(
            asof=at,market=market,authority="frozen_policy_paper",
            qualification="qualified",policy_hash=POLICY_HASH,
            strategy_namespace=STRATEGY_NAMESPACE,shared_allocator=False,
        )

    def test_partial_profit_then_runner_settlement_survives_accounting(self):
        s=Store(":memory:")
        p=SelectivePaper(
            s,STRATEGY_NAMESPACE+"-unit-partial",1000,delay=1,
            natural_policy_hash=POLICY_HASH,
        )
        p.reserve(
            "x",market="market",amount=100,gas_budget=20,now=10,
            features=self._features(10,"market"),kind="natural",
        )
        opened=p.advance(
            "x",now=11,action="entry",
            quote=Quote("market","buy",100,1000,2,0,self._stamp(11)),
        )
        self.assertEqual(opened["remaining_cost"],102)

        p.advance("x",now=12,action="exit_intent",exit_tokens=500)
        partial=p.advance(
            "x",now=13,action="exit",
            quote=Quote("market","sell",500,70,2,0,self._stamp(13)),
        )
        self.assertEqual((partial["status"],partial["tokens"]),("open",500))
        self.assertEqual(partial["remaining_cost"],51)
        self.assertEqual(partial["realized_pnl"],17)

        p.advance("x",now=14,action="exit_intent")
        final=p.advance(
            "x",now=15,action="exit",
            quote=Quote("market","sell",500,82,2,0,self._stamp(15)),
        )
        self.assertEqual(final["status"],"settled")
        self.assertEqual(final["pnl"],46)
        self.assertEqual(p.reconcile()["available"],1046)
        s.close()



    def test_pending_full_exit_survives_proven_market_transition(self):
        s=Store(":memory:")
        p=SelectivePaper(
            s,STRATEGY_NAMESPACE+"-unit-transition",1000,delay=1,
            natural_policy_hash=POLICY_HASH,
        )
        p.reserve(
            "x",market="curve",amount=100,gas_budget=20,now=10,
            features=self._features(10,"curve"),kind="natural",
        )
        p.advance(
            "x",now=11,action="entry",
            quote=Quote("curve","buy",100,1000,2,0,self._stamp(11)),
        )
        pending=p.advance("x",now=12,action="exit_intent")
        self.assertEqual(pending["pending_exit_tokens"],1000)
        transition=dict(
            previous_market="curve",market="v4",proof_hash="proof",
        )
        s.put("graduation","proof",transition)
        moved=p.advance("x",now=13,action="transition",transition=transition)
        self.assertEqual((moved["status"],moved["market"]),("exit_pending","v4"))
        final=p.advance(
            "x",now=13,action="exit",
            quote=Quote("v4","sell",1000,120,2,0,self._stamp(13)),
        )
        self.assertEqual(final["status"],"settled")
        self.assertEqual(final["tokens"],0)
        s.close()

if __name__=="__main__":
    unittest.main()
