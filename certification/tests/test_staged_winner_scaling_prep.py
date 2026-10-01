import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SPEC=ROOT/'certification/strategy-prep/staged-winner-scaling-v1.json'
DOC=ROOT/'docs/STAGED_WINNER_SCALING_V1_PREP.md'
IMPL=ROOT/'docs/STAGED_WINNER_SCALING_V1_IMPLEMENTATION_CONTRACT.md'

def load(): return json.loads(SPEC.read_text())

def test_stage_e_isolated_and_not_active():
    s=load()
    assert s['status']=='PREPARED_ONLY_NOT_ACTIVE'
    assert s['paper_only'] is True and s['live_money_authority'] is False
    iso=s['stage_e_isolation']
    assert not iso['stage_e_candidate_modified']
    assert not iso['stage_e_branch_modified']
    assert not iso['stage_e_workflow_modified']
    assert not iso['workflow_dispatch_authorized']
    assert not iso['market_run_authorized']
    assert not iso['activation_allowed']

def test_all_directional_regimes_in_scope():
    assert set(load()['scope'])=={'pump_current','pump_survivor','pons_current','pons_survivor'}

def test_economic_parameters_are_not_hindsight_frozen():
    p=load()['economic_parameters']
    assert p['scale_trigger_bps'] is None
    assert p['scale_target_bps'] is None
    assert p['maximum_total_position_bps'] is None
    assert p['parameter_status']=='RESEARCH_AND_CALIBRATION_REQUIRED_BEFORE_PROMOTION'

def test_scale_is_winner_only_and_cannot_reset_risk():
    r=load()['hard_requirements']
    assert r['no_average_down'] is True
    assert r['current_after_cost_return_must_be_positive'] is True
    assert r['fresh_policy_requalification_required'] is True
    assert r['no_pending_full_exit_or_irreversible_exit_intent'] is True
    assert r['risk_state_cannot_be_reset_by_scale'] is True
    assert r['high_water_and_exit_intent_must_survive_scale'] is True
    assert r['hard_stop_may_not_be_widened_due_to_scale'] is True
    assert r['scale_event_uses_same_native_lifecycle_identity'] is True

def test_compose_after_existing_prepared_stack():
    assert load()['composition_order'][-2:]==['directional-realized-equity-sizing-v1','staged-winner-scaling-v1']
    assert 'PREPARED ONLY — NOT ACTIVE' in DOC.read_text()
    text=IMPL.read_text()
    assert 'no second synthetic position' in text
    assert 'no Stage-E integration' in text
