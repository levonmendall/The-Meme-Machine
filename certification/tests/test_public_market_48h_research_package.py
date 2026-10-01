import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RESULT=ROOT/'research/public-market-48h-20261001/results.json'
REPORT=ROOT/'research/public-market-48h-20261001/REPORT.md'

def load(): return json.loads(RESULT.read_text())

def test_market_data_only():
    d=load()['data_policy']
    assert d['public_market_data_only'] is True
    assert d['meme_machine_runtime_evidence_used'] is False
    assert d['meme_machine_historical_trade_evidence_used'] is False
    assert d['meme_machine_rejected_winner_evidence_used'] is False
    assert d['alchemy_or_private_provider_data_used'] is False
    assert d['internal_candidate_or_fill_data_used'] is False

def test_no_strategy_promotion():
    r=load()
    assert r['status']=='COMPLETE_MARKET_RESEARCH_NO_PROMOTION'
    assert r['allocation_authority'] is False
    assert r['live_money_authority'] is False
    assert r['promotion_decision']['parameter_changes_authorized'] is False
    assert r['staged_scaling']['conclusion']=='DO_NOT_FREEZE_TRIGGER_OR_ADD_SIZE'
    assert r['reset_recovery']['conclusion']=='THESIS_PLAUSIBLE_BUT_NO_THRESHOLD_FREEZE'

def test_holdout_is_reported_not_hidden():
    s=load()['staged_scaling']
    assert s['holdout']['n']==9
    assert s['holdout']['mean_forward_return_pct']<0
    assert load()['reset_recovery']['holdout_selected_proxy']['n']==0
    text=REPORT.read_text()
    assert 'NO PROMOTION' in text
    assert 'market data only' in text
