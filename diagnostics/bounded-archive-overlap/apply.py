"""Apply the single proposed patch only to a fresh detached treatment worktree."""
import argparse,difflib,hashlib,json,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
REVIEW='3eeb02f060b4623b6842d8f18853e5340dec0684'
def run(root,*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
def main():
    p=argparse.ArgumentParser();p.add_argument('--treatment',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();root=Path(a.treatment).resolve();out=Path(a.output).resolve()
    assert not run(root,'status','--porcelain'), 'treatment_not_fresh'
    replacement=json.loads((HERE/'replacement-files.json').read_text())
    original=json.loads((HERE/'original-blob-shas.json').read_text())
    patch=[]
    for name,text in replacement.items():
        path=root/name
        old=path.read_text() if path.exists() else ''
        if name in original:assert run(root,'hash-object',name)==original[name],name
        else:assert not path.exists(),name
        patch.extend(difflib.unified_diff(old.splitlines(True),text.splitlines(True),
                      fromfile='a/'+name,tofile='b/'+name))
        path.write_text(text)
    out.mkdir(parents=True,exist_ok=True)
    (out/'treatment.patch').write_text(''.join(patch))
    run(root,'add',*replacement)
    tree=run(root,'write-tree')
    ident=dict(treatment_tree=tree,modified_files=sorted(replacement),
               patch_sha256=hashlib.sha256((out/'treatment.patch').read_bytes()).hexdigest(),
               actual_source_hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in replacement},
               production_byte_identical=False,review_package=REVIEW,
               treatment_parent=run(root,'rev-parse','HEAD'))
    (out/'treatment-source-identity.json').write_text(json.dumps(ident,indent=2)+'\n')
    print('TREATMENT_SOURCE '+json.dumps(ident),flush=True)
if __name__=='__main__':main()
