import json
from pathlib import Path

CERT=Path(__file__).resolve().parents[1]
PREP=CERT/'strategy-prep'

def load(name):
    return json.loads((PREP/name).read_text())

def test_nine_activate_items_are_explicit_and_ready():
    m=load('post-stage-e-strategy-activation-v1.json')
    assert m['paper_only'] is True
    assert m['live_money_authority'] is False
    items=m['activation_items']
    assert len(items)==9
    expected=[
        'directional_capital_parity',
        'realized_equity_compounding',
        'pump_current_exits',
        'pons_current_exits',
        'current_to_survivor_preservation',
        'common_right_tail_trail',
        'current_tail_bridge',
        'staged_winner_scaling',
        'meteora_exit_optimization',
    ]
    assert [x['id'] for x in items]==expected
    assert [x['number'] for x in items]==list(range(1,10))
    assert all(x['readiness']=='READY' for x in items)
    assert all(x['unresolved_decisions']==[] for x in items)
    assert m['final_acceptance']['activation_item_count']==9
    assert m['stage_e_boundary']['unresolved_strategy_or_economic_decisions']==[]

def test_capital_and_compounding_are_consistent():
    parity=load('directional-capital-parity-v1.json')
    sizing=load('directional-realized-equity-sizing-v1.json')
    assert all(parity['directional_targets'][k]['prepared_target_bps']==500 for k in
               ('pump_current','pump_survivor','pons_current','pons_survivor'))
    assert sizing['sizing_rule']['target_bps_of_realized_sleeve_equity']==500
    assert sizing['sizing_rule']['unrealized_pnl_included'] is False
    assert sizing['sizing_rule']['cross_sleeve_borrowing'] is False
    assert parity['activation_readiness']['unresolved_economic_decisions']==[]
    assert sizing['activation_readiness']['unresolved_economic_decisions']==[]

def test_current_exit_values_and_meteora_values_are_frozen():
    x=load('exit-optimization-v1.json')
    pump=x['changes']['pump_current']
    pons=x['changes']['pons_current']
    met=x['changes']['meteora']
    assert (pump['hard_stop_bps'],pump['first_profit_bps'],pump['first_profit_sell_bps'])==(-800,1500,2500)
    assert (pons['hard_stop_bps'],pons['first_profit_bps'],pons['first_profit_sell_bps_after'])==(-800,1800,2500)
    assert pons['runner_trailing_drawdown_bps_after']==1200
    assert pons['immediate_adverse_sell_buy_ratio_bps_after']==12000
    assert met['exit_one_way_two_way_balance_after']==0.18
    assert met['exit_one_way_drift_ratio_after']==0.82
    assert met['economic_collapse_confirmation_segments_after']==3

def test_opportunity_preservation_has_no_open_behavior_decisions():
    p=load('directional-opportunity-preservation-v1.json')
    r=p['implementation_resolution']
    assert r['survivor_discovery_independent_of_current'] is True
    assert r['same_asset_observation_allowed_while_current_exposure_open'] is True
    assert r['same_asset_survivor_fill_blocked_while_current_exposure_open'] is True
    assert r['decision_critical_research_provider_calls_allowed'] is False
    assert r['unresolved_policy_or_behavior_decisions']==[]

def test_right_tail_bridge_and_scaling_are_frozen():
    r=load('right-tail-capture-v1.json')
    tail=r['common_tail_mode']
    bridge=r['current_tail_bridge']
    scale=r['staged_winner_scaling']
    assert tail['arm_high_water_return_bps']==10000
    assert tail['accrued_gain_giveback_bps']==4000
    assert bridge['bridge_gates']['minimum_high_water_return_bps']==5000
    assert bridge['maximum_total_hold_seconds_from_original_open']==129600
    assert bridge['allocation_semantics']['new_entry'] is False
    assert bridge['allocation_semantics']['new_reservation'] is False
    assert scale['maximum_scale_events_per_lifecycle']==1
    assert scale['trigger']['minimum_high_water_return_bps']==10000
    assert scale['trigger']['minimum_seconds_since_first_crossing_trigger']==900
    assert scale['trigger']['maximum_current_drawdown_from_high_bps']==1500
    assert scale['add_size']['target_bps_of_realized_sleeve_equity']==250
    assert scale['add_size']['maximum_original_plus_added_committed_basis_bps_of_realized_sleeve_equity']==750
    assert scale['add_size']['unrealized_pnl_spendable'] is False
    assert r['activation_readiness']['unresolved_economic_decisions']==[]

def test_staged_scaling_source_agrees_with_right_tail_calibration():
    s=load('staged-winner-scaling-v1.json')
    e=s['economic_parameters']
    assert e['scale_trigger_bps']==10000
    assert e['scale_target_bps']==250
    assert e['maximum_total_position_bps']==750
    assert e['maximum_scale_events_per_lifecycle']==1
    assert e['confirmation_seconds_after_first_trigger_crossing']==900
    assert e['maximum_drawdown_from_high_bps_during_confirmation']==1500
    assert s['implementation_resolution']['unresolved_economic_decisions']==[]
