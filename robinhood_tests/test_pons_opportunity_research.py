"""Synthetic contract tests, never counted as retained market evidence."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from robinhood_research.pons_opportunity_research import (
    preservation,promotion_order,bounded_promotions,fill_hysteresis,acceptable,SELECTED_POLICY)
from robinhood_research.pons_selective_continuation import POLICY_HASH,EXIT_POLICY,ENTRY_THRESHOLDS


def ready(**changes):
    d=dict(candidate='curve',generation=1,scope_valid=True,provenance_valid=True,
        token_age_seconds=180,progress_bps=6000,current_snipe_bps=0,
        trajectory=dict(complete=True,accelerating=True,progress_15s_bps=500,graduation_eta_seconds=40),
        remaining_seconds=4,measured_service_seconds=1,
        demand=dict(current_net_quote=10,independent_groups=4))
    d.update(changes);return d


def fill(n=1,**changes):
    d=dict(observation_id=str(n),at=n,trusted=True,quote_age_seconds=1,
        hard_invalidators=[],soft_deterioration=False)
    d.update(changes);return d


class OpportunityResearchTests(unittest.TestCase):
    def test_temporary_states_do_not_grant_entry(self):
        for changes,state in [({'progress_bps':1},'WATCHING'),({'token_age_seconds':10},'DEFERRED'),
            ({'current_snipe_bps':9900},'DEFERRED'),({'trajectory':{}},'WATCHING')]:
            with self.subTest(changes=changes):
                out=preservation(ready(**changes));self.assertEqual(out['state'],state)
                self.assertFalse(out['entry_authority'])
    def test_later_ready_generation_can_promote_without_changing_canonical_gate(self):
        self.assertEqual(preservation(ready(progress_bps=3000))['state'],'WATCHING')
        self.assertEqual(preservation(ready(generation=2))['state'],'PROMOTED')
        self.assertEqual(ENTRY_THRESHOLDS['min_curve_progress_bps'],5000)
    def test_monotone_expiry_and_hard_risk_are_terminal(self):
        for changes in ({'token_age_seconds':601},{'progress_bps':8501},{'graduated':True},
                        {'scope_valid':False},{'provenance_valid':False},{'creator_adverse':True}):
            with self.subTest(changes=changes):self.assertEqual(preservation(ready(**changes))['state'],'REJECTED_TERMINAL')
    def test_unknown_and_original_deadline_are_fail_closed(self):
        for changes in ({'scope_valid':None},{'remaining_seconds':1},{'measured_service_seconds':None}):
            self.assertEqual(preservation(ready(**changes))['state'],'DEFERRED')
    def test_ordinal_order_budget_and_duplicate_idempotency(self):
        a=ready(candidate='a');b=ready(candidate='b',demand={})
        self.assertGreater(promotion_order(a),promotion_order(b))
        self.assertEqual(bounded_promotions([b,a,a],set()),[a])
        self.assertEqual(bounded_promotions([a,b],{('a',1)}),[b])
        self.assertEqual(bounded_promotions([a],set(),slots=0),[])
        with self.assertRaises(ValueError):bounded_promotions([a],set(),slots=2)
        with self.assertRaises(ValueError):bounded_promotions([a]*513,set())
        with self.assertRaises(ValueError):bounded_promotions([a,ready(candidate='a',progress_bps=6500)],set())
    def test_fill_hard_invalidators_and_freshness_never_soften(self):
        for hard in ('creator_distribution','creator_adverse','nonpositive_net_demand','unacceptable_cost',
                     'unavailable_cost','impact','structural_execution','zero_size'):
            self.assertEqual(fill_hysteresis(None,fill(hard_invalidators=[hard]))['action'],'CANCEL')
        for changes in ({'quote_age_seconds':6},{'quote_age_seconds':None},{'trusted':False}):
            self.assertEqual(fill_hysteresis(None,fill(**changes))['action'],'CANCEL')
    def test_soft_hysteresis_duplicate_and_recovery(self):
        first=fill(soft_deterioration=True);s=fill_hysteresis(None,first)
        self.assertEqual(s['action'],'HOLD');self.assertFalse(s['entry_authority'])
        self.assertEqual(fill_hysteresis(s,first),s)
        self.assertEqual(fill_hysteresis(s,fill(2))['action'],'READY')
        canceled=fill_hysteresis(s,fill(2,soft_deterioration=True))
        self.assertEqual(canceled['action'],'CANCEL')
        self.assertEqual(fill_hysteresis(canceled,fill(3))['action'],'CANCEL')
    def test_research_state_serialization_and_severity(self):
        for state in ('WATCHING','DEFERRED','PROMOTED','QUALIFIED'):
            payload=dict(state=state,candidate='curve',generation=2)
            self.assertEqual(json.loads(json.dumps(payload)),payload)
        s=fill_hysteresis(None,fill(soft_deterioration=True))
        restored=json.loads(json.dumps(s))
        self.assertEqual(fill_hysteresis(restored,fill(2,soft_deterioration=True))['action'],'CANCEL')
        self.assertEqual(fill_hysteresis(None,fill(severe=True))['action'],'CANCEL')
    def test_no_future_or_conflicting_fill_observation(self):
        s=fill_hysteresis(None,fill(2))
        with self.assertRaises(ValueError):fill_hysteresis(s,fill(1))
        with self.assertRaises(ValueError):fill_hysteresis(s,fill(2,soft_deterioration=True))
    def test_missing_outcomes_never_select_revision(self):
        self.assertFalse(acceptable({}))
        self.assertFalse(acceptable(dict(incremental_unique_winners=1,incremental_losers=0,downside_change=0,canonical_workload_change=None)))
        self.assertEqual(SELECTED_POLICY,0)
    def test_baseline_canonical_sizing_creator_cost_impact_and_exits_are_byte_identical(self):
        module=Path(__file__).resolve().parents[1]/'robinhood_research/pons_selective_continuation.py'
        self.assertEqual(hashlib.sha256(module.read_bytes()).hexdigest(),'09763b06f52b771eea1bbe3222cb92672a4a3f2af251bcb50ee61f2b3925a269')
        self.assertEqual(POLICY_HASH,'19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84')
        self.assertEqual(EXIT_POLICY['risk_bps'],-800)
        self.assertEqual(EXIT_POLICY['first_profit_bps'],1800)
        self.assertEqual(EXIT_POLICY['first_profit_sell_bps'],3333)
        self.assertEqual(ENTRY_THRESHOLDS['capital_size_bps'],25)
    def test_research_is_not_imported_by_live_strategy_paths(self):
        root=Path(__file__).resolve().parents[1]/'robinhood_research'
        for name in ('pons_selective_cohort.py','pons_selective_paper.py','pons_selective_acquisition.py'):
            self.assertNotIn('pons_opportunity_research',root.joinpath(name).read_text())
