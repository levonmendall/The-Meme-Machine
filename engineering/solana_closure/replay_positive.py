"""Reproduce authenticated positive warming through the final durable reader.

Inputs are a bounded read-only capture, not operational state. No network is
opened, and no entry, reservation, account book, signature or submission exists.
"""
import argparse,copy,io,json,struct,tempfile,time,zlib
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from .full_reference import transaction as full_transaction
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader
from meme_machine.solana_evidence_service import FinalizedFence
from meme_machine.solana_selective_source import install,commit_candidates
from meme_machine.solana_candidate_join import CandidateTransactionJoin
from meme_machine.solana_selective_history import CandidateReader,coverage_scope
from meme_machine.solana_evidence_queries import MeteoraEvidenceView
from meme_machine.solana_native_evidence import economic_transaction,signature
from meme_machine.yellowstone import geyser_pb2 as pb
from meme_machine.lanes.meteora import dlmm,dlmm_tape,runner

def frames(path):
 path=Path(path)
 source=io.BytesIO(zlib.decompress(path.with_name(path.name+'.zlib').read_bytes())) if not path.exists() else path.open('rb')
 with source as f:
  while header:=f.read(12):
   at,size=struct.unpack('<dI',header);raw=f.read(size)
   if len(raw)!=size:raise ValueError('capture_truncated')
   yield at,raw,pb.SubscribeUpdate.FromString(raw)

class ReplayRPC:
 def __init__(self,rows):self.rows=iter(rows);self.calls=[];self.last=None;self.clock=lambda: self.last['sealed_at'] if self.last else 0
 def call(self,method,params=None,priority=False,**kw):
  row=next(self.rows)
  if method!=row['method'] or (params or [])!=row['params']:
   raise ValueError('rpc_replay_request_mismatch:'+method+':'+row['method'])
  self.last=row;self.calls.append(row);return copy.deepcopy(row['response']['result'])

def run(folder):
 folder=Path(folder);summary=json.loads((folder/'result.json').read_text());positive=next(w for w in summary['warmups'] if w.get('qualification',{}).get('passes'))
 pool=positive['pool'];scope=coverage_scope('meteora',pool)
 captured=list(frames(folder/'native.frames'));first_slot=min(getattr(u,u.WhichOneof('update_oneof')).slot for _,_,u in captured if u.WhichOneof('update_oneof') in ('slot','block_meta','transaction_status','transaction'))
 addresses={a:coverage_scope('meteora',a) for a in summary['pools']}
 join=CandidateTransactionJoin(addresses,set(addresses),filtered_from_slot=first_slot);reference={};latencies=[];clock=[captured[0][0]]
 with tempfile.TemporaryDirectory() as d:
  writer=EvidenceWriter(Path(d)/'canonical.sqlite',clock=lambda:clock[0]);state=SimpleNamespace(writer=writer,fence=FinalizedFence(writer,endpoint_identity='a'*64));h=install(state);h.clock=h.lifecycle.clock=lambda:clock[0]
  for a in addresses:h.bind('meteora',a)
  for at,raw,u in captured:
   clock[0]=at;kind=u.WhichOneof('update_oneof')
   if kind in ('ping','pong'):continue
   started=time.perf_counter();frame=join.feed(u,len(raw),at)
   if frame:
    for t in frame.update.block.transactions:
     body,_=full_transaction(t,full=True)
     reference[signature(t.signature)]=dict(body,slot=frame.update.block.slot,blockTime=frame.update.block.block_time.timestamp)
    commit_candidates(state,frame,addresses,'captured-positive');latencies.append(time.perf_counter()-started)
  while h.lifecycle.flush():pass
  h.lifecycle.publish()
  with closing(EvidenceReader(writer.path)) as reader:
   view=MeteoraEvidenceView(CandidateReader(reader,'meteora',pool),scope)
   rpc_path=folder/'rpc.ndjson'
   rpc_text=rpc_path.read_text() if rpc_path.exists() else zlib.decompress(rpc_path.with_name(rpc_path.name+'.zlib').read_bytes()).decode()
   rpc_rows=[json.loads(r) for r in rpc_text.splitlines()]
   # Bootstrap genesis, census and initial tip are outside the one-pool warming.
   rpc=ReplayRPC(rpc_rows[positive.get('rpc_start_index',3):positive.get('rpc_end_index',len(rpc_rows))]);adapter=dlmm.Adapter(rpc,network_verified=True)
   snap=adapter.snapshot(pool,int(positive['first_scout_time']),True,True)
   origin=current=dlmm.validate(snap,int(rpc.last['sealed_at']),'real')
   cursor=[origin['slot'],2**31-1,2**31-1];minimal=[];full=[];chunk_results=[]
   trigger=None
   if positive.get('trigger'):
    compatibility_slot=current['slot']
    while current['slot']<positive['trigger']['fresh_state_slot']:
     next_time=int(rpc_rows[positive['rpc_start_index']+len(rpc.calls)]['sealed_at'])
     snapshot=adapter.snapshot_from_state(current,next_time,True,True)
     sigs,bodies,_=view.interval(pool,start_slot=current['slot'],end_slot=snapshot['slot'],as_of=clock[0])
     at=int(rpc.last['sealed_at'])
     a=dlmm_tape.reconstruct(current,snapshot,sigs,bodies,at,cursor)
     b=dlmm_tape.reconstruct(current,snapshot,sigs,{s['signature']:reference[s['signature']] for s in sigs if s['signature'] in reference},at,cursor)
     if (a.events,a.terminal)!=(b.events,b.terminal):raise ValueError('trigger_reference_difference')
     current=a.terminal;cursor=[current['slot'],2**31-1,2**31-1]
     if a.events:
      trigger=dict(authenticated=True,signature=a.events[0]['signature'],slot=a.events[0]['slot'],
       compatibility_slot=compatibility_slot,fresh_state_slot=current['slot'])
    if trigger is None or trigger['signature']!=positive['trigger']['signature']:raise ValueError('fresh_trigger_not_reproduced')
    origin=current
   for chunk in positive['chunks']:
    # Snapshot times affect freshness only; each exact provider response and
    # recorded native timestamp remains unchanged and independently replayable.
    next_time=int(rpc_rows[positive.get('rpc_start_index',3)+len(rpc.calls)]['sealed_at'])
    intervals=[]
    def interval(address,start_slot,end_slot):
     sigs,bodies,census=view.interval(address,start_slot=start_slot,end_slot=end_slot,as_of=clock[0]);intervals.append((sigs,bodies));return sigs,bodies,census
    plane=SimpleNamespace(meteora_interval=interval,count=lambda key:None)
    snapshots=[];snapshot_method=adapter.snapshot_from_state
    def capture_snapshot(*args,**kwargs):
     result=snapshot_method(*args,**kwargs);snapshots.append(result);return result
    # Same native warming function and normalized history commit, with archived
    # response timestamps replacing wall time and no network/sleep/monetary book.
    replay_time=SimpleNamespace(**{key:getattr(time,key) for key in dir(time) if not key.startswith('_')})
    replay_time.time=lambda:max(next_time,rpc.last['sealed_at'])
    # Replace only the native runner's clock binding. Patching time.time itself
    # contaminates concurrent source owners with this historical timestamp.
    with closing(CandidateHistory(h.lifecycle.path,clock=lambda:next_time)) as shared,patch.object(runner,'CANDIDATE_HISTORY',shared),patch.object(runner,'_evidence_plane',lambda:plane),patch.object(runner,'_stop_sleep',lambda n:None),patch.object(adapter,'snapshot_from_state',capture_snapshot),patch.object(runner,'time',replay_time):
     a,next_cursor,_=runner._capture_chunk(adapter,current,cursor,1)
    sigs,bodies=intervals[0];snapshot=snapshots[0]
    oracle={s['signature']:reference[s['signature']] for s in sigs if s['signature'] in reference}
    at=int(rpc.last['sealed_at'])
    b=dlmm_tape.reconstruct(current,snapshot,sigs,oracle,at,cursor)
    if (a.events,a.terminal,a.terminal_adjustments)!=(b.events,b.terminal,b.terminal_adjustments):raise ValueError('durable_reader_full_reference_difference')
    minimal.append(a);full.append(b);current=a.terminal
    cursor=next_cursor
    chunk_results.append(dict(start_slot=chunk['start_slot'],end_slot=snapshot['slot'],events=len(a.events),parity=True))
   narrow=dlmm_tape.chain_verified_tapes(origin,minimal);broad=dlmm_tape.chain_verified_tapes(origin,full);policy=runner.load_policy()
   # Public acceleration is unavailable in the structural path and has no
   # qualification authority. Both vectors use its explicit telemetry sentinel.
   context=dict(volume_acceleration=0.,fee_acceleration=0.)
   vector=runner.pre_entry_features(origin,narrow,current,context,policy);oracle_vector=runner.pre_entry_features(origin,broad,current,context,policy)
   if vector!=oracle_vector:raise ValueError('full_minimal_vector_difference')
   decision=runner.qualify(vector,policy)
   if not decision['passes']:raise ValueError('real_positive_not_qualified')
   # Exercise the exact position valuation/confirmation/safety/settlement
   # mechanics over real evidence, without any monetary authority.
   position=runner._build_position(origin,vector,policy)
   entry_flow={k:vector[k] for k in ('volume_rate_sol_lamports_per_second','fee_density')}
   reasons,recent,mark,uplift=runner._segment_exit(position,origin,narrow,current,entry_flow,policy)
   confirmed=runner._eligible_exit_reasons(reasons,elapsed_seconds=15,collapse_streaks=dict(volume_collapse=0,fee_density_collapse=0),policy=policy)
   result=dict(pool=pool,full_vector=oracle_vector,minimal_vector=vector,full_qualification=runner.qualify(oracle_vector,policy),minimal_qualification=decision,
     chunks=chunk_results,events=len(narrow.events),rpc_calls=len(rpc.calls),rpc_cu=len(rpc.calls)*20,
     scout_time=min(w['first_scout_time'] for w in summary['warmups']),
     promotion_time=min(w['promotion_time'] for w in summary['warmups']),
     positive_attempt_promotion_time=positive['promotion_time'],warm_start=positive['warming_start'],
     warm_complete=positive['warming_completion'],decision_deadline=min(w['decision_deadline'] for w in summary['warmups']),
     lead_time_margin_seconds=min(w['decision_deadline'] for w in summary['warmups'])-positive['warming_completion'],
     deadline_note='Conservative earliest original candidate deadline; the third positive attempt receives no deadline reset in this proof.',
     wall_clock_seconds=positive['wall_seconds'],http_bytes=positive['rpc_bytes'],
     captured_provider_grpc_bytes=summary['provider_grpc_bytes'],transaction_body_rpc_fetches=0,
     block_fetches=0,account_fetches=sum(len(r['params'][0]) for r in rpc.calls if r['method']=='getMultipleAccounts'),
     canonical_records=writer.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0],
     position_equivalent=dict(mark=mark,exit_reasons=reasons,confirmed_exits=confirmed),
     source_commit_seconds=latencies,trigger=trigger,classification='MEASURED_REPLAY',qualified=True)
  writer.close()
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('capture');p.add_argument('--output',required=True);a=p.parse_args()
 result=run(a.capture);Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k not in ('full_vector','minimal_vector','chunks','position_equivalent','source_commit_seconds')},indent=2))
