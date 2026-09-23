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
review={"artifact":artifact,"verified_sha256":actual,"result":result,"native_lifecycles":[],"raw":{},"capacity":{}}
native=root/f"certification-native/{PHASE}"
pons_path=native/"pons/pons-selective-continuation-v1-cohort"
pons_final=pons_path/"complete-result.json.gz"
pons_final_complete=pons_final.exists()
if pons_final_complete:
    with gzip.open(pons_final,"rt") as f:pons=json.load(f)
elif cancelled:
    checkpoint=pons_path/"cohort-progress.json"
    if not checkpoint.exists():raise RuntimeError("cancelled_pons_checkpoint_missing")
    pons=json.loads(checkpoint.read_text())
    review["pons_native_boundary"]="cancelled_before_complete_result; checkpoint and raw journals retained; no final lifecycle inference"
else:
    raise RuntimeError("normal_pons_complete_result_missing")
review["pons_native_final_complete"]=pons_final_complete
review["pons_complete"]=pons
for life in pons.get("lifecycles",[]):
    row={k:life.get(k) for k in ("index","status","boundary","entry_failure","lifecycle_id","started_at","ended_at","realized_pnl_quote","settlement_kind","reconciliation","cohort_reconciliation","provider_recoveries","final_position")}
    row["entry"]=life.get("entry")
    row["exit"]=life.get("exit")
    review["native_lifecycles"].append(row)
for lane in ("pump","meteora","pons","ramses"):
    stats={"archive_complete":True,"transports":0,"local_rejections":[],"provider_failures":[],"gpa_scans":[],"tx_batches":collections.Counter()}
    with gzip.open(base/lane/"rpc-evidence.jsonl.gz","rt") as f:
        try:
            for line in f:
                r=json.loads(line);req=r.get("request") or [];req=req if isinstance(req,list) else [req]
                methods=[x.get("method") if isinstance(x,dict) else x[0] for x in req]
                compact={k:v for k,v in r.items() if k!="response"}
                if r.get("transport_attempted"):
                    stats["transports"]+=1
                    if methods and set(methods)=={"getTransaction"}:stats["tx_batches"][len(req)]+=1
                    if r.get("error") or r.get("json_rpc_error_codes") or (r.get("http_status") or 0)>=400:stats["provider_failures"].append(compact)
                else:stats["local_rejections"].append(compact)
                if "getProgramAccounts" in methods:stats["gpa_scans"].append(compact)
        except EOFError:
            if not cancelled:raise
            stats['archive_complete']=False
            stats['archive_boundary']='cancelled_archive_missing_gzip_footer; original bytes retained; only complete readable records analyzed'
    review["raw"][lane]=stats
    (OUT/(lane+"-process.log")).write_bytes((base/lane/"process.log").read_bytes())
for path in base.glob("*.sqlite"):
    db=sqlite3.connect(f"file:{path}?mode=ro",uri=True);db.row_factory=sqlite3.Row
    tables={r[0] for r in db.execute("select name from sqlite_master where type='table'")}
    if "admissions" in tables:
        admissions=[json.loads(r[0]) for r in db.execute("select body from admissions")]
        failed=[r for r in admissions if not r.get("granted")]
        summary={}
        for lane in ("pons","ramses"):
            rows=[r for r in admissions if r.get("lane")==lane]
            summary[lane]={"requested":len(rows),"granted":sum(bool(r.get("granted")) for r in rows),
                "failed":sum(not r.get("granted") for r in rows),"max_wait":max((r.get("wait_seconds",0) for r in rows),default=0)}
        review["capacity"][path.name]={"summary":summary,"failed_admissions":failed}
    if "acquisition_phases" in tables:
        review["capacity"][path.name]={}
        queries={
          "phases":"select lane,kind,phase,count(*) count from acquisition_phases group by lane,kind,phase",
          "states":"select lane,kind,state,count(*) count from evidence_consumers group by lane,kind,state",
          "failures":"select lane,kind,reason,count(*) count from hydration_attempt_failures group by lane,kind,reason"}
        for key,q in queries.items():review["capacity"][path.name][key]=[dict(r) for r in db.execute(q)]
    if "grants" in tables:
        review["capacity"][path.name]={"grants":[dict(r) for r in db.execute("select lane,priority,granted,reason,count(*) count,max(wait) max_wait from grants group by lane,priority,granted,reason")]}
    db.close()
pump=json.loads((native/"pump/pump-acceleration-natural-prospective.json").read_text())
review["pump_complete"]=pump
proofs=[]
for path in sorted(pons_path.glob("trial-*.sqlite")):
    db=sqlite3.connect(f"file:{path}?mode=ro",uri=True)
    records=[]
    for category,body in db.execute("select category,body from records where category in ('selective_provider_recovery','pons_selective_paper_journal','selective_writeoff_proof','selective_provider_session_rotation')"):
        records.append({"category":category,"body":json.loads(body)})
    proofs.append({"file":path.name,"records":records});db.close()
review["pons_journals"]=proofs
(OUT/"complete-review.json").write_text(json.dumps(review,indent=2,sort_keys=True))
summary={"sha":SHA,"run":RUN,"phase":PHASE,"artifact_id":artifact["id"],"sha256":actual,
    "engineering":result.get("hourly_engineering" if PHASE=="hourly" else "smoke_engineering"),"overlap":result["continuous_overlap_seconds"],
    "elapsed":result["elapsed_seconds"],
    "lanes":{k:{x:v.get(x) for x in ("exit_code","unexpected_exit","natural_settled","forced_settled","open_positions","accounting_reconciled","cohort_accounting","native_accounting","provider_method_errors","provider_http_status_errors","provider_rpc_error_codes")} for k,v in result["lanes"].items()},
    "pons_summary":pons.get("summary"),
    "pons_native_final_complete":pons_final_complete,"pons_native_boundary":review.get("pons_native_boundary"),
    "pons_boundary":pons.get("boundary"),"pons_operational_configuration":pons.get("operational_configuration"),
    "pons_discovery_recoveries":pons.get("sequencer_recoveries"),
    "pons_lifecycle_sessions":[{"index":l.get("index"),"sessions":l.get("provider_sessions")} for l in pons.get("lifecycles",[])],
    "pons_session_rotations":[{"index":l.get("index"),"rotations":l.get("provider_session_rotations",[])} for l in pons.get("lifecycles",[])],
    "pons_lifecycles":[{k:v for k,v in r.items() if k not in ("entry","exit","cohort_reconciliation")} for r in review["native_lifecycles"]],
    "raw_summary":{k:{"archive_complete":v["archive_complete"],"transports":v["transports"],"local":len(v["local_rejections"]),"provider_failures":len(v["provider_failures"]),"gpa_scans":v["gpa_scans"],"tx_batches":v["tx_batches"]} for k,v in review["raw"].items()},
    "capacity":review["capacity"],
    "pump_settled":pump.get("settled"),"pump_replay":pump.get("accounting_replay")}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True))
print("FROZEN_REVIEW_JSON_BEGIN",flush=True)
print(json.dumps(summary,sort_keys=True),flush=True)
print("FROZEN_REVIEW_JSON_END",flush=True)
print("RAMSES_PROCESS_LOG_BEGIN",flush=True)
print((base/"ramses/process.log").read_text()[-16000:],flush=True)
print("RAMSES_PROCESS_LOG_END",flush=True)

if PHASE=="smoke":
    failures=[]
    if (result.get("smoke_engineering") or {}).get("status")!="PASS":failures.append("smoke_engineering")
    for lane,data in result["lanes"].items():
        if data.get("open_positions"):failures.append(lane+":open_positions")
        if data.get("unexpected_exit") or data.get("process_restarts"):failures.append(lane+":continuity")
    tx=review["raw"]["pump"]["tx_batches"]
    if tx and max(tx)>8:failures.append("pump_transaction_batch_above_8")
    (OUT/"review-gate.json").write_text(json.dumps({"failures":failures,"passed":not failures}))
    if failures:raise RuntimeError("smoke_artifact_review:"+",".join(failures))
