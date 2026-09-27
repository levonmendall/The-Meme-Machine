"""Profile a private copy of the digest-verified Run 381 database, offline."""
import cProfile,io,json,pathlib,pstats,sqlite3,tempfile,time
from meme_machine.solana_evidence_plane import EvidenceWriter
out=pathlib.Path('frozen-review');info=json.loads((out/'solana-durable-state.json').read_text());source=pathlib.Path('failed-hour')/info['path']
db=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
stats={'pragmas':{k:db.execute('pragma '+k).fetchone()[0] for k in ('page_size','page_count','freelist_count','cache_size')},'table_sizes':[dict(r) for r in db.execute('select name,sum(pgsize) bytes,count(*) pages from dbstat group by name order by bytes desc')], 'scope_ages':[dict(r) for r in db.execute('select scope,count(*) n,sum(body is null) archived,min(market_time) lo,max(market_time) hi,min(case when body is not null then slot end) first_hot from records group by scope')],'first_records':[dict(r) for r in db.execute('select identity,scope,slot,market_time,first_seen,body is null archived from records order by slot limit 25')]}
cutoff=1790470047-180
with tempfile.TemporaryDirectory() as td:
 path=pathlib.Path(td)/'copy.sqlite';target=sqlite3.connect(path);db.backup(target);target.close()
 w=EvidenceWriter(path,max_hot_bytes=2147483648)
 # Opening copy records restart gaps beyond the frontier; existing evidence and
 # historical gaps are left intact. Never mutate the preserved source database.
 results=[];profile=cProfile.Profile();profile.enable()
 for i in range(12):
  t=time.perf_counter();plan=w.archive_plan(cutoff,max_records=512);planned=time.perf_counter();receipt=w.write_archive(path,plan);written=time.perf_counter();n=w.commit_archive(plan,receipt);committed=time.perf_counter();w.retain(cutoff,max_records=512,archive_first=False);ended=time.perf_counter()
  results.append(dict(records=n,bytes=sum(len(json.dumps(r['body'])) for r in plan),plan=planned-t,write=written-planned,commit=committed-written,retain=ended-committed))
 profile.disable();s=io.StringIO();pstats.Stats(profile,stream=s).strip_dirs().sort_stats('cumtime').print_stats(45);(out/'storage-profile.txt').write_text(s.getvalue());stats['slices']=results
 stats['after']={'counters':dict(w.db.execute('select key,value from counters')),'pragmas':{k:w.db.execute('pragma '+k).fetchone()[0] for k in ('page_count','freelist_count')},'floors':dict(w.db.execute("select key,value from meta where key like 'retention_floor:%'"))};w.close()
db.close();(out/'storage-profile.json').write_text(json.dumps(stats,indent=2))
