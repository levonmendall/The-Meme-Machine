import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SPEC=ROOT/'certification/strategy-prep/directional-realized-equity-sizing-v1.json'
PATCH=ROOT/'certification/strategy-prep/directional-realized-equity-sizing-v1.patch'
DOC=ROOT/'docs/DIRECTIONAL_REALIZED_EQUITY_SIZING_V1_PREP.md'

def spec():
    return json.loads(SPEC.read_text())

def test_stage_e_isolation_and_paper_only():
    s=spec()
    assert s['paper_only'] is True
    assert s['live_money_authority'] is False
    iso=s['stage_e_isolation']
    assert iso['stage_e_candidate_modified'] is False
    assert iso['stage_e_branch_modified'] is False
    assert iso['stage_e_workflow_modified'] is False
    assert iso['workflow_dispatch_authorized'] is False
    assert iso['market_run_authorized'] is False
    assert iso['activation_allowed'] is False

def test_realized_equity_is_the_only_compounding_basis():
    rule=spec()['sizing_rule']
    assert rule['target_bps_of_realized_sleeve_equity']==500
    assert rule['realized_equity_formula']=='immutable_genesis_sleeve_capital + reconciled_realized_pnl'
    assert rule['unrealized_pnl_included'] is False
    assert rule['mark_to_market_equity_included'] is False
    assert rule['positive_realized_pnl_increases_future_targets'] is True
    assert rule['realized_losses_reduce_future_targets'] is True

def test_examples_compound_up_and_down():
    rows={r['realized_sleeve_equity']:r['target_5pct'] for r in spec()['examples_usd_if_sleeve_equity_is_usd_equivalent']}
    assert rows[125.0]==6.25
    assert rows[150.0]==7.50
    assert rows[100.0]==5.00
    assert rows[250.0]==12.50

def test_no_cross_sleeve_rebalance_or_borrowing():
    rule=spec()['sizing_rule']
    assert rule['cross_sleeve_borrowing'] is False
    assert rule['automatic_cross_sleeve_rebalancing'] is False
    assert rule['genesis_capital_remains_immutable_for_audit'] is True

def test_all_four_directional_regimes_are_in_scope():
    assert set(spec()['scope'])=={'pump_current','pump_survivor','pons_current','pons_survivor'}

def test_prepared_patch_uses_shared_sizing_primitive():
    p=PATCH.read_text()
    assert 'def sizing_basis(self,target_bps,*,minimum_bps=0)' in p
    assert "equity=state['capital']+state['realized']" in p
    assert "sleeve.sizing_basis(POLICY.entry_fraction_bps)" in p
    assert "sleeve.sizing_basis(500,minimum_bps=5)" in p
    assert "self.capital*500//10000" in p
    assert "target=sizing['target']" in p

def test_composition_follows_prior_prepared_layers():
    order=spec()['composition_order']
    assert order[-4:]==[
        'directional-capital-parity-v1',
        'exit-optimization-v1',
        'directional-opportunity-preservation-v1',
        'directional-realized-equity-sizing-v1',
    ]
    d=DOC.read_text()
    assert 'PREPARED ONLY — NOT ACTIVE' in d
    assert 'No active Stage-E branch' in d
