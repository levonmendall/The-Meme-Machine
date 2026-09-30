"""Experimental two-slot carrier; never imported by canonical production.

Logical quotas are shared, including full membership and plans after slicing.
One preparation executor job; the native pool and SQL owner are unchanged.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
import hashlib, json, pickle, sys, time
from .solana_evidence_plane import EvidenceWriter, EvidenceUnavailable, canonical

RECORD_CAP = 1000
ENCODED_CAP = 20*1024*1024
SNAPSHOT_TARGET = 4*1024*1024
BODY_CAP = 16*1024*1024
FILE_CAP = BODY_CAP+ENCODED_CAP+RECORD_CAP*512
PRIMARY_RECORDS = 750

def deep_bytes(value, seen=None):
    seen=set() if seen is None else seen
    key=id(value)
    if key in seen:return 0
    seen.add(key);size=sys.getsizeof(value)
    if isinstance(value,dict):
        size+=sum(deep_bytes(k,seen)+deep_bytes(v,seen) for k,v in value.items())
    elif isinstance(value,(tuple,list,set,frozenset,deque)):
        size+=sum(deep_bytes(v,seen) for v in value)
    return size

def fraction(limit, records):
    return limit*records//RECORD_CAP

@dataclass
class ArchiveFlight:
    future: object = None
    submitted: float | None = None
    pending: tuple | None = None
    prepared: dict | None = None
    generation: str | None = None
    lookahead: object = None
    reservation: int = PRIMARY_RECORDS
    membership: tuple = ()
    retained_snapshot: dict | None = None
    full_plan: list | None = None
    cycle: object = None
    serial_bytes: int = 0
    encoded_bytes: int = 0
    events: object = field(default_factory=lambda:deque(maxlen=64))
    peaks: dict = field(default_factory=dict)

    @property
    def idle(self):
        return self.future is None and self.pending is None and self.prepared is None and self.lookahead is None

    def slots(self):
        if self.lookahead is not None and self.lookahead.lookahead is not None:
            raise EvidenceUnavailable('overlap_third_slot')
        return [self]+([self.lookahead] if self.lookahead is not None else [])

    def hold(self,snapshot,generation,at):
        if not snapshot:return
        if self.future is not None or self.pending is not None or self.prepared is not None:
            raise EvidenceUnavailable('overlap_slot_occupied')
        snapshot['_overlap_reservation']=self.reservation
        members=tuple((r['identity'],r['hash']) for r in snapshot['rows'])
        if len(members)>self.reservation or len(set(members))!=len(members):
            raise EvidenceUnavailable('overlap_record_reservation')
        # Count actual retained dictionaries, references and serialized arguments.
        serial=pickle.dumps(snapshot,protocol=pickle.HIGHEST_PROTOCOL)
        roots=(snapshot,members)
        if (snapshot['encoded_bytes']>fraction(ENCODED_CAP,self.reservation)
            or len(serial)>fraction(ENCODED_CAP,self.reservation)
            or deep_bytes(roots)>fraction(ENCODED_CAP,self.reservation)):
            raise EvidenceUnavailable('overlap_encoded_reservation')
        self.serial_bytes=len(serial);self.encoded_bytes=snapshot['encoded_bytes']
        self.membership=members;self.prepared=snapshot;self.retained_snapshot=snapshot
        self.generation=generation
        self.events.append(dict(event='snapshot_selected',at=at,records=len(members),
                                reservation=self.reservation))

    def attach(self,future,submitted,generation):
        # Explicit replacement of the former one-future/receipt carrier.
        if self.future is not None or self.pending is not None or self.prepared is None:
            raise EvidenceUnavailable('overlap_slot_attachment')
        if generation!=self.generation:
            raise EvidenceUnavailable('maintenance_receipt_generation_changed')
        self.prepared=None;self.future=future;self.submitted=submitted
        self.cycle=getattr(future,'_ablation_cycle',None)
        self.events.append(dict(event='preparation_submitted',at=submitted))

    def launch_slot(self):
        prepared=[s for s in self.slots() if s.prepared is not None]
        if len(prepared)>1:
            raise EvidenceUnavailable('overlap_multiple_launches')
        if prepared and any(s.future is not None and not s.future.done() for s in self.slots()):
            raise EvidenceUnavailable('overlap_executing_worker_bound')
        return prepared[0] if prepared else None

    def poll(self,runtime,now):
        for s in self.slots():
            if s.generation is not None and s.generation!=runtime.generation:
                raise EvidenceUnavailable('maintenance_receipt_generation_changed')
            if s.future is None:continue
            if s.submitted is None or s.submitted>now:
                raise EvidenceUnavailable('maintenance_receipt_clock_invalid')
            if not s.future.done():
                if now-s.submitted>=runtime.leases.worker:
                    raise EvidenceUnavailable('maintenance_archive_worker_lease_exceeded')
                continue
            value=s.future.result()  # cancellation/errors revoke native admission
            plan,receipt=value
            if tuple((r['identity'],r['hash']) for r in plan)!=s.membership:
                raise EvidenceUnavailable('overlap_worker_identity_conflict')
            s.full_plan=plan;s.pending=value if plan else None;s.future=None
            if s.retained_snapshot is not None:s.retained_snapshot.clear()
            s.retained_snapshot=None
            s.events.append(dict(event='preparation_completed_observed',at=now))
        self.check(runtime.state.last_measured_archive_receipt)

    def check(self,telemetry_receipt=None):
        slots=self.slots()
        reserved=sum(s.reservation for s in slots if s.membership)
        members=[m for s in slots for m in s.membership]
        if reserved>RECORD_CAP or len(members)>RECORD_CAP:
            raise EvidenceUnavailable('overlap_aggregate_records')
        if len({m[0] for m in members})!=len(members):
            raise EvidenceUnavailable('overlap_membership_conflict')
        workers=sum(s.future is not None and not s.future.done() for s in slots)
        if workers>1:raise EvidenceUnavailable('overlap_executing_worker_bound')
        encoded=sum(s.encoded_bytes for s in slots)
        serial=sum(s.serial_bytes for s in slots)
        roots=[telemetry_receipt]
        for s in slots:
            roots.extend((s.membership,s.pending,s.full_plan,s.prepared,s.retained_snapshot,s.events,s.peaks,s.cycle))
            if s.future is not None and s.future.done() and not s.future.cancelled():
                error=s.future.exception()
                if error is None:roots.append(s.future.result())
        heap=deep_bytes(roots)
        if max(encoded,serial,heap)>ENCODED_CAP:
            raise EvidenceUnavailable('overlap_aggregate_bytes')
        values=dict(slots=len([s for s in slots if s.membership]),reserved_records=reserved,
                    membership_records=len(members),parent_retained_bytes=heap,
                    serialized_arguments_reserved_bytes=serial,encoded_reserved_bytes=encoded,
                    executing_preparations=workers)
        for k,v in values.items():self.peaks[k]=max(v,self.peaks.get(k,0))
        return values

    def promote(self,runtime,now):
        if self.pending is not None or self.future is not None or self.prepared is not None:
            raise EvidenceUnavailable('overlap_promotion_before_drain')
        if self.lookahead is None:return
        next_slot=self.lookahead
        if next_slot.generation!=runtime.generation:
            raise EvidenceUnavailable('maintenance_receipt_generation_changed')
        original_submitted=next_slot.submitted
        for name in ('future','submitted','pending','prepared','generation','reservation',
                     'membership','retained_snapshot','full_plan','cycle','serial_bytes','encoded_bytes'):
            setattr(self,name,getattr(next_slot,name))
        self.lookahead=None
        self.events.extend(next_slot.events)
        self.events.append(dict(event='lookahead_promoted',at=now,
                                original_submitted=original_submitted,
                                commit_authoritative=self.pending is not None))
        self.check(runtime.state.last_measured_archive_receipt)

    def acknowledge(self,now):
        self.events.append(dict(event='current_receipt_acknowledged',at=now))
        self.pending=None
        if self.full_plan is not None:self.full_plan.clear()
        self.full_plan=None;self.membership=();self.serial_bytes=0;self.encoded_bytes=0
        self.retained_snapshot=None;self.cycle=None

def select(runtime,slot,exclude=()):
    state=runtime.state
    snapshot=state._storage_stage('archive_plan',lambda:state.writer.archive_snapshot(
        runtime.wall()-180,max_records=slot.reservation,
        max_bytes=fraction(SNAPSHOT_TARGET,slot.reservation),exclude_identities=exclude))
    if snapshot:
        slot.hold(snapshot,runtime.generation,runtime.monotonic())
        state.storage_metrics['archive_snapshot.encoded_peak_bytes']=max(
            state.storage_metrics.get('archive_snapshot.encoded_peak_bytes',0),snapshot['encoded_bytes'])
        state.storage_metrics['archive_snapshot.records_peak']=max(
            state.storage_metrics.get('archive_snapshot.records_peak',0),len(snapshot['rows']))
    return snapshot

def prepare_and_write_archive(path,snapshot,*,max_bytes=16*1024*1024):
    """Native body validation/publication; strict shared allocation before append.

    One native inflater/cache/compressor exists. The parent and child argument
    snapshots are cleared only after completion, never while serialization runs.
    """
    quota=snapshot['_overlap_reservation']
    original=tuple((r['identity'],r['hash']) for r in snapshot['rows'])
    started=time.monotonic();lines=[];commit=[];body_bytes=0;file_bytes=0
    try:
        for row,body_raw in EvidenceWriter._archive_rows(snapshot,max_bytes=max_bytes,raw_bodies=True):
            body_bytes+=len(body_raw.encode())
            if body_bytes>fraction(BODY_CAP,quota):
                raise EvidenceUnavailable('overlap_worker_body_reservation')
            metadata={k:v for k,v in row.items() if k!='body'}
            line='{"body":'+body_raw+','+canonical(metadata)[1:]
            file_bytes+=len(line.encode())+1
            if file_bytes>fraction(FILE_CAP,quota):
                raise EvidenceUnavailable('overlap_worker_serialized_reservation')
            lines.append(line)
            commit.append(dict(identity=row['identity'],hash=row['hash'],
                               body=dict(scope=row['body']['scope'],slot=row['body']['slot'])))
        if tuple((r['identity'],r['hash']) for r in commit)!=original:
            raise EvidenceUnavailable('overlap_worker_partial_input')
        prepared=time.monotonic()
        receipt=EvidenceWriter._write_archive_raw(path,'\n'.join(lines)+'\n') if lines else None
        if receipt:
            receipt['worker_metrics']=dict(prepare_microseconds=int((prepared-started)*1_000_000),
                publish_microseconds=int((time.monotonic()-prepared)*1_000_000),records=len(commit))
            receipt['overlap_resources']=dict(body_bytes=body_bytes,file_bytes=file_bytes,
                input_records=len(original),reservation=quota)
        return commit,receipt
    finally:
        # The executor's retained call arguments contain this very dictionary.
        # Clear the child's copy before return; native Future completion then
        # permits releasing the separate parent's retained argument snapshot.
        snapshot.clear()
