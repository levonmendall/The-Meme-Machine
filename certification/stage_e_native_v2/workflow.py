"""Static YAML and forwarding validation only; never dispatches any workflow."""
import re
from pathlib import Path
from .contract import ROOT, HERE, read, sha256


def validate(root=ROOT):
    import yaml  # Optional static tooling, pinned separately from trial runtime.
    root=Path(root);base=root/'.github/workflows'
    caller_path=base/'stagee-native-qualification-v2.yml'
    reusable_path=base/'stagee-native-qualification-v2-reusable.yml'
    caller=yaml.load(caller_path.read_text(),Loader=yaml.BaseLoader)
    reusable=yaml.load(reusable_path.read_text(),Loader=yaml.BaseLoader)
    assert set(caller['on'])=={'workflow_dispatch'}
    assert set(reusable['on'])=={'workflow_call'}
    inputs={'expected_sha','plan_hash','input_manifest_hash'}
    assert set(caller['on']['workflow_dispatch']['inputs'])==inputs
    assert set(reusable['on']['workflow_call']['inputs'])==inputs
    job=caller['jobs']['qualification_v2']
    assert job['uses']=='./.github/workflows/stagee-native-qualification-v2-reusable.yml'
    assert job['with']=={k:'${{ inputs.'+k+' }}' for k in inputs}
    matrix=reusable['jobs']['trial']['strategy']['matrix']['case']
    assert matrix==read(root/'certification/stage_e_native_v2/trial-definition-v2.json')['deterministic_matrix']
    text=caller_path.read_text()+reusable_path.read_text()
    for workflow in (caller,reusable):
        for spec in workflow['jobs'].values():
            for step in spec.get('steps',[]):
                if 'uses' in step:assert re.search(r'@[0-9a-f]{40}$',step['uses'])
    assert 'persist-credentials: false' in text and 'fetch-depth: 0' in text
    assert 'MM_EXPECTED_SHA: ${{ inputs.expected_sha }}' in text
    assert 'MM_PLAN_HASH: ${{ inputs.plan_hash }}' in text
    assert 'MM_INPUT_HASH: ${{ inputs.input_manifest_hash }}' in text
    assert 'MM_WORKFLOW_SHA: ${{ github.workflow_sha }}' in text
    assert 'MM_WORKFLOW_REF: ${{ github.workflow_ref }}' in text
    assert 'github.run_attempt' in text and '--candidate "$MM_EXPECTED_SHA"' in text
    assert 'assembly/source/certification/stage_e_native_v2/bootstrap.py' not in text  # launch() is the sole bootstrap adapter
    assert '--assembly "$RUNNER_TEMP/assembly"' in text and '--digest "$MM_ASSEMBLY_DIGEST"' in text
    assert 'fail-fast: false' in text and 'if: always()' in text
    assert 'native-v2-${{ inputs.expected_sha }}-${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.case }}-' in text
    assert 'qualification_preflight' in text and 'aggregate-github' in text
    assert '--case preflight' in text
    for forbidden in ('maintenance_qualification','cleanup_recovery --','promote_phase_e','dispatch_phase_e','observer-measurement','run373-full','run379-full','run380-full'):
        assert forbidden not in text
    return dict(passed=True,classification='STATIC',workflow_hashes={str(p.relative_to(root)):sha256(p.read_bytes()) for p in (caller_path,reusable_path)},
        matrix=matrix,checks=['YAML parse','v2 input forwarding','exact candidate/workflow SHA','same assembly preflight/trial',
            'complete deterministic matrix','immutable actions','unique artifacts include attempt and trial ID','aggregation even on failure'],
        dispatched=False,canonical_authority=False)
