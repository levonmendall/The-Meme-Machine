"""Supplemental mature-pressure interaction proof; canonical driver is unchanged.

Catch-up bursts begin after retention is mature. Real SQLite readers are armed
only by actual multi-frame source batches, not by the preceding source pause.
Durable source and cleanup progress must occur during each held read snapshot.
All control requests use real local IPC. No external provider is called.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import threading
import time
from unittest.mock import patch


def verified(row,expected_sha):
    if not isinstance(row,dict):return False
    c=row.get('counters') or {};ipc=row.get('ipc') or {}
    profile=row.get('measured_contention') or {};joint=row.get('combined_load') or {}
    samples=joint.get('burst_evidence') or []
    return bool(
        row.get('passed') is True and row.get('integration_sha')==expected_sha
        and row.get('provider_calls')==0 and row.get('frames')==2223
        and row.get('source_seconds',0)>=600
        and c.get('stream_accepted_messages')==2223
        and ipc.get('stream.received_messages')==ipc.get('stream.commit_messages')==2224
        and 16<=ipc.get('stream.outstanding_frames_peak',0)<=64
        and 0<ipc.get('stream.dispatch_bytes_peak',0)<=96*1024*1024
        and 2<=ipc.get('stream.commit_batch_messages_peak',0)<=8
        and 0<ipc.get('stream.commit_batch_bytes_peak',0)<=16*1024*1024
        and ipc.get('stream.maintenance_backpressure_batching',0)>0
        and ipc.get('stream.maintenance_limited_commit_batches',0)>0
        and ipc.get('checkpoint.tail_deferred',0)>0
        and row.get('candidate_checks',0)>1
        and row.get('archive_records_verified',0)>0 and c.get('compacted_records',0)>0
        and not any(v for k,v in c.items() if k.startswith('disconnect:') or k=='capacity_stops')
        and 0<=row.get('lag_peak',float('inf'))<45
        and 0<row.get('oldest_hot_age_peak',float('inf'))<=240
        and 0<row.get('oldest_retained_age_peak',float('inf'))<=240
        and 0<row.get('hot_peak',float('inf'))<2*1024**3
        and row.get('integrity')==['ok']
        and profile.get('profile')=='run381-fullcert-36293751021'
        and profile.get('owner_seconds_per_frame',0)>=.165
        and profile.get('archive_seconds_per_thousand',0)>=.36
        and profile.get('additional_commit_latency_seconds',0)>=.006
        and profile.get('delayed_commits',0)>0
        and joint.get('profile')=='mature-burst-reader-tail-urgent-v2'
        and joint.get('held_reader_cycles',0)>=2 and joint.get('tail_delay_cycles',0)>=2
        and joint.get('urgent_acks',0)>=10 and joint.get('urgent_errors')==[]
        and len(samples)==2
        and all(s.get('source_seconds',0)>=210 and s.get('archived_records',0)>0
                and s.get('compacted_records',0)>0
                and s.get('observed_pause_seconds',0)>=8
                and s.get('multiframe_batches',0)>0
                and s.get('source_frames_while_reader',0)>0
                and s.get('reader_source_advance',0)>0
                and s.get('reader_compaction_advance',0)>0
                and s.get('reader_snapshot_preserved') is True
                and s.get('completed_tail_delayed') is True for s in samples))


class Interaction:
    def __init__(self):
        self.path=None;self.phase=0;self.batching_phase=0;self.reader_phase=0
        self.checkpoint_phase=0;self.tail_pending=0;self.stopping=False
        self.lock=threading.Lock()
        self.metrics=dict(profile='mature-burst-reader-tail-urgent-v2',
            source_pause_seconds=8,burst_evidence=[],held_reader_cycles=0,
            tail_delay_cycles=0,urgent_acks=0,urgent_errors=[])

    def inspect(self):
        if self.path is None:raise ValueError('combined_database_not_initialized')
        with closing(sqlite3.connect(self.path)) as db:
            counters=dict(db.execute('SELECT key,value FROM counters'))
        return {k:counters.get(k,0) for k in
                ('stream_accepted_messages','archived_records','compacted_records')}

    def source_started(self,size):
        with self.lock:
            if self.phase and size>1:
                sample=self.metrics['burst_evidence'][self.phase-1]
                sample['multiframe_batches']=sample.get('multiframe_batches',0)+1
                self.batching_phase=self.phase
            return self.reader_phase

    def source_completed(self,reader_phase,size):
        with self.lock:
            if reader_phase and reader_phase==self.reader_phase:
                sample=self.metrics['burst_evidence'][reader_phase-1]
                sample['source_frames_while_reader']=sample.get('source_frames_while_reader',0)+size

    def checkpoint(self,path,native):
        self.path=Path(path)
        with self.lock:
            phase=self.batching_phase;exercise=phase>self.checkpoint_phase
            if exercise:self.checkpoint_phase=phase
        if exercise:
            sample=self.metrics['burst_evidence'][phase-1]
            with closing(sqlite3.connect(path,isolation_level=None)) as reader:
                reader.execute('BEGIN')
                before=dict(reader.execute('SELECT key,value FROM counters'))
                with self.lock:self.reader_phase=phase
                try:
                    time.sleep(1.25)
                    native(path)
                    time.sleep(.1)
                    after=dict(reader.execute('SELECT key,value FROM counters'))
                    if before!=after:raise AssertionError('combined_reader_snapshot_changed')
                    sample['reader_snapshot_preserved']=True
                finally:
                    with self.lock:self.reader_phase=0
                    reader.execute('ROLLBACK')
            current=self.inspect()
            sample['reader_source_advance']=current['stream_accepted_messages']-before.get('stream_accepted_messages',0)
            sample['reader_compaction_advance']=current['compacted_records']-before.get('compacted_records',0)
            with self.lock:
                self.metrics['held_reader_cycles']+=1;self.tail_pending=phase
        result=native(path)
        with self.lock:tail=self.tail_pending
        if tail and result[0]==0 and result[1]==result[2]:
            # Delay only a genuinely complete PASSIVE receipt. This does not
            # falsify SQLite's return value or add owner-side execution work.
            time.sleep(.75)
            with self.lock:
                self.metrics['tail_delay_cycles']+=1
                self.metrics['burst_evidence'][tail-1]['completed_tail_delayed']=True
                self.tail_pending=0
        return result

    async def acknowledgements(self):
        from meme_machine.solana_evidence_runtime import RuntimeEvidence
        while not self.stopping:
            if self.path is not None:
                def acknowledge():
                    if self.inspect()['stream_accepted_messages']<10:return False
                    plane=RuntimeEvidence(self.path,owner='meteora')
                    try:
                        top=plane.frontier('program:meteora')
                        plane.command(op='ack',owner='meteora:combined-pressure',scope='program:meteora',slot=top)
                        return True
                    finally:plane.close()
                try:
                    if await asyncio.to_thread(acknowledge):self.metrics['urgent_acks']+=1
                except Exception as exc:
                    if not self.stopping:
                        self.metrics['urgent_errors'].append(type(exc).__name__)
                        return
            await asyncio.sleep(1)


async def run(output):
    from certification import run381_pressure as original
    from meme_machine.solana_evidence_plane import EvidenceWriter
    control=Interaction();native_checkpoint=EvidenceWriter.checkpoint
    class ObservedState(original.MeasuredServiceState):
        def source_batch(self,items):
            reader_phase=control.source_started(len(items))
            result=super().source_batch(items)
            control.source_completed(reader_phase,len(items))
            return result
    class BurstWire(original.Wire):
        def __init__(self):
            super().__init__();self.paused=set();self.pause_deadline=None;self.pause_started=None;self.pause_sample=None
        async def recv(self,decode=None):
            if self.sent in (800,1400) and self.sent not in self.paused:
                self.paused.add(self.sent)
                sample=await asyncio.to_thread(control.inspect)
                sample['source_seconds']=self.sent*.27
                control.metrics['burst_evidence'].append(sample)
                self.pause_started=time.monotonic();self.pause_deadline=self.pause_started+8
                self.pause_sample=sample
            if self.pause_deadline is not None:
                # Preserve the deadline when production wait_for(recv,.5)
                # cancels a poll; do not accidentally remove the intended burst.
                await asyncio.sleep(max(0,self.pause_deadline-time.monotonic()))
                self.pause_sample['observed_pause_seconds']=time.monotonic()-self.pause_started
                self.pause_deadline=None
                with control.lock:control.phase+=1
            # Original timestamps and the 600.21-second horizon do not move.
            result=await super().recv(decode)
            if self.sent>=self.frames:control.stopping=True
            return result
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    acknowledgements=asyncio.create_task(control.acknowledgements())
    try:
        with patch.object(original,'Wire',BurstWire),patch.object(original,'MeasuredServiceState',ObservedState),patch.object(
                EvidenceWriter,'checkpoint',side_effect=lambda path:control.checkpoint(path,native_checkpoint)):
            code=await original.run(2223,output,measured_contention=True)
    finally:
        control.stopping=True
        await asyncio.gather(acknowledgements,return_exceptions=False)
    path=output/'result.json';row=json.loads(path.read_text());row['combined_load']=control.metrics
    row['passed']=code==0 and row.get('passed') is True and verified(row,row.get('integration_sha'))
    if not row['passed'] and not row.get('failure'):row['failure']='combined_interaction_not_proved'
    path.write_text(json.dumps(row,indent=2)+'\n')
    print(json.dumps(dict(passed=row['passed'],failure=row.get('failure'),
        integration_sha=row['integration_sha'],combined_load=control.metrics)))
    return 0 if row['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args().output)))
