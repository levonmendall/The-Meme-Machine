import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
POLICY=json.loads((ROOT/'strategy-prep/right-tail-capture-v1.json').read_text()) if (ROOT/'strategy-prep/right-tail-capture-v1.json').exists() else json.loads((Path(__file__).resolve().parents[1]/'strategy-prep/right-tail-capture-v1.json').read_text())


def test_right_tail_prep_is_nonactivating():
    assert POLICY['status']=='PREPARED_ONLY_NOT_ACTIVE'
    assert POLICY['paper_only'] is True
    assert POLICY['live_money_authority'] is False
    isolation=POLICY['stage_e_isolation']
    assert isolation['stage_e_candidate_modified'] is False
    assert isolation['workflow_dispatch_authorized'] is False
    assert isolation['market_run_authorized'] is False
    assert isolation['activation_allowed'] is False


def test_tail_calibration_exact_boundaries():
    tail=POLICY['common_tail_mode']
    assert tail['arm_high_water_return_bps']==10000
    assert tail['accrued_gain_giveback_bps']==4000
    expected={2:1.6,5:3.4,10:6.4,25:15.4,50:30.4}
    observed={row['peak_x']:row['trail_exit_x'] for row in tail['implication_examples']}
    assert observed==expected


def test_pump_fixed_point_trail_is_removed():
    pump=POLICY['regime_trails']['pump_current']
    assert pump['fixed_return_point_trail_removed'] is True
    assert pump['before_tail_arm']['type']=='proportional_high_water_price_drawdown'
    assert pump['before_tail_arm']['drawdown_bps']==1400
    assert pump['at_or_after_tail_arm']=='common_tail_mode'


def test_bridge_closes_time_gap_without_new_exposure():
    bridge=POLICY['current_tail_bridge']
    assert bridge['bridge_gates']['first_realization_committed'] is True
    assert bridge['bridge_gates']['minimum_high_water_return_bps']==5000
    assert bridge['maximum_total_hold_seconds_from_original_open']==129600
    a=bridge['allocation_semantics']
    assert a['new_entry'] is False
    assert a['new_reservation'] is False
    assert a['extra_capital'] is False
    assert a['sell_rebuy_handoff'] is False
    s=bridge['survivor_interaction']
    assert s['existing_six_hour_survivor_minimum_unchanged'] is True
    assert s['survivor_fill_for_same_family_asset_while_bridge_open'] is False


def test_one_bounded_scale_is_frozen():
    scale=POLICY['staged_winner_scaling']
    assert scale['maximum_scale_events_per_lifecycle']==1
    assert scale['trigger']['minimum_high_water_return_bps']==10000
    assert scale['trigger']['minimum_seconds_since_first_crossing_trigger']==900
    assert scale['trigger']['maximum_current_drawdown_from_high_bps']==1500
    assert scale['add_size']['target_bps_of_realized_sleeve_equity']==250
    assert scale['add_size']['cap_as_fraction_of_original_committed_basis_bps']==5000
    assert scale['add_size']['maximum_original_plus_added_committed_basis_bps_of_realized_sleeve_equity']==750
    assert scale['risk_semantics']['high_water_reset'] is False
    assert scale['risk_semantics']['hard_stop_widening'] is False
