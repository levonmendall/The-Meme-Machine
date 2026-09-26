"""Exact Run 380 preserved-artifact diagnosis; no provider access."""
import contextlib,gzip,hashlib,json,os,pathlib,runpy,sqlite3,sys
out=pathlib.Path('frozen-review');out.mkdir(exist_ok=True)
with (out/'review-execution.log').open('w') as log,contextlib.redirect_stdout(log):
 try:runpy.run_path('certification/frozen_artifact_review.py',run_name='__main__')
 except Exception as exc:(out/'review-boundary.json').write_text(json.dumps({'type':type(exc).__name__,'boundary':str(exc)}))
root=pathlib.Path('failed-hour')
base=next(root.rglob('certification-smoke/result.json')).parent
assert json.loads((base/'result.json').read_text())['integration_sha']==os.environ['REVIEW_SHA']
def safe(value):
 if isinstance(value,dict):return {k:safe(v) for k,v in value.items()}
 if isinstance(value,list):return [safe(v) for v in value]
 if isinstance(value,str) and any(t in value.lower() for t in ('https://','http://','wss://','ws://','bearer ','authorization:')):return '<endpoint-bearing value redacted>'
 return value
(out/'result.json').write_text(json.dumps(safe(json.loads((base/'result.json').read_text()))))
inventory=[]
for p in root.rglob('*'):
 if not p.is_file():continue
 inventory.append({'path':str(p.relative_to(root)),'bytes':p.stat().st_size})
 if p.suffix=='.log':
  text='\n'.join(safe(line) for line in p.read_text(errors='replace').splitlines())
  (out/('log-'+str(p.relative_to(root)).replace('/','__'))).write_text(text[-500000:])
(out/'inventory.json').write_text(json.dumps(inventory,indent=2))
for lane in ('pump','meteora','pons','ramses'):
 rows=[]
 archive=base/lane/'rpc-evidence.jsonl.gz'
 if not archive.exists():
  (out/(lane+'-archive-boundary.json')).write_text(json.dumps({'rpc_archive_exists':False}))
  continue
 with gzip.open(archive,'rt') as f:
  for line in f:
   r=json.loads(line)
   if r.get('error') or r.get('json_rpc_error_codes') or (r.get('http_status') or 0)>=400:rows.append(safe(r))
 (out/(lane+'-complete-provider-failures.json')).write_text(json.dumps(rows,indent=2))
from meme_machine.solana_evidence_storage import decode
for p in root.rglob('*.sqlite'):
 db=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 tables={r[0] for r in db.execute("select name from sqlite_master where type='table'")}
 if 'service_health' in tables and 'stream_receipts' in tables:
  data={'path':str(p.relative_to(root)),'schema':[dict(r) for r in db.execute("select name,sql from sqlite_master where type='table'")]}
  for table in ('service_health','counters','gaps','cursors','conflicts','interests','stream_receipts'):
   data[table]=[dict(r) for r in db.execute('select * from '+table+' limit 10000')]
  data['record_shapes']=[dict(r) for r in db.execute('select scope,kind,count(*) n,min(slot) lo,max(slot) hi,max(length(body)) max_body from records group by scope,kind')]
  (out/'solana-durable-state.json').write_text(json.dumps(safe(data),indent=2))
  n=0;size=0
  with gzip.open(out/'solana-record-samples.jsonl.gz','wt') as f:
   for row in db.execute("select body from records where body is not null and kind='transaction' order by slot limit 2000"):
    body=decode(row[0],db);line=json.dumps(body,separators=(',',':'))+'\n';f.write(line);n+=1;size+=len(line)
    if size>24*1024*1024:break
  (out/'sample-count.json').write_text(json.dumps({'records':n,'uncompressed_bytes':size}))
 db.close()
print('Preserved exact artifact review complete; no provider calls.')
