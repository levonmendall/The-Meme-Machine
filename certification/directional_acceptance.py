"""Six-regime deterministic integration gate. No provider or dispatch capability."""
import argparse,json,os,subprocess,sys
from pathlib import Path
from certification.journal import digest
from certification.run import ROOT,source_integrity,manifest,git

# The approved alpha remains byte-identical while certified infrastructure
# overlays may change. Pin the successful Run 376 operational Ramses patch.
PRESERVED_INFRA={'certification/patches/run371-ramses-transient-pressure.patch'}
METEORA_RUNTIME_PATCH='certification/patches/run380-meteora-candidate-retention.patch'
INFRA_OVERLAYS=PRESERVED_INFRA|{
 'certification/patches/run377-ramses-rpc-state-attribution.patch',METEORA_RUNTIME_PATCH,
 'certification/patches/autonomous-ramses-campaign-recovery.patch',
 'certification/patches/autonomous-ramses-atomic-funding.patch',
 'certification/patches/autonomous-meteora-unfilled-recovery.patch',
 'certification/patches/autonomous-meteora-evidence-checkpoints.patch',
}
# These implementation-only files are additionally pinned by source_integrity.
# Strategy/policy/workflow hashes remain identical to the approved contracts.
RAMSES_RECOVERY_FILES={
 'robinhood_research/ramses_campaign.py','robinhood_research/ramses_extended_test.py',
 'robinhood_tests/test_ramses_continuous_campaign.py',
}
METEORA_RECOVERY_FILES={
 'meme_machine/dlmm_independent_accounting.py','tests/solana_dlmm_independent_v1.py',
 'tests/test_dlmm_independent_accounting.py',
}
METEORA_THRESHOLD_PATCH='certification/patches/meteora-moderate-admission-thresholds-v1.patch'
METEORA_POLICY_HASH='78a9658dfc8dda7a35c20486527f24553b00b9a20b8140e65dedde90c9a93408'
METEORA_COMPOSED_FILES={
 '.github/workflows/solana-dlmm-independent-v1.yml':'44c899b3fa9b94f0942afb61ced69c4d76a8291e710c854742d9641e2f914dbe',
 'SOLANA_DLMM_INDEPENDENT_V1.json':'f64304f125edfde0af5dff04b53332bd811bce47cf27fd72e611dafc09abd916',
}
METEORA_MODERATE_NOTE={
 'revision':'moderate-admission-thresholds-v1',
 'min_authenticated_fee_density_24h_pct':[5,4],
 'min_competing_range_liquidity_to_capital_multiple':[5,4],
 'min_two_way_balance':[0.25,0.2],
 'max_drift_ratio':[0.75,0.8],
 'max_stress_unwind_loss_bps':[150,200],
 'expected_net_positive_gate_unchanged':True,
 'range_width_unchanged':True,
 'core_hold_unchanged':True,
 'exit_thresholds_changed':False,
 'paper_only_unchanged':True,
}
METEORA_ADMISSION_SCOPE=(
 'exactly-one-WSOL-leg nonblacklisted pools with a fresh authenticated finalized swap, '
 'exact 12-second warmup, authenticated local fee density >=4%/day, two-way balance >=0.20, '
 'competing range liquidity >=4x capital, executable local range depth, drift ratio <=0.80, '
 'stress unwind loss <=200 bps and strictly positive projected four-hour after-cost net'
)

def strategy_contract(row):
 value=json.loads(json.dumps(row))
 value.pop('source_diff_sha256',None)
 value.pop('integration_overlay_files',None)
 composed=value.pop('composed_file_hashes',value.get('file_hashes',{}))
 value['file_hashes']={k:v for k,v in composed.items() if k not in RAMSES_RECOVERY_FILES}
 value['overlay_patches']=[p for p in value.get('overlay_patches',[]) if p not in INFRA_OVERLAYS]
 return value

def meteora_base_contract(row):
 """Strip only the exact v14 threshold identity; every unrelated field must match."""
 value=json.loads(json.dumps(row))
 value.pop('source_diff_sha256',None)
 value.pop('policy_hash',None)
 value.pop('composed_file_hashes',None)
 value.pop('integration_overlay_files',None)
 value['overlay_patches']=[
  p for p in value.get('overlay_patches',[])
  if p not in INFRA_OVERLAYS and p!=METEORA_THRESHOLD_PATCH
 ]
 execution=value.get('execution_certification') or {}
 execution.pop('moderate_admission_thresholds_v1',None)
 prospect=value.get('prospect_admission') or {}
 prospect.pop('investment_evaluation_scope',None)
 return value

def meteora_threshold_revision_is_bounded(row,prior):
 prospect=row.get('prospect_admission') or {}
 return all((
  meteora_base_contract(row)==meteora_base_contract(prior),
  row.get('policy_hash')==METEORA_POLICY_HASH,
  [p for p in row.get('overlay_patches',[]) if p not in INFRA_OVERLAYS]==
   [p for p in prior.get('overlay_patches',[]) if p not in INFRA_OVERLAYS]+[METEORA_THRESHOLD_PATCH],
  {k:v for k,v in row.get('composed_file_hashes',{}).items() if k not in METEORA_RECOVERY_FILES}==METEORA_COMPOSED_FILES,
  (row.get('execution_certification') or {}).get('moderate_admission_thresholds_v1')==METEORA_MODERATE_NOTE,
  prospect.get('investment_evaluation_scope')==METEORA_ADMISSION_SCOPE,
  prospect.get('strategy_thresholds_changed') is True,
  prospect.get('profitability_authority') is True,
 ))

FOCUSED={
 'pump':['tests.test_directional_capacity','tests.test_pumpswap_survivor','tests.test_pumpswap_survivor_evidence','tests.test_pump_shared_survivor'],
 'pons':['robinhood_tests.test_pons_capacity_persistence','robinhood_tests.test_pons_entry_confirmation_ordering',
         'robinhood_tests.test_pons_postgrad_survivor','robinhood_tests.test_pons_shared_survivor'],
 'meteora':['tests.test_solana_dlmm_independent_v1'],
}

def offline_suite(roots,lane,names,out):
 env=dict(os.environ,PYTHONPATH=str(ROOT))
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
 p=subprocess.run([sys.executable,'-c',script,*names],cwd=roots/lane,env=env,
                  capture_output=True,text=True,timeout=120)
 (out/(lane+'.log')).write_text(p.stdout+p.stderr)
 return p.returncode==0

def run(worktrees,output):
 roots=Path(worktrees).resolve();out=Path(output).resolve();out.mkdir(parents=True,exist_ok=True)
 spec=manifest()
 original=json.loads(subprocess.check_output(['git','show',
   'af60b355995dfa960555288fa73808bb7aba5d25:certification/sources.json'],cwd=ROOT))
 prior=json.loads(subprocess.check_output(['git','show',
   '48e46b27086a8058fcbd7752a42420c1f9186af7:certification/sources.json'],cwd=ROOT))
 checks=dict(
  exactly_four_lanes=set(spec['lanes'])=={'pump','pons','meteora','ramses'},
  meteora_threshold_revision_bounded=meteora_threshold_revision_is_bounded(
      spec['lanes']['meteora'],prior['lanes']['meteora']),
  ramses_unchanged=strategy_contract(spec['lanes']['ramses'])==strategy_contract(original['lanes']['ramses']),
 )
 checks['preserved_ramses_runtime_repair']=all(
  (ROOT/p).read_bytes()==subprocess.check_output(
   ['git','show','2d93e6b5fdb751a3a3e9b057cca759bb0549839f:'+p],cwd=ROOT)
  for p in PRESERVED_INFRA
 )
 observed=source_integrity(roots);components={};suites={}
 for lane in ('pump','pons'):
  env=dict(os.environ,PYTHONPATH=str(ROOT))
  code="import json; from certification.directional_sleeve import composite_policy,composite_hash; print(json.dumps(dict(policy=composite_policy(%r),hash=composite_hash(%r))))"%(lane,lane)
  actual=json.loads(subprocess.check_output([sys.executable,'-c',code],cwd=roots/lane,env=env))
  components[lane]=actual
  checks[lane+'_policy_identity']=(
   actual['hash']==spec['lanes'][lane]['policy_hash']
   and actual['policy']==spec['lanes'][lane]['composite_policy']
  )
  checks[lane+'_one_sleeve']=(
   actual['policy']['allocation']['one_sleeve'] is True
   and actual['policy']['allocation']['portfolio_allocation_increased'] is False
  )
 for lane,names in FOCUSED.items():
  suites[lane]=offline_suite(roots,lane,names,out)
 checks['six_active_regimes']=sum(len(v['policy']['strategies']) for v in components.values())+2==6
 checks['focused_native_regressions']=all(suites.values())
 checks['prepared_sources_unchanged']=source_integrity(roots)==observed
 result=dict(
  passed=all(checks.values()),scope='six_regime_preserved_and_synthetic_integration',
  checks=checks,components=components,integration_sha=git('rev-parse','HEAD'),
  source_manifest_hash=digest(spec),external_market_collection=False,
  paper_only=True,live_money=False,
 )
 (out/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
 print(json.dumps(dict(passed=result['passed'],checks=checks),sort_keys=True))
 return 0 if result['passed'] else 1

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--worktrees',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 raise SystemExit(run(a.worktrees,a.output))
