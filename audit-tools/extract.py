"""One immutable archived-block extraction. No provider access or market collection."""
import hashlib, json, os, pathlib, shutil, subprocess, sys, urllib.request, urllib.error, zipfile
REPO='levonmendall/The-Meme-Machine'
RUN=35935431384
ARTIFACT=10785439707
SHA='c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66'
DIGEST='1729982afa710db37dc401b0d515125f7cd7d5c6fd2d8a43fafaf334a86e326c'
OUT=pathlib.Path('coverage-evidence'); OUT.mkdir()
TOKEN=os.environ['GITHUB_TOKEN']
def api(path):
    req=urllib.request.Request('https://api.github.com/repos/'+REPO+path,headers={'Authorization':'Bearer '+TOKEN,'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=60) as r:return json.load(r)
run=api(f'/actions/runs/{RUN}')
a=api(f'/actions/artifacts/{ARTIFACT}')
assert run['head_sha']==SHA and run['conclusion']=='success'
assert a['workflow_run']['id']==RUN and a['workflow_run']['head_sha']==SHA
assert a['digest']=='sha256:'+DIGEST and not a['expired']
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
req=urllib.request.Request(a['archive_download_url'],headers={'Authorization':'Bearer '+TOKEN})
try:r=urllib.request.build_opener(NoRedirect()).open(req,timeout=60)
except urllib.error.HTTPError as e:
    if e.code!=302:raise
    r=urllib.request.urlopen(e.headers['Location'],timeout=120)
archive=pathlib.Path('preserved-hour.zip')
with r, archive.open('wb') as f:shutil.copyfileobj(r,f,1024*1024)
with archive.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
assert actual==DIGEST
expected={r['path']:r for r in json.loads(pathlib.Path('audit-tools/verified-file-checksums.json').read_text())}
selected=[]; shared=None
with zipfile.ZipFile(archive) as z:
    for info in z.infolist():
        p=pathlib.PurePosixPath(info.filename)
        if p.is_absolute() or '..' in p.parts or ((info.external_attr >>16)&0o170000)==0o120000:raise ValueError('unsafe_member')
        name=info.filename
        if info.is_dir():continue
        if name.endswith('/shared-solana-evidence.sqlite'):
            target=pathlib.Path('shared-solana-evidence.sqlite');shared=target
        elif (name.startswith('certification-native/hourly/') or name.endswith('/rpc-evidence.jsonl.gz')
                or name=='certification-hourly/ramses/telemetry.sqlite'
                or name in ('certification-hourly/shared-robinhood-admission.sqlite','certification-hourly/shared-provider.sqlite')
                or (name.startswith('certification-hourly/') and len(p.parts)==2 and p.suffix=='.json')):
            target=OUT/name
        else:continue
        target.parent.mkdir(parents=True,exist_ok=True)
        h=hashlib.sha256();size=0
        with z.open(info) as src,target.open('wb') as dst:
            while chunk:=src.read(1024*1024):dst.write(chunk);h.update(chunk);size+=len(chunk)
        row={'path':name,'bytes':size,'sha256':h.hexdigest()}
        if name in expected:
            assert row['bytes']==expected[name]['bytes'] and row['sha256']==expected[name]['sha256'],name
        elif name.endswith('.sqlite') or name.endswith('.jsonl.gz'):raise ValueError('unverified_native_member:'+name)
        selected.append(row)
assert shared is not None
with (OUT/'pump-shared-attribution.json').open('w') as f:
    subprocess.run([sys.executable,'audit-tools/pump_shared_query.py',str(shared),'lane-worktrees/pump'],stdout=f,check=True)
shared.unlink()
(OUT/'provenance.json').write_text(json.dumps({'schema':'immutable-coverage-extract-v1','source_run':RUN,'source_sha':SHA,'source_artifact':a,'archive_sha256':actual,'files':selected,'query':'audit-tools/pump_shared_query.py','market_requests':0},indent=2)+'\n')
print(json.dumps({'source_run':RUN,'source_sha':SHA,'archive_sha256':actual,'verified_files':len(selected),'market_requests':0}))
