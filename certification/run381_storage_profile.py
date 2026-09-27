"""Profile a private copy of the digest-verified Run 381 database, offline."""
import cProfile,io,json,pathlib,pstats,sqlite3,tempfile,time
from meme_machine.solana_evidence_plane import EvidenceWriter
out=pathlib.Path('frozen-review');info=json.loads((out/'solana-durable-state.json').read_text());source=pathlib.Path('failed-hour')/info['path']
db=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
stats={'pragmas':{k:db.execute('pragma '+k).fetchone()[0] for k in ('page_size','page_count','freelist_count','cache_size')},'table_sizes':[dict(r) for r in db.execute('select name,sum(pgsize) bytes,count(*) pages from dbstat group by name order by bytes desc')], 'scope_ages':[dict(r) for r in db.execute('select scope,count(*) n,sum(body is null) archived,min(market_time) lo,max(market_time) hi,min(case when body is not null then slot end) first_hot from records group by scope')],'first_records':[dict(r) for r in db.execute('select identity,scope,slot,market_time,first_seen,body is null archived from records order by slot limit 25')]}
cutoff=1790470047-180
class TimedDB:
 def __init__(self,inner):self.inner=inner;self.times={}
 def __getattr__(self,key):return getattr(self.inner,key)
 def execute(self,sql,*args):
  t=time.perf_counter()
  try:return self.inner.execute(sql,*args)
  finally:
   key=' '.join(sql.split());r=self.times.setdefault(key,[0,0]);r[0]+=1;r[1]+=time.perf_counter()-t
stats['variants']={}
for variant in ('baseline','indexed'):
 with tempfile.TemporaryDirectory() as td:
  path=pathlib.Path(td)/'copy.sqlite';target=sqlite3.connect(path);db.backup(target);target.close()
  w=EvidenceWriter(path,max_hot_bytes=2147483648)
  if variant=='indexed':
   w.db.execute('create index if not exists records_hot_scope_slot on records(scope,slot) where body is not null')
   w.db.execute('create index if not exists records_archive_ref on records(archive) where archive is not null')
  w.db=TimedDB(w.db);results=[]
  for i in range(12):
   t=time.perf_counter();plan=w.archive_plan(cutoff,max_records=512);planned=time.perf_counter();receipt=w.write_archive(path,plan);written=time.perf_counter();n=w.commit_archive(plan,receipt);committed=time.perf_counter();w.retain(cutoff,max_records=512,archive_first=False);ended=time.perf_counter()
   results.append(dict(records=n,plan=planned-t,write=written-planned,commit=committed-written,retain=ended-committed))
  stats['variants'][variant]={'slices':results,'sql':sorted(w.db.times.items(),key=lambda x:-x[1][1])[:25]};w.close()
db.close();(out/'storage-profile.json').write_text(json.dumps(stats,indent=2))
