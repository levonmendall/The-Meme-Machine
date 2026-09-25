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
'''

class FinalizedFence:
    def __init__(self,writer,*,endpoint_identity,decoders=None):
        self.writer=writer;self.endpoint_identity=endpoint_identity
        self.decoders=decoders or {};self.session=uuid.uuid4().hex
        writer.db.executescript(SERVICE_SCHEMA)

    def disconnect(self,reason='stream_disconnect'):
        bounds=dict(self.writer.db.execute('SELECT scope,slot+1 FROM cursors'))
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
        if op=='interest':
            owner=request['owner'];scope=request['scope']
            self.writer.interest(owner,scope,lower_slot=request['lower_slot'],
                priority=request['priority'],lifecycle=request['lifecycle'])
            addresses=request.get('addresses',[])
            if not isinstance(addresses,list) or len(addresses)>100:
                raise EvidenceUnavailable('interest_account_bound')
            with self.writer.transaction():
                for address in addresses:
                    if not isinstance(address,str) or not address or len(address)>128:
                        raise EvidenceUnavailable('interest_address')
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
    url=alchemy_stream_endpoint(endpoint);writer=EvidenceWriter(path)
    fence=FinalizedFence(writer,endpoint_identity=hashlib.sha256(endpoint.encode()).hexdigest(),decoders=program_decoders())
    stop=stop or asyncio.Event();path=Path(path);socket_path=str(path)+'.sock'
    Path(socket_path).unlink(missing_ok=True)
    async def consumer(reader,stream):
        try:
            line=await asyncio.wait_for(reader.readline(),.5)
            if len(line)>32768:raise EvidenceUnavailable('consumer_command_bound')
            response=fence.command(json.loads(line))
        except (ValueError,KeyError,TypeError,TimeoutError) as exc:response={'ok':False,'error':type(exc).__name__}
        stream.write((canonical(response)+'\n').encode());await stream.drain();stream.close()
    server=await asyncio.start_unix_server(consumer,path=socket_path,limit=32769)
    os.chmod(socket_path,0o600)
    async def stream_source():
        while not stop.is_set():
            try:
                async with connect(url,max_size=16*1024*1024,max_queue=32,ping_interval=10,ping_timeout=10,open_timeout=10) as ws:
                    pending={};active={};registered=set();retiring=set();number=0
                    async def register(sub):
                        nonlocal number
                        number+=1;pending[number]=sub;await ws.send(canonical(sub.request(number)))
                    for sub in program_subscriptions():await register(sub)
                    while not stop.is_set():
                        # Durable interests survive consumer/service restarts. Account
                        # observations remain content only, never interval authority.
                        interests=writer.db.execute("SELECT DISTINCT s.address FROM service_interests s JOIN interests i ON s.owner=i.owner AND s.scope=i.scope WHERE i.active=1 ORDER BY i.priority LIMIT 256").fetchall()
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
                        message=json.loads(raw);seen=time.time()
                        if message.get('id') in retiring:
                            retiring.remove(message['id']);continue
                        if 'id' in message:
                            sub=pending.pop(message['id'])
                            if 'error' in message or type(message.get('result')) is not int:
                                raise EvidenceUnavailable('authoritative_subscription_rejected')
                            active[message['result']]=sub;continue
                        sub=active.get((message.get('params') or {}).get('subscription'))
                        if sub is None:raise EvidenceUnavailable('unknown_source_subscription')
                        if sub.evidence_class=='logs':fence.logs(sub,message,seen)
                        elif sub.evidence_class=='account':
                            writer.ingest(FinalizedNotificationDecoder(endpoint_identity=fence.endpoint_identity).decode(sub,message,seen))
                        else:fence.block(sub,message,seen)
            except (OSError,ValueError,KeyError,TypeError,TimeoutError,ConnectionClosed) as exc:
                if isinstance(exc,EvidenceConflict):
                    with writer.transaction():writer.db.execute("INSERT OR REPLACE INTO meta VALUES('poisoned','1')")
                    raise
                fence.disconnect(type(exc).__name__)
                with writer.transaction():writer._count('stream_reconnects')
                try:await asyncio.wait_for(stop.wait(),1)
                except TimeoutError:pass
    # Repair transport is detached from the SQLite writer and strategy consumers.
    # One bounded page is in flight; commits are applied on this writer's thread.
    async def repair_worker():
        while not stop.is_set():
            if repair_rpc is not None:
                gap=writer.db.execute('SELECT id,scope,lo,hi,repair_cursor,pages FROM gaps WHERE repaired IS NULL AND hi IS NOT NULL AND pages<16 AND attempts<48 ORDER BY created LIMIT 1').fetchone()
                if gap:
                    gid,scope,lo,hi,cursor,pages=gap
                    subscriptions={s.scope:s for s in program_subscriptions()}
                    sub=subscriptions.get(scope)
                    if sub:
                        state=json.loads(cursor) if cursor else {'next':None}
                        cfg=dict(transactionDetails='full',sortOrder='asc',limit=100,commitment='finalized',encoding='json',maxSupportedTransactionVersion=1,filters={'slot':{'gte':lo,'lte':hi}})
                        if state.get('next'):cfg['paginationToken']=state['next']
                        try:
                            with writer.transaction():
                                writer.db.execute('UPDATE gaps SET attempts=attempts+1 WHERE id=?',(gid,))
                                writer._count('gap_repair_calls')
                            value=await asyncio.to_thread(repair_rpc.call,'getTransactionsForAddress',[sub.address,cfg],False)
                            # Apply through the same bounded durable repair boundary.
                            class ReceiptRPC:
                                def call(self,*args):return value
                            frontier=writer.db.execute('SELECT MAX(slot) FROM stream_receipts WHERE scope=?',(scope,)).fetchone()[0]
                            AddressGapRepair(ReceiptRPC(),writer,endpoint_identity=fence.endpoint_identity,record_mapper=fence.repair_records).step(gid,sub.address,now=time.time(),finalized_through=frontier)
                        except (OSError,ValueError,KeyError,TypeError,TimeoutError):
                            with writer.transaction():writer._count('gap_repair_failures')
            try:await asyncio.wait_for(stop.wait(),1)
            except TimeoutError:pass
    tasks=[asyncio.create_task(stream_source()),asyncio.create_task(repair_worker())]
    try:
        stopper=asyncio.create_task(stop.wait())
        done,_=await asyncio.wait([stopper,*tasks],return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is not stopper:task.result()
    finally:
        if 'stopper' in locals():stopper.cancel()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        fence.disconnect('service_shutdown');server.close();await server.wait_closed()
        writer.close();Path(socket_path).unlink(missing_ok=True)
