"""C only: exact preserved run381 contention and adversarial interference."""
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch
import bound_runtime as bound
from core import S,REAL_NS,COHORT,read,workload,require,sha
from preserve import persist
from production import read_snapshot,native_archive_proof
from verify import stress_member_result
from stress_predicates import common_valid
from overload import restart_witness
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




async def run_member():
    from certification import run381_pressure as original,combined_pressure as legacy
    from certification import combined_observer as qualification,cleanup_recovery as recovery
    from certification import lifecycle_capacity,pressure_diagnostics as diag
    from meme_machine.solana_evidence_plane import EvidenceWriter
    import concurrent.futures
    params=bound.PARAMS;output=Path(params['output'])
    require(params['kind']=='C','synthetic_contention_only_in_C')
    frames=params['frames'];observed=True
    control=qualification.Interaction() if observed else legacy.Interaction()
    control.checkpoint=lambda path,native:checkpoint(control,path,native,observed)
    recovery.PLAN_PATH=Path(params['assembly'])/'source/certification/stagee24_qualification_plan.json'
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
            if observed:control.source_completed(phase,len(items))
            return result
    def pool(*args,**kwargs):
        require('mp_context' in kwargs,'C_shared_spawn_pool_required')
        return native_pool(*args,**kwargs)
    class TapeWire:
        def __init__(self):
            expected=next(m for m in workload('C')['tape_binding']['members'] if m['id']==params['member'])
            self.reader=Reader(params['tape_path'],expected);self.template=self.reader.next()[0];self.pending=self.template
            self.frames=frames;self.sent=0;self.acks=asyncio.Queue();self.start=None
            self.paused=set();self.pause_deadline=None;self.pause_started=None;self.pause_sample=None
            self.pause_inspection=None
            self.first_release=None;self.samples=[];self.raw_hashes=[];wire_holder.append(self)
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def send(self,raw):
            r=json.loads(raw)
            await self.acks.put(json.dumps(dict(id=r['id'],result=r['id'])).encode())
        async def recv(self,decode=None):
            if not self.acks.empty():return await self.acks.get()
            if self.sent>=self.frames:return await self.acks.get()
            if self.sent in (800,1400) and self.sent not in self.paused:
                self.paused.add(self.sent)
                self.pause_inspection=asyncio.create_task(asyncio.to_thread(control.inspect))
            if self.pause_inspection is not None:
                # Preserve the required pause even when recv's native .5-second
                # polling timeout cancels a slow control snapshot.
                sample=await asyncio.shield(self.pause_inspection)
                sample['source_seconds']=self.sent*.27;control.metrics['burst_evidence'].append(sample)
                self.pause_started=time.monotonic();self.pause_deadline=self.pause_started+8
                self.pause_sample=sample
                self.pause_inspection=None
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
            raw=self.pending if self.pending is not None else self.reader.next()[0]
            bound.ensure_release()
            self.pending=None
            if self.first_release is None:
                self.start=1800000000
                self.first_release=bound.CLOCK.activate()
            self.raw_hashes.append(dict(number=self.sent,sha256=sha(raw),bytes=len(raw),
                                        released_real_monotonic_ns=REAL_NS()))
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
             patch.object(recovery,'PLAN_PATH',Path(params['assembly'])/'source/certification/stagee24_qualification_plan.json'),\
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
        clock_samples=wire.samples,raw_release_hashes=wire.raw_hashes,
        last_release_real_monotonic_ns=wire.raw_hashes[-1]['released_real_monotonic_ns'] if wire.raw_hashes else None,
        retiming_calls=0,declaration_sha256=params['declaration_sha256']))
    row.update(version='stage-e-native-v3-stress-member',kind='C',member=params['member'],
        mode=params['mode'],artificial_contention=workload('C')['artificial_contention'],
        candidate_sha=S,declaration_sha256=params['declaration_sha256'],
        source_receipt=read(output/'SOURCE_RECEIPT.json'),runtime_path=str(Path(params['runtime'])/'db'),
        final=read_snapshot(Path(params['runtime'])/'db'),provider_attempts=list(bound.PROVIDER_ATTEMPTS),
        observer_samples=observer.samples if observer else [],
        archives=native_archive_proof(Path(params['runtime'])/'db'))
    # Snapshot and preserve the actual failed/full native DB before any restart.
    # A wrapper stop cannot supply this native refusal witness.
    row['native_restart']=restart_witness(Path(params['runtime'])/'db',output,
        native_failure=row.get('failure'),failure_frames=row.get('failure_frames',[]))
    classification=stress_member_result(row)
    row.update(classification)
    persist(output/'MEMBER_RESULT.json',row)
    if not row['mandatory_native_safety_pass']:
        raise ValueError('mandatory_C_native_safety_not_proved')
    # A native safe overload is a terminal protocol result, with the original
    # FAILED_DIAGNOSTIC preserved. The trial stops further members and the
    # controller grants C safety only after independent raw verification.



def main():
    asyncio.run(run_member())
