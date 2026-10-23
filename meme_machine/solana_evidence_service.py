"""Finalized filtered-block fences over the existing single-writer evidence store.

Only this source adapter can seal coverage. Consumers send lifecycle interests and
read SQLite; they cannot send records, receipts, frontiers or interval proofs.
A receipt authenticates a block's filtered census. Its linked finalized child is
required to seal it. Silence, root notifications and socket ACKs never seal data.
"""
from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import time
from time import thread_time as owner_thread_time
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
CREATE INDEX IF NOT EXISTS receipt_unsealed ON stream_receipts(scope,session,slot) WHERE sealed=0;
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
# Match the existing configured native replay window. This is a recorder bound,
# not a claim that any provider can currently supply that historical interval.
# Existing source request can include the 6,000-slot required range, its
# unchanged 256-slot overlap, and the linked child. This is a memory bound,
# never an assertion about a provider's actual replay availability.
STREAM_CONTROL_REAUTH_MAX_RECEIPTS=6000+256+1


def decode_source_message(raw,credential,program_addresses=(),endpoint_identity=None,observed_at=None):
    """Synchronous compatibility entrypoint; live intake precedes process IPC."""
    from .solana_source_intake import select_frame
    selected=select_frame(raw,credential,program_addresses,max_bytes=STREAM_MAX_MESSAGE_BYTES,
        full_transaction_addresses=tuple(s.address for s in program_subscriptions() if s.evidence_class=='transactions'))
    return prepare_selected_source(selected,endpoint_identity,observed_at)


def prepare_selected_source(selected,endpoint_identity=None,observed_at=None):
    """Canonical work receives only the locally selected, lossless transactions."""
    from .solana_source_intake import SelectedFrame
    if not isinstance(selected,SelectedFrame):
        raise EvidenceUnavailable('source_message_shape')
    message=selected.message;total=selected.source_transactions;retained=selected.retained_transactions
    normalized_keys={};members={}
    if message.get('method')=='blockNotification':
        value=message['params']['result']['value'];block=value['block']
        transactions=block['transactions']
        normalized_keys={id(tx):keys for tx,keys in zip(transactions,selected.normalized_keys)}
        members={address:[transactions[i] for i in indexes] for address,indexes in selected.members.items()}
    if endpoint_identity is not None and observed_at is not None and message.get('method')=='blockNotification':
        scopes={};prepared_bytes=0;budget=[STREAM_PREPARED_MAX_BYTES];log_cache={}
        for sub in program_subscriptions():
            if sub.evidence_class=='logs':continue
            try:
                scoped=prepare_block_scope(sub,message,observed_at,endpoint_identity,program_decoders(),include_logs=True,budget=budget,
                    normalized_keys=normalized_keys,members=members,log_cache=log_cache)
            except PreparationBudgetExceeded:
                # An unusual multi-event block may expand beyond the preparation
                # budget. Retain its exact former serial path, never drop content.
                result=PreparedSource(message);result.scopes=None;result.prepared_bytes=0
                result.intake_counts=selected.counters()
                return result,total,retained
            prepared_bytes=STREAM_PREPARED_MAX_BYTES-budget[0]
            scopes[sub.scope]=scoped
        result=PreparedSource(message);result.scopes=scopes;result.prepared_bytes=prepared_bytes
        result.intake_counts=selected.counters()
        # Economic bodies now live only in the prepared records. Do not retain
        # a second full transaction tree while waiting for the ordered commit.
        result['params']=dict(message['params'],result=dict(message['params']['result'],
            value=dict(value,block=dict(block,transactions=[]))))
        message=result
    return message,total,retained


class PreparedSource(dict):
    """Local process-pool product, impossible to forge through provider JSON."""
    def __reduce__(self):
        if self.scopes is None:return PreparedSource,(dict(self),),self.__dict__
        # The SQL owner consumes trusted prepared bytes, not a second parsed
        # payload tree. Keep every original byte/hash/chunk and all native
        # record metadata, while avoiding duplicate raw IPC and parent GC work.
        scopes={key:dict(value,batches=tuple(tuple(
            replace(row,record=replace(row.record,payload={})) for row in batch)
            for batch in value['batches'])) for key,value in self.scopes.items()}
        return restore_prepared_source,(dict(self),scopes,self.prepared_bytes,getattr(self,'intake_counts',{}))


def restore_prepared_source(message,scopes,prepared_bytes,intake_counts=None):
    result=PreparedSource(message);result.scopes=scopes;result.prepared_bytes=prepared_bytes;result.intake_counts=intake_counts or {}
    return result


class PreparationBudgetExceeded(Exception):pass

def prepare_block_scope(subscription,message,seen,endpoint_identity,decoders,*,include_logs,budget,normalized_keys=None,members=None,log_cache=None):
    """Pure decode/hash/compression, with no database or authority publication."""
    from .solana_evidence_plane import prepare_record
    def prepare(record):
        result=prepare_record(record,log_cache=log_cache)
        budget[0]-=result.byte_count
        if budget[0]<0:raise PreparationBudgetExceeded()
        return result
    value=message['params']['result']['value'];slot=value['slot'];block=value['block']
    transactions=block.get('transactions')
    if not isinstance(transactions,list):raise EvidenceUnavailable('filtered_block_bound')
    def keys(tx):
        if normalized_keys is not None and id(tx) in normalized_keys:return normalized_keys[id(tx)]
        values=tx['transaction']['message']['accountKeys'];loaded=tx['meta'].get('loadedAddresses') or {}
        return [k if isinstance(k,str) else k['pubkey'] for k in values]+list(loaded.get('writable') or [])+list(loaded.get('readonly') or [])
    transactions=members.get(subscription.address,[]) if members is not None else [tx for tx in transactions if subscription.address in keys(tx)]
    if len(transactions)>2048:raise EvidenceUnavailable('filtered_block_bound')
    signatures=[tx['transaction']['signatures'][0] for tx in transactions]
    scoped=dict(method='blockNotification',params=dict(result=dict(value=dict(value,block=dict(block,transactions=transactions)))))
    decoder=FinalizedNotificationDecoder(endpoint_identity=endpoint_identity)
    records=decoder.decode(replace(subscription,evidence_class='transactions'),scoped,seen) if subscription.evidence_class=='transactions' else []
    enriched=[];deliveries=[];batches=[]
    for tx,record in zip(transactions,records):
        body=dict(record.payload)
        enriched.append(prepare(replace(record,payload=body,
            addresses=tuple(sorted(set(keys(tx)+[subscription.address]))))))
    if enriched:batches.append(tuple(enriched))
    for tx,signature in zip(transactions,signatures):
        if subscription.evidence_class=='census' and include_logs:
            meta=tx['meta'];log=dict(signature=signature,logs=meta.get('logMessages'),err=meta.get('err'))
            notification=dict(method='logsNotification',params=dict(result=dict(context=dict(slot=slot),value=log)))
            rows=FinalizedNotificationDecoder(endpoint_identity=endpoint_identity,log_decoder=decoders[subscription.scope]).decode(replace(subscription,evidence_class='logs'),notification,seen)
            if rows:batches.append(tuple(prepare(replace(row,transaction_index=tx.get('transactionIndex'))) for row in rows))
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
        from .runtime.operating_families import evidence_scope_sql,enabled
        self.writer=writer;self.endpoint_identity=endpoint_identity
        self.decoders=decoders or {};self.session=uuid.uuid4().hex
        # A fresh CONTROL replay must authenticate an old receipt again without
        # rewriting its original session/availability. Eligibility is deliberately
        # process-local: another interruption requires another authenticated
        # replay; only the canonical coverage/seal transaction survives it.
        self._control_reauthenticated={}
        # A thread-safe hint, never subscription/evidence authority. The owner
        # still reads durable interests at the original priority and cadence.
        self.subscriptions_dirty=threading.Event();self.subscriptions_dirty.set()
        writer.db.executescript(SERVICE_SCHEMA)
        if writer.db.execute('SELECT 1 FROM stream_receipts WHERE '+evidence_scope_sql('stream_receipts.scope')+' LIMIT 1').fetchone():self.disconnect('service_restart')
        with writer.transaction():
            for key in ('pump.foreground_historical_rpc_calls','meteora.historical_reconstruction_rpc_calls',
                        'stream_messages','stream_bytes','stream_reconnects','stream_rejected_messages',
                        'stream_accepted_messages','gap_repair_retries','rejected_evidence_records',
                        'ingested_event','ingested_transaction','ingested_account',
                        'pump.local_evidence_reads','meteora.local_evidence_reads',
                        'pump.complete_local_reads','meteora.complete_local_reads',
                        'pump.incomplete_local_reads','meteora.incomplete_local_reads',
                        'pump.repair_assisted_windows','meteora.repair_assisted_windows'):
                if key.startswith('meteora.') and not enabled('meteora'):continue
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
        from .runtime.operating_families import active_scope_sql
        live=active_scope_sql('owner')+' AND '+active_scope_sql('scope')
        with self.writer.transaction():
            n=self.writer.db.execute("UPDATE interests SET active=0 WHERE "+live+" AND active=1 AND lifecycle IN ('candidate','research') AND updated<?",(now-1200,)).rowcount
            self.writer._count('expired_candidate_interests',n)
            self.writer.db.execute('DELETE FROM service_interests WHERE '+live+' AND NOT EXISTS(SELECT 1 FROM interests i WHERE i.owner=service_interests.owner AND i.scope=service_interests.scope AND i.active=1)')
            self.writer.db.execute('DELETE FROM interests WHERE '+live+' AND active=0 AND updated<?',(now-7200,))
            self.writer.db.execute('DELETE FROM interest_checkpoints WHERE '+live+' AND NOT EXISTS(SELECT 1 FROM interests i WHERE i.owner=interest_checkpoints.owner AND i.scope=interest_checkpoints.scope)')
            self.writer.db.execute('DELETE FROM interest_owners WHERE '+active_scope_sql('owner')+' AND NOT EXISTS(SELECT 1 FROM interests i WHERE i.owner=interest_owners.owner)')
        if n:self.subscriptions_dirty.set()

    def disconnect(self,reason='stream_disconnect'):
        from .runtime.operating_families import evidence_scope_sql
        # Account notifications are content observations, never interval sources.
        # Creating unrepairable interval gaps for them would pin expired account
        # history forever. Program fences still fail closed across this restart;
        # execution accounts require the independently bounded current refresh.
        bounds=dict(self.writer.db.execute("SELECT scope,slot+1 FROM cursors WHERE "+evidence_scope_sql('cursors.scope')+" AND scope NOT LIKE 'account:%'"))
        with self.writer.transaction():
            self.writer.db.execute('INSERT OR REPLACE INTO service_health VALUES(?,?)',
                ('account_stream_discontinuity',canonical(dict(reason=reason,seen=self.writer.clock()))))
        for scope,slot in self.writer.db.execute('SELECT scope,MIN(slot) FROM stream_receipts WHERE '+evidence_scope_sql('stream_receipts.scope')+' AND sealed=0 AND session=? GROUP BY scope',(self.session,)):
            bounds[scope]=min(bounds.get(scope,slot),slot)
        for scope,slot in bounds.items():self.writer.gap(scope,slot,None,reason)
        self.session=uuid.uuid4().hex
        self._control_reauthenticated.clear()

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
                    body=dict(record.payload)
                    enriched.append(replace(record,payload=body,
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
                        if records:self.writer.ingest([replace(row,transaction_index=tx.get('transactionIndex')) for row in records])
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
            old=self.writer.db.execute('SELECT parent,hash,previous_hash,market_time,census,session FROM stream_receipts WHERE scope=? AND slot=?',(scope,slot)).fetchone()
            values=(parent,block['blockhash'],block['previousBlockhash'],at,census)
            if old and tuple(old[:5])!=values:
                raise EvidenceConflict('conflicting_finalized_block_receipt')
            if scope=='control:solana' and old and old[5]!=self.session:
                if slot not in self._control_reauthenticated and len(self._control_reauthenticated)>=STREAM_CONTROL_REAUTH_MAX_RECEIPTS:
                    raise EvidenceUnavailable('control_reauthentication_capacity')
            self.writer.db.execute('INSERT OR IGNORE INTO stream_receipts VALUES(?,?,?,?,?,?,?,?,?,0)',
                (scope,slot,*values,self.session,seen))
            prior=self.writer.db.execute('SELECT MAX(slot) FROM stream_receipts WHERE scope=? AND slot<?',(scope,slot)).fetchone()[0]
            # Do not classify a skipped slot as a produced block; parent links are
            # the explicit proof of skipped slots. An unknown parent is a gap.
            if prior is not None and parent>prior:
                self.writer._gap(scope,prior,parent,'missing_filtered_block_receipt')
            self.writer.db.execute('INSERT OR REPLACE INTO service_health VALUES(?,?)',
                ('finalized_frontier:'+scope,canonical(dict(slot=slot,time=at,seen=seen))))
        if scope=='control:solana' and old and old[5]!=self.session:
            self._control_reauthenticated[slot]=(values,seen)
        # An overlap replay is allowed to arrive before an outstanding outage.
        # It cannot bound that later gap yet. Keep the strict writer guard and
        # wait for an authenticated receipt at or beyond every open gap floor.
        later_gap=self.writer.db.execute('SELECT 1 FROM gaps WHERE scope=? AND hi IS NULL AND repaired IS NULL AND lo>? LIMIT 1',
            (scope,slot)).fetchone()
        if not later_gap:self.writer.reconnect(scope,slot)
        self.seal(scope,seen)

    def seal(self,scope,seen):
        selection='''SELECT p.slot,p.hash,p.census,p.seen,c.slot,c.hash,c.previous_hash,c.seen,
            p.parent,p.previous_hash,p.market_time,p.session,c.parent,c.census,c.market_time,c.session
            FROM stream_receipts p JOIN stream_receipts c ON c.scope=p.scope AND c.parent=p.slot
            WHERE p.scope=? AND p.sealed=0'''
        if scope=='control:solana' and self._control_reauthenticated:
            # Exact sparse primary-key candidates, never a scan of retained old
            # receipts. A child can have arrived before its replayed parent.
            replayed=self._control_reauthenticated
            slots=sorted(set(replayed)|{values[0] for values,_ in replayed.values()})
            pairs=self.writer.db.execute(selection+' AND p.slot IN ('+','.join('?' for _ in slots)+') ORDER BY p.slot',
                (scope,*slots)).fetchall()
            current=self.writer.db.execute(selection+' AND p.session=? AND c.session=? ORDER BY p.slot LIMIT 64',
                (scope,self.session,self.session)).fetchall()
            pairs=sorted(set(pairs+current),key=lambda row:row[0])
        else:
            pairs=self.writer.db.execute(selection+' AND p.session=? AND c.session=? ORDER BY p.slot LIMIT 64',
                (scope,self.session,self.session)).fetchall()
        completed=0
        for slot,blockhash,census,pseen,child,chash,previous,cseen,parent,p_previous,market_time,p_session,c_parent,c_census,c_time,c_session in pairs:
            reauthenticated={}
            for identity,values,original_session in (
                    (slot,(parent,blockhash,p_previous,market_time,census),p_session),
                    (child,(c_parent,chash,previous,c_time,c_census),c_session)):
                if original_session==self.session:continue
                fresh=self._control_reauthenticated.get(identity) if scope=='control:solana' else None
                if fresh is None or fresh[0]!=values:break
                reauthenticated[identity]=fresh[1]
            # Both immutable receipts must actually be authenticated during
            # this session. Merely finding an old linked pair is insufficient.
            if (p_session!=self.session and slot not in reauthenticated
                    or c_session!=self.session and child not in reauthenticated):continue
            if completed>=64:break
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
            if reauthenticated:
                witness['replayed_receipts']=dict(authenticated_session=self.session,
                    parent_session=p_session,child_session=c_session,
                    parent_observed_at=reauthenticated.get(slot,pseen),
                    child_observed_at=reauthenticated.get(child,cseen))
            available=max([seen,pseen,cseen,*reauthenticated.values()]+[delivered[s] for s in expected])
            proof=IntervalProof(scope,slot,child-1,'alchemy_finalized_stream',self.endpoint_identity,witness,available)
            self.writer.ingest([],proof=proof)
            with self.writer.transaction():
                n=self.writer.db.execute("UPDATE gaps SET repaired=? WHERE scope=? AND lo=? AND hi=? AND reason='missing_filtered_delivery' AND repaired IS NULL",(available,scope,slot,slot)).rowcount
                self.writer._count('gaps_repaired',n)
                self.writer.db.execute('UPDATE stream_receipts SET sealed=1 WHERE scope=? AND slot=?',(scope,slot))
            self._control_reauthenticated.pop(slot,None)
            completed+=1

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
        from .runtime.operating_families import require_scope,require_active,PausedFamily
        try:
            require_scope(request.get('scope',''))
            require_active(request.get('consumer',''))
        except PausedFamily:
            raise EvidenceUnavailable('paused_family_activity_forbidden') from None
        if op in ('interest','release','ack','advance_interest'):
            owner=request['owner'];consumer=request.get('consumer',owner)
            if not isinstance(owner,str) or len(owner)>256 or not isinstance(consumer,str) or len(consumer)>128:
                raise EvidenceUnavailable('interest_owner_bound')
            known=self.writer.db.execute('SELECT consumer FROM interest_owners WHERE owner=?',(owner,)).fetchone()
            if known and known[0]!=consumer:raise EvidenceUnavailable('interest_owned_by_other_consumer')
            if not known and op=='advance_interest':raise EvidenceUnavailable('interest_checkpoint_unknown_owner')
            if not known and op=='interest':
                if not hasattr(self,'selective') and self.writer.db.execute('SELECT COUNT(*) FROM interest_owners').fetchone()[0]>=4096:
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
            from .runtime.operating_families import active_scope_sql
            current={r[0] for r in self.writer.db.execute('SELECT DISTINCT s.address FROM service_interests s JOIN interests i ON i.owner=s.owner AND i.scope=s.scope WHERE i.active=1 AND '+active_scope_sql('s.owner')+' AND '+active_scope_sql('s.scope'))}
            if len(current|set(addresses))>256:
                if hasattr(self,'selective'):
                    self.count('subscription_capacity_pressure')
                else:
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
    from .runtime.operating_families import enabled
    if enabled('meteora'):
        result.append(Subscription('service',METEORA_SCOPE,'LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo','transactions',4))
    return result


def program_decoders():
    from .solana_program_decoders import pump_events,pumpswap_trade_events
    from .solana_evidence_runtime import PUMP_SCOPE,SWAP_SCOPE
    return {PUMP_SCOPE:pump_events,SWAP_SCOPE:pumpswap_trade_events}


def operational_storage_limit(path):
    """A verified existing epoch uses disk health, not accumulated file size."""
    from .runtime.operating_families import operational
    limit=2*1024*1024*1024
    root=os.environ.get('MM_STATE_ROOT')
    if not operational() or os.environ.get('MM_MODE')!='PAPER' or not root:return limit
    root=Path(root)
    if Path(path).resolve()!=root/'shared/solana-evidence.sqlite':return limit
    from .operational.storage_guard import verify_storage
    # Missing/mismatched storage configuration refuses startup. It never
    # falls back to an unverified permissive operational storage profile.
    if not os.environ.get('MM_STORAGE_GUARD_CONFIG'):
        raise EvidenceUnavailable('operational_storage_configuration_required')
    verify_storage(root)
    return None


class ServiceState:
    """All SQLite access is confined to the priority owner thread."""
    def __init__(self,path,config):
        from .solana_evidence_plane import EvidenceWriter
        # Retention and fixed memory/transaction bounds remain independent of
        # durable history growth on the verified epoch volume.
        self.writer=EvidenceWriter(path,max_hot_bytes=operational_storage_limit(path))
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
        # durable evidence still uses FULL-synchronous WAL and physical storage
        # guards. Configure before any temporary schema or owner work is created.
        self.writer.db.execute('PRAGMA cache_size=-16384')
        self.writer.db.execute('PRAGMA temp_store=MEMORY')
        self.fence=FinalizedFence(self.writer,endpoint_identity=config.identity,decoders=program_decoders())
        self.fence.health('provider',dict(provider=config.provider,network=config.network,endpoint_identity=config.identity))
        self.fence.health('phase','WARMING');self.fence.health('heartbeat',time.time())
        import os
        self.fence.health('pid',os.getpid())
        self.fence.health('hot_limit_bytes',self.writer.max_hot_bytes)
        self.fence.health('storage_capacity_mode','verified_epoch_volume' if self.writer.max_hot_bytes is None else 'bounded_file')
        self.failed=False
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
        from .runtime.operating_families import active_scope_sql
        return [r[0] for r in self.writer.db.execute("SELECT s.address FROM service_interests s JOIN interests i ON s.owner=i.owner AND s.scope=i.scope WHERE i.active=1 AND "+active_scope_sql('s.owner')+' AND '+active_scope_sql('s.scope')+" GROUP BY s.address ORDER BY MIN(i.priority),s.address LIMIT 257")]

    def disconnected(self,reason):
        self.fence.disconnect(reason);self.fence.count('stream_reconnects')
        self.fence.count('disconnect:'+reason)
        self.fence.health('phase','DEGRADED')
        self.fence.health('last_source_error',reason)

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
            self.storage_metrics['owner_sql_transactions']=dict(getattr(self.writer,'transaction_metrics',{}))
            self.maintenance_health(http)
            self.fence.health('ipc',ipc)
            self.fence.health('owner_scheduler',scheduler)
            if os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')=='1':
                from .runtime.sqlite_failure import coverage_status
                # The bounded diagnostic driver treats lost coverage as invalid
                # and drains safely. Optional recorder loss never closes normal
                # position protection or changes evidence/readiness policy.
                self.fence.health('sqlite_failure_recorder',coverage_status())

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
        self.writer.last_retention_progress=RetentionProgress(
            timing_enabled=os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')=='1')
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
        finally:
            # Optional fixed-size diagnostics include failed/rolled-back work,
            # while the original outcome below still credits only commits.
            # Recorder failure cannot replace an application/cleanup exception.
            try:
                for key,value in self.writer.last_retention_progress.timing_metrics().items():
                    self.storage_metrics[key]=self.storage_metrics.get(key,0)+value
            except BaseException:
                try:
                    key='retention_phase.unmeasured'
                    self.storage_metrics[key]=self.storage_metrics.get(key,0)+1
                except BaseException:pass
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


def source_join_snapshot(source_driver):
    """Copy two existing samples without renewing their clocks or provenance."""
    joins=getattr(source_driver,'join_state',{})
    return {plane:dict(joins[plane],join=dict(joins[plane]['join']),
        commit_queue=dict(joins[plane]['commit_queue']))
        for plane in ('rolling','candidate') if plane in joins}


async def publish_operation_costs(path,owner,stop):
    """Opt-in process telemetry, independent of canonical owner admission."""
    import asyncio
    import stat
    from .operational.supervisor import Supervisor
    from .portfolio_accounting import _atomic_json
    from .runtime import operation_costs
    if not operation_costs.enabled() or os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')!='1':return
    target=Path(path).parent/'solana-evidence-operation-costs.json'
    def store(row):
        for parent in (target.parent,*target.parent.parents):
            if parent.is_symlink():raise ValueError('operation_cost_publication_path')
        for candidate in (target,target.with_name(target.name+'.tmp')):
            try:info=candidate.lstat()
            except FileNotFoundError:continue
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1
                    or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600):
                raise ValueError('operation_cost_publication_path')
        if len(canonical(row).encode())+1>1024*1024:
            raise ValueError('operation_cost_publication_bound')
        _atomic_json(target,row)
    async def persist(state):
        pid=os.getpid();ticks=Supervisor._source_start_ticks(pid)
        if type(ticks) is not int or ticks<=0:raise ValueError('operation_cost_process_identity')
        costs=operation_costs.snapshot();clock=costs.get('collected_monotonic')
        if (type(costs.get('pid')) is not int or costs['pid']!=pid or costs.get('enabled') is not True
                or type(clock) not in (int,float) or not 0<=clock<2**64):
            raise ValueError('operation_cost_snapshot_identity')
        row=dict(version=1,pid=pid,process_start_ticks=ticks,publication_state=state,
            scope='INDEPENDENT_PROCESS_TELEMETRY_NOT_EVIDENCE_OR_READINESS',
            operation_costs=costs,owner_scheduler=owner.telemetry())
        pending=asyncio.create_task(asyncio.to_thread(store,row))
        try:await asyncio.shield(pending)
        except asyncio.CancelledError:
            # A canceled waiter cannot leave an ACTIVE write racing STOPPED.
            while not pending.done():
                try:await asyncio.shield(pending)
                except asyncio.CancelledError:pass
                except Exception:break
            try:pending.result()
            except Exception:pass
            raise
    failed=False
    try:
        while not stop.is_set():
            await persist('ACTIVE')
            try:await asyncio.wait_for(stop.wait(),1)
            except TimeoutError:pass
    except BaseException:
        failed=True;raise
    finally:
        try:await persist('STOPPED')
        except BaseException:
            if not failed:raise


async def serve(path,endpoint,*,repair_rpc=None,stop=None,source_driver=None):
    """Model B startup, bounded socket handling and one canonical owner."""
    if source_driver is None:
        raise EvidenceUnavailable('legacy_startup_archived_model_b_driver_required')
    import asyncio
    from concurrent.futures import ProcessPoolExecutor,ThreadPoolExecutor
    import multiprocessing
    import os
    from pathlib import Path
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed
    from .solana_provider_config import AlchemyEndpoint
    from .solana_evidence_transport import Subscription
    from .solana_evidence_plane import EvidenceWriter
    from .solana_evidence_control import PriorityOwner,PendingCommands,MAX_COMMAND_BYTES,admit
    config=AlchemyEndpoint.parse(endpoint)
    import logging
    logger=logging.Logger('alchemy_evidence_transport');logger.addHandler(logging.NullHandler());logger.propagate=False
    owner=PriorityOwner(lambda:ServiceState(path,config),clock=time.monotonic)
    pending_commands=PendingCommands(owner)
    await asyncio.wrap_future(owner.ready)
    decoder_pool=ProcessPoolExecutor(max_workers=STREAM_DECODE_WORKERS,mp_context=multiprocessing.get_context('spawn'))
    await asyncio.gather(*(asyncio.wrap_future(decoder_pool.submit(source_decoder_probe))
                           for _ in range(STREAM_DECODE_WORKERS)))
    from .solana_preparation_pool import PreparationPool
    preparation_loop=asyncio.get_running_loop()
    decoder_pool=PreparationPool(decoder_pool,notify=lambda:preparation_loop.call_soon_threadsafe(
        source_driver.archive_preparation_wakeup.notify))
    from .solana_history_work import HistoryExecutor,enabled as separated_history
    historical_executor=HistoryExecutor() if separated_history() else None
    delivery_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='candidate-history') if historical_executor is not None else None
    if historical_executor is not None:
        source_driver.historical_executor=historical_executor
        source_driver.delivery_executor=delivery_executor
        source_driver.preparation_executor=decoder_pool.native
        source_driver.archive_preparation_executor=decoder_pool
    source_program_addresses=tuple(sorted({s.address for s in program_subscriptions()}))
    counts={}
    def counter_snapshot():
        # Owner completion updates and event-loop snapshots share its existing
        # lock. Other counter keys remain event-loop-owned and never await here.
        with owner.cv:return dict(counts)
    async def work(fn,priority=1,*,label=None,component=None,accepted=None,admit_before=None,maintenance_ticket=None,continuation=None):
        if label not in (None,'source_commit','candidate_development','archive_plan','archive_commit_plan','retention','maintenance_health','health_ipc','health_scheduler','checkpoint_prepare','checkpoint_finish','maintenance_decision','history_dispatch','history_apply','candidate_delivery_capture','candidate_delivery_ack'):
            raise EvidenceUnavailable('owner_stage_identity')
        if component not in (None,'control','candidate','scout','history_publication','delivery_accounting'):
            raise EvidenceUnavailable('owner_component_identity')
        if continuation is not None and (priority!=2 or label!='candidate_delivery_ack'
                or component is not None or not callable(continuation)):
            raise EvidenceUnavailable('owner_stage_identity')
        submitted=time.monotonic()
        def timed(state):
            started=time.monotonic();cpu_started=owner_thread_time()
            continued=None
            try:
                value=fn(state)
                if continuation is not None and value is True:
                    def capture_next(state):
                        nonlocal continued
                        begun=time.monotonic();cpu_begun=owner_thread_time()
                        try:return continuation(state)
                        finally:continued=(time.monotonic()-begun,owner_thread_time()-cpu_begun)
                    owner.try_continuation(capture_next)
            finally:
                finished=time.monotonic();cpu_finished=owner_thread_time()
                # Accepted callbacks can outlive canceled asyncio waiters.
                # Record exactly once at completion, including failed/yielded
                # operations, before their future exposes the result.
                with owner.cv:
                    capture_wall,capture_cpu=continued if continued is not None else (0,0)
                    stages=[(label,component,started-submitted,finished-started-capture_wall,
                        cpu_finished-cpu_started-capture_cpu)]
                    if continued is not None:stages.append(('candidate_delivery_capture',None,0,capture_wall,capture_cpu))
                    # The two logical stages have disjoint execution costs.
                    # Immediate continuation has no second admission/queue wait;
                    # the priority hold below still includes the entire unit.
                    for name,part,queue,execution,cpu in stages:
                        if name is None:continue
                        key='owner.stage.'+name
                        keys=[key] if part is None else [key,key+'.component.'+part]
                        for key in keys:
                            counts[key+'.calls']=counts.get(key+'.calls',0)+1
                            for stage,duration in (('queue',queue),('execution',execution),('execution_cpu',cpu)):
                                metric=key+'.'+stage;micros=int(max(0,duration)*1_000_000)
                                counts[metric+'_total_microseconds']=counts.get(metric+'_total_microseconds',0)+micros
                                counts[metric+'_peak_microseconds']=max(counts.get(metric+'_peak_microseconds',0),micros)
                    for stage,duration in (('queue',started-submitted),('execution',finished-started)):
                        key=f'owner.priority{priority}.{stage}';micros=int(max(0,duration)*1_000_000)
                        counts[key+'_total_microseconds']=counts.get(key+'_total_microseconds',0)+micros
                        counts[key+'_peak_microseconds']=max(counts.get(key+'_peak_microseconds',0),micros)
            return value,int((started-submitted)*1_000_000),int((finished-started)*1_000_000)
        timed.owner_operation=dict(stage=label,component=component,
            origin_module=getattr(fn,'__module__',None),
            origin_line=getattr(getattr(fn,'__code__',None),'co_firstlineno',None))
        submit_options=dict(priority=priority)
        if admit_before is not None:submit_options['admit_before']=admit_before
        # Every producer keeps its one bounded outstanding command until the
        # owner can admit it. Rejection happens before mutation; a retry submits
        # the same command once, preserving its immutable evidence/deadline.
        # Admission offers retain their separate expiry/recheck semantics.
        future=(owner.submit_maintenance(timed,maintenance_ticket) if maintenance_ticket is not None
                else await admit(owner,timed,**submit_options))
        if accepted is not None:accepted(future)
        wrapped=asyncio.wrap_future(future)
        try:value,_,_=await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            # Accepted owner work outlives a cancelled maintenance waiter. Its
            # recorded outcome must be consumed even when cooperative SQL yield
            # finishes after shutdown has cancelled that background coroutine.
            wrapped.add_done_callback(lambda f:f.exception() if not f.cancelled() else None)
            raise
        return value
    work.candidate_delivery_continuation=True
    work.candidate_delivery_capture_actor=True
    work.candidate_delivery_publication_handoff=True
    work.candidate_delivery_fanout=historical_executor is not None
    stop=stop or asyncio.Event();socket_path=str(path)+'.sock';Path(socket_path).unlink(missing_ok=True)
    clients=set()
    from .solana_owner_admission import OwnerAdmission,SourceState
    admission=OwnerAdmission(owner,clock=time.monotonic)
    if source_driver is not None:source_driver.diagnostic_generation=lambda:admission.generation
    loop=asyncio.get_running_loop()
    owner.admission_notify=lambda:loop.call_soon_threadsafe(admission.recheck)
    # A prepared archive receipt is already durable outside SQLite. While its
    # bounded 512-row commit slices remain, do not let the independent retention
    # loop enqueue fresh background work between those slices. Source/foreground
    # work still enters the owner FIFO normally, and retention resumes while the
    # next archive receipt is being prepared by the worker.
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

    server=None;tasks=[];checkpoint_worker=None
    storage_ready=asyncio.Event()
    try:
        from .solana_checkpoint import CheckpointWorker,reclaim_at_boundary
        checkpoint_worker=CheckpointWorker(owner,path)
        await asyncio.shield(asyncio.wrap_future(checkpoint_worker.ready))
        server=await asyncio.start_unix_server(consumer,path=socket_path,limit=MAX_COMMAND_BYTES+1,backlog=32)
        os.chmod(socket_path,0o600)
        async def health():
            # Health publication has its own single outstanding owner request.
            # Its scheduler wait must not idle a completed archive worker.
            while not stop.is_set():
                try:
                    http=repair_rpc.telemetry() if repair_rpc is not None and hasattr(repair_rpc,'telemetry') else {}
                    snapshot=counter_snapshot()
                    if source_driver is not None:
                        snapshot['pipeline']={k:dict(v) for k,v in getattr(source_driver,'pipeline_metrics',{}).items()}
                        # Two bounded existing join samples; copy their original
                        # clocks/generation instead of refreshing stale facts.
                        snapshot['join_state']=source_join_snapshot(source_driver)
                        drain=getattr(source_driver,'drain_snapshot',None)
                        if callable(drain):snapshot['source_drain']=drain()
                        from .runtime.operation_costs import enabled as costs_enabled,snapshot as costs_snapshot
                        if costs_enabled():snapshot['operation_costs']=costs_snapshot()
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
            await recover(work,decoder_pool,path,stop,wall=runtime.wall,
                monotonic=runtime.monotonic,force=True,clock=runtime.clock,
                record_required=runtime.cold_record_required,
                nonrecord_required=runtime.cold_nonrecord_required,
                on_complete=lambda state,observation:runtime.cold_completed(observation))
            storage_ready.set()
            admission.generation=runtime.generation
            flight=ArchiveFlight()
            while not stop.is_set():
                offer=await admission.before_maintenance()
                if stop.is_set():break
                ticket=None
                try:
                    deadline=runtime.admission_deadline()
                    if offer is not None:deadline=min(deadline,offer.row['deadline'])
                    ticket=await admission.boundary(deadline,stop)
                    if ticket is None or stop.is_set():break
                    # Only now does the real native command exist. Its truthful
                    # acceptance clock follows all older FIFO work; waiting for
                    # a scheduling marker is never a renewed command lease.
                    submitted=time.monotonic()
                    def turn(state):
                        # Refuse an expired queued command before native arbitration.
                        # FIFO, debt deadlines and the owner lease stay unchanged.
                        entered=time.monotonic()
                        if entered-submitted>runtime.leases.owner:
                            raise EvidenceUnavailable('evidence_command_expired')
                        admission.entry(offer)
                        try:
                            result=runtime.turn(flight,submitted,owner_entered=entered)
                        except BaseException as exc:
                            admission.completed(offer,error=exc,event=runtime.ring[-1] if runtime.ring else None)
                            raise
                        else:
                            admission.completed(offer,result=result,event=runtime.ring[-1])
                            return result
                    result=await work(turn,4,label='maintenance_decision',
                        accepted=lambda future:admission.accepted(future,offer),
                        admit_before=offer.row['deadline'] if offer is not None else None,
                        maintenance_ticket=ticket)
                    admission.publish(runtime.generation,result)
                    if result.get('cold_recovery_required'):
                        await recover(work,decoder_pool,path,stop,wall=runtime.wall,
                            monotonic=runtime.monotonic,force=True,flight=flight,
                            on_complete=lambda state,observation:runtime.cold_completed(observation,flight),clock=runtime.clock,
                            record_required=runtime.cold_record_required,
                            nonrecord_required=runtime.cold_nonrecord_required)
                        if stop.is_set():break
                        await work(lambda state:state.fence.count('maintenance_cold_self_recoveries'),
                            4,label='maintenance_decision')
                        continue
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
                    if str(exc) in ('evidence_admission_offer_expired','evidence_admission_offer_unavailable','evidence_command_expired',
                            'maintenance_boundary_expired','maintenance_boundary_unavailable','maintenance_boundary_urgent_invalidated'):
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
                finally:
                    if ticket is not None:owner.cancel_maintenance_boundary(ticket)
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
                            boundary_started=time.monotonic()
                            final=await reclaim_at_boundary(owner,path,worker=checkpoint_worker)
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

        async def selected_source():
            await storage_ready.wait()
            await source_driver(work,stop)
        # Model B is the only producer. Archived startup cannot be selected.
        producers=[asyncio.create_task(selected_source())]
        from .runtime.operation_costs import enabled as costs_enabled
        cost_publisher=(asyncio.create_task(publish_operation_costs(path,owner,stop))
            if costs_enabled() and os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')=='1' else None)
        tasks=[*producers,asyncio.create_task(maintenance()),asyncio.create_task(health()),asyncio.create_task(checkpoint()),asyncio.create_task(stop.wait())]
        if cost_publisher is not None:tasks.append(cost_publisher)
        done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        if stop.is_set():
            admission.close()
            drain_deadline=asyncio.get_running_loop().time()+30
            if source_driver is not None:
                prior=getattr(source_driver,'drain_deadline',None)
                if prior is not None:drain_deadline=min(drain_deadline,prior)
                source_driver.drain_deadline=drain_deadline
            # The stop waiter/maintenance often wins FIRST_COMPLETED. Reception
            # stops immediately, but the source owns the admitted-frame drain.
            # Do not cancel that owner while decoded frames still await commit.
            try:await asyncio.wait_for(asyncio.shield(tasks[0]),max(0,drain_deadline-asyncio.get_running_loop().time()))
            except TimeoutError:
                await work(lambda state:setattr(state,'failed',True),0)
                await work(lambda state:state.fence.health('shutdown_boundary','admitted_frame_drain_timeout'),0)
                raise EvidenceUnavailable('admitted_frame_drain_timeout') from None
            # The owner can finish before the maintenance coroutine receives
            # its future. Join accepted work before cancelling that waiter;
            # otherwise a terminal error can disappear behind a normal stop.
            future=admission.maintenance_future
            if future is not None:
                try:
                    if future.done():future.result()
                    else:await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)),5)
                except TimeoutError as exc:
                    if future.done() and future.exception() is exc:raise
                    raise EvidenceUnavailable('evidence_owner_shutdown_timeout') from None
                except EvidenceUnavailable as exc:
                    if str(exc) not in ('evidence_background_yield','evidence_command_expired',
                            'evidence_admission_offer_expired','evidence_admission_offer_unavailable'):
                        raise
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
        if checkpoint_worker is not None:checkpoint_worker.close()
        if clients:await asyncio.gather(*list(clients),return_exceptions=True)
        # Persist the final bounded counters after producers stop; a short drain
        # can otherwise finish between maintenance snapshots and hide pressure.
        final_snapshot=counter_snapshot()
        if source_driver is not None:
            final_snapshot['pipeline']={k:dict(v) for k,v in getattr(source_driver,'pipeline_metrics',{}).items()}
            final_snapshot['join_state']=source_join_snapshot(source_driver)
            drain=getattr(source_driver,'drain_snapshot',None)
            if callable(drain):final_snapshot['source_drain']=drain()
            from .runtime.operation_costs import enabled as costs_enabled,snapshot as costs_snapshot
            if costs_enabled():final_snapshot['operation_costs']=costs_snapshot()
        await work(lambda state:state.fence.health('ipc',final_snapshot),0)
        scheduler=owner.telemetry()
        scheduler['owner_admission']=admission.telemetry()
        await work(lambda state:state.fence.health('owner_scheduler',scheduler),0)
        await asyncio.to_thread(owner.close)
        if delivery_executor is not None:await asyncio.to_thread(delivery_executor.shutdown,wait=True,cancel_futures=True)
        if historical_executor is not None:await asyncio.to_thread(historical_executor.close)
        await asyncio.to_thread(decoder_pool.shutdown,wait=True,cancel_futures=True)
        Path(socket_path).unlink(missing_ok=True)
