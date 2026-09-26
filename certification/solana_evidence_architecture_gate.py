"""Offline architecture gates for the composed Solana paper runtimes."""
import argparse,json,os,subprocess,sys
from pathlib import Path
from certification.run import source_integrity,git

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--worktrees',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);env=dict(os.environ,PYTHONPATH=str(ROOT))
    before=source_integrity(args.worktrees);rows=[]
    fixtures=ROOT/'tests/fixtures/solana_evidence_plane'
    commands=[('shared',ROOT,['-m','unittest','tests.test_solana_read_rpc','tests.test_solana_evidence_plane','tests.test_solana_evidence_transport','tests.test_solana_evidence_queries','tests.test_solana_evidence_fences','tests.test_solana_evidence_service_runtime','tests.test_run369_runtime','tests.test_solana_evidence_retention','tests.test_solana_retained_raw','tests.test_report_publisher_isolation','certification.tests.test_reserved_evidence_priority','-v']),
      ('pump-production',args.worktrees/'pump',['-m','unittest','tests.test_evidence_runtime_cutover','tests.test_run369_liveness','-v']),
      ('meteora-production',args.worktrees/'meteora',['-m','unittest','tests.test_evidence_runtime_cutover','tests.test_run369_admission','-v']),
      ('retained-warmup',args.worktrees/'meteora',['-m','certification.replay_retained_warmup','--fixture',str(fixtures/'run-368-meteora-warmup.json.gz')]),
      ('retained-position',args.worktrees/'meteora',['-m','certification.replay_retained_meteora','--fixture',str(fixtures/'run-368-meteora-journal.json')]),
      ('provider-topology',ROOT,['-m','certification.solana_provider_gate','--worktrees',str(args.worktrees)]),
      ('real-ipc',ROOT,['-m','certification.evidence_ipc_check'])]
    for name,cwd,command in commands:
        with (args.output/(name+'.log')).open('wb') as log:
            result=subprocess.run([sys.executable,*command],cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=120)
        rows.append(dict(name=name,exit_code=result.returncode))
        if result.returncode:break
    passed=len(rows)==len(commands) and all(r['exit_code']==0 for r in rows) and before==source_integrity(args.worktrees)
    audit=json.loads((fixtures/'pump-coverage-audit.json').read_text())
    result=dict(passed=passed,sha=git('rev-parse','HEAD'),source_diff_hashes=before,gates=rows,
        pump_retained_full_window_parity='PERMANENTLY_CENSORED_LEGACY_EVIDENCE',
        prospective_operational_validation='DEFERRED_REQUIRES_SEPARATE_AUTHORIZATION',
        retained_pump_cases_censored=len(audit['cases']),market_workflow_launched=False,provider_calls_to_market=0)
    (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,sort_keys=True))
    return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
