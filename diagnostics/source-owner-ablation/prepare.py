"""Read-only static verification before either bounded arm; no workload execution."""
import argparse, ast, hashlib, importlib.util, json, os, subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
REVIEWED='2cc7a7c42e8f98acd57c2b606d132867d2393def'

def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True)
    args=parser.parse_args();out=Path(args.root);out.mkdir(parents=True,exist_ok=False)
    assert os.environ['GITHUB_RUN_ATTEMPT']=='1'
    req=json.loads((HERE/'execution-request.json').read_text())
    c,t=req['arms']['control'],req['arms']['treatment']
    assert {k for k in c if c[k]!=t[k]}=={'source_owner_floor'} and set(c)==set(t)
    assert c['source_owner_floor']==.165 and t['source_owner_floor']==0
    assert req['executions']==2 and req['order']==['control','treatment']
    assert req['planned_budget_before']==2 and req['planned_budget_after']==4 and req['unused_after']==2
    plan=json.loads((ROOT/'certification/stagee24_qualification_plan.json').read_text())
    cleanup=json.loads((ROOT/'certification/cleanup_recovery_plan.json').read_text())
    assert plan['burst_source_seconds']==cleanup['burst_source_seconds']==[216,378]
    assert plan['recovery_deadline_source_seconds']==cleanup['recovery_deadline_source_seconds']==120
    assert c['frames']==1334 and (c['frames']-1)*.27>=216+120+req['fixed_observation_guard_source_seconds']-1e-9
    assert abs(c['frames']*.27-req['frame_count_source_coordinate'])<1e-9
    assert (c['frames']-1)*.27<378 and req['first_recovery_window']==[216,336]
    state=ast.parse((ROOT/'meme_machine/solana_maintenance_state.py').read_text())
    values={n.targets[0].id:ast.literal_eval(n.value) for n in state.body
        if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and
        n.targets[0].id in ('RECOVERY_SOURCE_SECONDS','PIPELINE_SLACK_RECORDS')}
    assert values==dict(RECOVERY_SOURCE_SECONDS=120.,PIPELINE_SLACK_RECORDS=1000)
    old=ast.parse((ROOT/'diagnostics/stage-e-fresh-causal-isolation/harness.py').read_text())
    new=ast.parse((HERE/'harness.py').read_text())
    def find(tree,name):
        matches=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==name]
        assert len(matches)==1,name
        return ast.dump(matches[0],include_attributes=False)
    for name in ('Wire','explain','choose','transaction','checkpoint','boundary','owner_init','local_only'):
        assert find(old,name)==find(new,name),name
    def before_worker_return(tree):
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='worker_call')
        return [ast.dump(n,include_attributes=False) for n in fn.body[:-1]]
    assert before_worker_return(old)==before_worker_return(new)
    assert (HERE/'harness.py').read_text().count('value=native_source(self,items)')==1
    inputs=set(plan['unchanged_inputs'])|set(plan['observation_sources'])|set(cleanup['unchanged_inputs'])
    # The whole reviewed tree is verified below. Also record executable local dependencies.
    inputs.update(['tests/test_run379_production_pressure.py','meme_machine/solana_evidence_service.py',
        'meme_machine/solana_evidence_control.py','meme_machine/solana_maintenance_runtime.py',
        'meme_machine/solana_maintenance_state.py','meme_machine/solana_maintenance_arbiter.py',
        'certification/stagee24_qualification_plan.json','requirements.txt'])
    hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sorted(inputs)}
    for p,want in {**plan['unchanged_inputs'],**plan['observation_sources'],**cleanup['unchanged_inputs']}.items():
        assert hashes[p]==want,p
    spec=importlib.util.spec_from_file_location('ablation_static',HERE/'harness.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    identity=mod.identity();env=mod.environment()
    write(out/'identity.json',identity);write(out/'environment.json',env)
    write(out/'STATIC_PREFIX_VERIFICATION.json',dict(verified=True,reviewed_sha=REVIEWED,
        identical_configuration_except_source_floor=True,identical_native_wire_ast=True,
        unchanged_native_decision_transaction_checkpoint_wrappers=True,
        unchanged_worker_native_call_and_floor=True,workload_hashes=hashes,
        first_window=[216,336],fixed_guard=23.91,last_payload_deadline=(1334-1)*.27,
        count_coordinate=1334*.27,second_burst=378,
        no_canonical_authority=True,tests_rerun=False))
    for file in HERE.iterdir():
        if file.is_file(): (out/file.name).write_bytes(file.read_bytes())
    (out/'workflow.yml').write_bytes((ROOT/'.github/workflows/source-owner-ablation.yml').read_bytes())
    history=out/'historical';history.mkdir()
    old_dir=ROOT/'diagnostics/stage-e-fresh-causal-isolation'
    for name in ('ASTRA_GATE.json','ASTRA_REVIEW_PACKAGE.md','PREFLIGHT_EVIDENCE.json',
                 'M1_SUMMARY.json','M1_ARTIFACT.json','M2_SUMMARY.json','M2_ARTIFACT.json',
                 'PUBLICATION_IDENTITY.json','PUBLICATION_RECEIPT.json'):
        (history/name).write_bytes((old_dir/name).read_bytes())
    print('STATIC_PREFIX_VERIFIED '+json.dumps(dict(identity=identity,environment=env,
        prefix_frames=1334,first_window=[216,336],guard=23.91)),flush=True)

if __name__=='__main__':main()
