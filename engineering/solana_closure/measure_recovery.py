"""Replay durable restart boundaries using an authenticated 103-tx archive."""
import argparse,json,sqlite3,subprocess,sys,tempfile,time,zlib
from contextlib import closing
from pathlib import Path
from meme_machine.solana_evidence_plane import EvidenceWriter
from meme_machine.solana_evidence_service import FinalizedFence
from meme_machine.solana_selective_source import install
from meme_machine.solana_selective_history import coverage_scope
from types import SimpleNamespace

def replay(capture,checkpoint):
 capture=Path(capture)
 archived=json.loads(zlib.decompress(capture.read_bytes()) if capture.suffix=='.zlib' else capture.read_text());facts=archived['result'];pages=archived['pages']
 first=pages[0]['data'][0];mint='7sYAHmtqvPTbjqAERhDJRiXrFta1NXPtEv5WwAeMpump';curve='EioKN3ovjTe1hKVoTTBGt7WfQ71TNDMGzXBiKNfki3RV'
 now=[first['blockTime']+1000.];clock=lambda:now[0];timings=[]
 with tempfile.TemporaryDirectory() as d:
  path=Path(d)/'canonical.sqlite'
  def start():
   begin=time.perf_counter();w=EvidenceWriter(path,clock=clock);s=SimpleNamespace(writer=w,fence=FinalizedFence(w,endpoint_identity='a'*64));h=install(s);h.clock=h.lifecycle.clock=clock;timings.append(time.perf_counter()-begin);return s,h
  s,h=start();h.observe('pump',curve,slot=first['slot'],signature='',seen=now[0]-10,fields={});h.bind('pump',curve,market_address=mint,aliases=(mint,))
  h.request('pump',curve,facts['creation_slot'],facts['late_overlap_upper_slot'],priority=1,deadline=now[0]+150)
  job=h.plan()[0];h.commit_page(job,pages[0],finalized_through=job['hi']);h.lifecycle.publish()
  partial_count=h.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0];s.writer.close()
  start_restart=time.perf_counter();s,h=start();rebuilt=time.perf_counter()-start_restart;job=h.plan()[0]
  missing=h.lifecycle.missing(coverage_scope('pump',curve),job['lo'],job['hi']);original_deadline=job['deadline'];calls=0;received=0;before=time.perf_counter()
  for page in pages[1:]:
   calls+=1;received+=len(page['data']);h.commit_page(job,page,finalized_through=job['hi']);h.lifecycle.publish();plan=h.plan()
   if plan:job=plan[0]
  catchup=time.perf_counter()-before;canonical=h.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0]
  # Overlapping replay admits no duplicate economic record or history event.
  identities_before=h.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0]
  for page in pages:
   h.request('pump',curve,facts['creation_slot'],facts['late_overlap_upper_slot']+1,priority=1,deadline=original_deadline)
   current=h.plan()[0];h.commit_page(current,page,finalized_through=current['hi']);h.lifecycle.publish()
  duplicate_admitted=h.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0]-identities_before
  s.writer.close()
 checkpoint=Path(checkpoint)
 if checkpoint.suffix=='.json':
  historical=json.loads(checkpoint.read_text());reconnects=historical['reconnects'];spans=historical['session_spans']
 else:
  historical=sqlite3.connect('file:'+str(checkpoint)+'?mode=ro&immutable=1',uri=True)
  reconnects=historical.execute("SELECT value FROM counters WHERE key='stream_reconnects'").fetchone()[0]
  spans=historical.execute('SELECT MIN(seen),MAX(seen),COUNT(*) FROM stream_receipts GROUP BY session').fetchall();historical.close()
 exposure=sum(hi-lo for lo,hi,n in spans);rate=reconnects*86400/exposure
 return dict(classification='MEASURED_REPLAY',replayed_transactions=facts['transactions'],
  raw_provider_bytes_per_reconnect=facts['provider_bytes'],rpc_cu_per_reconnect=facts['cu'],rpc_calls_per_reconnect=facts['rpc_calls'],
  provider_capture_catchup_seconds=facts['wall_seconds'],replay_processing_catchup_seconds=catchup,
  restart_detection_seconds=timings[-1],subscription_interest_rebuild_seconds=rebuilt,
  gap_slots=facts['late_overlap_upper_slot']-facts['creation_slot']+1,missing_interval=missing,
  original_deadline=original_deadline,resumed_archive_calls=calls,resumed_transactions=received,
  partial_canonical_records=partial_count,canonical_records=canonical,duplicates_received=facts['transactions'],duplicates_canonically_admitted=duplicate_admitted,
  historical_reconnects=reconnects,historical_visible_connected_seconds=exposure,historical_sessions=len(spans),
  expected_reconnects_per_day=rate,high_reconnects_per_day=rate*2,
  expected_replay_provider_bytes_per_day=facts['provider_bytes']*rate,expected_replay_cu_per_day=facts['cu']*rate,
  frequency_classification='DERIVED',frequency_source=str(checkpoint),
  frequency_limitation='Legacy broad topology, retained visible session spans give a conservative exposure denominator; not a new-topology live rate.',
  continuity_complete=duplicate_admitted==0 and facts['pagination_exhausted'])

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('capture');p.add_argument('checkpoint');p.add_argument('--output',required=True);a=p.parse_args();result=replay(a.capture,a.checkpoint);Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
