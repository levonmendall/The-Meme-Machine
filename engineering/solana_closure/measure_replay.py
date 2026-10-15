"""Bounded simultaneous replay of authenticated provider captures.

No network or monetary authority. Provider bytes are the recorded delivered
payloads, including duplicated shard messages; reconstructed WS projection sizes
are labelled DERIVED, never confused with a provider invoice measurement.
"""
import argparse,asyncio,collections,json,math,resource,tempfile,time,zlib
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from .replay_positive import frames,run as positive_replay
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceWriter,canonical,decode_body
from meme_machine.solana_evidence_service import FinalizedFence
from meme_machine.solana_selective_source import install,commit_scout,plan_live
from meme_machine.solana_selective_history import economic_records,coverage_scope
from meme_machine.solana_native_evidence import economic_transaction,pubkey,signature
from meme_machine.solana_program_decoders import pump_events,pumpswap_trade_events
from meme_machine.solana_activity_routes import ActivityRoutes
from meme_machine.solana_scoped_retirement import ScopedRetirement
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.lanes.pump.pump_acceleration_strategy import ExitObservation,exit_decision,MODE_POSTGRAD
from meme_machine.yellowstone import geyser_pb2 as pb

def distribution(values):
 values=sorted(values)
 if not values:return dict(mean=None,p50=None,p95=None,p99=None,max=None,samples=0)
 def q(f):return values[min(len(values)-1,math.ceil(f*len(values))-1)]
 return dict(mean=sum(values)/len(values),p50=q(.5),p95=q(.95),p99=q(.99),max=values[-1],samples=len(values))

def captured_json(path):
 path=Path(path)
 return json.loads(path.read_text() if path.exists() else zlib.decompress(path.with_name(path.name+'.zlib').read_bytes()))

class State:
 def __init__(self,path):
  self.writer=EvidenceWriter(path);self.fence=FinalizedFence(self.writer,endpoint_identity='a'*64);install(self)
 def close(self):self.writer.close()

async def measure(old,positive,*,pace=1):
 old=Path(old);positive=Path(positive)
 scouts=[r for r in frames(old/'delivery-20261007T023339Z/scout.frames') if r[2].WhichOneof('update_oneof')=='account']
 routed=list(frames(old/'routes-20261007T014803Z/raw.frames'))
 reference={signature(u.transaction.transaction.signature):u.transaction.transaction for _,_,u in routed if u.WhichOneof('update_oneof')=='transaction'}
 matches=captured_json(old/'routes-20261007T014803Z/bodies.json')
 statuses=captured_json(old/'routes-20261007T014803Z/statuses.json')
 census=sorted({a for row in matches.values() for a in row['matches']})
 # One shared address per neighbouring shard tests paid overlap explicitly.
 routes=[ActivityRoutes(census[n:n+49]+(census[n-1:n] if n else [])) for n in range(0,len(census),49)]
 native_status={signature(u.transaction_status.signature):u for _,_,u in routed if u.WhichOneof('update_oneof')=='transaction_status'}
 profile=collections.Counter();shard_bytes=collections.Counter();received=collections.Counter();routing_misses=[];copies=collections.defaultdict(list)
 for sig,row in matches.items():
  if sig not in statuses:continue
  hit=set(row['matches']);seen=set()
  for index,route in enumerate(routes):
   labels=[label for label,addresses in route.groups.items() if hit.intersection(addresses)]
   if not labels:continue
   resolved=route.resolve(labels);seen.update(resolved['addresses'])
   # Exact serialization of this preserved authoritative status at the safe
   # filter boundary, independently delivered by each overlapping shard.
   # Preserve vote/error/transaction index and original provider timestamps.
   # Only the routing labels change in this explicitly DERIVED shard replay.
   u=pb.SubscribeUpdate();u.CopyFrom(native_status[sig]);del u.filters[:];u.filters.extend(labels)
   size=u.ByteSize();profile['shard_delivered_bytes']+=size;shard_bytes[index]+=size;received[sig]+=1
   copies[sig].append(size)
  if not hit.issubset(seen):routing_misses.append(sig)
 duplicate_bytes=sum(sum(sizes[1:]) for sizes in copies.values())
 latency=collections.defaultdict(list);errors=[];warm_peak=0;age_peak=0.;positions=collections.Counter();position_marks=[];burst=collections.defaultdict(collections.Counter)
 windows=dict(scout=25.184735190996435,routing=30.10356330004288)
 start=time.perf_counter();cpu0=time.process_time();pump_position=None;swap_position=None
 with tempfile.TemporaryDirectory() as d:
  owner=PriorityOwner(lambda:State(Path(d)/'canonical.sqlite'));await asyncio.wrap_future(owner.ready)
  async def work(fn,priority=2):
   nonlocal age_peak
   arrival=time.perf_counter();future=owner.submit(fn,priority=priority);result=await asyncio.wrap_future(future)
   latency['owner_'+str(priority)].append(time.perf_counter()-arrival)
   with owner.cv:
    if owner.enqueued:age_peak=max(age_peak,time.monotonic()-min(owner.enqueued.values()))
   return result
  def promote_reactivated(h,second):
   # Immediate permissive handoff makes this a reproducible demand/stress
   # cohort. Production acquisition/governor throughput is NOT inferred from
   # a count reduced by local coroutine interleaving or the capture's tail.
   for family,address,lo in h.db.execute("SELECT family,address,lower_slot FROM candidate_lifecycle WHERE state='reactivated'").fetchall():
    identity=h.lifecycle.promote(family,address,deadline=time.time()+150,lower_slot=0 if family=='pump' else lo)
    if identity:burst[family][second]+=1
  async def scout_producer():
   nonlocal warm_peak
   base=scouts[0][0]
   for at,raw,u in scouts:
    await asyncio.sleep(max(0,(at-base)/pace-(time.perf_counter()-start)))
    arrival=time.perf_counter()
    def ingest(s):
     h=install(s);h.delivery('discovery','yellowstone',raw_bytes=len(raw),seen=at);commit_scout(s,u,at)
     address=pubkey(u.account.account.pubkey);family='pump' if list(u.filters)==['p'] else 'meteora'
     # This is the production handoff after reactivation, with the original
     # infrastructure deadline and no public ranking or economic cutoff.
     promote_reactivated(h,int(at-base))
     h.lifecycle.publish()
     return h.db.execute("SELECT COUNT(*) FROM candidate_lifecycle WHERE state IN ('queued','warming')").fetchone()[0]
    warm_peak=max(warm_peak,await work(ingest,5));latency['candidate_event_arrival'].append(time.perf_counter()-arrival)
    latency['promotion'].append(time.perf_counter()-arrival)
  async def history_producer():
   nonlocal pump_position,swap_position
   base=routed[0][0];prior={}
   for at,raw,u in routed:
    if u.WhichOneof('update_oneof')!='transaction':continue
    await asyncio.sleep(max(0,(at-base)/pace-(time.perf_counter()-start)))
    t=u.transaction.transaction;sig=signature(t.signature);body=economic_transaction(t,slot=u.transaction.slot,block_time=0,rich=False)
    # The economic event carries its own authoritative market timestamp.
    pe=pump_events(body);se=pumpswap_trade_events(body)
    rows=[]
    for family,addresses in [('pump',{e['mint'] for e in pe}),('pumpswap',{e['pool'] for e in se})]:
     for address in addresses:
      rows.extend(economic_records(family,address,body,endpoint_identity='a'*64,seen=at,source='alchemy_finalized_stream'))
    if not rows:continue
    arrival=time.perf_counter()
    def ingest(s):
     h=install(s)
     for row in rows:
      family='pump' if row.scope.endswith(':pump') else 'pumpswap';event=row.payload['event'];a=event['mint'] if family=='pump' else event['pool'];h.bind(family,a)
      h.lifecycle.observe(family,a,slot=row.slot,seen=at,fields={},activity=True,signature=sig)
     before=h.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0]
     h.ingest(rows);h.lifecycle.publish()
     after=h.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0]
     profile['first_canonical_admissions']+=after-before
     # Duplicated overlapping replay exercises the same immutable writer.
     h.ingest(rows);h.lifecycle.publish()
     profile['duplicate_canonical_admissions']+=h.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0]-after
     promote_reactivated(h,int(at-base));h.lifecycle.publish()
    await work(ingest,1);latency['ordered_history'].append(time.perf_counter()-arrival)
    for event in se:
     pool=event['pool'];profile['body_free_events']+=1
     profile['logical_event_bytes']+=len(canonical(event).encode())
     # Position reads consume the same stream; they never allocate a new full
     # body subscription or acquire capital.
     if swap_position is None:swap_position=pool
     if pool==swap_position:
      positions['pumpswap_events']+=1
      price=(event.get('quote_amount') or event.get('sol_amount') or 1)/max(1,event.get('token_amount') or event.get('base_amount') or 1)
      before=time.perf_counter();old=prior.setdefault(pool,dict(first=price,high=price));old['high']=max(old['high'],price)
      observation=ExitObservation(MODE_POSTGRAD,100,90,int((price/old['first']-1)*10000),int((old['high']/old['first']-1)*10000),100,'pumpswap')
      reason=await work(lambda s:exit_decision(observation),0)
      elapsed=time.perf_counter()-before
      for name in ('open_position_mark','hwm_update','exit_signal','safety_signal'):latency[name].append(elapsed)
      position_marks.append(dict(signature=sig,exit=reason))
  async def maintenance():
   while time.perf_counter()-start<max(windows.values())/pace:
    await work(lambda s:install(s).lifecycle.publish(),6);await asyncio.sleep(.1)
  async def warming():
   # Reproduce the complete provider-equivalent Meteora interval and actual
   # qualification while scouts, Pump histories and position reads run.
   before=time.perf_counter();proof=await asyncio.to_thread(positive_replay,positive)
   latency['hydration'].append(proof['wall_clock_seconds']);latency['qualification_ready'].append(proof['warm_complete']-proof['scout_time'])
   latency['meteora_replay_processing'].append(time.perf_counter()-before)
   return proof
  tasks=[asyncio.create_task(scout_producer()),asyncio.create_task(history_producer()),asyncio.create_task(maintenance()),asyncio.create_task(warming())]
  outcomes=await asyncio.gather(*tasks,return_exceptions=True)
  for o in outcomes:
   if isinstance(o,BaseException):errors.append(type(o).__name__+':'+str(o)[:180])
  positive_proof=outcomes[-1] if not isinstance(outcomes[-1],BaseException) else None
  def finish(s):
   h=install(s)
   while h.lifecycle.flush():pass
   measures={}
   for family in ('pump','pumpswap','meteora'):
    retained_locators=h.db.execute('SELECT COUNT(*) FROM candidate_lifecycle WHERE family=?',(family,)).fetchone()[0]
    denominator=(h.db.execute("SELECT COUNT(*) FROM market_observations WHERE family='meteora' AND json_extract(fields,'$.wsol_pair_locator')=1").fetchone()[0]
                 if family=='meteora' else retained_locators)
    numerator=h.db.execute("SELECT COUNT(*) FROM candidate_history_outbox WHERE family=? AND kind='promotion'",(family,)).fetchone()[0]
    promoted_unique=h.db.execute("SELECT COUNT(DISTINCT address) FROM candidate_history_outbox WHERE family=? AND kind='promotion'",(family,)).fetchone()[0]
    react=h.db.execute("SELECT COUNT(*) FROM candidate_history_outbox WHERE family=? AND kind='reactivated'",(family,)).fetchone()[0]
    seconds=windows['scout'] if family!='pumpswap' else windows['routing']
    measures[family]=dict(denominator=denominator,retained_locators=retained_locators,
     unresolved_structural_locators=retained_locators-denominator,numerator=numerator,reactivations=react,seconds=seconds,
     rate_hour=numerator*3600/seconds,rate_day=numerator*86400/seconds,promoted_unique=promoted_unique,promotion_percentage=100*promoted_unique/max(1,denominator),
     burst_max_per_second=max(burst[family].values(),default=0),classification='MEASURED_REPLAY',
     cohort='Activity-first capture with immediate permissive handoff for demand replay; not a new-creation census or certified governed operating rate.')
   with closing(CandidateHistory(h.lifecycle.path)) as shared:
    backlog=shared.pending();pending=[(r[0],r[1]) for r in shared.db.execute("SELECT ready_at,deadline FROM work WHERE status='pending'")]
   profile['canonical_logical_bytes']=sum(len(canonical(decode_body(r[0],h.db)).encode())
     for r in h.db.execute('SELECT body FROM canonical_evidence WHERE body IS NOT NULL'))
   before=ScopedRetirement(h).retire()
   # Demotion never retires active/pending or open-position state; no lease is
   # rewritten merely to obtain a favourable storage measurement.
   return measures,backlog,pending,before
  measures,backlog,pending,retirement=await work(finish,6)
  owner_metrics=dict(owner.metrics);owner.close()
 elapsed=time.perf_counter()-start;cpu=time.process_time()-cpu0
 proof_summary={k:v for k,v in (positive_proof or {}).items() if k not in ('full_vector','minimal_vector','source_commit_seconds','chunks')}
 # Exact burst admission into the current two-worker EDF configuration. Use
 # measured warming duration, never the old arbitrary saturation envelope.
 warm_seconds=(positive_proof or {}).get('wall_clock_seconds',16.003484838001896)
 jobs=sorted(pending);workers=[0.,0.];missed=0;max_delay=0.
 if jobs:
  epoch=min(r[0] for r in jobs)
  for ready,deadline in sorted(jobs,key=lambda r:(r[1],r[0])):
   index=min(range(2),key=workers.__getitem__);begin=max(ready-epoch,workers[index]);end=begin+warm_seconds
   max_delay=max(max_delay,begin-(ready-epoch));workers[index]=end;missed+=end>deadline-epoch
 return dict(classification='MEASURED_REPLAY',window_seconds=windows,wall_seconds=elapsed,pace=pace,
  candidate_rates=measures,latency_seconds={k:distribution(v) for k,v in latency.items()},errors=errors,
  routing=dict(matched=len(statuses),omissions=len(routing_misses),body_free_events=profile['body_free_events'],
   shards=len(routes),addresses_per_shard=[len(r.addresses) for r in routes],filters_per_shard=[len(r.groups) for r in routes],
   delivered_status_bytes=profile['shard_delivered_bytes'],duplicate_delivered_bytes=duplicate_bytes,
   bytes_per_shard=dict(shard_bytes),received_duplicates=sum(n-1 for n in received.values()),
   duplicate_canonical_events=profile['duplicate_canonical_admissions'],
   serialization_classification='DERIVED_FROM_MEASURED',first_canonical_admissions=profile['first_canonical_admissions']),
  provider_raw_bytes_per_second=(sum(len(r[1]) for r in scouts)/windows['scout']+profile['shard_delivered_bytes']/windows['routing']),
  provider_rate_scope='Scout payloads plus derived overlapping status deliveries only. Candidate WS log bytes and HTTP work are not included; this is not an aggregate production wire rate.',
  queue_depth_peak=owner_metrics.get('queue_peak',0),oldest_queue_age_seconds=age_peak,warming_backlog_peak=warm_peak,
  warming_backlog_end=backlog,owner_metrics=owner_metrics,cpu_seconds=cpu,cpu_percent_one_core=cpu/elapsed*100,
  maximum_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
  network=dict(replay_network_bytes=0,
   actual_reference_capture_bytes=sum(len(r[1]) for r in scouts+routed)+(positive_proof or {}).get('captured_provider_grpc_bytes',0),
   derived_shard_status_bytes=profile['shard_delivered_bytes'],invoice_meter=False,
   note='Preserved full reference bodies were provider-delivered historical bytes. The future default body-free path still buys WS logs; this replay does not measure that aggregate live subscription rate.'),
  positions=dict(positions),retirement=retirement,positive=proof_summary,
  byte_boundaries=dict(captured_scout_provider_bytes=sum(len(r[1]) for r in scouts),
   derived_provider_shard_status_bytes=profile['shard_delivered_bytes'],
   local_materialized_hot_bytes=retirement['hot_bytes_before'],
   canonical_logical_bytes=profile['canonical_logical_bytes'],local_ipc_bytes=0,
   limitation='Scout and routing captures differ in time; status sharding is derived. No production aggregate/day or IPC/day is inferred.'),
  two_worker_deadline_envelope=dict(workers=2,measured_seconds_per_warmup=warm_seconds,queued_jobs=len(jobs),
   predicted_deadline_misses=missed,maximum_start_delay_seconds=max_delay,
   classification='DERIVED_FROM_MEASURED',economic_rejection=False,
   assumption='Every promoted Meteora scope requires the measured compatible full warmup; compatibility incidence is unmeasured.'),
  local_evidence_readiness_pass=not errors and not routing_misses and bool(latency['open_position_mark']) and max(latency['open_position_mark'])<1.,
  shared_governed_provider_latency_certified=False,
  capacity_pass=not errors and not routing_misses and missed==0)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('old');p.add_argument('positive');p.add_argument('--output',required=True);p.add_argument('--pace',type=float,default=1);a=p.parse_args()
 result=asyncio.run(measure(a.old,a.positive,pace=a.pace));Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k not in ('owner_metrics','positive')},indent=2))
