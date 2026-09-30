"""Exactly two sequential fresh process groups. Never retries a workload."""
import argparse,hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args()
    root=Path(a.root)
    assert not (HERE/'FOLLOWUP_STOP.json').exists(), 'astra_followup_hard_stop'
    assert os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert json.loads((root/'STATIC_PREFIX_VERIFICATION.json').read_text())['verified']
    assert not (root/'FOLLOWUP_STOP.json').exists()
    request=HERE/'execution-request.json';req=json.loads(request.read_text())
    ledger=root/'execution-ledger.jsonl'
    ledger.open('x').close()
    rows=[]
    for number,arm in enumerate(('control','treatment'),3):
        output=root/arm
        assert not output.exists()
        start=time.monotonic()
        entry=dict(material_execution_number=number,arm=arm,utc_start=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),
            runner=os.environ.get('RUNNER_NAME'),hostname=__import__('socket').gethostname(),
            run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
        with ledger.open('a') as stream:stream.write(json.dumps(dict(event='launch',**entry))+'\n')
        print('ARM_START '+json.dumps(entry),flush=True)
        with (root/(arm+'.log')).open('w') as log:
            proc=subprocess.Popen([sys.executable,str(HERE/'harness.py'),'--request',str(request),
                '--output',str(output),'--arm',arm],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            forced=False
            try:code=proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                forced=True
                os.killpg(proc.pid,signal.SIGKILL)
                code=proc.wait(timeout=10)
            # Native service joins its workers on normal exit. Kill any remaining
            # members of this completed process group before starting the other arm.
            residual=False
            try:os.killpg(proc.pid,0)
            except ProcessLookupError:pass
            else:
                residual=True
                os.killpg(proc.pid,signal.SIGKILL)
        end=time.monotonic()
        entry.update(pid=proc.pid,returncode=code,elapsed=end-start,
            forced_wall_bound=forced,residual_process_group=residual,
            utc_end=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
        if (output/'summary.json').exists():
            summary=json.loads((output/'summary.json').read_text())
            entry.update(completed_frames=summary['completed_frames'],source_seconds=summary['source_seconds'],
                stop_reason=summary['stop_reason'],failure=summary['failure'])
        else:entry.update(stop_reason='wall_time_bound' if forced else 'harness_failure_without_summary')
        rows.append(entry)
        with ledger.open('a') as stream:stream.write(json.dumps(dict(event='finished',**entry))+'\n')
        print('ARM_END '+json.dumps(entry),flush=True)
    write(root/'pair-executions.json',rows)
    write(root/'FOLLOWUP_STOP.json',dict(status='ASTRA_REVIEW_READY: SOURCE_OWNER_ABLATION_COMPLETE',
        stop_all_diagnostic_execution=True,executions_consumed=4,ceiling=6,unused=2,
        retry_authorized=False,production_repair_approved=False,production_repair_implemented=False,
        stage_e='RED',stage_f='NOT_STARTED',paper_only=True,
        compared_arms=['control','treatment'],same_job=True,sequential=True,
        historical_gate_preserved=True,scope='One pair completed; analysis/publication only. Stop for Astra.'))

if __name__=='__main__':main()
