"""One bounded, fixed-input implementation replay; never policy discovery.

Captured account/receipt evidence proves decoder and quote arithmetic only.
Synthetic trajectories prove exact frozen boundaries, not market profitability.
"""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path
from certification.run import ROOT,git,source_integrity

FIXTURES={
 'pump':['tests/fixtures/mainnet_candidate_accounts.json','tests/fixtures/postgrad_pumpswap_mainnet.json','tests/fixtures/mainnet_trade.json'],
 'pons':['robinhood_tests/fixtures/pons_paper_lifecycle_35382359016.json','robinhood_tests/fixtures/pons_lineage_35378762520.json','robinhood_tests/fixtures/mainnet_read_summary.json'],
}
BUNDLES={
 'pump':['tests.test_postgrad_captured','tests.test_directional_capacity','tests.test_pumpswap_survivor','tests.test_pumpswap_survivor_evidence'],
 'pons':['robinhood_tests.test_captured','robinhood_tests.test_pons_capacity_persistence','robinhood_tests.test_pons_postgrad_survivor','robinhood_tests.test_pons_entry_confirmation_ordering'],
 'shared':['certification.tests.test_survivor_commit','certification.tests.test_survivor_risk_boundaries','certification.tests.test_survivor_history'],
}
GUARD='''import sys,ipaddress,unittest,json
forbidden=[]
def guard(event,args):
 if event=='socket.connect' and isinstance(args[1],tuple):
  try:local=ipaddress.ip_address(args[1][0]).is_loopback
  except ValueError:local=args[1][0]=='localhost'
  if not local:forbidden.append(event);raise RuntimeError('preserved_validation_external_socket_forbidden')
sys.addaudithook(guard)
r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:]))
print(json.dumps(dict(tests=r.testsRun,passed=r.wasSuccessful() and not forbidden,external_socket_attempts=len(forbidden))))
raise SystemExit(0 if r.wasSuccessful() and not forbidden else 1)
'''

def run(worktrees,output):
 roots=Path(worktrees).resolve();out=Path(output).resolve();out.parent.mkdir(parents=True,exist_ok=True)
 logdir=out.parent/'preserved-validation-logs';logdir.mkdir(exist_ok=True)
 identity=source_integrity(roots)
 fixtures={lane:{name:hashlib.sha256((roots/lane/name).read_bytes()).hexdigest() for name in names} for lane,names in FIXTURES.items()}
 bundles={}
 for lane,names in BUNDLES.items():
  env={k:v for k,v in os.environ.items() if not k.startswith(('MM_','GH_','GITHUB_')) and not any(w in k.upper() for w in ('SECRET','TOKEN','PRIVATE_KEY'))}
  env['PYTHONPATH']=str(ROOT)
  p=subprocess.run([sys.executable,'-c',GUARD,*names],cwd=ROOT if lane=='shared' else roots/lane,
      env=env,capture_output=True,text=True,timeout=150)
  (logdir/(lane+'.log')).write_text(p.stdout+p.stderr)
  try:observed=json.loads(p.stdout.strip().splitlines()[-1])
  except (ValueError,IndexError):observed=dict(passed=False,tests=None)
  bundles[lane]=dict(observed,exit_code=p.returncode,tests_selected=names)
 unchanged=identity==source_integrity(roots)
 result=dict(passed=unchanged and all(r['passed'] and r['exit_code']==0 for r in bundles.values()),
   integration_sha=git('rev-parse','HEAD'),fixed_input_passes=1,thresholds_changed=False,
   source_unchanged=unchanged,fresh_market_data_used=False,market_workflow_launched=False,
   fixtures=fixtures,bundles=bundles,
   captured_evidence_scope=['native captured protocol identity/decoding','Pump curve/PumpSwap executable quote arithmetic',
       'preserved Pons lifecycle and lineage metadata; no invented short-window demand'],
   synthetic_contract_scope=['capacity only shrinks; fragile 2x capacity; useful minimum survives',
       'point-in-time repeat flow; no future buyers; generation fencing and crash recovery',
       'Survivor survival/reset/base/continuation; exact retention and exit boundaries',
       'Mayhem agents excluded or unknown/active/unclean evidence gates admission',
       'incremental bounded history, immutable graduation, gap and capacity fail-closed'],
   unknown_historical_evidence=['complete seven-day authenticated Survivor price/demand trajectories',
       'authoritative Mayhem completion timestamps for historical candidates','historical Survivor fill and profitability outcomes'],
   profitability_claim=False,paper_only=True)
 out.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
 print(json.dumps(dict(passed=result['passed'],tests={k:v['tests'] for k,v in bundles.items()},historical_profitability='UNKNOWN'),sort_keys=True))
 return 0 if result['passed'] else 1

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--worktrees',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 raise SystemExit(run(a.worktrees,a.output))
