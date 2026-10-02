"""Read-only source/static proof. Git subprocesses are local identity reads only."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/workspace/The-Meme-Machine-S')
S = '7a516a6a92be9347661ac0e7f560971c171a0931'
T = '9da7d1e1625ba04c1437c63606c90f5e293bdba7'
REVIEW = 'dd75942dcc7498156f80808397c594a6767871e9'


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(['git','-C',str(SOURCE),*args])


def git_object(kind, data):
    return hashlib.sha1(kind.encode()+b' '+str(len(data)).encode()+b'\0'+data).hexdigest()


def source_integrity():
    assert git('rev-parse','HEAD').decode().strip() == S, 'HARD STOP S mismatch'
    assert git('rev-parse','HEAD^{tree}').decode().strip() == T, 'HARD STOP T mismatch'
    detached = subprocess.run(['git','-C',str(SOURCE),'symbolic-ref','-q','HEAD'],
                              capture_output=True,check=False)
    assert detached.returncode == 1, 'candidate must be detached'
    before=read(ROOT/'candidate_integrity_before.json')
    assert before['S'] == S and before['T'] == T
    changed=[]
    for name,record in before['tracked_files'].items():
        data=(SOURCE/name).read_bytes()
        if sha(data)!=record['sha256'] or git_object('blob',data)!=record['git_blob']:
            changed.append(name)
    assert not changed, changed
    assert not git('status','--porcelain','--untracked-files=all'), 'candidate checkout must remain clean'
    manifests=read(ROOT/'source_evidence_manifest.json')
    for commit,record in manifests['commits'].items():
        data=(ROOT/'evidence'/commit/'git-commit-object.txt').read_bytes()
        assert git_object('commit',data)==commit and sha(data)==record['commit_object_sha256']
        assert git('rev-parse',commit+'^{tree}').decode().strip()==record['tree']
    for record in manifests['evidence_files']:
        data=(ROOT/'evidence'/record['commit']/record['path']).read_bytes()
        assert len(data)==record['bytes'] and sha(data)==record['sha256'], record['path']
        assert git_object('blob',data)==record['git_blob'], record['path']
    consumed=read(ROOT/'consumed_sources.json')
    for record in consumed['sources']:
        data=(SOURCE/record['path']).read_bytes()
        assert sha(data)==record['sha256'] and git_object('blob',data)==record['git_blob']
    return dict(candidate_files=len(before['tracked_files']),evidence_files=len(manifests['evidence_files']),
                consumed_source_files=len(consumed['sources']),changed_candidate_files=[],changed_history_files=[])


def contract_static():
    old=read(SOURCE/'certification/stage_e_native_v2/plan-v2.json')
    oldmap=read(SOURCE/'certification/stage_e_native_v2/gate-map-v2.json')
    newmap=read(ROOT/'gate-map-v3.json')
    assert len(old['required_gates'])==44
    assert {r['predecessor_gate'] for r in newmap['gates'] if r['required']}==set(old['required_gates'])
    assert len(newmap['gates'])==len(oldmap['gates'])==44
    assert len(newmap['required_gates'])==len(set(newmap['required_gates']))==47
    assert not newmap['unmapped_required_gates'] and not newmap['dropped_gates']
    rows={r['new_gate']:r for r in oldmap['gates']}
    for r in newmap['gates']:
        assert r['predecessor_row']==rows[r['predecessor_gate']]
        assert r['execution_now']=='NOT_AUTHORIZED'
        assert r['acceptance_evidence_now']=='NOT_RUN'
    manifest=read(SOURCE/'certification/stage_e_native_v2/input-manifest-v2.json')
    for name,checksum in manifest['inputs'].items():
        assert sha((SOURCE/name).read_bytes())==checksum,name
    for name,checksum in old['historical_inputs'].items():
        assert sha((SOURCE/name).read_bytes())==checksum,name
    assert sha((SOURCE/'certification/stage_e_native_v2/gate-map-v2.json').read_bytes())==old['gate_map_hash']
    historical=ROOT/'evidence'/REVIEW/'diagnostics/stage-e-observer-v2-self-hosted'
    declaration=read(historical/'PREDECLARATION.json')
    assert sha((SOURCE/'certification/stage_e_native_v2/plan-v2.json').read_bytes())==declaration['identity']['plan_hash']
    assert sha((SOURCE/'certification/stage_e_native_v2/input-manifest-v2.json').read_bytes())==declaration['identity']['input_manifest_hash']
    A=read(ROOT/'production_capacity_workload.json');B=read(ROOT/'observer_workload.json');C=read(ROOT/'adversarial_stress_workload.json')
    common=['candidate_sha','candidate_tree','resource_envelope','clock','tape_binding','cohort',
            'worker_limits','native_work','candidate_local_read_schedule','urgent_ack_schedule',
            'source_release_schedule','common_safety_monitoring','member_deadline','verification','post_failure']
    assert all(A[k]==B[k] for k in common), 'A/B production equivalent inputs/resources/boundaries differ'
    assert [m['frames'] for m in A['cohort']]==[2223,2223,2223,4445]
    assert A['source_frames_total']==11114 and A['source_duration_total_us']==3000780000
    assert A['artificial_contention']==B['artificial_contention']
    assert A['tape_binding']==C['tape_binding']
    assert B['modes']==['baseline','observed','observed','baseline','baseline','observed']
    assert B['repetition_policy']==read(SOURCE/'certification/stage_e_native_v2/observer-contract-v2.json')['repetition_policy']
    safety=read(ROOT/'safety_ledger.json')
    assert not safety['changes']
    for a,b in [('source_lag_seconds',45),('hot_age_seconds',240),('retained_age_seconds',240)]:
        assert safety['limits'][a]=={'operator':'<','value':b,'domain':safety['limits'][a]['domain']}
    contract=read(ROOT/'contract.json')
    assert not contract['execution_authorized'] and contract['stage_e']=='RED' and contract['stage_f']=='NOT STARTED'
    assert contract['source_audit_complete'] and not contract['unresolved_source_bindings']
    assert not read(ROOT/'acceptance_semantic_changes.json')['production_safety_limit_changes']
    assert not read(ROOT/'policy_conservation.json')['changes']
    for file in ROOT.glob('*.py'):
        ast.parse(file.read_bytes(),filename=file.name)
    for file in ROOT.glob('*.json'):
        read(file)
    return dict(v2_gates_mapped=44,v3_required_gates=47,v2_input_hashes_verified=len(manifest['inputs']),
                all_proposed_workloads='NOT_RUN',A_B_equal_bindings=True)


def main():
    result={'scope':'STATIC_ONLY','preservation':source_integrity(),'contract':contract_static(),
            'capacity_workload_executed':False,'observer_campaign_executed':False,
            'synthetic_stress_executed':False,'stage_e':'RED','stage_f':'NOT STARTED'}
    (ROOT/'preservation_verification.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
