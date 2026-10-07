"""Finalized filtered-block fences over the existing single-writer evidence store.

Only this source adapter can seal coverage. Consumers send lifecycle interests and
read SQLite; they cannot send records, receipts, frontiers or interval proofs.
A receipt authenticates a block's filtered census. Its linked finalized child is
required to seal it. Silence, root notifications and socket ACKs never seal data.
"""
from contextlib import contextmanager
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
STREAM_PREPARED_MAX_BYTES=16*1024*1024
STREAM_PROTOCOL_QUEUE_FRAMES=32
STREAM_DISPATCH_MAX_MESSAGES=64
STREAM_DISPATCH_MAX_BYTES=96*1024*1024
STREAM_PROCESS_DECODE_MIN_BYTES=1024*1024
STREAM_DECODE_WORKERS=2
# Keep each synchronous=FULL owner transaction no larger than one maximum provider
# frame while amortizing fsync cost across consecutive smaller finalized blocks.
STREAM_COMMIT_BATCH_MAX_MESSAGES=8
STREAM_COMMIT_BATCH_MAX_BYTES=16*1024*1024
# The immutable archive file may still contain up to 1,000 records, but hot-DB
# mutation is deliberately smaller so one archive receipt cannot monopolize the
# sole SQLite owner while source frames queue behind it.
ARCHIVE_COMMIT_SLICE_RECORDS=512
STREAM_SUBSCRIPTION_SYNC_SECONDS=.25
STREAM_WATCHDOG_SECONDS=.1
STREAM_SOURCE_IDLE_SECONDS=20
STREAM_COMMIT_STALL_SECONDS=15


def decode_source_message(raw,credential,program_addresses=(),endpoint_identity=None,observed_at=None):
    """Decode and authority-preservingly compact one provider frame.

    This function is process-safe. For full block notifications it inspects every
    transaction's static and loaded account keys before dropping unrelated bodies.
    The parent receives only the union relevant to Pump, PumpSwap, or Meteora.
    """
    if not isinstance(raw,(str,bytes)) or len(raw)>STREAM_MAX_MESSAGE_BYTES:
        raise EvidenceUnavailable('source_message_size_limit')
    needle=credential.encode() if isinstance(raw,bytes) else credential
    if needle and needle in raw:
        raise ValueError('provider_credential_publication_rejected')
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
    if endpoint_identity is not None and observed_at is not None and message.get('method')=='blockNotification':
        scopes={};prepared_bytes=0;budget=[STREAM_PREPARED_MAX_BYTES]
        for sub in program_subscriptions():
            if sub.evidence_class=='logs':continue
            try:
                scoped=prepare_block_scope(sub,message,observed_at,endpoint_identity,program_decoders(),include_logs=True,budget=budget)
            except PreparationBudgetExceeded:
                # An unusual multi-event block may expand beyond the preparation
                # budget. Retain its exact former serial path, never drop content.
                result=PreparedSource(message);result.scopes=None;result.prepared_bytes=0
                return result,total,retained
            prepared_bytes=STREAM_PREPARED_MAX_BYTES-budget[0]
            scopes[sub.scope]=scoped
        result=PreparedSource(message);result.scopes=scopes;result.prepared_bytes=prepared_bytes
        # Economic bodies now live only in the prepared records. Do not retain
        # a second full transaction tree while waiting for the ordered commit.
        result['params']=dict(message['params'],result=dict(message['params']['result'],
            value=dict(value,block=dict(block,transactions=[]))))
        message=result
    return message,total,retained


class PreparedSource(dict):
    """Local process-pool product, impossible to forge through provider JSON."""
    pass


class PreparationBudgetExceeded(Exception):pass

def prepare_block_scope(subscription,message,seen,endpoint_identity,decoders,*,include_logs,budget):
    """Pure decode/hash/compression, with no database or authority publication."""
    from .solana_evidence_plane import prepare_record
    def prepare(record):
        result=prepare_record(record)
        budget[0]-=result.byte_count
        if budget[0]<0:raise PreparationBudgetExceeded()
        return result
    value=message['params']['result']['value'];slot=value['slot'];block=value['block']
    transactions=block.get('transactions')
    if not isinstance(transactions,list):raise EvidenceUnavailable('filtered_block_bound')
    def keys(tx):
        values=tx['transaction']['message']['accountKeys'];loaded=tx['meta'].get('loadedAddresses') or {}
        return [k if isinstance(k,str) else k['pubkey'] for k in values]+list(loaded.get('writable') or [])+list(loaded.get('readonly') or [])
    transactions=[tx for tx in transactions if subscription.address in keys(tx)]
    if len(transactions)>2048:raise EvidenceUnavailable('filtered_block_bound')
    signatures=[tx['transaction']['signatures'][0] for tx in transactions]
    scoped=dict(method='blockNotification',params=dict(result=dict(value=dict(value,block=dict(block,transactions=transactions)))))
    decoder=FinalizedNotificationDecoder(endpoint_identity=endpoint_identity)
    records=decoder.decode(replace(subscription,evidence_class='transactions'),scoped,seen) if subscription.evidence_class=='transactions' else []
    enriched=[];deliveries=[];batches=[]
    for tx,record in zip(transactions,records):
        body=dict(record.payload);body.pop('transactionIndex',None)
        enriched.append(prepare(replace(record,payload=body,transaction_index=None,
            addresses=tuple(sorted(set(keys(tx)+[subscription.address]))))))
    if enriched:batches.append(tuple(enriched))
    for tx,signature in zip(transactions,signatures):
        if subscription.evidence_class=='census' and include_logs:
            meta=tx['meta'];log=dict(signature=signature,logs=meta.get('logMessages'),err=meta.get('err'))
            notification=dict(method='logsNotification',params=dict(result=dict(context=dict(slot=slot),value=log)))
            rows=FinalizedNotificationDecoder(endpoint_identity=endpoint_identity,log_decoder=decoders[subscription.scope]).decode(replace(subscription,evidence_class='logs'),notification,seen)
            if rows:batches.append(tuple(prepare(row) for row in rows))
            deliveries.append((signature,digest(log)))
        elif subscription.evidence_class=='transactions':deliveries.append((signature,digest(tx)))
    # Prepared scopes already share the 16 MiB frame budget. Group their exact
    # ordered records when the existing ingestion count bound permits it.
    if len(batches)>1 and sum(map(len,batches))<=2048:
        batches=[tuple(row for batch in batches for row in batch)]
    return dict(signatures=signatures,batches=tuple(batches),deliveries=tuple(deliveries),
                endpoint_identity=endpoint_identity,observed_at=seen,slot=slot)


def source_decoder_probe():
    return True

class FinalizedFence:
    def __init__(self,writer,*,endpoint_identity,decoders=None):
        import threading
        self.writer=writer;self.endpoint_identity=endpoint_identity
        self.decoders=decoders or {};self.session=uuid.uuid4().hex
        # A thread-safe hint, never subscription/evidence authority. The owner
        # still reads durable interests at the original priority and cadence.
        self.subscriptions_dirty=threading.Event();self.subscriptions_dirty.set()
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

    def _health(self,key,value):
        from .solana_provider_config import public_value
        public_value(value)
        self.writer.db.execute('INSERT OR REPLACE INTO service_health VALUES(?,?)',(key,canonical(value)))

    def health(self,key,value):
        with self.writer.transaction():
            self._health(key,value)

    def count(self,key,n=1):
        with self.writer.transaction():self.writer._count(key,n)

    def expire_candidates(self,now):
        with self.writer.transaction():
            n=self.writer.db.execute("UPDATE interests SET active=0 WHERE active=1 AND lifecycle IN ('candidate','research') AND updated<?",(now-1200,)).rowcount
            self.writer._count('expired_candidate_interests',n)
            self.writer.db.execute('DELETE FROM service_interests WHERE NOT EXISTS(SELECT 1 FROM interests i WHERE i.owner=service_interests.owner AND i.scope=service_interests.scope AND i.active=1)')
            self.writer.db.execute('DELETE FROM interests WHERE active=0 AND updated<?',(now-7200,))
            self.writer.db.execute('DELETE FROM interest_checkpoints WHERE NOT EXISTS(SELECT 1 FROM interests i WHERE i.owner=interest_checkpoints.owner AND i.scope=interest_checkpoints.scope)')
            self.writer.db.execute('DELETE FROM interest_owners WHERE NOT EXISTS(SELECT 1 FROM interests i WHERE i.owner=interest_owners.owner)')
        if n:self.subscriptions_dirty.set()

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
        self._delivery_hash(scope,slot,signature,digest(payload),seen)

    def _delivery_hash(self,scope,slot,signature,checksum,seen):
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
    def block(self,subscription,message,seen,*,include_logs=False,prepared=None):
        value=message['params']['result']['value'];slot=value['slot'];block=value.get('block')
        if value.get('err') is not None or not isinstance(block,dict):
            self.writer.gap(subscription.scope,slot,slot,'filtered_block_unavailable')
            raise EvidenceUnavailable('filtered_block_unavailable')
        parent=block.get('parentSlot');at=block.get('blockTime')
        if (type(slot) is not int or type(parent) is not int or not 0<=parent<slot
                or type(at) is not int or at>seen or not block.get('blockhash') or not block.get('previousBlockhash')):
            raise EvidenceUnavailable('finalized_block_fence_shape')
        if subscription.evidence_class in ('transactions','census'):
            if prepared is None:
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
                        if records:self.writer.ingest(records)
                        self._delivery(subscription.scope,slot,signature,log,seen)
                    elif subscription.evidence_class=='transactions':self._delivery(subscription.scope,slot,signature,tx,seen)
            else:
                if (prepared['endpoint_identity']!=self.endpoint_identity or prepared['observed_at']!=seen or prepared['slot']!=slot):
                    raise EvidenceUnavailable('prepared_source_identity_mismatch')
                signatures=prepared['signatures']
                for records in prepared['batches']:self.writer.ingest(records)
                with self.writer.transaction():
                    self.writer.db.executemany('INSERT OR IGNORE INTO stream_order VALUES(?,?,?,?,?)',
                        [(subscription.scope,slot,sig,rank,block['blockhash']) for rank,sig in enumerate(signatures)])
                for signature,checksum in prepared['deliveries']:
                    self._delivery_hash(subscription.scope,slot,signature,checksum,seen)

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
        response=self._command(request)
        # Signal after the command/receipt transaction has completed, even when
        # its socket waiter has already disconnected. Failed mutations grant no
        # subscription authority; a reconnect always reloads durable interests.
        if request.get('op') in ('interest','release') and response.get('ok'):
            self.subscriptions_dirty.set()
        return response

    def _command(self,request):
        from .solana_evidence_control import MAX_RECEIPTS,COMMAND_SECONDS,command_envelope
        # Direct in-process fixture callers retain the same whitelist. Production
        # IPC requires the versioned envelope before it reaches this method.
        if 'request_id' not in request:return self._apply_command(request)
        now=self.writer.clock()
        consumer,identity,expiry=command_envelope(request,now)
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
        if op in ('interest','release','ack','advance_interest'):
            owner=request['owner'];consumer=request.get('consumer',owner)
            if not isinstance(owner,str) or len(owner)>256 or not isinstance(consumer,str) or len(consumer)>128:
                raise EvidenceUnavailable('interest_owner_bound')
            known=self.writer.db.execute('SELECT consumer FROM interest_owners WHERE owner=?',(owner,)).fetchone()
            if known and known[0]!=consumer:raise EvidenceUnavailable('interest_owned_by_other_consumer')
            if not known and op=='advance_interest':raise EvidenceUnavailable('interest_checkpoint_unknown_owner')
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
        elif op=='advance_interest':
            self.writer.advance_interest(request['owner'],request['scope'],
                lower_slot=request['lower_slot'],consumed_slot=request['consumed_slot'],
                checkpoint_hash=request['checkpoint_hash'])
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
    from .solana_program_decoders import pump_events,pumpswap_trade_events
    from .solana_evidence_runtime import PUMP_SCOPE,SWAP_SCOPE
    return {PUMP_SCOPE:pump_events,SWAP_SCOPE:pumpswap_trade_events}


class ServiceState:
    """All SQLite access is confined to the priority owner thread."""
    def __init__(self,path,config):
        from .solana_evidence_plane import EvidenceWriter
        # Whole-program history is an archive workload. Keep a bounded three-minute
        # hot tail plus explicit lifecycle pins, not two hours of every transaction.
        self.writer=EvidenceWriter(path,max_hot_bytes=2*1024*1024*1024)
        # FULL WAL commits remain durable. The independently scheduled bounded
        # checkpoint worker owns PASSIVE checkpoints; SQLite's default automatic
        # checkpoint otherwise copies/syncs the database inside source commits
        # (and again in subsequent metadata commits while a reader pins the WAL).
        # Keep this service-only: standalone writers need their default policy.
        self.writer.db.execute('PRAGMA wal_autocheckpoint=0')
        # Retention deletes fan out across the address index. SQLite's 2 MiB
        # default cache repeatedly evicts those pages, and file-backed statement
        # rollback journals copy them again for each delete. Give the sole owner
        # a fixed 16 MiB working cache and keep temporary rollback work in memory.
        # Source/retention transaction bounds and cache spill remain enabled;
        # durable evidence still uses FULL-synchronous WAL and the same 2 GiB
        # guard. Configure before any temporary schema or owner work is created.
        self.writer.db.execute('PRAGMA cache_size=-16384')
        self.writer.db.execute('PRAGMA temp_store=MEMORY')
        self.fence=FinalizedFence(self.writer,endpoint_identity=config.identity,decoders=program_decoders())
        self.fence.health('provider',dict(provider=config.provider,network=config.network,endpoint_identity=config.identity))
        self.fence.health('phase','WARMING');self.fence.health('heartbeat',time.time())
        import os
        self.fence.health('pid',os.getpid())
        self.fence.health('hot_limit_bytes',self.writer.max_hot_bytes)
        self.repair_after={};self.failed=False
        prior=self.writer.db.execute("SELECT value FROM service_health WHERE key='storage_maintenance'").fetchone()
        self.storage_metrics=json.loads(prior[0]) if prior else {}
        self.last_measured_archive_receipt=None

    def _storage_stage(self,name,fn):
        """Fixed stage names, numeric costs only; retained across service restarts."""
        if name not in ('source_commit','archive_plan','archive_commit','retention','repair_apply'):
            raise EvidenceUnavailable('storage_stage_identity')
        started=time.monotonic()
        try:return fn()
        except Exception as exc:
            import sqlite3
            yielded=(isinstance(exc,sqlite3.OperationalError) and str(exc)=='interrupted'
                     or isinstance(exc,EvidenceUnavailable) and str(exc)=='evidence_background_yield')
            suffix='yielded' if yielded else 'failed'
            key=name+'.'+suffix;self.storage_metrics[key]=self.storage_metrics.get(key,0)+1
            raise
        finally:
            elapsed=int((time.monotonic()-started)*1_000_000)
            for suffix,value in (('calls',1),('total_microseconds',elapsed)):
                key=name+'.'+suffix;self.storage_metrics[key]=self.storage_metrics.get(key,0)+value
            key=name+'.peak_microseconds';self.storage_metrics[key]=max(self.storage_metrics.get(key,0),elapsed)

    def _source_locked(self,sub,message,seen,byte_count):
        self.writer._count('stream_messages');self.writer._count('stream_bytes',byte_count)
        if sub.evidence_class=='blocks':
            # One full block transport is reused by all three scopes. Empty
            # scoped blocks also retain their authenticated parent witness.
            for target in program_subscriptions():
                if target.evidence_class!='logs':
                    prepared=message.scopes.get(target.scope) if isinstance(message,PreparedSource) and message.scopes is not None else None
                    self.fence.block(target,message,seen,include_logs=True,prepared=prepared)
        else:
            self.writer.ingest(FinalizedNotificationDecoder(endpoint_identity=self.fence.endpoint_identity).decode(sub,message,seen))
        self.writer._count('stream_accepted_messages')
        # This method always runs under the writer transaction. Avoid two nested
        # SAVEPOINT pairs per frame for heartbeat metadata.
        self.fence._health('phase','ACTIVE');self.fence._health('heartbeat',time.time())

    def source(self,sub,message,seen,byte_count):
        with self.writer.source_frame():
            self._source_locked(sub,message,seen,byte_count)

    def source_batch(self,items):
        # One timer per bounded owner admission, never per record. Execution is
        # separate from the work() admission timer and includes durable COMMIT.
        return self._storage_stage('source_commit',lambda:self._source_batch(items))

    def _source_batch(self,items):
        """Commit consecutive block/account frames with one durable outer fsync.

        Each frame retains its own SAVEPOINT so a malformed later frame cannot
        contaminate prior valid frames. Prior frames are committed before the
        original exception is re-raised, matching the former one-frame-at-a-time
        failure boundary.
        """
        items=tuple(items)
        if (not 1<=len(items)<=STREAM_COMMIT_BATCH_MAX_MESSAGES
                or any(getattr(sub,'evidence_class',None) not in ('blocks','account')
                       or type(size) is not int or size<0
                       for sub,_,_,size in items)
                or sum(size for _,_,_,size in items)>STREAM_COMMIT_BATCH_MAX_BYTES):
            raise EvidenceUnavailable('stream_commit_batch_bound')
        failure=None;committed=0
        with self.writer.transaction():
            for item in items:
                try:
                    with self.writer.source_frame():
                        self._source_locked(*item)
                except Exception as exc:
                    failure=exc
                    break
                committed+=1
        if failure is not None:
            raise failure
        return committed

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
        rows=self.writer.db.execute('SELECT id,scope,lo,hi,repair_cursor,attempts,pages FROM gaps WHERE repaired IS NULL AND hi IS NOT NULL AND pages<16 AND attempts<48 ORDER BY attempts,created LIMIT 64').fetchall()
        for gid,scope,lo,hi,cursor,attempts,pages in rows:
            if now<self.repair_after.get(gid,0):continue
            sub=next((s for s in program_subscriptions() if s.scope==scope),None)
            if sub is None:continue
            state=json.loads(cursor) if cursor else {}
            cfg=dict(transactionDetails='full',sortOrder='asc',limit=100,commitment='finalized',encoding='json',maxSupportedTransactionVersion=1,filters={'slot':{'gte':lo,'lte':hi}})
            if state.get('next'):cfg['paginationToken']=state['next']
            # Each successful page has one dispatch attempt and one durable
            # apply receipt. Pagination itself is not a failed provider retry.
            failures=max(0,attempts-2*pages)
            with self.writer.transaction():
                self.writer.db.execute('UPDATE gaps SET attempts=attempts+1 WHERE id=?',(gid,))
                self.writer._count('gap_repair_attempts')
                if failures:self.writer._count('gap_repair_retries')
            # At most 64 bounded retry leases; completed/old leases are expendable.
            self.repair_after={k:v for k,v in self.repair_after.items() if v>now}
            self.repair_after[gid]=now+min(60,2**min(failures,6))
            return gid,sub.address,cfg

    def repair_apply(self,plan,value):
        from .solana_evidence_transport import AddressGapRepair
        gid,address,_=plan
        scope=self.writer.db.execute('SELECT scope FROM gaps WHERE id=?',(gid,)).fetchone()[0]
        frontier=self.writer.db.execute('SELECT MAX(slot) FROM stream_receipts WHERE scope=?',(scope,)).fetchone()[0]
        class ReceiptRPC:
            def call(self,*args):return value
        try:
            self._storage_stage('repair_apply',lambda:AddressGapRepair(ReceiptRPC(),self.writer,endpoint_identity=self.fence.endpoint_identity,record_mapper=self.fence.repair_records).step(gid,address,now=time.time(),finalized_through=frontier))
            self.repair_after[gid]=time.time()+1
        except (ValueError,KeyError,TypeError) as exc:
            self.fence.count('gap_repair_failures')
            self.fence.health('last_repair_error',str(exc) if isinstance(exc,EvidenceUnavailable) else type(exc).__name__)

    def maintenance_health(self,http):
        from .solana_evidence_plane import require_storage,storage_health
        now=time.time();self.fence.expire_candidates(now)
        self.fence.health('heartbeat',now);self.fence.health('storage',storage_health(self.writer.path))
        self.fence.health('repair_http',http);require_storage(self.writer.path)
        self.fence.health('storage_maintenance',dict(self.storage_metrics))

    def maintenance(self,http):
        self.maintenance_health(http)
        # A small archive slice yields to the control queue after every commit.
        snapshot=self.archive_plan()
        if snapshot is None:self.retention()
        return snapshot

    def publish_health(self,http,ipc,scheduler):
        # Telemetry is background work, not a lifecycle/foreground request. One
        # owner request cannot enqueue urgent callbacks that interrupt our own
        # archive/retention transactions. Actual source heartbeats and
        # finalized frontiers remain part of their durable source commit.
        with self.writer.transaction():
            self.maintenance_health(http)
            self.fence.health('ipc',ipc)
            self.fence.health('owner_scheduler',scheduler)

    def archive_plan(self):
        snapshot=self._storage_stage('archive_plan',lambda:self.writer.archive_snapshot(time.time()-180,max_records=1000))
        if snapshot:
            self.storage_metrics['archive_snapshot.encoded_peak_bytes']=max(self.storage_metrics.get('archive_snapshot.encoded_peak_bytes',0),snapshot['encoded_bytes'])
            self.storage_metrics['archive_snapshot.records_peak']=max(self.storage_metrics.get('archive_snapshot.records_peak',0),len(snapshot['rows']))
        return snapshot

    def archive_commit(self,plan,receipt,*,retain=True):
        metrics={}
        for name in ('prepare_microseconds','publish_microseconds','records'):
            value=(receipt or {}).get('worker_metrics',{}).get(name,0)
            if type(value) is not int or value<0:raise EvidenceUnavailable('archive_worker_metric')
            metrics[name]=value
        # A retained receipt may be committed repeatedly after SQL yield. Count
        # worker cost once, not once per owner retry. Only one bounded receipt
        # reference is retained; it is telemetry, never commit authority.
        if receipt is not self.last_measured_archive_receipt:
            self.last_measured_archive_receipt=receipt
            for name,value in metrics.items():
                key='archive_worker.'+name
                self.storage_metrics[key+'.total']=self.storage_metrics.get(key+'.total',0)+value
                self.storage_metrics[key+'.peak']=max(self.storage_metrics.get(key+'.peak',0),value)
        self._storage_stage('archive_commit',lambda:self.writer.commit_archive(plan,receipt))
        if retain:self.retention()

    def archive_commit_slice(self,plan,receipt):
        """Commit one bounded part of an already durable immutable archive."""
        if not plan:return []
        batch=plan[:ARCHIVE_COMMIT_SLICE_RECORDS]
        self.archive_commit(batch,receipt,retain=False)
        return plan[len(batch):]

    def archive_commit_slice_and_plan(self,plan,receipt):
        """Finish one existing bounded mutation and prepare its successor input.

        Source and cleanup still interleave between 512-record commit slices.
        Only the last slice also selects the next immutable snapshot: placing
        that dependent read behind a fresh source admission idles the archive
        worker under sustained multi-frame source batches. No larger write
        transaction or additional in-flight archive is introduced.

        If the following read yields, the caller retains the published receipt
        and retries idempotently; committed rows cannot be selected a second time.
        """
        remaining=self.archive_commit_slice(plan,receipt)
        return remaining,None if remaining else self.archive_plan()

    def archive_commit_and_plan(self,plan,receipt):
        self.archive_commit(plan,receipt,retain=False)
        return self.archive_plan()

    @contextmanager
    def housekeeping_retention(self):
        """One owner-affine eligible turn; ordinary retirement hooks stay zero-argument."""
        previous=getattr(self,'_housekeeping_retention',False)
        self._housekeeping_retention=True
        try:
            yield
        finally:
            self._housekeeping_retention=previous

    def retention(self, *, housekeeping_first=False):
        import sqlite3
        from .solana_retention_outcome import RetentionProgress
        if self.writer.db.in_transaction:
            raise EvidenceUnavailable('retention_inside_source_transaction')
        self.writer.last_retention_progress=RetentionProgress()
        housekeeping_first=housekeeping_first or getattr(self,'_housekeeping_retention',False)
        retention_options=dict(housekeeping_first=True) if housekeeping_first else {}
        try:
            self._storage_stage('retention',lambda:self.writer.retain(
                time.time()-180,max_records=1000,archive_first=False,checkpoint=False,
                **retention_options))
        except EvidenceUnavailable as exc:
            if str(exc)!='evidence_background_yield':raise
            self.writer.last_retention_progress.interrupted=True
        except sqlite3.OperationalError as exc:
            # A prior interrupted query is not evidence that a later disk/busy
            # error was a cooperative yield. Preserve unrelated storage failures.
            if (str(exc) != 'interrupted' or
                    not getattr(self.writer,'_background_sql_interrupted',False)):
                raise
            report=self.writer.last_retention_progress
            report.interrupted=True;report.yield_reason='urgent_sql'
        outcome=self.writer.last_retention_progress.snapshot()
        for name in ('retired_records','continuity_rows','housekeeping_rows',
                     'floor_updates','committed_slices','examined_scopes'):
            key='retention_outcome.'+name
            self.storage_metrics[key]=self.storage_metrics.get(key,0)+getattr(outcome,name)
        state='pending' if outcome.pending is True else 'idle' if outcome.pending is False else 'unknown'
        key='retention_outcome.'+state
        self.storage_metrics[key]=self.storage_metrics.get(key,0)+1
        self.storage_metrics['retention_outcome.interrupted']=(
            self.storage_metrics.get('retention_outcome.interrupted',0)+int(outcome.interrupted))
        return outcome

    def close(self):
        try:
            self.fence.health('storage_maintenance',dict(self.storage_metrics))
            self.fence.disconnect('service_shutdown')
            self.fence.health('phase','FAILED' if self.failed else 'OFF')
            self.fence.health('heartbeat',time.time())
        finally:self.writer.close()


async def serve(path,endpoint,*,repair_rpc=None,stop=None,source_driver=None):
    """Only the shared Model B owner may start a Solana evidence service.

    The former lane-local startup producer is archived with PR #121's legacy
    source. Lane decoder/fixture helpers above do not start provider intake.
    """
    from meme_machine.solana_evidence_service import serve as primary
    return await primary(path,endpoint,repair_rpc=repair_rpc,stop=stop,source_driver=source_driver)
