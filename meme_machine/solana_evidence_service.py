"""Finalized filtered-block fences over the existing single-writer evidence store.

Only this source adapter can seal coverage. Consumers send lifecycle interests and
read SQLite; they cannot send records, receipts, frontiers or interval proofs.
A receipt authenticates a block's filtered census. Its linked finalized child is
required to seal it. Silence, root notifications and socket ACKs never seal data.
"""
from dataclasses import replace
import json
import time
import uuid
from .solana_evidence_plane import EvidenceUnavailable, EvidenceConflict, IntervalProof, digest, canonical
from .solana_evidence_transport import FinalizedNotificationDecoder

SERVICE_SCHEMA='''
CREATE TABLE IF NOT EXISTS stream_receipts(
 scope TEXT NOT NULL,slot INTEGER NOT NULL,parent INTEGER NOT NULL,hash TEXT NOT NULL,
 previous_hash TEXT NOT NULL,market_time INTEGER NOT NULL,census TEXT NOT NULL,
 session TEXT NOT NULL,seen REAL NOT NULL,sealed INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(scope,slot));
CREATE INDEX IF NOT EXISTS receipt_time ON stream_receipts(scope,market_time,slot);
CREATE TABLE IF NOT EXISTS stream_deliveries(
 scope TEXT NOT NULL,slot INTEGER NOT NULL,signature TEXT NOT NULL,hash TEXT NOT NULL,
 seen REAL NOT NULL,PRIMARY KEY(scope,slot,signature));
CREATE TABLE IF NOT EXISTS service_interests(
 owner TEXT NOT NULL,scope TEXT NOT NULL,address TEXT NOT NULL,evidence_class TEXT NOT NULL,
 PRIMARY KEY(owner,scope,address));
CREATE TABLE IF NOT EXISTS stream_order(scope TEXT NOT NULL,slot INTEGER NOT NULL,signature TEXT NOT NULL,rank INTEGER NOT NULL,blockhash TEXT NOT NULL,PRIMARY KEY(scope,slot,signature));
CREATE TABLE IF NOT EXISTS service_health(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS interest_owners(owner TEXT PRIMARY KEY,consumer TEXT NOT NULL);
'''

def poison_conflicts(method):
    from functools import wraps
    @wraps(method)
    def guarded(self,*args,**kwargs):
        try:return method(self,*args,**kwargs)
        except EvidenceConflict:
            with self.writer.transaction():
                self.writer.db.execute("INSERT OR REPLACE INTO meta VALUES('poisoned','1')")
                self.writer._count('source_conflicts')
            raise
    return guarded

class FinalizedFence:
    def __init__(self,writer,*,endpoint_identity,decoders=None):
        self.writer=writer;self.endpoint_identity=endpoint_identity
        self.decoders=decoders or {};self.session=uuid.uuid4().hex
        writer.db.executescript(SERVICE_SCHEMA)
        if writer.db.execute('SELECT 1 FROM stream_receipts LIMIT 1').fetchone():self.disconnect('service_restart')
        with writer.transaction():
            for key in ('pump.foreground_historical_rpc_calls','meteora.historical_reconstruction_rpc_calls',
                        'stream_messages','stream_bytes','stream_reconnects','stream_rejected_messages',
                        'stream_accepted_messages','gap_repair_retries','rejected_evidence_records',
                        'ingested_event','ingested_transaction','ingested_account',
                        'pump.local_evidence_reads','meteora.local_evidence_reads',
                        'pump.complete_local_reads','meteora.complete_local_reads',
                        'pump.incomplete_local_reads','meteora.incomplete_local_reads',
                        'pump.repair_assisted_windows','meteora.repair_assisted_windows'):
                writer.db.execute('INSERT OR IGNORE INTO counters VALUES(?,0)',(key,))

    def health(self,key,value):
        from .solana_provider_config import public_value
        public_value(value)
        with self.writer.transaction():
            self.writer.db.execute('INSERT OR REPLACE INTO service_health VALUES(?,?)',(key,canonical(value)))

    def count(self,key,n=1):
        with self.writer.transaction():self.writer._count(key,n)

    def expire_candidates(self,now):
        with self.writer.transaction():
            n=self.writer.db.execute("UPDATE interests SET active=0 WHERE active=1 AND lifecycle IN ('candidate','research') AND updated<?",(now-1200,)).rowcount
            self.writer._count('expired_candidate_interests',n)
            self.writer.db.execute('DELETE FROM service_interests WHERE NOT EXISTS(SELECT 1 FROM interests i WHERE i.owner=service_interests.owner AND i.scope=service_interests.scope AND i.active=1)')
            self.writer.db.execute('DELETE FROM interests WHERE active=0 AND updated<?',(now-7200,))
            self.writer.db.execute('DELETE FROM interest_owners WHERE NOT EXISTS(SELECT 1 FROM interests i WHERE i.owner=interest_owners.owner)')

    def disconnect(self,reason='stream_disconnect'):
        # Account notifications are content observations, never interval sources.
        # Creating unrepairable interval gaps for them would pin expired account
        # history forever. Program fences still fail closed across this restart;
        # execution accounts require the independently bounded current refresh.
        bounds=dict(self.writer.db.execute("SELECT scope,slot+1 FROM cursors WHERE scope NOT LIKE 'account:%'"))
        with self.writer.transaction():
            self.writer.db.execute('INSERT OR REPLACE INTO service_health VALUES(?,?)',
                ('account_stream_discontinuity',canonical(dict(reason=reason,seen=self.writer.clock()))))
        for scope,slot in self.writer.db.execute('SELECT scope,MIN(slot) FROM stream_receipts WHERE sealed=0 GROUP BY scope'):
            bounds[scope]=min(bounds.get(scope,slot),slot)
        for scope,slot in bounds.items():self.writer.gap(scope,slot,None,reason)
        self.session=uuid.uuid4().hex

    def _delivery(self,scope,slot,signature,payload,seen):
        checksum=digest(payload)
        with self.writer.transaction():
            old=self.writer.db.execute('SELECT hash FROM stream_deliveries WHERE scope=? AND slot=? AND signature=?',
                (scope,slot,signature)).fetchone()
            if old and old[0]!=checksum:
                raise EvidenceConflict('conflicting_stream_delivery')
            self.writer.db.execute('INSERT OR IGNORE INTO stream_deliveries VALUES(?,?,?,?,?)',
                (scope,slot,signature,checksum,seen))

    @poison_conflicts
    def logs(self,subscription,message,seen):
        result=message['params']['result'];slot=result['context']['slot'];v=result['value']
        decoder=FinalizedNotificationDecoder(endpoint_identity=self.endpoint_identity,
            log_decoder=self.decoders[subscription.scope])
        records=decoder.decode(subscription,message,seen)
        # Store economic content separately from source delivery identity. Preserve
        # original availability and log indices through all replays.
        self.writer.ingest(records)
        self._delivery(subscription.scope,slot,v['signature'],v,seen)
        self.seal(subscription.scope,seen)

    @poison_conflicts
    def block(self,subscription,message,seen):
        value=message['params']['result']['value'];slot=value['slot'];block=value.get('block')
        if value.get('err') is not None or not isinstance(block,dict):
            self.writer.gap(subscription.scope,slot,slot,'filtered_block_unavailable')
            raise EvidenceUnavailable('filtered_block_unavailable')
        parent=block.get('parentSlot');at=block.get('blockTime')
        if (type(slot) is not int or type(parent) is not int or not 0<=parent<slot
                or type(at) is not int or at>seen or not block.get('blockhash') or not block.get('previousBlockhash')):
            raise EvidenceUnavailable('finalized_block_fence_shape')
        if subscription.evidence_class=='transactions':
            transactions=block.get('transactions')
            if not isinstance(transactions,list) or len(transactions)>2048:
                raise EvidenceUnavailable('filtered_block_bound')
            signatures=[tx['transaction']['signatures'][0] for tx in transactions]
            decoder=FinalizedNotificationDecoder(endpoint_identity=self.endpoint_identity)
            records=decoder.decode(subscription,message,seen)
            enriched=[]
            for rank,(tx,record) in enumerate(zip(transactions,records)):
                message_keys=tx['transaction']['message'].get('accountKeys') or []
                keys=[k if isinstance(k,str) else k['pubkey'] for k in message_keys]
                loaded=(tx.get('meta') or {}).get('loadedAddresses') or {}
                keys+=list(loaded.get('writable') or [])+list(loaded.get('readonly') or [])
                body=dict(record.payload);body.pop('transactionIndex',None)
                enriched.append(replace(record,payload=body,transaction_index=None,
                    addresses=tuple(sorted(set(keys+[subscription.address])))))
            self.writer.ingest(enriched)
            with self.writer.transaction():
                self.writer.db.executemany('INSERT OR IGNORE INTO stream_order VALUES(?,?,?,?,?)',
                    [(subscription.scope,slot,sig,rank,block['blockhash']) for rank,sig in enumerate(signatures)])
            for tx,signature in zip(transactions,signatures):
                self._delivery(subscription.scope,slot,signature,tx,seen)
        else:
            signatures=block.get('signatures')
        if (not isinstance(signatures,list) or len(signatures)>2048
                or any(not isinstance(s,str) or not s for s in signatures)
                or len(signatures)!=len(set(signatures))):
            raise EvidenceUnavailable('filtered_census_shape')
        census=canonical(signatures);scope=subscription.scope
        with self.writer.transaction():
            old=self.writer.db.execute('SELECT parent,hash,previous_hash,market_time,census FROM stream_receipts WHERE scope=? AND slot=?',(scope,slot)).fetchone()
            values=(parent,block['blockhash'],block['previousBlockhash'],at,census)
            if old and tuple(old)!=values:
                raise EvidenceConflict('conflicting_finalized_block_receipt')
            self.writer.db.execute('INSERT OR IGNORE INTO stream_receipts VALUES(?,?,?,?,?,?,?,?,?,0)',
                (scope,slot,*values,self.session,seen))
            prior=self.writer.db.execute('SELECT MAX(slot) FROM stream_receipts WHERE scope=? AND slot<?',(scope,slot)).fetchone()[0]
            # Do not classify a skipped slot as a produced block; parent links are
            # the explicit proof of skipped slots. An unknown parent is a gap.
            if prior is not None and parent>prior:
                self.writer._gap(scope,prior,parent,'missing_filtered_block_receipt')
            self.writer.db.execute('INSERT OR REPLACE INTO service_health VALUES(?,?)',
                ('finalized_frontier:'+scope,canonical(dict(slot=slot,time=at,seen=seen))))
        self.writer.reconnect(scope,slot)
        self.seal(scope,seen)

    def seal(self,scope,seen):
        pairs=self.writer.db.execute('''SELECT p.slot,p.hash,p.census,p.seen,c.slot,c.hash,c.previous_hash,c.seen
            FROM stream_receipts p JOIN stream_receipts c ON c.scope=p.scope AND c.parent=p.slot
            WHERE p.scope=? AND p.sealed=0 AND p.session=? AND c.session=? ORDER BY p.slot LIMIT 64''',
            (scope,self.session,self.session)).fetchall()
        for slot,blockhash,census,pseen,child,chash,previous,cseen in pairs:
            if previous!=blockhash:
                self.writer.gap(scope,slot,child,'finalized_parent_hash_mismatch')
                raise EvidenceConflict('finalized_parent_hash_mismatch')
            expected=set(json.loads(census))
            delivered=dict(self.writer.db.execute('SELECT signature,seen FROM stream_deliveries WHERE scope=? AND slot=?',(scope,slot)))
            if not expected.issubset(delivered):
                self.writer.gap(scope,slot,slot,'missing_filtered_delivery')
                continue
            witness=dict(finalized=True,complete=True,scope=scope,lower_slot=slot,upper_slot=child-1,
                source_contract='complete_filtered_block_census_with_linked_finalized_child',
                parent_blockhash=blockhash,child_blockhash=chash,child_slot=child,
                signature_count=len(expected),lineage_hash=digest([scope,slot,blockhash,census,child,chash]))
            available=max([seen,pseen,cseen]+[delivered[s] for s in expected])
            proof=IntervalProof(scope,slot,child-1,'alchemy_finalized_stream',self.endpoint_identity,witness,available)
            self.writer.ingest([],proof=proof)
            with self.writer.transaction():
                n=self.writer.db.execute("UPDATE gaps SET repaired=? WHERE scope=? AND lo=? AND hi=? AND reason='missing_filtered_delivery' AND repaired IS NULL",(available,scope,slot,slot)).rowcount
                self.writer._count('gaps_repaired',n)
                self.writer.db.execute('UPDATE stream_receipts SET sealed=1 WHERE scope=? AND slot=?',(scope,slot))

    def repair_records(self,record):
        """Same normalized economic bytes for stream and HTTP repair lineage."""
        tx=dict(record.payload);tx.pop('transactionIndex',None)
        scope=record.scope
        if scope in self.decoders:
            sub=next(s for s in program_subscriptions() if s.scope==scope and s.evidence_class=='logs')
            message={'method':'logsNotification','params':{'result':{'context':{'slot':record.slot},
                'value':{'signature':record.signature,'logs':(tx.get('meta') or {}).get('logMessages'),
                         'err':(tx.get('meta') or {}).get('err')}}}}
            rows=FinalizedNotificationDecoder(endpoint_identity=self.endpoint_identity,log_decoder=self.decoders[scope]).decode(sub,message,record.observed_at)
            return [replace(r,source='alchemy_finalized_repair') for r in rows]
        keys=tx['transaction']['message'].get('accountKeys') or []
        keys=[k if isinstance(k,str) else k['pubkey'] for k in keys]
        loaded=(tx.get('meta') or {}).get('loadedAddresses') or {}
        keys+=list(loaded.get('writable') or [])+list(loaded.get('readonly') or [])
        previous=self.writer.db.execute('SELECT transaction_index FROM records WHERE identity=?',(record.identity,)).fetchone()
        index=previous[0] if previous else record.transaction_index
        return [replace(record,payload=tx,addresses=tuple(sorted(set(keys+[record.program]))),transaction_index=index)]

    def command(self,request):
        """Strict consumer IPC whitelist; no proof/ingest/SQL escape hatch."""
        op=request.get('op')
        if op in ('interest','release','ack'):
            owner=request['owner'];consumer=request.get('consumer',owner)
            if not isinstance(owner,str) or len(owner)>256 or not isinstance(consumer,str) or len(consumer)>128:
                raise EvidenceUnavailable('interest_owner_bound')
            known=self.writer.db.execute('SELECT consumer FROM interest_owners WHERE owner=?',(owner,)).fetchone()
            if known and known[0]!=consumer:raise EvidenceUnavailable('interest_owned_by_other_consumer')
            if not known and op=='interest':
                if self.writer.db.execute('SELECT COUNT(*) FROM interest_owners').fetchone()[0]>=4096:
                    raise EvidenceUnavailable('interest_owner_capacity')
        if op=='interest':
            owner=request['owner'];scope=request['scope']
            addresses=request.get('addresses',[])
            if not isinstance(addresses,list) or len(addresses)>100:
                raise EvidenceUnavailable('interest_account_bound')
            if any(not isinstance(a,str) or not a or len(a)>128 for a in addresses):
                raise EvidenceUnavailable('interest_address')
            phase=self.writer.db.execute("SELECT value FROM service_health WHERE key='phase'").fetchone()
            if phase and json.loads(phase[0])=='DRAINING' and request['lifecycle'] not in ('reserved','open'):
                raise EvidenceUnavailable('service_draining')
            current={r[0] for r in self.writer.db.execute('SELECT DISTINCT s.address FROM service_interests s JOIN interests i ON i.owner=s.owner AND i.scope=s.scope WHERE i.active=1')}
            if len(current|set(addresses))>256:
                self.count('subscription_capacity_rejections')
                raise EvidenceUnavailable('subscription_capacity')
            with self.writer.transaction():
                self.writer._interest(owner,scope,lower_slot=request['lower_slot'],
                    priority=request['priority'],lifecycle=request['lifecycle'])
                self.writer.db.execute('INSERT OR IGNORE INTO interest_owners VALUES(?,?)',(owner,consumer))
                for address in addresses:
                    self.writer.db.execute('INSERT OR REPLACE INTO service_interests VALUES(?,?,?,?)',
                        (owner,scope,address,'account'))
        elif op=='release':
            self.writer.release(request['owner'],request['scope'],lifecycle_resolved=request.get('resolved') is True)
        elif op=='ack':
            self.writer.acknowledge(request['owner'],request['scope'],request['slot'])
        elif op=='counter':
            key=request['key'];count=request.get('count',1)
            if not key.startswith(('pump.','meteora.')) or len(key)>120 or type(count) is not int or not 0<=count<=10000:
                raise EvidenceUnavailable('consumer_counter_bound')
            with self.writer.transaction():self.writer._count(key,count)
        else:
            raise EvidenceUnavailable('consumer_command_forbidden')
        return {'ok':True}


def program_subscriptions():
    from .solana_evidence_transport import Subscription
    from .solana_evidence_runtime import PUMP_SCOPE,SWAP_SCOPE,METEORA_SCOPE
    from . import pump
    from .postgrad import PUMPSWAP_PROGRAM
    result=[]
    for scope,address in [(PUMP_SCOPE,pump.PROGRAM),(SWAP_SCOPE,PUMPSWAP_PROGRAM)]:
        result.extend(Subscription('service',scope,address,kind,4) for kind in ('logs','census'))
    result.append(Subscription('service',METEORA_SCOPE,'LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo','transactions',4))
    return result


def program_decoders():
    from . import pump
    from .pump_acceleration_evidence import pumpswap_trade_events
    from .solana_evidence_runtime import PUMP_SCOPE,SWAP_SCOPE
    def pump_events(tx):
        return [dict(e,event_type='trade') for e in pump.trade_events(tx)]+[dict(e,event_type='create') for e in pump.create_events(tx)]
    return {PUMP_SCOPE:pump_events,SWAP_SCOPE:pumpswap_trade_events}


async def serve(path,endpoint,*,repair_rpc=None,stop=None):
    """One supervised process, one SQLite writer, bounded source and IPC I/O."""
    import asyncio
    import hashlib
    import os
    from pathlib import Path
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed
    from .solana_evidence_plane import EvidenceWriter
    from .solana_evidence_transport import alchemy_stream_endpoint,Subscription,AddressGapRepair
    from .solana_provider_config import AlchemyEndpoint
    from .solana_evidence_plane import require_storage,storage_health
    config=AlchemyEndpoint.parse(endpoint)
    import logging
    logger=logging.Logger('alchemy_evidence_transport');logger.addHandler(logging.NullHandler());logger.propagate=False
    url=config.stream_url;writer=EvidenceWriter(path)
    fence=FinalizedFence(writer,endpoint_identity=config.identity,decoders=program_decoders())
    fence.health('provider',dict(provider=config.provider,network=config.network,endpoint_identity=config.identity))
    fence.health('phase','WARMING')
    stop=stop or asyncio.Event();path=Path(path);socket_path=str(path)+'.sock'
    Path(socket_path).unlink(missing_ok=True)
    async def consumer(reader,stream):
        try:
            line=await asyncio.wait_for(reader.readline(),.5)
            if len(line)>32768:raise EvidenceUnavailable('consumer_command_bound')
            request=json.loads(line)
            if not request.get('consumer'):raise EvidenceUnavailable('consumer_identity_required')
            response=fence.command(request)
        except (ValueError,KeyError,TypeError,TimeoutError) as exc:response={'ok':False,'error':type(exc).__name__}
        stream.write((canonical(response)+'\n').encode());await stream.drain();stream.close()
    server=await asyncio.start_unix_server(consumer,path=socket_path,limit=32769)
    os.chmod(socket_path,0o600)
    async def stream_source():
        while not stop.is_set():
            try:
                async with connect(url,logger=logger,max_size=16*1024*1024,max_queue=32,ping_interval=10,ping_timeout=10,open_timeout=10) as ws:
                    pending={};active={};registered=set();retiring=set();number=0
                    async def register(sub):
                        nonlocal number
                        number+=1;pending[number]=sub;await ws.send(canonical(sub.request(number)))
                    for sub in program_subscriptions():await register(sub)
                    while not stop.is_set():
                        # Durable interests survive consumer/service restarts. Account
                        # observations remain content only, never interval authority.
                        interests=writer.db.execute("SELECT s.address FROM service_interests s JOIN interests i ON s.owner=i.owner AND s.scope=i.scope WHERE i.active=1 GROUP BY s.address ORDER BY MIN(i.priority),s.address").fetchall()
                        if len(interests)>256:
                            fence.count('subscription_capacity_rejections')
                            raise EvidenceUnavailable('restored_subscription_capacity')
                        wanted={r[0] for r in interests}
                        for sid,sub in list(active.items()):
                            if sub.evidence_class=='account' and sub.address not in wanted:
                                number+=1;retiring.add(number)
                                await ws.send(canonical(dict(jsonrpc='2.0',id=number,method='accountUnsubscribe',params=[sid])))
                                del active[sid];registered.discard(sub.address)
                        for address, in interests:
                            if address not in registered:
                                await register(Subscription('service','account:'+address,address,'account',0));registered.add(address)
                        try:raw=await asyncio.wait_for(ws.recv(),.5)
                        except TimeoutError:continue
                        seen=time.time()
                        fence.count('stream_messages');fence.count('stream_bytes',len(raw.encode() if isinstance(raw,str) else raw))
                        message=json.loads(raw);config.public(message)
                        if message.get('id') in retiring:
                            retiring.remove(message['id']);continue
                        if 'id' in message:
                            sub=pending.pop(message['id'])
                            if 'error' in message or type(message.get('result')) is not int:
                                if (message.get('error') or {}).get('code')==-32601:fence.count('stream_unsupported_methods')
                                raise EvidenceUnavailable('authoritative_subscription_rejected')
                            active[message['result']]=sub
                            from collections import Counter
                            fence.health('subscriptions',dict(active=len(active),by_evidence_class=dict(Counter(s.evidence_class for s in active.values())),pending=len(pending),wanted_accounts=len(wanted)))
                            continue
                        sub=active.get((message.get('params') or {}).get('subscription'))
                        if sub is None:raise EvidenceUnavailable('unknown_source_subscription')
                        if sub.evidence_class=='logs':fence.logs(sub,message,seen)
                        elif sub.evidence_class=='account':
                            writer.ingest(FinalizedNotificationDecoder(endpoint_identity=fence.endpoint_identity).decode(sub,message,seen))
                        else:fence.block(sub,message,seen)
                        fence.count('stream_accepted_messages')
                        fence.health('phase','ACTIVE')
                        from collections import Counter
                        fence.health('subscriptions',dict(active=len(active),by_evidence_class=dict(Counter(s.evidence_class for s in active.values())),pending=len(pending),wanted_accounts=len(wanted)))
            except (OSError,ValueError,KeyError,TypeError,TimeoutError,ConnectionClosed) as exc:
                fence.count('stream_rejected_messages')
                if str(exc) in ('hot_store_capacity','storage_capacity_critical'):raise
                if isinstance(exc,EvidenceConflict):
                    with writer.transaction():writer.db.execute("INSERT OR REPLACE INTO meta VALUES('poisoned','1')")
                    raise
                fence.disconnect(type(exc).__name__)
                fence.count('stream_reconnects');fence.count('stream_reconnect_reason.'+type(exc).__name__)
                fence.health('subscriptions',dict(active=0,by_evidence_class={},pending=0,wanted_accounts=0))
                fence.health('phase','WARMING')
                try:await asyncio.wait_for(stop.wait(),1)
                except TimeoutError:pass
    # Repair transport is detached from the SQLite writer and strategy consumers.
    # One bounded page is in flight; commits are applied on this writer's thread.
    async def repair_worker():
        while not stop.is_set():
            if repair_rpc is not None:
                gap=writer.db.execute('SELECT id,scope,lo,hi,repair_cursor,pages,attempts FROM gaps WHERE repaired IS NULL AND hi IS NOT NULL AND pages<16 AND attempts<48 ORDER BY created LIMIT 1').fetchone()
                if gap:
                    gid,scope,lo,hi,cursor,pages,attempts=gap
                    subscriptions={s.scope:s for s in program_subscriptions()}
                    sub=subscriptions.get(scope)
                    if sub:
                        state=json.loads(cursor) if cursor else {'next':None}
                        cfg=dict(transactionDetails='full',sortOrder='asc',limit=100,commitment='finalized',encoding='json',maxSupportedTransactionVersion=1,filters={'slot':{'gte':lo,'lte':hi}})
                        if state.get('next'):cfg['paginationToken']=state['next']
                        try:
                            with writer.transaction():
                                writer.db.execute('UPDATE gaps SET attempts=attempts+1 WHERE id=?',(gid,))
                                writer._count('gap_repair_attempts')
                                if attempts:writer._count('gap_repair_retries')
                            active=writer.db.execute("SELECT 1 FROM interests WHERE scope=? AND active=1 AND lifecycle IN ('candidate','reserved','open') LIMIT 1",(scope,)).fetchone()
                            value=await asyncio.to_thread(repair_rpc.call,'getTransactionsForAddress',[sub.address,cfg],bool(active))
                            # Apply through the same bounded durable repair boundary.
                            class ReceiptRPC:
                                def call(self,*args):return value
                            frontier=writer.db.execute('SELECT MAX(slot) FROM stream_receipts WHERE scope=?',(scope,)).fetchone()[0]
                            AddressGapRepair(ReceiptRPC(),writer,endpoint_identity=fence.endpoint_identity,record_mapper=fence.repair_records).step(gid,sub.address,now=time.time(),finalized_through=frontier)
                        except (OSError,ValueError,KeyError,TypeError,TimeoutError):
                            with writer.transaction():writer._count('gap_repair_failures')
            try:await asyncio.wait_for(stop.wait(),1)
            except TimeoutError:pass
    async def maintenance():
        previous=None
        while not stop.is_set():
            # Candidate interests have bounded leases; unresolved money/lifecycle
            # interests never expire. No archive slice runs ahead of a reservation.
            now=time.time()
            fence.expire_candidates(now)
            fence.health('storage',storage_health(writer.path));require_storage(writer.path)
            counts=dict(writer.db.execute('SELECT * FROM counters'))
            backlog=writer.db.execute('SELECT COUNT(*) FROM gaps WHERE repaired IS NULL').fetchone()[0]
            http=repair_rpc.telemetry() if repair_rpc is not None and hasattr(repair_rpc,'telemetry') else {}
            fence.health('repair_http',http)
            if repair_rpc is not None and hasattr(repair_rpc,'governor'):
                fence.health('http_governor',repair_rpc.governor.status())
            current=(now,counts.get('stream_bytes',0),counts.get('stream_reconnects',0),backlog)
            anomalies=[]
            if storage_health(writer.path)['state']!='ok':anomalies.append('filesystem_capacity_pressure')
            if previous:
                seconds=max(.001,now-previous[0])
                if (current[1]-previous[1])/seconds>16*1024*1024:anomalies.append('stream_byte_rate')
                if current[2]-previous[2]>=3:anomalies.append('reconnect_loop')
                if backlog>previous[3]:anomalies.append('growing_repair_backlog')
            hc=http.get('counters',{})
            if hc.get('429s',0)>=3:anomalies.append('repeated_429s')
            if hc.get('unsupported_methods',0)+counts.get('stream_unsupported_methods',0)>=3:anomalies.append('unsupported_method')
            if counts.get('subscription_capacity_rejections',0):anomalies.append('subscription_growth')
            hot=sum(p.stat().st_size for p in (writer.path,Path(str(writer.path)+'-wal')) if p.exists())
            if hot>writer.max_hot_bytes*.8:anomalies.append('hot_capacity_pressure')
            decisions=counts.get('pump.decisions_fully_local',0)+counts.get('meteora.local_warmup_intervals',0)
            if hc.get('physical_requests',0)>max(100,decisions*20):anomalies.append('http_per_decision')
            fence.health('resource_anomalies',dict(states=anomalies,repair_backlog=backlog,observed_at=now,
                stream_bytes_per_second=(current[1]-previous[1])/max(.001,now-previous[0]) if previous else None))
            previous=current
            if not writer.db.execute("SELECT 1 FROM interests WHERE active=1 AND lifecycle='reserved' LIMIT 1").fetchone():
                plan=writer.archive_plan(now-7200,max_records=256)
                receipt=await asyncio.to_thread(writer.write_archive,writer.path,plan)
                writer.commit_archive(plan,receipt)
                writer.retain(now-7200,max_records=256,archive_first=False)
            try:await asyncio.wait_for(stop.wait(),5)
            except TimeoutError:pass
    tasks=[asyncio.create_task(stream_source()),asyncio.create_task(repair_worker()),asyncio.create_task(maintenance())]
    try:
        stopper=asyncio.create_task(stop.wait())
        done,_=await asyncio.wait([stopper,*tasks],return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is not stopper:task.result()
    finally:
        fence.health('phase','DRAINING')
        if 'stopper' in locals():stopper.cancel()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        fence.disconnect('service_shutdown');server.close();await server.wait_closed()
        if repair_rpc is not None and hasattr(repair_rpc,'telemetry'):fence.health('repair_http',repair_rpc.telemetry())
        fence.health('phase','OFF')
        writer.close();Path(socket_path).unlink(missing_ok=True)
