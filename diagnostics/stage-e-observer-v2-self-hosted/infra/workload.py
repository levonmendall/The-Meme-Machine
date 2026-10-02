"""Approved observer adapter around the unchanged native pressure workload."""
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch
import bound_runtime as bound
from core import BASE,S,REAL_NS,COHORT,persist,read
from tape import Reader


def checkpoint(control,path,native,observed):
    """Identical reader/checkpoint/sleep work; qualification reads are explicit."""
    from certification import combined_observer as qualification
    control.path=Path(path)
    with control.lock:
        phase=control.batching_phase;exercise=phase>control.checkpoint_phase
        if exercise:control.checkpoint_phase=phase
    if exercise:
        sample=control.metrics['burst_evidence'][phase-1]
        with closing(sqlite3.connect(path,isolation_level=None)) as reader:
            reader.execute('BEGIN')
            before=dict(reader.execute('SELECT key,value FROM counters'))
            if observed:sample['eligible_at_reader_start']=qualification.eligible(reader)
            with control.lock:control.reader_phase=phase
            try:
                time.sleep(1.25)
                native(path)
                time.sleep(.1)
                if observed:
                    with control.lock:qualification.observe_window(reader,path,before,sample)
            finally:
                with control.lock:control.reader_phase=0
                reader.execute('ROLLBACK')
        with control.lock:
            control.metrics['held_reader_cycles']+=1;control.tail_pending=phase
    result=native(path)
    with control.lock:tail=control.tail_pending
    if tail and result[0]==0 and result[1]==result[2]:
        time.sleep(.75)
        with control.lock:
            control.metrics['tail_delay_cycles']+=1
            control.metrics['burst_evidence'][tail-1]['completed_tail_delayed']=True
            control.tail_pending=0
    return result


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


async def run_member():
    from certification import run381_pressure as original,combined_pressure as legacy
    from certification import combined_observer as qualification,cleanup_recovery as recovery
    from certification import lifecycle_capacity,pressure_diagnostics as diag
    from meme_machine.solana_evidence_plane import EvidenceWriter
    import concurrent.futures
    params=bound.PARAMS;output=Path(params['output'])
    frames=params['frames'];observed=params['mode']=='observed'
    control=qualification.Interaction()
    control.checkpoint=lambda path,native:checkpoint(control,path,native,observed)
    recovery.PLAN_PATH=BASE/'assembly/source/certification/stagee24_qualification_plan.json'
    observer=lifecycle_capacity.LifecycleObserver(output) if observed and params['member']=='recovery-1' else None
    native_checkpoint=EvidenceWriter.checkpoint
    native_state=original.MeasuredServiceState
    native_pool=original.NativeProcessPool
    native_classify=diag.statement_class
    wire_holder=[]
    class State(native_state):
        def __init__(self,path,config):
            super().__init__(path,config)
            if observer:observer.attach(path)
        def close(self):
            if observer:observer.stop.set()
            return super().close()
        def source_batch(self,items):
            phase=control.source_started(len(items))
            result=super().source_batch(items)
            control.source_completed(phase,len(items))
            return result
    def pool(*args,**kwargs):
        if 'mp_context' not in kwargs:
            kwargs['initializer']=bound.fork_initializer
        return native_pool(*args,**kwargs)
    class TapeWire:
        def __init__(self):
            self.reader=Reader(frames);self.template=self.reader.next();self.pending=self.template
            self.frames=frames;self.sent=0;self.acks=asyncio.Queue();self.start=None
            self.paused=set();self.pause_deadline=None;self.pause_started=None;self.pause_sample=None
            self.first_release=None;self.samples=[];wire_holder.append(self)
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def send(self,raw):
            r=json.loads(raw)
            await self.acks.put(json.dumps(dict(id=r['id'],result=r['id'])).encode())
        async def recv(self,decode=None):
            if not self.acks.empty():return await self.acks.get()
            if self.sent>=self.frames:return await self.acks.get()
            if self.sent in (800,1400) and self.sent not in self.paused:
                self.paused.add(self.sent);sample=await asyncio.to_thread(control.inspect)
                sample['source_seconds']=self.sent*.27;control.metrics['burst_evidence'].append(sample)
                self.pause_started=time.monotonic();self.pause_deadline=self.pause_started+8
                self.pause_sample=sample
            if self.pause_deadline is not None:
                await asyncio.sleep(max(0,self.pause_deadline-time.monotonic()))
                self.pause_sample['observed_pause_seconds']=time.monotonic()-self.pause_started
                self.pause_deadline=None
                with control.lock:control.phase+=1
            if self.first_release is not None:
                due=self.first_release+self.sent*270000000
                await asyncio.sleep(max(0,(due-REAL_NS())/10**9))
            # Cancellation can occur while awaiting cadence; consume tape only
            # after that wait completes. No cadence/deadline is ever shifted.
            raw=self.pending if self.pending is not None else self.reader.next()
            self.pending=None
            if self.first_release is None:
                self.start=1800000000
                self.first_release=bound.CLOCK.activate()
            self.sent+=1
            if self.sent==1 or self.sent%100==0 or self.sent==self.frames:
                self.samples.append(dict(frames=self.sent,**bound.CLOCK.sample()))
            if self.sent>=self.frames:control.stopping=True
            return raw
    class PersistentDirectory:
        def __enter__(self):
            self.path=Path(params['runtime']);self.path.mkdir(parents=True,exist_ok=False)
            if len(str(self.path/'db.sock').encode())>=108:raise ValueError('unix_socket_path_length')
            return str(self.path)
        def __exit__(self,*args):pass
    ack=asyncio.create_task(control.acknowledgements())
    try:
        with patch.object(original,'Wire',TapeWire),patch.object(original,'MeasuredServiceState',State),\
             patch.object(original,'NativeProcessPool',pool),\
             patch.object(original.tempfile,'TemporaryDirectory',PersistentDirectory),\
             patch.object(EvidenceWriter,'checkpoint',side_effect=lambda path:control.checkpoint(path,native_checkpoint)),\
             patch.object(recovery,'PLAN_PATH',BASE/'assembly/source/certification/stagee24_qualification_plan.json'),\
             patch.object(diag,'statement_class',new=lambda sql:recovery.sql_phase(sql,native_classify) if params['member']=='recovery-1' else native_classify(sql)):
            code=await original.run(frames,output,measured_contention=True,diagnostics=params['member']=='recovery-1')
    finally:
        control.stopping=True
        await asyncio.gather(ack,return_exceptions=False)
        if observer:observer.close()
    row=read(output/'result.json');row['combined_load']=control.metrics
    row['observer_mode']=params['mode'];row['observer_errors']=observer.errors if observer else []
    if observer:
        # Native pure assessment is an observer cost; it grants no Stage-E credit.
        row['observer_assessment']=lifecycle_capacity.assessment(observer.samples,observer.errors)
    row['workload_valid']=code==0 and common_valid(row,frames)
    if observed:
        row['observation_valid']=qualification.observation_verified(row) and not row['observer_errors']
        if observer:row['observation_valid']=row['observation_valid'] and len(observer.samples)>=30
    else:row['observation_valid']=True
    if len(wire_holder)!=1:raise ValueError('multiple_source_wires')
    wire=wire_holder[0]
    tape=wire.reader.close(strict=False)
    row['workload_valid']=row['workload_valid'] and tape['valid'] and wire.sent==frames
    persist(output/'SOURCE_RECEIPT.json',dict(member=params['member'],mode=params['mode'],
        tape=tape,source_frames_released=wire.sent,first_release_real_monotonic_ns=wire.first_release,
        immutable_semantic_wall_epoch=1800000000,immutable_semantic_monotonic_epoch=100,
        clock_samples=wire.samples,retiming_calls=0))
    persist(output/'MEMBER_RESULT.json',row)
    if not row['workload_valid'] or not row['observation_valid']:
        raise ValueError('member_workload_or_observation_invalid')


def main():
    asyncio.run(run_member())
