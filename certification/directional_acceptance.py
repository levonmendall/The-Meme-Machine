"""Six-regime deterministic integration gate. No provider or dispatch capability."""
import argparse,json,os,subprocess,sys
from pathlib import Path
from certification.journal import digest
from certification.run import ROOT,source_integrity,manifest,git

FOCUSED={
 'pump':['tests.test_directional_capacity','tests.test_pumpswap_survivor','tests.test_pumpswap_survivor_evidence','tests.test_pump_shared_survivor'],
 'pons':['robinhood_tests.test_pons_capacity_persistence','robinhood_tests.test_pons_entry_confirmation_ordering',
         'robinhood_tests.test_pons_postgrad_survivor','robinhood_tests.test_pons_shared_survivor'],
}

def run(worktrees,output):
 roots=Path(worktrees).resolve();out=Path(output).resolve();out.mkdir(parents=True,exist_ok=True)
 spec=manifest();base=json.loads(subprocess.check_output(['git','show',
   'af60b355995dfa960555288fa73808bb7aba5d25:certification/sources.json'],cwd=ROOT))
 checks=dict(exactly_four_lanes=set(spec['lanes'])=={'pump','pons','meteora','ramses'},
             meteora_unchanged=spec['lanes']['meteora']==base['lanes']['meteora'],
             ramses_unchanged=spec['lanes']['ramses']==base['lanes']['ramses'])
 observed=source_integrity(roots);components={};suites={}
 for lane in ('pump','pons'):
  env=dict(os.environ,PYTHONPATH=str(ROOT))
  code="import json; from certification.directional_sleeve import composite_policy,composite_hash; print(json.dumps(dict(policy=composite_policy(%r),hash=composite_hash(%r))))"%(lane,lane)
  actual=json.loads(subprocess.check_output([sys.executable,'-c',code],cwd=roots/lane,env=env))
  components[lane]=actual
  checks[lane+'_policy_identity']=(actual['hash']==spec['lanes'][lane]['policy_hash'] and actual['policy']==spec['lanes'][lane]['composite_policy'])
  checks[lane+'_one_sleeve']=actual['policy']['allocation']['one_sleeve'] is True and actual['policy']['allocation']['portfolio_allocation_increased'] is False
  # Socket audit makes an accidental provider call a failing gate, including in
  # any new adapter test. Local native replay needs no external connectivity.
  script="""import sys,unittest,ipaddress
forbidden=[]
def guard(event,args):
 if event=='socket.connect' and isinstance(args[1],tuple):
  try:local=ipaddress.ip_address(args[1][0]).is_loopback
  except ValueError:local=args[1][0]=='localhost'
  if not local:forbidden.append(event);raise RuntimeError('offline_external_socket_forbidden')
sys.addaudithook(guard)
suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:])
r=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if r.wasSuccessful() and not forbidden else 1)
"""
  p=subprocess.run([sys.executable,'-c',script,*FOCUSED[lane]],cwd=roots/lane,env=env,capture_output=True,text=True,timeout=120)
  (out/(lane+'.log')).write_text(p.stdout+p.stderr);suites[lane]=p.returncode==0
 checks['six_active_regimes']=sum(len(v['policy']['strategies']) for v in components.values())+2==6
 checks['focused_native_regressions']=all(suites.values())
 checks['prepared_sources_unchanged']=source_integrity(roots)==observed
 result=dict(passed=all(checks.values()),scope='six_regime_preserved_and_synthetic_integration',checks=checks,
             components=components,integration_sha=git('rev-parse','HEAD'),source_manifest_hash=digest(spec),
             external_market_collection=False,paper_only=True,live_money=False)
 (out/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
 print(json.dumps(dict(passed=result['passed'],checks=checks),sort_keys=True))
 return 0 if result['passed'] else 1
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--worktrees',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 raise SystemExit(run(a.worktrees,a.output))
