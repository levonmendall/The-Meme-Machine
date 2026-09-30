"""Transport-only validator: reads Git objects; never executes candidate code."""
import hashlib,json,os,re,subprocess
from pathlib import Path

def git(*args):
    return subprocess.check_output(['git',*args],text=True).strip()

def restore(request,payload_root):
    required={'expected_commit','expected_tree','expected_parent','remote_prerequisite','bundle_sha256','parts','regenerate_inventory','destination_ref','paper_only','execute_candidate','market_authority'}
    assert set(request)==required,'request_schema'
    assert request['paper_only'] is True and request['execute_candidate'] is False and request['market_authority'] is False
    for key in ('expected_commit','expected_tree','expected_parent','remote_prerequisite'):
        assert re.fullmatch('[0-9a-f]{40}',request[key]),key
    assert re.fullmatch('[0-9a-f]{64}',request['bundle_sha256'])
    assert request['destination_ref']=='refs/heads/preserved/stagee-objects-'+request['expected_commit']
    assert 1<=len(request['parts'])<=32
    data=bytearray()
    for i,part in enumerate(request['parts']):
        assert set(part)=={'path','sha256'}
        assert part['path']==f'.github/stagee-object-transport/candidate.part{i}'
        path=Path(payload_root)/part['path'];assert path.is_file() and not path.is_symlink()
        raw=path.read_bytes();assert 0<len(raw)<=256*1024
        assert hashlib.sha256(raw).hexdigest()==part['sha256']
        data.extend(raw)
    assert len(data)<8*1024*1024 and hashlib.sha256(data).hexdigest()==request['bundle_sha256']
    target=Path(os.environ['RUNNER_TEMP'])/'stagee-exact-transport.bundle'
    assert not target.exists(),'fresh_transport_output_required'
    target.write_bytes(data)
    subprocess.run(['git','fetch','--no-tags','origin',request['remote_prerequisite']],check=True)
    subprocess.run(['git','cat-file','-e',request['remote_prerequisite']+'^{commit}'],check=True)
    subprocess.run(['git','bundle','verify',str(target)],check=True)
    subprocess.run(['git','bundle','unbundle',str(target)],check=True)
    assert 0<=len(request['regenerate_inventory'])<=4
    for item in request['regenerate_inventory']:
        assert set(item)=={'commit','path','excluded','count','expected_blob','expected_sha256'}
        assert re.fullmatch('[0-9a-f]{40}',item['commit'])
        assert item['path']=='certification/native_qualification_preserved_sources.json'
        assert re.fullmatch('[0-9a-f]{40}',item['expected_blob'])
        assert re.fullmatch('[0-9a-f]{64}',item['expected_sha256'])
        assert item['path'] in item['excluded'] and 1<=len(item['excluded'])<=64
        assert 0<item['count']<=5000
        inv={};all_paths=set()
        for line in git('ls-tree','-r',item['commit']).splitlines():
            meta,path=line.split('\t',1);mode,kind,sha=meta.split();all_paths.add(path)
            assert kind=='blob' and mode in ('100644','100755'),'nonregular_candidate_file'
            if path in item['excluded']:continue
            raw=subprocess.check_output(['git','cat-file','blob',sha])
            inv[path]={'git_blob':sha,'mode':int(mode,8)&0o777,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
        assert len(inv)==item['count'] and set(item['excluded'])<=all_paths
        raw=(json.dumps(inv,indent=2,sort_keys=True)+'\n').encode()
        assert hashlib.sha256(raw).hexdigest()==item['expected_sha256']
        sha=subprocess.check_output(['git','hash-object','-w','--stdin'],input=raw).decode().strip()
        assert sha==item['expected_blob']==git('rev-parse',item['commit']+':'+item['path'])
    sha=request['expected_commit']
    assert git('rev-parse',sha+'^{tree}')==request['expected_tree']
    assert git('rev-list','--parents','-n','1',sha).split()==[sha,request['expected_parent']]
    subprocess.run(['git','merge-base','--is-ancestor',request['remote_prerequisite'],sha],check=True)
    subprocess.run(['git','fsck','--full'],check=True)
    return dict(passed=True,request=request,candidate_code_executed=False,tests_executed=0,profiles_executed=0,provider_calls=0,canonical_promotion=False)

if __name__=='__main__':
    control_sha=os.environ['GITHUB_SHA']
    assert os.environ['GITHUB_EVENT_NAME']=='push' and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert git('rev-parse','HEAD')==control_sha and not git('status','--porcelain')
    request=json.loads(Path('.github/stagee-object-transport/request.json').read_text())
    result=restore(request,Path('.'))
    assert git('rev-parse','HEAD')==control_sha and not git('status','--porcelain')
    ref=request['destination_ref'];sha=request['expected_commit']
    assert not git('ls-remote','--heads','origin',ref),'destination_already_exists'
    subprocess.run(['git','push','--porcelain','--force-with-lease='+ref+':','origin',sha+':'+ref],check=True)
    assert git('ls-remote','--heads','origin',ref).split()==[sha,ref]
    result.update(transport_sha=control_sha,run_id=os.environ['GITHUB_RUN_ID'])
    output=Path(os.environ['RUNNER_TEMP'])/'exact-object-evidence';output.mkdir(exist_ok=True)
    (output/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
