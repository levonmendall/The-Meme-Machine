"""Read-only rolling pre-warm driver. No broad Pump/PumpSwap body stream.

Universal account scouts retain identities; first sight installs pre-warm interests.
Archive pagination repairs gaps. Body-free Pump/PumpSwap logs are joined to
independent native signature/index witnesses. Only selected Meteora candidates
receive rich native bodies. A linked finality stream is acquired once for control.
"""
import asyncio
import base64
import hashlib
import json
import time
import uuid
import grpc
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from .solana_activity_routes import ActivityRoutes,shards
from .solana_candidate_join import CandidateTransactionJoin,candidate_subscription
from .solana_native_evidence import economic_transaction,pubkey,signature
from .solana_evidence_plane import EvidenceUnavailable,IntervalProof,digest,canonical
from .solana_evidence_transport import Subscription
from .solana_selective_history import SelectiveHistory,FAMILIES,PROGRAMS,coverage_scope,economic_records
from .solana_selective_runtime import CONTROL
from .solana_source_intake import candidate_log_message
from .yellowstone import geyser_pb2 as pb
from .runtime.operating_families import enabled,active_sql,active_scope_sql,operational

HOST='solana-mainnet.streaming.alchemy.com:443'
MAX_FRAME_BYTES=16*1024*1024
# 47 status filters + one scoped Meteora content filter + metadata + finality
# remain within the demonstrated 50-filter limit across request maps.
MAX_LIVE_CANDIDATES=48 # StableShards subtracts the one Meteora content filter.
ARCHIVE_WORKERS=8
SCOUT_COMMIT_BATCH=64
# This integration candidate must never silently activate an unproved source.
# These are implementation/validation gaps, not owner-approval requirements.
PRODUCTION_BLOCKERS=(
    'combined_position_and_candidate_provider_latency_not_certified',
)

def require_certified():
    if PRODUCTION_BLOCKERS:raise EvidenceUnavailable('solana_candidate_topology_not_certified')
REPLAY_SLOTS=6000
CONTROL_OVERLAP=256
WARM_OVERLAP=32
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
    request.accounts_data_slice.add(offset=0,length=56)
    return request

def commit_scout(state,update,seen):
    history=install(state);item=update.account;account=item.account
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
        history.observe('pump',address,slot=item.slot,signature=sig,fields=fields,seen=seen)
    elif labels and labels.issubset({'m','n'}):
        if pubkey(account.owner)!=PROGRAMS['meteora']:raise EvidenceUnavailable('candidate_scout_owner')
        if labels=={'m','n'}:return # Existing WSOL policy is XOR, not an OR pair.
        history.observe('meteora',address,slot=item.slot,signature=sig,
            fields=dict(wsol_pair_locator=True,economic_event=False,history_complete=False,activity=activity),seen=seen)
    elif labels=={'a'}:
        if len(raw)!=56 or pubkey(account.owner)!=PROGRAMS['meteora']:raise EvidenceUnavailable('candidate_scout_fields_missing')
        # A bin-array account header is a wakeup only. It cannot replace swaps,
        # exact bins, balances, instructions or economic interval completeness.
        history.observe('meteora',pubkey(raw[24:56]),slot=item.slot,signature=sig,
            fields=dict(bin_array_locator=address,economic_event=False,history_complete=False,activity=activity),seen=seen)
    else:raise EvidenceUnavailable('candidate_scout_filter')

def block_message(frame):
    b=frame.update.block
    return dict(method='blockNotification',params=dict(result=dict(value=dict(slot=b.slot,err=None,
        block=dict(parentSlot=b.parent_slot,blockhash=b.blockhash,previousBlockhash=b.parent_blockhash,
                   blockTime=b.block_time.timestamp,transactions=[])))))

def commit_control(state,frame,*,active=True):
    install(state);b=frame.update.block;seen=frame.seen
    prepared=dict(endpoint_identity=state.fence.endpoint_identity,observed_at=seen,
                  slot=b.slot,signatures=[],batches=[],deliveries=[])
    with state.writer.source_frame():
        state.fence.block(Subscription('source',CONTROL,'control','census',2),block_message(frame),seen,prepared=prepared)
        state.writer._count('stream_accepted_messages')
        state.fence._health('phase','ACTIVE' if active else 'DEGRADED');state.fence._health('heartbeat',seen)
        # Source coordinates inform bounded storage maintenance, never global
        # economic completeness. Candidate proofs live in a separate namespace.
        for scope in (FAMILIES[f] for f in install(state).active_families):
            state.fence._health('finalized_frontier:'+scope,dict(slot=b.slot,time=b.block_time.timestamp,seen=seen))

def skipped_prefix(history,scope,frame):
    """A finalized parent below the replay floor proves skipped slots only."""
    b=frame.update.block;lo=frame.replay_from_slot
    if not (0<lo<b.slot and b.parent_slot<lo):return
    witness=dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=b.slot-1,
        lineage_hash=digest([lo,b.slot,b.parent_slot,b.blockhash,b.parent_blockhash]),
        method='native_finalized_parent_proves_no_block_in_replay_prefix',native_order=True)
    history.lifecycle.defer_proof(IntervalProof(scope,lo,b.slot-1,'alchemy_finalized_stream',history.endpoint_identity,witness,frame.seen))

def commit_candidates(state,frame,addresses,session,*,publish=True):
    history=install(state);b=frame.update.block;seen=frame.seen
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
        history.ingest(rows.values())
        for scope,census in censuses.items():
            old=state.writer.db.execute('SELECT slot,parent,hash,previous_hash,market_time,seen,session,census_hash FROM candidate_blocks WHERE scope=?',(scope,)).fetchone()
            values=(b.slot,b.parent_slot,b.blockhash,b.parent_blockhash,b.block_time.timestamp,seen,session,digest(census))
            if old and b.slot<=old[0]:
                if b.slot==old[0] and (old[1:5],old[7])!=(values[1:5],values[7]):raise EvidenceUnavailable('candidate_replay_receipt_conflict')
                if b.slot==old[0] and old[6]!=session:
                    # An exact replayed boundary can join this session's child.
                    # Preserve original receipt time and immutable economics.
                    state.writer.db.execute('UPDATE candidate_blocks SET session=? WHERE scope=?',(session,scope))
                continue
            if old is None:skipped_prefix(history,scope,frame)
            if old and old[6]==session:
                witness=dict(finalized=True,complete=True,scope=scope,lower_slot=old[0],upper_slot=b.slot-1,
                    lineage_hash=digest([scope,list(old),list(values)]),
                    method='candidate_filtered_native_status_and_verified_content_with_linked_child',
                    native_order=True,transaction_bodies_only_for_meteora=True)
                history.lifecycle.defer_proof(IntervalProof(scope,old[0],b.slot-1,'alchemy_finalized_stream',history.endpoint_identity,witness,seen))
            state.writer.db.execute('INSERT OR REPLACE INTO candidate_blocks VALUES(?,?,?,?,?,?,?,?,?)',(scope,*values))
    if publish:history.lifecycle.publish()

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
    chosen=desired
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
                if str(exc) not in ('evidence_background_yield','evidence_control_overloaded') or stop.is_set():raise
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

    def observe(self,kind,**values):
        identity=values.get('stream_id');family=values.get('family','shared')
        if kind=='subscribe':
            self.native_streams[identity]=dict(consumer=family,delivering=False)
            self.native_attempts[family]=self.native_attempts.get(family,0)+1
            self.native_peak=max(self.native_peak,len(self.native_streams));self.native_revision+=1
        elif kind=='delivery' and identity in self.native_streams and not self.native_streams[identity]['delivering']:
            self.native_streams[identity]['delivering']=True;self.native_revision+=1
        elif kind=='native_error':
            key=family+':'+values['status'];self.native_errors[key]=self.native_errors.get(key,0)+1
            self.native_revision+=1
        elif kind=='unsubscribe':
            self.native_streams.pop(identity,None);self.native_revision+=1
        if self.observer is not None:self.observer(kind,values)

    def stream_telemetry(self):
        # A client-open stream is not independently certified provider admission.
        # First physical delivery is distinguished from subscription attempts.
        families=set(self.native_attempts)|{r['consumer'] for r in self.native_streams.values()}
        return dict(client_open_streams=len(self.native_streams),peak_client_streams=self.native_peak,
            delivering_streams=sum(r['delivering'] for r in self.native_streams.values()),
            by_consumer={f:dict(attempts=self.native_attempts.get(f,0),
                client_open=sum(r['consumer']==f for r in self.native_streams.values()),
                delivering=sum(r['consumer']==f and r['delivering'] for r in self.native_streams.values()))
                for f in sorted(families)},errors=dict(self.native_errors),
            provider_quota_verified=False)

    async def delivered(self,family,transport,size,seen,priority=2):
        if not self.batched:
            await self.work(lambda s:install(s).delivery(family,transport,raw_bytes=size,seen=seen),priority)
            return
        key=(int(seen)//86400,family,transport)
        total,first=self.pending_delivery.get(key,(0,seen))
        self.pending_delivery[key]=(total+size,first)

    async def flush_delivery(self):
        async with self.delivery_lock:
            pending=dict(self.pending_delivery)
            if not pending:return
            def commit(state):
                h=install(state)
                with state.writer.transaction():
                    for (_,family,transport),(size,seen) in pending.items():
                        h.delivery(family,transport,raw_bytes=size,seen=seen)
            await self.work(commit,2)
            for key,(size,seen) in pending.items():
                remaining=self.pending_delivery[key][0]-size
                if remaining:self.pending_delivery[key]=(remaining,self.pending_delivery[key][1])
                else:del self.pending_delivery[key]

    async def publish_history(self):
        try:
            while not self.stop.is_set():
                await self.flush_delivery()
                revision=self.native_revision;native=self.stream_telemetry()
                ready=time.monotonic();timing={}
                def publish(s):
                    timing['owner_claim_monotonic']=time.monotonic()
                    if revision!=self.native_published:s.fence._health('native_streams',native)
                    h=install(s);timing['publication_started_monotonic']=time.monotonic()
                    h.lifecycle.publish()
                    timing['publication_finished_monotonic']=time.monotonic()
                    timing['publication_finished_wall']=time.time()
                    return h.startup.advance()
                await self.work(publish,2,label='source_commit')
                self.observe('publication_timing',work_ready_monotonic=ready,
                    work_returned_monotonic=time.monotonic(),**timing)
                self.native_published=revision
                await asyncio.sleep(.1)
        finally:await self.flush_delivery()

    async def control_commits(self,queue):
        while not self.stop.is_set():
            first=await queue.get();batch=[first]
            # The same eight-frame durable batch bound as the shared service.
            await asyncio.sleep(.01)
            while len(batch)<8:
                try:batch.append(queue.get_nowait())
                except asyncio.QueueEmpty:break
            def commit(state):
                with state.writer.transaction():
                    for frame in batch:commit_control(state,frame,active=self.control_connected)
            await self.work(commit,2,label='source_commit')
            for _ in batch:queue.task_done()

    async def control_stream(self,channel,tip,queue):
        retry=0
        while not self.stop.is_set():
            checkpoint=await self.work(lambda s:s.writer.db.execute(
                'SELECT MAX(hi) FROM coverage WHERE scope=?',(CONTROL,)).fetchone()[0],2)
            floor=max(1,(tip if checkpoint is None else checkpoint)-CONTROL_OVERLAP)
            req=pb.SubscribeRequest(commitment=pb.FINALIZED,from_slot=floor)
            req.blocks_meta['b'].SetInParent();req.slots['f'].filter_by_commitment=True
            join=CandidateTransactionJoin({},set(),filtered_from_slot=floor)
            async def control(update,size,seen):
                self.control_connected=True
                frame=join.feed(update,size,seen)
                if frame:await queue.put(frame)
            try:
                await self.stream(channel,req,control,'shared');return
            except EvidenceUnavailable as exc:
                if str(exc) not in ('candidate_native_eof','candidate_native_unavailable','candidate_native_internal','candidate_native_deadline_exceeded','candidate_native_cancelled','candidate_native_resource_exhausted'):raise
                self.control_connected=False
                retry+=1
                def disconnected(state):
                    h=install(state)
                    state.fence._health('phase','DEGRADED')
                    h._observation(None,'control_reconnect',dict(reason=str(exc),attempt=retry,checkpoint=checkpoint))
                await self.work(disconnected,0)
                await queue.join()
                await asyncio.sleep(min(8,.5*2**min(retry-1,4)))
    async def measured_rpc(self,method,params,family,priority=4):
        from .runtime.operating_families import require_active
        require_active(family)
        for attempt in range(3):
            try:result,receipt=await asyncio.to_thread(self.rpc.call_delivered,method,params,priority)
            except ValueError as exc:
                receipt=getattr(exc,'receipt',None)
                if receipt is not None:
                    await self.work(lambda s:install(s).delivery(family,'rpc',raw_bytes=receipt['bytes'],
                        rpc_cu=receipt['cu'],calls=1),priority)
                if not getattr(exc,'retryable',False) or attempt==2:raise
                await self.work(lambda s:install(s)._observation(None,'rpc_retry',dict(method=method,
                    family=family,attempt=attempt+1,deadline_reset=False,cause_kind=getattr(exc,'cause_kind',None))),priority)
                await asyncio.sleep(.2*(attempt+1));continue
            await self.work(lambda s:install(s).delivery(family,'rpc',raw_bytes=receipt['bytes'],
                rpc_cu=receipt['cu'],calls=1),priority)
            return result
    async def stream(self,channel,request,handler,family,local_stop=None):
        from .runtime.operating_families import require_active
        require_active(family)
        stream_id=uuid.uuid4().hex
        self.observe('subscribe',stream_id=stream_id,family=family,request=request)
        call=channel.stream_stream('/geyser.Geyser/Subscribe',request_serializer=lambda r:r.SerializeToString(),
            response_deserializer=lambda r:r)(metadata=(('x-token',self.token),))
        pending=None;phase='subscription_write'
        try:
            # Subscription establishment can fail with the same native status
            # as a subsequent read. It must enter identical scoped retry/gap
            # handling rather than escape as an unclassified transport error.
            await call.write(request)
            phase='stream_read'
            while not self.stop.is_set() and not (local_stop and local_stop.is_set()):
                if pending is None:pending=asyncio.create_task(call.read())
                try:raw=await asyncio.wait_for(asyncio.shield(pending),1)
                except TimeoutError:continue
                pending=None
                if raw is grpc.aio.EOF:raise EvidenceUnavailable('candidate_native_eof')
                if len(raw)>MAX_FRAME_BYTES:raise EvidenceUnavailable('candidate_native_frame_bound')
                at=time.time();received=time.monotonic()
                self.observe('delivery',stream_id=stream_id,family=family,transport='yellowstone',raw=raw,seen=at,received_monotonic=received)
                # Delivery counts before parsing, routing, filtering or dedup.
                await self.delivered(family,'yellowstone',len(raw),at)
                decode_started=time.monotonic()
                update=pb.SubscribeUpdate.FromString(raw);kind=update.WhichOneof('update_oneof')
                self.observe('decode_timing',stream_id=stream_id,family=family,transport='yellowstone',bytes=len(raw),seconds=time.monotonic()-decode_started)
                if kind=='ping':await call.write(pb.SubscribeRequest(ping=pb.SubscribeRequestPing(id=1)));continue
                if kind=='pong':continue
                await handler(update,len(raw),at)
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
            call.cancel()
            self.observe('unsubscribe',stream_id=stream_id,family=family)

    async def scout_stream(self,channel,tip,handler):
        """Retry transport failure with the original overlapping scout boundary.

        Account locators grant neither economic coverage nor entry authority.
        Retrying never advances a canonical or CandidateHistory checkpoint.
        """
        retry=0
        while not self.stop.is_set():
            request=scout_request();request.from_slot=max(1,tip-CONTROL_OVERLAP)
            try:
                await self.stream(channel,request,handler,'pump' if not enabled('meteora') else 'discovery');return
            except EvidenceUnavailable as exc:
                if str(exc) not in ('candidate_native_eof','candidate_native_unavailable','candidate_native_internal','candidate_native_deadline_exceeded','candidate_native_cancelled','candidate_native_resource_exhausted'):raise
                retry+=1
                def record(state):
                    h=install(state)
                    h._observation(None,'scout_reconnect',dict(reason=str(exc),attempt=retry,
                        from_slot=request.from_slot,economic_coverage_claim=False,checkpoint_advanced=False))
                await self.work(record,1)
                await asyncio.sleep(min(8,.5*2**min(retry-1,4)))

    async def __call__(self,work,stop):
        require_certified()
        return await self.run(work,stop)

    async def run(self,work,stop):
        """The production read-only driver; also used by bounded certification.

        The supported service still applies require_certified before entering.
        This method neither starts a PAPER lifecycle nor grants entry authority.
        """
        work=source_work(work,stop,self.observe)
        self.work=work;self.stop=stop;self.batched=True
        def boot(state):
            h=install(state);h.startup.begin();return str(state.writer.path)
        self.canonical_path=await work(boot,0)
        tip=await self.measured_rpc('getSlot',[dict(commitment='finalized')],'shared',2)
        async with grpc.aio.secure_channel(HOST,grpc.ssl_channel_credentials(),options=[
                ('grpc.max_receive_message_length',MAX_FRAME_BYTES),('grpc.max_send_message_length',4*1024*1024),('grpc.http2.bdp_probe',0)]) as channel:
            control_queue=asyncio.Queue(maxsize=64)
            async def scouts(update,size,seen):
                if update.WhichOneof('update_oneof')!='account':raise EvidenceUnavailable('candidate_scout_filter')
                await work(lambda s:commit_scout(s,update,seen),5,label='source_commit')
            census=asyncio.create_task(self.structural_census()) if enabled('meteora') else None
            stop_task=asyncio.create_task(stop.wait())
            tasks=[asyncio.create_task(self.control_stream(channel,tip,control_queue)),
                   asyncio.create_task(self.scout_stream(channel,tip,scouts)),
                   asyncio.create_task(self.acquire_pool()),asyncio.create_task(self.live_manager(channel)),
                   asyncio.create_task(self.rolling_programs(channel)),
                   asyncio.create_task(self.cold_maintenance()),
                   asyncio.create_task(self.publish_history()),
                   asyncio.create_task(self.control_commits(control_queue)),
                   stop_task]
            if census is not None:tasks.append(census)
            if not operational():tasks.append(asyncio.create_task(self.activity_manager(channel)))
            try:
                remaining=set(tasks)
                while not stop.is_set():
                    done,_=await asyncio.wait(remaining,return_when=asyncio.FIRST_COMPLETED)
                    if stop.is_set():return
                    for task in done:
                        task.result()
                        if task is stop_task:return
                        if task is census:
                            # The startup structural census is finite. Completing
                            # it must not terminate discovery/positions/recovery.
                            remaining.remove(task)
                        else:raise EvidenceUnavailable('candidate_source_task_stopped')
            except Exception as exc:
                # The owner records a Model B defect before shutdown. There is
                # no archived startup producer to fall back to.
                await work(lambda s:install(s).startup.fail(type(exc).__name__),0)
                raise
            finally:
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)

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
                        for task in running:task.cancel()
                        await asyncio.gather(*running,return_exceptions=True)
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
            for task in running:task.cancel()
            await asyncio.gather(*running,return_exceptions=True)

    async def rolling_programs(self,channel):
        """Fixed body-free filters, independent of candidate count or promotion.

        WS carries logs only; native status supplies identity/order, metadata and
        linked finality seal intervals. A restart requests an explicit overlapping
        gap, never falsely completes an unseen past.
        """
        from .solana_rolling_history import program_scope
        while not self.stop.is_set():
            def rows(state):
                h=install(state)
                return [dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,
                    deadline=h.clock()+120,lower_slot=0,rolling=True) for f in ('pump','pumpswap')]
            desired=await self.work(rows,6)
            try:await self.live(channel,desired,self.stop)
            except (EvidenceUnavailable,ConnectionClosed,OSError) as exc:
                reason=str(exc) if isinstance(exc,EvidenceUnavailable) else type(exc).__name__
                self.observe('rolling_retry',reason=reason)
                await self.work(lambda state:install(state)._observation(None,'rolling_retry',dict(reason=reason,complete=False)),1)
                await asyncio.sleep(.5)

    async def cold_maintenance(self):
        from .solana_scoped_retirement import ScopedRetirement
        # Retirement is not a prerequisite for initial evidence convergence.
        # Keep its telemetry and disk work out of the startup release barrier.
        await self.wait_startup()
        while not self.stop.is_set():
            def retire(state):
                h=install(state);h.lifecycle.publish()
                return ScopedRetirement(h).retire(limit=64)
            # The owner installs its existing urgent SQL interruption hook for
            # maintenance priority four. Interrupted slices retry durably.
            await self.work(retire,4,label='retention')
            await asyncio.sleep(1)

    async def acquire_pool(self):
        tasks=[asyncio.create_task(self.acquire()) for _ in range(ARCHIVE_WORKERS)]
        try:await asyncio.gather(*tasks)
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)

    async def acquire(self):
        while not self.stop.is_set():
            def request_development(state):
                from .lanes.pump.pump_acceleration_strategy import POLICY
                h=install(state);db=state.writer.db
                if not hasattr(state,'acquisition_inflight'):state.acquisition_inflight=set()
                if not h.startup.snapshot().get('released'):return None
                frontier=db.execute('SELECT MAX(hi) FROM coverage WHERE scope=?',(CONTROL,)).fetchone()[0]
                if frontier is not None:
                    for addr,fields in db.execute('''SELECT address,fields FROM market_observations m WHERE family='pump'
                        AND NOT EXISTS(SELECT 1 FROM evidence_bindings b WHERE b.family=m.family AND b.address=m.address)'''):
                        value=json.loads(fields);upper=value.get('development_upper_bps')
                        if value.get('complete') or upper is None or upper>=POLICY.min_curve_progress_bps:
                            h.bind('pump',addr)
                            first=db.execute("SELECT first_seen FROM candidate_lifecycle WHERE family='pump' AND address=?",(addr,)).fetchone()[0]
                            h.rolling.prepare('pump',addr,0,frontier,priority=3,deadline=first+150)
                    for family,addr,lo in db.execute("SELECT family,address,lower_slot FROM candidate_lifecycle WHERE "+active_sql('family',solana=True)+" AND state='reactivated'").fetchall():
                        from .solana_scoped_retirement import ScopedRetirement
                        ScopedRetirement(h).restore(family,addr)
                        epoch=db.execute('SELECT epoch FROM candidate_lifecycle WHERE family=? AND address=?',(family,addr)).fetchone()[0]
                        first=db.execute("SELECT MIN(json_extract(body,'$.seen')) FROM candidate_history_outbox WHERE family=? AND address=? AND kind='reactivated' AND json_extract(body,'$.epoch')=?",(family,addr,epoch)).fetchone()[0]
                        deadline=(time.time() if first is None else first)+150
                        if deadline<=time.time():
                            h._observation(None,'promotion_deadline_missed',dict(family=family,address=addr,deadline=deadline,deadline_reset=False))
                            h.lifecycle.demote(family,addr,reason='original_promotion_deadline_expired');continue
                        h.lifecycle.promote(family,addr,deadline=deadline,lower_slot=0 if family=='pump' else None if family=='meteora' else lo)
                    h.rolling.resume_boundaries()
                    h.rolling.resume_publication()
                h.lifecycle.publish()
                h.rolling.repair_required_checkpoint_prefixes()
                result=h.plan(excluding=tuple(state.acquisition_inflight))
                if result:
                    state.acquisition_inflight.add(result[0]['id'])
                    result[0]['finalized_hint']=frontier
                return result
            plan=await self.work(request_development,4)
            if not plan:await asyncio.sleep(.1);continue
            job,config=plan
            def commit(state):
                h=install(state)
                if job['family']=='pump':
                    from .solana_program_decoders import pump_events
                    for tx in value['data']:
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
                result=h.commit_page(job,value,finalized_through=finalized)
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
                requested=self.read_revision()
                self.observe('membership_requested',revision=requested)
                if requested!=revision:
                    def plan(state):
                        rows=plan_live(state)
                        return state.writer.db.execute('SELECT revision FROM prewarm_membership_revision WHERE id=1').fetchone()[0],rows
                    revision,desired=await self.work(plan,2)
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
                        local_stop.set();task.cancel();await asyncio.gather(task,return_exceptions=True)
                        del running[number]
                for number,group in groups.items():
                    if number in running or time.monotonic()<retry_at.get(number,0):continue
                    local_stop=asyncio.Event()
                    self.observe('membership_install',group=number,identity=group['identity'])
                    running[number]=(group['identity'],local_stop,asyncio.create_task(self.live(channel,group['rows'],local_stop)))
                await asyncio.sleep(.25)
        finally:
            for _,local_stop,task in running.values():local_stop.set();task.cancel()
            await asyncio.gather(*(task for _,_,task in running.values()),return_exceptions=True)

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

    async def live(self,channel,desired,local_stop):
        rolling=any(r.get('rolling') for r in desired);has_checkpoint=False
        tip=await self.measured_rpc('getSlot',[dict(commitment='finalized')],'shared',2)
        def replay_floor(state):
            nonlocal has_checkpoint
            h=install(state);points=[]
            for row in desired:
                scopes=h.rolling.scopes(row['family'],row['scope'])
                value=state.writer.db.execute('SELECT MAX(slot) FROM candidate_checkpoints WHERE scope IN ('+
                    ','.join('?' for _ in scopes)+')',scopes).fetchone()[0]
                if value is not None:points.append(value)
            earliest=min(points,default=tip)
            has_checkpoint=bool(points)
            if rolling and points:return max(1,earliest-1)
            if any(r.get('rolling') for r in desired) and not points:return tip+1
            if all(r['family']=='meteora' for r in desired) and not points:
                # First-sight accumulation starts here. The scout's old locator
                # is not an obligation to reconstruct its entire past. Promotion
                # and positions request exact checkpoint/lookback gaps separately.
                return tip+1
            return max(1,min(tip-WARM_OVERLAP,earliest-WARM_OVERLAP)) if tip-earliest<REPLAY_SLOTS else max(1,tip-WARM_OVERLAP)
        floor=await self.work(replay_floor,1 if any(r['priority']<=1 for r in desired) else 3)
        addresses={r['address']:r['scope'] for r in desired}
        full={r['address'] for r in desired if r['family']=='meteora'}
        # A fresh HTTP tip can be ahead of the finalized WS delivery frontier.
        # Buffer the startup log prefix until both subscribed programs deliver
        # their first real finalized slot. Coverage starts on the following
        # slot; the partially subscribed first slot is never called complete.
        fresh_rolling=rolling and not has_checkpoint
        join=CandidateTransactionJoin(addresses,full,filtered_from_slot=1 if fresh_rolling else floor,max_join_seconds=120 if rolling else 10);session=uuid.uuid4().hex
        log_frontiers={};logs_available=asyncio.Event()
        native_announced=False
        async def commit(frame):
            nonlocal native_announced
            grouped=all(r['family']=='meteora' and r['priority']>1 for r in desired)
            if frame:
                ready=time.monotonic();ready_wall=time.time();claimed=[];finished_wall=[]
                def durable(state):
                    claimed.append(time.monotonic())
                    (commit_rolling_group if grouped else commit_candidates)(state,frame,addresses,session,publish=not self.batched)
                    if rolling and not native_announced:install(state).startup.native([r['family'] for r in desired])
                    claimed.append(time.monotonic())
                    finished_wall.append(time.time())
                await self.work(durable,0 if any(r['priority']<=1 for r in desired) else 2,label='source_commit')
                self.observe('evidence_timing',session=session,slot=frame.update.block.slot,
                    native_last_receipt_wall=frame.seen,
                    economic_available_wall=max((r[4] for r in frame.candidate_statuses),default=frame.seen),
                    join_ready_wall=ready_wall,durable_finished_wall=finished_wall[-1],
                    join_ready_monotonic=ready,owner_claim_monotonic=claimed[-2],
                    durable_finished_monotonic=claimed[-1],work_returned_monotonic=time.monotonic(),
                    published_inline=not self.batched)
                if rolling:native_announced=True
        acknowledged=asyncio.Event()
        async def native(update,size,seen):
            try:
                frame=join.feed(update,size,seen)
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
                await self.work(lambda s:install(s)._observation(None,'join_failure',diagnostic),1)
                raise
        async def logs():
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
                    raw=await ws.recv();seen=time.time();received=time.monotonic();size=len(raw.encode() if isinstance(raw,str) else raw)
                    self.observe('delivery',stream_id=ws_id,family='candidate_logs',transport='websocket',raw=raw.encode() if isinstance(raw,str) else raw,seen=seen,received_monotonic=received)
                    decode_started=time.monotonic();value=candidate_log_message(raw,max_bytes=MAX_FRAME_BYTES)
                    self.observe('decode_timing',stream_id=ws_id,family='candidate_logs',transport='websocket',bytes=size,seconds=time.monotonic()-decode_started)
                    await self.delivered('candidate_logs','websocket',size,seen,0 if 'id' in value else (0 if any(r['priority']<=1 for r in desired) else 2))
                    if 'id' in value:
                        if 'error' in value or value['id'] not in pending:raise EvidenceUnavailable('authoritative_subscription_rejected')
                        registered[value['result']]=pending.pop(value['id'])
                        if not pending:acknowledged.set()
                        continue
                    result=value['params']['result'];row=registered.get(value['params']['subscription'])
                    if row is None:raise EvidenceUnavailable('unknown_source_subscription')
                    v=result['value']
                    if fresh_rolling:
                        log_frontiers.setdefault(row['family'],result['context']['slot'])
                        if len(log_frontiers)==len({r['family'] for r in desired}):logs_available.set()
                    if v['err'] is None:await commit(join.feed_log(result['context']['slot'],v['signature'],v['logs'],None,seen))
        tasks=[];waiter=None
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
                raise EvidenceUnavailable('candidate_websocket_ack_timeout')
            tip=await self.measured_rpc('getSlot',[dict(commitment='finalized')],'replay',1)
            if rolling and not has_checkpoint:
                try:await asyncio.wait_for(logs_available.wait(),8)
                except TimeoutError:raise EvidenceUnavailable('rolling_delivery_frontier_unavailable') from None
                floor=max(log_frontiers.values())+1
                buffered=tuple(join.early_logs.items())
                join=CandidateTransactionJoin(addresses,full,filtered_from_slot=floor,max_join_seconds=120)
                for (slot,sig),(content,error,seen) in buffered:join.feed_log(slot,sig,content,error,seen)
            def warm(state):
                from .solana_scoped_retirement import ScopedRetirement
                h=install(state);cold=ScopedRetirement(h)
                if rolling:
                    for row in desired:h.startup.feed_ack(row['family'],floor,max(floor,tip))
                for row in desired:cold.restore(row['family'],row['address'])
                # A subscription ACK supplies an upper fence for this handoff
                # only. It cannot close another shard's outstanding disconnect.
                scopes=tuple({row['scope'] for row in desired})
                state.writer.db.execute('UPDATE candidate_gaps SET hi=? WHERE hi IS NULL AND lo<=? AND scope IN ('+
                    ','.join('?' for _ in scopes)+')',(tip,tip,*scopes))
                # The native feed will replay full Meteora deltas from floor.
                # Before its durable publication, missing rows are convergence,
                # not evidence of a provider/history gap. Required checkpoint
                # prefixes are handled only once a real retained floor proves
                # that native rolling coverage cannot supply them.
                recovery=[r for r in desired if not r.get('rolling') and r['family']!='meteora' and r['priority']<5]
                h.lifecycle.repair(recovery,tip);h.lifecycle.publish()
            await self.work(warm,1 if any(r['priority']<=1 for r in desired) else 3)
            # The native replay supplies independent identity/order witnesses;
            # RPC supplies only the old log content unavailable from WS ACKs.
            for row in sorted(desired,key=lambda r:r['priority']):
                if row['family']=='meteora' or row.get('rolling') or floor>tip:continue
                token=None
                while True:
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
            if rolling and has_checkpoint:
                async def repair_logs():
                    # Independent native identities determine the exact missing
                    # field. This exception fetches bodies only for the recovery
                    # prefix unavailable from a new WS, never every promotion.
                    inflight=set()
                    async def one(slot,sig):
                        try:
                            tx=await self.measured_rpc('getTransaction',[sig,dict(commitment='finalized',encoding='json',maxSupportedTransactionVersion=1)],'rolling_recovery_missing_logs',2)
                            if not tx or tx['slot']!=slot or tx['meta']['err'] is not None:
                                raise EvidenceUnavailable('candidate_required_content_missing')
                            await self.work(lambda s:install(s)._observation(None,'selective_missing_field',dict(signature=sig,slot=slot,field='logMessages',reason='RECOVERY_GAP')),2)
                            await commit(join.feed_log(slot,sig,tx['meta']['logMessages'],None,time.time()))
                            while True:
                                frame=join.drain()
                                if frame is None:break
                                await commit(frame)
                        finally:inflight.discard((slot,sig))
                    pending=set()
                    try:
                        while not self.stop.is_set() and not local_stop.is_set():
                            for task in list(pending):
                                if task.done():task.result();pending.remove(task)
                            for key in join.missing_log_keys(tip):
                                if len(pending)>=8:break
                                if key not in inflight:
                                    inflight.add(key);pending.add(asyncio.create_task(one(*key)))
                            await asyncio.sleep(.01)
                    finally:
                        for task in pending:task.cancel()
                        await asyncio.gather(*pending,return_exceptions=True)
                tasks.append(asyncio.create_task(repair_logs()))
            consumer='pump' if not enabled('meteora') else 'candidate_live'
            tasks.append(asyncio.create_task(self.stream(channel,candidate_subscription(addresses,floor,full_addresses=full),native,consumer,local_stop)))
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
        finally:
            if waiter is not None:waiter.cancel()
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,*([waiter] if waiter is not None else []),return_exceptions=True)
            def disconnect(state):
                h=install(state)
                for row in desired:
                    checkpoint=state.writer.db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',(row['scope'],)).fetchone()
                    h.gap(row['scope'],floor if checkpoint is None else checkpoint[0]+1,None,
                        'candidate_live_disconnect_or_filter_rebuild')
            await self.work(disconnect,1 if any(r['priority']<=1 for r in desired) else 3)
