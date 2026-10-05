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
    from .solana_evidence_control import PriorityOwner,PendingCommands,MAX_COMMAND_BYTES
    config=AlchemyEndpoint.parse(endpoint)
    import logging
    logger=logging.Logger('alchemy_evidence_transport');logger.addHandler(logging.NullHandler());logger.propagate=False
    owner=PriorityOwner(lambda:ServiceState(path,config))
    pending_commands=PendingCommands(owner)
    await asyncio.wrap_future(owner.ready)
    decoder_pool=ProcessPoolExecutor(max_workers=STREAM_DECODE_WORKERS,mp_context=multiprocessing.get_context('spawn'))
    await asyncio.gather(*(asyncio.wrap_future(decoder_pool.submit(source_decoder_probe))
                           for _ in range(STREAM_DECODE_WORKERS)))
    source_program_addresses=tuple(sorted({s.address for s in program_subscriptions()}))
    async def work(fn,priority=1,*,label=None,accepted=None,admit_before=None):
        if label not in (None,'source_commit','archive_plan','archive_commit_plan','retention','maintenance_health','health_ipc','health_scheduler','checkpoint_prepare','checkpoint_finish','maintenance_decision'):
            raise EvidenceUnavailable('owner_stage_identity')
        submitted=time.monotonic();execution=[None,None]
        def timed(state):
            started=time.monotonic();execution[0]=started
            try:value=fn(state)
            finally:execution[1]=time.monotonic()
            return value,int((started-submitted)*1_000_000),int((execution[1]-started)*1_000_000)
        submit_options=dict(priority=priority)
        if admit_before is not None:submit_options['admit_before']=admit_before
        future=owner.submit(timed,**submit_options)
        if accepted is not None:accepted(future)
        wrapped=asyncio.wrap_future(future)
        try:value,queued,executed=await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            # Accepted owner work outlives a cancelled maintenance waiter. Its
            # recorded outcome must be consumed even when cooperative SQL yield
            # finishes after shutdown has cancelled that background coroutine.
            wrapped.add_done_callback(lambda f:f.exception() if not f.cancelled() else None)
            raise
        finally:
            # Fixed labels distinguish archive scheduling from cleanup and health.
            # Include completed cooperative yields, which aggregate success-only
            # priority metrics otherwise miss. Never retain request/evidence text.
            if label is not None and execution[1] is not None:
                key='owner.stage.'+label
                counts[key+'.calls']=counts.get(key+'.calls',0)+1
                for stage,duration in (('queue',execution[0]-submitted),('execution',execution[1]-execution[0])):
                    metric=key+'.'+stage;micros=int(max(0,duration)*1_000_000)
                    counts[metric+'_total_microseconds']=counts.get(metric+'_total_microseconds',0)+micros
                    counts[metric+'_peak_microseconds']=max(counts.get(metric+'_peak_microseconds',0),micros)
        # Separate scheduler wait from actual writer work; the prior "commit"
        # metric included both and could not identify the saturated stage.
        for stage,duration in (('queue',queued),('execution',executed)):
            key=f'owner.priority{priority}.{stage}'
            counts[key+'_total_microseconds']=counts.get(key+'_total_microseconds',0)+duration
            counts[key+'_peak_microseconds']=max(counts.get(key+'_peak_microseconds',0),duration)
        return value
    stop=stop or asyncio.Event();socket_path=str(path)+'.sock';Path(socket_path).unlink(missing_ok=True)
    clients=set();counts={}
    from .solana_owner_admission import OwnerAdmission,SourceState
    admission=OwnerAdmission(owner,clock=time.monotonic)
    loop=asyncio.get_running_loop()
    owner.admission_notify=lambda:loop.call_soon_threadsafe(admission.recheck)
    # Source batching amortizes FULL-synchronous fsyncs while the store is clean.
    # Once archive/retention has real backlog, however, a multi-frame batch would
    # consume several frames inside one owner admission and make cleanup fairness
    # depend on decode timing. Keep the fast path, but collapse source commits to
    # one frame while either maintenance path reports active backlog.
    maintenance_pressure={'archive':False,'retention':False}
    # A prepared archive receipt is already durable outside SQLite. While its
    # bounded 512-row commit slices remain, do not let the independent retention
    # loop enqueue fresh background work between those slices. Source/foreground
    # work still enters the owner FIFO normally, and retention resumes while the
    # next archive receipt is being prepared by the worker.
    def maintenance_batch_limit(pending_frames):
        # Cleanup fairness matters when source is keeping pace. If the bounded
        # transport queue itself is materially backed up, preserve the existing
        # batching fast path so reception can drain without manufacturing a
        # capacity discontinuity. Once backlog falls below two maximum batches,
        # maintenance regains one-frame source admissions until it catches up.
        if (any(maintenance_pressure.values())
                and pending_frames<2*STREAM_COMMIT_BATCH_MAX_MESSAGES):
            return 1
        return STREAM_COMMIT_BATCH_MAX_MESSAGES
    def count(key):counts[key]=counts.get(key,0)+1
    subscriptions_dirty=await work(lambda state:state.fence.subscriptions_dirty,0)

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
                future=pending_commands.submit(request)
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
    storage_ready=asyncio.Event()
    try:
        server=await asyncio.start_unix_server(consumer,path=socket_path,limit=MAX_COMMAND_BYTES+1,backlog=32)
        os.chmod(socket_path,0o600)
        class StreamDispatchCapacity(OSError):
            pass

        async def source():
            await storage_ready.wait()
            while not stop.is_set():
                connection_tasks=[]
                connection_stop=asyncio.Event()
                try:
                    # Keep websocket draining independent from decode, SQLite
                    # persistence, and account-subscription reconciliation. Run 373
                    # proved that a healthy receiver can still lose continuity when
                    # one sequential downstream processor cannot sustain block flow.
                    # A bounded websocket data queue pauses transport reads,
                    # including PONG frames. Its autonomous ping deadline cannot
                    # distinguish that intentional backpressure from a dead peer.
                    # Keep pings, but enforce explicit receive/commit progress
                    # deadlines below; native freshness/finality gates are intact.
                    async with connect(config.stream_url,logger=logger,max_size=STREAM_MAX_MESSAGE_BYTES,max_queue=STREAM_PROTOCOL_QUEUE_FRAMES,ping_interval=10,ping_timeout=None,open_timeout=10) as ws:
                        from collections import Counter,deque
                        number=1
                        pending={1:Subscription('service','chain:solana','all','blocks',2)}
                        active={};registered=set();retiring=set();retired_subscriptions=deque(maxlen=256)
                        inbound=asyncio.Queue(maxsize=STREAM_DISPATCH_MAX_MESSAGES)
                        decoded=asyncio.Queue(maxsize=STREAM_DISPATCH_MAX_MESSAGES)
                        pending_bytes=0;pending_frames=0;receive_sequence=0
                        commit_progress=time.monotonic()
                        receive_capacity_waiting=False
                        drained=asyncio.Event();drained.set()
                        capacity_available=asyncio.Event()
                        wanted=set()
                        await ws.send(canonical(pending[1].request(1)))

                        async def sync_subscriptions_once():
                            nonlocal number,wanted
                            started=time.monotonic()
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
                                pending[number]=sub;registered.add(address)
                                await ws.send(canonical(sub.request(number)))
                            elapsed=int((time.monotonic()-started)*1_000_000)
                            counts['stream.subscription_syncs']=counts.get('stream.subscription_syncs',0)+1
                            counts['stream.subscription_sync_peak_microseconds']=max(
                                counts.get('stream.subscription_sync_peak_microseconds',0),elapsed)

                        async def subscription_manager():
                            restore=True
                            while not stop.is_set() and not connection_stop.is_set():
                                if restore or subscriptions_dirty.is_set():
                                    # Clear before enqueueing the read. A mutation
                                    # during that read/send sets a fresh hint for
                                    # the next cycle; no wakeup can be erased.
                                    subscriptions_dirty.clear()
                                    await sync_subscriptions_once();restore=False
                                else:count('stream.subscription_unchanged_polls')
                                try:await asyncio.wait_for(connection_stop.wait(),STREAM_SUBSCRIPTION_SYNC_SECONDS)
                                except TimeoutError:pass

                        async def receive():
                            nonlocal pending_bytes,pending_frames,receive_sequence,receive_capacity_waiting
                            last_receive=time.monotonic()
                            while not stop.is_set() and not connection_stop.is_set():
                                # Reserve room for one maximum-sized frame before
                                # asking the transport for it. A full local queue
                                # is backpressure, not missing evidence: let the
                                # ordered committer free capacity instead of reading
                                # a frame that we must discard and disconnect over.
                                # The protocol queue and TCP flow control remain
                                # bounded. A real transport discontinuity still gaps.
                                wait_started=None
                                while (pending_frames>=STREAM_DISPATCH_MAX_MESSAGES
                                       or pending_bytes+STREAM_MAX_MESSAGE_BYTES>STREAM_DISPATCH_MAX_BYTES):
                                    if wait_started is None:
                                        wait_started=time.monotonic()
                                        count('stream.admission_waits')
                                        receive_capacity_waiting=True;admission.recheck()
                                    capacity_available.clear()
                                    try:await asyncio.wait_for(capacity_available.wait(),.5)
                                    except TimeoutError:pass
                                    if stop.is_set() or connection_stop.is_set():return
                                    if time.monotonic()-commit_progress>STREAM_COMMIT_STALL_SECONDS:
                                        raise EvidenceUnavailable('local_ordered_commit_stalled')
                                if wait_started is not None:
                                    receive_capacity_waiting=False
                                    wait_us=int((time.monotonic()-wait_started)*1_000_000)
                                    counts['stream.admission_wait_total_microseconds']=counts.get('stream.admission_wait_total_microseconds',0)+wait_us
                                    counts['stream.admission_wait_peak_microseconds']=max(counts.get('stream.admission_wait_peak_microseconds',0),wait_us)
                                try:raw=await asyncio.wait_for(ws.recv(decode=False),.5)
                                except TimeoutError:
                                    if time.monotonic()-last_receive>STREAM_SOURCE_IDLE_SECONDS:
                                        raise EvidenceUnavailable('source_receive_idle_timeout')
                                    continue
                                last_receive=time.monotonic()
                                size=len(raw) if isinstance(raw,(str,bytes)) else STREAM_MAX_MESSAGE_BYTES+1
                                # The frame that crosses the bound is the first
                                # unretained frame. Stop reception, drain every frame
                                # already accepted into this connection, then create
                                # the continuity gap at the resulting committed edge.
                                if (size>STREAM_MAX_MESSAGE_BYTES
                                        or pending_frames>=STREAM_DISPATCH_MAX_MESSAGES
                                        or pending_bytes+size>STREAM_DISPATCH_MAX_BYTES):
                                    count('stream.dispatch_queue_overflow')
                                    counts['stream.dispatch_overflow_frame_bytes']=max(
                                        counts.get('stream.dispatch_overflow_frame_bytes',0),size)
                                    counts['stream.dispatch_overflow_pending_frames']=max(
                                        counts.get('stream.dispatch_overflow_pending_frames',0),pending_frames)
                                    counts['stream.dispatch_overflow_pending_bytes']=max(
                                        counts.get('stream.dispatch_overflow_pending_bytes',0),pending_bytes)
                                    return ('capacity',size)
                                sequence=receive_sequence;receive_sequence+=1
                                pending_frames+=1;pending_bytes+=size;drained.clear()
                                admission.recheck()
                                received_at=time.monotonic()
                                inbound.put_nowait((sequence,raw,time.time(),size,received_at))
                                counts['stream.received_messages']=counts.get('stream.received_messages',0)+1
                                counts['stream.raw_message_peak_bytes']=max(
                                    counts.get('stream.raw_message_peak_bytes',0),size)
                                counts['stream.dispatch_queue_peak']=max(
                                    counts.get('stream.dispatch_queue_peak',0),inbound.qsize())
                                counts['stream.dispatch_bytes_peak']=max(
                                    counts.get('stream.dispatch_bytes_peak',0),pending_bytes)
                                counts['stream.outstanding_frames_peak']=max(
                                    counts.get('stream.outstanding_frames_peak',0),pending_frames)

                        async def decode_worker(worker_id):
                            while True:
                                item=await inbound.get()
                                if item is None:
                                    inbound.task_done()
                                    await decoded.put(('worker_done',worker_id))
                                    return
                                sequence,raw,seen,size,received_at=item
                                try:
                                    decode_started=time.monotonic()
                                    queue_wait_us=int(max(0.0,decode_started-received_at)*1_000_000)
                                    counts['stream.decode_queue_wait_peak_microseconds']=max(
                                        counts.get('stream.decode_queue_wait_peak_microseconds',0),queue_wait_us)
                                    if size>=STREAM_PROCESS_DECODE_MIN_BYTES:
                                        future=decoder_pool.submit(
                                            decode_source_message,raw,config.credential,source_program_addresses,config.identity,seen)
                                        message,source_transactions,retained_transactions=await asyncio.shield(
                                            asyncio.wrap_future(future))
                                        counts['stream.decode_process_messages']=counts.get('stream.decode_process_messages',0)+1
                                    else:
                                        message,source_transactions,retained_transactions=await asyncio.to_thread(
                                            decode_source_message,raw,config.credential,source_program_addresses,config.identity,seen)
                                        counts['stream.decode_thread_messages']=counts.get('stream.decode_thread_messages',0)+1
                                    if isinstance(message,PreparedSource):
                                        key='stream.prepared_messages' if message.scopes is not None else 'stream.preparation_fallbacks'
                                        counts[key]=counts.get(key,0)+1
                                        counts['stream.prepared_payload_peak_bytes']=max(counts.get('stream.prepared_payload_peak_bytes',0),message.prepared_bytes)
                                    decoded_at=time.monotonic()
                                    decode_us=int((decoded_at-decode_started)*1_000_000)
                                    counts['stream.decode_peak_microseconds']=max(
                                        counts.get('stream.decode_peak_microseconds',0),decode_us)
                                    counts['stream.decode_total_microseconds']=(
                                        counts.get('stream.decode_total_microseconds',0)+decode_us)
                                    counts['stream.source_transactions']=(
                                        counts.get('stream.source_transactions',0)+source_transactions)
                                    counts['stream.retained_transactions']=(
                                        counts.get('stream.retained_transactions',0)+retained_transactions)
                                    await decoded.put(('frame',sequence,message,seen,size,decoded_at))
                                    admission.recheck()
                                finally:
                                    inbound.task_done()

                        async def commit_ordered():
                            nonlocal pending_bytes,pending_frames,commit_progress
                            next_sequence=0;finished_workers=0;ready={}
                            while finished_workers<STREAM_DECODE_WORKERS or ready or pending_frames:
                                # Pull every completion already available before
                                # entering the ordered commit pass. Without this,
                                # the committer immediately consumed one decoded
                                # frame and therefore could not form a batch even
                                # while the decoded queue was backing up.
                                completed=[await decoded.get()]
                                while len(completed)<STREAM_DISPATCH_MAX_MESSAGES:
                                    try:
                                        completed.append(decoded.get_nowait())
                                    except asyncio.QueueEmpty:
                                        break
                                counts['stream.decoded_drain_peak']=max(
                                    counts.get('stream.decoded_drain_peak',0),len(completed))
                                try:
                                    for item in completed:
                                        if item[0]=='worker_done':
                                            finished_workers+=1
                                        else:
                                            _,sequence,message,seen,size,decoded_at=item
                                            ready[sequence]=(message,seen,size,decoded_at)
                                            counts['stream.ordered_ready_peak']=max(
                                                counts.get('stream.ordered_ready_peak',0),len(ready))
                                    while next_sequence in ready:
                                        message,seen,size,decoded_at=ready[next_sequence]

                                        # Run 376: interleaved account notifications
                                        # defeated block-only fsync amortization.
                                        # Batch consecutive data frames in exact wire
                                        # order, retaining per-frame savepoints and
                                        # the existing 8-frame/16-MiB transaction cap.
                                        # Subscription/control ACKs remain barriers.
                                        if 'id' in message:admission.counters['bypass_head_ack']+=1
                                        if 'id' not in message:
                                            sid=(message.get('params') or {}).get('subscription')
                                            sub=active.get(sid)
                                            if sub is None and sid in retired_subscriptions:
                                                sub=None
                                            elif sub is None:
                                                raise EvidenceUnavailable('unknown_source_subscription')
                                            if sub is not None and sub.evidence_class not in ('blocks','account'):
                                                admission.counters['bypass_head_control']+=1
                                            if sub is not None and sub.evidence_class in ('blocks','account'):
                                                def source_state():
                                                    now=time.monotonic()
                                                    return SourceState(sub.evidence_class,pending_frames,pending_bytes,
                                                        receive_capacity_waiting,inbound.qsize(),decoded.qsize(),len(ready),
                                                        now-commit_progress,now-decoded_at,
                                                        stop.is_set() or connection_stop.is_set())
                                                offer=await admission.rendezvous(source_state)
                                                try:
                                                    batch=[];batch_bytes=0;cursor=next_sequence
                                                    batch_limit=maintenance_batch_limit(pending_frames)
                                                    maintenance_limited=batch_limit==1
                                                    if (not maintenance_limited
                                                            and any(maintenance_pressure.values())):
                                                        counts['stream.maintenance_backpressure_batching']=(
                                                            counts.get('stream.maintenance_backpressure_batching',0)+1)
                                                    while (cursor in ready
                                                           and len(batch)<batch_limit):
                                                        candidate,c_seen,c_size,c_decoded_at=ready[cursor]
                                                        if 'id' in candidate:
                                                            break
                                                        c_sid=(candidate.get('params') or {}).get('subscription')
                                                        c_sub=active.get(c_sid)
                                                        if c_sub is None:
                                                            break
                                                        if c_sub.evidence_class not in ('blocks','account'):
                                                            break
                                                        if batch and batch_bytes+c_size>STREAM_COMMIT_BATCH_MAX_BYTES:
                                                            break
                                                        if c_size>STREAM_COMMIT_BATCH_MAX_BYTES:
                                                            raise EvidenceUnavailable('stream_commit_batch_bound')
                                                        ready.pop(cursor)
                                                        batch.append((c_sub,candidate,c_seen,c_size,c_decoded_at))
                                                        batch_bytes+=c_size;cursor+=1
                                                    commit_started=time.monotonic()
                                                    wait_us=max(int(max(0.0,commit_started-row[4])*1_000_000)
                                                                for row in batch)
                                                    counts['stream.ordered_commit_wait_peak_microseconds']=max(
                                                        counts.get('stream.ordered_commit_wait_peak_microseconds',0),wait_us)
                                                    source_items=tuple((row[0],row[1],row[2],row[3]) for row in batch)
                                                    await work(lambda state,items=source_items:state.source_batch(items),
                                                               0 if all(row[0].evidence_class=='account' for row in batch) else 2,
                                                               label='source_commit',
                                                               accepted=lambda future:admission.source_accepted(future,offer,len(batch)))
                                                    commit_us=int((time.monotonic()-commit_started)*1_000_000)
                                                    counts['stream.commit_messages']=counts.get('stream.commit_messages',0)+len(batch)
                                                    counts['stream.commit_batches']=counts.get('stream.commit_batches',0)+1
                                                    counts['stream.commit_batch_messages_peak']=max(
                                                        counts.get('stream.commit_batch_messages_peak',0),len(batch))
                                                    counts['stream.commit_batch_bytes_peak']=max(
                                                        counts.get('stream.commit_batch_bytes_peak',0),batch_bytes)
                                                    counts['stream.commit_batch_saved_transactions']=(
                                                        counts.get('stream.commit_batch_saved_transactions',0)+max(0,len(batch)-1))
                                                    if maintenance_limited:
                                                        counts['stream.maintenance_limited_commit_batches']=(
                                                            counts.get('stream.maintenance_limited_commit_batches',0)+1)
                                                        counts['stream.maintenance_limited_commit_messages']=(
                                                            counts.get('stream.maintenance_limited_commit_messages',0)+len(batch))
                                                    counts['stream.commit_peak_microseconds']=max(
                                                        counts.get('stream.commit_peak_microseconds',0),commit_us)
                                                    counts['stream.commit_total_microseconds']=(
                                                        counts.get('stream.commit_total_microseconds',0)+commit_us)
                                                    pending_bytes=max(0,pending_bytes-batch_bytes)
                                                    pending_frames=max(0,pending_frames-len(batch))
                                                    commit_progress=time.monotonic()
                                                    capacity_available.set()
                                                    if pending_frames==0:drained.set()
                                                    next_sequence+=len(batch)
                                                finally:
                                                    admission.abort(offer)
                                                continue

                                        # Subscription acknowledgements, retired
                                        # notifications and account observations
                                        # preserve the exact former one-at-a-time
                                        # path.
                                        message,seen,size,decoded_at=ready.pop(next_sequence)
                                        commit_started=time.monotonic()
                                        ordered_wait_us=int(max(0.0,commit_started-decoded_at)*1_000_000)
                                        counts['stream.ordered_commit_wait_peak_microseconds']=max(
                                            counts.get('stream.ordered_commit_wait_peak_microseconds',0),ordered_wait_us)
                                        if message.get('id') in retiring:
                                            retiring.remove(message['id'])
                                        elif 'id' in message:
                                            sub=pending.pop(message['id'])
                                            if 'error' in message or type(message.get('result')) is not int:
                                                raise EvidenceUnavailable('authoritative_subscription_rejected')
                                            active[message['result']]=sub
                                            status=dict(active=len(active),by_evidence_class=dict(Counter(s.evidence_class for s in active.values())),
                                                        pending=len(pending),wanted_accounts=len(wanted))
                                            await work(lambda state:state.fence.health('subscriptions',status))
                                        else:
                                            sid=(message.get('params') or {}).get('subscription')
                                            sub=active.get(sid)
                                            if sub is None and sid in retired_subscriptions:
                                                sub=None
                                            elif sub is None:
                                                raise EvidenceUnavailable('unknown_source_subscription')
                                            if sub is not None:
                                                await work(lambda state:state.source(sub,message,seen,size),
                                                           0 if sub.evidence_class=='account' else 2)
                                        commit_us=int((time.monotonic()-commit_started)*1_000_000)
                                        counts['stream.commit_messages']=counts.get('stream.commit_messages',0)+1
                                        counts['stream.commit_peak_microseconds']=max(
                                            counts.get('stream.commit_peak_microseconds',0),commit_us)
                                        counts['stream.commit_total_microseconds']=(
                                            counts.get('stream.commit_total_microseconds',0)+commit_us)
                                        pending_bytes=max(0,pending_bytes-size)
                                        pending_frames=max(0,pending_frames-1)
                                        commit_progress=time.monotonic()
                                        capacity_available.set()
                                        if pending_frames==0:drained.set()
                                        next_sequence+=1
                                finally:
                                    for _ in completed:
                                        decoded.task_done()
                            if pending_frames or ready:
                                raise EvidenceUnavailable('stream_ordered_drain_incomplete')

                        async def loop_watchdog():
                            expected=time.monotonic()+STREAM_WATCHDOG_SECONDS
                            while not stop.is_set() and not connection_stop.is_set():
                                await asyncio.sleep(STREAM_WATCHDOG_SECONDS)
                                now=time.monotonic()
                                lag_us=int(max(0.0,now-expected)*1_000_000)
                                counts['stream.event_loop_lag_peak_microseconds']=max(
                                    counts.get('stream.event_loop_lag_peak_microseconds',0),lag_us)
                                expected=now+STREAM_WATCHDOG_SECONDS

                        receiver=asyncio.create_task(receive())
                        decoders=[asyncio.create_task(decode_worker(i)) for i in range(STREAM_DECODE_WORKERS)]
                        committer=asyncio.create_task(commit_ordered())
                        subscriptions=asyncio.create_task(subscription_manager())
                        watchdog=asyncio.create_task(loop_watchdog())
                        stopper=asyncio.create_task(stop.wait())
                        connection_tasks=[receiver,*decoders,committer,subscriptions,watchdog,stopper]
                        watched=[receiver,*decoders,committer,subscriptions,watchdog,stopper]
                        done,_=await asyncio.wait(watched,return_when=asyncio.FIRST_COMPLETED)

                        # A subscription/watchdog task can observe the stop flag
                        # before the dedicated waiter runs. The flag, not which
                        # task wins FIRST_COMPLETED, owns admitted-frame drain.
                        if stop.is_set():
                            admission.recheck()
                            connection_stop.set();receiver.cancel()
                            await asyncio.gather(receiver,return_exceptions=True)
                            for _ in decoders:await inbound.put(None)
                            await asyncio.gather(*decoders)
                            await committer
                            return

                        if receiver in done:
                            receiver_exc=receiver.exception()
                            outcome=None if receiver_exc else receiver.result()
                            connection_stop.set();admission.recheck()
                            for _ in decoders:await inbound.put(None)
                            drain_started=time.monotonic()
                            await asyncio.gather(*decoders)
                            await committer
                            await drained.wait()
                            counts['stream.drain_count']=counts.get('stream.drain_count',0)+1
                            drain_us=int((time.monotonic()-drain_started)*1_000_000)
                            counts['stream.drain_peak_microseconds']=max(
                                counts.get('stream.drain_peak_microseconds',0),drain_us)
                            if receiver_exc is not None:raise receiver_exc
                            if outcome and outcome[0]=='capacity':
                                raise StreamDispatchCapacity() from None
                            raise EvidenceUnavailable('stream_receiver_stopped')

                        # Any downstream task ending while reception is active is
                        # structural. Propagate its exception rather than silently
                        # reconnecting around corrupt ordering or persistence.
                        for task in done:
                            if task is not stopper:
                                result=task.result()
                                raise EvidenceUnavailable('stream_pipeline_task_stopped:'+task.get_coro().__name__)
                except (OSError,ValueError,KeyError,TypeError,TimeoutError,ConnectionClosed) as exc:
                    if stop.is_set():return
                    if isinstance(exc,EvidenceConflict) or str(exc) in ('hot_store_capacity','storage_capacity_critical'):raise
                    reason=('local_receive_dispatch_capacity' if isinstance(exc,StreamDispatchCapacity)
                            else disconnect_classification(exc))
                    await work(lambda state:state.disconnected(reason))
                    try:await asyncio.wait_for(stop.wait(),1)
                    except TimeoutError:pass
                finally:
                    connection_stop.set();admission.recheck()
                    for task in connection_tasks:task.cancel()
                    if connection_tasks:await asyncio.gather(*connection_tasks,return_exceptions=True)

        async def repair():
            await storage_ready.wait()
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

        async def health():
            # Health publication has its own single outstanding owner request.
            # Its scheduler wait must not idle a completed archive worker.
            while not stop.is_set():
                try:
                    http=repair_rpc.telemetry() if repair_rpc is not None and hasattr(repair_rpc,'telemetry') else {}
                    snapshot=dict(counts)
                    scheduler=owner.telemetry()
                    scheduler['owner_admission']=admission.telemetry()
                    await work(lambda state:state.publish_health(http,snapshot,scheduler),4,label='maintenance_health')
                except EvidenceUnavailable as exc:
                    if str(exc)!='evidence_background_yield':raise
                try:await asyncio.wait_for(stop.wait(),1)
                except TimeoutError:pass

        async def maintenance():
            # The single admission loop. Native owner-entry arbitration resolves
            # READY receipts against fresh debt; no independent retention request
            # can be waiting with an obsolete pre-queue ordering decision.
            from .solana_maintenance_runtime import ArchiveFlight,MaintenanceRuntime
            from .startup_storage import recover
            runtime=await work(lambda state:MaintenanceRuntime(state),4,label='maintenance_decision')
            await recover(work,decoder_pool,path,stop,wall=runtime.wall,monotonic=runtime.monotonic)
            storage_ready.set()
            admission.generation=runtime.generation
            flight=ArchiveFlight()
            while not stop.is_set():
                offer=await admission.before_maintenance()
                if stop.is_set():break
                submitted=time.monotonic()
                try:
                    def turn(state):
                        # Refuse an expired queued command before native arbitration.
                        # FIFO, debt deadlines and the owner lease stay unchanged.
                        if time.monotonic()-submitted>runtime.leases.owner:
                            raise EvidenceUnavailable('evidence_command_expired')
                        admission.entry(offer)
                        try:
                            result=runtime.turn(flight,submitted)
                        except BaseException as exc:
                            admission.completed(offer,error=exc,event=runtime.ring[-1] if runtime.ring else None)
                            raise
                        else:
                            admission.completed(offer,result=result,event=runtime.ring[-1])
                            return result
                    result=await work(turn,4,label='maintenance_decision',
                        accepted=lambda future:admission.accepted(future,offer),
                        admit_before=offer.row['deadline'] if offer is not None else None)
                    admission.publish(runtime.generation,result)
                    maintenance_pressure['archive']=result['archive_pressure']
                    maintenance_pressure['retention']=result['retirement_pressure']
                    if flight.prepared is not None:
                        snapshot=flight.prepared
                        future=decoder_pool.submit(EvidenceWriter.prepare_and_write_archive,path,snapshot,max_bytes=16*1024*1024)
                        # The sole coroutine attaches at the quiescent boundary
                        # after its owner decision returned. No SQL, second
                        # admission decision, or extra owner round trip occurs.
                        flight.attach(future,time.monotonic(),runtime.generation)
                    if result['side'] is not None:
                        await asyncio.sleep(0)
                        continue
                except EvidenceUnavailable as exc:
                    admission.refused(offer,exc)
                    if str(exc) in ('evidence_admission_offer_expired','evidence_admission_offer_unavailable','evidence_command_expired'):
                        await asyncio.sleep(0)
                        continue
                    if str(exc)!='evidence_background_yield':
                        admission.failed=True
                        admission.generation_invalid='generation' in str(exc)
                        admission.recheck()
                        raise
                    await asyncio.sleep(0)
                    continue
                except BaseException as exc:
                    admission.refused(offer,exc);admission.failed=True;admission.recheck()
                    raise
                await admission.idle(stop,flight.future)

        async def checkpoint():
            # One outstanding disk flush, with no pending-work queue. Retention
            # and source commits must not wait behind a slow PASSIVE page copy.
            # Join the accepted thread before closing the owner on cancellation.
            while not stop.is_set():
                started=time.monotonic()
                ticket=await work(lambda state:owner.checkpoint_ticket_after_current(),2,label='checkpoint_prepare')
                pending=asyncio.create_task(asyncio.to_thread(EvidenceWriter.checkpoint,path))
                try:result=await asyncio.shield(pending)
                except asyncio.CancelledError:
                    await pending
                    raise
                elapsed=int((time.monotonic()-started)*1_000_000)
                counts['checkpoint.calls']=counts.get('checkpoint.calls',0)+1
                counts['checkpoint.total_microseconds']=counts.get('checkpoint.total_microseconds',0)+elapsed
                counts['checkpoint.peak_microseconds']=max(counts.get('checkpoint.peak_microseconds',0),elapsed)
                counts['checkpoint.busy']=counts.get('checkpoint.busy',0)+int(result[0]!=0)
                bulk_complete=(result[0]==0 and result[1]==result[2])
                counts['checkpoint.bulk_incomplete']=counts.get('checkpoint.bulk_incomplete',0)+int(not bulk_complete)
                # Do not ask the owner to TRUNCATE a checkpoint that a pinned
                # reader prevented the off-owner PASSIVE copy from completing.
                # When the bulk copy is complete, put only the zero-wait reset
                # handshake in the same FIFO class as normal source commits.
                # Older admitted source work completes first, but newer source
                # work cannot overtake the reset. Priority >=2 also means the
                # reset never interrupts and rolls back an archive SQL slice.
                # A generation fence additionally refuses TRUNCATE after
                # any intervening owner operation. busy_timeout=0 alone
                # limits lock waiting, not the cost of copying a new tail.
                # A deferred completion gets a serialized off-owner retry below;
                # it cannot depend on an idle writer queue to make progress.
                if bulk_complete:
                    try:
                        def finish_if_current(state):
                            if not owner.checkpoint_current(ticket):return None
                            return state.writer.finish_checkpoint()
                        final=await work(finish_if_current,2,label='checkpoint_finish')
                        if final is None:
                            counts['checkpoint.tail_deferred']=counts.get('checkpoint.tail_deferred',0)+1
                            # A generation fence is safe but can starve physical
                            # reclamation under continuous source/retention work.
                            # Give the independent checkpoint worker one FIFO
                            # mutation boundary, not another chance at idle time.
                            # It never waits for pinned readers; incomplete copy
                            # releases the boundary and preserves their snapshots.
                            from .solana_checkpoint import reclaim_at_boundary
                            boundary_started=time.monotonic()
                            final=await reclaim_at_boundary(owner,path)
                            boundary_us=int((time.monotonic()-boundary_started)*1_000_000)
                            counts['checkpoint.boundary_calls']=counts.get('checkpoint.boundary_calls',0)+1
                            counts['checkpoint.boundary_total_microseconds']=counts.get('checkpoint.boundary_total_microseconds',0)+boundary_us
                            counts['checkpoint.boundary_peak_microseconds']=max(counts.get('checkpoint.boundary_peak_microseconds',0),boundary_us)
                            counts['checkpoint.boundary_reclaimed']=counts.get('checkpoint.boundary_reclaimed',0)+int(final==(0,0,0))
                        counts['checkpoint.incomplete']=counts.get('checkpoint.incomplete',0)+int(
                            final[0]!=0 or final[1]!=final[2])
                        counts['checkpoint.reclaimed']=counts.get('checkpoint.reclaimed',0)+int(
                            final==(0,0,0))
                    except EvidenceUnavailable as exc:
                        if str(exc)!='evidence_background_yield':raise
                        counts['checkpoint.yielded']=counts.get('checkpoint.yielded',0)+1
                try:await asyncio.wait_for(stop.wait(),1)
                except TimeoutError:pass

        tasks=[asyncio.create_task(source()),asyncio.create_task(repair()),asyncio.create_task(maintenance()),asyncio.create_task(health()),asyncio.create_task(checkpoint()),asyncio.create_task(stop.wait())]
        done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        if stop.is_set():
            admission.close()
            # The stop waiter/maintenance often wins FIRST_COMPLETED. Reception
            # stops immediately, but the source owns the admitted-frame drain.
            # Do not cancel that owner while decoded frames still await commit.
            try:await asyncio.wait_for(asyncio.shield(tasks[0]),30)
            except TimeoutError:
                await work(lambda state:setattr(state,'failed',True),0)
                await work(lambda state:state.fence.health('shutdown_boundary','admitted_frame_drain_timeout'),0)
                raise EvidenceUnavailable('admitted_frame_drain_timeout') from None
        # Source draining can finish another worker after FIRST_COMPLETED.
        # Inspect all completed workers, not just the original winning set;
        # an owner/arbiter failure racing with stop must not become success.
        for task in tasks:
            if task.done() and not task.cancelled():task.result()
    except BaseException:
        await work(lambda state:setattr(state,'failed',True),0)
        raise
    finally:
        admission.close()
        owner.admission_notify=None
        await work(lambda state:state.fence.health('phase','DRAINING'),0)
        if server:server.close();await server.wait_closed()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        if clients:await asyncio.gather(*list(clients),return_exceptions=True)
        # Persist the final bounded counters after producers stop; a short drain
        # can otherwise finish between maintenance snapshots and hide pressure.
        await work(lambda state:state.fence.health('ipc',dict(counts)),0)
        scheduler=owner.telemetry()
        scheduler['owner_admission']=admission.telemetry()
        await work(lambda state:state.fence.health('owner_scheduler',scheduler),0)
        await asyncio.to_thread(owner.close)
        await asyncio.to_thread(decoder_pool.shutdown,wait=True,cancel_futures=True)
        Path(socket_path).unlink(missing_ok=True)
