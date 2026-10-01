"""Static ancestry/protected-byte and separate housekeeping compatibility proof."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
BASE='b11b16fbdc4ea0312b2c6f51de37e4d68e1f2da1'
PRODUCTION=('meme_machine/solana_evidence_control.py',
    'meme_machine/solana_evidence_service.py','meme_machine/solana_owner_admission.py')

def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)

def verify(output):
    subprocess.run(['git','merge-base','--is-ancestor',BASE,'HEAD'],cwd=ROOT,check=True)
    changed=git('diff','--name-only',BASE,'HEAD').decode().splitlines()
    allowed=set(PRODUCTION)|{'tests/test_owner_admission_phase2.py',
        '.github/workflows/owner-admission-phase2.yml'}
    assert all(p in allowed or p.startswith('diagnostics/stage-e-owner-admission-phase2/')
               for p in changed),changed
    m1='meme_machine/solana_maintenance_runtime.py'
    assert git('rev-parse',BASE+':'+m1)==git('rev-parse','HEAD:'+m1),'M1 runtime changed'
    protected=['meme_machine/solana_maintenance_arbiter.py',
        'meme_machine/solana_maintenance_state.py','meme_machine/solana_evidence_plane.py',
        'tests/test_m1_maintenance_completion.py','.github/workflows/m1-completion-deterministic.yml',
        '.github/workflows/stagee-fixed-cohort.yml','certification/maintenance_qualification_plan.json',
        'meme_machine/engine.py']
    assert all(git('rev-parse',BASE+':'+p)==git('rev-parse','HEAD:'+p) for p in protected)
    patch_hashes={}
    for name,paths in [('treatment',[]),('admission',list(PRODUCTION)),
                       ('deterministic',['tests/test_owner_admission_phase2.py',
                        'diagnostics/stage-e-owner-admission-phase2',
                        '.github/workflows/owner-admission-phase2.yml'])]:
        data=git('diff','--binary',BASE,'HEAD','--',*paths)
        (output/(name+'.patch')).write_bytes(data)
        patch_hashes[name]=hashlib.sha256(data).hexdigest()

    reference=(Path(__file__).with_name('HOUSEKEEPING_REFERENCE.patch')).read_bytes()
    reference_sha=hashlib.sha256(reference).hexdigest()
    assert reference_sha=='f4d3b0399dcfbe43b968ef0a901be73efe187f1a3ecdc79b16f5defb177f6f2d'
    runtime=(ROOT/m1).read_text()
    service=(ROOT/PRODUCTION[1]).read_text()
    gate=(ROOT/PRODUCTION[2]).read_text()
    for text in (runtime,service,gate):
        assert 'housekeeping_first' not in text
    for forbidden in ('.arbiter','.episodes','.last_observation','Need(','.writer',
                      'MaintenanceArbiter','_demands(','.retention(','archive_commit('):
        assert forbidden not in gate,forbidden
    lines=reference.decode().splitlines()
    start=lines.index('+    def _housekeeping_first(self,decision,observation,needs,ready,flight):')
    helper=[]
    for line in lines[start:]:
        if not line.startswith('+'):break
        helper.append(line[1:])
    helper='\n'.join(helper)+'\n'
    assert '_housekeeping_first' in helper and "n.scope=='__housekeeping__'" in helper
    future_runtime=runtime.replace('    def turn(self, flight, submitted):',
                                  helper+'\n    def turn(self, flight, submitted):')
    future_runtime=future_runtime.replace("result['retention_outcome']=self.state.retention()",
        "result['retention_outcome']=self.state.retention(housekeeping_first=self._housekeeping_first(decision,observation,needs,ready,flight))")
    ast.parse(future_runtime)
    before=ast.parse(runtime);after=ast.parse(future_runtime)
    def method(tree,name):
        cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='MaintenanceRuntime')
        return ast.dump(next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name==name))
    assert method(before,'_complete_decision')==method(after,'_complete_decision')
    assert method(before,'_cooperative')==method(after,'_cooperative')
    # Applying the original pre-M1 unified patch requires updated completion
    # context. This read-only check preserves the exact historical patch bytes.
    check=subprocess.run(['git','apply','--check','-'],cwd=ROOT,input=reference,
                         stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    housekeeping=dict(reference_sha256=reference_sha,carried=False,
        exact_selector_sha256=hashlib.sha256(helper.encode()).hexdigest(),
        selector_ast_valid_on_m1=True,m1_completion_ast_unchanged=True,
        admission_contains_no_housekeeping_predicates=True,
        original_patch_check_exit=check.returncode,
        original_patch_check=check.stdout.decode(),
        compatibility='selector and ordinary retention hook remain compatible; original pre-M1 patch context needs rebase before a combined fixture')
    row=dict(base=BASE,base_tree=git('rev-parse',BASE+'^{tree}').decode().strip(),
        sha=git('rev-parse','HEAD').decode().strip(),
        tree=git('rev-parse','HEAD^{tree}').decode().strip(),changed_files=changed,
        protected_blobs_unchanged=True,m1_runtime_blob=git('rev-parse','HEAD:'+m1).decode().strip(),
        patch_sha256=patch_hashes,housekeeping=housekeeping,
        working_tree=git('status','--porcelain','--untracked-files=no').decode(),
        material_executions=0,canonical_stage_e=False,stage_f=False)
    assert not row['working_tree']
    (output/'STATIC_VERIFICATION.json').write_text(json.dumps(row,indent=2,sort_keys=True)+'\n')
    print('PHASE2_STATIC '+json.dumps(row,sort_keys=True),flush=True)
    return row
