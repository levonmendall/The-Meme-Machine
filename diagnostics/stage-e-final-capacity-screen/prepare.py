"""Static exact-tree construction only. This script never starts pressure."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import io

ROOT=Path('/workspace/The-Meme-Machine')
WORK=Path('/workspace/stage-e-screen-work')
HERE=ROOT/'diagnostics/stage-e-final-capacity-screen'
S='7a516a6a92be9347661ac0e7f560971c171a0931'
T='9da7d1e1625ba04c1437c63606c90f5e293bdba7'
CONTROL='19b4244d6c09eeebab37319784109b876c94a0d4'
PATH='meme_machine/solana_evidence_service.py'

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def sha(data):return hashlib.sha256(data).hexdigest()
def canonical(row):return json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def write(name,row):(HERE/name).write_text(json.dumps(row,sort_keys=True,indent=2)+'\n')

def main():
    reviewed=json.loads((WORK/'assembly/assembly.json').read_bytes())
    body=dict(reviewed);own=body.pop('assembly_digest')
    assert own=='08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659'
    assert sha(canonical(body))==own
    assert git('rev-parse',S+'^{tree}').decode().strip()==T
    changed=git('diff','--name-only',S,CONTROL).decode().splitlines()
    assert changed==[PATH]
    source=git('show',S+':'+PATH)
    control=git('show',CONTROL+':'+PATH)
    original=b'offer=await admission.rendezvous(source_state)'
    disabled=b'offer=None'
    assert source.count(original)==1 and control==source.replace(original,disabled)
    patched_ast=ast.parse(source.replace(original,disabled))
    assert ast.dump(patched_ast,include_attributes=False)==ast.dump(ast.parse(control),include_attributes=False)
    patch=git('diff','--binary','--full-index','--no-ext-diff','--no-textconv','--no-renames',S,CONTROL)
    (HERE/'CONTROL.patch').write_bytes(patch)
    (HERE/'CONTROL.diff').write_bytes(patch)
    proof={'control_commit':CONTROL,'control_tree':git('rev-parse',CONTROL+'^{tree}').decode().strip(),
        'treatment_commit':S,'treatment_tree':T,'changed_files':changed,'patch_sha256':sha(patch),
        'exact_one_callsite_replacement':True,'control_ast_equals_single_replacement_treatment_ast':True,
        'all_other_tracked_blobs_and_modes_identical':True,
        'qualification_v2_bytes_unchanged':True,'m1_and_housekeeping_service_functions_unchanged':True,
        'constant_file_hashes':{p:sha(git('show',S+':'+p)) for p in (
            'meme_machine/solana_evidence_plane.py','meme_machine/solana_maintenance_runtime.py',
            'meme_machine/solana_maintenance_arbiter.py','meme_machine/solana_maintenance_state.py',
            'meme_machine/solana_owner_admission.py','meme_machine/solana_evidence_control.py',
            'meme_machine/solana_checkpoint.py')},
        'semantic_delta':'The blocks/account branch receives offer=None instead of awaiting A2 rendezvous. '
            'No offer can open. SourceState construction, batching, source submission, admission.source_accepted, '
            'abort(None), ordinary maintenance admission, native arbitration and all other service code remain exact.'}
    write('STATIC_CONTROL_PROOF.json',proof)
    write('CHANGED_FILES.json',changed)
    clone={'version':'stage-e-final-capacity-screen-control-assembly-v1',
        'identity':{'repository':'levonmendall/The-Meme-Machine','candidate_sha':CONTROL,
            'candidate_tree':proof['control_tree'],'base_reviewed_assembly_digest':own,
            'environment_identity':reviewed['identity']['environment_identity'],
            'assembly_recipe':'exact control git tree; only A2 callsite disabled; no generated runtime bytes'},
        'files':copy.deepcopy(reviewed['files'])}
    clone['files'][PATH].update(sha256=sha(control),bytes=len(control),git_blob=git('rev-parse',CONTROL+':'+PATH).decode().strip())
    clone['assembly_digest']=sha(canonical(clone))
    for label,commit,manifest in (('treatment',S,reviewed),('control',CONTROL,clone)):
        directory=WORK/(label+'-assembly')
        directory.mkdir(exist_ok=False)
        with tarfile.open(fileobj=io.BytesIO(git('archive','--format=tar',commit))) as archive:
            archive.extractall(directory/'source',filter='data')
        for name,info in manifest['files'].items():
            path=directory/'source'/name
            assert sha(path.read_bytes())==info['sha256'],name
            path.chmod(0o555 if info['mode']=='100755' else 0o444)
        for path in sorted((directory/'source').rglob('*'),reverse=True):
            if path.is_dir():path.chmod(0o555)
        (directory/'source').chmod(0o555)
        (directory/'assembly.json').write_bytes(canonical(manifest))
        (directory/'assembly.json').chmod(0o444)
        directory.chmod(0o555)
        (HERE/(label.upper()+'_ASSEMBLY.json')).write_bytes(canonical(manifest))
    write('ASSEMBLY_IDENTITIES.json',{
        'control':{'commit':CONTROL,'tree':proof['control_tree'],'assembly_digest':clone['assembly_digest']},
        'treatment':{'commit':S,'tree':T,'assembly_digest':own},'patch_sha256':sha(patch)})
    print(json.dumps({'identities':json.loads((HERE/'ASSEMBLY_IDENTITIES.json').read_bytes()),'material_executions':0},indent=2))

if __name__=='__main__':main()
