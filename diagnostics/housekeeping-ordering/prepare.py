"""Verify protected source, then apply one patch in disposable checkouts."""
import argparse, ast, copy, hashlib, json, os, shutil, subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASE='dc08f9064cf5e37b63f383f52aa709d0afc1723f'
EVIDENCE='750190b2067ca2fca771b531396d8e06a9351c62'
CHANGED=('meme_machine/solana_evidence_plane.py',
         'meme_machine/solana_evidence_service.py',
         'meme_machine/solana_maintenance_runtime.py')

def git(*args,cwd=ROOT):
    return subprocess.check_output(['git',*args],cwd=cwd,text=True).strip()

def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def manifest(ref):
    return {line.split('\t',1)[1]:line.split('\t',1)[0]
            for line in git('ls-tree','-r',ref).splitlines()}

def find(tree,name):
    found=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==name]
    assert len(found)==1,name
    return found[0]

def dump(node):
    return ast.dump(node,include_attributes=False)

def functions(path):
    tree=ast.parse(path.read_text())
    return {n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)
            and n.col_offset==4}

def verify_ast(control,treatment):
    old=ast.parse((control/CHANGED[0]).read_text())
    new=ast.parse((treatment/CHANGED[0]).read_text())
    before,after=find(old,'retain'),find(new,'retain')
    native_gc_start=next(i for i,n in enumerate(before.body)
        if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)
        and n.targets[0].id=='garbage')
    helper=find(new,'_retention_housekeeping')
    assert [dump(n) for n in helper.body]==[dump(n) for n in before.body[native_gc_start:native_gc_start+3]]
    # The complete per-scope loop and all its pin/floor/gap/continuity checks persist.
    loops=lambda fn:[n for n in fn.body if isinstance(n,ast.For)]
    assert dump(loops(before)[0])==dump(loops(after)[0])
    for path,excluded in ((CHANGED[0],{'retain','_retention_housekeeping'}),
                          (CHANGED[1],{'retention'}),
                          (CHANGED[2],{'turn','_housekeeping_first'})):
        om,nm=functions(control/path),functions(treatment/path)
        assert set(om)-excluded==set(nm)-excluded,path
        for name in set(om)-excluded:assert dump(om[name])==dump(nm[name]),(path,name)
    # After stripping the one new argument, existing service/turn control flow is identical.
    for path,name in ((CHANGED[1],'retention'),(CHANGED[2],'turn')):
        original=functions(control/path)[name]
        modified=copy.deepcopy(functions(treatment/path)[name])
        if name=='retention':
            assert modified.args.kwonlyargs[-1].arg=='housekeeping_first'
            modified.args.kwonlyargs.pop();modified.args.kw_defaults.pop()
        for n in ast.walk(modified):
            if isinstance(n,ast.Call):
                n.keywords=[k for k in n.keywords if k.arg!='housekeeping_first']
        assert dump(original)==dump(modified),(path,name)
    # Frozen choice, readiness, owner scheduling, leases, ledger and outcomes are byte-identical.
    for path in ('meme_machine/solana_maintenance_arbiter.py',
                 'meme_machine/solana_maintenance_state.py',
                 'meme_machine/solana_evidence_control.py',
                 'meme_machine/solana_retention_outcome.py'):
        assert (control/path).read_bytes()==(treatment/path).read_bytes(),path
    return dict(native_housekeeping_ast_identical=True,
        native_scope_loop_ast_identical=True,native_scope_transactions_identical=True,
        service_and_turn_flow_identical_except_prefix_argument=True,
        arbiter_and_owner_unchanged=True,ledger_and_outcome_model_unchanged=True,
        housekeeping_atomic_shield_added=False)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True)
    args=parser.parse_args()
    assert os.environ['GITHUB_RUN_ATTEMPT']=='1','no_retry'
    assert not (HERE/'FOLLOWUP_STOP.json').exists(),'astra_review_stop'
    req=json.loads((HERE/'execution-request.json').read_text())
    assert req['execute'] is True
    assert req['astra_decision']=='HOUSEKEEPING_ORDERING_REPAIR_APPROVED_FOR_TESTING'
    assert req['source_sha']==BASE and req['evidence_base_sha']==EVIDENCE
    assert req['planned_budget_before']==4 and req['planned_budget_after']==6 and req['unused_after']==0
    assert req['order']==['control','treatment'] and req['executions']==2 and req['no_retry']
    c,t=req['arms']['control'],req['arms']['treatment']
    assert set(c)==set(t) and {k for k in c if c[k]!=t[k]}=={'ordering_treatment'}
    assert c['ordering_treatment'] is False and t['ordering_treatment'] is True
    assert c['source_owner_floor']==t['source_owner_floor']==.165
    assert c['archive_floor']==.36 and c['commit_latency']==.006
    assert c['urgent_controls'] is False and c['frames']==1334 and c['sample_seconds']==5
    assert req['first_recovery_window']==[216,336] and req['wall_time_bound_seconds']==600
    assert abs((1334-1)*.27-req['last_payload_deadline_source_offset'])<1e-9
    assert (1334-1)*.27>=336+req['fixed_observation_guard_source_seconds']-1e-9
    assert (1334-1)*.27<req['second_burst_source_seconds']==378
    base,evidence,head=manifest(BASE),manifest(EVIDENCE),manifest('HEAD')
    assert all(evidence.get(p)==v for p,v in base.items())
    assert all(head.get(p)==v for p,v in evidence.items()),'protected_evidence_changed'
    additions=set(head)-set(evidence)
    assert all(p.startswith('diagnostics/housekeeping-ordering/') or
        p=='.github/workflows/housekeeping-ordering.yml' for p in additions)
    for path,value in evidence.items():
        mode,kind,oid=value.split()
        assert kind=='blob' and mode in ('100644','100755'),(path,value)
        raw=(ROOT/path).read_bytes()
        assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==oid,path
    out=Path(args.root);out.mkdir(parents=True,exist_ok=False)
    for p in HERE.iterdir():
        if p.is_file():shutil.copy2(p,out/p.name)
    shutil.copy2(ROOT/'.github/workflows/housekeeping-ordering.yml',out/'workflow.yml')
    work=out/'worktrees';work.mkdir()
    for arm in ('control','treatment'):
        git('worktree','add','--detach',str(work/arm),EVIDENCE)
        shutil.copytree(HERE,work/arm/'diagnostics/housekeeping-ordering')
        shutil.copy2(HERE/'test_housekeeping_ordering.py',work/arm/'tests/test_housekeeping_ordering.py')
    treatment=work/'treatment'
    patchfile=HERE/'treatment.patch'
    git('apply','--check',str(patchfile),cwd=treatment)
    git('apply',str(patchfile),cwd=treatment)
    assert set(git('diff','--name-only',cwd=treatment).splitlines())==set(CHANGED)
    ast_checks=verify_ast(work/'control',treatment)
    import importlib.util
    spec=importlib.util.spec_from_file_location('housekeeping_static',HERE/'harness.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    m.selfcheck()
    env=m.environment();write(out/'environment.json',env)
    assert env['python']=='3.12.14' and env['websockets']=='17.1',env['differences']
    plan=json.loads((ROOT/'certification/stagee24_qualification_plan.json').read_text())
    cleanup=json.loads((ROOT/'certification/cleanup_recovery_plan.json').read_text())
    assert plan['burst_source_seconds']==cleanup['burst_source_seconds']==[216,378]
    assert plan['recovery_deadline_source_seconds']==cleanup['recovery_deadline_source_seconds']==120
    frozen={**plan['unchanged_inputs'],**plan['observation_sources'],**cleanup['unchanged_inputs']}
    for p,want in frozen.items():assert sha(ROOT/p)==want,p
    baseline=ast.parse((ROOT/'diagnostics/source-owner-ablation/harness.py').read_text())
    current=ast.parse((HERE/'harness.py').read_text())
    for name in ('Wire','explain','choose','transaction','checkpoint','boundary','owner_init','local_only','worker_call'):
        assert dump(find(baseline,name))==dump(find(current,name)),name
    hashes={arm:{p:sha(work/arm/p) for p in evidence} for arm in ('control','treatment')}
    assert {p for p in hashes['control'] if hashes['control'][p]!=hashes['treatment'][p]}==set(CHANGED)
    manifests={**hashes,'treatment_changed_paths':list(CHANGED),'patch_sha256':sha(patchfile)}
    write(out/'checkout-manifests.json',manifests)
    for arm in ('control','treatment'):
        write(work/arm/'diagnostics/housekeeping-ordering/checkout-manifests.json',manifests)
    proof=dict(verified=True,source_sha=BASE,evidence_base_sha=EVIDENCE,
        diagnostic_sha=git('rev-parse','HEAD'),diagnostic_tree=git('rev-parse','HEAD^{tree}'),
        protected_production_files=len(base),protected_evidence_files=len(evidence),
        source_and_evidence_blobs_and_modes_unchanged=True,
        changed_paths=list(CHANGED),patch_sha256=sha(patchfile),
        tests_sha256=sha(HERE/'test_housekeeping_ordering.py'),
        identical_harness_native_wrappers=True,identical_native_workload_wire=True,
        identical_configuration_except_ordering=True,source_floor_both=.165,
        unchanged_workload_hashes={p:sha(ROOT/p) for p in frozen},ast_checks=ast_checks,
        historical_stops_preserved=True,stage_e='RED',stage_f='NOT_STARTED',paper_only=True)
    write(out/'STATIC_VERIFICATION.json',proof)
    print('STATIC_VERIFIED '+json.dumps(proof,sort_keys=True),flush=True)

if __name__=='__main__':main()
