"""Control plane: publish/read back declaration; time and preserve six slots."""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from core import ASSEMBLY,BASE,COHORT,INFRA,MODES,MOUNT,PERF_NS,PYTHON,S,T,canonical,clean_env,file_sha,persist,read,runtime_command,sha,storage

API='https://api.github.com/repos/levonmendall/The-Meme-Machine/'
EVIDENCE_PATH='diagnostics/stage-e-observer-v2-self-hosted-execution/'
EXECUTION_KEY='observer-v2-20261002-exact-7a516a6a'


def api(method,path,row=None):
    request=urllib.request.Request(API+path,data=canonical(row) if row is not None else None,
        headers={'Authorization':'Bearer '+os.environ['GH_OBSERVER_TOKEN'],
            'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28',
            'Content-Type':'application/json'},method=method)
    with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)


def execution():
    return MOUNT/'ov2'/('r'+os.environ['GITHUB_RUN_ID'])


def publish(name,payload,branch):
    path=EVIDENCE_PATH+name
    result=api('PUT','contents/'+path,dict(message='[skip ci] Preserve observer '+name,
        content=base64.b64encode(payload).decode(),branch=branch))
    commit=result['commit']['sha']
    got=api('GET','contents/'+path+'?ref='+commit)
    if base64.b64decode(got['content'])!=payload:raise ValueError('github_evidence_readback')
    return dict(commit_sha=commit,path=path,sha256=sha(payload),readback_success=True,
        url='https://github.com/levonmendall/The-Meme-Machine/blob/'+commit+'/'+path)


def configure():
    root=execution();root.mkdir(parents=True,exist_ok=False)
    authority=BASE/'EXECUTION_AUTHORITY.json'
    fd=os.open(authority,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o444)
    with os.fdopen(fd,'wb') as f:
        f.write(canonical(dict(run_id=os.environ['GITHUB_RUN_ID'],attempt=1,slots=6)));f.flush();os.fsync(f.fileno())
    if os.environ['GITHUB_RUN_ATTEMPT']!='1':raise ValueError('automatic_rerun_forbidden')
    if os.environ['RUNNER_NAME']!='the meme machine' or __import__('socket').gethostname()!='ubuntu-gd-2vcpu-8gb-nyc1':
        raise ValueError('runner_identity')
    prep=read(BASE/'PREPARATION.json');env=read(BASE/'fresh-environment.json')
    if not prep['passed'] or prep['started_trials']!=0:raise ValueError('preparation_gate')
    if prep['infrastructure_path']!=str(INFRA):raise ValueError('infrastructure_path')
    if file_sha(INFRA/'INFRASTRUCTURE.json')!=prep['infrastructure_manifest_sha256']:raise ValueError('infrastructure_gate')
    for name,info in read(INFRA/'INFRASTRUCTURE.json')['files'].items():
        if file_sha(INFRA/name)!=info['sha256']:raise ValueError('infrastructure_content_gate')
    if file_sha(BASE/'fresh-environment.json')!=prep['environment_sha256']:raise ValueError('environment_file_gate')
    import sys
    sys.path[:]=[str(INFRA),str(BASE/'assembly/source'),env['stdlib'],env['stdlib']+'/lib-dynload',env['dependency_root']]
    from certification.stage_e_native_v2.binding import verify_assembly,environment_identity
    checked=verify_assembly(BASE/'assembly',ASSEMBLY)
    fresh=environment_identity()
    if fresh!={k:v for k,v in env.items() if k not in ('hostname','cpu_count','affinity','runtime_source')}:
        raise ValueError('fresh_environment_drift')
    tape=read(BASE/'tape/TAPE.json')
    if file_sha(BASE/'tape/TAPE.json')!=prep['tape_manifest_sha256'] or file_sha(tape['tape'])!=tape['physical_sha256']:
        raise ValueError('immutable_tape_gate')
    jobs=api('GET','actions/runs/'+os.environ['GITHUB_RUN_ID']+'/jobs')['jobs']
    eligible=[j for j in jobs if j['runner_name']=='the meme machine' and j['runner_id']==21]
    if len(jobs)!=1 or len(eligible)!=1:raise ValueError('single_job_actual_runner')
    routing=['self-hosted','linux','x64','meme-machine-stage-e-observer']
    if [x.lower() for x in eligible[0]['labels']]!=routing:raise ValueError('actual_job_targeting')
    workspace=Path(os.environ['GITHUB_WORKSPACE'])
    workflow=workspace/'.github/workflows/non-market-certification.yml'
    if os.environ['GITHUB_SHA']!=os.environ['OBSERVER_EXPECTED_SHA'] or os.environ['GITHUB_WORKFLOW_SHA']!=os.environ['GITHUB_SHA']:
        raise ValueError('immutable_workflow_identity')
    contract=read(BASE/'assembly/source/certification/stage_e_native_v2/observer-contract-v2.json')
    identity=dict(candidate_sha=S,candidate_tree=T,assembly_digest=ASSEMBLY,
        plan_hash=checked['identity']['plan_hash'],input_manifest_hash=checked['identity']['input_manifest_hash'],
        environment_sha256=prep['environment_sha256'],infrastructure_manifest_sha256=prep['infrastructure_manifest_sha256'],
        tape_manifest_sha256=prep['tape_manifest_sha256'],workflow_sha=os.environ['GITHUB_SHA'],
        workflow_file_sha256=file_sha(workflow),run_id=os.environ['GITHUB_RUN_ID'],attempt=1)
    declaration=dict(version='executable-equal-byte-observer-predeclaration-v1',
        executable=True,paper_only=True,stage_e='RED',stage_f='NOT STARTED',
        astra_authority=['AUTHORIZE_BOUND_EQUAL_BYTE_OBSERVER_WORKLOAD','RESUME_OBSERVER_ON_DURABLE_EXECUTOR'],
        execution_key=EXECUTION_KEY,identity=identity,
        runner=dict(name='the meme machine',runner_id=21,hostname='ubuntu-gd-2vcpu-8gb-nyc1',droplet_id=605465049,
            actual_job_id=eligible[0]['id'],routing_labels=routing,
            unique_eligibility='User confirmed only this repository runner carries the unique label; inventory API denied administration access.'),
        workflow=dict(path='.github/workflows/non-market-certification.yml',job=eligible[0]['name'],
            timeout_minutes=720,matrix=False,cancel_in_progress=False,rerun=False,migration=False,
            pinned_actions=['11bd71901bbe5b1630ceea73d27597364c9af683','ea165f8d65b6e75b540449e92b4886f43607fa02']),
        preparation=prep,tape=tape,observer_contract=contract,
        modes=MODES,cohort=[dict(id=name,frames=count) for name,count in COHORT],
        trials=[dict(sequence=n,mode=mode,pair=(n+1)//2,
            id=f'{EXECUTION_KEY}-t{n:02d}-p{(n+1)//2}-{mode}',status='UNUSED') for n,mode in enumerate(MODES,1)],
        clock=dict(wall_epoch=1800000000,monotonic_epoch=100,
            anchor='real monotonic_ns at first source-data release of each member',
            afterward='real speed; all overhead/pauses/backpressure/maintenance/sleeps/scheduler delays consume headroom',
            trial_retiming=False),
        timing=dict(clock='real time.perf_counter_ns',start='before isolated trial process startup and all complete-cohort setup',
            end='after four members, native teardown, observer joins, required persistence, all helpers terminate',
            no_subtraction=True,no_double_count=True,uploads_inside=False),
        storage=storage(),preservation='fsynced per-trial raw archive and inventories plus immutable GitHub artifact/readback receipt before advancing',
        no_warmups=True,no_retries=True,no_replacements=True,started_trials=0,started_members=0,
        strict_acceptance='sum(observed_ns-baseline_ns)*100 < sum(baseline_ns); equality fails; native observer.verify()',
        stop='STOP FOR ASTRA; no prepared qualification, canonical Stage E or Stage F')
    branch='diagnostics/stage-e-observer-v2-results-'+os.environ['GITHUB_RUN_ID']
    api('POST','git/refs',dict(ref='refs/heads/'+branch,sha=os.environ['GITHUB_SHA']))
    data=canonical(declaration)+b'\n';publication=publish('PREDECLARATION.json',data,branch)
    persist(root/'PREDECLARATION.json',declaration)
    persist(root/'PREDECLARATION_READBACK.json',publication)
    ledger=dict(version='observer-unused-slot-ledger-v1',declaration_sha256=sha(data),
        evidence_branch=branch,identity=identity,slots=[dict(sequence=n,mode=mode,status='UNUSED') for n,mode in enumerate(MODES,1)],
        started_trials=0,started_members=0,retries=0,invalid_pairs=0)
    persist(root/'LEDGER.json',ledger)
    # Only a successful remote readback creates the executable gate.
    persist(root/'READY.json',dict(declaration_sha256=sha(data),publication=publication))
    print(json.dumps(dict(phase='DECLARED_AND_READ_BACK',publication=publication,started_trials=0)),flush=True)


def processes_stopped(folder,timeout=30):
    deadline=time.monotonic()+timeout
    while True:
        alive=[]
        for path in folder.rglob('ORIGIN-*-initialized.json'):
            row=read(path);pid=row['pid'];status=Path('/proc')/str(pid)/'stat'
            if status.exists():
                try:
                    state=status.read_text().rsplit(')',1)[1].split()[0]
                    if state!='Z':alive.append(pid)
                except FileNotFoundError:pass
        if not alive:return True
        if time.monotonic()>deadline:return False
        time.sleep(.05)


def run_trial(number):
    root=execution();ledger=read(root/'LEDGER.json');ready=read(root/'READY.json')
    if ready['declaration_sha256']!=ledger['declaration_sha256']:raise ValueError('declaration_readback_gate')
    if number!=ledger['started_trials']+1 or ledger['slots'][number-1]['status']!='UNUSED':raise ValueError('slot_already_consumed')
    if number>1 and not (root/f't{number-1}'/'DURABLE.json').exists():raise ValueError('previous_trial_not_durable')
    slot=ledger['slots'][number-1];slot['status']='STARTED';ledger['started_trials']=number
    persist(root/'LEDGER.json',ledger)
    prep=read(BASE/'PREPARATION.json')
    start=PERF_NS()
    folder=root/f't{number}';folder.mkdir(exist_ok=False)
    params=folder/'params.json'
    persist(params,dict(sequence=number,mode=MODES[number-1],output=str(folder),
        environment=read(BASE/'fresh-environment.json'),os_tools=prep['os_tools'],
        infrastructure_manifest_sha256=prep['infrastructure_manifest_sha256'],
        declaration_sha256=ledger['declaration_sha256']))
    lock=folder/'MEASURED.lock';lock.write_bytes(b'active')
    child_env=clean_env(params)
    try:
        with (folder/'trial.log').open('wb') as log:
            child=subprocess.Popen(['unshare','--net',*runtime_command('bootstrap.py','--trial')],
                env=child_env,cwd=BASE/'candidate-checkout',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            persist(folder/'STARTED.json',dict(sequence=number,mode=MODES[number-1],pid=child.pid,real_start_ns=start))
            code=child.wait(timeout=3600)
        stopped=processes_stopped(folder)
        if not stopped:
            os.killpg(child.pid,signal.SIGTERM)
            stopped=processes_stopped(folder,15)
        end=PERF_NS()
        result=read(folder/'TRIAL_RESULT.json') if (folder/'TRIAL_RESULT.json').exists() else None
        origins=[read(p) for p in folder.rglob('ORIGIN-*.json')]
        provider_files=list(folder.rglob('PROVIDER_ATTEMPT-*.json'))
        receipts_ok=bool(origins) and all(not r['provider_attempts'] and r['isolated']==1 and r['no_site']==1 for r in origins)
        source_receipts=[read(p) for p in folder.rglob('SOURCE_RECEIPT.json')]
        declaration=read(root/'PREDECLARATION.json')
        expected=declaration['tape']['members']
        tape_ok=len(source_receipts)==4 and all(r['source_frames_released']==e['frames']
            and r['tape']['encoded_prefix_sha256']==e['encoded_prefix_sha256']
            and r['tape']['decoded_canonical_sha256']==e['decoded_canonical_sha256']
            for r,e in zip(sorted(source_receipts,key=lambda r:[x[0] for x in COHORT].index(r['member'])),expected))
        valid=bool(code==0 and result and result['valid'] and stopped and receipts_ok and tape_ok and not provider_files)
        measurement=dict(sequence=number,mode=MODES[number-1],start_ns=start,end_ns=end,
            elapsed_ns=end-start,valid=valid,exit_code=code,helpers_stopped=stopped,
            origins_valid=receipts_ok,tape_valid=tape_ok,provider_attempts=len(provider_files),
            complete_members=len(source_receipts),declaration_sha256=ledger['declaration_sha256'])
        persist(folder/'MEASUREMENT.json',measurement)
        slot.update(status='COMPLETED' if valid else 'INVALID',measurement=measurement)
        if not valid:ledger['invalid_pairs']=1
    except BaseException as exc:
        if 'child' in locals() and child.poll() is None:
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=15)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        persist(folder/'INTERRUPTION.json',dict(reason=type(exc).__name__,sequence=number))
        slot['status']='INTERRUPTED'
        raise
    finally:
        lock.unlink(missing_ok=True)
        ledger['started_members']=sum(read(p)['started'] for p in root.glob('t*/MEMBERS_STARTED.json'))
        persist(root/'LEDGER.json',ledger)
    if not measurement['valid']:raise ValueError('trial_invalid_no_replacement')


def preserve(number):
    root=execution();folder=root/f't{number}'
    if not folder.exists():return
    if (folder/'MEASURED.lock').exists() or not processes_stopped(folder):raise ValueError('upload_would_overlap_measurement')
    inventory={str(p.relative_to(folder)):dict(bytes=p.stat().st_size,sha256=file_sha(p))
        for p in sorted(folder.rglob('*')) if p.is_file()}
    archive=root/f'TRIAL-{number}.tar.gz'
    with tarfile.open(archive,'w:gz',compresslevel=6) as target:
        for path in sorted(folder.rglob('*')):
            if path.is_file():target.add(path,arcname=str(path.relative_to(folder)),recursive=False)
    with archive.open('rb') as f:os.fsync(f.fileno())
    # Verify the exact raw byte inventory from the archive before reclaiming DBs.
    with tarfile.open(archive,'r:gz') as source:
        names=source.getnames()
        if set(names)!=set(inventory):raise ValueError('raw_archive_membership')
        for name,info in inventory.items():
            h=__import__('hashlib').sha256();size=0
            with source.extractfile(name) as f:
                for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block);size+=len(block)
            if h.hexdigest()!=info['sha256'] or size!=info['bytes']:raise ValueError('raw_archive_readback')
    persist(root/f'INVENTORY-{number}.json',dict(sequence=number,raw_files=inventory,
        archive_sha256=file_sha(archive),archive_bytes=archive.stat().st_size))
    for path in folder.glob('m*/d'):shutil.rmtree(path)
    print(json.dumps(dict(phase='TRIAL_PRESERVED',sequence=number,archive_bytes=archive.stat().st_size)),flush=True)


def durable(number):
    root=execution();ledger=read(root/'LEDGER.json');folder=root/f't{number}'
    if not folder.exists():return
    artifact=int(os.environ['OBSERVER_ARTIFACT_ID']);digest=os.environ['OBSERVER_ARTIFACT_DIGEST']
    artifact_row=api('GET','actions/artifacts/'+str(artifact))
    if artifact_row['digest']!='sha256:'+digest or artifact_row['workflow_run']['id']!=int(os.environ['GITHUB_RUN_ID']):
        raise ValueError('artifact_identity_readback')
    row=dict(sequence=number,artifact_id=artifact,artifact_digest=digest,
        artifact_name=artifact_row['name'],inventory=read(root/f'INVENTORY-{number}.json'),
        measurement=read(folder/'MEASUREMENT.json') if (folder/'MEASUREMENT.json').exists() else None,
        artifact_readback_success=True,ledger=ledger)
    publication=publish(f'TRIAL-{number}-DURABILITY.json',canonical(row)+b'\n',ledger['evidence_branch'])
    persist(folder/'DURABLE.json',dict(publication=publication,artifact_id=artifact,artifact_digest=digest))


def finalize():
    root=execution();ledger=read(root/'LEDGER.json') if (root/'LEDGER.json').exists() else None
    if not ledger:
        row=dict(outcome='IDENTITY_OR_WORKLOAD_MISMATCH',reason='Executable predeclaration gate did not complete',started_trials=0)
    else:
        slots=ledger['slots'];started=ledger['started_trials']
        if any(s['status']=='INTERRUPTED' for s in slots) or any((root/f't{s["sequence"]}'/'INTERRUPTION.json').exists() for s in slots):
            row=dict(outcome='EXECUTION_INTERRUPTED',reason='Started execution interrupted')
        elif any(s['status']=='INVALID' for s in slots):
            row=dict(outcome='INVALID_PAIR',reason='Started member or cohort failed its bound workload/observation/receipt gate')
        elif started!=6 or any(s['status']!='COMPLETED' for s in slots) or any(not (root/f't{n}'/'DURABLE.json').exists() for n in range(1,7)):
            row=dict(outcome='EXECUTION_INTERRUPTED',reason='Not all six consumed slots completed with durable evidence')
        else:
            env=read(BASE/'fresh-environment.json');__import__('sys').path.insert(0,str(BASE/'assembly/source'))
            from certification.stage_e_native_v2.observer import verify
            contract=read(BASE/'assembly/source/certification/stage_e_native_v2/observer-contract-v2.json')
            pairs=[]
            for i in range(3):
                members=slots[2*i:2*i+2]
                baseline=next(s['measurement']['elapsed_ns'] for s in members if s['mode']=='baseline')
                observed=next(s['measurement']['elapsed_ns'] for s in members if s['mode']=='observed')
                pairs.append(dict(pair_id=f'{EXECUTION_KEY}-p{i+1}',baseline_ns=baseline,observed_ns=observed,
                    valid=True,same_workload_hash=contract['workload_identity']))
            n=sum(p['observed_ns']-p['baseline_ns'] for p in pairs);d=sum(p['baseline_ns'] for p in pairs)
            measurement={k:contract[k] for k in ('baseline','metric','estimator','repetition_policy')}
            measurement.update(contract=contract['version'],identity=ledger['identity'],workload_identity=contract['workload_identity'],
                raw_pairs=pairs,numerator_ns=n,denominator_ns=d,ratio=n/d)
            try:
                assert verify(measurement,ledger['identity']) is True
                row=dict(outcome='PASS_STRICT_LT_1_PERCENT',native_verifier_passed=True)
            except ValueError as exc:
                row=dict(outcome='FAIL_OVERHEAD_AT_OR_ABOVE_1_PERCENT' if str(exc)=='observer_ratio_must_be_strictly_less_than_0_01' else 'INVALID_PAIR',
                    native_verifier_passed=False,native_verifier_reason=str(exc))
            persist(root/'MEASUREMENT.json',measurement)
            row['measurement']=measurement
        row.update(started_trials=started,started_members=ledger['started_members'],ledger=ledger)
    row.update(version='self-hosted-observer-v2-final-v1',paper_only=True,stage_e='RED',stage_f='NOT STARTED',
        stop='STOP FOR ASTRA',no_retries=True,no_replacements=True)
    persist(root/'RESULTS.json',row)
    if ledger:
        publish('RESULTS.json',canonical(row)+b'\n',ledger['evidence_branch'])
    print('OBSERVER_V2:\n'+row['outcome']+'\n\nSTOP FOR ASTRA',flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['configure','trial','preserve','durable','finalize'])
    parser.add_argument('--sequence',type=int);args=parser.parse_args()
    if args.action=='configure':configure()
    elif args.action=='finalize':finalize()
    else:globals()[{'trial':'run_trial','preserve':'preserve','durable':'durable'}[args.action]](args.sequence)


if __name__=='__main__':main()
