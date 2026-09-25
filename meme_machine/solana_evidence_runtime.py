"""Read-only production consumer and bounded lifecycle-interest IPC.

This module has no historical provider dependency and no writer/proof interface.
"""
import json
import os
from pathlib import Path
import socket
import time
from .solana_evidence_plane import EvidenceReader,EvidenceUnavailable,canonical
from .solana_evidence_queries import PumpEvidenceView,MeteoraEvidenceView

PUMP_SCOPE='program:pump'
SWAP_SCOPE='program:pumpswap'
METEORA_SCOPE='program:meteora'

class RuntimeEvidence:
    def __init__(self,path=None,*,owner,clock=time.time,command=None):
        path=path or os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB')
        if not path:raise EvidenceUnavailable('shared_evidence_plane_required')
        self.path=Path(path).resolve();self.reader=EvidenceReader(self.path)
        self.owner=owner;self.clock=clock;self._command=command
        self.counts={}
    def command(self,**request):
        if self._command:return self._command(request)
        request.setdefault('owner',self.owner)
        data=(canonical(request)+'\n').encode()
        if len(data)>32768:raise EvidenceUnavailable('evidence_interest_command_bound')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as stream:
            stream.settimeout(.25)
            try:
                stream.connect(str(self.path)+'.sock');stream.sendall(data)
                reply=stream.makefile('rb').readline(32769)
            except OSError as exc:raise EvidenceUnavailable('evidence_service_unavailable') from exc
        result=json.loads(reply)
        if result.get('ok') is not True:raise EvidenceUnavailable(result.get('error','evidence_command_rejected'))
        return result
    def count(self,key,count=1):
        self.counts[key]=self.counts.get(key,0)+count
        self.command(op='counter',key=key,count=count)
    def interest(self,scope,*,lower_slot,addresses=(),lifecycle='candidate',priority=3,owner=None):
        return self.command(op='interest',owner=owner or self.owner,scope=scope,
            lower_slot=lower_slot,addresses=list(addresses),lifecycle=lifecycle,priority=priority)
    def frontier(self,scope):
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
    def pump_events(self,scope,address,lower_time,upper_time,*,upper_slot=None):
        try:
            lo,hi=self.bounds(scope,lower_time,upper_time,upper_slot=upper_slot)
            return PumpEvidenceView(self.reader,scope).events(address,lower_slot=lo,upper_slot=hi,
                lower_time=lower_time,upper_time=upper_time,as_of=self.clock())
        except EvidenceUnavailable:
            self.count('pump.gap_blocked_queries');raise
    def meteora_interval(self,pool,start,end):
        try:return MeteoraEvidenceView(self.reader,METEORA_SCOPE).interval(pool,start_slot=start,end_slot=end,as_of=self.clock())
        except EvidenceUnavailable:
            self.count('meteora.gap_blocked_reconstructions');raise
    def telemetry(self):return dict(self.reader.telemetry(),lane_counters=dict(self.counts))
    def close(self):self.reader.close()

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
            self.rows=self.plane.pump_events(SWAP_SCOPE,self.pool,self.graduation_time,at,upper_slot=upper)
            self._history_complete=True
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
        rows=self.plane.reader.db.execute('''SELECT r.body FROM addresses a JOIN records r ON r.identity=a.identity
            WHERE a.address=? AND r.scope=? AND r.kind='event' AND r.first_seen<=? ORDER BY a.slot DESC LIMIT 1000''',
            (mint,PUMP_SCOPE,self.plane.clock()))
        for raw, in rows:
            if raw:
                event=json.loads(raw)['payload'].get('event',{})
                if event.get('event_type')=='create':return event
        return None
    def events_since(self,sequence):
        hi=self.plane.frontier(PUMP_SCOPE)
        rows=self.plane.reader.db.execute('''SELECT rowid,body FROM records WHERE scope=? AND kind='event'
            AND rowid>? AND slot<=? AND first_seen<=? ORDER BY rowid LIMIT 5000''',
            (PUMP_SCOPE,sequence,hi,self.plane.clock())).fetchall()
        events=[]
        for seq,raw in rows:
            if raw is None:raise EvidenceUnavailable('pump_consumer_backlog_archived')
            event=json.loads(raw)['payload']['event']
            if event.get('event_type')!='create':events.append(event)
            sequence=seq
        if rows:self.plane.command(op='ack',owner=self.plane.owner,scope=PUMP_SCOPE,slot=hi)
        return events,sequence
    def covered(self,now=None):
        try:
            hi=self.plane.frontier(PUMP_SCOPE);at=self.plane.block_time(hi)
            lo,_=self.plane.bounds(PUMP_SCOPE,at-60,at,upper_slot=hi)
            return self.plane.reader.covered(PUMP_SCOPE,lo,hi,as_of=self.plane.clock())
        except EvidenceUnavailable:return False
    def status(self,now=None):return self.plane.telemetry()
