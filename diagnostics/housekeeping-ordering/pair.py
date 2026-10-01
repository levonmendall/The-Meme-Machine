"""One control then one treatment, gated by tests; no automatic material retry."""
import argparse, hashlib, json, os, signal, socket, subprocess, sys, time
from pathlib import Path
HERE=Path(__file__).resolve().parent
def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args()
    root=Path(a.root)
    assert os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert not (HERE/'FOLLOWUP_STOP.json').exists()
    assert not (root/'FOLLOWUP_STOP.json').exists()
    gate=json.loads((root/'SAFETY_GATE.json').read_text())
    proof=json.loads((root/'STATIC_VERIFICATION.json').read_text())
    assert gate['passed'] is True and proof['verified'] is True
    assert gate['patch_sha256']==proof['patch_sha256']
    assert gate['tests_sha256']==proof['tests_sha256']
    request=HERE/'execution-request.json';req=json.loads(request.read_text())
    assert req['execute'] is True and req['planned_budget_before']==4
    assert req['astra_decision']=='HOUSEKEEPING_ORDERING_REPAIR_APPROVED_FOR_TESTING'
    ledger=root/'execution-ledger.jsonl';ledger.open('x').close()
    rows=[]
    try:
        for number,arm in enumerate(('control','treatment'),5):
            output=root/arm;assert not output.exists()
            checkout=root/'worktrees'/arm
            env=dict(os.environ,MM_HOUSEKEEPING_ARM=arm,
                MM_HOUSEKEEPING_DIAGNOSTIC_SHA=proof['diagnostic_sha'])
            entry=dict(material_execution_number=number,arm=arm,
                utc_start=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),
                runner=os.environ.get('RUNNER_NAME'),hostname=socket.gethostname(),
                run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
            with ledger.open('a') as stream:stream.write(json.dumps(dict(event='launch',**entry))+'\n')
            rows.append(entry)
            print('ARM_START '+json.dumps(entry),flush=True)
            start=time.monotonic()
            with (root/(arm+'.log')).open('w') as log:
                proc=subprocess.Popen([sys.executable,
                    str(checkout/'diagnostics/housekeeping-ordering/harness.py'),
                    '--request',str(request),'--output',str(output),'--arm',arm],
                    cwd=checkout,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                forced=False
                try:code=proc.wait(timeout=600)
                except subprocess.TimeoutExpired:
                    forced=True;os.killpg(proc.pid,signal.SIGKILL);code=proc.wait(timeout=10)
                residual=False
                try:os.killpg(proc.pid,0)
                except ProcessLookupError:pass
                else:residual=True;os.killpg(proc.pid,signal.SIGKILL)
            entry.update(pid=proc.pid,returncode=code,elapsed=time.monotonic()-start,
                forced_wall_bound=forced,residual_process_group=residual,
                utc_end=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
            if (output/'summary.json').exists():
                summary=json.loads((output/'summary.json').read_text())
                entry.update(completed_frames=summary['completed_frames'],
                    source_seconds=summary['source_seconds'],stop_reason=summary['stop_reason'],
                    failure=summary['failure'])
            else:entry['stop_reason']='wall_time_bound' if forced else 'harness_failure_without_summary'
            with ledger.open('a') as stream:stream.write(json.dumps(dict(event='finished',**entry))+'\n')
            print('ARM_END '+json.dumps(entry),flush=True)
    finally:
        write(root/'pair-executions.json',rows)
        consumed=4+len(rows)
        write(root/'FOLLOWUP_STOP.json',dict(
            status='HOUSEKEEPING_ORDERING_PAIR_STOP_FOR_ASTRA',
            stop_all_diagnostic_execution=True,executions_consumed=consumed,
            ceiling=6,unused=6-consumed,retry_authorized=False,
            production_promotion_approved=False,canonical_stage_e_approved=False,
            successor_freeze_approved=False,stage_e='RED',stage_f='NOT_STARTED',
            paper_only=True,compared_arms=[r['arm'] for r in rows],
            same_job=True,sequential=True,historical_gates_preserved=True,
            scope='Only evidence analysis/publication remains; stop for Astra.'))

if __name__=='__main__':main()
