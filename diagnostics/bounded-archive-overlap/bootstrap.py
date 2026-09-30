"""Read-only evidence verification and two short allocation boundary checks.

There is no material harness invocation, provider call, or pressure workload here.
"""
import hashlib,json,os,platform,resource,socket,sqlite3,subprocess,sys,urllib.request,urllib.error,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
REVIEW='3eeb02f060b4623b6842d8f18853e5340dec0684'
def run(*args,cwd=ROOT,**kwargs):return subprocess.check_output(args,cwd=cwd,text=True,**kwargs).strip()
def write(path,obj):path.write_text(json.dumps(obj,indent=2)+'\n')
def manifest(ref):
    return {r.split('\t',1)[1]:r.split('\t',1)[0] for r in run('git','ls-tree','-r',ref).splitlines()}
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
def read_optional(path):
    try:return Path(path).read_text()[:4096]
    except OSError:return None
def main():
    out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=False)
    req=json.loads((HERE/'execution-request.json').read_text())
    assert os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert not req['material_launch_enabled']
    before=manifest(REVIEW);current=manifest('HEAD')
    assert all(current.get(k)==v for k,v in before.items())
    allowed=set(current)-set(before)
    assert all(p.startswith('diagnostics/bounded-archive-overlap/') or
               p=='.github/workflows/bounded-archive-overlap-gates.yml' for p in allowed)
    write(out/'source-preservation.json',dict(review=REVIEW,review_tree=run('git','rev-parse',REVIEW+'^{tree}'),
        diagnostic_sha=run('git','rev-parse','HEAD'),diagnostic_tree=run('git','rev-parse','HEAD^{tree}'),
        verified_preexisting_blobs_and_modes=len(before),all_unchanged=True,additions=sorted(allowed)))
    write(out/'execution-ledger.json',dict(material_executions_before=4,
        material_executions_added=0,material_executions_after=4,ceiling=6,remaining=2,
        pressure_workload_launched=False,provider_calls=0,paper_only=True))
    env=dict(python=platform.python_version(),sqlite=sqlite3.sqlite_version,
        websockets=__import__('importlib.metadata',fromlist=['version']).version('websockets'),
        os=platform.platform(),cpu_count=os.cpu_count(),affinity=sorted(os.sched_getaffinity(0)),
        load_start=list(os.getloadavg()),memory=read_optional('/proc/meminfo'),
        cpu_quota=read_optional('/sys/fs/cgroup/cpu.max'),memory_quota=read_optional('/sys/fs/cgroup/memory.max'),
        rlimits={n:list(resource.getrlimit(getattr(resource,n))) for n in
                  ('RLIMIT_CPU','RLIMIT_AS','RLIMIT_NOFILE','RLIMIT_NPROC')},
        run_id=os.getenv('GITHUB_RUN_ID'),run_attempt=os.getenv('GITHUB_RUN_ATTEMPT'),
        runner=os.getenv('RUNNER_NAME'),hostname=socket.gethostname())
    write(out/'environment.json',env)
    # Download the exact durable ZIP, remove authentication before following its
    # signed storage redirect, and independently hash ZIP and original JSON bytes.
    endpoint='https://api.github.com/repos/levonmendall/The-Meme-Machine/actions/artifacts/11124508037/zip'
    request=urllib.request.Request(endpoint,headers={
        'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'})
    opener=urllib.request.build_opener(NoRedirect)
    try:
        response=opener.open(request,timeout=30);raw=response.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in (301,302,303,307,308):raise
        location=exc.headers['Location']
        raw=urllib.request.urlopen(location,timeout=30).read()
    digest=hashlib.sha256(raw).hexdigest();assert digest==req['zip_sha256']
    archive=out/'reviewed-evidence.zip';archive.write_bytes(raw)
    with zipfile.ZipFile(archive) as z:
        names=[n for n in z.namelist() if n.endswith('COMPARISON.json')]
        assert len(names)==1
        comparison=z.read(names[0])
    digest_json=hashlib.sha256(comparison).hexdigest()
    assert digest_json==req['original_comparison_sha256']
    (out/'reviewed-COMPARISON.json').write_bytes(comparison)
    write(out/'reviewed-evidence-binding.json',dict(run=36771603217,artifact=11124508037,
        zip_sha256=digest,original_comparison_sha256=digest_json,independently_verified=True))
    reference=out/'reference-worktree';treatment=out/'treatment-worktree'
    run('git','worktree','add','--detach',str(reference),'HEAD')
    run('git','worktree','add','--detach',str(treatment),'HEAD')
    subprocess.run([sys.executable,str(HERE/'apply.py'),'--treatment',str(treatment),
                    '--output',str(out/'source')],check=True,cwd=ROOT)
    modes=[('reference',reference),('prototype',treatment)]
    boundaries={}
    for mode,worktree in modes:
        target=out/(mode+'-boundary')
        child_env=dict(os.environ,PYTHONPATH=str(worktree))
        with (out/(mode+'-boundary.log')).open('w') as log:
            subprocess.run([sys.executable,str(HERE/'design_gate.py'),'--mode',mode,
                '--output',str(target)],cwd=worktree,env=child_env,stdout=log,stderr=subprocess.STDOUT,
                check=True,timeout=30)
        boundaries[mode]=json.loads((target/'result.json').read_text())
        print('ALLOCATION_BOUNDARY '+json.dumps(boundaries[mode],sort_keys=True),flush=True)
    ref,treat=boundaries['reference'],boundaries['prototype']
    gate=bool(ref['accepted'] and treat['accepted'] and
              ref['archived_records']==treat['archived_records']==1 and
              ref['integrity']==treat['integrity']=='ok')
    write(out/'DESIGN_GATE.json',dict(passed=gate,kind='unchanged_single_file_eligibility',
        native_accepted=ref['accepted'],prototype_accepted=treat['accepted'],
        no_lookahead_in_either_case=True,reference_body_bytes=ref['actual_body_bytes'],
        prototype_current_allocation=treat['prototype_current_body_allocation'],
        first_blocker=None if gate else 'Fixed initial 750/250 partition rejects a native-valid single body even without lookahead',
        prototype_error=treat.get('error'),focused_safety_suite_launched=False,
        material_workloads_launched=False,budget_consumed=4,unused=2))
    # Hard stop. No alternate allocation or pressure workload can follow a blocker.
    status='OVERLAP_DESIGN_OR_SAFETY_BLOCKED' if not gate else 'GATES_INCOMPLETE'
    write(out/'FOLLOWUP_STOP.json',dict(status=status,stop_all_diagnostic_execution=True,
        material_executions_consumed=4,ceiling=6,remaining=2,prototype_promoted=False,
        canonical_authority=False,stage_e='RED',stage_f='NOT_STARTED',paper_only=True,
        scoped_request='bounded-archive-overlap',previous_stops_preserved=True))
    for path in HERE.iterdir():
        if path.is_file():(out/path.name).write_bytes(path.read_bytes())
    (out/'workflow.yml').write_bytes((ROOT/'.github/workflows/bounded-archive-overlap-gates.yml').read_bytes())
    print('DESIGN_GATE '+json.dumps(json.loads((out/'DESIGN_GATE.json').read_text()),sort_keys=True),flush=True)
    if not gate:raise SystemExit(1)
    # No implicit execution budget use even in the unexpected passing case.
if __name__=='__main__':main()
