"""Read-only review of one exact failed campaign artifact; no provider credentials."""
import collections,gzip,hashlib,json,os,pathlib,sqlite3,time,urllib.request,urllib.error,zipfile
REPO="levonmendall/The-Meme-Machine"
RUN=int(os.environ.get("REVIEW_RUN_ID","35555511322"))
PHASE=os.environ.get("REVIEW_PHASE","hourly")
SHA=os.environ.get("REVIEW_SHA","fba42effbe23fe1d3428b95e2280cd4dec0a0d06")
OUT=pathlib.Path("frozen-review");OUT.mkdir(exist_ok=True)
def api(path):
    req=urllib.request.Request("https://api.github.com/repos/"+REPO+path,
        headers={"Authorization":"Bearer "+os.environ["GITHUB_TOKEN"],"Accept":"application/vnd.github+json"})
    with urllib.request.urlopen(req,timeout=60) as r:return json.load(r)
run_state=api(f'/actions/runs/{RUN}')
cancelled=run_state.get('conclusion')=='cancelled'
artifact=None
for attempt in range(120):
    data=api(f"/actions/runs/{RUN}/artifacts")
    artifact=next((a for a in data["artifacts"] if a["name"].startswith("four-lane-hourly-" if PHASE=="hourly" else "four-lane-certification-")),None)
    if artifact:break
    time.sleep(10)
if artifact is None:raise RuntimeError("exact_hour_artifact_not_available")
if artifact["workflow_run"]["head_sha"]!=SHA:raise RuntimeError("artifact_source_mismatch")
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
req=urllib.request.Request(artifact["archive_download_url"],headers={"Authorization":"Bearer "+os.environ["GITHUB_TOKEN"]})
try:response=urllib.request.build_opener(NoRedirect()).open(req,timeout=60)
except urllib.error.HTTPError as e:
    if e.code!=302:raise
    response=urllib.request.urlopen(e.headers["Location"],timeout=120)
archive=pathlib.Path("failed-hour.zip")
with response,archive.open("wb") as f:
    while chunk:=response.read(1024*1024):f.write(chunk)
actual=hashlib.file_digest(archive.open("rb"),"sha256").hexdigest()
if artifact.get("digest")!="sha256:"+actual:raise RuntimeError("artifact_digest_mismatch")
(OUT/"artifact.json").write_text(json.dumps(artifact,indent=2))
root=pathlib.Path("failed-hour");root.mkdir(exist_ok=True)
with zipfile.ZipFile(archive) as z:
    for member in z.infolist():
        if not (root/member.filename).resolve().is_relative_to(root.resolve()):raise RuntimeError("archive_path")
    z.extractall(root)
result_path=next(root.rglob(f"certification-{PHASE}/result.json"));base=result_path.parent;root=base.parent
result=json.loads(result_path.read_text())
if result["integration_sha"]!=SHA:raise RuntimeError("result_source_mismatch")

import re
out=OUT
manifest=json.loads((root/'evidence-snapshot.json').read_text())
failures=[];counts=collections.Counter();verified=[]
for row in manifest['files']:
    counts[row['kind'] if 'kind' in row else 'snapshot_error']+=1
    if row.get('error_type'):failures.append({'snapshot_error':row})
    if not row.get('sha256'):continue
    parts=pathlib.Path(row['target']).parts
    try:relative=pathlib.Path(*parts[parts.index('certification-artifact')+1:])
    except ValueError:raise RuntimeError('unexpected_staged_target')
    path=root/relative
    if not path.resolve().is_relative_to(root.resolve()):raise RuntimeError('snapshot_path')
    with path.open('rb') as file:actual=hashlib.file_digest(file,'sha256').hexdigest()
    if actual!=row['sha256'] or path.stat().st_size!=row['bytes']:
        failures.append({'checksum':str(relative)})
    record={'path':str(relative),'bytes':path.stat().st_size,'sha256':actual}
    if row.get('kind')=='sqlite_online_backup':
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
        integrity=db.execute('PRAGMA quick_check').fetchall()
        mode=db.execute('PRAGMA journal_mode').fetchone()[0]
        db.close()
        record.update(integrity=integrity,journal_mode=mode)
        if integrity!=[('ok',)] or mode!='delete':failures.append({'sqlite':str(relative)})
    verified.append(record)
if not manifest.get('snapshot_complete'):failures.append({'snapshot_complete':False})
if manifest.get('native_exposure_relabelled') is not False:failures.append({'exposure_manifest':False})

logs={}
for lane in ("pump","meteora","pons","ramses"):
    path=base/lane/"process.log"
    value=path.read_text() if path.exists() else "<missing>"
    value="\n".join("<sensitive endpoint line redacted>" if any(marker in line.lower() for marker in ("http://","https://","ws://","wss://","authorization:","bearer ")) else line for line in value.splitlines())
    logs[lane]=value[-24000:]
    (OUT/(lane+"-process-sanitized.log")).write_text(value)
receipt={"artifact":artifact,"verified_sha256":artifact["digest"],"result":result,"snapshot_complete":manifest.get("snapshot_complete"),"file_kinds":dict(counts),"verified_file_count":len(verified),"failures":failures,"logs":logs}
(OUT/"startup-audit.json").write_text(json.dumps(receipt,indent=2,sort_keys=True))
(OUT/"verified-file-checksums.json").write_text(json.dumps(verified,indent=2,sort_keys=True))
print("STARTUP_AUDIT_BEGIN",flush=True)
print(json.dumps(receipt,sort_keys=True),flush=True)
print("STARTUP_AUDIT_END",flush=True)
if failures:raise RuntimeError("snapshot_integrity_failed")
