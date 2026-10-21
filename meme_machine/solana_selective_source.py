"""Read-only rolling pre-warm driver. No broad Pump/PumpSwap body stream.

Universal account scouts retain identities; first sight installs pre-warm interests.
Archive pagination repairs gaps. Body-free Pump/PumpSwap logs are joined to
independent native signature/index witnesses. Only selected Meteora candidates
receive rich native bodies. A linked finality stream is acquired once for control.
"""
import asyncio
import os
import base64
import hashlib
import json
import logging
import sqlite3
from inspect import getattr_static
import time
import uuid
import grpc
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from .solana_activity_routes import ActivityRoutes,shards
from .solana_candidate_join import CandidateTransactionJoin,candidate_subscription,MAX_PENDING_BYTES
from .solana_stream_log_repair import (
    explicit_truncation,log_input_reason,rebase_log_join,authenticate_supplement,FATAL_REPAIR_REASONS,
)
from .solana_candidate_phases import CandidatePhases,DEVELOPMENT_PHASES,phase as candidate_phase
from .runtime.operation_costs import operation,measured
from .solana_native_evidence import economic_transaction,pubkey,signature
from .solana_evidence_plane import EvidenceUnavailable,IntervalProof,digest,canonical
from .solana_evidence_transport import Subscription
from .solana_selective_history import SelectiveHistory,FAMILIES,PROGRAMS,coverage_scope,economic_records
from .solana_selective_runtime import CONTROL
from .solana_source_intake import candidate_log_message
from .solana_source_drain import AcceptedQueue,StopEither,next_owned,join_owned,settle_owned,receive_until_closed,INTAKE_CLOSED
from .solana_source_drain import CONTROL_RECOVERY_KEY,control_recovery,preserve_control_recovery,complete_control_recovery
from .solana_source_drain import HandlerLedger,HANDLER_RECOVERY_KEY,preserve_handlers,finish_owned
from .solana_source_drain import retained_source_drain,assert_source_drain_boundary,publish_source_drain
from .solana_source_drain import begin_source_observation
from .yellowstone import geyser_pb2 as pb
from .runtime.operating_families import enabled,active_sql,active_scope_sql,operational

HOST='solana-mainnet.streaming.alchemy.com:443'
MAX_FRAME_BYTES=16*1024*1024
# 47 status filters + one scoped Meteora content filter + metadata + finality
# remain within the demonstrated 50-filter limit across request maps.
MAX_LIVE_CANDIDATES=48 # StableShards subtracts the one Meteora content filter.
ARCHIVE_WORKERS=8
SCOUT_COMMIT_BATCH=64
CANDIDATE_COMMIT_BATCH=8
DEVELOPMENT_BATCH=16 # Bounded owner work, not a candidate population limit.
CANDIDATE_COMMIT_BYTES=32*1024*1024
# Acquisition cannot prove funded-position latency before a position exists.
# Enforce this guard at capital admission, never at read-only source startup.
PRODUCTION_BLOCKERS=() # Retained import compatibility; readiness is live and regime-specific.

def require_certified():
    from .operational.admission import require_normal
    return require_normal()
REPLAY_SLOTS=6000
CONTROL_OVERLAP=256
CONTROL_CURRENT_SECONDS=15 # Same market-time bound as normal Pump readiness.
WARM_OVERLAP=32

def native_commit_priority(desired):
    # Unfunded intake shares the existing bounded FIFO with required
    # maintenance. Continuous priority-one intake starved that work even when
    # its slices were short. Held/reserved intake retains priority zero;
    # ordered control and durable publication share that bounded FIFO too.
    if any(row['priority']<=1 for row in desired):return 0
    return 2

def rolling_replay_boundary(state,desired,tip):
    """Fresh prospective program census; retain exact old history obligations.

    Yellowstone's identity replay cannot replay a newly opened WS log feed.
    Rebuilding every program transaction across an outage would serialize the
    current market behind exceptional HTTP hydration. Establish the current
    linked tail instead. Existing candidate/position recovery still supplies
    every required missing interval; no checkpoint or gap is relabeled complete.
    """
    h=install(state);points=[]
    for row in desired:
        scopes=h.rolling.scopes(row['family'],row['scope'])
        value=state.writer.db.execute('SELECT MAX(slot) FROM candidate_checkpoints WHERE scope IN ('+
            ','.join('?' for _ in scopes)+')',scopes).fetchone()[0]
        points.append(value)
    present=[p for p in points if p is not None]
    for row,point in zip(desired,points):
        if point is not None and point<tip:
            h.gap(row['scope'],point+1,tip,'rolling_reconnect_missing_websocket_history')
    # Actual finalized WS observations for BOTH programs replace this
    # scheduling placeholder before any native subscription is opened.
    return tip+1,True,bool(present)

def preserve_subscription_handoff(state,desired,tip,*,rolling_floor=None):
    """Retain the unavailable prefix before an observed rolling WS floor.

    The post-ACK HTTP tip only bounds the old disconnect. Fresh rolling starts
    exclude the partially subscribed slots through the latest first WS delivery;
    those slots need their own gap even when no old disconnect exists. Neither
    boundary proves economics, repairs history or advances a checkpoint.
    """
    h=install(state);scopes=tuple({row['scope'] for row in desired})
    with state.writer.transaction():
        state.writer.db.execute('UPDATE candidate_gaps SET hi=? WHERE hi IS NULL AND lo<=? AND scope IN ('+
            ','.join('?' for _ in scopes)+')',(tip,tip,*scopes))
        if rolling_floor is not None and rolling_floor>tip+1:
            for row in desired:
                if row.get('rolling'):
                    h.gap(row['scope'],tip+1,rolling_floor-1,'rolling_partial_subscription_prefix')

def subscription_disconnect_lower(history,row,floor,session,*,fresh_rolling=False):
    """Preserve a proved current island without advancing its global cursor."""
    checkpoint=history.db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',
        (row['scope'],)).fetchone()
    lower=floor if checkpoint is None else checkpoint[0]+1
    if fresh_rolling and row.get('rolling'):
        child=history.db.execute('SELECT slot,parent,session FROM candidate_blocks WHERE scope=?',
            (row['scope'],)).fetchone()
        # An older unresolved gap can correctly prevent a global checkpoint
        # while this session's linked child already sealed the current prefix.
        # The unsealed child slot is not coverage. Retain the prefix only after
        # the original economic publication and consumer fences actually pass.
        if (child is not None and child[2]==session and floor<=child[1]<child[0]
                and not history.rolling.missing(row['family'],row['scope'],floor,child[1])
                and history.lifecycle.unconsumed(row['scope'],through=child[1]) is None):
            lower=max(lower,child[1]+1)
    return lower

STATE_SCHEMA='''
CREATE TABLE IF NOT EXISTS candidate_blocks(scope TEXT PRIMARY KEY,slot INTEGER NOT NULL,
 parent INTEGER NOT NULL,hash TEXT NOT NULL,previous_hash TEXT NOT NULL,
 market_time INTEGER NOT NULL,seen REAL NOT NULL,session TEXT NOT NULL,census_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidate_live_work(family TEXT NOT NULL,address TEXT NOT NULL,
 priority INTEGER NOT NULL,deadline REAL NOT NULL,created REAL NOT NULL,PRIMARY KEY(family,address));
CREATE TABLE IF NOT EXISTS structural_census(
 label TEXT PRIMARY KEY,cursor TEXT,status TEXT NOT NULL,slot INTEGER,updated REAL NOT NULL);
'''

def install(state):
    if not hasattr(state,'selective'):
        state.selective=SelectiveHistory(state.writer,state.fence.endpoint_identity)
        state.writer.db.executescript(STATE_SCHEMA)
        from .solana_candidate_lifecycle import CandidateLifecycle
        state.selective.lifecycle=CandidateLifecycle(state.selective)
        from .solana_rolling_history import RollingHistory
        state.selective.rolling=RollingHistory(state.selective)
        from .solana_prewarm_startup import PrewarmStartup
        state.selective.startup=PrewarmStartup(state.selective)
        from .solana_history_work import HistoricalTasks,enabled as separated_history
        if separated_history():
            state.selective.historical_tasks=HistoricalTasks(state.selective)
            state.selective.lifecycle.delivery_separated=True
        elif state.writer.db.execute("SELECT 1 FROM sqlite_master WHERE name='rolling_preparation_jobs'").fetchone():
            # Flag rollback preserves newly queued, not-yet-applied obligations.
            state.selective.historical_recovery=HistoricalTasks(state.selective)
        state.fence.selective=state.selective
        state.fence.health('topology','candidate_hybrid_v1')
    return state.selective

def scout_request():
    request=pb.SubscribeRequest(commitment=pb.FINALIZED)
    for label,program,kind in [('p',PROGRAMS['pump'],'BondingCurve'),
                              ('m',PROGRAMS['meteora'],'LbPair'),('n',PROGRAMS['meteora'],'LbPair'),
                              ('a',PROGRAMS['meteora'],'BinArray')]:
        if program==PROGRAMS['meteora'] and not enabled('meteora'):continue
        f=request.accounts[label];f.owner.append(program)
        f.filters.add().memcmp.CopyFrom(pb.SubscribeRequestFilterAccountsFilterMemcmp(
            offset=0,bytes=hashlib.sha256(('account:'+kind).encode()).digest()[:8]))
    from . import pump
    from .postgrad import WSOL
    for label,offset in [('m',88),('n',120)]:
        if not enabled('meteora'):continue
        request.accounts[label].filters.add().memcmp.CopyFrom(pb.SubscribeRequestFilterAccountsFilterMemcmp(offset=offset,bytes=pump.un58(WSOL)))
    # Pump nominations consume only bytes 0..48. The remaining seven bytes
    # belong to Meteora's bin-array locator, whose producers are paused in
    # operational mode. Keep its full slice for historical/offline consumers.
    length=56 if 'a' in request.accounts else 49
    request.accounts_data_slice.add(offset=0,length=length)
    return request

def scout_fact(update,seen):
    """Retain only the fixed locator facts, never a queued native payload.

    Delivered bytes have already been charged by the stream reader. Locators
    cannot establish economic coverage, qualification or execution authority.
    """
    item=update.account;account=item.account
    labels=set(update.filters);raw=account.data;address=pubkey(account.pubkey)
    if labels & {'m','n','a'} and not enabled('meteora'):return
    if len(raw)<49:raise EvidenceUnavailable('candidate_scout_fields_missing')
    sig=signature(account.txn_signature) if account.HasField('txn_signature') else ''
    activity=bool(sig and not item.is_startup)
    if labels=={'p'}:
        if pubkey(account.owner)!=PROGRAMS['pump']:raise EvidenceUnavailable('candidate_scout_owner')
        reserve=int.from_bytes(raw[24:32],'little');supply=int.from_bytes(raw[40:48],'little')
        fields=dict(real_token_reserves=reserve,total_supply=supply,complete=bool(raw[48]),
            # This upper bound can promote too early, never reject an actually
            # qualifying curve. Exact initial reserves are hydrated before entry.
            development_upper_bps=None if not 0<=reserve<=supply or supply==0 else 10000*(supply-reserve)//supply,
            economic_event=False,history_complete=False,activity=activity)
        family='pump'
    elif labels and labels.issubset({'m','n'}):
        if pubkey(account.owner)!=PROGRAMS['meteora']:raise EvidenceUnavailable('candidate_scout_owner')
        if labels=={'m','n'}:return # Existing WSOL policy is XOR, not an OR pair.
        family='meteora';fields=dict(wsol_pair_locator=True,economic_event=False,history_complete=False,activity=activity)
    elif labels=={'a'}:
        if len(raw)!=56 or pubkey(account.owner)!=PROGRAMS['meteora']:raise EvidenceUnavailable('candidate_scout_fields_missing')
        # A bin-array account header is a wakeup only. It cannot replace swaps,
        # exact bins, balances, instructions or economic interval completeness.
        family='meteora';fields=dict(bin_array_locator=address,economic_event=False,history_complete=False,activity=activity)
        address=pubkey(raw[24:56])
    else:raise EvidenceUnavailable('candidate_scout_filter')
    fact=dict(family=family,address=address,slot=item.slot,signature=sig,fields=fields,seen=seen)
    # A fixed account-data slice needs no unbounded protobuf in the writer queue.
    if len(canonical(fact).encode())>2048:raise EvidenceUnavailable('candidate_scout_fact_bound')
    return fact

def commit_scout_fact(state,fact):
    if fact is not None:install(state).observe(**fact)

def commit_scout(state,update,seen):
    commit_scout_fact(state,scout_fact(update,seen))

@measured('owner.scout_commit')
def commit_scout_batch(state,facts):
    if not 0<len(facts)<=SCOUT_COMMIT_BATCH:raise EvidenceUnavailable('candidate_scout_batch_bound')
    history=install(state)
    with state.writer.source_frame():
        history.observe_many(facts)

def block_message(frame):
    b=frame.update.block
    return dict(method='blockNotification',params=dict(result=dict(value=dict(slot=b.slot,err=None,
        block=dict(parentSlot=b.parent_slot,blockhash=b.blockhash,previousBlockhash=b.parent_blockhash,
                   blockTime=b.block_time.timestamp,transactions=[])))))

@measured('owner.control_commit')
def commit_control(state,frame,*,active=True):
    install(state);b=frame.update.block;seen=frame.seen
    prepared=dict(endpoint_identity=state.fence.endpoint_identity,observed_at=seen,
                  slot=b.slot,signatures=[],batches=[],deliveries=[])
    with state.writer.source_frame():
        state.fence.block(Subscription('source',CONTROL,'control','census',2),block_message(frame),seen,prepared=prepared)
        state.writer._count('stream_accepted_messages')
        state.fence._health('phase','ACTIVE' if active else 'DEGRADED')
        # Liveness records this successful publication, not the age of a frame
        # that waited in the durable owner queue. Frame availability and market
        # time below retain their original values and freshness requirements.
        state.fence._health('heartbeat',state.writer.clock())
        # Source coordinates inform bounded storage maintenance, never global
        # economic completeness. Candidate proofs live in a separate namespace.
        for scope in (FAMILIES[f] for f in install(state).active_families):
            state.fence._health('finalized_frontier:'+scope,dict(slot=b.slot,time=b.block_time.timestamp,seen=seen))
        h=install(state)
        startup=state.writer.db.execute('SELECT released FROM prewarm_startup WHERE id=1').fetchone()
        if (startup and not startup[0]) or state.writer.db.execute('SELECT 1 FROM candidate_pending_proofs LIMIT 1').fetchone():
            from .solana_history_notifications import changed
            changed(h)

def skipped_prefix(history,scope,frame):
    """A finalized parent below the replay floor proves skipped slots only."""
    b=frame.update.block;lo=frame.replay_from_slot
    if not (0<lo<b.slot and b.parent_slot<lo):return
    witness=dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=b.slot-1,
        lineage_hash=digest([lo,b.slot,b.parent_slot,b.blockhash,b.parent_blockhash]),
        method='native_finalized_parent_proves_no_block_in_replay_prefix',native_order=True)
    history.lifecycle.defer_proof(IntervalProof(scope,lo,b.slot-1,'alchemy_finalized_stream',history.endpoint_identity,witness,frame.seen))

def commit_candidates(state,frame,addresses,session,*,publish=True,prepared=None,timing=None):
    with candidate_phase(timing,'validate'):
        history=install(state);b=frame.update.block;seen=frame.seen
        if prepared is not None:
            from .solana_economic_preparation import PreparedCandidateFrame,coordinates
            if (not isinstance(prepared,PreparedCandidateFrame) or prepared.coordinates!=
                    coordinates(frame,addresses,session,history.endpoint_identity)):
                raise EvidenceUnavailable('candidate_preparation_source_changed')
            rows=prepared.rows;censuses=prepared.censuses
        else:
            bodies={signature(tx.signature):economic_transaction(tx,slot=b.slot,
                block_time=b.block_time.timestamp,rich=True) for tx in b.transactions}
            bodies.update({tx['transaction']['signatures'][0]:tx for tx in frame.log_transactions})
            rows={};censuses={scope:[] for scope in addresses.values()}
        reverse={scope:address for address,scope in addresses.items()}
        for scope in addresses.values():
            old=state.writer.db.execute('SELECT slot,hash,session FROM candidate_blocks WHERE scope=?',(scope,)).fetchone()
            if old and old[2]==session and b.slot>old[0] and (old[0]!=b.parent_slot or old[1]!=b.parent_blockhash):
                # A discontinuity receipt must survive the aborted source frame.
                history.gap(scope,old[0],b.slot-1,'candidate_native_parent_gap')
                raise EvidenceUnavailable('candidate_native_parent_gap')
    with state.writer.source_frame():
        if prepared is None:
            with candidate_phase(timing,'validate'):
                for sig,index,scopes,error,available in frame.candidate_statuses:
                    for scope in scopes:
                        address=reverse[scope];family=scope.split(':',2)[1]
                        censuses[scope].append([sig,index,error])
                        if error is not None:continue # failed attempts have no committed economic events
                        tx=bodies.get(sig)
                        if tx is None:raise EvidenceUnavailable('candidate_required_content_missing')
                        for row in economic_records(family,address,tx,endpoint_identity=history.endpoint_identity,
                                                     seen=available,source='alchemy_finalized_stream'):
                            previous=rows.get(row.identity)
                            if previous and previous.body()!=row.body():raise EvidenceUnavailable('candidate_economic_content_conflict')
                            rows[row.identity]=row
        material=rows if prepared is not None else rows.values()
        if timing is None:history.ingest(material)
        else:history.ingest(material,timing=timing)
        with candidate_phase(timing,'coverage_receipt'):
            for scope,census in censuses.items():
                old=state.writer.db.execute('SELECT slot,parent,hash,previous_hash,market_time,seen,session,census_hash FROM candidate_blocks WHERE scope=?',(scope,)).fetchone()
                census_hash=digest(census) if prepared is None else prepared.census_hashes[scope]
                values=(b.slot,b.parent_slot,b.blockhash,b.parent_blockhash,b.block_time.timestamp,seen,session,census_hash)
                if old and b.slot<=old[0]:
                    if b.slot==old[0] and (old[1:5],old[7])!=(values[1:5],values[7]):raise EvidenceUnavailable('candidate_replay_receipt_conflict')
                    if old[6]==session:continue
                    # The current session's actual replay receipt may precede the
                    # previous session's last block. Its own next linked child is
                    # required before this interval can be republished. Canonical
                    # event availability and historical checkpoints stay unchanged.
                # The first receipt of a restarted session can independently
                # prove skipped replay-prefix slots. A prior session's receipt
                # must not suppress that finalized-parent witness.
                if old is None or old[6]!=session:skipped_prefix(history,scope,frame)
                if old and old[6]==session:
                    witness=dict(finalized=True,complete=True,scope=scope,lower_slot=old[0],upper_slot=b.slot-1,
                        lineage_hash=digest([scope,list(old),list(values)]),
                        method='candidate_filtered_native_status_and_verified_content_with_linked_child',
                        native_order=True,transaction_bodies_only_for_meteora=True)
                    history.lifecycle.defer_proof(IntervalProof(scope,old[0],b.slot-1,'alchemy_finalized_stream',history.endpoint_identity,witness,seen))
                state.writer.db.execute('INSERT OR REPLACE INTO candidate_blocks VALUES(?,?,?,?,?,?,?,?,?)',(scope,*values))
    if publish:history.lifecycle.publish()


def commit_candidate_batch(state,frames,addresses,session,*,grouped=False,publish=True,prepared=None,timing=None):
    """The original ordered frames, under one atomic durable owner command."""
    if not 0<len(frames)<=CANDIDATE_COMMIT_BATCH:
        raise EvidenceUnavailable('candidate_commit_batch_bound')
    history=install(state)
    if prepared is not None and (grouped or len(prepared)!=len(frames)):
        raise EvidenceUnavailable('candidate_preparation_batch_shape')
    try:
        transaction=state.writer.transaction()
        with (transaction if timing is None else timing.transaction_exit(transaction)):
            for index,frame in enumerate(frames):
                if grouped:commit_rolling_group(state,frame,addresses,session,publish=False)
                else:commit_candidates(state,frame,addresses,session,publish=False,
                    prepared=None if prepared is None else prepared[index],timing=timing)
    except Exception:
        # A discontinuity inside the enclosing batch rolls back with it.
        # Retain its unavailable interval outside that rollback, before retry.
        for scope in addresses.values():
            history.gap(scope,min(f.update.block.slot for f in frames),
                max(f.update.block.slot for f in frames),'candidate_native_batch_failed')
        raise
    if publish:history.lifecycle.publish()


async def wait_candidate_log_space(join,progress,stop,local_stop,slot,sig,logs):
    """Backpressure speculative WS occupancy inside the existing hard bound.

    Future WS packets must not consume the entire join while an authenticated
    HTTP field is growing beyond its truncated prefix. The half-waterline
    reduces speculative occupancy; decoded log sizes differ from HTTP bytes,
    so it is not a guaranteed response reservation. A missing log named by an
    actual native status can use the original full byte/count bound. Every wake
    rechecks that identity so native delivery can release a waiting WS packet.
    """
    if slot<join.filtered_from_slot or slot<=join.completed or (slot,sig) in join.early_logs:return
    size=len(str(logs).encode())
    if size>MAX_PENDING_BYTES:raise EvidenceUnavailable('candidate_log_buffer_pressure')
    started=join.clock()
    while True:
        # A native/HTTP callback may have consumed this slot or installed the
        # same key while this WS packet waited. Its original late/duplicate
        # validator must run next without reserving these bytes twice.
        if slot<join.filtered_from_slot or slot<=join.completed or (slot,sig) in join.early_logs:return
        if len(join.early_logs)<32768 and join.early_log_bytes+size<=MAX_PENDING_BYTES//2:return
        pending=join.pending.get(slot)
        required=bool(pending is not None and sig in pending['missing_logs']
            and any(pending['signature_text'].get(index)==sig for index in pending['log_required']))
        # Intake has already accepted this packet. Closing the session must
        # not turn its speculative soft-waterline wait into an interrupted
        # handler when the original hard bound can still retain it. The
        # normal join validation/ordered commit and partial-session recovery
        # persistence still run before the handler or session may finish.
        closing=stop.is_set() or local_stop.is_set()
        closing_admission=closing and join.clock()-started<join.max_join_seconds
        byte_bound=MAX_PENDING_BYTES if required or closing_admission else MAX_PENDING_BYTES//2
        if len(join.early_logs)<32768 and join.early_log_bytes+size<=byte_bound:return
        if closing:raise asyncio.CancelledError()
        if join.clock()-started>=join.max_join_seconds:
            raise EvidenceUnavailable('candidate_log_buffer_pressure')
        progress.clear()
        try:await asyncio.wait_for(progress.wait(),.05)
        except TimeoutError:pass


class CandidateCommitQueue:
    """FIFO verified frames; count and bytes include the owner-held batch."""
    def __init__(self,changed=None):
        self.queue=asyncio.Queue(maxsize=CANDIDATE_COMMIT_BATCH)
        self.count=0;self.bytes=0;self.space=asyncio.Event()
        self.admission=asyncio.Lock();self.changed=changed

    async def put(self,frame):
        # Native bodies are already included in source_bytes. Body-free WS
        # log content must also remain inside the physical retained-data bound.
        size=frame.source_bytes+sum(len(canonical(tx).encode()) for tx in frame.log_transactions)
        if not 0<size<=CANDIDATE_COMMIT_BYTES:
            raise EvidenceUnavailable('candidate_commit_batch_bound')
        # Native, WS and HTTP-repair callbacks share one ordered join. Its
        # frames must enter this queue in that same order, including while
        # waiting for the owner-held batch's count/byte reservation. Event
        # wakeup alone lets a resumed producer enqueue its next frame before
        # an older blocked producer; the native parent check then fails.
        # asyncio.Lock admission is FIFO. Waiting/cancellation changes no
        # reservation; the existing durable completion alone releases it.
        async with self.admission:
            while self.count>=CANDIDATE_COMMIT_BATCH or self.bytes+size>CANDIDATE_COMMIT_BYTES:
                self.space.clear();await self.space.wait()
            self.count+=1;self.bytes+=size
            self.queue.put_nowait((frame,size,time.monotonic(),time.time()))
            if self.changed:self.changed(1,0)

    async def batch(self,producer_done=None):
        first=await self.queue.get() if producer_done is None else await next_owned(self.queue,producer_done)
        if first is None:return []
        rows=[first]
        while len(rows)<CANDIDATE_COMMIT_BATCH:
            try:rows.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:break
        return rows

    def done(self,rows):
        for _,size,_,_ in rows:
            self.count-=1;self.bytes-=size;self.queue.task_done()
        if self.changed:self.changed(0,len(rows))
        self.space.set()

    async def join(self):await self.queue.join()

def commit_rolling_group(state,frame,addresses,session,*,publish=True):
    """One proved membership interval, shared by all quiet Meteora views.

    This is the same native per-address status/content join as candidate work.
    Empty pool intervals share a receipt, rather than writing one copy of the
    identical finalized header for every quiet candidate on every block.
    """
    history=install(state);b=frame.update.block;seen=frame.seen
    scope=coverage_scope('meteora','group-'+digest(sorted(addresses.items())))
    old=history.db.execute('SELECT slot,parent,hash,previous_hash,market_time,seen,session,census_hash FROM candidate_blocks WHERE scope=?',(scope,)).fetchone()
    if old and old[6]==session and b.slot>old[0] and (old[0]!=b.parent_slot or old[2]!=b.parent_blockhash):
        history.gap(scope,old[0],b.slot-1,'candidate_native_parent_gap')
        raise EvidenceUnavailable('candidate_native_parent_gap')
    bodies={signature(tx.signature):economic_transaction(tx,slot=b.slot,
        block_time=b.block_time.timestamp,rich=True) for tx in b.transactions}
    reverse={s:a for a,s in addresses.items()};rows={}
    census=[]
    with state.writer.source_frame():
        for sig,index,scopes,error,available in frame.candidate_statuses:
            census.append([sig,index,list(scopes),error])
            if error is not None:continue
            if not scopes or not set(scopes).issubset(reverse) or sig not in bodies:
                raise EvidenceUnavailable('candidate_required_content_missing')
            # One immutable economic packet even when several pools consume it.
            address=reverse[scopes[0]]
            for row in economic_records('meteora',address,bodies[sig],endpoint_identity=history.endpoint_identity,
                    seen=available,source='alchemy_finalized_stream'):rows[row.identity]=row
        history.ingest(rows.values())
        if old is None:
            # The immutable group identity includes the full address/scope set.
            # Membership does not need 47 repeated inserts on every quiet block.
            for address in addresses:
                history.db.execute('INSERT OR IGNORE INTO rolling_group_members VALUES(?,?,?,?)',
                    (scope,'meteora',address,frame.replay_from_slot or b.slot))
        values=(b.slot,b.parent_slot,b.blockhash,b.parent_blockhash,b.block_time.timestamp,seen,session,digest(census))
        if old and b.slot<=old[0]:
            if b.slot==old[0] and (old[1:5],old[7])!=(values[1:5],values[7]):raise EvidenceUnavailable('candidate_replay_receipt_conflict')
            if b.slot==old[0] and old[6]!=session:history.db.execute('UPDATE candidate_blocks SET session=? WHERE scope=?',(session,scope))
        else:
            if old is None:skipped_prefix(history,scope,frame)
            if old and old[6]==session:
                witness=dict(finalized=True,complete=True,scope=scope,lower_slot=old[0],upper_slot=b.slot-1,
                    lineage_hash=digest([scope,list(old),list(values)]),method='scoped_native_membership_census_with_linked_child',
                    addresses=sorted(addresses),native_order=True)
                history.lifecycle.defer_proof(IntervalProof(scope,old[0],b.slot-1,'alchemy_finalized_stream',history.endpoint_identity,witness,seen))
            history.db.execute('INSERT OR REPLACE INTO candidate_blocks VALUES(?,?,?,?,?,?,?,?,?)',(scope,*values))
    if publish:history.lifecycle.publish()

def plan_live(state):
    history=install(state);now=time.time();db=state.writer.db
    history.lifecycle.refresh()
    desired=[]
    for scope,address,priority,lower,updated,position in db.execute('''SELECT i.scope,s.address,MIN(i.priority),
        MIN(i.lower_slot),MIN(i.updated),MAX(i.lifecycle IN ('open','reserved')) FROM service_interests s JOIN interests i
        ON i.owner=s.owner AND i.scope=s.scope WHERE i.active=1 AND '''+active_scope_sql('i.scope')+''' GROUP BY i.scope,s.address'''):
        family=next((f for f,b in FAMILIES.items() if b==scope),None)
        if family not in history.active_families:continue
        role=1 if position else (0 if priority==0 else (2 if priority<=2 else 3))
        # Stable interest identity: a polling clock cannot reconnect every feed.
        deadline=updated+3600 if role<=2 else updated+120
        desired.append((role,deadline,updated,family,address,lower))
        history.bind(family,address)
        db.execute('INSERT OR IGNORE INTO candidate_live_work VALUES(?,?,?,?,?)',(family,address,role,deadline,updated))
    # Provider promotions carry their original deadline across process/filter
    # restarts; a polling clock must never manufacture a fresh decision window.
    for family,address,deadline,lo,created in db.execute('''SELECT family,address,deadline,lower_slot,first_seen
            FROM candidate_lifecycle WHERE '''+active_sql('family',solana=True)+''' AND state IN ('queued','warming','active')'''):
        existing=next((i for i,r in enumerate(desired) if r[3:5]==(family,address)),None)
        if existing is None:
            desired.append((4,deadline,created,family,address,lo))
        else:
            p,d,age,f,a,lower=desired[existing]
            desired[existing]=(p,min(d,deadline),min(age,created),f,a,min(lower,lo))
    # Meteora's exact mechanics need instructions, transfer bindings and native
    # order. Accumulate the minimum native economic packet from first sight,
    # independently of promotion/capital. Quiet scopes do not fetch accounts.
    selected={(r[3],r[4]) for r in desired}
    for address,lo,created in db.execute("""SELECT c.address,c.first_slot,c.first_seen FROM candidate_lifecycle c
        JOIN market_observations m ON m.family=c.family AND m.address=c.address
        WHERE """+active_sql('c.family',solana=True)+""" AND c.family='meteora' AND json_extract(m.fields,'$.wsol_pair_locator')=1"""):
        if ('meteora',address) not in selected:
            history.bind('meteora',address)
            desired.append((5,created+3600,created,'meteora',address,lo))
    desired.sort()
    if len(desired)>MAX_LIVE_CANDIDATES:
        with state.writer.transaction():history._observation(None,'capacity_pressure',dict(live_requested=len(desired),live_capacity=MAX_LIVE_CANDIDATES,economic_rejection=False))
    # The provider's filter-map limit is a shard size, never rejection authority.
    # Every requested scope remains serviced; rich acquisition is separately EDF.
    from .operational.position_continuation import position_only
    chosen=[row for row in desired if row[0]<=2] if position_only() else desired
    return [dict(family=f,address=a,scope=history.scope_for(f,a),priority=p,deadline=d,lower_slot=lo)
            for p,d,_,f,a,lo in chosen]

def source_work(work,stop,observe=None):
    """Rejected admission retains the same frame and applies backpressure."""
    async def resumable(fn,priority=1,**options):
        started=time.monotonic();retries=0
        while True:
            try:
                result=await work(fn,priority,**options)
                if retries and observe:observe('owner_backpressure',retries=retries,seconds=time.monotonic()-started,priority=priority)
                return result
            except EvidenceUnavailable as exc:
                if str(exc) not in ('evidence_background_yield','evidence_control_overloaded'):raise
                # Overload rejects before admission; a background yield rolls
                # back its transaction. Neither case permits dropping a frame
                # or changing its original work/deadline.
                retries+=1
                await asyncio.sleep(min(.2,.01*2**min(retries-1,5)))
    return resumable


class SelectiveSource:
    def __init__(self,config,rpc,*,token=None):
        self.config=config;self.rpc=rpc;self.token=token or config.credential
        self.work=None;self.stop=None
        self.observer=None
        self.batched=False;self.pending_delivery={};self.delivery_lock=asyncio.Lock();self.control_connected=False
        self.native_streams={};self.native_attempts={};self.native_errors={}
        self.native_peak=0;self.native_revision=0;self.native_published=-1
        self.pending_diagnostics=[]
        self.join_observed={}
        self.join_state={};self.diagnostic_generation=None
        self.pipeline_metrics={}
        self.candidate_phases=CandidatePhases(self.pipeline_metrics)
        self.development_phases=CandidatePhases(self.pipeline_metrics,
            phases=DEVELOPMENT_PHASES,prefix='development_phase:')
        self.rolling_publications=0
        self.control_bootstrap_tip=None;self.control_committed_slot=None
        self.control_committed_market_time=None
        self.acquisition_plan_lock=asyncio.Lock();self.acquisition_idle_until=0
        self.preparation_lock=asyncio.Lock()
        from .solana_history_notifications import WorkPulse
        self.history_wakeup=WorkPulse();self.delivery_wakeup=WorkPulse()
        self.delivery_urgent=WorkPulse();self.delivery_revision=0
        self.source_drain=dict(state='RUNNING',terminal=False,source_pid=os.getpid(),run_identity=uuid.uuid4().hex,
            started_at_monotonic=time.monotonic(),terminal_at_monotonic=None,accepted_handlers=0,
            settled_handlers=0,closed_sessions=0,preserved_partial_sessions=0,
            unpreserved_sessions=0,queues={name:dict(accepted=0,committed=0)
                for name in ('control','scout','rolling','candidate')})
        self.handlers=HandlerLedger(self.source_drain['run_identity'])
        self.contained_observation=False;self.observation_drain_boundary=None
        self.session_teardowns={};self.session_deadlines={};self.optional_stops=set()

    def shutdown_deadline(self,coordinator=None):
        deadline=getattr(self,'drain_deadline',None)
        if deadline is None and self.stop is not None and self.stop.is_set():
            # Same existing service source-drain boundary; never renew it.
            deadline=asyncio.get_running_loop().time()+30
            self.drain_deadline=deadline
        local=self.session_deadlines.get(coordinator)
        return min(x for x in (deadline,local,asyncio.get_running_loop().time()+30) if x is not None)

    async def close_optional_session(self,task,local_stop):
        local_stop.set()
        self.session_deadlines.setdefault(task,self.shutdown_deadline())
        self.optional_stops.add(task);task.add_done_callback(self.optional_stops.discard)
        # Cancel the coordinator, not its accepted-frame consumers. Its finally
        # owns one shielded teardown. A child ignoring the event is still woken.
        if not task.done() and task not in self.session_teardowns and not task.cancelling():task.cancel()
        async def result():return await asyncio.gather(asyncio.shield(task),return_exceptions=True)
        waiter=asyncio.create_task(result())
        try:return await finish_owned(waiter,self.session_deadlines[task])
        except TimeoutError:
            self.source_drain.update(state='RECOVERY_REQUIRED',terminal_record_unavailable=True)
            task.cancel() # Existing deadline exhausted; original service escalation still applies.
            raise
        finally:
            if task.done() and task not in self.session_teardowns:self.session_deadlines.pop(task,None)

    def frame_census(self,plane,accepted,committed):
        row=self.source_drain['queues'][plane]
        row['accepted']+=accepted;row['committed']+=committed

    def drain_snapshot(self):
        body=dict(self.source_drain)
        handlers=self.handlers.snapshot()
        if not handlers['valid']:
            body.update(state='RECOVERY_REQUIRED',terminal_record_unavailable=True)
            if self.stop is not None:self.stop.set()
        body.update(accepted_handlers=handlers['accepted'],settled_handlers=handlers['returned'],
            handler_accounting=handlers)
        body['queues']={name:dict(row,pending=row['accepted']-row['committed'])
            for name,row in body['queues'].items()}
        body['pending_handlers']=body['accepted_handlers']-body['settled_handlers']
        body['all_accepted_committed']=all(row['pending']==0 for row in body['queues'].values())
        body['scope']='JOINED_FRAME_COMMITS_AND_RECEIVED_HANDLERS_PARTIAL_JOINS_REMAIN_EXPLICIT_GAPS'
        return body

    async def handle_native(self,handler,update,size,seen,stream,family):
        kind=update.WhichOneof('update_oneof');item=getattr(update,kind) if kind else None
        slot=getattr(item,'slot',None)
        identity=None
        if kind=='transaction_status':identity=signature(item.signature)
        elif kind=='account':identity=pubkey(item.account.pubkey)
        number=self.handlers.accept(stream,getattr(handler,'source_session',stream),'yellowstone',
            family,kind or 'unknown',seen,slot=slot,identity=identity,scopes=getattr(handler,'source_scopes',()))
        try:await handler(update,size,seen)
        except BaseException as exc:
            self.handlers.fail(number,exc);raise
        else:self.handlers.finish(number)

    def history_changed(self,*,publication=True,delivery=True,urgent_delivery=True):
        if publication:self.history_wakeup.notify()
        if delivery:
            self.delivery_revision=getattr(self,'delivery_revision',0)+1
            self.delivery_wakeup.notify()
        if delivery and urgent_delivery:self.delivery_urgent.notify()

    def retain_join_state(self,plane,session,body,queue,*,state,monotonic):
        # Reuse the existing join sample; no second pending-state walk, timer,
        # DB observation or retained join/queue object. Candidate streams share
        # one last-sampled slot, explicitly not a population aggregate.
        if plane not in ('rolling','candidate'):return
        previous=self.join_state.get(plane)
        if state=='CLOSED' and previous is not None and previous['session']!=session:return
        try:generation=self.diagnostic_generation() if callable(self.diagnostic_generation) else None
        except Exception:generation=None
        fields=('filtered_from_slot','completed','pending_slots','pending_bytes',
            'early_log_count','early_log_bytes','early_log_min_slot','early_log_max_slot',
            'oldest_slot','oldest_age','oldest_meta','oldest_finality','oldest_statuses',
            'oldest_bodies','oldest_missing_logs','replay_prefix_bytes')
        self.join_state[plane]=dict(plane=plane,session=session,source_pid=os.getpid(),
            source_generation=generation,sampled_at=time.time(),sampled_at_monotonic=monotonic,
            state=state,join={key:body.get(key) for key in fields},
            commit_queue=dict(count=None if queue is None else queue.count,
                              bytes=None if queue is None else queue.bytes),
            scope='LAST_SAMPLED_SESSION_NOT_POPULATION_OWNER_HELD_BATCH_INCLUDED')

    def observe_join(self,plane,join,session,queue=None):
        now=time.monotonic()
        if now-self.join_observed.get(plane,-5)>=5:
            self.join_observed[plane]=now
            body=dict(plane=plane,session=session,**join.diagnostic())
            self.retain_join_state(plane,session,body,queue,state='ACTIVE',monotonic=now)
            self.diagnostic('native_join_state',body)

    def diagnostic(self,kind,body):
        # Reuse canonical acquisition observations, without bodies, new files
        # or a second writer. Journal spill preserves diagnostics when the
        # owner is delayed; forensic work cannot block native protection.
        if len(self.pending_diagnostics)>=64:
            logging.getLogger(__name__).warning('source_diagnostic %s %s',kind,canonical(body))
            return
        self.pending_diagnostics.append((kind,body))

    def commit_diagnostics(self,state,rows):
        h=install(state)
        for kind,body in rows:h._observation(None,kind,body)

    async def flush_diagnostics(self):
        rows=list(self.pending_diagnostics)
        if rows:
            await self.work(lambda s:self.commit_diagnostics(s,rows),2)
            del self.pending_diagnostics[:len(rows)]

    def observe(self,kind,**values):
        # Numeric, process-local attribution only. Reuse the existing health
        # publication; never add an evidence receipt or per-event SQL write.
        if kind=='log_repair':
            # duplicate_deliveries counts packets coalesced while a repair is
            # pending; late known partial duplicates are ignored by the join.
            # Logical RPC invocations are distinct from transport attempts,
            # whose original measured_rpc/provider accounting includes retries.
            metric=self.pipeline_metrics.setdefault('log_repair:rolling',dict(calls=0,
                deferred=0,duplicate_deliveries=0,repair_logical_calls=0,
                supplements_authenticated=0,supplements_failed=0,pending_peak=0,
                repair_physical_requests=0,repair_retry_calls=0,batch_requests=0,batch_members=0))
            metric['calls']+=1
            stage=values.get('stage')
            if stage in ('deferred','duplicate_deliveries','repair_logical_calls',
                    'supplements_authenticated','supplements_failed','repair_physical_requests',
                    'repair_retry_calls','batch_requests','batch_members'):
                metric[stage]+=values.get('count',1)
            count=values.get('pending')
            if type(count) is int:metric['pending_peak']=max(metric['pending_peak'],count)
        if kind in ('joined_frame','economic_prepared','evidence_timing','publication_timing','history_delivery_timing','decode_timing'):
            plane=values.get('plane','shared')
            if plane not in ('shared','rolling','candidate'):plane='shared'
            key=kind+':'+plane
            metric=self.pipeline_metrics.setdefault(key,dict(calls=0))
            metric['calls']+=1
            slot=values.get('slot')
            if type(slot) is int:metric['latest_slot']=max(metric.get('latest_slot',0),slot)
            def interval(start,finish):
                a,b=values.get(start),values.get(finish)
                return b-a if type(a) in (int,float) and type(b) in (int,float) else None
            durations={}
            if kind=='decode_timing':durations={'decode':values.get('seconds'),'decode_cpu':values.get('cpu_seconds')}
            elif kind=='economic_prepared':durations={k:values.get(k) for k in ('cpu_seconds','wall_seconds','transfer_and_wait_seconds')}
            elif kind=='history_delivery_timing':durations={k:values.get(k) for k in ('wall_seconds','cpu_seconds')}
            elif kind=='publication_timing':
                durations={'owner_queue':interval('work_ready_monotonic','owner_claim_monotonic'),
                    'execution':interval('publication_started_monotonic','publication_finished_monotonic')}
            elif kind=='evidence_timing':
                durations={'owner_queue':interval('join_ready_monotonic','owner_claim_monotonic'),
                    'execution':interval('owner_claim_monotonic','durable_finished_monotonic')}
            if durations and all(d is None for d in durations.values()):
                metric['unmeasured_calls']=metric.get('unmeasured_calls',0)+1
            for name,duration in durations.items():
                if duration is None:continue
                micros=int(max(0,duration)*1_000_000)
                metric[name+'_total_microseconds']=metric.get(name+'_total_microseconds',0)+micros
                metric[name+'_peak_microseconds']=max(metric.get(name+'_peak_microseconds',0),micros)
            if kind=='economic_prepared':metric['records']=metric.get('records',0)+values.get('records',0)
            if kind=='evidence_timing' and 'durable_finished_wall' in values:metric['latest_durable_wall']=values['durable_finished_wall']
            if kind=='joined_frame':metric['latest_joined_wall']=values['joined_wall']
        identity=values.get('stream_id');family=values.get('family','shared')
        if kind=='subscribe':
            from google.protobuf.json_format import MessageToDict
            request=(MessageToDict(values['request'],preserving_proto_field_name=True)
                if values.get('request') is not None else None)
            self.native_streams[identity]=dict(consumer=family,delivering=False,
                request=request,messages={},samples=[])
            self.diagnostic('native_subscribe',dict(stream_id=identity,family=family,request=request))
            self.native_attempts[family]=self.native_attempts.get(family,0)+1
            self.native_peak=max(self.native_peak,len(self.native_streams));self.native_revision+=1
        elif kind=='delivery' and identity in self.native_streams and not self.native_streams[identity]['delivering']:
            self.native_streams[identity]['delivering']=True;self.native_revision+=1
        elif kind=='native_error':
            key=family+':'+values['status'];self.native_errors[key]=self.native_errors.get(key,0)+1
            self.native_revision+=1
            context=self.native_streams.get(identity,{})
            body=dict(**values,request=context.get('request'),messages=context.get('messages'),samples=context.get('samples'))
            self.diagnostic('native_error',body)
            # The existing service journal survives even if the canonical
            # owner itself fails before the pending observations can commit.
            logging.getLogger(__name__).warning('native_error %s',canonical(body))
        elif kind=='native_frame':
            context=self.native_streams[identity];message=values['message']
            context['messages'][message]=context['messages'].get(message,0)+1
            if len(context['samples'])<16:context['samples'].append(values)
            # Actual parsed native progress, distinct from joined/prepared and
            # durable slots. Fixed families/types bound the diagnostic keys.
            family=family if family in ('shared','pump','pumpswap','discovery','replay','candidate','rolling') else 'shared'
            message=message if message in ('slot','block_meta','transaction_status','transaction','account','ping','pong') else 'unknown'
            metric=self.pipeline_metrics.setdefault('native_frame:'+family+':'+message,dict(calls=0,bytes=0))
            metric['calls']+=1
            if type(values.get('bytes')) is int:metric['bytes']+=values['bytes']
            else:metric['unmeasured_bytes_frames']=metric.get('unmeasured_bytes_frames',0)+1
            if type(values.get('seen')) in (int,float):metric['latest_received_wall']=values['seen']
            if type(values.get('slot')) is int:metric['latest_slot']=max(metric.get('latest_slot',0),values['slot'])
            if 'provider_created_at' in values:metric['latest_provider_created_wall']=values['provider_created_at']
            return # Existing transport observers already receive the raw delivery.
        elif kind=='unsubscribe':
            context=self.native_streams.get(identity,{})
            self.diagnostic('native_stream_closed',dict(stream_id=identity,family=family,
                messages=context.get('messages'),samples=context.get('samples')))
            self.native_streams.pop(identity,None);self.native_revision+=1
        if self.observer is not None:self.observer(kind,values)

    def stream_telemetry(self):
        from .runtime.provider_purchases import ledger
        # A client-open stream is not independently certified provider admission.
        # First physical delivery is distinguished from subscription attempts.
        families=set(self.native_attempts)|{r['consumer'] for r in self.native_streams.values()}
        return dict(client_open_streams=len(self.native_streams),peak_client_streams=self.native_peak,
            delivering_streams=sum(r['delivering'] for r in self.native_streams.values()),
            by_consumer={f:dict(attempts=self.native_attempts.get(f,0),
                client_open=sum(r['consumer']==f for r in self.native_streams.values()),
                delivering=sum(r['consumer']==f and r['delivering'] for r in self.native_streams.values()))
                for f in sorted(families)},errors=dict(self.native_errors),
            provider_quota_verified=False,provider_purchases=ledger(self).snapshot())

    async def delivered(self,family,transport,size,seen,priority=2):
        from .runtime.provider_purchases import ledger,provider_work
        # Program feeds are shared by independent strategies. Do not assign
        # their purchase twice or infer an unseen redelivery from byte totals.
        kind='solana_websocket' if transport=='websocket' else 'solana_grpc'
        with provider_work('pump_discovery' if family=='discovery' else 'history_receipt',
                family='pump' if family in ('pump','pumpswap','discovery','replay') else 'shared',consumer='shared'):
            ledger(self).stream(kind,size,family='shared')
        if not self.batched:
            await self.work(lambda s:install(s).delivery(family,transport,raw_bytes=size,seen=seen),priority)
            return
        key=(int(seen)//86400,family,transport)
        total,first=self.pending_delivery.get(key,(0,seen))
        self.pending_delivery[key]=(total+size,first)

    async def flush_delivery(self,after=None):
        async with self.delivery_lock:
            pending=dict(self.pending_delivery)
            if not pending and after is None:return
            committed=False;accepted_future=None
            def accepted(future):
                nonlocal accepted_future
                accepted_future=future
            def commit(state):
                nonlocal committed
                if pending and not committed:
                    h=install(state)
                    with state.writer.transaction():
                        for (_,family,transport),(size,seen) in pending.items():
                            h.delivery(family,transport,raw_bytes=size,seen=seen)
                    # A publication yield may retry this callback in a new
                    # fair owner turn. Its accounting COMMIT must not repeat.
                    committed=True
                if after is not None:return after(state)
            # Publication awaits these exact delivery receipts. Giving this
            # small commit a different class stalls the entire publisher.
            # Use intake/publication's bounded FIFO; actual protective work
            # retains its reserved higher priority and SQL preemption.
            try:
                return await self.work(commit,2,label='source_commit',
                    component='delivery_accounting' if after is None else 'history_publication',accepted=accepted)
            except asyncio.CancelledError:
                if accepted_future is not None:
                    # Accepted owner work outlives its waiter. Keep the delta
                    # lock until that exact callback finishes; do not shield a
                    # new admission or allow another flush to charge it twice.
                    waiter=asyncio.wrap_future(accepted_future)
                    while not waiter.done():
                        try:await asyncio.shield(waiter)
                        except asyncio.CancelledError:pass
                        except Exception:break
                    try:waiter.result()
                    except EvidenceUnavailable as exc:
                        # source_work would retry these outcomes. Cancellation
                        # stops that retry, including its pre-admission wait.
                        if str(exc) not in ('evidence_background_yield','evidence_control_overloaded'):raise
                raise
            finally:
                if committed:
                    for key,(size,seen) in pending.items():
                        remaining=self.pending_delivery[key][0]-size
                        if remaining:self.pending_delivery[key]=(remaining,self.pending_delivery[key][1])
                        else:del self.pending_delivery[key]

    async def publish_history(self):
        seen=-1;retry_at=None
        try:
            while not self.stop.is_set():
                seen=await self.history_wakeup.wait(seen,self.stop,
                    delay=None if retry_at is None else max(0,retry_at-time.monotonic()))
                if self.stop.is_set():break
                ready=time.monotonic();timing={}
                def publish(s):
                    timing['owner_claim_monotonic']=time.monotonic()
                    h=install(s);timing['publication_started_monotonic']=time.monotonic()
                    h.lifecycle.publish()
                    timing['publication_finished_monotonic']=time.monotonic()
                    timing['publication_finished_wall']=time.time()
                    startup=h.startup.advance()
                    return (bool(getattr(h.lifecycle,'_proof_publication_cursor',None)),startup,
                        getattr(h.lifecycle,'_consumer_retry_at',None),getattr(h.lifecycle,'_published_count',0))
                more,startup,retry_at,published=await self.flush_delivery(publish)
                self.observe('publication_timing',work_ready_monotonic=ready,
                    work_returned_monotonic=time.monotonic(),**timing)
                if more:self.history_wakeup.notify() # Drain one fixed durable horizon, then sleep.
                if published:self.history_changed(publication=False) # Revalidate context changed by actual publication.
        finally:
            await self.flush_delivery()

    async def source_reporting(self):
        """Accounting and diagnostics keep their independent original cadence.

        This timer never invokes historical publication. Idle reporting issues
        no owner command; a diagnostic cannot wake its own publication loop.
        """
        while not self.stop.is_set():
            await self.flush_delivery()
            await self.flush_diagnostics()
            revision=self.native_revision
            if revision!=self.native_published:
                native=self.stream_telemetry()
                await self.work(lambda s:s.fence._health('native_streams',native),2,label='source_commit')
                self.native_published=revision
            try:await asyncio.wait_for(self.stop.wait(),.1)
            except TimeoutError:pass

    async def control_commits(self,queue,producer_done=None):
        while producer_done is not None or not self.stop.is_set():
            first=await queue.get() if producer_done is None else await next_owned(queue,producer_done)
            if first is None:return
            batch=[first]
            # The same eight-frame durable batch bound as the shared service.
            await asyncio.sleep(.01)
            while len(batch)<8:
                try:batch.append(queue.get_nowait())
                except asyncio.QueueEmpty:break
            def commit(state):
                with state.writer.transaction():
                    for frame in batch:commit_control(state,frame,active=self.control_connected)
                    remaining=complete_control_recovery(state,CONTROL)
                self.source_drain['control_pending_replay']=remaining
                # Scheduling may follow only the durable authenticated receipt;
                # a socket, raw slot notification or submitted command is not it.
                return state.writer.db.execute('''SELECT slot,market_time FROM stream_receipts
                    WHERE scope=? AND sealed=1 ORDER BY slot DESC LIMIT 1''',(CONTROL,)).fetchone()
            receipt=await self.work(commit,2,label='source_commit',component='control')
            if receipt is not None:
                self.control_committed_slot,self.control_committed_market_time=receipt
            if isinstance(queue,AcceptedQueue):queue.committed(batch)
            else:
                for _ in batch:queue.task_done()

    async def candidate_commits(self,queue,addresses,session,*,rolling=False,grouped=False,priority=2,producer_done=None):
        native_announced=False
        while producer_done is not None or not self.stop.is_set() or queue.count:
            rows=await queue.batch(producer_done)
            if not rows:return
            frames=[r[0] for r in rows]
            prepared=None;preparation={}
            if getattr(self,'history_separated',False) and not grouped:
                from .solana_economic_preparation import prepare_candidate_frames
                # One bounded preparation batch, entirely BEFORE enqueueing any
                # owner callback. Neither execution mode waits on the owner.
                async with self.preparation_lock:
                    started=time.monotonic()
                    try:
                        from .solana_evidence_service import STREAM_PROCESS_DECODE_MIN_BYTES
                        if priority==0 or sum(r[1] for r in rows)>=STREAM_PROCESS_DECODE_MIN_BYTES:
                            prepared,preparation=await asyncio.wrap_future(self.preparation_executor.submit(
                                prepare_candidate_frames,frames,addresses,session,self.config.identity))
                            preparation['mode']='existing_process_pool'
                        else:
                            # Reuse the already validated source-decode boundary.
                            # Small packets cost more to transfer than prepare.
                            # They still finish BEFORE owner admission, yielding
                            # between frames. Large/protective packets use the
                            # existing pool; no historian or delivery job is added.
                            products=[];totals=dict(cpu_seconds=0,wall_seconds=0,prepared_bytes=0,records=0,mode='off_owner_inline')
                            for frame in frames:
                                product,timing=prepare_candidate_frames((frame,),addresses,session,self.config.identity)
                                products.extend(product)
                                for key in ('cpu_seconds','wall_seconds','prepared_bytes','records'):totals[key]+=timing[key]
                                if totals['prepared_bytes']>CANDIDATE_COMMIT_BYTES:
                                    raise EvidenceUnavailable('candidate_preparation_result_bound')
                                await asyncio.sleep(0)
                            prepared=tuple(products);preparation=totals
                    except asyncio.CancelledError:raise
                    except Exception as error:
                        def failed(state):
                            h=install(state)
                            for scope in addresses.values():h.gap(scope,min(f.update.block.slot for f in frames),
                                max(f.update.block.slot for f in frames),'candidate_economic_preparation_failed')
                            from .runtime.evidence_worker import failure_diagnostic
                            h._observation(None,'candidate_economic_preparation_failed',dict(
                                error=failure_diagnostic(error),checkpoint_advanced=False))
                        await self.work(failed,priority,label='source_commit')
                        raise
                    preparation['transfer_and_wait_seconds']=time.monotonic()-started
            self.observe('economic_prepared',plane='rolling' if rolling else 'candidate',
                slot=max(f.update.block.slot for f in frames),**preparation)
            claimed=[];finished_wall=[]
            def durable(state):
                claimed.append(time.monotonic())
                commit_candidate_batch(state,frames,addresses,session,
                    grouped=grouped,publish=not self.batched,prepared=prepared,timing=self.candidate_phases)
                if rolling and not native_announced:
                    install(state).startup.native([s.split(':',2)[1] for s in addresses.values()])
                claimed.append(time.monotonic());finished_wall.append(time.time())
            await self.work(durable,priority,label='source_commit',component='candidate')
            for frame,_,ready,ready_wall in rows:
                self.observe('evidence_timing',plane='rolling' if rolling else 'candidate',session=session,slot=frame.update.block.slot,
                    native_last_receipt_wall=frame.seen,
                    economic_available_wall=max((r[4] for r in frame.candidate_statuses),default=frame.seen),
                    join_ready_wall=ready_wall,durable_finished_wall=finished_wall[-1],
                    join_ready_monotonic=ready,owner_claim_monotonic=claimed[-2],
                    durable_finished_monotonic=claimed[-1],work_returned_monotonic=time.monotonic(),
                    published_inline=not self.batched,durable_batch_frames=len(frames),preparation=preparation)
            if rolling:
                native_announced=True;self.rolling_publications+=len(frames)
            queue.done(rows)

    async def control_stream(self,channel,tip,queue):
        retry=0
        while not self.stop.is_set():
            if retry:
                # Reconnect after an ordinary outage uses a current provider
                # replay boundary, not the process's original startup tip.
                tip=await self.measured_rpc('getSlot',[dict(commitment='finalized')],'shared',2)
            point=await self.work(lambda s:s.writer.db.execute('''SELECT MAX(hi),
                (SELECT value FROM service_health WHERE key='source_control_recovery')
                FROM coverage WHERE scope=?''',(CONTROL,)).fetchone(),2)
            checkpoint=point[0];required=control_recovery(point[1] if len(point)>1 else None)
            self.source_drain['control_pending_replay']=required
            # A stale checkpoint cannot request replay outside the supported
            # 6,000-slot window. The retained outage remains an explicit gap;
            # current linked receipts never assert that missing history exists.
            stale=checkpoint is not None and tip-checkpoint>REPLAY_SLOTS
            # An outage outside the supported replay window cannot be repaired
            # by replaying its last 6,000 slots. Retain its historical gap and
            # authenticate the current linked control tail. Exact candidate and
            # position history obligations remain separately unavailable.
            floor=max(1,(tip if checkpoint is None or stale else checkpoint)-CONTROL_OVERLAP)
            if required is not None:
                if tip-required['lower_slot']>REPLAY_SLOTS:
                    raise EvidenceUnavailable('control_required_replay_outside_configured_window')
                floor=min(floor,max(1,required['lower_slot']-CONTROL_OVERLAP))
            if stale:self.diagnostic('control_current_tail',dict(checkpoint=checkpoint,
                tip=tip,from_slot=floor,historical_gap_repaired=False))
            req=pb.SubscribeRequest(commitment=pb.FINALIZED,from_slot=floor)
            req.blocks_meta['b'].SetInParent();req.slots['f'].filter_by_commitment=True
            join=CandidateTransactionJoin({},set(),filtered_from_slot=floor)
            handler_session=uuid.uuid4().hex
            async def control(update,size,seen):
                self.control_connected=True
                self.handlers.phase('CONTROL_JOIN')
                frame=join.feed(update,size,seen)
                self.observe_join('control',join,str(floor))
                if frame:
                    self.handlers.phase('CONTROL_QUEUE')
                    await queue.put(frame)
            control.source_session=handler_session
            control.source_scopes=(CONTROL,)
            try:
                await self.stream(channel,req,control,'shared');return
            except EvidenceUnavailable as exc:
                if str(exc) not in ('candidate_native_eof','candidate_native_unavailable','candidate_native_internal','candidate_native_deadline_exceeded','candidate_native_cancelled','candidate_native_resource_exhausted'):raise
                self.control_connected=False
                self.diagnostic('control_join_failure',dict(reason=str(exc),**join.diagnostic()))
                retry+=1
                def disconnected(state):
                    h=install(state)
                    state.fence._health('phase','DEGRADED')
                    h._observation(None,'control_reconnect',dict(reason=str(exc),attempt=retry,checkpoint=checkpoint))
                await self.work(disconnected,0)
                worker=getattr(self,'control_commit_task',None)
                if worker is None:await queue.join() # Standalone bounded adapter/tests.
                else:await join_owned(queue,worker)
                await asyncio.sleep(min(8,.5*2**min(retry-1,4)))
            finally:
                import sys
                primary=sys.exc_info()[1];body=join.diagnostic();interrupted=self.handlers.pending(handler_session)
                def preserve(state):
                    # Retain the original overlap and exact unfinished native
                    # floor. The existing linked-receipt/reconnect machinery
                    # owns gap validation; a partial next header is not itself
                    # proof that a produced block or a history interval is lost.
                    pending=self.source_drain['queues']['control']
                    with state.writer.transaction():
                        lows=[body['oldest_slot']] if body['oldest_slot'] is not None else []
                        lows.extend(r['slot'] for r in interrupted if type(r.get('slot')) is int and r['slot']>0)
                        if pending['accepted']>pending['committed']:
                            lows.append(floor if self.control_committed_slot is None else self.control_committed_slot+1)
                        if lows:
                            upper=max([*join.pending,join.completed,*lows])
                            self.source_drain['control_pending_replay']=preserve_control_recovery(state,min(lows),upper)
                        required=self.source_drain.get('control_pending_replay')
                        retained=preserve_handlers(state,self.handlers,interrupted,
                            dict(kind='CONTROL_REPLAY',**required) if required else None)
                        install(state)._observation(None,'control_session_drain',dict(**body,
                            replay_from_slot=floor,unfinished_replay_floor=body['oldest_slot'],
                            complete_history_claim=False))
                        return retained
                try:
                    retained=await self.work(preserve,0,label='source_commit')
                    self.handlers.preserved(retained)
                    if body['pending_slots']:self.source_drain['preserved_partial_sessions']+=1
                except BaseException:
                    self.source_drain['unpreserved_sessions']+=1
                    if primary is None:raise
                finally:self.source_drain['closed_sessions']+=1
    async def measured_rpc(self,method,params,family,priority=4):
        from .runtime.operating_families import require_active
        require_active(family)
        def repair_receipt(receipt,attempt):
            if family=='rolling_recovery_missing_logs':
                self.observe('log_repair',stage='repair_physical_requests',
                    count=receipt.get('calls',int(receipt.get('cu',0)>0)))
                if attempt:self.observe('log_repair',stage='repair_retry_calls')
        for attempt in range(3):
            from .operational.position_continuation import position_only
            if priority>2 and position_only():raise EvidenceUnavailable('bootstrap_optional_work_closed')
            from .runtime.provider_purchases import provider_work
            operation='recovery_restart' if family in ('replay','rolling_recovery_missing_logs') else 'history_receipt'
            try:
                with provider_work(operation,family='pump' if family in ('pump','pumpswap','replay','rolling_recovery_missing_logs') else 'shared',
                        consumer='recovery' if operation=='recovery_restart' else 'history',retry_attempt=attempt):
                    result,receipt=await asyncio.to_thread(self.rpc.call_delivered,method,params,priority)
            except ValueError as exc:
                receipt=getattr(exc,'receipt',None)
                if receipt is not None:
                    repair_receipt(receipt,attempt)
                    await self.work(lambda s:install(s).delivery(family,'rpc',raw_bytes=receipt['bytes'],
                        rpc_cu=receipt['cu'],calls=receipt.get('calls',1)),priority)
                from .runtime.evidence_worker import failure_diagnostic
                self.diagnostic('rpc_failure',dict(method=method,family=family,
                    attempt=attempt+1,deadline_reset=False,diagnostic=failure_diagnostic(exc)))
                if not getattr(exc,'retryable',False) or attempt==2:raise
                await self.work(lambda s:install(s)._observation(None,'rpc_retry',dict(method=method,
                    family=family,attempt=attempt+1,deadline_reset=False,cause_kind=getattr(exc,'cause_kind',None))),priority)
                await asyncio.sleep(.2*(attempt+1));continue
            repair_receipt(receipt,attempt)
            await self.work(lambda s:install(s).delivery(family,'rpc',raw_bytes=receipt['bytes'],
                rpc_cu=receipt['cu'],calls=receipt.get('calls',1)),priority)
            return result
    async def measured_log_batch(self,signatures,priority=2):
        """Retry only unavailable batch members, retaining successful inputs.

        One bounded logical population uses the ordinary managed governor,
        physical pacer and durable accounting. No successful member is fetched
        again when another response in its envelope is retryable.
        """
        if len(signatures)==1:
            return [await self.measured_rpc('getTransaction',[signatures[0],dict(commitment='finalized',
                encoding='json',maxSupportedTransactionVersion=1)],'rolling_recovery_missing_logs',priority)]
        from .runtime.evidence_worker import DeliveredRPCError,failure_diagnostic
        from .runtime.provider_purchases import provider_work
        from .runtime.operating_families import require_active
        family='rolling_recovery_missing_logs';require_active(family)
        pending=list(enumerate(signatures));result=[None]*len(pending)
        for attempt in range(3):
            with provider_work('recovery_restart',family='pump',consumer='recovery',retry_attempt=attempt):
                values,receipt=await asyncio.to_thread(self.rpc.log_batch_delivered,
                    [sig for _,sig in pending],priority)
            await self.work(lambda s:install(s).delivery(family,'rpc',raw_bytes=receipt['bytes'],
                rpc_cu=receipt['cu'],calls=receipt.get('calls',0)),priority)
            self.observe('log_repair',stage='repair_physical_requests',count=receipt.get('calls',0))
            if receipt.get('batch_members',0):
                self.observe('log_repair',stage='batch_requests',count=receipt.get('calls',0))
                self.observe('log_repair',stage='batch_members',count=receipt['batch_members'])
            if attempt:self.observe('log_repair',stage='repair_retry_calls',count=len(pending))
            retry=[];fatal=None
            for (index,sig),value in zip(pending,values):
                if isinstance(value,DeliveredRPCError):
                    self.diagnostic('rpc_failure',dict(method='getTransaction',family=family,
                        attempt=attempt+1,deadline_reset=False,diagnostic=failure_diagnostic(value)))
                    if not value.retryable or attempt==2:fatal=fatal or value
                    else:retry.append((index,sig))
                else:result[index]=value
            if fatal is not None:raise fatal
            if not retry:return result
            await self.work(lambda s:install(s)._observation(None,'rpc_retry',dict(method='getTransaction',
                family=family,attempt=attempt+1,deadline_reset=False,members=len(retry))),priority)
            await asyncio.sleep(.2*(attempt+1));pending=retry

    async def stream(self,channel,request,handler,family,local_stop=None,*,optional=False):
        from .runtime.operating_families import require_active
        require_active(family)
        stream_id=uuid.uuid4().hex
        self.observe('subscribe',stream_id=stream_id,family=family,request=request)
        call=channel.stream_stream('/geyser.Geyser/Subscribe',request_serializer=lambda r:r.SerializeToString(),
            response_deserializer=lambda r:r)(metadata=(('x-token',self.token),))
        pending=None;phase='subscription_write'
        closed=asyncio.create_task(StopEither(self.stop,*([local_stop] if local_stop is not None else [])).wait())
        async def send(request):
            writing=asyncio.create_task(call.write(request))
            try:
                done,_=await asyncio.wait((writing,closed),return_when=asyncio.FIRST_COMPLETED)
                if writing in done:writing.result();return True
                return False
            finally:
                if not writing.done():writing.cancel()
                await asyncio.gather(writing,return_exceptions=True)
        try:
            # Subscription establishment can fail with the same native status
            # as a subsequent read. It must enter identical scoped retry/gap
            # handling rather than escape as an unclassified transport error.
            if not await send(request):return
            phase='stream_read'
            while True:
                closing=self.stop.is_set() or (local_stop and local_stop.is_set())
                # A read which completed just as the stop waiter won is already
                # client-owned. Settle its handler before canceling the next
                # outstanding network read; never drop that last delivery.
                if closing and not (pending is not None and pending.done()):break
                if optional:
                    from .operational.position_continuation import position_only
                    if position_only() and not (pending is not None and pending.done()):return
                ready=False
                if pending is None:
                    # Only an explicitly implemented adapter fast path. Native
                    # calls and dynamic proxy/mock attributes retain read().
                    read_ready=getattr_static(call,'read_ready',None)
                    if callable(read_ready):ready,raw=call.read_ready()
                if not ready:
                    if pending is None:pending=asyncio.create_task(call.read())
                    done,_=await asyncio.wait((pending,closed),timeout=1,return_when=asyncio.FIRST_COMPLETED)
                    if pending not in done:
                        if closed in done:break
                        continue
                    raw=pending.result()
                    pending=None
                if raw is grpc.aio.EOF:raise EvidenceUnavailable('candidate_native_eof')
                if len(raw)>MAX_FRAME_BYTES:raise EvidenceUnavailable('candidate_native_frame_bound')
                at=time.time();received=time.monotonic()
                self.observe('delivery',stream_id=stream_id,family=family,transport='yellowstone',raw=raw,seen=at,received_monotonic=received)
                # Delivery counts before parsing, routing, filtering or dedup.
                await self.delivered(family,'yellowstone',len(raw),at)
                decode_started=time.monotonic()
                update=pb.SubscribeUpdate.FromString(raw);kind=update.WhichOneof('update_oneof')
                item=getattr(update,kind) if kind else None
                sample=dict(stream_id=stream_id,family=family,message=kind or 'unknown',
                    bytes=len(raw),filters=list(update.filters),seen=at)
                if update.HasField('created_at'):
                    sample['provider_created_at']=update.created_at.seconds+update.created_at.nanos/1e9
                for key in ('slot','parent','parent_slot','status','index','executed_transaction_count','bank_id'):
                    if item is not None and hasattr(item,key):sample[key]=getattr(item,key)
                self.observe('native_frame',**sample)
                self.observe('decode_timing',stream_id=stream_id,family=family,transport='yellowstone',bytes=len(raw),seconds=time.monotonic()-decode_started)
                if kind=='ping':
                    if not await send(pb.SubscribeRequest(ping=pb.SubscribeRequestPing(id=1))):break
                    continue
                if kind=='pong':continue
                await self.handle_native(handler,update,len(raw),at,stream_id,family)
        except grpc.aio.AioRpcError as exc:
            # Preserve the provider's reason separately from HTTP errors. This
            # observation grants no coverage, does not advance a checkpoint and
            # does not enqueue forensic work on the canonical owner.
            from .solana_provider_config import SECRET_PATTERN
            details=exc.details() or ''
            for secret in (self.token,self.config.credential):
                if isinstance(secret,str) and secret:details=details.replace(secret,'[redacted]')
            details=SECRET_PATTERN.sub('[redacted]',details)
            self.observe('native_error',stream_id=stream_id,family=family,phase=phase,
                status=exc.code().name,details=details[:2048])
            raise EvidenceUnavailable('candidate_native_'+exc.code().name.lower()) from None
        finally:
            if pending:pending.cancel();await asyncio.gather(pending,return_exceptions=True)
            closed.cancel();await asyncio.gather(closed,return_exceptions=True)
            call.cancel()
            self.observe('unsubscribe',stream_id=stream_id,family=family)

    async def scout_stream(self,channel,tip,handler):
        """Retry locators within the provider's actual bounded replay window.

        Account locators grant neither economic coverage nor entry authority.
        Retrying never advances a canonical or CandidateHistory checkpoint.
        """
        retry=0
        floor=max(1,tip-CONTROL_OVERLAP)
        while not self.stop.is_set():
            from .operational.position_continuation import position_only
            if position_only():await asyncio.sleep(.5);continue
            if retry:
                current=await self.measured_rpc('getSlot',[dict(commitment='finalized')],'shared',2)
                if current-floor>REPLAY_SLOTS:
                    next_floor=max(1,current-REPLAY_SLOTS)
                    def gap(state):
                        install(state)._observation(None,'scout_replay_gap',dict(
                            lower_slot=floor,upper_slot=next_floor-1,
                            reason='outside_provider_replay_window',economic_coverage_claim=False,
                            checkpoint_advanced=False,canonical_candidate_proofs_still_required=True))
                    await self.work(gap,1)
                    floor=next_floor
            request=scout_request();request.from_slot=floor
            try:
                await self.stream(channel,request,handler,'pump' if not enabled('meteora') else 'discovery',optional=True)
                if not position_only():return
            except EvidenceUnavailable as exc:
                if str(exc) not in ('candidate_native_eof','candidate_native_unavailable','candidate_native_internal','candidate_native_deadline_exceeded','candidate_native_cancelled','candidate_native_resource_exhausted'):raise
                retry+=1
                def record(state):
                    h=install(state)
                    h._observation(None,'scout_reconnect',dict(reason=str(exc),attempt=retry,
                        from_slot=request.from_slot,economic_coverage_claim=False,checkpoint_advanced=False))
                await self.work(record,1)
                await asyncio.sleep(min(8,.5*2**min(retry-1,4)))

    async def scout_commits(self,queue,producer_done=None):
        """One ordered writer admission for an available burst; no batch timer.

        At most 64 small facts wait here (128 KiB serialized). Backpressure
        retains the current fact; control/protective commands keep priority.
        A failed atomic commit publishes no portion of the batch.
        """
        while producer_done is not None or not self.stop.is_set():
            first=await queue.get() if producer_done is None else await next_owned(queue,producer_done)
            if first is None:return
            batch=[first]
            while len(batch)<SCOUT_COMMIT_BATCH:
                try:batch.append(queue.get_nowait())
                except asyncio.QueueEmpty:break
            await self.work(lambda s:commit_scout_batch(s,batch),5,label='source_commit',component='scout')
            if isinstance(queue,AcceptedQueue):queue.committed(batch)
            else:
                for _ in batch:queue.task_done()

    async def __call__(self,work,stop):
        return await self.run(work,stop)

    async def run(self,work,stop):
        """The production read-only driver; also used by bounded certification.

        This method neither starts a PAPER lifecycle nor grants entry authority.
        """
        work=source_work(work,stop,self.observe)
        self.work=work;self.stop=stop;self.batched=True
        loop=asyncio.get_running_loop()
        def boot(state):
            # Refuse unidentified old callbacks before history/startup writes or
            # any provider dispatch. A new run's empty ledger cannot erase them.
            try:self.retained_source_drain=retained_source_drain(state)
            except EvidenceUnavailable as exc:
                if (str(exc)!='source_drain_historical_handlers_unlocated'
                        or os.environ.get('MM_MODE')!='PAPER'
                        or os.environ.get('MM_OPERATIONAL_PHASE')!='OBSERVATION'):
                    raise
                self.retained_source_drain=retained_source_drain(state,contained_observation=True)
                self.contained_observation=True
                self.source_drain.update(historical_unknown_handlers=2,
                    historical_source_drain_sha256=hashlib.sha256(self.retained_source_drain.encode()).hexdigest(),
                    historical_recovery_verified=False)
            from .operational.position_continuation import position_only
            retained=state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(HANDLER_RECOVERY_KEY,)).fetchone()
            self.retained_handler_recovery=None if retained is None else retained[0]
            if retained:
                if len(retained[0].encode())>self.handlers.maximum_bytes:raise EvidenceUnavailable('source_handler_record_bound')
                value=json.loads(retained[0])
                if value.get('version')!=1 or not isinstance(value.get('records'),list):
                    raise EvidenceUnavailable('source_handler_recovery_corrupt')
                self.source_drain['inherited_handler_recovery']=dict(records=len(value['records']),
                    sha256=hashlib.sha256(retained[0].encode()).hexdigest(),
                    status='RETAINED_NOT_REACQUIRED_BY_STARTUP',key=HANDLER_RECOVERY_KEY)
            if self.contained_observation:
                self.observation_drain_boundary=begin_source_observation(state,self.retained_source_drain,
                    self.drain_snapshot(),handler_boundary=self.retained_handler_recovery)
            h=install(state)
            from .solana_history_notifications import install as notifications
            notifications(h,loop,self.history_changed)
            if not position_only():h.startup.begin()
            return str(state.writer.path)
        self.canonical_path=await work(boot,0)
        from .solana_history_work import enabled as separated_history
        self.history_separated=separated_history()
        if separated_history() and not callable(getattr(getattr(self,'historical_executor',None),'submit',None)):
            raise EvidenceUnavailable('historical_executor_required')
        if separated_history() and not callable(getattr(getattr(self,'delivery_executor',None),'submit',None)):
            raise EvidenceUnavailable('candidate_delivery_executor_required')
        if separated_history() and not callable(getattr(getattr(self,'preparation_executor',None),'submit',None)):
            raise EvidenceUnavailable('candidate_preparation_executor_required')
        tip=await self.measured_rpc('getSlot',[dict(commitment='finalized')],'shared',2)
        self.control_bootstrap_tip=tip
        async with grpc.aio.secure_channel(HOST,grpc.ssl_channel_credentials(),options=[
                ('grpc.max_receive_message_length',MAX_FRAME_BYTES),('grpc.max_send_message_length',4*1024*1024),('grpc.http2.bdp_probe',0)]) as channel:
            control_queue=AcceptedQueue(64,lambda a,c:self.frame_census('control',a,c))
            scout_queue=AcceptedQueue(SCOUT_COMMIT_BATCH,lambda a,c:self.frame_census('scout',a,c))
            control_done=asyncio.Event();scout_done=asyncio.Event()
            async def owned(coroutine,finished):
                try:return await coroutine
                finally:finished.set()
            async def scouts(update,size,seen):
                if update.WhichOneof('update_oneof')!='account':raise EvidenceUnavailable('candidate_scout_filter')
                fact=scout_fact(update,seen)
                if fact is not None:
                    self.handlers.phase('SCOUT_QUEUE')
                    await scout_queue.put(fact)
            census=asyncio.create_task(self.structural_census()) if enabled('meteora') else None
            stop_task=asyncio.create_task(stop.wait())
            self.control_commit_task=asyncio.create_task(self.control_commits(control_queue,control_done))
            scout_commit=asyncio.create_task(self.scout_commits(scout_queue,scout_done))
            producers=[asyncio.create_task(owned(self.control_stream(channel,tip,control_queue),control_done)),
                asyncio.create_task(owned(self.scout_stream(channel,tip,scouts),scout_done)),
                asyncio.create_task(self.live_manager(channel)),asyncio.create_task(self.rolling_programs(channel))]
            background=[asyncio.create_task(self.acquire_pool()),asyncio.create_task(self.cold_maintenance()),
                asyncio.create_task(self.publish_history()),asyncio.create_task(self.source_reporting())]
            if separated_history():
                background.append(asyncio.create_task(self.historical_processing()))
                background.append(asyncio.create_task(self.candidate_history_delivery()))
            if census is not None:background.append(census)
            if not operational():producers.append(asyncio.create_task(self.activity_manager(channel)))
            consumers=[self.control_commit_task,scout_commit]
            tasks=[*producers,*consumers,*background,stop_task];primary=None
            try:
                remaining=set(tasks)
                while not stop.is_set():
                    done,_=await asyncio.wait(remaining,return_when=asyncio.FIRST_COMPLETED)
                    # Inspect a failure racing with stop before accepting stop.
                    for task in done:
                        if task.cancelled() and stop.is_set():continue
                        task.result()
                        if task is census:remaining.remove(task)
                        elif task is not stop_task and not stop.is_set():
                            raise EvidenceUnavailable('candidate_source_task_stopped')
            except BaseException as exc:
                if isinstance(exc,asyncio.CancelledError) and not stop.is_set():
                    self.source_drain['unexpected_cancellation']=True
                primary=exc;stop.set()
                if not isinstance(exc,asyncio.CancelledError):
                    from .runtime.evidence_worker import failure_diagnostic
                    try:await work(lambda s:install(s).startup.fail(failure_diagnostic(exc)),0)
                    except BaseException:pass # The first application error wins.
                raise
            finally:
                stop.set();self.source_drain['state']='DRAINING'
                async def teardown():
                    drain_error=None
                    try:
                        # Optional/history work stops first; its existing accepted
                        # consumer future still FULL-commits/ACKs on cancellation.
                        for task in background:task.cancel()
                        background_results=await asyncio.gather(*background,return_exceptions=True)
                        failures=[result for result in background_results
                            if isinstance(result,BaseException) and not isinstance(result,asyncio.CancelledError)]
                        results=await settle_owned(producers,consumers)
                        for result in results:
                            if isinstance(result,BaseException):
                                # Stop waiters and producers canceled because their
                                # consumer failed are secondary. Preserve the real
                                # commit error below; the census still fails closed
                                # for every incomplete accepted handler/frame.
                                if isinstance(result,asyncio.CancelledError):continue
                                failures.append(result)
                        # An independent source failure must not abandon the other
                        # healthy queue's already accepted durable work.
                        for queue,worker in ((control_queue,self.control_commit_task),(scout_queue,scout_commit)):
                            try:await join_owned(queue,worker)
                            except BaseException as exc:failures.append(exc)
                        results=await asyncio.gather(*consumers,return_exceptions=True)
                        failures.extend(result for result in results if isinstance(result,BaseException))
                        await self.flush_delivery();await self.flush_diagnostics()
                        if failures:raise failures[0]
                    except BaseException as exc:
                        drain_error=exc
                    finally:
                        remaining=[*tasks,*self.optional_stops]
                        for task in remaining:
                            if not task.done():task.cancel()
                        await asyncio.gather(*remaining,return_exceptions=True)
                        snapshot=self.drain_snapshot()
                        complete=(drain_error is None and snapshot['all_accepted_committed']
                            and snapshot['pending_handlers']==0 and not snapshot['unpreserved_sessions']
                            and snapshot['handler_accounting']['valid'] and not snapshot.get('unexpected_cancellation',False))
                        self.source_drain.update(state='DRAINED' if complete else 'RECOVERY_REQUIRED',terminal=True,
                            terminal_at_monotonic=time.monotonic())
                        if not complete and drain_error is None:
                            drain_error=EvidenceUnavailable('accepted_source_frame_drain_incomplete')
                        unresolved=[dict(r) for r in self.handlers.records.values() if r['state']!='RECOVERABLE']
                        def terminal(state):
                            h=install(state);body=self.drain_snapshot()
                            with state.writer.transaction():
                                assert_source_drain_boundary(state,self.retained_source_drain,
                                    handler_boundary=self.retained_handler_recovery)
                                preserve_handlers(state,self.handlers,unresolved,None)
                                body['pending_history']=h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0]
                                body['pending_proofs']=h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0]
                                publish_source_drain(state,self.retained_source_drain,body,
                                    handler_boundary=self.retained_handler_recovery,
                                    contained_observation=self.contained_observation,
                                    observation_boundary=self.observation_drain_boundary)
                        try:await self.work(terminal,0,label='source_commit')
                        except BaseException:
                            self.source_drain.update(state='RECOVERY_REQUIRED',terminal_record_unavailable=True)
                            if drain_error is None:drain_error=EvidenceUnavailable('source_drain_terminal_unavailable')
                    if primary is None and drain_error is not None:raise drain_error
                cleanup=asyncio.create_task(teardown())
                self.global_teardown=cleanup
                try:await finish_owned(cleanup,self.shutdown_deadline())
                except TimeoutError:
                    self.source_drain.update(state='RECOVERY_REQUIRED',terminal_record_unavailable=True)
                    if primary is not None and not isinstance(primary,asyncio.CancelledError):raise primary
                    raise

    async def structural_census(self):
        """Exhaust both WSOL orientations. Quiet pools remain durable forever."""
        if not enabled('meteora'):return
        await self.wait_startup()
        from . import pump
        from .postgrad import WSOL
        for label,offset in (('m',88),('n',120)):
            def load(state):
                h=install(state);db=state.writer.db
                row=db.execute('SELECT cursor,status,slot FROM structural_census WHERE label=?',(label,)).fetchone()
                # After a completed census, changedSinceSlot catches restart
                # development. A partially scanned census resumes its real cursor.
                return row or (None,'pending',None)
            token,status,since=await self.work(load,6)
            while not self.stop.is_set():
                options=dict(commitment='finalized',encoding='base64',withContext=True,limit=1000,
                    dataSlice=dict(offset=0,length=152),filters=[
                        dict(memcmp=dict(offset=0,bytes=pump.b58(hashlib.sha256(b'account:LbPair').digest()[:8]))),
                        dict(memcmp=dict(offset=offset,bytes=WSOL))])
                if token is not None:options['paginationKey']=token
                if status=='complete' and since is not None:options['changedSinceSlot']=since
                result=await self.measured_rpc('getProgramAccountsV2',[PROGRAMS['meteora'],options],'meteora_scout',6)
                context=result.get('context',{});value=result.get('value',result)
                if (type(context.get('slot')) is not int or not isinstance(value.get('accounts'),list)
                        or len(value['accounts'])>1000):raise EvidenceUnavailable('candidate_scout_census_shape')
                next_token=value.get('paginationKey')
                if next_token is not None and (not isinstance(next_token,str) or not next_token or next_token==token):
                    raise EvidenceUnavailable('repair_pagination_stalled')
                def commit(state,rows):
                    h=install(state);seen=h.clock()
                    with state.writer.transaction():
                        for row in rows:
                            account=row['account'];data=base64.b64decode(account['data'][0],validate=True)
                            if account['owner']!=PROGRAMS['meteora'] or len(data)!=152:
                                raise EvidenceUnavailable('candidate_scout_fields_missing')
                            if pubkey(data[offset:offset+32])!=WSOL:raise EvidenceUnavailable('candidate_scout_filter')
                            # Exact existing policy permits exactly one WSOL side.
                            if pubkey(data[88:120])==pubkey(data[120:152]):continue
                            h.observe('meteora',row['pubkey'],slot=context['slot'],signature='',seen=seen,
                                fields=dict(wsol_pair_locator=True,activity=False,economic_event=False,
                                    history_complete=False,source='paginated_structural_census'))
                    h.lifecycle.publish()
                # Provider pages remain complete and are not filtered. Only the
                # owner transaction is sliced so discovery cannot monopolize
                # control, position or deadline-sensitive canonical commits.
                for offset_in_page in range(0,len(value['accounts']),SCOUT_COMMIT_BATCH):
                    rows=value['accounts'][offset_in_page:offset_in_page+SCOUT_COMMIT_BATCH]
                    await self.work(lambda state,rows=rows:commit(state,rows),6,label='source_commit')
                def checkpoint(state):
                    h=install(state)
                    with state.writer.transaction():
                        state.writer.db.execute('INSERT OR REPLACE INTO structural_census VALUES(?,?,?,?,?)',
                            (label,next_token,'complete' if next_token is None else 'pending',context['slot'],h.clock()))
                # A crash inside a page repeats its unchanged durable cursor;
                # account identities/history deduplicate the completed slices.
                await self.work(checkpoint,6,label='source_commit')
                if next_token is None:break
                token=next_token

    async def activity_manager(self,channel):
        """Cheap status interests for retained market identities; no rich stream."""
        running=[];old=None;local_stop=None
        try:
            while not self.stop.is_set():
                # Account scouts already cover Pump and Meteora development.
                # PumpSwap quiet/demoted pools need their scoped status wakeups.
                addresses=await self.work(lambda s:[r[0] for r in install(s).db.execute(
                    "SELECT address FROM market_observations WHERE family='pumpswap' ORDER BY address")],6)
                identity=digest(addresses)
                for task in running:
                    if task.done():task.result();raise EvidenceUnavailable('candidate_activity_task_stopped')
                if identity!=old:
                    if running:
                        local_stop.set()
                        await asyncio.gather(*running)
                    old=identity;local_stop=asyncio.Event();running=[]
                    for route in shards(addresses):
                        async def activity(update,size,seen,route=route):
                            if update.WhichOneof('update_oneof')!='transaction_status':
                                raise EvidenceUnavailable('activity_filter_identity')
                            resolved=route.resolve(update.filters);item=update.transaction_status
                            def commit(state):
                                h=install(state)
                                for address in resolved['addresses']:
                                    h.lifecycle.wake('pumpswap',address,slot=item.slot,seen=seen,
                                        signature=signature(item.signature),evidence=resolved)
                                h.lifecycle.publish()
                            await self.work(commit,5,label='source_commit')
                        running.append(asyncio.create_task(self.stream(channel,route.subscription(),activity,
                            'pumpswap_activity',local_stop)))
                await asyncio.sleep(.5)
        finally:
            if local_stop is not None:local_stop.set()
            results=await asyncio.gather(*running,return_exceptions=True)
            if not __import__('sys').exc_info()[1]:
                for result in results:
                    if isinstance(result,BaseException):raise result

    async def rolling_programs(self,channel):
        """Fixed body-free filters, independent of candidate count or promotion.

        WS carries logs only; native status supplies identity/order, metadata and
        linked finality seal intervals. A restart requests an explicit overlapping
        gap, never falsely completes an unseen past.
        """
        from .solana_rolling_history import program_scope
        await self.wait_current_control()
        failures=0
        while not self.stop.is_set():
            from .operational.position_continuation import position_only
            if position_only():await asyncio.sleep(.5);continue
            def rows(state):
                h=install(state)
                return [dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,
                    deadline=h.clock()+120,lower_slot=0,rolling=True) for f in ('pump','pumpswap')]
            desired=await self.work(rows,6)
            published=self.rolling_publications
            local_stop=asyncio.Event();task=asyncio.create_task(self.live(channel,desired,local_stop));handled=None
            try:
                while not task.done() and not self.stop.is_set() and not position_only():
                    await asyncio.sleep(.25)
                if task.done():await task
            except (EvidenceUnavailable,ConnectionClosed,OSError) as exc:
                handled=exc
                reason=str(exc) if isinstance(exc,EvidenceUnavailable) else type(exc).__name__
                self.observe('rolling_retry',reason=reason)
                self.diagnostic('rolling_retry',dict(reason=reason,complete=False))
                # Repeating the same permanently incomplete supplement cannot
                # repair its missing economics. Preserve its exact gap and
                # report unavailable instead of rebuilding the entire feed.
                if reason in FATAL_REPAIR_REASONS:raise
                if self.rolling_publications>published:failures=0
                failures+=1
                await asyncio.sleep(min(8,.5*2**min(failures-1,4)))
            finally:
                import sys
                primary=sys.exc_info()[1]
                results=await self.close_optional_session(task,local_stop)
                if primary is None:
                    for result in results:
                        if isinstance(result,BaseException) and not isinstance(result,asyncio.CancelledError) and result is not handled:raise result

    async def cold_maintenance(self):
        from .solana_scoped_retirement import ScopedRetirement
        from .solana_history_work import enabled as separated_history
        from .solana_history_archive import prepare,apply
        # Retirement is not a prerequisite for initial evidence convergence.
        # Keep its telemetry and disk work out of the startup release barrier.
        await self.wait_startup()
        failures=0
        while not self.stop.is_set():
            def retire(state):
                h=install(state)
                if not self.batched:h.lifecycle.publish()
                separated=separated_history()
                if separated:
                    from .solana_history_delivery import readonly_history
                    from contextlib import closing
                    if not h.lifecycle.path.exists():return None
                    with closing(readonly_history(h.lifecycle.path)) as shared:
                        if not shared.db.execute("SELECT 1 FROM sqlite_master WHERE name='work'").fetchone():return None
                return ScopedRetirement(h).retire(limit=64,measure_hot_bytes=False,plan_only=separated)
            # The owner installs its existing urgent SQL interruption hook for
            # maintenance priority four. Interrupted slices retry durably.
            plan=await self.work(retire,4,label='retention')
            if separated_history() and plan not in (None,0):
                try:
                    if plan['selected']:
                        result=await asyncio.wrap_future(self.historical_executor.submit(prepare,plan))
                    else:result=dict(selected={},addresses={},body_hashes={},receipt=None,worker=dict(cpu_seconds=0,wall_seconds=0))
                    await self.work(lambda state:apply(install(state),plan,result),4,label='retention')
                    failures=0
                except asyncio.CancelledError:raise
                except sqlite3.OperationalError as exc:
                    if getattr(exc,'sqlite_errorcode',0)&255 not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):raise
                    failures+=1
                    await self.work(lambda state:install(state)._observation(None,'candidate_consumer_write_busy',
                        dict(complete=False,operation='scoped_archive_verify',off_owner=True)),2)
                    await asyncio.sleep(min(2,.1*2**min(failures-1,5)))
                except (RuntimeError,MemoryError) as exc:
                    failures+=1
                    await self.work(lambda state:install(state)._observation(None,'historical_archival_unavailable',
                        dict(complete=False,reason=type(exc).__name__,failures=failures)),2)
                    await asyncio.sleep(min(30,.5*2**min(failures-1,6)))
            await asyncio.sleep(1)

    async def acquire_pool(self):
        tasks=[asyncio.create_task(self.acquire()) for _ in range(ARCHIVE_WORKERS)]
        try:await asyncio.gather(*tasks)
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)

    async def historical_processing(self):
        """One bounded off-owner result; archive workers do not run its CPU work."""
        from .solana_history_work import prepare_history
        await self.wait_startup()
        while not self.stop.is_set():
            job=await self.work(lambda state:install(state).historical_tasks.claim(),4,
                label='history_dispatch')
            if job is None:
                await asyncio.sleep(.1);continue
            try:
                future=self.historical_executor.submit(prepare_history,self.canonical_path,job)
                result=await asyncio.wrap_future(future)
                # Keep a completed immutable result through cooperative owner
                # SQL yields; do not restart the expensive calculation.
                while not self.stop.is_set():
                    try:
                        await self.work(lambda state:install(state).historical_tasks.apply(job,result),
                            0 if job['priority']<=2 else 4,label='history_apply')
                        break
                    except EvidenceUnavailable as exc:
                        if str(exc)!='evidence_background_yield':raise
                        await asyncio.sleep(0)
                    except sqlite3.OperationalError as exc:
                        if str(exc)!='interrupted':raise
                        await asyncio.sleep(0)
            except asyncio.CancelledError:
                # An accepted bounded CPU task can finish without publishing.
                # Its durable lease remains recoverable; canonical intake and
                # accounting do not depend on a volatile result being retained.
                raise
            except Exception as exc:
                if isinstance(exc,EvidenceUnavailable) and 'corrupt' in str(exc):raise
                # No paid retry and no favourable coverage. Optional history
                # failure retains candidates and backs off independently.
                import os
                diagnostic={}
                if os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')=='1':
                    from concurrent.futures.process import BrokenProcessPool
                    from .runtime.sqlite_failure import payload
                    context=payload(exc)
                    if isinstance(exc,BrokenProcessPool):raise
                    if isinstance(exc,sqlite3.Error) and (
                            context is None or context.get('recorder_valid') is not True):raise
                    if context is not None:
                        from .runtime.evidence_worker import failure_diagnostic
                        diagnostic['diagnostic']=failure_diagnostic(exc)
                reason=type(exc).__name__
                await self.work(lambda state:install(state).historical_tasks.defer(
                    job,reason,**diagnostic),2,label='history_apply')
                await asyncio.sleep(.1)

    async def _complete_history_delivery(self,snapshot,result):
        """ACK then publish this exact durable proof batch, in separate turns.

        The background proof cursor may have passed the batch while its
        independent consumer FULL-committed. Revisit its pending identities,
        never its untrusted result as completeness. Keep an owner admission
        between ACK and proof publication so protective work can still win.
        """
        from .solana_history_delivery import acknowledge
        snapshot['proof_publication_changed']=False
        accepted=await self.work(lambda state:acknowledge(install(state).lifecycle,snapshot,result),2,
            label='candidate_delivery_ack')
        identities=tuple(snapshot.get('publication_ids',[proof['identity'] for proof in snapshot['proofs']]))
        if accepted and identities:
            # Retain the same accounting-before-publication fence as the
            # background publisher. ACK alone does not flush native delivery.
            def publish_exact(state):
                life=install(state).lifecycle;life.publish(proof_ids=identities)
                return getattr(life,'_published_count',0)
            published=await self.flush_delivery(publish_exact)
            snapshot['proof_publication_changed']=bool(published)
        return accepted

    async def candidate_history_delivery(self):
        """Mandatory bounded consumer work, independent of optional history."""
        from .solana_history_delivery import capture,deliver,acknowledge
        failures=0;seen=-1;urgent_seen=0;not_before=0;deadline=None
        while not self.stop.is_set():
            seen=await self.delivery_wakeup.wait(seen,self.stop,
                delay=None if deadline is None else max(0,deadline-time.time()))
            if time.monotonic()<not_before:
                await self.delivery_urgent.wait(urgent_seen,self.stop,delay=not_before-time.monotonic())
            seen=self.delivery_wakeup.epoch;urgent_seen=self.delivery_urgent.epoch
            if self.stop.is_set():break
            snapshot=await self.work(lambda state:capture(install(state).lifecycle,
                revision=getattr(self,'delivery_revision',0),schedule=True),2,
                label='candidate_delivery_capture')
            if snapshot is None:
                deadline=None;continue
            deadline=snapshot.get('proof_deadline')
            try:
                consumer_work=bool(snapshot['rows'] or snapshot['proofs'] or snapshot['refresh'])
                if consumer_work:
                    future=asyncio.wrap_future(self.delivery_executor.submit(deliver,snapshot))
                    try:result=await asyncio.shield(future)
                    except asyncio.CancelledError:
                        # Drain the single accepted batch before owner closure.
                        # A crash leaves exact durable receipts/pending replay.
                        result=await asyncio.shield(future)
                        await self.work(lambda state:acknowledge(install(state).lifecycle,snapshot,result),2,
                            label='candidate_delivery_ack')
                        raise
                else:result=dict(acknowledgements=[],refreshed=[])
                accepted=await self._complete_history_delivery(snapshot,result)
                if snapshot.get('proof_publication_changed'):self.history_changed(publication=False)
                if consumer_work:self.observe('history_delivery_timing',**result['metrics'])
                # Noncritical short batches coalesce within the ORIGINAL 100-ms
                # cadence. Canonical/proof work bypasses it; a full batch drains
                # immediately. There is no idle polling or later trade deadline.
                not_before=0 if len(snapshot['rows'])==64 else time.monotonic()+.1
                publication=bool(snapshot.get('publication_ids',snapshot['proofs'])) or not accepted
                more=bool(snapshot.get('proof_scan',{}).get('more'))
                # Internal page/ACK drainage is not another committed-work
                # revision: finished scans must not reopen each other forever.
                if publication:self.history_wakeup.notify()
                if consumer_work or more or not accepted:self.delivery_wakeup.notify()
                if publication or more or not accepted:self.delivery_urgent.notify()
                failures=0
            except sqlite3.OperationalError as exc:
                if getattr(exc,'sqlite_errorcode',0)&255 not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):raise
                failures+=1
                await self.work(lambda state:install(state)._observation(None,'candidate_consumer_write_busy',
                    dict(complete=False,failures=failures,off_owner=True)),2)
                await asyncio.sleep(min(2,.1*2**min(failures-1,5)))
                self.delivery_wakeup.notify()
            except (RuntimeError,MemoryError) as exc:
                failures+=1
                await self.work(lambda state:install(state)._observation(None,'candidate_delivery_unavailable',
                    dict(complete=False,failures=failures,reason=type(exc).__name__)),2)
                await asyncio.sleep(min(8,.5*2**min(failures-1,4)))
                self.delivery_wakeup.notify()

    async def acquire(self):
        from .operational.position_continuation import position_only
        from .runtime.evidence_worker import DeliveredRPCError,failure_diagnostic
        from .solana_selective_history import (missing_archive_log_transactions,
            join_archive_log_supplement,complete_archive_transaction)
        while not self.stop.is_set():
            def request_development(state):
                from .lanes.pump.pump_acceleration_strategy import POLICY
                timing=self.development_phases
                with timing.phase('selection'):
                    h=install(state);db=state.writer.db
                    if not hasattr(state,'acquisition_inflight'):state.acquisition_inflight=set()
                    if not h.startup.snapshot().get('released'):return None
                    if hasattr(h,'historical_recovery'):h.historical_recovery.resume_sync(limit=16)
                    frontier=db.execute('SELECT MAX(hi) FROM coverage WHERE scope=?',(CONTROL,)).fetchone()[0]
                # Eight acquisition workers share one owner and one development
                # queue. Coalesce their duplicate housekeeping at the existing
                # 100-ms polling cadence, while planning every individual job.
                # This is a scheduling clock, never evidence or a fresh deadline.
                if (frontier is not None and not position_only()
                        and time.monotonic()>=getattr(state,'development_poll_at',0)):
                    # One existing owner operation, not a FULL fsync for every
                    # binding, wait and reactivation. Original facts and absolute
                    # deadlines roll back together if this operation yields.
                    cursors=getattr(state,'development_cursors',{})
                    with timing.transaction_exit(state.writer.transaction(),phase_name='commit'):
                        with timing.phase('selection'):
                            for addr, in h.development_candidates(POLICY.min_curve_progress_bps,DEVELOPMENT_BATCH):
                                h.bind('pump',addr)
                                first=db.execute("SELECT first_seen FROM candidate_lifecycle WHERE family='pump' AND address=?",(addr,)).fetchone()[0]
                                h.rolling.prepare('pump',addr,0,frontier,priority=3,deadline=first+150)
                        with timing.phase('reactivation'):
                            query="SELECT rowid,family,address,lower_slot FROM candidate_lifecycle WHERE "+active_sql('family',solana=True)+" AND state='reactivated' AND rowid>? ORDER BY rowid LIMIT ?"
                            with operation('owner.reactivation_lookup'):
                                reactivated=db.execute(query,(cursors.get('reactivated',0),DEVELOPMENT_BATCH)).fetchall()
                                if not reactivated and cursors.get('reactivated',0):reactivated=db.execute(query,(0,DEVELOPMENT_BATCH)).fetchall()
                            for _,family,addr,lo in reactivated:
                                with operation('owner.reactivation_lookup'):
                                    epoch=db.execute('SELECT epoch FROM candidate_lifecycle WHERE family=? AND address=?',(family,addr)).fetchone()[0]
                                    first=db.execute("SELECT MIN(json_extract(body,'$.seen')) FROM candidate_history_outbox WHERE family=? AND address=? AND kind='reactivated' AND json_extract(body,'$.epoch')=?",(family,addr,epoch)).fetchone()[0]
                                deadline=(time.time() if first is None else first)+150
                                if deadline<=time.time():
                                    h._observation(None,'promotion_deadline_missed',dict(family=family,address=addr,deadline=deadline,deadline_reset=False))
                                    h.lifecycle.demote(family,addr,reason='original_promotion_deadline_expired');continue
                                if hasattr(h,'historical_tasks') and family in ('pump','pumpswap'):
                                    if not h.historical_tasks.cold_ready(family,addr,epoch=epoch,deadline=deadline):continue
                                else:
                                    from .solana_scoped_retirement import ScopedRetirement
                                    ScopedRetirement(h).restore(family,addr)
                                h.lifecycle.promote(family,addr,deadline=deadline,lower_slot=0 if family=='pump' else None if family=='meteora' else lo)
                        with timing.phase('boundaries'):
                            boundary=h.rolling.resume_boundaries(limit=DEVELOPMENT_BATCH,after=cursors.get('boundary',0))
                        with timing.phase('publication'):
                            publication=h.rolling.resume_publication(limit=DEVELOPMENT_BATCH,after=cursors.get('publication',0))
                    # Advance scheduling cursors only after the whole bounded
                    # owner transaction commits. A yielded slice retries every
                    # original fact and deadline, without skipping obligations.
                    state.development_cursors=dict(reactivated=reactivated[-1][0] if reactivated else 0,
                        boundary=boundary,publication=publication)
                    state.development_poll_at=time.monotonic()+.1
                # The batched source already owns the ordered 100-ms publisher.
                # Pending proofs still block false coverage in h.plan below.
                with timing.phase('plan'):
                    if not self.batched:h.lifecycle.publish()
                    if 'meteora' in h.active_families:h.rolling.repair_required_checkpoint_prefixes()
                    result=h.plan(excluding=tuple(state.acquisition_inflight))
                    if result:
                        state.acquisition_inflight.add(result[0]['id'])
                        result[0]['finalized_hint']=frontier
                return result
            # All archive workers use the same sole owner and pending queue.
            # After an empty plan, eight identical polls otherwise contend with
            # native publication. Share only the existing 100-ms idle cadence;
            # every nonempty job still gets its own original claim/deadline.
            # No evidence result or successful plan is cached here.
            async with self.acquisition_plan_lock:
                if time.monotonic()<self.acquisition_idle_until:plan=None
                else:
                    plan=await self.work(request_development,4,label='candidate_development')
                    if not plan:self.acquisition_idle_until=time.monotonic()+.1
            if not plan:await asyncio.sleep(.1);continue
            job,config=plan
            def commit(state):
                h=install(state)
                if job['family']=='pump':
                    from .solana_program_decoders import pump_events
                    for tx in value['data']:
                        supplement=supplement_by_original.get(canonical(tx))
                        if supplement is not None:
                            tx=complete_archive_transaction(tx,supplement,endpoint_identity=self.config.identity)
                        for event in pump_events(tx):
                            if event['event_type']=='create' and job['address'] in (event.get('mint'),event.get('bonding_curve')):
                                # Initial curve identity is upgraded, not rejected,
                                # when its canonical creation reveals the mint.
                                old_scope=h.scope_for('pump',job['address'])
                                state.writer.db.execute('DELETE FROM evidence_bindings WHERE family=? AND address=?',('pump',job['address']))
                                new_scope=h.bind('pump',job['address'],market_address=event['mint'],aliases=(event['mint'],))
                                if old_scope!=new_scope:
                                    h.lifecycle.rebind_pins(old_scope,new_scope)
                                    # Reprove the actual alias interval; an old
                                    # namespace checkpoint is never copied ahead.
                                    h.gap(new_scope,job['lo'],job['hi'],'pump_identity_upgrade_overlap')
                            if event['event_type']=='migration':
                                h.observe('pumpswap',event['pool'],slot=event['slot'],signature=tx['transaction']['signatures'][0],fields=dict(mint=event['mint'],graduation=event['market_time']))
                                h.bind('pumpswap',event['pool'])
                result=h.commit_page(job,value,finalized_through=finalized,supplements=supplements)
                h.lifecycle.publish()
                return result
            try:
                value=await self.measured_rpc('getTransactionsForAddress',[job['address'],config],job['family'],job['priority'])
                # The immutable upper bound is already finalized when the linked
                # control stream has durably covered it. Only missing authority
                # needs an additional physical finality read for this page.
                finalized=job.get('finalized_hint')
                if finalized is None or finalized<job['hi']:
                    finalized=await self.measured_rpc('getSlot',[dict(commitment='finalized')],'shared',job['priority'])
                if finalized<job['hi']:await asyncio.sleep(.1);continue
                acquired=[];supplement_bytes=0
                for original in missing_archive_log_transactions(job['family'],value):
                    fetched=await self.measured_rpc('getTransaction',[original['transaction']['signatures'][0],
                        dict(commitment='finalized',encoding='json',maxSupportedTransactionVersion=1)],
                        job['family'],job['priority'])
                    supplement=join_archive_log_supplement(original,fetched,endpoint_identity=self.config.identity)
                    supplement_bytes+=len(supplement.fetched_json.encode())
                    if supplement_bytes>MAX_FRAME_BYTES:raise EvidenceUnavailable('archive_log_supplement_bound')
                    acquired.append(supplement)
                supplements=tuple(acquired)
                supplement_by_original={item.original_json:item for item in supplements}
                # A fetched page publishes required canonical evidence. Priority
                # four is the owner's interruptible maintenance class: using it
                # here repeatedly rolled a 100-row Meteora page back whenever
                # position/control work arrived. Keep the bounded page in the
                # ordinary source FIFO; urgent work still runs before its claim.
                # Acquisition RPC urgency and the original deadline are unchanged.
                try:await self.work(commit,min(job['priority'],3),label='source_commit')
                except ValueError as exc:
                    if isinstance(exc,EvidenceUnavailable):
                        if str(exc)!='candidate_page_lease_stale':raise
                        def expired(state):
                            h=install(state)
                            row=h.db.execute('SELECT status,deadline FROM acquisition_jobs WHERE id=?',(job['id'],)).fetchone()
                            if not row or row[0]!='deadline_missed' or row[1]>h.clock():raise EvidenceUnavailable('candidate_page_lease_stale')
                            h._observation(job['id'],'late_page_after_original_deadline',dict(deadline=row[1],canonical_admission=False,deadline_reset=False))
                        await self.work(expired,job['priority'])
                    elif str(exc) in ('truncated trade event','truncated create event'):
                        # Frozen decoder incompatibility is scoped and explicit.
                        # Preserve the candidate, deadline and missing interval;
                        # never certify the page or terminate unrelated positions.
                        def unavailable(state):
                            h=install(state)
                            with state.writer.transaction():
                                h.db.execute("UPDATE acquisition_jobs SET status='failed',error=?,updated=? WHERE id=? AND status='pending'",
                                    ('candidate_archive_decoder_unavailable',h.clock(),job['id']))
                                h.gap(h.scope_for(job['family'],job['address']),job['lo'],job['hi'],'candidate_archive_decoder_unavailable')
                                h._observation(job['id'],'archive_decoder_unavailable',dict(reason=str(exc),
                                    candidate_retained=True,economic_rejection=False,complete=False,deadline=job['deadline']))
                        await self.work(unavailable,job['priority'])
                    else:raise
            except DeliveredRPCError as exc:
                if job['priority']<=2:raise
                await self.work(lambda state:install(state).defer_provider_failure(job,
                    retryable=exc.retryable,diagnostic=failure_diagnostic(exc)),job['priority'])
            except EvidenceUnavailable as exc:
                if str(exc)!='bootstrap_optional_work_closed':raise
                await self.work(lambda state:install(state)._observation(job['id'],
                    'bootstrap_optional_work_closed',dict(candidate_retained=True,complete=False,
                        deadline=job['deadline'],funding_closed=True)),1)
            finally:
                await self.work(lambda state:state.acquisition_inflight.discard(job['id']),1)

    async def live_manager(self,channel):
        from .solana_stable_shards import StableShards
        await self.wait_startup()
        planner=StableShards(MAX_LIVE_CANDIDATES);running={};retry_at={};failures={};revision=None;groups={}
        try:
            while not self.stop.is_set():
                # A read-only revision peek cannot mutate or fork membership.
                # Many changes coalesce into one plan of the latest owner state.
                from .operational.position_continuation import position_only
                requested=(self.read_revision(),position_only())
                self.observe('membership_requested',revision=requested)
                if requested!=revision:
                    def plan(state):
                        rows=plan_live(state)
                        return state.writer.db.execute('SELECT revision FROM prewarm_membership_revision WHERE id=1').fetchone()[0],rows
                    _revision,desired=await self.work(plan,2)
                    revision=requested
                    # Pump/PumpSwap candidates consume the fixed program feeds.
                    # Only position/continuation interests need extra priority
                    # filters; promotion never installs a historical RPC stream.
                    desired=[r for r in desired if r['family']=='meteora' or r['priority']<=2]
                    groups=planner.reconcile(desired);self.observe('membership_plan',revision=revision,groups=len(groups))
                else:self.observe('membership_suppressed',revision=revision)
                for number,(identity,local_stop,task) in list(running.items()):
                    if task.done():
                        try:task.result()
                        except (ConnectionClosed,OSError) as exc:
                            failures[number]=failures.get(number,0)+1
                            retry_at[number]=time.monotonic()+min(8,.5*2**min(failures[number]-1,4))
                            await self.work(lambda s:install(s)._observation(None,'subscription_retry',dict(shard=number,reason='candidate_websocket_transport_closed',position=groups.get(number,{}).get('position',False))),1)
                        except EvidenceUnavailable as exc:
                            if str(exc) not in ('candidate_websocket_ack_timeout','candidate_native_eof','candidate_native_unavailable','candidate_native_internal','candidate_native_deadline_exceeded','candidate_native_cancelled','candidate_native_resource_exhausted','candidate_log_buffer_pressure','yellowstone_census_buffer_bound','yellowstone_incomplete_status_census'):raise
                            failures[number]=failures.get(number,0)+1
                            retry_at[number]=time.monotonic()+min(8,.5*2**min(failures[number]-1,4))
                            await self.work(lambda s:install(s)._observation(None,'subscription_retry',dict(shard=number,reason=str(exc),position=groups.get(number,{}).get('position',False))),1)
                        else:raise EvidenceUnavailable('candidate_live_task_stopped')
                        del running[number]
                        continue
                    if number not in groups or groups[number]['identity']!=identity:
                        local_stop.set()
                        self.session_deadlines.setdefault(task,self.shutdown_deadline())
                        try:await asyncio.wait_for(asyncio.shield(task),30)
                        except TimeoutError:
                            task.cancel();await asyncio.gather(task,return_exceptions=True)
                            raise EvidenceUnavailable('source_filter_rebuild_drain_timeout') from None
                        del running[number]
                for number,group in groups.items():
                    if number in running or time.monotonic()<retry_at.get(number,0):continue
                    local_stop=asyncio.Event()
                    self.observe('membership_install',group=number,identity=group['identity'])
                    running[number]=(group['identity'],local_stop,asyncio.create_task(self.live(channel,group['rows'],local_stop)))
                await asyncio.sleep(.25)
        finally:
            for _,local_stop,task in running.values():local_stop.set()
            results=await asyncio.gather(*(task for _,_,task in running.values()),return_exceptions=True)
            if not __import__('sys').exc_info()[1]:
                for result in results:
                    if isinstance(result,BaseException):raise result

    def read_revision(self):
        import sqlite3
        from pathlib import Path
        from contextlib import closing
        with closing(sqlite3.connect(Path(self.canonical_path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            return db.execute('SELECT revision FROM prewarm_membership_revision WHERE id=1').fetchone()[0]

    async def wait_startup(self):
        from .solana_prewarm_startup import candidate_release
        while not self.stop.is_set():
            if candidate_release(self.canonical_path):return
            try:await asyncio.wait_for(self.stop.wait(),.1)
            except TimeoutError:pass
        raise asyncio.CancelledError()

    async def wait_current_control(self):
        """Catch up the existing header replay before opening live log joins.

        This orders acquisition only. Full economic publication, canonical
        candidate coverage, fresh execution and financial admission still apply.
        """
        # The initial HTTP tip ages while replay drains. Reaching that old
        # number can leave control minutes behind newly opened WS logs, which
        # then compete with the required replay and fill the bounded join.
        # Use only an actually sealed, durably committed native receipt here.
        # This gate grants no economic coverage or executable quote authority.
        while (self.control_bootstrap_tip is not None and
                (self.control_committed_slot is None or self.control_committed_slot<self.control_bootstrap_tip
                 or self.control_committed_market_time is None
                 or not 0<=time.time()-self.control_committed_market_time<=CONTROL_CURRENT_SECONDS)):
            if self.stop.is_set():raise asyncio.CancelledError()
            try:await asyncio.wait_for(self.stop.wait(),.05)
            except TimeoutError:pass

    async def live(self,channel,desired,local_stop):
        session_stop=asyncio.Event();local_stop=StopEither(local_stop,session_stop)
        if self.stop.is_set() or local_stop.is_set():return
        rolling=any(r.get('rolling') for r in desired);has_checkpoint=False;prospective_rolling=False
        tip=await self.measured_rpc('getSlot',[dict(commitment='finalized')],'shared',2)
        def replay_floor(state):
            nonlocal has_checkpoint,prospective_rolling
            if rolling:
                floor,prospective_rolling,has_checkpoint=rolling_replay_boundary(state,desired,tip)
                return floor
            h=install(state);points=[]
            for row in desired:
                scopes=h.rolling.scopes(row['family'],row['scope'])
                value=state.writer.db.execute('SELECT MAX(slot) FROM candidate_checkpoints WHERE scope IN ('+
                    ','.join('?' for _ in scopes)+')',scopes).fetchone()[0]
                if value is not None:points.append(value)
            earliest=min(points,default=tip)
            has_checkpoint=bool(points)
            if any(r.get('rolling') for r in desired) and not points:return tip+1
            if all(r['family']=='meteora' for r in desired) and not points:
                # First-sight accumulation starts here. The scout's old locator
                # is not an obligation to reconstruct its entire past. Promotion
                # and positions request exact checkpoint/lookback gaps separately.
                return tip+1
            return max(1,min(tip-WARM_OVERLAP,earliest-WARM_OVERLAP)) if tip-earliest<REPLAY_SLOTS else max(1,tip-WARM_OVERLAP)
        floor=await self.work(replay_floor,1 if any(r['priority']<=1 for r in desired) else 3)
        if self.stop.is_set() or local_stop.is_set():return
        addresses={r['address']:r['scope'] for r in desired}
        full={r['address'] for r in desired if r['family']=='meteora'}
        # A fresh HTTP tip can be ahead of the finalized WS delivery frontier.
        # Buffer the startup log prefix until both subscribed programs deliver
        # their first real finalized slot. Coverage starts on the following
        # slot; the partially subscribed first slot is never called complete.
        fresh_rolling=rolling and prospective_rolling
        join=CandidateTransactionJoin(addresses,full,filtered_from_slot=1 if fresh_rolling else floor,max_join_seconds=120 if rolling else 10);session=uuid.uuid4().hex
        log_frontiers={};logs_available=asyncio.Event()
        plane='rolling' if rolling else 'candidate'
        candidate_queue=CandidateCommitQueue(lambda a,c:self.frame_census(plane,a,c));join_progress=asyncio.Event()
        producer_done=asyncio.Event()
        async def commit(frame):
            if frame:
                self.handlers.phase('CANDIDATE_QUEUE')
                self.observe('joined_frame',plane='rolling' if rolling else 'candidate',
                    slot=frame.update.block.slot,joined_wall=time.time())
                await candidate_queue.put(frame)
        acknowledged=asyncio.Event()
        async def native(update,size,seen):
            try:
                self.handlers.phase('CANDIDATE_JOIN')
                frame=join.feed(update,size,seen)
                join_progress.set()
                self.observe_join('rolling' if rolling else 'candidate',join,session,candidate_queue)
                await commit(frame)
            except EvidenceUnavailable as exc:
                diagnostic=dict(reason=str(exc),addresses=len(addresses),pending_slots=len(join.pending),
                    pending_bytes=join.pending_bytes,missing_logs=sum(1 for slot,item in join.pending.items()
                        for index,fact in item['statuses'].items() if fact[2] is None and not join.full_scopes.intersection(fact[3])
                        and (slot,signature(fact[0])) not in join.early_logs),
                    missing_meta=sum(item['meta'] is None for item in join.pending.values()),
                    missing_finality=sum(item['finality'] is None for item in join.pending.values()),
                    oldest_join_age=max((join.clock()-item['started'] for item in join.pending.values()),default=0),
                    missing_log_examples=[dict(slot=slot,signature=signature(fact[0])) for slot,item in join.pending.items() for index,fact in item['statuses'].items() if fact[2] is None and not join.full_scopes.intersection(fact[3]) and (slot,signature(fact[0])) not in join.early_logs][:8],
                    position=any(r['priority']<=1 for r in desired))
                try:await self.work(lambda s:install(s)._observation(None,'join_failure',diagnostic),1)
                except BaseException:
                    # The original failed handler wins over optional recording.
                    self.diagnostic('join_failure_record_unavailable',dict(original_failure_preserved=True))
                raise
        native.source_session=session
        native.source_scopes=tuple(addresses.values())
        async def logs():
            closed=asyncio.create_task(StopEither(self.stop,local_stop).wait())
            try:
                async with connect(self.config.stream_url,max_size=MAX_FRAME_BYTES,max_queue=2,ping_interval=10,ping_timeout=None) as ws:
                    ws_id=uuid.uuid4().hex
                    self.observe('websocket_open',stream_id=ws_id,addresses=[r['address'] for r in desired if r['family']!='meteora'])
                    pending={};registered={}
                    for number,row in enumerate((r for r in sorted(desired,key=lambda r:r['priority']) if r['family']!='meteora'),1):
                        pending[number]=row
                        await ws.send(canonical(dict(jsonrpc='2.0',id=number,method='logsSubscribe',
                            params=[dict(mentions=[row['address']]),dict(commitment='finalized')])))
                    if not pending:acknowledged.set()
                    while not self.stop.is_set() and not local_stop.is_set():
                        raw=await receive_until_closed(ws.recv,local_stop,closed_task=closed)
                        if raw is INTAKE_CLOSED:return
                        seen=time.time();received=time.monotonic();size=len(raw.encode() if isinstance(raw,str) else raw)
                        number=self.handlers.accept(ws_id,session,'websocket','candidate_logs','log_or_ack',seen)
                        try:
                            self.handlers.phase('LOG_DECODE')
                            self.observe('delivery',stream_id=ws_id,family='candidate_logs',transport='websocket',raw=raw.encode() if isinstance(raw,str) else raw,seen=seen,received_monotonic=received)
                            decode_started=time.monotonic();value=candidate_log_message(raw,max_bytes=MAX_FRAME_BYTES)
                            self.observe('decode_timing',stream_id=ws_id,family='candidate_logs',transport='websocket',bytes=size,seconds=time.monotonic()-decode_started)
                            if 'id' not in value:
                                result=value['params']['result']
                                self.handlers.phase('LOG_ACCOUNTING',slot=result['context']['slot'],identity=result['value']['signature'])
                                binding=registered.get(value['params']['subscription'])
                                if binding is not None:self.handlers.phase('LOG_ACCOUNTING',scope=binding['scope'])
                            await self.delivered('candidate_logs','websocket',size,seen,0 if 'id' in value else (0 if any(r['priority']<=1 for r in desired) else 2))
                            if 'id' in value:
                                if 'error' in value or value['id'] not in pending:raise EvidenceUnavailable('authoritative_subscription_rejected')
                                registered[value['result']]=pending.pop(value['id'])
                                if not pending:acknowledged.set()
                            else:
                                row=registered.get(value['params']['subscription'])
                                if row is None:raise EvidenceUnavailable('unknown_source_subscription')
                                v=result['value']
                                if fresh_rolling:
                                    log_frontiers.setdefault(row['family'],result['context']['slot'])
                                    if len(log_frontiers)==len({r['family'] for r in desired}):logs_available.set()
                                if v['err'] is None:
                                    self.handlers.phase('LOG_BUFFER_WAIT')
                                    await wait_candidate_log_space(join,join_progress,self.stop,local_stop,
                                        result['context']['slot'],v['signature'],v.get('logs'))
                                    try:
                                        self.handlers.phase('LOG_JOIN')
                                        if explicit_truncation(v.get('logs')):
                                            key=(result['context']['slot'],v['signature'])
                                            duplicate=key in join.incomplete_logs
                                            join.defer_log(result['context']['slot'],v['signature'],v['logs'],seen)
                                            if key in join.incomplete_logs:
                                                self.observe('log_repair',stage='duplicate_deliveries' if duplicate else 'deferred',
                                                    pending=len(join.incomplete_logs))
                                        elif (result['context']['slot'],v['signature']) in join.incomplete_logs:
                                            join.hold_complete_log(result['context']['slot'],v['signature'],v.get('logs'))
                                            self.observe('log_repair',stage='duplicate_deliveries')
                                        else:
                                            await commit(join.feed_log(result['context']['slot'],v['signature'],v.get('logs'),None,seen))
                                    except EvidenceUnavailable as exc:
                                        self.diagnostic('log_join_failure',dict(reason=str(exc),**join.diagnostic()))
                                        if str(exc)=='incomplete_finalized_logs':
                                            self.diagnostic('log_join_failure',dict(reason=log_input_reason(v.get('logs')),
                                                complete=False,**join.diagnostic()))
                                        raise
                        except BaseException as exc:
                            self.handlers.fail(number,exc);raise
                        else:self.handlers.finish(number)
            finally:
                closed.cancel();await asyncio.gather(closed,return_exceptions=True)
        tasks=[asyncio.create_task(self.candidate_commits(candidate_queue,addresses,session,
            rolling=rolling,grouped=all(r['family']=='meteora' and r['priority']>1 for r in desired),
            priority=native_commit_priority(desired),producer_done=producer_done))];waiter=None
        if len(full)<len(desired):tasks.append(asyncio.create_task(logs()))
        else:acknowledged.set()
        try:
            # Subscribe live first. The archive's upper fence is sampled AFTER
            # all ACKs, so events during subscribe/replay overlap are covered.
            waiter=asyncio.create_task(acknowledged.wait())
            done,_=await asyncio.wait([waiter,*tasks],timeout=8,return_when=asyncio.FIRST_COMPLETED)
            if waiter not in done:
                waiter.cancel();await asyncio.gather(waiter,return_exceptions=True)
                for task in done:task.result()
                if self.stop.is_set() or local_stop.is_set():return
                raise EvidenceUnavailable('candidate_websocket_ack_timeout')
            tip=await self.measured_rpc('getSlot',[dict(commitment='finalized')],'replay',1)
            if self.stop.is_set() or local_stop.is_set():return
            if fresh_rolling:
                try:await asyncio.wait_for(logs_available.wait(),8)
                except TimeoutError:raise EvidenceUnavailable('rolling_delivery_frontier_unavailable') from None
                floor=max(log_frontiers.values())+1
                join=rebase_log_join(join,floor)
            def warm(state):
                from .solana_scoped_retirement import ScopedRetirement
                h=install(state);cold=ScopedRetirement(h)
                if rolling:
                    for row in desired:h.startup.feed_ack(row['family'],floor,max(floor,tip))
                for row in desired:cold.restore(row['family'],row['address'])
                # A subscription ACK supplies an upper fence for this handoff
                # only. It cannot close another shard's outstanding disconnect.
                preserve_subscription_handoff(state,desired,tip,
                    rolling_floor=floor if fresh_rolling else None)
                # The native feed will replay full Meteora deltas from floor.
                # Before its durable publication, missing rows are convergence,
                # not evidence of a provider/history gap. Required checkpoint
                # prefixes are handled only once a real retained floor proves
                # that native rolling coverage cannot supply them.
                recovery=[r for r in desired if not r.get('rolling') and r['family']!='meteora' and r['priority']<5]
                h.lifecycle.repair(recovery,tip);h.lifecycle.publish()
                return bool(recovery) and len(recovery)==len(desired) and all(
                    r['family'] in ('pump','pumpswap') and not h.rolling.missing(r['family'],r['scope'],floor,tip)
                    for r in recovery)
            shared_replay=await self.work(warm,1 if any(r['priority']<=1 for r in desired) else 3)
            if shared_replay:
                # The fixed program feeds have already published this exact
                # recovery prefix. Keep that history and observe only its new
                # tail instead of buying identical per-position replay logs.
                floor=tip+1
                join=rebase_log_join(join,floor)
            # The native replay supplies independent identity/order witnesses;
            # RPC supplies only the old log content unavailable from WS ACKs.
            for row in sorted(desired,key=lambda r:r['priority']):
                if self.stop.is_set() or local_stop.is_set():return
                if row['family']=='meteora' or row.get('rolling') or floor>tip:continue
                token=None
                while True:
                    if self.stop.is_set() or local_stop.is_set():return
                    def published(state):
                        h=install(state)
                        return not rolling and all(r['family'] in ('pump','pumpswap') and r['priority']<5
                            and not h.rolling.missing(r['family'],r['scope'],floor,tip) for r in desired)
                    if await self.work(published,min(row['priority'],3)):
                        floor=tip+1
                        join=rebase_log_join(join,floor)
                        break
                    config=dict(transactionDetails='full',sortOrder='asc',limit=100,commitment='finalized',
                        encoding='json',maxSupportedTransactionVersion=1,filters=dict(slot=dict(gte=floor,lte=tip)))
                    if token:config['paginationToken']=token
                    value=await self.measured_rpc('getTransactionsForAddress',[row['address'],config],'replay',row['priority'])
                    for tx in value['data']:
                        if tx['meta']['err'] is None:join.feed_log(tx['slot'],tx['transaction']['signatures'][0],tx['meta']['logMessages'],None,time.time())
                    next_token=value.get('paginationToken')
                    if next_token is None:break
                    if next_token==token:raise EvidenceUnavailable('repair_pagination_stalled')
                    token=next_token
            if rolling:
                async def repair_logs():
                    # Independent native identities determine the exact missing
                    # field. This exception fetches bodies only for the recovery
                    # prefix unavailable from a new WS, never every promotion.
                    inflight=set();batch_inflight=False
                    async def publish_log(slot,sig,logs):
                        await self.work(lambda s:install(s)._observation(None,'selective_missing_field',dict(signature=sig,slot=slot,field='logMessages',reason='RECOVERY_GAP')),2)
                        frame=join.feed_log(slot,sig,logs,None,time.time());join_progress.set()
                        await commit(frame)
                        while True:
                            frame=join.drain()
                            if frame is None:break
                            join_progress.set();await commit(frame)
                    not_fetched=object()
                    async def one(slot,sig,fetched=not_fetched):
                        witness=None;authenticated=False
                        try:
                            witness=join.deferred_log_witness(slot,sig)
                            if fetched is not_fetched:
                                if witness is not None:self.observe('log_repair',stage='repair_logical_calls')
                                tx=await self.measured_rpc('getTransaction',[sig,dict(commitment='finalized',encoding='json',maxSupportedTransactionVersion=1)],'rolling_recovery_missing_logs',2)
                            else:tx=fetched
                            if witness is not None:
                                try:
                                    complete,receipt=authenticate_supplement(join,witness,tx,self.config.identity)
                                except EvidenceUnavailable as error:
                                    # Retain the actual failed input for offline
                                    # review; none of its strings are stdout or
                                    # permission to complete native coverage.
                                    failed=dict(native_witness=witness,response=tx,
                                        observed_websocket_logs=join.early_logs[(slot,sig)][0],
                                        reason=str(error),complete=False)
                                    await self.work(lambda s:install(s)._observation(None,
                                        'native_stream_log_supplement_failed',failed),2)
                                    raise
                                await self.work(lambda s:install(s)._observation(None,
                                    'native_stream_log_supplement',receipt),2)
                                frame=join.complete_deferred_log(slot,sig,complete,time.time());join_progress.set()
                                await commit(frame)
                                while True:
                                    frame=join.drain()
                                    if frame is None:break
                                    join_progress.set();await commit(frame)
                                authenticated=True
                                self.observe('log_repair',stage='supplements_authenticated')
                                return
                            if not tx or tx['slot']!=slot or tx['meta']['err'] is not None:
                                raise EvidenceUnavailable('candidate_required_content_missing')
                            await publish_log(slot,sig,tx['meta']['logMessages'])
                        finally:
                            if witness is not None and not authenticated:
                                self.observe('log_repair',stage='supplements_failed')
                            inflight.discard((slot,sig))
                    async def log_batch(keys):
                        nonlocal batch_inflight
                        fetched=False
                        try:
                            for _ in keys:self.observe('log_repair',stage='repair_logical_calls')
                            values=await self.measured_log_batch([sig for _,sig in keys],2)
                            fetched=True
                            # Each response still needs its exact current native
                            # witness and original WS prefix/suffix. Ordered frame
                            # publication remains the existing single commit queue.
                            for (slot,sig),value in zip(keys,values):await one(slot,sig,value)
                        finally:
                            if not fetched:
                                for _ in keys:self.observe('log_repair',stage='supplements_failed')
                            inflight.difference_update(keys);batch_inflight=False
                    async def block_group(keys,witness,profile):
                        from .solana_candidate_join import authenticated_block_logs
                        try:
                            try:
                                block=await self.measured_rpc('getBlock',[witness['slot'],dict(commitment='finalized',
                                    encoding='json',transactionDetails='full',rewards=False,maxSupportedTransactionVersion=1)],'rolling_recovery_missing_logs',2)
                                logs=authenticated_block_logs(block,witness,keys,profile['max_response_bytes'])
                            except (ValueError,KeyError,TypeError,EvidenceUnavailable):
                                # Same original keys, native join expiry and governor.
                                # A failed dense attempt supplies no partial authority.
                                fallback=[asyncio.create_task(one(*key)) for key in keys]
                                try:await asyncio.gather(*fallback)
                                finally:
                                    for task in fallback:
                                        if not task.done():task.cancel()
                                    await asyncio.gather(*fallback,return_exceptions=True)
                                return
                            for slot,sig in keys:await publish_log(slot,sig,logs[(slot,sig)])
                        finally:inflight.difference_update(keys)
                    pending=set()
                    try:
                        while not self.stop.is_set() and not local_stop.is_set():
                            for task in list(pending):
                                if task.done():task.result();pending.remove(task)
                            keys=[]
                            for key in join.missing_log_keys(max(join.pending,default=tip)):
                                if key in inflight:continue
                                deferred=key in join.incomplete_logs
                                if deferred:
                                    if batch_inflight or join.deferred_log_witness(*key) is None:continue
                                elif not (has_checkpoint and not fresh_rolling and key[0]<=tip):continue
                                keys.append(key)
                                if len(keys)>=max(0,8-len(inflight)):break
                            if len(inflight)>=8:keys=[]
                            profile=getattr(self.rpc,'block_repair_profile',None)
                            grouped=set()
                            # A truncated packet needs its own exact WS binding;
                            # the existing dense missing-prefix optimization is
                            # unchanged for ordinary old recovery keys.
                            ordinary=[key for key in keys if key not in join.incomplete_logs]
                            for group,witness in join.block_repair_groups(ordinary,profile,join.clock()):
                                inflight.update(group);grouped.update(group)
                                pending.add(asyncio.create_task(block_group(group,witness,profile)))
                            deferred=[key for key in keys if key in join.incomplete_logs]
                            if deferred:
                                inflight.update(deferred);batch_inflight=True
                                pending.add(asyncio.create_task(log_batch(deferred)))
                            for key in keys:
                                if key not in grouped and key not in deferred:
                                    inflight.add(key);pending.add(asyncio.create_task(one(*key)))
                            await asyncio.sleep(.01)
                    finally:
                        # An accepted HTTP result may complete the final native
                        # join. Let its original deadline finish before closing
                        # the commit queue; do not discard it on filter rebuild.
                        results=await asyncio.gather(*pending,return_exceptions=True)
                        for result in results:
                            if isinstance(result,BaseException):raise result
                tasks.append(asyncio.create_task(repair_logs()))
            consumer='pump' if not enabled('meteora') else 'candidate_live'
            if self.stop.is_set() or local_stop.is_set():return
            tasks.append(asyncio.create_task(self.stream(channel,candidate_subscription(addresses,floor,full_addresses=full),native,consumer,local_stop)))
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
        finally:
            import sys
            primary=sys.exc_info()[1];session_stop.set()
            async def teardown():
                drain_error=None
                if waiter is not None:waiter.cancel()
                try:
                    results=await settle_owned(tasks[1:],tasks[:1])
                    producer_done.set()
                    await join_owned(candidate_queue,tasks[0]);await tasks[0]
                    for result in results:
                        if isinstance(result,BaseException) and result is not primary:raise result
                except BaseException as exc:drain_error=exc
                finally:
                    producer_done.set()
                    for task in tasks:
                        if not task.done():task.cancel()
                    await asyncio.gather(*tasks,*([waiter] if waiter is not None else []),return_exceptions=True)
                    body=dict(plane=plane,session=session,**join.diagnostic(),accepted_pending=candidate_queue.count,
                        accepted_pending_bytes=candidate_queue.bytes,drained=candidate_queue.count==0 and drain_error is None)
                    self.retain_join_state(plane,session,body,candidate_queue,state='CLOSED',monotonic=time.monotonic())
                    self.diagnostic('native_join_closed',body)
                    interrupted=self.handlers.pending(session)
                    def disconnect(state):
                        h=install(state);obligations=[]
                        with state.writer.transaction():
                            gap_ids=[];gap_scopes={}
                            for row in desired:
                                lower=subscription_disconnect_lower(h,row,floor,session,fresh_rolling=fresh_rolling)
                                pending=[n for n in (body['oldest_slot'],body['early_log_min_slot']) if n is not None and n>0]
                                pending.extend(r['slot'] for r in interrupted if type(r.get('slot')) is int and r['slot']>0)
                                if pending:lower=min(lower,*pending)
                                h.gap(row['scope'],lower,None,'candidate_live_disconnect_or_filter_rebuild')
                                gap_ids.append(h.db.execute('SELECT last_insert_rowid()').fetchone()[0])
                                gap_scopes[row['scope']]=gap_ids[-1]
                                obligations.append(dict(scope=row['scope'],lower_slot=lower,upper_slot=None))
                            retained=[]
                            for item in interrupted:
                                ids=gap_ids
                                if item.get('scope_count')==1:
                                    ids=[identity for scope,identity in gap_scopes.items()
                                         if self.handlers.scope_hash((scope,))==item.get('scope_hash')]
                                recovery=dict(kind='CANDIDATE_GAPS',gap_ids=ids) if item.get('scope_count') else None
                                retained.extend(preserve_handlers(state,self.handlers,[item],recovery))
                            h._observation(None,'source_session_drain',dict(**body,replay_from_slot=floor,
                                recovery_obligations=obligations,handler_dispositions=retained,complete_history_claim=False))
                            return retained
                    try:
                        retained=await self.work(disconnect,1 if any(r['priority']<=1 for r in desired) else 3,label='source_commit')
                        self.handlers.preserved(retained)
                        if body['pending_slots'] or body['early_log_count']:
                            self.source_drain['preserved_partial_sessions']+=1
                    except BaseException as exc:
                        self.source_drain['unpreserved_sessions']+=1
                        if drain_error is None:drain_error=exc
                    self.source_drain['closed_sessions']+=1
                if primary is None and drain_error is not None:raise drain_error
            coordinator=asyncio.current_task()
            cleanup=asyncio.create_task(teardown())
            self.session_teardowns[coordinator]=cleanup
            try:await finish_owned(cleanup,self.shutdown_deadline(coordinator))
            except BaseException:
                self.source_drain.update(state='RECOVERY_REQUIRED',terminal_record_unavailable=True)
                if primary is not None and not isinstance(primary,asyncio.CancelledError):raise primary
                raise
            finally:
                if cleanup.done():
                    self.session_teardowns.pop(coordinator,None);self.session_deadlines.pop(coordinator,None)
