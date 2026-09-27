"""Provider-free, fixed-clock mature evidence pressure from preserved public bodies.

Preserved templates remain immutable on disk. Envelopes, identity suffixes and
event timestamps are synthetically replayed against the fixed source clock.
The default replay spans 600 real seconds and crosses the actual retention age.
"""
import argparse,asyncio,base64,gzip,hashlib,json,re,sqlite3,struct,subprocess,tempfile,time,traceback
from pathlib import Path
from unittest.mock import patch
from tests.test_run380_production_pressure import Wire as PreservedWire
from tests.test_run373_dispatch_throughput import database_ready
from tests.evidence_ipc_harness import ipc_transport
from meme_machine.solana_evidence_plane import EvidenceReader,digest
from meme_machine.solana_evidence_runtime import RuntimeEvidence
import meme_machine.solana_evidence_service as service

class Wire(PreservedWire):
 """Retiming is test-only: old event clocks must not force premature archival."""
 async def recv(self,decode=None):
  message=await super().recv(decode)
  clock=re.search(rb'"blockTime":(\d+)',message)
  if clock is None:return message
  at=int(clock[1]);cache={}
  def retime(match):
   encoded=match[1]
   if encoded in cache:return cache[encoded]
   raw=bytearray(base64.b64decode(encoded));disc=bytes(raw[:8]);offset=None
   if disc==bytes([189,219,127,211,78,230,97,238]):offset=89
   elif disc in (bytes([103,244,82,31,44,245,119,119]),bytes([62,47,55,10,165,3,220,42])):offset=8
   elif disc==bytes([27,114,169,77,222,235,99,118]):
    offset=8
    for _ in range(3):offset+=4+struct.unpack_from('<I',raw,offset)[0]
    offset+=128
   if offset is not None:struct.pack_into('<q',raw,offset,at)
   result=b'Program data: '+base64.b64encode(raw);cache[encoded]=result;return result
  return re.sub(rb'Program data: ([A-Za-z0-9+/=]+)',retime,message)

async def run(frames,output):
 output=Path(output);output.mkdir(parents=True,exist_ok=True)
 wire=Wire();wire.frames=frames;stop=asyncio.Event();lags=[];hot_peak=0;oldest_hot_age_peak=0;oldest_retained_age_peak=0;started=time.monotonic();queries=[];last_report=0
 with tempfile.TemporaryDirectory() as td,ipc_transport(),patch('websockets.asyncio.client.connect',return_value=wire):
  path=Path(td)/'db';runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
  def snapshot():
   if not database_ready(path):return {},None,0,None,None
   db=sqlite3.connect(path)
   try:
    c=dict(db.execute('select key,value from counters'));f=db.execute("select value from service_health where key='finalized_frontier:program:meteora'").fetchone()
    gaps=db.execute('select count(*) from gaps where repaired is null').fetchone()[0]
    oldest=db.execute('SELECT COALESCE(market_time,first_seen) FROM records WHERE body IS NOT NULL ORDER BY COALESCE(market_time,first_seen),identity LIMIT 1').fetchone()
    retained=db.execute('SELECT MIN(COALESCE(market_time,first_seen)) FROM records').fetchone()[0]
    return c,json.loads(f[0]) if f else None,gaps,oldest[0] if oldest else None,retained
   finally:db.close()
  def candidate():
   plane=RuntimeEvidence(path,owner='meteora')
   try:
    top=plane.frontier('program:meteora');plane.command(op='ack',owner='meteora:run381',scope='program:meteora',slot=top)
    results={scope:len(plane.reader.window(scope,top,top,as_of=time.time())) for scope in ('program:meteora','program:pump','program:pumpswap')}
    assert results['program:meteora']==128,results
    assert results['program:pump']>0 and results['program:pumpswap']>0,results
    return results
   finally:plane.close()
  c={};failure=None;failure_frames=[];control=None;next_query=0
  try:
   while c.get('stream_accepted_messages',0)<frames:
    if runner.done():await runner
    c,f,gaps,oldest,retained=await asyncio.to_thread(snapshot);assert not gaps,('runtime_gap',gaps)
    oldest_hot_age=max(0,time.time()-oldest) if oldest is not None else 0
    oldest_hot_age_peak=max(oldest_hot_age_peak,oldest_hot_age)
    oldest_retained_age=max(0,time.time()-retained) if retained is not None else 0
    oldest_retained_age_peak=max(oldest_retained_age_peak,oldest_retained_age)
    if f:lags.append(time.time()-f['time'])
    hot=sum(p.stat().st_size for p in (path,Path(str(path)+'-wal')) if p.exists());hot_peak=max(hot_peak,hot)
    elapsed=time.monotonic()-started
    if control is not None and control.done():queries.append(await control);control=None
    if c.get('stream_accepted_messages',0)>10 and elapsed>=next_query and control is None:
     control=asyncio.create_task(asyncio.to_thread(candidate));next_query=elapsed+10
    if elapsed-last_report>=30:
     last_report=elapsed;print(json.dumps(dict(elapsed=elapsed,frames=c.get('stream_accepted_messages',0),hot_bytes=hot,lag=lags[-1] if lags else None,oldest_hot_age=oldest_hot_age,oldest_retained_age=oldest_retained_age,archived=c.get('archived_records',0),compacted=c.get('compacted_records',0))),flush=True)
    if elapsed>frames*.27+120:raise AssertionError('pressure_deadline')
    if lags and max(lags)>45:raise AssertionError('source_clock_fell_behind')
    # This fixture has no lifecycle pins. A growing archive backlog cannot pass
    # merely because the ten-minute test ended before the storage guard fired.
    if oldest_hot_age>240:raise AssertionError('archive_clock_fell_behind')
    # With no lifecycle/gap pins, archived index rows must retire within the
    # same 180-second retention plus 60-second backlog bound as hot payloads.
    if oldest_retained_age>240:raise AssertionError('retention_clock_fell_behind')
    await asyncio.sleep(.25)
   if control is not None:queries.append(await control);control=None
   assert queries
   if frames>=1000:
    assert c.get('archived_records',0)>0 and c.get('compacted_records',0)>0,c
   assert not {k:v for k,v in c.items() if (k.startswith('disconnect:') or k=='capacity_stops') and v},c
  except BaseException as exc:
   failure=type(exc).__name__+':'+str(exc)
   failure_frames=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name) for f in traceback.extract_tb(exc.__traceback__)][-16:]
  finally:
   stop.set()
   try:await runner
   except BaseException as exc:
    if failure is None:
     failure=type(exc).__name__+':'+str(exc)
     failure_frames=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name) for f in traceback.extract_tb(exc.__traceback__)][-16:]
   if control is not None:await asyncio.gather(control,return_exceptions=True)
   db=sqlite3.connect(path);health={k:json.loads(v) for k,v in db.execute('select key,value from service_health')};ipc=health.get('ipc',{})
   counters=dict(db.execute('select key,value from counters'));integrity=db.execute('pragma integrity_check').fetchone()
   retained_by_scope=[dict(scope=scope,hot=hot,archived_pending=archived,oldest_slot=slot) for scope,hot,archived,slot in db.execute('SELECT scope,SUM(body IS NOT NULL),SUM(body IS NULL),MIN(slot) FROM records GROUP BY scope')]
   db.close()
   archive_records=0
   for archive in path.parent.glob('*.archive/*.gz'):
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==archive.name.split('.')[0]
    with gzip.open(archive,'rt') as source:
     for line in source:
      row=json.loads(line);assert digest(row['body'])==row['hash'];assert row['lineage'];archive_records+=1
   result=dict(passed=failure is None,failure=failure,frames=frames,frame_bytes=len(wire.template),source_seconds=frames*.27,elapsed=time.monotonic()-started,lag_peak=max(lags,default=0),hot_peak=hot_peak,candidate_checks=len(queries),archive_records_verified=archive_records,counters=counters,ipc=ipc,owner=health.get('owner_scheduler'),integrity=integrity,provider_calls=0)
   result['integration_sha']=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
   result['source_hashes']={name:hashlib.sha256((Path(service.__file__).parent/name).read_bytes()).hexdigest() for name in ('solana_evidence_plane.py','solana_evidence_service.py','solana_evidence_storage.py','solana_evidence_control.py','solana_program_decoders.py')}
   result['storage_maintenance']=health.get('storage_maintenance',{})
   result['failure_frames']=failure_frames
   result['oldest_hot_age_peak']=oldest_hot_age_peak
   result['oldest_retained_age_peak']=oldest_retained_age_peak
   result['retained_by_scope']=retained_by_scope
   result['archived_pending_compaction']=sum(r['archived_pending'] for r in retained_by_scope)
   for condition,name in [(integrity==('ok',),'integrity'),(ipc.get('stream.received_messages')==ipc.get('stream.commit_messages'),'admitted_drain'),(ipc.get('stream.outstanding_frames_peak',0)<=64,'frame_bound'),(ipc.get('stream.dispatch_bytes_peak',0)<=96*1024*1024,'byte_bound'),(ipc.get('stream.commit_batch_bytes_peak',0)<=16*1024*1024,'commit_bound'),(hot_peak<2*1024**3,'hot_store_bound')]:
    if not condition:result['passed']=False;result['failure']=result['failure'] or name
   (output/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
   return 0 if result['passed'] else 1

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--frames',type=int,default=2223);p.add_argument('--output',required=True);a=p.parse_args();raise SystemExit(asyncio.run(run(a.frames,a.output)))
