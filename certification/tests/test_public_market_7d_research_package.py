import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
R=ROOT/'research/public-market-7d-20261001/results.json'
S=ROOT/'research/public-market-7d-20261001/provisional-shadow-parameters.json'
D=ROOT/'research/public-market-7d-20261001/REPORT.md'
def result():return json.loads(R.read_text())
def shadow():return json.loads(S.read_text())
def test_market_only_no_allocation():
 r=result(); assert r['data_policy']['public_market_data_only'] is True
 assert r['data_policy']['meme_machine_market_or_trade_data_used'] is False
 assert r['allocation_authority'] is False and r['live_money_authority'] is False
def test_pump_scaling_rejected():
 assert result()['staged_scaling']['pump_high_volume']['conclusion']=='REJECT_SIMPLE_PRICE_STRENGTH_SCALE_RULE_FOR_PUMP'
 assert shadow()['pump_staged_scaling']['enabled_for_shadow_observation'] is False
def test_pons_shadow_parameters_only():
 s=shadow()
 assert s['authority']=='RESEARCH_SHADOW_ONLY'
 assert s['pons_staged_scaling']['strength_from_recent_low_bps']==500
 assert s['pons_staged_scaling']['add_size_bps'] is None
 assert s['pons_reset_recovery']['minimum_drawdown_bps']==1500
 assert s['pons_reset_recovery']['minimum_recovery_from_trough_bps']==1000
 assert s['pons_reset_recovery']['allocation_authority'] is False
def test_no_pump_reset_threshold_freeze():
 s=shadow()['pump_reset_recovery']
 assert s['parameters_frozen'] is False and s['allocation_authority'] is False
def test_report_states_scope():
 t=D.read_text()
 assert 'conclusive for **research triage and shadow parameterization**' in t
 assert 'not** profitability certification' in t
