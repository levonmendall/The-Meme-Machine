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
class Plumbing(ast.NodeTransformer):
    """Remove only enumerated operational adapters for economic AST comparison."""
    def visit_Constant(self,node):
        if isinstance(node.value,str):
            for old,new in ENV.items():node.value=node.value.replace(old,new)
            node.value=node.value.replace('certification.','meme_machine.runtime.')
        return node
    def visit_ImportFrom(self,node):
        if node.module=='meme_machine.runtime.storage' or node.module=='meme_machine.runtime.native_boundary':return None
        if node.module:node.module=node.module.replace('certification.','meme_machine.runtime.')
        return node
    def visit_FunctionDef(self,node):
        if node.name=='_stop_sleep':return None
        return self.generic_visit(node)
    def visit_Expr(self,node):
        if isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):return None
        call=node.value
        if isinstance(call,ast.Call):
            if isinstance(call.func,ast.Name) and call.func.id=='audit_ring':return None
            if isinstance(call.func,ast.Attribute) and call.func.attr=='execute' and call.args and isinstance(call.args[0],ast.Constant):
                sql=call.args[0].value
                if isinstance(sql,str) and any(sql.startswith('DELETE FROM '+table+' ') for table in ('evidence','gas_quotes')):return None
        return self.generic_visit(node)
    def visit_Assign(self,node):
        if any(isinstance(t,ast.Attribute) and t.attr=='portfolio' for t in node.targets):return None
        return self.generic_visit(node)
    def visit_If(self,node):
        text=ast.unparse(node.test)
        if text in ("getattr(self, 'portfolio', None)","self.records >= 8192"):return None
        return self.generic_visit(node)
    def visit_Call(self,node):
        if isinstance(node.func,ast.Name) and node.func.id=='_stop_sleep':node.func=ast.Attribute(value=ast.Name(id='time',ctx=ast.Load()),attr='sleep',ctx=ast.Load())
        node.keywords=[k for k in node.keywords if k.arg!='retention']
        return self.generic_visit(node)
ENV={'MM_CERTIFICATION_RUN_ID':'MM_PAPER_EPOCH','MM_CERTIFICATION_LANE':'MM_RUNTIME_LANE',
     'MM_CERTIFICATION_RPC_CACHE_DB':'MM_RPC_CACHE_DB','MM_CERTIFICATION_RPC_CAPABILITIES':'MM_RPC_CAPABILITIES',
     'MM_CERTIFICATION_PROVIDER_DB':'MM_PROVIDER_DB'}
def normalized(source):return ast.dump(Plumbing().visit(ast.parse(source)),include_attributes=False)
checked=[];plumbing=[]
for p in sorted((ROOT/'meme_machine/lanes/ramses').rglob('*.py')):
 rel=str(p.relative_to(ROOT));old=before(rel);new=p.read_text()
 assert normalized(old)==normalized(new),rel
 checked.append(rel)
 if ast.dump(ast.parse(old))!=ast.dump(ast.parse(new)):plumbing.append(rel)
for name in ('RAMSES_THETA_HARVEST_V3.json','RAMSES_WIDE_MAKER_V4.json'):
 rel='meme_machine/lanes/ramses/'+name
 if (ROOT/rel).exists():assert before(rel)==(ROOT/rel).read_text(),rel
assert subprocess.check_output(['git','show','7a516a6a92be9347661ac0e7f560971c171a0931:meme_machine/solana_owner_admission.py'],cwd=ROOT)==(ROOT/'meme_machine/solana_owner_admission.py').read_bytes()
print(json.dumps(dict(result='PASS',pre_change_commit=BASE,ramses_economic_modules_unchanged=len(checked),
    ramses_plumbing_modules=plumbing,entry_and_survivor_policies_only_approved_deltas=True,
    owner_admission_scheduler_byte_identical_to_engineering_base=True)))
