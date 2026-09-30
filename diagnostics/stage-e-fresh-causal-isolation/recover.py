"""Read only a fresh diagnostic artifact; never run or recover historical Pro work."""
import argparse, hashlib, io, json, os, re, urllib.request, zipfile
from pathlib import Path
REPO='levonmendall/The-Meme-Machine'

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        # Do not forward the repository token to the artifact blob host.
        return urllib.request.Request(newurl,headers={'Accept':'application/vnd.github+json'})

def main():
    p=argparse.ArgumentParser(); p.add_argument('--request',required=True);p.add_argument('--output',required=True)
    a=p.parse_args(); request=json.loads(Path(a.request).read_text())
    binding=request['recover_artifact']; assert binding['run_id']==36756490388
    assert binding['id']==11116354967 and binding['head_sha']=='7234dcc545b7372c2f177bbe3ef938db5f2454e6'
    url=f"https://api.github.com/repos/{REPO}/actions/artifacts/{binding['id']}/zip"
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],
        'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.build_opener(SafeRedirect()).open(req,timeout=30) as response: raw=response.read(32*1024**2)
    assert hashlib.sha256(raw).hexdigest()==binding['zip_sha256']
    output=Path(a.output);output.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        manifest=json.loads(z.read('SHA256.json'))
        for name,digest in manifest.items():
            assert hashlib.sha256(z.read(name)).hexdigest()==digest
        log=z.read('unittest.log').decode()
        (output/'recovered-unittest.log').write_text(log)
        headers=re.findall(r'^(?:FAIL|ERROR): .*$',log,re.M)
        ran=re.search(r'^Ran (\d+) tests in (.*)$',log,re.M)
        footer=re.findall(r'^(?:OK.*|FAILED .*|Ran .*tests.*)$',log,re.M)
        row=dict(binding=binding,manifest_verified=True,tests_run=int(ran[1]) if ran else None,
            failures=headers,footer=footer,unittest_sha256=manifest['unittest.log'])
        (output/'validation-evidence.json').write_text(json.dumps(row,indent=2)+'\n')
        print('VALIDATION_EVIDENCE '+json.dumps(row),flush=True)
        # The complete log is uploaded; bounded failing traces are readable in CI.
        blocks=re.split(r'\n={10,}\n',log)
        for b in [b for b in blocks if b.startswith(('FAIL:','ERROR:'))][:12]:
            print('VALIDATION_FAILURE '+b[:4500],flush=True)

if __name__=='__main__': main()
