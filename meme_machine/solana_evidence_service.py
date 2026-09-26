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
CREATE INDEX IF NOT EXISTS receipt_parent ON stream_receipts(scope,parent,session);
CREATE TABLE IF NOT EXISTS stream_deliveries(
 scope TEXT NOT NULL,slot INTEGER NOT NULL,signature TEXT NOT NULL,hash TEXT NOT NULL,
 seen REAL NOT NULL,PRIMARY KEY(scope,slot,signature));
CREATE TABLE IF NOT EXISTS service_interests(
 owner TEXT NOT NULL,scope TEXT NOT NULL,address TEXT NOT NULL,evidence_class TEXT NOT NULL,
 PRIMARY KEY(owner,scope,address));
CREATE TABLE IF NOT EXISTS stream_order(scope TEXT NOT NULL,slot INTEGER NOT NULL,signature TEXT NOT NULL,rank INTEGER NOT NULL,blockhash TEXT NOT NULL,PRIMARY KEY(scope,slot,signature));
CREATE TABLE IF NOT EXISTS service_health(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS interest_owners(owner TEXT PRIMARY KEY,consumer TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS command_receipts(
 consumer TEXT NOT NULL,request_id TEXT NOT NULL,hash TEXT NOT NULL,response TEXT NOT NULL,
 expires REAL NOT NULL,PRIMARY KEY(consumer,request_id));
CREATE INDEX IF NOT EXISTS command_expiry ON command_receipts(expires);
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


def disconnect_classification(exc):
    """Secret-safe attribution: never persist arbitrary provider exception text."""
    if isinstance(exc,EvidenceUnavailable):return str(exc)
    sent=getattr(exc,'sent',None);received=getattr(exc,'rcvd',None)
    if getattr(sent,'code',None)==1009 or getattr(received,'code',None)==1009:return 'source_message_size_limit'
    if 'keepalive ping timeout' in str(getattr(sent,'reason','')).lower():return 'local_receive_backpressure_ping_timeout'
    if received is not None:
        return 'provider_close_'+str(received.code)
    return type(exc).__name__

STREAM_MAX_MESSAGE_BYTES=16*1024*1024
STREAM_PROTOCOL_QUEUE_FRAMES=32
STREAM_DISPATCH_MAX_MESSAGES=64
STREAM_DISPATCH_MAX_BYTES=96*1024*1024
STREAM_WATCHDOG_SECONDS=.1


def decode_source_message(raw,credential,program_addresses=()):
    """Decode and authority-preservingly compact one provider frame.

    This function is process-safe. For full block notifications it inspects every
    transaction's static and loaded account keys before dropping unrelated bodies.
    The parent receives only the union relevant to Pump, PumpSwap, or Meteora.
    """
    from .solana_provider_config import public_value
    if not isinstance(raw,str) or len(raw)>STREAM_MAX_MESSAGE_BYTES:
        raise EvidenceUnavailable('source_message_size_limit')
    public_value(raw,credential)
    message=json.loads(raw)
    if not isinstance(message,dict):
        raise EvidenceUnavailable('source_message_shape')
    total=retained=0
    if message.get('method')=='blockNotification':
        try:
            value=message['params']['result']['value'];block=value.get('block')
            transactions=block.get('transactions') if isinstance(block,dict) else None
        except (KeyError,TypeError,AttributeError):
            raise EvidenceUnavailable('source_block_shape') from None
        if not isinstance(transactions,list):
            raise EvidenceUnavailable('source_block_shape')
        targets=set(program_addresses);kept=[]
        for tx in transactions:
            try:
                keys=tx['transaction']['message']['accountKeys']
                meta=tx['meta']
                if not isinstance(keys,list) or not isinstance(meta,dict):
                    raise TypeError()
                normalized=[k if isinstance(k,str) else k['pubkey'] for k in keys]
                loaded=meta.get('loadedAddresses') or {}
                normalized+=list(loaded.get('writable') or [])+list(loaded.get('readonly') or [])
                if any(not isinstance(k,str) for k in normalized):
                    raise TypeError()
            except (KeyError,TypeError,AttributeError):
                raise EvidenceUnavailable('source_transaction_shape') from None
            total+=1
            if targets.intersection(normalized):
                kept.append(tx)
        retained=len(kept)
        block=dict(block);block['transactions']=kept
        value=dict(value);value['block']=block
        result=dict(message['params']['result']);result['value']=value
        params=dict(message['params']);params['result']=result
        message=dict(message);message['params']=params
    return message,total,retained


def source_decoder_probe():
    return True

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
        for scope,slot in self.writer.db.execute('SELECT scope,MIN(slot) FROM stream_receipts WHERE sealed=0 AND session=? GROUP BY scope',(self.session,)):
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
    def block(self,subscription,message,seen,*,include_logs=False):
        value=message['params']['result']['value'];slot=value['slot'];block=value.get('block')
        if value.get('err') is not None or not isinstance(block,dict):
            self.writer.gap(subscription.scope,slot,slot,'filtered_block_unavailable')
            raise EvidenceUnavailable('filtered_block_unavailable')
        parent=block.get('parentSlot');at=block.get('blockTime')
        if (type(slot) is not int or type(parent) is not int or not 0<=parent<slot
                or type(at) is not int or at>seen or not block.get('blockhash') or not block.get('previousBlockhash')):
            raise EvidenceUnavailable('finalized_block_fence_shape')
        if subscription.evidence_class in ('transactions','census'):
            transactions=block.get('transactions')
            if not isinstance(transactions,list):
                raise EvidenceUnavailable('filtered_block_bound')
            # Run 369: mentionsAccountOrProgram selected whole blocks. A signature
            # list cannot prove which program was mentioned. Inspect authenticated
            # static AND loaded keys, and persist only the scoped transactions.
            def keys(tx):
                values=tx['transaction']['message']['accountKeys']
                loaded=tx['meta'].get('loadedAddresses') or {}
                return [k if isinstance(k,str) else k['pubkey'] for k in values]+list(loaded.get('writable') or [])+list(loaded.get('readonly') or [])
            transactions=[tx for tx in transactions if subscription.address in keys(tx)]
            if len(transactions)>2048:raise EvidenceUnavailable('filtered_block_bound')
            signatures=[tx['transaction']['signatures'][0] for tx in transactions]
            scoped=dict(method='blockNotification',params=dict(result=dict(value=dict(value,block=dict(block,transactions=transactions)))))
            decoder=FinalizedNotificationDecoder(endpoint_identity=self.endpoint_identity)
            records=decoder.decode(replace(subscription,evidence_class='transactions'),scoped,seen) if subscription.evidence_class=='transactions' else []
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
                if subscription.evidence_class=='census' and include_logs:
                    meta=tx['meta']
                    log=dict(signature=signature,logs=meta.get('logMessages'),err=meta.get('err'))
                    notification=dict(method='logsNotification',params=dict(result=dict(context=dict(slot=slot),value=log)))
                    records=FinalizedNotificationDecoder(endpoint_identity=self.endpoint_identity,log_decoder=self.decoders[subscription.scope]).decode(replace(subscription,evidence_class='logs'),notification,seen)
                    self.writer.ingest(records)
                    self._delivery(subscription.scope,slot,signature,log,seen)
                elif subscription.evidence_class=='transactions':self._delivery(subscription.scope,slot,signature,tx,seen)
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
        from .solana_evidence_control import MAX_RECEIPTS,COMMAND_SECONDS
        # Direct in-process fixture callers retain the same whitelist. Production
        # IPC requires the versioned envelope before it reaches this method.
        if 'request_id' not in request:return self._apply_command(request)
        consumer=request.get('consumer');identity=request['request_id'];expiry=request.get('expires_at')
        now=self.writer.clock()
        if (not isinstance(consumer,str) or not consumer or len(consumer)>128
                or not isinstance(identity,str) or not 1<=len(identity)<=64
                or type(expiry) not in (int,float) or not now-COMMAND_SECONDS*2<=expiry<=now+COMMAND_SECONDS):
            raise EvidenceUnavailable('evidence_command_envelope')
        checksum=digest(request)
        with self.writer.transaction():
            old=self.writer.db.execute('SELECT hash,response FROM command_receipts WHERE consumer=? AND request_id=?',(consumer,identity)).fetchone()
            if old:
                if old[0]!=checksum:raise EvidenceUnavailable('evidence_request_identity_conflict')
                self.writer._count('ipc.deduplicated')
                return json.loads(old[1])
            if expiry<now:raise EvidenceUnavailable('evidence_command_expired')
            self.writer.db.execute('DELETE FROM command_receipts WHERE expires<?',(now-COMMAND_SECONDS*2,))
            if self.writer.db.execute('SELECT COUNT(*) FROM command_receipts').fetchone()[0]>=MAX_RECEIPTS:
                self.writer._count('ipc.receipt_capacity_rejections')
                return dict(ok=False,state='rejected',error='evidence_receipt_capacity',request_id=identity)
            try:
                with self.writer.transaction():self._apply_command(request)
                response=dict(ok=True,state='applied',request_id=identity)
                self.writer._count('ipc.applied')
            except (EvidenceUnavailable,KeyError,TypeError) as exc:
                response=dict(ok=False,state='rejected',request_id=identity,
                              error=str(exc) if isinstance(exc,EvidenceUnavailable) else 'evidence_command_shape')
                self.writer._count('ipc.rejected')
            self.writer.db.execute('INSERT INTO command_receipts VALUES(?,?,?,?,?)',(consumer,identity,checksum,canonical(response),expiry))
            return response

    def _apply_command(self,request):
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


class ServiceState:
    """All SQLite access is confined to the priority owner thread."""
    def __init__(self,path,config):
        from .solana_evidence_plane import EvidenceWriter
        # Whole-program history is an archive workload. Keep a bounded three-minute
        # hot tail plus explicit lifecycle pins, not two hours of every transaction.
        self.writer=EvidenceWriter(path,max_hot_bytes=2*1024*1024*1024)
        self.fence=FinalizedFence(self.writer,endpoint_identity=config.identity,decoders=program_decoders())
        self.fence.health('provider',dict(provider=config.provider,network=config.network,endpoint_identity=config.identity))
        self.fence.health('phase','WARMING');self.fence.health('heartbeat',time.time())
        import os
        self.fence.health('pid',os.getpid())
        self.fence.health('hot_limit_bytes',self.writer.max_hot_bytes)
        self.repair_after={};self.failed=False

    def source(self,sub,message,seen,byte_count):
        from .solana_evidence_transport import Subscription
        with self.writer.transaction():
            self.writer._count('stream_messages');self.writer._count('stream_bytes',byte_count)
            if sub.evidence_class=='blocks':
                # One full block transport is reused by all three scopes. Empty
                # scoped blocks also retain their authenticated parent witness.
                for target in program_subscriptions():
                    if target.evidence_class!='logs':self.fence.block(target,message,seen,include_logs=True)
            else:
                self.writer.ingest(FinalizedNotificationDecoder(endpoint_identity=self.fence.endpoint_identity).decode(sub,message,seen))
            self.writer._count('stream_accepted_messages')
            self.fence.health('phase','ACTIVE');self.fence.health('heartbeat',time.time())

    def interests(self):
        return [r[0] for r in self.writer.db.execute("SELECT s.address FROM service_interests s JOIN interests i ON s.owner=i.owner AND s.scope=i.scope WHERE i.active=1 GROUP BY s.address ORDER BY MIN(i.priority),s.address LIMIT 257")]

    def disconnected(self,reason):
        self.fence.disconnect(reason);self.fence.count('stream_reconnects')
        self.fence.count('disconnect:'+reason)
        self.fence.health('phase','DEGRADED')
        self.fence.health('last_source_error',reason)

    def repair_plan(self):
        now=time.time()
        # One bounded provider page runs outside the owner, at the governor's
        # background priority. Open lifecycles can still repair missing evidence;
        # they never wait for this worker to perform their current-state refresh.
        if self.writer.db.execute("SELECT value FROM meta WHERE key='poisoned'").fetchone():return None
        rows=self.writer.db.execute('SELECT id,scope,lo,hi,repair_cursor,attempts FROM gaps WHERE repaired IS NULL AND hi IS NOT NULL AND pages<16 AND attempts<48 ORDER BY attempts,created LIMIT 64').fetchall()
        for gid,scope,lo,hi,cursor,attempts in rows:
            if now<self.repair_after.get(gid,0):continue
            sub=next((s for s in program_subscriptions() if s.scope==scope),None)
            if sub is None:continue
            state=json.loads(cursor) if cursor else {}
            cfg=dict(transactionDetails='full',sortOrder='asc',limit=100,commitment='finalized',encoding='json',maxSupportedTransactionVersion=1,filters={'slot':{'gte':lo,'lte':hi}})
            if state.get('next'):cfg['paginationToken']=state['next']
            with self.writer.transaction():
                self.writer.db.execute('UPDATE gaps SET attempts=attempts+1 WHERE id=?',(gid,))
                self.writer._count('gap_repair_attempts')
                if attempts:self.writer._count('gap_repair_retries')
            # At most 64 bounded retry leases; completed/old leases are expendable.
            self.repair_after={k:v for k,v in self.repair_after.items() if v>now}
            self.repair_after[gid]=now+min(60,2**min(attempts,6))
            return gid,sub.address,cfg

    def repair_apply(self,plan,value):
        from .solana_evidence_transport import AddressGapRepair
        gid,address,_=plan
        scope=self.writer.db.execute('SELECT scope FROM gaps WHERE id=?',(gid,)).fetchone()[0]
        frontier=self.writer.db.execute('SELECT MAX(slot) FROM stream_receipts WHERE scope=?',(scope,)).fetchone()[0]
        class ReceiptRPC:
            def call(self,*args):return value
        try:
            AddressGapRepair(ReceiptRPC(),self.writer,endpoint_identity=self.fence.endpoint_identity,record_mapper=self.fence.repair_records).step(gid,address,now=time.time(),finalized_through=frontier)
        except (ValueError,KeyError,TypeError) as exc:
            self.fence.count('gap_repair_failures')
            self.fence.health('last_repair_error',str(exc) if isinstance(exc,EvidenceUnavailable) else type(exc).__name__)

    def maintenance(self,http):
        from .solana_evidence_plane import require_storage,storage_health
        now=time.time();self.fence.expire_candidates(now)
        self.fence.health('heartbeat',now);self.fence.health('storage',storage_health(self.writer.path))
        self.fence.health('repair_http',http);require_storage(self.writer.path)
        # A small archive slice yields to the control queue after every commit.
        return self.writer.archive_plan(now-180,max_records=512)

    def archive_commit(self,plan,receipt):
        self.writer.commit_archive(plan,receipt)
        self.writer.retain(time.time()-180,max_records=512,archive_first=False)

    def close(self):
        try:
            self.fence.disconnect('service_shutdown')
            self.fence.health('phase','FAILED' if self.failed else 'OFF')
            self.fence.health('heartbeat',time.time())
        finally:self.writer.close()


async def serve(path,endpoint,*,repair_rpc=None,stop=None):
    """Independent bounded socket handling and one priority SQLite owner."""
    import asyncio
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    import os
    from pathlib import Path
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed
    from .solana_provider_config import AlchemyEndpoint
    from .solana_evidence_transport import Subscription
    from .solana_evidence_plane import EvidenceWriter
    from .solana_evidence_control import PriorityOwner,command_priority,MAX_COMMAND_BYTES
    config=AlchemyEndpoint.parse(endpoint)
    import logging
    logger=logging.Logger('alchemy_evidence_transport');logger.addHandler(logging.NullHandler());logger.propagate=False
    owner=PriorityOwner(lambda:ServiceState(path,config))
    await asyncio.wrap_future(owner.ready)
    decoder_pool=ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'))
    await asyncio.wrap_future(decoder_pool.submit(source_decoder_probe))
    source_program_addresses=tuple(sorted({s.address for s in program_subscriptions()}))
    async def work(fn,priority=1):
        return await asyncio.shield(asyncio.wrap_future(owner.submit(fn,priority=priority)))
    stop=stop or asyncio.Event();socket_path=str(path)+'.sock';Path(socket_path).unlink(missing_ok=True)
    clients=set();counts={}
    def count(key):counts[key]=counts.get(key,0)+1

    async def consumer(reader,stream):
        task=asyncio.current_task();admitted=len(clients)<32
        if admitted:clients.add(task)
        response=dict(ok=False,state='rejected',error='evidence_control_overloaded')
        try:
            if not admitted:count('ipc.overloaded')
            else:
                line=await asyncio.wait_for(reader.readline(),.5)
                if len(line)>MAX_COMMAND_BYTES:raise EvidenceUnavailable('consumer_command_bound')
                request=json.loads(line)
                if not isinstance(request,dict) or not request.get('consumer') or not request.get('request_id') or 'expires_at' not in request:
                    raise EvidenceUnavailable('evidence_command_envelope')
                # Enqueue once. Waiting clients may disconnect; the mutation and
                # receipt remain owned by this task/SQLite actor, never the socket.
                future=owner.submit(lambda state:state.fence.command(request),priority=command_priority(request))
                wrapped=asyncio.wrap_future(future)
                try:response=await asyncio.wait_for(asyncio.shield(wrapped),.4)
                except TimeoutError:
                    count('ipc.pending')
                    response=dict(ok=False,state='pending',request_id=request['request_id'],error='evidence_command_pending')
                    # Consume eventual failures without cancelling accepted work.
                    wrapped.add_done_callback(lambda f:f.exception() if not f.cancelled() else None)
        except (ValueError,KeyError,TypeError,TimeoutError,OSError) as exc:
            count('ipc.rejected')
            response=dict(ok=False,state='rejected',error=str(exc) if isinstance(exc,EvidenceUnavailable) else 'evidence_command_transport')
        finally:
            try:
                stream.write((canonical(response)+'\n').encode())
                if admitted:await asyncio.wait_for(stream.drain(),.2)
            except (OSError,TimeoutError,RuntimeError):count('ipc.disconnected')
            finally:
                stream.close()
                try:
                    if admitted:await asyncio.wait_for(stream.wait_closed(),.2)
                except (OSError,TimeoutError,RuntimeError):pass
                clients.discard(task)

    server=None;tasks=[]
    try:
        server=await asyncio.start_unix_server(consumer,path=socket_path,limit=MAX_COMMAND_BYTES+1,backlog=32)
        os.chmod(socket_path,0o600)
        class StreamDispatchCapacity(OSError):
            pass

        async def source():
            while not stop.is_set():
                connection_tasks=[]
                try:
                    # The websocket reader is deliberately independent of SQLite
                    # ingestion. Run 371 proved that awaiting the owner after every
                    # message can fill the protocol receive queue and starve pong
                    # handling while persistence/compaction/gap repair is busy.
                    async with connect(config.stream_url,logger=logger,max_size=STREAM_MAX_MESSAGE_BYTES,max_queue=STREAM_PROTOCOL_QUEUE_FRAMES,ping_interval=10,ping_timeout=10,open_timeout=10) as ws:
                        from collections import Counter,deque
                        number=1;pending={1:Subscription('service','chain:solana','all','blocks',2)};active={};registered=set();retiring=set();retired_subscriptions=deque(maxlen=256)
                        inbound=asyncio.Queue(maxsize=STREAM_DISPATCH_MAX_MESSAGES)
                        inbound_bytes=0
                        await ws.send(canonical(pending[1].request(1)))

                        async def sync_subscriptions():
                            nonlocal number
                            wanted=set(await work(lambda state:state.interests(),0))
                            if len(wanted)>256:raise EvidenceUnavailable('restored_subscription_capacity')
                            for sid,sub in list(active.items()):
                                if sub.evidence_class=='account' and sub.address not in wanted:
                                    number+=1;retiring.add(number)
                                    retired_subscriptions.append(sid)
                                    await ws.send(canonical(dict(jsonrpc='2.0',id=number,method='accountUnsubscribe',params=[sid])))
                                    del active[sid];registered.discard(sub.address)
                            for address in sorted(wanted-registered):
                                number+=1;sub=Subscription('service','account:'+address,address,'account',0)
                                pending[number]=sub;registered.add(address);await ws.send(canonical(sub.request(number)))
                            return wanted

                        async def receive():
                            nonlocal inbound_bytes
                            while not stop.is_set():
                                try:raw=await asyncio.wait_for(ws.recv(),.5)
                                except TimeoutError:continue
                                size=len(raw) if isinstance(raw,str) else STREAM_MAX_MESSAGE_BYTES+1
                                if (size>STREAM_MAX_MESSAGE_BYTES or inbound.full()
                                        or inbound_bytes+size>STREAM_DISPATCH_MAX_BYTES):
                                    count('stream.dispatch_queue_overflow')
                                    counts['stream.dispatch_bytes_peak']=max(
                                        counts.get('stream.dispatch_bytes_peak',0),inbound_bytes)
                                    raise StreamDispatchCapacity() from None
                                inbound_bytes+=size
                                inbound.put_nowait((raw,time.time(),size))
                                counts['stream.received_messages']=counts.get('stream.received_messages',0)+1
                                counts['stream.raw_message_peak_bytes']=max(
                                    counts.get('stream.raw_message_peak_bytes',0),size)
                                counts['stream.dispatch_queue_peak']=max(
                                    counts.get('stream.dispatch_queue_peak',0),inbound.qsize())
                                counts['stream.dispatch_bytes_peak']=max(
                                    counts.get('stream.dispatch_bytes_peak',0),inbound_bytes)

                        async def process():
                            nonlocal inbound_bytes
                            wanted=set()
                            while not stop.is_set():
                                try:raw,seen,size=await asyncio.wait_for(inbound.get(),.5)
                                except TimeoutError:
                                    wanted=await sync_subscriptions()
                                    continue
                                try:
                                    wanted=await sync_subscriptions()
                                    decode_started=time.monotonic()
                                    decoded=decoder_pool.submit(
                                        decode_source_message,raw,config.credential,source_program_addresses)
                                    message,source_transactions,retained_transactions=await asyncio.shield(
                                        asyncio.wrap_future(decoded))
                                    decode_us=int((time.monotonic()-decode_started)*1_000_000)
                                    counts['stream.decode_process_messages']=counts.get('stream.decode_process_messages',0)+1
                                    counts['stream.decode_peak_microseconds']=max(
                                        counts.get('stream.decode_peak_microseconds',0),decode_us)
                                    counts['stream.decode_total_microseconds']=(
                                        counts.get('stream.decode_total_microseconds',0)+decode_us)
                                    counts['stream.source_transactions']=(
                                        counts.get('stream.source_transactions',0)+source_transactions)
                                    counts['stream.retained_transactions']=(
                                        counts.get('stream.retained_transactions',0)+retained_transactions)
                                    if message.get('id') in retiring:
                                        retiring.remove(message['id']);continue
                                    if 'id' in message:
                                        sub=pending.pop(message['id'])
                                        if 'error' in message or type(message.get('result')) is not int:raise EvidenceUnavailable('authoritative_subscription_rejected')
                                        active[message['result']]=sub
                                        status=dict(active=len(active),by_evidence_class=dict(Counter(s.evidence_class for s in active.values())),pending=len(pending),wanted_accounts=len(wanted))
                                        await work(lambda state:state.fence.health('subscriptions',status));continue
                                    sub=active.get((message.get('params') or {}).get('subscription'))
                                    if sub is None and (message.get('params') or {}).get('subscription') in retired_subscriptions:continue
                                    if sub is None:raise EvidenceUnavailable('unknown_source_subscription')
                                    await work(lambda state:state.source(sub,message,seen,len(raw)),0 if sub.evidence_class=='account' else 2)
                                finally:
                                    inbound_bytes=max(0,inbound_bytes-size)
                                    inbound.task_done()

                        async def loop_watchdog():
                            expected=time.monotonic()+STREAM_WATCHDOG_SECONDS
                            while not stop.is_set():
                                await asyncio.sleep(STREAM_WATCHDOG_SECONDS)
                                now=time.monotonic()
                                lag_us=int(max(0.0,now-expected)*1_000_000)
                                counts['stream.event_loop_lag_peak_microseconds']=max(
                                    counts.get('stream.event_loop_lag_peak_microseconds',0),lag_us)
                                expected=now+STREAM_WATCHDOG_SECONDS

                        receiver=asyncio.create_task(receive());processor=asyncio.create_task(process())
                        watchdog=asyncio.create_task(loop_watchdog());stopper=asyncio.create_task(stop.wait())
                        connection_tasks=[receiver,processor,watchdog,stopper]
                        done,_=await asyncio.wait(connection_tasks,return_when=asyncio.FIRST_COMPLETED)
                        for task in done:task.result()
                except (OSError,ValueError,KeyError,TypeError,TimeoutError,ConnectionClosed) as exc:
                    if stop.is_set():return
                    if isinstance(exc,EvidenceConflict) or str(exc) in ('hot_store_capacity','storage_capacity_critical'):raise
                    reason=('local_receive_dispatch_capacity' if isinstance(exc,StreamDispatchCapacity)
                            else disconnect_classification(exc))
                    await work(lambda state:state.disconnected(reason))
                    try:await asyncio.wait_for(stop.wait(),1)
                    except TimeoutError:pass
                finally:
                    for task in connection_tasks:task.cancel()
                    if connection_tasks:await asyncio.gather(*connection_tasks,return_exceptions=True)

        async def repair():
            while not stop.is_set():
                try:
                    if repair_rpc is not None:
                        plan=await work(lambda state:state.repair_plan(),4)
                        if plan:
                            value=await asyncio.to_thread(repair_rpc.call,'getTransactionsForAddress',[plan[1],plan[2]],False)
                            await work(lambda state:state.repair_apply(plan,value),4)
                except (OSError,ValueError,KeyError,TypeError,TimeoutError) as exc:
                    if str(exc)!='evidence_background_yield':
                        await work(lambda state:state.fence.count('gap_repair_failures'),3)
                try:await asyncio.wait_for(stop.wait(),1)
                except TimeoutError:pass

        async def maintenance():
            next_health=0
            while not stop.is_set():
                plan=None
                try:
                    if time.monotonic()>=next_health:
                        http=repair_rpc.telemetry() if repair_rpc is not None and hasattr(repair_rpc,'telemetry') else {}
                        plan=await work(lambda state:state.maintenance(http),4);next_health=time.monotonic()+1
                        snapshot=dict(counts)
                        await work(lambda state:state.fence.health('ipc',snapshot),1)
                    else:plan=await work(lambda state:state.writer.archive_plan(time.time()-180,max_records=512),4)
                    if plan:
                        receipt=await asyncio.to_thread(EvidenceWriter.write_archive,path,plan)
                        await work(lambda state:state.archive_commit(plan,receipt),4)
                except EvidenceUnavailable as exc:
                    if str(exc)!='evidence_background_yield':raise
                try:await asyncio.wait_for(stop.wait(),.1 if plan else 1)
                except TimeoutError:pass

        tasks=[asyncio.create_task(source()),asyncio.create_task(repair()),asyncio.create_task(maintenance()),asyncio.create_task(stop.wait())]
        done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        for task in done:task.result()
    except BaseException:
        await work(lambda state:setattr(state,'failed',True),0)
        raise
    finally:
        await work(lambda state:state.fence.health('phase','DRAINING'),0)
        if server:server.close();await server.wait_closed()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        if clients:await asyncio.gather(*list(clients),return_exceptions=True)
        await asyncio.to_thread(owner.close)
        await asyncio.to_thread(decoder_pool.shutdown,wait=True,cancel_futures=True)
        Path(socket_path).unlink(missing_ok=True)
