import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SPEC=ROOT/'certification/strategy-prep/idle-capital-rotation-architecture-v1.json'
DOC=ROOT/'docs/IDLE_CAPITAL_ROTATION_ARCHITECTURE_V1.md'
CONTRACT=ROOT/'docs/IDLE_CAPITAL_ROTATION_FUTURE_GOVERNOR_CONTRACT.md'

def load(): return json.loads(SPEC.read_text())

def test_architecture_only_and_cross_sleeve_borrowing_stays_off():
    s=load()
    assert s['status']=='ARCHITECTURE_ONLY_NOT_ACTIVE'
    assert s['runtime_implementation_authorized'] is False
    assert s['cross_sleeve_borrowing_active'] is False
    assert s['paper_only'] is True and s['live_money_authority'] is False

def test_stage_e_isolated():
    assert not any(load()['stage_e_isolation'].values())

def test_no_unrestricted_pool_or_double_spend_model():
    m=load()['model']
    assert m['no_unrestricted_pool'] is True
    assert m['no_re_lending'] is True
    assert m['no_borrowing_from_open_basis'] is True
    assert m['no_borrowing_from_reserved_capital'] is True
    assert m['no_borrowing_against_unrealized_pnl'] is True
    assert m['lease_must_be_durable_and_restart_replayable'] is True

def test_parameters_intentionally_unset():
    p=load()['parameters_intentionally_unset']
    assert p['status']=='UTILIZATION_AND_ATTRIBUTION_EVIDENCE_REQUIRED'
    for k,v in p.items():
        if k!='status': assert v is None

def test_current_no_borrowing_rule_remains_authoritative():
    assert 'continues to require no cross-sleeve borrowing' in load()['compatibility_note']
    assert 'ARCHITECTURE ONLY — NOT ACTIVE' in DOC.read_text()
    text=CONTRACT.read_text()
    assert 'one unrestricted shared cash pool' in text
    assert 'runtime implementation before utilization evidence' in text
