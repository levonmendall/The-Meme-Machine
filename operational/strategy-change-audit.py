"""Offline approved-policy comparison against the pre-change commit."""
import ast,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE='e34c38c78061834ad2892a897fcdd52fc438b061'
def before(path):return subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT,text=True)
def value(source,name):
 nodes=[n for n in ast.parse(source).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets)]
 ns={};exec(compile(ast.Module(nodes,type_ignores=[]),'<policy>','exec'),{'STRATEGY_ID':'strategy','STRATEGY_VERSION':'strategy'},ns);return ns[name]
def check(rel,name,expected):
 a=value(before(rel),name);b=value((ROOT/rel).read_text(),name)
 assert {k:(a.get(k),b.get(k)) for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}==expected,rel
p='meme_machine/lanes/pons/pons_selective_continuation.py'
check(p,'ENTRY_THRESHOLDS',{'capital_size_bps':(25,500)})
for name in ('POST_GRAD_THRESHOLDS','REENTRY_POLICY','BREAKOUT_THRESHOLDS'):check(p,name,{})
check(p,'EXIT_POLICY',{'first_profit_sell_bps':(3333,2500),'runner_trailing_drawdown_bps':(1000,1200),
 'min_adverse_sell_buy_ratio_bps':(None,12000),'tail_arm_bps':(None,10000),'tail_gain_giveback_bps':(None,4000)})
for rel in ('pump/pumpswap_survivor.py','pons/pons_postgrad_survivor.py'):
 path='meme_machine/lanes/'+rel;a=value(before(path),'POLICY');b=value((ROOT/path).read_text(),'POLICY')
 if rel.startswith('pump'):a['target_sleeve_bps']=500
 else:a['execution']['target_capital_bps']=500
 assert a==b,path
path='meme_machine/lanes/pump/pump_acceleration_strategy.py'
def scalars(src):
 cls=next(n for n in ast.parse(src).body if isinstance(n,ast.ClassDef) and n.name=='FrozenPolicy')
 return {n.target.id:ast.dump(n.value) for n in cls.body if isinstance(n,ast.AnnAssign)}
a=scalars(before(path));b=scalars((ROOT/path).read_text())
assert {k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}=={'version','trailing_drawdown_bps','tail_arm_bps','tail_gain_giveback_bps'}
checked=0
for p in (ROOT/'meme_machine/lanes/ramses').rglob('*.py'):
 rel=str(p.relative_to(ROOT));old=before(rel).replace('certification.','meme_machine.runtime.')
 assert ast.dump(ast.parse(old))==ast.dump(ast.parse(p.read_text().replace("certification.","meme_machine.runtime."))),rel
 checked+=1
for name in ('RAMSES_THETA_HARVEST_V3.json','RAMSES_WIDE_MAKER_V4.json'):
 rel='meme_machine/lanes/ramses/'+name
 if (ROOT/rel).exists():assert before(rel)==(ROOT/rel).read_text(),rel
print(json.dumps(dict(result='PASS',pre_change_commit=BASE,ramses_modules_unchanged=checked,
    entry_and_survivor_policies_only_approved_deltas=True)))
