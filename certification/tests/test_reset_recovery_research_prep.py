import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SPEC=ROOT/'certification/strategy-prep/reset-recovery-research-v1.json'
DOC=ROOT/'docs/RESET_RECOVERY_RESEARCH_V1_PREP.md'
CONTRACT=ROOT/'docs/RESET_RECOVERY_V1_RESEARCH_CONTRACT.md'

def load(): return json.loads(SPEC.read_text())

def test_research_only_and_stage_e_isolated():
    s=load()
    assert s['status']=='RESEARCH_PREP_ONLY_NOT_ACTIVE'
    assert s['paper_only'] is True
    assert s['live_money_authority'] is False
    assert s['allocation_authority'] is False
    iso=s['stage_e_isolation']
    assert not any(iso.values())

def test_not_a_current_or_survivor_relaxation():
    x=load()['strategy_independence']
    assert x['not_a_current_threshold_relaxation'] is True
    assert x['not_a_survivor_threshold_relaxation'] is True
    assert x['independent_policy_identity_required_if_promoted'] is True
    assert x['independent_profitability_cohort_required_if_promoted'] is True

def test_no_economic_thresholds_frozen():
    p=load()['economic_parameters']
    assert p['status']=='NO_ECONOMIC_THRESHOLDS_FROZEN_UNTIL_RESEARCH_EVIDENCE'
    for k,v in p.items():
        if k!='status': assert v is None

def test_postgrad_initial_universe_and_shadow_only():
    u=load()['initial_research_universe']
    assert u['pregraduation_reset_entry_authorized'] is False
    i=load()['instrumentation']
    assert i['no_new_decision_critical_provider_calls'] is True
    assert i['shadow_entry_requires_executable_quote'] is True

def test_contract_has_no_allocation_authority():
    assert 'No part of this file grants that authority.' in CONTRACT.read_text()
    assert 'RESEARCH PREP ONLY — NOT ACTIVE' in DOC.read_text()
