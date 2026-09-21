"""Reconstruct reviewed native repairs, canonicalize overlays, and publish blobs only."""
import base64,hashlib,json,os,pathlib,subprocess,sys,tempfile,urllib.request
from certification.run import ROOT,manifest,source_integrity
PATCHES={'pump':'pump-accounting.patch','meteora':'meteora-checkpoint.patch','pons':'pons-cohort-capital.patch','ramses':'ramses-admission.patch'}
def run(args,**kwargs):return subprocess.check_output(args,**kwargs)
def apply(worktrees):
    worktrees=pathlib.Path(worktrees)
    before=source_integrity(worktrees)
    inputs=json.loads((ROOT/'certification/frozen_repair_inputs.json').read_text())
    for lane,files in inputs.items():
        for name,content in files.items():
            path=worktrees/lane/name
            if not path.resolve().is_relative_to((worktrees/lane).resolve()):raise ValueError('input_path')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
            subprocess.run(['git','add','-N','--',name],cwd=worktrees/lane,check=True)
    proofs={}
    for lane,row in manifest()['lanes'].items():
        work=worktrees/lane;patch=ROOT/'certification/patches'/PATCHES[lane]
        diff=run(['git','diff','--binary','HEAD'],cwd=work);patch.write_bytes(diff)
        with tempfile.TemporaryDirectory() as td:
            env=dict(os.environ,GIT_INDEX_FILE=str(pathlib.Path(td)/'index'))
            subprocess.run(['git','read-tree',row['source_sha']],cwd=ROOT,env=env,check=True)
            subprocess.run(['git','apply','--cached',str(patch)],cwd=ROOT,env=env,check=True)
            rebuilt=run(['git','diff','--cached','--binary',row['source_sha']],cwd=ROOT,env=env)
            if rebuilt!=diff:raise ValueError('noncanonical_overlay:'+lane)
            for name,expected in row['file_hashes'].items():
                actual=hashlib.sha256(run(['git','show',':'+name],cwd=ROOT,env=env)).hexdigest()
                if actual!=expected:raise ValueError('frozen_file_changed:'+lane+':'+name)
        proofs[lane]=dict(source_sha=row['source_sha'],previous_overlay=before[lane],
            overlay_sha256=hashlib.sha256(diff).hexdigest(),byte_identical=True,frozen_files_unchanged=True)
    source_integrity(worktrees)
    output=ROOT/'frozen-repair-gates';output.mkdir(exist_ok=True)
    (output/'canonicality.json').write_text(json.dumps(proofs,indent=2)+'\n')
    print(json.dumps(proofs),flush=True)
def publish():
    if os.environ.get('GITHUB_REF_NAME')!='repair/frozen-campaign-handoff':raise ValueError('wrong_branch')
    out=ROOT/'frozen-repair-gates';gate=json.loads((out/'deterministic.json').read_text())
    if not gate['passed']:raise ValueError('verification_required')
    files=[ROOT/'certification/patches'/PATCHES[l] for l in PATCHES]
    entries=[]
    for path in files+sorted(out.glob('*')):
        if not path.is_file():continue
        content=path.read_bytes()
        target=str(path.relative_to(ROOT)) if path in files else 'certification/results/hosted-frozen-repair/default-signature-admission/'+path.name
        request=urllib.request.Request('https://api.github.com/repos/levonmendall/The-Meme-Machine/git/blobs',
            data=json.dumps({'content':base64.b64encode(content).decode(),'encoding':'base64'}).encode(),
            headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/json'},
            method='POST')
        with urllib.request.urlopen(request,timeout=60) as response:blob=json.load(response)
        entries.append(dict(path=target,sha=blob['sha'],mode='100644',type='blob',
            sha256=hashlib.sha256(content).hexdigest(),bytes=len(content)))
    result=dict(parent=os.environ['GITHUB_SHA'],entries=entries,gate=gate)
    (out/'published-blobs.json').write_text(json.dumps(result,indent=2)+'\n')
    print('FROZEN_REPAIR_BLOBS_BEGIN',flush=True);print(json.dumps(result),flush=True);print('FROZEN_REPAIR_BLOBS_END',flush=True)
if __name__=='__main__':
    if sys.argv[1]=='apply':apply(sys.argv[2])
    elif sys.argv[1]=='publish':publish()
    else:raise ValueError('unsupported_command')
