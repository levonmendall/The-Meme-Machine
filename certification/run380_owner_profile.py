"""Provider-free performance comparison on a COPY of the digest-verified DB."""
import collections,cProfile,gzip,io,json,pathlib,pstats,sqlite3,tempfile,time
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_evidence_transport import Subscription
from meme_machine.solana_provider_config import AlchemyEndpoint
out=pathlib.Path('frozen-review');info=json.loads((out/'solana-durable-state.json').read_text());source=pathlib.Path('failed-hour')/info['path']
db=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)
shape={table:db.execute('select count(*) from '+table).fetchone()[0] for table in ('records','address_keys','address_refs','hot_chunks','hot_refs')}
shape['page_size']=db.execute('pragma page_size').fetchone()[0];shape['cache_size']=db.execute('pragma cache_size').fetchone()[0]
base=db.execute('select max(slot) from stream_receipts').fetchone()[0]+10000
slots=collections.defaultdict(dict)
for line in gzip.open(out/'solana-record-samples.jsonl.gz','rt'):
 r=json.loads(line);tx=dict(r['payload']);tx.pop('slot',None);tx.pop('blockTime',None);slots[r['slot']][r['signature']]=tx
for line in gzip.open(out/'solana-event-samples.jsonl.gz','rt'):
 r=json.loads(line)
 if r['signature'] not in slots[r['slot']]:slots[r['slot']][r['signature']]={'transaction':{'signatures':[r['signature']],'message':{'accountKeys':[r['program']]+r['addresses']}},'meta':{'logMessages':r['payload']['raw_lineage']['logs'],'err':r['payload']['raw_lineage']['err']}}
frames=[]
for i,(_,txs) in enumerate(sorted(slots.items())):
 slot=base+i;at=int(time.time())-1
 for tx in txs.values():tx['transaction']['signatures']=['offline-profile:'+tx['transaction']['signatures'][0]]
 message=dict(method='blockNotification',params=dict(subscription=1,result=dict(value=dict(slot=slot,err=None,block=dict(parentSlot=slot-1,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),blockTime=at,transactions=list(txs.values()))))))
 size=len(json.dumps(message,separators=(',',':')).encode());frames.append((Subscription('service','blocks','all','blocks',4),message,at+1,size))
results={}
for label in ('populated','populated_cache16','populated_cache32'):
 with tempfile.TemporaryDirectory() as td:
  path=pathlib.Path(td)/'copy.sqlite'
  if label.startswith('populated'):
   target=sqlite3.connect(path);db.backup(target);target.close()
  state=ServiceState(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
  if 'cache' in label:state.writer.db.execute('pragma cache_size=-'+str(int(label.split('cache')[1])*1024))
  profiler=cProfile.Profile();start=time.perf_counter();profiler.enable()
  try:
   for frame in frames:state.source_batch([frame])
  finally:
   profiler.disable();elapsed=time.perf_counter()-start;stream=io.StringIO();pstats.Stats(profiler,stream=stream).strip_dirs().sort_stats('cumtime').print_stats(45)
   (out/('owner-profile-'+label+'.txt')).write_text(stream.getvalue());results[label]={'elapsed':elapsed,'frames':len(frames),'body_bytes':sum(f[-1] for f in frames)};state.close()
(out/'owner-profile-summary.json').write_text(json.dumps({'source_copy_only':True,'original_shape':shape,'results':results},indent=2));db.close()
