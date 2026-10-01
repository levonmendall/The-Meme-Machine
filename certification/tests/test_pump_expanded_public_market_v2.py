import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
R=ROOT/'research/public-market-7d-20261001/pump-expanded-v2.json'
S=ROOT/'research/public-market-7d-20261001/pump-compression-breakout-shadow-v1.json'
D=ROOT/'research/public-market-7d-20261001/PUMP_EXPANDED_V2.md'
def r():return json.loads(R.read_text())
def s():return json.loads(S.read_text())
def test_market_only_no_authority():
 x=r();assert x['source_policy']['public_market_data_only'] is True
 assert x['allocation_authority'] is False and x['live_money_authority'] is False
def test_primary_opportunity_is_compression_breakout():
 x=r()
 assert x['research_decision']['primary_pump_opportunity']=='compression-breakout'
 assert x['hypotheses_tested']['deep_or_shallow_reset_recovery']['robust_in_established_development_and_holdout']==0
def test_shadow_parameters():
 x=s();m=x['market_path'];e=x['provisional_shadow_exit']
 assert x['authority']=='RESEARCH_SHADOW_ONLY' and x['no_trade_authority'] is True
 assert m['base_lookback_observations']==5
 assert m['maximum_base_range_bps']==500
 assert m['breakout_min_bps']==250 and m['breakout_max_bps']==750
 assert e['hard_stop_bps']==-250 and e['take_profit_bps']==1000
 assert e['maximum_hold_seconds']==21600
def test_full_non_price_stack_required():
 assert len(s()['mandatory_non_price_gates'])>=8
def test_report_scope():
 t=D.read_text()
 assert 'COMPRESSION BREAKOUT IDENTIFIED' in t
 assert 'No allocation authority' in t
