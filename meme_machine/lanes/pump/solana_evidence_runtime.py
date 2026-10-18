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
import threading
from contextlib import contextmanager
from .solana_evidence_plane import EvidenceReader,EvidenceUnavailable,canonical,decode_body
from .solana_evidence_queries import PumpEvidenceView,MeteoraEvidenceView

PUMP_SCOPE='program:pump'
SWAP_SCOPE='program:pumpswap'
METEORA_SCOPE='program:meteora'

class BaseRuntimeEvidence:
    def __init__(self,path=None,*,owner,clock=time.time,command=None,
                 native_resources=None,native_ports=None):
        self.native_resources=None;self.native_endpoint_identity=None
        self._native_commands=None
        if native_resources is not None:
            from meme_machine.runtime.isolated_native_bootstrap import require_runner_ports
            ports=require_runner_ports(native_resources,native_ports)
            expected=native_resources.root/'solana-evidence.sqlite'
            if (path is None or Path(path)!=expected or command is not None
                    or owner not in ('pump','pump:survivor')):
                raise EvidenceUnavailable('isolated_native_evidence_owner')
            for suffix in ('','-wal','-shm','.sock'):
                if Path(str(expected)+suffix).is_symlink():
                    raise EvidenceUnavailable('isolated_native_evidence_symlink')
            self.native_resources=native_resources
            self.native_endpoint_identity=ports.rpc_port('pump',
                'survivor' if owner=='pump:survivor' else 'current').source.endpoint_identity
            self._native_commands=ports._source_command_connector(owner)
        elif native_ports is not None:
            raise EvidenceUnavailable('isolated_native_resources_required')
        path=path or os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB')
        if not path:raise EvidenceUnavailable('shared_evidence_plane_required')
        self.path=Path(path).resolve()
        self._thread_readers=threading.local()
        try:self.reader=EvidenceReader(self.path)
        except sqlite3.Error:self.reader=None
        self.owner=owner;self.clock=clock;self._command=command
        self.counts={}
        self.health_observations={}
    @property
    def reader(self):
        # The facade may be shared with a position worker; SQLite handles may not.
        if not hasattr(self._thread_readers,'reader'):
            try:self._thread_readers.reader=EvidenceReader(self.path)
            except sqlite3.Error:self._thread_readers.reader=None
        return self._thread_readers.reader
    @reader.setter
    def reader(self,value):
        self._thread_readers.reader=value
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
                with (self._native_commands.connect() if self._native_commands is not None
                        else socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)) as stream:
                    stream.settimeout(min(ATTEMPT_SECONDS,remaining))
                    if self._native_commands is None:stream.connect(str(self.path)+'.sock')
                    stream.sendall(data)
                    with stream.makefile('rb') as source:reply=source.readline(32769)
                if len(reply)>32768:raise ValueError('reply_bound')
                result=json.loads(reply)
                if result.get('state')=='pending' or result.get('error')=='evidence_control_overloaded':
                    self.counts['ipc_retries']=self.counts.get('ipc_retries',0)+1
                    _stop_sleep(min(.05,max(0,end-time.monotonic())));continue
                if result.get('ok') is not True:raise EvidenceUnavailable(result.get('error','evidence_command_rejected'))
                if result.get('request_id')!=request['request_id']:raise EvidenceUnavailable('evidence_ack_identity')
                return result
            except EvidenceUnavailable:raise
            except (OSError,ValueError):
                self.counts['ipc_retries']=self.counts.get('ipc_retries',0)+1
                _stop_sleep(min(.05,max(0,end-time.monotonic())))
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
    def advance_interest(self,scope,*,lower_slot,consumed_slot,checkpoint_hash,owner):
        """Call only after the consuming native replay checkpoint is durable."""
        return self.command(op='advance_interest',owner=owner,scope=scope,
            lower_slot=lower_slot,consumed_slot=consumed_slot,checkpoint_hash=checkpoint_hash)
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
            view=PumpEvidenceView(self.reader,scope)
            events=view.events(address,lower_slot=lo,upper_slot=hi,
                lower_time=lower_time,upper_time=upper_time,as_of=self.clock())
            self._thread_readers.pump_ordered_records=view.ordered_records
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
        # Closing a worker must neither open a new handle nor close another owner.
        reader=getattr(self._thread_readers,'reader',None)
        if reader:reader.close()
        self._thread_readers.reader=None

from meme_machine.solana_selective_runtime import SelectiveRuntime

class RuntimeEvidence(SelectiveRuntime,BaseRuntimeEvidence):
    pass

class LocalPumpHistory:
    """Adapter for the real Pump runner's frozen history/decision interface."""
    def __init__(self,plane,pool,graduation_time):
        self.plane=plane;self.pool=pool;self.graduation_time=int(graduation_time)
        self.snapshot=None;self.rows=[];self.candidate_history_rows=[];self._window_complete=False;self._history_complete=False
    def bind_snapshot(self,snapshot):self.snapshot=snapshot
    def refresh(self,rpc,now,*,research=False,hydration_kind=None):
        if self.snapshot is None:raise EvidenceUnavailable('pump_local_snapshot_boundary_required')
        at=int(self.snapshot['market_time']);upper=self.snapshot['slot']
        self._window_complete=self._history_complete=False
        self.rows=self.plane.pump_events(SWAP_SCOPE,self.pool,at-30,at,upper_slot=upper)
        self.candidate_history_rows=list(getattr(self.plane._thread_readers,'pump_ordered_records',[]))
        self._window_complete=True
        if research:
            try:
                self.rows=self.plane.pump_events(SWAP_SCOPE,self.pool,self.graduation_time,at,upper_slot=upper)
                self.candidate_history_rows=list(getattr(self.plane._thread_readers,'pump_ordered_records',[]))
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
    def __init__(self,plane,*,native_work=None):
        self.plane=plane
        self.native_work=native_work
        # Ordered normalized rows from the most recent cursor advance. Strategy
        # callers keep their existing event shape; candidate-history persistence
        # consumes this side channel so promotion has complete pre-grad economics.
        self.candidate_history_rows=[]
    @contextmanager
    def _cached_window_authority(self,mint,lower_time,upper_time,upper_slot):
        """A retained cache cannot overrule current canonical unavailability."""
        from meme_machine.solana_selective_runtime import selective,CONTROL
        from meme_machine.solana_selective_history import CandidateReader,ConsumerReader
        from meme_machine.solana_evidence_plane import EvidenceUnavailable as CanonicalUnavailable
        reader=getattr(self.plane,'reader',None)
        if reader is None:raise EvidenceUnavailable('cached_history_canonical_authority_required')
        original=reader.original if isinstance(reader,ConsumerReader) else reader
        db=original.db
        at=self.plane.clock()
        db.execute('BEGIN')
        try:
            scoped=selective(original)
            scope=CONTROL if scoped else PUMP_SCOPE
            usable=getattr(self.plane,'require_usable',None)
            if callable(usable):usable(PUMP_SCOPE)
            else:
                from meme_machine.solana_evidence_health import evidence_health
                health=evidence_health(original,scope,at)
                if health.get('usable') is not True:
                    raise EvidenceUnavailable(health.get('reason','cached_history_health_unverified'))
            # Use the original block-time boundary and completeness predicates;
            # neither the cache's first trade nor its largest slot is a witness.
            from types import SimpleNamespace
            fixed=SimpleNamespace(reader=reader,clock=lambda:at)
            lo,hi=BaseRuntimeEvidence.bounds(fixed,scope,lower_time,upper_time,
                upper_slot=upper_slot)
            candidate=CandidateReader(original,'pump',mint) if scoped else original
            target=candidate.scope if scoped else PUMP_SCOPE
            if not candidate.covered(target,lo,hi,as_of=at):
                raise EvidenceUnavailable('unresolved_evidence_gap')
            authority=None
            if scoped:
                from meme_machine.solana_provider_config import AlchemyEndpoint
                from meme_machine.solana_rolling_history import program_scope
                if getattr(self.plane,'native_resources',None) is None:
                    endpoint=AlchemyEndpoint.parse(os.environ['MM_SOLANA_READ_RPC_URL']).identity
                else:
                    from meme_machine.runtime.isolated_native_resources import require_resources
                    require_resources(self.plane.native_resources)
                    endpoint=self.plane.native_endpoint_identity
                authority=dict(candidate_scope=target,program_scope=program_scope('pump'),endpoint=endpoint)
                if db.execute("SELECT 1 FROM service_health WHERE key='source_drain_observation'").fetchone():
                    stat=original.path.stat()
                    session=db.execute('SELECT session FROM prewarm_startup WHERE id=1').fetchone()
                    authority['generation']=(session,endpoint,stat.st_dev,stat.st_ino)
            # Keep this canonical snapshot through the cache read. A cache is
            # not an independent way to move past a newly unavailable interval.
            yield authority
        except CanonicalUnavailable as exc:
            raise EvidenceUnavailable(str(exc)) from exc
        finally:db.execute('ROLLBACK')
    def window(self,mint,now,max_slot=None):
        try:rows=self.plane.pump_events(PUMP_SCOPE,mint,int(now)-60,int(now),upper_slot=max_slot)
        except EvidenceUnavailable:
            from contextlib import closing
            from meme_machine.runtime.candidate_history import open_candidate_history
            history=open_candidate_history()
            if history is None:raise
            try:
                with closing(history),self._cached_window_authority(
                        mint,int(now)-60,int(now),max_slot) as authority:
                    rows=history.covered_events('pump',mint,PUMP_SCOPE,int(now)-60,int(now),
                        upper_slot=max_slot,source_authority=authority)
            except ValueError as exc:raise EvidenceUnavailable(str(exc)) from exc
        return [e for e in rows if e.get('event_type') not in ('create','migration')]
    def creation(self,mint):
        # This is observation attention, not a negative evidence verdict. A
        # popular mint can occur many times in one bounded delivery batch. Read
        # its same historical creation once, and forget misses on the very next
        # poll (including an empty poll). Quotes/coverage never use this cache.
        batch=getattr(self,'_creation_batch',None)
        if batch is not None and mint in batch:return batch[mint]
        value=self._creation(mint)
        if batch is not None and len(batch)<256:batch[mint]=value
        return value

    def _creation(self,mint):
        from meme_machine.runtime.stop import requested,Shutdown
        from meme_machine.runtime.sqlite_failure import preserving_cleanup
        def check_stop():
            if requested.is_set():raise Shutdown()
        check_stop()
        db=self.plane.reader.db;db.execute('BEGIN')
        try:
            # The existing canonical create receipt is committed with its
            # economics. Resolve it by identity instead of expanding up to a
            # thousand later trade bodies. This is lineage attention, never
            # an interval-completeness or qualification verdict.
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rolling_origins'").fetchone():
                origin=db.execute("SELECT lower_slot,market_time,receipt FROM rolling_origins WHERE family='pump' AND address=?",(mint,)).fetchone()
                check_stop()
                if origin:
                    row=db.execute('SELECT body,hash,first_seen FROM records WHERE identity=? AND scope=? AND kind=\'event\' AND first_seen<=? LIMIT 1',
                        (origin[2],PUMP_SCOPE,self.plane.clock())).fetchone()
                    check_stop()
                    if row and row[0]:
                        record=decode_body(row[0],db);check_stop()
                        from .solana_evidence_plane import digest
                        event=record.get('payload',{}).get('event',{})
                        if (digest(record)!=row[1] or record.get('identity')!=origin[2]
                                or record.get('scope')!=PUMP_SCOPE or record.get('kind')!='event'
                                or record.get('slot')!=origin[0] or record.get('market_time')!=origin[1]
                                or event.get('event_type')!='create' or event.get('mint')!=mint):
                            raise EvidenceUnavailable('pump_creation_origin_mismatch')
                        return dict(event,available_time=int(row[2]))
            # Materializing the canonical UNION view for a join scanned the
            # entire retained market on every trade. Bind the same address's
            # identities first, then use each canonical branch's primary key.
            # A large identity set keeps the original path, never loses rows.
            identities=[r[0] for r in db.execute('SELECT identity FROM addresses WHERE address=? LIMIT 2049',(mint,))]
            check_stop()
            if len(identities)>2048:
                rows=db.execute('''SELECT r.body,r.first_seen FROM addresses a JOIN records r ON r.identity=a.identity
                    WHERE a.address=? AND r.scope=? AND r.kind='event' AND r.first_seen<=? ORDER BY r.slot DESC LIMIT 1000''',
                    (mint,PUMP_SCOPE,self.plane.clock()))
            elif identities:
                # More than one identity let SQLite favor the whole-program
                # ordering index again. Materialize only bounded point metadata
                # before ordering, then expand the same selected bodies by PK.
                # Keep SELECT outermost so the existing ConsumerReader maps
                # every record reference to its canonical content views.
                rows=db.execute("SELECT (SELECT body FROM records e WHERE e.identity=r.identity LIMIT 1),r.first_seen FROM (WITH matched AS MATERIALIZED (SELECT identity,scope,kind,slot,first_seen FROM records WHERE identity IN ("+
                    ','.join('?' for _ in identities)+")) SELECT identity,first_seen FROM matched WHERE scope=? AND kind='event' AND first_seen<=? ORDER BY slot DESC LIMIT 1000) r",
                    (*identities,PUMP_SCOPE,self.plane.clock()))
            else:rows=[]
            for raw,seen in rows:
                check_stop()
                if raw:
                    event=decode_body(raw,db)['payload'].get('event',{})
                    check_stop()
                    if event.get('event_type')=='create':return dict(event,available_time=int(seen))
            check_stop()
            from contextlib import closing
            from meme_machine.runtime.candidate_history import open_candidate_history
            history=open_candidate_history()
            if history is not None:
                with closing(history):
                    # Both canonical reference and legacy source producers use
                    # this normalized kind. Resolve creation only; buying a
                    # local archived trade history again cannot supply it.
                    for record in history.events('pump',mint,kind='pump_create'):
                        check_stop()
                        event=record['payload']
                        if event.get('event_type')=='create':return dict(event,available_time=int(event.get('available_time',event['market_time'])))
            return None
        finally:
            with preserving_cleanup():db.execute('ROLLBACK')
    def events_since(self,sequence):
        self._creation_batch={}
        self.candidate_history_retained_path=None
        self.candidate_history_retained_count=0
        from meme_machine.solana_selective_runtime import selective,consume_pump_discovery
        if hasattr(self.plane,'_selective_reader') and selective(self.plane._selective_reader()):return consume_pump_discovery(self,sequence)
        hi=self.plane.frontier(PUMP_SCOPE)
        # Keep body and shared material on the same bounded read snapshot while
        # archive GC runs. Release it before any control acknowledgement.
        db=self.plane.reader.db;db.execute('BEGIN')
        try:
            rows=db.execute('''SELECT rowid,body,slot,identity,signature,transaction_index,
                    event_index,market_time,first_seen FROM records WHERE scope=? AND kind='event'
                AND rowid>? AND slot<=? AND first_seen<=? ORDER BY rowid LIMIT 5000''',
                (PUMP_SCOPE,sequence,hi,self.plane.clock())).fetchall()
            from meme_machine.runtime.candidate_history import order_economic_records
            source_records=[decode_body(row[1],db) for row in rows if row[1] is not None]
            if len(source_records)!=len(rows):raise EvidenceUnavailable('pump_consumer_backlog_archived')
            try:ordered=order_economic_records(source_records,db,PUMP_SCOPE)
            except ValueError as exc:raise EvidenceUnavailable(str(exc)) from exc
            economic_orders={row['identity']:order for row,order in ordered}
            events=[];history_rows=[]
            for (seq,raw,slot,identity,signature,transaction_index,event_index,market_time,first_seen),record in zip(rows,source_records,strict=True):
                if raw is None:raise EvidenceUnavailable('pump_consumer_backlog_archived')
                event=dict(record['payload']['event'])
                event['_economic_order']=economic_orders[identity]
                event['available_time']=int(first_seen)
                history_rows.append(dict(
                    identity=identity,signature=signature,slot=int(slot),
                    transaction_index=transaction_index,event_index=int(event_index),
                    market_time=int(market_time),event=event))
                if event.get('event_type') not in ('create','migration'):events.append(event)
                sequence=seq
            self.candidate_history_rows=history_rows
        finally:db.execute('ROLLBACK')
        if rows or hi>=0:
            # Commit normalized history before relinquishing the source pin.
            # A crash between the commit and ack replays idempotently; the
            # reverse order could let retention erase uncommitted economics.
            from contextlib import closing
            from meme_machine.runtime.candidate_history import open_candidate_history
            last_sequence=sequence;complete_slot=hi
            unread=db.execute("SELECT MIN(slot) FROM records WHERE scope=? AND kind='event' AND rowid>? AND slot<=?",
                              (PUMP_SCOPE,last_sequence,hi)).fetchone()[0]
            if unread is not None:complete_slot=int(unread)-1
            history=open_candidate_history()
            if history is not None:
                with closing(history):
                    history.retain_pump_source_history(history_rows)
                    # Do not certify the last slot if the bounded page stopped
                    # within it. Earlier complete slots may be checkpointed.
                    coverage=db.execute('SELECT MIN(lo) FROM coverage WHERE scope=? AND available<=?',
                                        (PUMP_SCOPE,self.plane.clock())).fetchone()[0]
                    if coverage is not None and complete_slot>=coverage:
                        if not self.plane.reader.covered(PUMP_SCOPE,coverage,complete_slot,as_of=self.plane.clock()):
                            raise EvidenceUnavailable('candidate_history_continuity_missing')
                        first=db.execute('SELECT market_time FROM stream_receipts WHERE scope=? AND slot=?',
                                         (PUMP_SCOPE,coverage)).fetchone()
                        last=db.execute('SELECT market_time FROM stream_receipts WHERE scope=? AND slot=?',
                                        (PUMP_SCOPE,complete_slot)).fetchone()
                        if first and last:
                            from meme_machine.runtime.journal import digest
                            witnesses=db.execute('SELECT lo,hi,proof FROM coverage WHERE scope=? AND available<=? ORDER BY lo,hi',
                                                (PUMP_SCOPE,self.plane.clock())).fetchall()
                            history.commit_coverage(PUMP_SCOPE,int(coverage),int(complete_slot),int(first[0]),int(last[0]),
                                                    proof_hash=digest(witnesses))
            if complete_slot>=0:self.plane.command(op='ack',owner=self.plane.owner,scope=PUMP_SCOPE,slot=complete_slot)
        return events,sequence
    def covered(self,now=None):
        from meme_machine.solana_selective_runtime import selective
        if hasattr(self.plane,'_selective_reader') and selective(self.plane._selective_reader()):return self.plane.health(PUMP_SCOPE)['usable']
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


def _stop_sleep(seconds):
    from meme_machine.runtime.stop import sleep
    return sleep(seconds,sleeper=time.sleep)
