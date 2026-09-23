"""Run real SIGKILL probes against native ledger transactions in separate processes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

from certification.run import ROOT,atomic,source_integrity


def lane_check(lane,worktrees,output):
    folder=output/lane;folder.mkdir()
    command=[sys.executable,str(ROOT/'certification/native_crash.py'),'--lane',lane,'--db',str(folder/'native.sqlite')]
    def call(*args):
        return subprocess.run(command+list(args),cwd=worktrees/lane,capture_output=True,text=True,timeout=20)
    def read():
        r=call('--inspect')
        if r.returncode:raise AssertionError(r.stderr)
        return json.loads(r.stdout)
    rows=[]
    r=call('--step','0');assert r.returncode==-9,(lane,'genesis',r.returncode,r.stderr)
    initial=read()
    r=call('--step','1','--before-commit');assert r.returncode==-9,(lane,'precommit',r.stderr)
    assert read()==initial,(lane,'uncommitted_reservation_survived')
    rows.append(dict(boundary='before_reservation_commit',result='PROVEN',recovered=initial))
    for step,boundary in enumerate(('reservation','entry','monitor_or_exit_intent','settlement'),1):
        r=call('--step',str(step));assert r.returncode==-9,(lane,boundary,r.stderr)
        state=read();assert read()==state,(lane,'nondeterministic_reopen')
        if step in (1,2,4):
            duplicate=call('--step',str(step))
            assert read()==state,(lane,boundary,'duplicate_changed_state',duplicate.stderr)
        rows.append(dict(boundary='after_'+boundary+'_commit',result='PROVEN',recovered=state))
    final=read()
    if lane=='pump':assert final['cash']==1030 and final['reserved']==0 and final['open_positions']==0,final
    elif lane=='pons':assert final['cash']==1026 and final['remaining_cost_basis']==0,final
    elif lane=='ramses':assert final['available']==1030 and final['committed']==0 and final['open_positions']==0,final
    else:
        assert final['cash']==1_000_000_000+final['realized_pnl_lamports'],final
        assert final['settled']==1 and final['open_positions']==0 and final['reserved']==0,final
    return dict(lane=lane,passed=True,probes=rows,final=final,
        scope='native_ledger_SIGKILL_transaction_durability',
        fixture_kind='synthetic_ledger_inputs',
        qualification_proven=False,automatic_runner_recovery_proven=False,
        limitation='Reopens native books and issues the next native command; does not resume production discovery or lifecycle orchestration.')


def run(worktrees,output):
    worktrees=Path(worktrees).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    identity=source_integrity(worktrees)
    def checked(lane):
        try:return lane_check(lane,worktrees,output)
        except Exception as exc:return dict(lane=lane,passed=False,error=str(exc))
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(checked,('pump','pons','meteora','ramses')))
    result=dict(scope='native_ledger_crash_matrix',lanes=rows,passed=all(r['passed'] for r in rows),
        source_diff_hashes=identity,source_unchanged=source_integrity(worktrees)==identity,
        engineering_certification='NOT_CERTIFIED',natural_market_proof=False)
    atomic(output/'result.json',result)
    print(json.dumps(result,sort_keys=True),flush=True)
    return 0 if result['passed'] and result['source_unchanged'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--worktrees',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();sys.exit(run(args.worktrees,args.output))
