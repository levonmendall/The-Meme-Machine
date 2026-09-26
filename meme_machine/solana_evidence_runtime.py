"""Read-only production consumer and bounded lifecycle-interest IPC.

This module has no historical provider dependency and no writer/proof interface.
"""
import json
import os
from pathlib import Path
import socket
import time
import uuid
import sqlite3
from .solana_evidence_plane import EvidenceReader,EvidenceUnavailable,canonical,decode_body
from .solana_evidence_queries import PumpEvidenceView,MeteoraEvidenceView

PUMP_SCOPE='program:pump'
SWAP_SCOPE='program:pumpswap'
METEORA_SCOPE='program:meteora'

class RuntimeEvidence:
    def __init__(self,path=None,*,owner,clock=time.time,command=None):
        path=path or os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB')
        if not path:raise EvidenceUnavailable('shared_evidence_plane_required')
        self.path=Path(path).resolve()
        try:self.reader=EvidenceReader(self.path)
        except sqlite3.Error:self.reader=None
        self.owner=owner;self.clock=clock;self._command=command
        self.counts={}
        self.health_observations={}
    def command(self,**request):
        from .solana_evidence_control import COMMAND_SECONDS,ATTEMPT_SECONDS
        request.setdefault('owner',self.owner)
        request['consumer']=self.owner
        if self._command:return self._command(request)
        request.setdefault('request_id',uuid.uuid4().hex)
        request.setdefault('expires_at',time.time()+COMMAND_SECONDS)
        data=(canonical(request)+'\n').encode()
        if len(data)>32768:raise EvidenceUnavailable('evidence_interest_command_bound')
        end=time.monotonic()+COMMAND_SECONDS
        for attempt in range(6):
            remaining=end-time.monotonic()
            if remaining<=0:break
            try:
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as stream:
                    stream.settimeout(min(ATTEMPT_SECONDS,remaining))
                    stream.connect(str(self.path)+'.sock');stream.sendall(data)
                    with stream.makefile('rb') as source:reply=source.readline(32769)
                if len(reply)>32768:raise ValueError('reply_bound')
                result=json.loads(reply)
                if result.get('state')=='pending' or result.get('error')=='evidence_control_overloaded':
                    self.counts['ipc_retries']=self.counts.get('ipc_retries',0)+1
                    time.sleep(min(.05,max(0,end-time.monotonic())));continue
                if result.get('ok') is not True:raise EvidenceUnavailable(result.get('error','evidence_command_rejected'))
                if result.get('request_id')!=request['request_id']:raise EvidenceUnavailable('evidence_ack_identity')
                return result
            except EvidenceUnavailable:raise
            except (OSError,ValueError):
                self.counts['ipc_retries']=self.counts.get('ipc_retries',0)+1
                time.sleep(min(.05,max(0,end-time.monotonic())))
        self.counts['ipc_unacknowledged']=self.counts.get('ipc_unacknowledged',0)+1
        error=EvidenceUnavailable('evidence_command_unacknowledged')
        error.request=request # retry this exact envelope; never mint a new counter ID
        raise error
    def count(self,key,count=1):
        self.counts[key]=self.counts.get(key,0)+count
        try:self.command(op='counter',key=key,count=count)
        except EvidenceUnavailable:
            # Diagnostic delivery does not own lane liveness or decision authority.
            self.counts['ipc_counter_unacknowledged']=self.counts.get('ipc_counter_unacknowledged',0)+1
    def interest(self,scope,*,lower_slot,addresses=(),lifecycle='candidate',priority=3,owner=None):
        return self.command(op='interest',owner=owner or self.owner,scope=scope,
            lower_slot=lower_slot,addresses=list(addresses),lifecycle=lifecycle,priority=priority)
    def admit_candidate(self,scope,*,addresses,owner):
        """The lane consumes a classified infrastructure result, never a crash."""
        try:
            self.require_usable(scope)
            frontier=self.frontier(scope)
            self.interest(scope,lower_slot=max(0,frontier-1),addresses=addresses,owner=owner)
            return dict(accepted=True)
        except EvidenceUnavailable as exc:
            return dict(accepted=False,terminal_classification='infrastructure_evidence_unavailable',
                        reason=str(exc),economic_rejection=False)
    def frontier(self,scope):
        self.require_usable(scope)
        row=self.reader.db.execute('SELECT MAX(hi) FROM coverage WHERE scope=? AND available<=?',(scope,self.clock())).fetchone()
        if not row or row[0] is None:raise EvidenceUnavailable('evidence_cold_start')
        return row[0]
    def block_time(self,slot):
        rows=self.reader.db.execute('SELECT DISTINCT market_time FROM stream_receipts WHERE slot=? AND seen<=?',(slot,self.clock())).fetchall()
        if len(rows)!=1:raise EvidenceUnavailable('exact_finalized_block_time_unavailable')
        return rows[0][0]
    def bounds(self,scope,lower_time,upper_time,*,upper_slot=None):
        cutoff=self.clock()
        # A real block at/before the lower time is required. Earliest trade is not
        # a boundary witness, and wall time cannot extend finalized coverage.
        lo=self.reader.db.execute('SELECT slot FROM stream_receipts WHERE scope=? AND market_time<=? AND seen<=? ORDER BY market_time DESC,slot ASC LIMIT 1',
            (scope,lower_time,cutoff)).fetchone()
        if upper_slot is None:
            hi=self.reader.db.execute('SELECT slot FROM stream_receipts WHERE scope=? AND market_time>=? AND seen<=? ORDER BY slot LIMIT 1',
                (scope,upper_time,cutoff)).fetchone()
        else:hi=(upper_slot,)
        if not lo or not hi:raise EvidenceUnavailable('evidence_time_boundary_unavailable')
        return lo[0],hi[0]
    def acknowledge(self,scope,slot):
        owner=self.owner+':'+scope
        row=self.reader.db.execute('SELECT slot FROM consumers WHERE owner=?',(owner,)).fetchone()
        if row is None or slot>=row[0]:self.command(op='ack',owner=owner,scope=scope,slot=slot)
    def pump_events(self,scope,address,lower_time,upper_time,*,upper_slot=None):
        try:
            self.require_usable(scope)
            self.count('pump.local_evidence_reads')
            lo,hi=self.bounds(scope,lower_time,upper_time,upper_slot=upper_slot)
            events=PumpEvidenceView(self.reader,scope).events(address,lower_slot=lo,upper_slot=hi,
                lower_time=lower_time,upper_time=upper_time,as_of=self.clock())
            self.acknowledge(scope,hi)
            self.count('pump.complete_local_reads')
            self._repair_assisted('pump',scope,lo,hi)
            return events
        except EvidenceUnavailable:
            self.count('pump.gap_blocked_queries')
            self.count('pump.incomplete_local_reads');raise
    def meteora_scope(self,pool):
        if self.reader is None:self.require_usable(METEORA_SCOPE)
        scoped='pool:meteora:'+pool
        if self.reader.db.execute('SELECT 1 FROM coverage WHERE scope=? LIMIT 1',(scoped,)).fetchone():return scoped
        return METEORA_SCOPE
    def meteora_interval(self,pool,start,end):
        try:
            self.count('meteora.local_evidence_reads')
            scope=self.meteora_scope(pool)
            self.require_usable(METEORA_SCOPE)
            result=MeteoraEvidenceView(self.reader,scope).interval(pool,start_slot=start,end_slot=end,as_of=self.clock())
            self.acknowledge(scope,end)
            self.count('meteora.complete_local_reads')
            self._repair_assisted('meteora',scope,start,end)
            return result
        except EvidenceUnavailable:
            self.count('meteora.gap_blocked_reconstructions')
            self.count('meteora.incomplete_local_reads');raise
    def _repair_assisted(self,lane,scope,lo,hi):
        if self.reader.db.execute("SELECT 1 FROM coverage WHERE scope=? AND lo<=? AND hi>=? AND available<=? AND proof LIKE '%alchemy_finalized_repair%' LIMIT 1",(scope,hi,lo,self.clock())).fetchone():
            self.count(lane+'.repair_assisted_windows')
    def health(self,scope):
        from .solana_evidence_health import evidence_health
        if self.reader is None:
            try:self.reader=EvidenceReader(self.path)
            except sqlite3.Error:return dict(state='FAILED',usable=False,reason='evidence_service_unavailable',scope=scope,observed_at=self.clock())
        health=evidence_health(self.reader,scope,self.clock())
        self.health_observations[scope]=health
        return health
    def require_usable(self,scope):
        health=self.health(scope)
        if not health['usable']:raise EvidenceUnavailable(health['reason'])
        return health
    def telemetry(self):
        return dict(self.reader.telemetry() if self.reader else {},lane_counters=dict(self.counts),admission_health=dict(self.health_observations))
    def close(self):
        if self.reader:self.reader.close()

class LocalPumpHistory:
    """Adapter for the real Pump runner's frozen history/decision interface."""
    def __init__(self,plane,pool,graduation_time):
        self.plane=plane;self.pool=pool;self.graduation_time=int(graduation_time)
        self.snapshot=None;self.rows=[];self._window_complete=False;self._history_complete=False
    def bind_snapshot(self,snapshot):self.snapshot=snapshot
    def refresh(self,rpc,now,*,research=False,hydration_kind=None):
        if self.snapshot is None:raise EvidenceUnavailable('pump_local_snapshot_boundary_required')
        at=int(self.snapshot['market_time']);upper=self.snapshot['slot']
        self._window_complete=self._history_complete=False
        self.rows=self.plane.pump_events(SWAP_SCOPE,self.pool,at-30,at,upper_slot=upper)
        self._window_complete=True
        if research:
            try:
                self.rows=self.plane.pump_events(SWAP_SCOPE,self.pool,self.graduation_time,at,upper_slot=upper)
                self._history_complete=True
            except EvidenceUnavailable:
                # Momentum can use its covered window; the independent second-leg
                # path still requires complete graduation history and fails closed.
                self._history_complete=False
        return list(self.rows)
    def decision_rows(self,now,seconds=30):
        if not self._window_complete:raise EvidenceUnavailable('unresolved_evidence_gap')
        at=int(self.snapshot['market_time'])
        return [r for r in self.rows if at-seconds<=r['market_time']<=at]
    def decision_window_status(self,now,seconds=30):return dict(complete=self._window_complete,source='local_finalized_evidence',historical_provider_calls=0)
    def complete(self,now):return self._history_complete
    def status(self,now):return dict(complete=self._history_complete,decision_window=self.decision_window_status(now),events=len(self.rows),historical_provider_calls=0)

class LocalPumpTape:
    def __init__(self,plane):self.plane=plane
    def window(self,mint,now,max_slot=None):
        rows=self.plane.pump_events(PUMP_SCOPE,mint,int(now)-60,int(now),upper_slot=max_slot)
        return [e for e in rows if e.get('event_type')!='create']
    def creation(self,mint):
        rows=self.plane.reader.db.execute('''SELECT r.body,r.first_seen FROM addresses a JOIN records r ON r.identity=a.identity
            WHERE a.address=? AND r.scope=? AND r.kind='event' AND r.first_seen<=? ORDER BY a.slot DESC LIMIT 1000''',
            (mint,PUMP_SCOPE,self.plane.clock()))
        for raw,seen in rows:
            if raw:
                event=decode_body(raw,self.plane.reader.db)['payload'].get('event',{})
                if event.get('event_type')=='create':return dict(event,available_time=int(seen))
        return None
    def events_since(self,sequence):
        hi=self.plane.frontier(PUMP_SCOPE)
        rows=self.plane.reader.db.execute('''SELECT rowid,body,slot FROM records WHERE scope=? AND kind='event'
            AND rowid>? AND slot<=? AND first_seen<=? ORDER BY rowid LIMIT 5000''',
            (PUMP_SCOPE,sequence,hi,self.plane.clock())).fetchall()
        events=[]
        for seq,raw,slot in rows:
            if raw is None:raise EvidenceUnavailable('pump_consumer_backlog_archived')
            event=decode_body(raw,self.plane.reader.db)['payload']['event']
            if event.get('event_type')!='create':events.append(event)
            sequence=seq
        if rows:self.plane.command(op='ack',owner=self.plane.owner,scope=PUMP_SCOPE,slot=rows[-1][2])
        return events,sequence
    def covered(self,now=None):
        try:
            hi=self.plane.frontier(PUMP_SCOPE)
            row=self.plane.reader.db.execute('SELECT market_time FROM stream_receipts WHERE scope=? AND slot<=? ORDER BY slot DESC LIMIT 1',(PUMP_SCOPE,hi)).fetchone()
            if row is None:return False
            at=row[0]
            lo,_=self.plane.bounds(PUMP_SCOPE,at-60,at,upper_slot=hi)
            return self.plane.reader.covered(PUMP_SCOPE,lo,hi,as_of=self.plane.clock())
        except EvidenceUnavailable:return False
    def status(self,now=None):return self.plane.telemetry()

class LocalInterestRegistry:
    def __init__(self,plane):self.plane=plane
    def add_address(self,address):
        try:lower=max(0,self.plane.frontier(SWAP_SCOPE)-1)
        except EvidenceUnavailable:lower=0
        self.plane.interest(SWAP_SCOPE,lower_slot=lower,addresses=[address],owner='pump:pool:'+address)
        return SWAP_SCOPE
    def remove_address(self,address):
        return self.plane.command(op='release',owner='pump:pool:'+address,scope=SWAP_SCOPE,resolved=False)
    def status(self):return self.plane.telemetry()
