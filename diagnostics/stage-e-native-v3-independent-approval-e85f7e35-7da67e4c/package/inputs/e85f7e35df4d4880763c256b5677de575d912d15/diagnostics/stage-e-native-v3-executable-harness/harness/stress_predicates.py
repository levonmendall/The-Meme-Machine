"""Exact historical external common_valid predicate, C diagnostics only."""
from core import S

def common_valid(row,frames):
    c=row.get('counters',{});ipc=row.get('ipc',{});joint=row.get('combined_load',{})
    bursts=joint.get('burst_evidence',[]);profile=row.get('measured_contention',{})
    return bool(row.get('passed') is True and row.get('integration_sha')==S
        and row.get('frames')==frames and row.get('source_seconds')==frames*.27
        and c.get('stream_accepted_messages')==frames
        and ipc.get('stream.received_messages')==ipc.get('stream.commit_messages')==frames+1
        and 16<=ipc.get('stream.outstanding_frames_peak',0)<=64
        and 0<ipc.get('stream.dispatch_bytes_peak',0)<=96*1024**2
        and 2<=ipc.get('stream.commit_batch_messages_peak',0)<=8
        and 0<ipc.get('stream.commit_batch_bytes_peak',0)<=16*1024**2
        and all(ipc.get(k,0)>0 for k in ('stream.maintenance_backpressure_batching',
            'stream.maintenance_limited_commit_batches','checkpoint.tail_deferred','checkpoint.boundary_reclaimed'))
        and row.get('provider_calls')==0 and row.get('integrity')==['ok']
        and 0<=row.get('lag_peak',float('inf'))<45
        and 0<row.get('oldest_hot_age_peak',float('inf'))<240
        and 0<row.get('oldest_retained_age_peak',float('inf'))<240
        and 0<row.get('hot_peak',float('inf'))<2*1024**3
        and row.get('candidate_checks',0)>1 and row.get('archive_records_verified',0)>0
        and c.get('compacted_records',0)>0
        and not any(v for k,v in c.items() if k.startswith('disconnect:') or k=='capacity_stops')
        and profile.get('profile')=='run381-fullcert-36293751021'
        and profile.get('owner_seconds_per_frame')==.165
        and profile.get('archive_seconds_per_thousand')==.36
        and profile.get('additional_commit_latency_seconds')==.006
        and profile.get('delayed_commits',0)>0
        and joint.get('held_reader_cycles',0)>=2 and joint.get('tail_delay_cycles',0)>=2
        and joint.get('urgent_acks',0)>=10 and joint.get('urgent_errors')==[]
        and len(bursts)==2 and all(s.get('source_seconds',0)>=210
            and s.get('archived_records',0)>0 and s.get('compacted_records',0)>0
            and s.get('observed_pause_seconds',0)>=8 and s.get('multiframe_batches',0)>0
            and s.get('completed_tail_delayed') is True for s in bursts))
