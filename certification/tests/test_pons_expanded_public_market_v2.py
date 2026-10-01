import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
R=ROOT/'research/public-market-7d-20261001/pons-expanded-v2.json'
S=ROOT/'research/public-market-7d-20261001/pons-reset-recovery-shadow-v2.json'
D=ROOT/'research/public-market-7d-20261001/PONS_EXPANDED_V2.md'
def r():return json.loads(R.read_text())
def s():return json.loads(S.read_text())
def test_market_only_no_authority():
 x=r();assert x['source_policy']['public_market_data_only'] is True
 assert x['allocation_authority'] is False and x['live_money_authority'] is False
def test_reset_is_primary():
 assert r()['research_decision']['primary_pons_opportunity']=='reset-recovery'
 assert r()['staged_scaling']['conclusion']=='DEPRIORITIZE_STAGED_SCALING_KEEP_OBSERVATION_ONLY'
def test_shadow_v2_parameters():
 x=s();m=x['market_path'];e=x['provisional_shadow_exit']
 assert x['authority']=='RESEARCH_SHADOW_ONLY' and x['allocation_authority'] is False
 assert m['minimum_drawdown_bps']==1000
 assert m['minimum_recovery_from_trough_bps']==1250
 assert m['maximum_recovery_from_trough_bps']==2000
 assert m['stabilization_gap_observations']==3
 assert m['maximum_entry_above_preflush_high_bps']==500
 assert e['hard_stop_bps']==-750 and e['take_profit_bps']==1500
 assert e['maximum_hold_seconds']==21600
def test_non_price_gates_required():
 assert len(s()['mandatory_non_price_gates'])>=8
 assert s()['no_trade_authority'] is True
def test_report_scope():
 t=D.read_text()
 assert 'RESET-RECOVERY PRIORITIZED' in t
 assert 'zero allocation authority' in t.lower()
