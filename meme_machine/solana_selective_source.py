"""Read-only hybrid provider driver. No program-wide bodies or log subscription.

Universal account scouts retain identities; candidate activity wakes a conservative
superset. Archive pagination proves gaps. Live Pump/PumpSwap logs are joined to
independent native signature/index witnesses. Only selected Meteora candidates
receive rich native bodies. A linked finality stream is acquired once for control.
"""
import asyncio
import hashlib
import json
import time
import uuid
import grpc
from websockets.asyncio.client import connect
from .solana_activity_routes import ActivityRoutes,shards
from .solana_candidate_join import CandidateTransactionJoin,candidate_subscription
from .solana_native_evidence import economic_transaction,pubkey,signature
from .solana_evidence_plane import EvidenceUnavailable,IntervalProof,digest,canonical
from .solana_evidence_transport import Subscription
from .solana_selective_history import SelectiveHistory,FAMILIES,PROGRAMS,coverage_scope,economic_records
from .solana_selective_runtime import CONTROL
from .yellowstone import geyser_pb2 as pb

HOST='solana-mainnet.streaming.alchemy.com:443'
MAX_FRAME_BYTES=16*1024*1024
MAX_LIVE_CANDIDATES=48
# This integration candidate must never silently activate an unproved source.
# These are implementation/validation gaps, not owner-approval requirements.
PRODUCTION_BLOCKERS=(
    'meteora_structural_scout_to_strategy_promotion_not_integrated',
    'candidate_activity_reactivation_not_integrated',
    'selective_cold_cache_retirement_not_integrated',
    'combined_position_and_candidate_provider_latency_not_certified',
    'websocket_ack_to_native_replay_handoff_not_certified',
    'candidate_restart_gap_repair_not_integrated',
    'positive_meteora_opportunity_warming_parity_not_demonstrated',
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
'''

def install(state):
    if not hasattr(state,'selective'):
        state.selective=SelectiveHistory(state.writer,state.fence.endpoint_identity)
        state.writer.db.executescript(STATE_SCHEMA)
        state.fence.selective=state.selective
        state.fence.health('topology','candidate_hybrid_v1')
    return state.selective

def scout_request():
    request=pb.SubscribeRequest(commitment=pb.FINALIZED)
    for label,program,kind in [('p',PROGRAMS['pump'],'BondingCurve'),
                              ('m',PROGRAMS['meteora'],'LbPair'),('n',PROGRAMS['meteora'],'LbPair'),
                              ('a',PROGRAMS['meteora'],'BinArray')]:
        f=request.accounts[label];f.owner.append(program)
        f.filters.add().memcmp.CopyFrom(pb.SubscribeRequestFilterAccountsFilterMemcmp(
            offset=0,bytes=hashlib.sha256(('account:'+kind).encode()).digest()[:8]))
    from . import pump
    from .postgrad import WSOL
    for label,offset in [('m',88),('n',120)]:
        request.accounts[label].filters.add().memcmp.CopyFrom(pb.SubscribeRequestFilterAccountsFilterMemcmp(offset=offset,bytes=pump.un58(WSOL)))
    request.accounts_data_slice.add(offset=0,length=56)
    return request

def commit_scout(state,update,seen):
    history=install(state);item=update.account;account=item.account
    labels=set(update.filters);raw=account.data;address=pubkey(account.pubkey)
    if len(raw)<49:raise EvidenceUnavailable('candidate_scout_fields_missing')
    sig=signature(account.txn_signature) if account.HasField('txn_signature') else ''
    if labels=={'p'}:
        if pubkey(account.owner)!=PROGRAMS['pump']:raise EvidenceUnavailable('candidate_scout_owner')
        reserve=int.from_bytes(raw[24:32],'little');supply=int.from_bytes(raw[40:48],'little')
        fields=dict(real_token_reserves=reserve,total_supply=supply,complete=bool(raw[48]),
            # This upper bound can promote too early, never reject an actually
            # qualifying curve. Exact initial reserves are hydrated before entry.
            development_upper_bps=None if not 0<=reserve<=supply or supply==0 else 10000*(supply-reserve)//supply,
            economic_event=False,history_complete=False)
        history.observe('pump',address,slot=item.slot,signature=sig,fields=fields,seen=seen)
    elif labels and labels.issubset({'m','n'}):
        if pubkey(account.owner)!=PROGRAMS['meteora']:raise EvidenceUnavailable('candidate_scout_owner')
        history.observe('meteora',address,slot=item.slot,signature=sig,
            fields=dict(wsol_pair_locator=True,economic_event=False,history_complete=False),seen=seen)
    elif labels=={'a'}:
        if len(raw)!=56 or pubkey(account.owner)!=PROGRAMS['meteora']:raise EvidenceUnavailable('candidate_scout_fields_missing')
        # A bin-array account header is a wakeup only. It cannot replace swaps,
        # exact bins, balances, instructions or economic interval completeness.
        history.observe('meteora',pubkey(raw[24:56]),slot=item.slot,signature=sig,
            fields=dict(bin_array_locator=address,economic_event=False,history_complete=False),seen=seen)
    else:raise EvidenceUnavailable('candidate_scout_filter')

def block_message(frame):
    b=frame.update.block
    return dict(method='blockNotification',params=dict(result=dict(value=dict(slot=b.slot,err=None,
        block=dict(parentSlot=b.parent_slot,blockhash=b.blockhash,previousBlockhash=b.parent_blockhash,
                   blockTime=b.block_time.timestamp,transactions=[])))))

def commit_control(state,frame):
    install(state);b=frame.update.block;seen=frame.seen
    prepared=dict(endpoint_identity=state.fence.endpoint_identity,observed_at=seen,
                  slot=b.slot,signatures=[],batches=[],deliveries=[])
    with state.writer.source_frame():
        state.fence.block(Subscription('source',CONTROL,'control','census',2),block_message(frame),seen,prepared=prepared)
        state.fence._health('phase','ACTIVE');state.fence._health('heartbeat',seen)
        # Source coordinates inform bounded storage maintenance, never global
        # economic completeness. Candidate proofs live in a separate namespace.
        for scope in FAMILIES.values():
            state.fence._health('finalized_frontier:'+scope,dict(slot=b.slot,time=b.block_time.timestamp,seen=seen))

def commit_candidates(state,frame,addresses,session):
    history=install(state);b=frame.update.block;seen=frame.seen
    bodies={signature(tx.signature):economic_transaction(tx,slot=b.slot,
        block_time=b.block_time.timestamp,rich=True) for tx in b.transactions}
    bodies.update({tx['transaction']['signatures'][0]:tx for tx in frame.log_transactions})
    rows={};censuses={scope:[] for scope in addresses.values()}
    reverse={scope:address for address,scope in addresses.items()}
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
                continue
            if old and old[6]==session:
                if old[0]!=b.parent_slot or old[2]!=b.parent_blockhash:
                    history.gap(scope,old[0],b.slot-1,'candidate_native_parent_gap')
                    raise EvidenceUnavailable('candidate_native_parent_gap')
                witness=dict(finalized=True,complete=True,scope=scope,lower_slot=old[0],upper_slot=b.slot-1,
                    lineage_hash=digest([scope,list(old),list(values)]),
                    method='candidate_filtered_native_status_and_verified_content_with_linked_child',
                    native_order=True,transaction_bodies_only_for_meteora=True)
                history.prove(IntervalProof(scope,old[0],b.slot-1,'alchemy_finalized_stream',history.endpoint_identity,witness,seen))
            state.writer.db.execute('INSERT OR REPLACE INTO candidate_blocks VALUES(?,?,?,?,?,?,?,?,?)',(scope,*values))

def plan_live(state):
    history=install(state);now=time.time();db=state.writer.db
    desired=[]
    for scope,address,priority,lower,updated,position in db.execute('''SELECT i.scope,s.address,MIN(i.priority),
        MIN(i.lower_slot),MIN(i.updated),MAX(i.lifecycle IN ('open','reserved')) FROM service_interests s JOIN interests i
        ON i.owner=s.owner AND i.scope=s.scope WHERE i.active=1 GROUP BY i.scope,s.address'''):
        family=next((f for f,b in FAMILIES.items() if b==scope),None)
        if family is None:continue
        role=1 if position else (0 if priority==0 else (2 if priority<=2 else 3))
        # Stable interest identity: a polling clock cannot reconnect every feed.
        deadline=updated+3600 if role<=2 else updated+120
        desired.append((role,deadline,updated,family,address,lower))
        history.bind(family,address)
        db.execute('INSERT OR IGNORE INTO candidate_live_work VALUES(?,?,?,?,?)',(family,address,role,deadline,updated))
    desired.sort()
    if len(desired)>MAX_LIVE_CANDIDATES:
        with state.writer.transaction():history._observation(None,'capacity_pressure',dict(live_requested=len(desired),live_capacity=MAX_LIVE_CANDIDATES,economic_rejection=False))
    # The provider's filter-map limit is a shard size, never rejection authority.
    # Every requested scope remains serviced; rich acquisition is separately EDF.
    chosen=desired
    return [dict(family=f,address=a,scope=coverage_scope(f,a),priority=p,deadline=d,lower_slot=lo)
            for p,d,_,f,a,lo in chosen]

class SelectiveSource:
    def __init__(self,config,rpc,*,token=None):
        self.config=config;self.rpc=rpc;self.token=token or config.credential
        self.work=None;self.stop=None
    async def measured_rpc(self,method,params,family,priority=4):
        try:result,receipt=await asyncio.to_thread(self.rpc.call_delivered,method,params,priority)
        except ValueError as exc:
            receipt=getattr(exc,'receipt',None)
            if receipt is not None:
                await self.work(lambda s:install(s).delivery(family,'rpc',raw_bytes=receipt['bytes'],
                    rpc_cu=receipt['cu'],calls=1),priority)
            raise
        await self.work(lambda s:install(s).delivery(family,'rpc',raw_bytes=receipt['bytes'],
            rpc_cu=receipt['cu'],calls=1),priority)
        return result
    async def stream(self,channel,request,handler,family,local_stop=None):
        call=channel.stream_stream('/geyser.Geyser/Subscribe',request_serializer=lambda r:r.SerializeToString(),
            response_deserializer=lambda r:r)(metadata=(('x-token',self.token),))
        await call.write(request);pending=None
        try:
            while not self.stop.is_set() and not (local_stop and local_stop.is_set()):
                if pending is None:pending=asyncio.create_task(call.read())
                try:raw=await asyncio.wait_for(asyncio.shield(pending),1)
                except TimeoutError:continue
                pending=None
                if raw is grpc.aio.EOF:raise EvidenceUnavailable('candidate_native_eof')
                if len(raw)>MAX_FRAME_BYTES:raise EvidenceUnavailable('candidate_native_frame_bound')
                at=time.time()
                # Delivery counts before parsing, routing, filtering or dedup.
                await self.work(lambda s:install(s).delivery(family,'yellowstone',raw_bytes=len(raw),seen=at),2)
                update=pb.SubscribeUpdate.FromString(raw);kind=update.WhichOneof('update_oneof')
                if kind=='ping':await call.write(pb.SubscribeRequest(ping=pb.SubscribeRequestPing(id=1)));continue
                if kind=='pong':continue
                await handler(update,len(raw),at)
        except grpc.aio.AioRpcError as exc:raise EvidenceUnavailable('candidate_native_'+exc.code().name.lower()) from None
        finally:
            if pending:pending.cancel();await asyncio.gather(pending,return_exceptions=True)
            call.cancel()

    async def __call__(self,work,stop):
        require_certified()
        self.work=work;self.stop=stop;await work(install,0)
        tip=await self.measured_rpc('getSlot',[dict(commitment='finalized')],'shared',2)
        async with grpc.aio.secure_channel(HOST,grpc.ssl_channel_credentials(),options=[
                ('grpc.max_receive_message_length',MAX_FRAME_BYTES),('grpc.max_send_message_length',4*1024*1024),('grpc.http2.bdp_probe',0)]) as channel:
            req=pb.SubscribeRequest(commitment=pb.FINALIZED,from_slot=max(1,tip-CONTROL_OVERLAP))
            req.blocks_meta['b'].SetInParent();req.slots['f'].filter_by_commitment=True
            join=CandidateTransactionJoin({},set(),filtered_from_slot=req.from_slot)
            async def control(update,size,seen):
                frame=join.feed(update,size,seen)
                if frame:await work(lambda s:commit_control(s,frame),2,label='source_commit')
            async def scouts(update,size,seen):
                if update.WhichOneof('update_oneof')!='account':raise EvidenceUnavailable('candidate_scout_filter')
                await work(lambda s:commit_scout(s,update,seen),5,label='source_commit')
            tasks=[asyncio.create_task(self.stream(channel,req,control,'shared')),
                   asyncio.create_task(self.stream(channel,scout_request(),scouts,'discovery')),
                   asyncio.create_task(self.acquire()),asyncio.create_task(self.live_manager(channel)),
                   asyncio.create_task(stop.wait())]
            try:
                done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task is not tasks[-1]:task.result()
            finally:
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)

    async def acquire(self):
        while not self.stop.is_set():
            def request_development(state):
                from .lanes.pump.pump_acceleration_strategy import POLICY
                h=install(state);db=state.writer.db
                frontier=db.execute('SELECT MAX(hi) FROM coverage WHERE scope=?',(CONTROL,)).fetchone()[0]
                if frontier is not None:
                    for addr,fields in db.execute('''SELECT address,fields FROM market_observations m WHERE family='pump'
                        AND NOT EXISTS(SELECT 1 FROM evidence_bindings b WHERE b.family=m.family AND b.address=m.address)'''):
                        value=json.loads(fields);upper=value.get('development_upper_bps')
                        if value.get('complete') or upper is None or upper>=POLICY.min_curve_progress_bps:
                            h.bind('pump',addr);h.request('pump',addr,0,frontier,priority=3,deadline=time.time()+120)
                return h.plan()
            plan=await self.work(request_development,4)
            if not plan:await asyncio.sleep(.1);continue
            job,config=plan
            value=await self.measured_rpc('getTransactionsForAddress',[job['address'],config],job['family'],job['priority'])
            finalized=await self.measured_rpc('getSlot',[dict(commitment='finalized')],'shared',job['priority'])
            if finalized<job['hi']:await asyncio.sleep(.1);continue
            def commit(state):
                h=install(state)
                if job['family']=='pump':
                    from .solana_program_decoders import pump_events
                    for tx in value['data']:
                        for event in pump_events(tx):
                            if event['event_type']=='create':
                                # Initial curve identity is upgraded, not rejected,
                                # when its canonical creation reveals the mint.
                                state.writer.db.execute('DELETE FROM evidence_bindings WHERE family=? AND address=?',('pump',job['address']))
                                h.bind('pump',job['address'],market_address=event['mint'],aliases=(event['mint'],))
                            if event['event_type']=='migration':
                                h.observe('pumpswap',event['pool'],slot=event['slot'],signature=tx['transaction']['signatures'][0],fields=dict(mint=event['mint'],graduation=event['market_time']))
                                h.bind('pumpswap',event['pool'])
                return h.commit_page(job,value,finalized_through=finalized)
            await self.work(commit,job['priority'],label='source_commit')

    async def live_manager(self,channel):
        running=[];identity=None;local_stop=None
        try:
            while not self.stop.is_set():
                desired=await self.work(plan_live,2)
                new=digest([[r['family'],r['address'],r['priority']] for r in desired])
                for task in running:
                    if task.done():task.result();raise EvidenceUnavailable('candidate_live_task_stopped')
                if new!=identity:
                    if running:
                        local_stop.set()
                        for task in running:task.cancel()
                        await asyncio.gather(*running,return_exceptions=True)
                    identity=new
                    if desired:
                        local_stop=asyncio.Event()
                        running=[asyncio.create_task(self.live(channel,desired[n:n+MAX_LIVE_CANDIDATES],local_stop))
                                 for n in range(0,len(desired),MAX_LIVE_CANDIDATES)]
                    else:running=[]
                await asyncio.sleep(.25)
        finally:
            for task in running:task.cancel()
            if running:await asyncio.gather(*running,return_exceptions=True)

    async def live(self,channel,desired,local_stop):
        tip=await self.measured_rpc('getSlot',[dict(commitment='finalized')],'shared',2)
        floor=max(1,tip-WARM_OVERLAP);addresses={r['address']:r['scope'] for r in desired}
        full={r['address'] for r in desired if r['family']=='meteora'}
        join=CandidateTransactionJoin(addresses,full,filtered_from_slot=floor);session=uuid.uuid4().hex
        # Archive jobs persist across source/filter changes. Their exhaustion is
        # required before qualification, even when the live feed is already hot.
        def warm(state):
            h=install(state)
            for row in desired:h.request(row['family'],row['address'],row['lower_slot'],tip,
                priority=row['priority'],deadline=row['deadline'])
        await self.work(warm,2)
        async def commit(frame):
            if frame:await self.work(lambda s:commit_candidates(s,frame,addresses,session),
                0 if any(r['priority']<=1 for r in desired) else 2,label='source_commit')
        # Obtain replay log content from the same authoritative archive. A WS
        # ACK supplies no old events; each short page's token must be followed.
        for row in desired:
            if row['family']=='meteora':continue
            token=None
            while True:
                config=dict(transactionDetails='full',sortOrder='asc',limit=100,commitment='finalized',
                    encoding='json',maxSupportedTransactionVersion=1,filters=dict(slot=dict(gte=floor,lte=tip)))
                if token:config['paginationToken']=token
                value=await self.measured_rpc('getTransactionsForAddress',[row['address'],config],row['family'],row['priority'])
                for tx in value['data']:
                    if tx['meta']['err'] is None:join.feed_log(tx['slot'],tx['transaction']['signatures'][0],tx['meta']['logMessages'],None,time.time())
                next_token=value.get('paginationToken')
                if next_token is None:break
                if next_token==token:raise EvidenceUnavailable('repair_pagination_stalled')
                token=next_token
        async def native(update,size,seen):await commit(join.feed(update,size,seen))
        async def logs():
            async with connect(self.config.stream_url,max_size=MAX_FRAME_BYTES,max_queue=2,ping_interval=10,ping_timeout=None) as ws:
                pending={};registered={}
                for number,row in enumerate((r for r in desired if r['family']!='meteora'),1):
                    pending[number]=row
                    await ws.send(canonical(dict(jsonrpc='2.0',id=number,method='logsSubscribe',
                        params=[dict(mentions=[row['address']]),dict(commitment='finalized')])))
                while not self.stop.is_set() and not local_stop.is_set():
                    raw=await ws.recv();seen=time.time();size=len(raw.encode() if isinstance(raw,str) else raw)
                    await self.work(lambda s:install(s).delivery('candidate_logs','websocket',raw_bytes=size,seen=seen),2)
                    value=json.loads(raw)
                    if 'id' in value:
                        if 'error' in value or value['id'] not in pending:raise EvidenceUnavailable('authoritative_subscription_rejected')
                        registered[value['result']]=pending.pop(value['id']);continue
                    result=value['params']['result'];row=registered.get(value['params']['subscription'])
                    if row is None:raise EvidenceUnavailable('unknown_source_subscription')
                    v=result['value']
                    if v['err'] is None:await commit(join.feed_log(result['context']['slot'],v['signature'],v['logs'],None,seen))
        tasks=[asyncio.create_task(self.stream(channel,candidate_subscription(addresses,floor,full_addresses=full),native,'candidate_live',local_stop))]
        if len(full)<len(desired):tasks.append(asyncio.create_task(logs()))
        try:
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
