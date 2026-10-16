import unittest

from meme_machine.lanes.pons.pons_postgrad_survivor import (
    POLICY, STRATEGY_VERSION, evaluate_entry, exit_action, select_entries,
    trend_efficiency_bps,
)


NOW=1_000_000


def winner_points():
    # A survivor trends higher, resets ~14% from an earlier peak, builds a two-hour
    # base, then breaks out without a one-candle 20% chase.
    return [
        (NOW-30*60*60,10_000),
        (NOW-24*60*60,10_200),
        (NOW-12*60*60,12_000),
        (NOW-8*60*60,13_000),
        (NOW-6*60*60,11_600),
        (NOW-4*60*60,11_800),
        (NOW-2*60*60,11_300),
        (NOW-90*60,11_500),
        (NOW-30*60,11_700),
        (NOW-16*60,11_800),
        (NOW-5*60,12_600),
        (NOW,12_900),
    ]


def facts(**changes):
    d=dict(
        now=NOW,graduation_at=NOW-30*60*60,lineage_proven=True,native_quote=True,continuity_complete=True,
        price_points=winner_points(),capital_quote=10**18,
        flow_30m=dict(
            buy_quote=10**17,sell_quote=5*10**16,
            buyer_groups=["0x"+f"{i:040x}" for i in range(1,8)],
            new_buyer_groups=["0x"+f"{i:040x}" for i in range(5,8)],
            largest_buyer_flow_bps=2500,creator_sell_quote=0,
        ),
        flow_previous_30m=dict(buy_quote=6*10**16,
            buyer_groups=['0x'+f'{i:040x}' for i in range(1,5)]),
        execution=dict(roundtrip_loss_bps=180,double_size_roundtrip_loss_bps=260),
    )
    d.update(changes);return d


class PonsPostgradSurvivorTests(unittest.TestCase):
    def cycle_facts(self,**changes):
        value=facts(**changes)
        value['rally_cycle_context']=dict(candidate='native-token',venue='pons_v4',
            graduation=dict(at=value['graduation_at'],block=1,block_hash='graduation-block',
                transition=dict(market='authenticated-pool',graduation_transaction='graduation-tx')),
            evidence_id='authenticated-contiguous-history-and-state',authoritative=True)
        return value

    def test_native_cycle_uses_retained_peak_reset_base_and_breakout_clocks(self):
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
        from meme_machine.runtime.rally_cycle import validate_cycle
        adapter=object.__new__(Runtime)
        out=adapter.qualify(self.cycle_facts())
        self.assertTrue(out['candidate'],out['all_rejections'])
        cycle=validate_cycle(out['rally_cycle'],candidate='native-token',observation_at=NOW)
        self.assertEqual(cycle['peak_at'],NOW-8*3600)
        self.assertEqual(cycle['reset_at'],NOW-2*3600)
        self.assertEqual(cycle['base_start'],cycle['reset_at'])
        self.assertEqual(cycle['base_end'],NOW-16*60)
        self.assertEqual(cycle['breakout_at'],NOW-5*60)
        self.assertEqual(cycle['minimum_base_seconds'],900)
        self.assertEqual(POLICY['trend']['base_seconds'],7200)
        self.assertEqual(POLICY['trend']['breakout_exclusion_seconds'],900)

    def test_native_cycle_identity_survives_new_decision_buyer_and_flow_counts(self):
        from unittest.mock import patch
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
        adapter=object.__new__(Runtime)
        with patch('meme_machine.lanes.pons.pons_survivor_runtime.time.time',return_value=NOW+10):
            original=adapter.qualify(self.cycle_facts())
        later=self.cycle_facts(now=NOW+60,price_points=winner_points()+[(NOW+60,12_910)])
        later['flow_30m']=dict(later['flow_30m'],buy_quote=11*10**16,
            buyer_groups=later['flow_30m']['buyer_groups']+['new-buyer'])
        with patch('meme_machine.lanes.pons.pons_survivor_runtime.time.time',return_value=NOW+70):
            updated=adapter.qualify(later)
        self.assertTrue(updated['candidate'],updated['all_rejections'])
        self.assertEqual(original['rally_cycle']['id'],updated['rally_cycle']['id'])
        self.assertNotEqual(original['rally_cycle']['decision_at'],updated['rally_cycle']['decision_at'])

    def test_native_cycle_rejects_unverified_lineage_and_short_post_reset_base(self):
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
        adapter=object.__new__(Runtime)
        unavailable=self.cycle_facts()
        unavailable['rally_cycle_context']['authoritative']=False
        out=adapter.qualify(unavailable)
        self.assertFalse(out['candidate'])
        self.assertIn('unverified_rally_cycle',out['all_rejections'])
        points=winner_points()[:6]+[(NOW-2*3600,11_800),(NOW-20*60,11_300),
            (NOW-16*60,11_800),(NOW-5*60,12_600),(NOW,12_900)]
        late_reset=self.cycle_facts(price_points=points)
        # The old complete two-hour window economics remain intact. The extra
        # cycle gate requires a genuinely completed post-reset base as well.
        self.assertTrue(evaluate_entry(late_reset)['candidate'])
        out=adapter.qualify(late_reset)
        self.assertFalse(out['candidate'])
        self.assertIn('unverified_rally_cycle',out['all_rejections'])

    def test_native_timestamp_accountability_preserves_canonical_and_observed_time(self):
        from unittest.mock import patch
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime,_quote_times
        from types import SimpleNamespace
        adapter=object.__new__(Runtime)
        value=self.cycle_facts(market_time=NOW,evidence_acquired_at=NOW+5,
            state_evidence_available_at=NOW+5.5,evidence_available_at=NOW+6)
        with patch('meme_machine.lanes.pons.pons_survivor_runtime.time.time',return_value=NOW+7):
            out=adapter.qualify(value)
        self.assertEqual(out['timestamp_accountability'],dict(market_time=NOW,
            evidence_acquired_at=NOW+5,state_evidence_available_at=NOW+5.5,
            evidence_available_at=NOW+6,decision_at=NOW+7))
        self.assertEqual(_quote_times(SimpleNamespace(stamp=SimpleNamespace(
            event_at=NOW,observed_at=NOW+6))),dict(market_time=NOW,evidence_available_at=NOW+6))

    def young_facts(self,age=4*3600):
        return facts(graduation_at=NOW-age,price_points=[
            (NOW-age,10000),(NOW-150*60,12000),(NOW-2*3600,11400),
            (NOW-90*60,11500),(NOW-16*60,11700),(NOW-5*60,12500),(NOW,12600)])

    def test_four_to_six_hour_histories_are_complete_effective_windows(self):
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
        adapter=object.__new__(Runtime)
        for age in (4*3600,5*3600,6*3600,6*3600+1):
            f=self.young_facts(age);out=adapter.qualify(f)
            self.assertTrue(out['candidate'],out['all_rejections'])
            w=out['features']['medium_window']
            self.assertEqual(w['nominal_duration_seconds'],21600)
            self.assertEqual(w['effective_duration_seconds'],min(age,21600))
            self.assertEqual(w['window_start'],NOW-min(age,21600))
            self.assertEqual(w['covered_duration_seconds'],min(age,21600))
            self.assertTrue(w['complete'])

    def test_missing_boundary_or_native_continuity_does_not_shorten_window(self):
        for remove_anchor,continuity in ((True,True),(False,False)):
            f=self.young_facts()
            if remove_anchor:f['price_points']=f['price_points'][1:]
            f['continuity_complete']=continuity
            out=evaluate_entry(f)
            self.assertFalse(out['candidate'])
            self.assertIn('incomplete_medium_window',out['all_rejections'])
            self.assertEqual(out['features']['medium_window']['effective_duration_seconds'],14400)
            self.assertFalse(out['features']['medium_window']['complete'])

    def test_four_hour_and_seven_day_entry_boundaries_are_inclusive(self):
        early=evaluate_entry(self.young_facts(4*3600-1))
        self.assertIn('too_early',early['all_rejections'])
        self.assertTrue(evaluate_entry(self.young_facts())['candidate'])
        at_limit=facts(graduation_at=NOW-7*86400,
            price_points=[(NOW-7*86400,10000)]+winner_points()[1:])
        self.assertTrue(evaluate_entry(at_limit)['candidate'])
        beyond=dict(at_limit,graduation_at=NOW-7*86400-1,
            price_points=[(NOW-7*86400-1,10000)]+winner_points()[1:])
        self.assertIn('too_old',evaluate_entry(beyond)['all_rejections'])
        ongoing=evaluate_entry(dict(beyond,qualification_scope='existing_position_add'))
        self.assertTrue(ongoing['candidate'],ongoing['all_rejections'])
        self.assertEqual(ongoing['qualification_scope'],'existing_position_add')

    def test_sustained_buying_and_missing_optional_acceleration_can_qualify(self):
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
        adapter=object.__new__(Runtime)
        for previous in ({'buy_quote':10**17,'buyer_groups':[]},
                {'buy_quote':12*10**16,'buyer_groups':[]},{'buyer_groups':[]}):
            f=facts(flow_previous_30m=previous);out=adapter.qualify(f)
            self.assertTrue(out['candidate'],out['all_rejections'])
            self.assertNotIn('no_demand_acceleration',out['all_rejections'])
            if 'buy_quote' not in previous:
                self.assertIsNone(out['features']['buy_acceleration_bps'])
                self.assertIn('buy_acceleration_bps',out['confirmation_context']['unavailable_fields'])
            else:
                self.assertIn('no_demand_acceleration',out['confirmation_context']['previous_policy_would_reject'])
                self.assertTrue(out['newly_admitted_by_revision'])
        f=facts(flow_previous_30m={'buy_quote':12*10**16,'buyer_groups':[]})
        f['flow_30m']=dict(f['flow_30m'],sell_quote=10**17)
        self.assertIn('weak_buy_sell_flow',adapter.qualify(f)['all_rejections'])

    def test_current_newcomers_are_independent_of_optional_previous_population(self):
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
        adapter=object.__new__(Runtime)
        for previous in ({},{'buy_quote':10**17},{'buy_quote':10**17,'buyer_groups':None}):
            out=adapter.qualify(facts(flow_previous_30m=previous))
            self.assertTrue(out['candidate'],out['all_rejections'])
            self.assertEqual(out['features']['new_independent_buyers_30m'],3)
            self.assertIsNone(out['features']['total_buyer_population_change'])
            self.assertIsNone(out['features']['repeat_independent_buyers_30m'])
        available=adapter.qualify(facts(flow_previous_30m={'buyer_groups':[]}))
        self.assertTrue(available['candidate'],available['all_rejections'])
        self.assertIsNone(available['features']['buy_acceleration_bps'])

    def test_missing_actual_newcomer_population_is_unavailable_required_evidence(self):
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
        adapter=object.__new__(Runtime)
        for absent in (True,None,'unavailable',[None],['']):
            f=facts();f['flow_30m']=dict(f['flow_30m'])
            if absent is True:f['flow_30m'].pop('new_buyer_groups')
            else:f['flow_30m']['new_buyer_groups']=absent
            out=adapter.qualify(f)
            self.assertFalse(out['candidate'])
            self.assertIn('missing_new_buyer_population',out['all_rejections'])
            self.assertIsNone(out['features']['new_independent_buyers_30m'])

    def test_open_market_style_survivor_breakout_qualifies(self):
        out=evaluate_entry(facts())
        self.assertTrue(out["candidate"],out["all_rejections"])
        self.assertEqual(out["strategy"],STRATEGY_VERSION)
        self.assertGreater(out["proposed_quote_amount"],0)

    def test_preserved_archive_compaction_keeps_complete_native_features(self):
        import hashlib,os,tempfile
        from pathlib import Path
        from unittest.mock import patch
        from meme_machine.runtime.survivor_history import History
        from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
        for age in (30*3600,7*86400):
            for price in (10000,20000):
                f=facts(graduation_at=NOW-age)
                f['price_points']=[(NOW-age,price),(NOW-27*3600,11000),(NOW-25*3600,21000)]+winner_points()[1:]
                expected=evaluate_entry(f)
                with tempfile.TemporaryDirectory() as td:
                    path=Path(td)/'history.sqlite';h=History(path,policy=POLICY_HASH)
                    h.graduate('coin',dict(at=NOW-age))
                    h.append('coin',through=NOW,events=[],points=f['price_points'],complete=True);h.close()
                    checksum=hashlib.sha256(path.read_bytes()).hexdigest()
                    with patch.dict(os.environ,MM_AUTONOMOUS_STATE_RECEIPT='verified-predecessor'):
                        h=History(path,policy=POLICY_HASH)
                    h.compact_archived(dict(state_hash='parent',history_sha256=checksum))
                    retained,_=h.facts('coin',NOW)
                    f['price_points']=[(r['at'],r['price']) for r in retained]
                    self.assertEqual(evaluate_entry(f),expected)
                    h.close()

    def test_volume_alone_cannot_rescue_downtrend(self):
        points=[
            (NOW-30*60*60,20_000),(NOW-24*60*60,18_000),
            (NOW-8*60*60,14_000),(NOW-6*60*60,12_000),
            (NOW-2*60*60,9_000),(NOW-30*60,9_300),(NOW,10_000),
        ]
        out=evaluate_entry(facts(price_points=points))
        self.assertFalse(out["candidate"])
        self.assertTrue(any(x in out["all_rejections"] for x in (
            "weak_since_graduation","weak_long_trend","weak_6h_trend"
        )))

    def test_dead_cat_bounce_is_rejected_even_with_strong_recent_flow(self):
        points=[
            (NOW-30*60*60,20_000),(NOW-24*60*60,17_000),
            (NOW-8*60*60,11_000),(NOW-6*60*60,9_000),
            (NOW-2*60*60,7_000),(NOW-30*60,7_200),
            (NOW-16*60,7_300),(NOW,8_500),
        ]
        out=evaluate_entry(facts(price_points=points))
        self.assertFalse(out["candidate"])
        self.assertIn("weak_since_graduation",out["all_rejections"])

    def test_thin_market_and_concentrated_buyer_fail_closed(self):
        f=facts(
            flow_30m=dict(
                buy_quote=10**15,sell_quote=2*10**14,
                buyer_groups=["0x"+f"{i:040x}" for i in range(1,8)],
                new_buyer_groups=["0x"+f"{i:040x}" for i in range(5,8)],
                largest_buyer_flow_bps=5000,creator_sell_quote=0,
            ),
            execution=dict(roundtrip_loss_bps=500,double_size_roundtrip_loss_bps=900),
        )
        out=evaluate_entry(f)
        self.assertFalse(out["candidate"])
        self.assertIn("buyer_concentration",out["all_rejections"])
        self.assertIn("roundtrip_friction",out["all_rejections"])
        self.assertIn("stress_friction",out["all_rejections"])
        self.assertIn("insufficient_executable_capacity",out["all_rejections"])

    def test_creator_distribution_is_hard_reject(self):
        flow=dict(facts()["flow_30m"]);flow["creator_sell_quote"]=1
        out=evaluate_entry(facts(flow_30m=flow))
        self.assertFalse(out["candidate"])
        self.assertIn("creator_distribution",out["all_rejections"])

    def test_one_buyer_pump_is_not_independent_demand(self):
        flow=dict(facts()["flow_30m"])
        flow["buyer_groups"]=["0x"+"11"*20]
        flow["new_buyer_groups"]=["0x"+"11"*20]
        out=evaluate_entry(facts(flow_30m=flow))
        self.assertFalse(out["candidate"])
        self.assertIn("insufficient_buyer_breadth",out["all_rejections"])

    def test_late_vertical_extension_is_not_chased(self):
        pts=winner_points()[:-2]+[(NOW-5*60,14_500),(NOW,15_000)]
        out=evaluate_entry(facts(price_points=pts))
        self.assertFalse(out["candidate"])
        self.assertIn("late_extension",out["all_rejections"])

    def test_cross_sectional_selection_prefers_persistent_strength(self):
        a=facts()
        b=facts(price_points=[
            (at,price*(101 if i==len(winner_points())-1 else 100)//100)
            for i,(at,price) in enumerate(winner_points())
        ])
        selected,decisions=select_entries([a,b],open_positions=0)
        self.assertEqual(len(selected),2)
        self.assertTrue(all(x["candidate"] for x in decisions))

    def test_exit_hard_stop(self):
        self.assertEqual(
            exit_action(
                after_cost_return_bps=-1000,high_water_return_bps=0,
                hold_seconds=100,seconds_since_high=100,
                buy_quote_30m=1,sell_quote_30m=1,new_buyers_30m=1,
            )["reason"],"hard_stop"
        )

    def test_exit_trails_large_winner(self):
        self.assertEqual(
            exit_action(
                after_cost_return_bps=2400,high_water_return_bps=4000,
                hold_seconds=10_000,seconds_since_high=600,
                buy_quote_30m=2,sell_quote_30m=1,new_buyers_30m=1,
            )["reason"],"high_water_trailing_stop"
        )

    def test_soft_demand_failure_requires_confirmation(self):
        first=exit_action(
            after_cost_return_bps=500,high_water_return_bps=1000,
            hold_seconds=1000,seconds_since_high=1000,
            buy_quote_30m=7,sell_quote_30m=10,new_buyers_30m=0,
            deterioration_streak=1,
        )
        second=exit_action(
            after_cost_return_bps=500,high_water_return_bps=1000,
            hold_seconds=1000,seconds_since_high=1000,
            buy_quote_30m=7,sell_quote_30m=10,new_buyers_30m=0,
            deterioration_streak=2,
        )
        self.assertEqual(first["action"],"hold")
        self.assertEqual(second["reason"],"persistent_demand_failure")

    def test_old_high_and_small_return_cannot_exit_healthy_long_held_demand(self):
        for age in (6*3600,36*3600,72*3600,96*3600,7*86400,14*86400,30*86400):
            for gain in (0,100,499):
                for buy,sell,buyers in ((300,100,5),(70,100,1)):
                    result=exit_action(after_cost_return_bps=gain,high_water_return_bps=gain,
                        hold_seconds=age,seconds_since_high=age,buy_quote_30m=buy,
                        sell_quote_30m=sell,new_buyers_30m=buyers)
                    self.assertEqual(result['action'],'hold',(age,gain,buyers,result))

    def test_stale_thesis_requires_adverse_flow_and_matches_native_age_return_boundaries(self):
        from meme_machine.runtime.survivor_risk import mark
        from meme_machine.lanes.pons.pons_postgrad_survivor import risk_policy
        for age in (21600-1,21600,30*86400):
            for gain in (100,499,500):
                for soft in (False,True):
                    for streak in (1,2):
                        result=exit_action(after_cost_return_bps=gain,high_water_return_bps=gain,
                            hold_seconds=age,seconds_since_high=age,buy_quote_30m=70 if soft else 300,
                            sell_quote_30m=100,new_buyers_30m=0 if soft else 5,deterioration_streak=streak)
                        state=dict(opened_at=0,high_at=0,high_water_bps=gain,
                            original_quantity=400,remaining_quantity=400,realization_taken=False,
                            deterioration_streak=streak-1 if soft else 0)
                        _,native=mark(state,dict(id='flow',at=age,after_cost_return_bps=gain,
                            soft_deterioration=soft,exit_liquidity_valid=True),risk_policy())
                        self.assertEqual(result['action'],native['action'],(age,gain,soft,streak))
                        if result['action']=='full_exit':
                            self.assertEqual(result['reason'],'persistent_demand_failure' if streak==2 else 'stale_thesis')

    def test_strategy_has_no_pregrad_import_dependency(self):
        import inspect
        import meme_machine.lanes.pons.pons_postgrad_survivor as module
        source=inspect.getsource(module)
        self.assertNotIn("pons_selective_continuation",source)
        self.assertNotIn("pons_opportunity_research",source)

    def test_efficiency_penalizes_chop(self):
        self.assertGreater(
            trend_efficiency_bps([100,110,120,130]),
            trend_efficiency_bps([100,130,90,130]),
        )


if __name__=="__main__":
    unittest.main()
