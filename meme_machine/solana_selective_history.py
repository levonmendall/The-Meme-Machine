"""Candidate-scoped acquisition and durable delivery accounting.

Discovery locators are never economic interval proofs. Canonical content remains
shared by the three lanes; completeness belongs to an address and its requested
interval. Archive work advances only in the transaction committing that content.
No capital, portfolio, signing or transaction-submission interface exists here.
"""
from dataclasses import replace
import hashlib
import json
import time
import zlib
from functools import lru_cache
from .solana_evidence_plane import FinalizedRecord,IntervalProof,EvidenceUnavailable,EvidenceConflict,canonical,digest,decode_body
from .solana_program_decoders import pump_events,pumpswap_trade_events
from .solana_native_evidence import normalize_zero_display

FAMILIES={'pump':'program:pump','pumpswap':'program:pumpswap','meteora':'program:meteora'}
PROGRAMS={'pump':'6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P',
          'pumpswap':'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA',
          'meteora':'LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo'}
SCHEMA='''
CREATE TABLE IF NOT EXISTS market_observations(
 family TEXT NOT NULL,address TEXT NOT NULL,first_slot INTEGER NOT NULL,
 last_slot INTEGER NOT NULL,first_seen REAL NOT NULL,last_seen REAL NOT NULL,
 source_signature TEXT NOT NULL,fields TEXT NOT NULL,hash TEXT NOT NULL,
 PRIMARY KEY(family,address));
CREATE TABLE IF NOT EXISTS evidence_bindings(
 family TEXT NOT NULL,address TEXT NOT NULL,market_address TEXT NOT NULL,
 canonical_scope TEXT NOT NULL,coverage_scope TEXT NOT NULL,metadata TEXT NOT NULL,
 PRIMARY KEY(family,address));
CREATE TABLE IF NOT EXISTS acquisition_jobs(
 id TEXT PRIMARY KEY,family TEXT NOT NULL,address TEXT NOT NULL,
 lo INTEGER NOT NULL,hi INTEGER NOT NULL,priority INTEGER NOT NULL,deadline REAL NOT NULL,
 status TEXT NOT NULL,token TEXT,pages INTEGER NOT NULL,last_slot INTEGER,last_index INTEGER,
 lineage TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,error TEXT);
CREATE INDEX IF NOT EXISTS acquisition_priority ON acquisition_jobs(status,priority,deadline,created);
CREATE TABLE IF NOT EXISTS acquisition_page_receipts(
 job TEXT NOT NULL,page INTEGER NOT NULL,input_hash TEXT NOT NULL,
 result TEXT NOT NULL,committed REAL NOT NULL,PRIMARY KEY(job,page));
CREATE TABLE IF NOT EXISTS native_order_attestations(
 scope TEXT NOT NULL,slot INTEGER NOT NULL,signature TEXT NOT NULL,
 transaction_index INTEGER NOT NULL,hash TEXT NOT NULL,
 PRIMARY KEY(scope,slot,signature));
CREATE TABLE IF NOT EXISTS provider_delivery(
 day INTEGER NOT NULL,family TEXT NOT NULL,transport TEXT NOT NULL,
 raw_bytes INTEGER NOT NULL DEFAULT 0,retained_bytes INTEGER NOT NULL DEFAULT 0,
 canonical_bytes INTEGER NOT NULL DEFAULT 0,ipc_bytes INTEGER NOT NULL DEFAULT 0,
 rpc_cu INTEGER NOT NULL DEFAULT 0,calls INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(day,family,transport));
CREATE TABLE IF NOT EXISTS acquisition_observations(
 id INTEGER PRIMARY KEY,job TEXT,kind TEXT NOT NULL,at REAL NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidate_coverage(
 scope TEXT NOT NULL,lo INTEGER NOT NULL,hi INTEGER NOT NULL,count INTEGER NOT NULL,
 first_available REAL NOT NULL,last_available REAL NOT NULL,points BLOB NOT NULL,
 hash TEXT NOT NULL,lineage TEXT NOT NULL,source TEXT NOT NULL,PRIMARY KEY(scope,lo));
CREATE INDEX IF NOT EXISTS candidate_coverage_bounds ON candidate_coverage(scope,hi,lo);
CREATE TABLE IF NOT EXISTS candidate_gaps(
 id INTEGER PRIMARY KEY,scope TEXT NOT NULL,lo INTEGER NOT NULL,hi INTEGER,
 created REAL NOT NULL,repaired REAL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shared_history_cache(
 identity TEXT PRIMARY KEY,scope TEXT NOT NULL,slot INTEGER NOT NULL,signature TEXT NOT NULL,
 program TEXT NOT NULL,market_time INTEGER,event_index INTEGER NOT NULL,transaction_index INTEGER,
 kind TEXT NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL,first_seen REAL NOT NULL,archive TEXT);
CREATE TABLE IF NOT EXISTS cached_addresses(identity TEXT NOT NULL,address TEXT NOT NULL,
 PRIMARY KEY(identity,address),FOREIGN KEY(identity) REFERENCES shared_history_cache(identity) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS cached_address_lookup ON cached_addresses(address,identity);
CREATE VIEW IF NOT EXISTS canonical_evidence AS
 SELECT * FROM records WHERE body IS NOT NULL OR NOT EXISTS(
   SELECT 1 FROM shared_history_cache c WHERE c.identity=records.identity)
 UNION ALL SELECT * FROM shared_history_cache c WHERE NOT EXISTS(
   SELECT 1 FROM records r WHERE r.identity=c.identity AND r.body IS NOT NULL);
CREATE VIEW IF NOT EXISTS canonical_addresses AS
 SELECT identity,address FROM addresses UNION SELECT identity,address FROM cached_addresses;
CREATE TABLE IF NOT EXISTS candidate_outbox(
 sequence INTEGER PRIMARY KEY,identity TEXT NOT NULL UNIQUE,scope TEXT NOT NULL,
 slot INTEGER NOT NULL,first_seen REAL NOT NULL);
CREATE INDEX IF NOT EXISTS candidate_outbox_scope ON candidate_outbox(scope,sequence);
CREATE TABLE IF NOT EXISTS candidate_content_receipts(
 identity TEXT PRIMARY KEY,economic_hash TEXT NOT NULL,transaction_index INTEGER,
 first_seen REAL NOT NULL);
'''

@lru_cache(maxsize=8192)
def pump_curve_address(mint):
    """Cache immutable PDA computation, never candidate eligibility or history."""
    from . import pump
    return pump.pda([b'bonding-curve',pump.un58(mint)],pump.PROGRAM)

def coverage_scope(family,address):
    if family not in FAMILIES or not isinstance(address,str) or not address:
        raise EvidenceUnavailable('candidate_scope_shape')
    return 'candidate:'+family+':'+address

def rpc_economic_transaction(tx,*,rich):
    """Same economic interface for native, archive and selective body fallback."""
    try:
        message=tx['transaction']['message'];meta=tx['meta']
        if not isinstance(message,dict) or not isinstance(meta,dict) or 'err' not in meta:
            raise KeyError()
        keys=[k if isinstance(k,str) else k['pubkey'] for k in message['accountKeys']]
        loaded=meta.get('loadedAddresses') or {}
        keys+=list(loaded.get('writable') or [])+list(loaded.get('readonly') or [])
        if not tx['transaction']['signatures'] or not all(isinstance(k,str) for k in keys):raise KeyError()
        logs=meta['logMessages']
        if meta['err'] is None and not isinstance(logs,list):raise KeyError()
        body=dict(slot=tx['slot'],blockTime=tx['blockTime'],transactionIndex=tx['transactionIndex'],
            transaction=dict(signatures=list(tx['transaction']['signatures']),message=dict(accountKeys=keys)),
            meta=dict(err=meta['err'],logMessages=logs))
        if rich:
            for field in ('innerInstructions','preTokenBalances','postTokenBalances'):
                body['meta'][field]=meta[field]
            body['transaction']['message']['instructions']=[
                {k:v for k,v in instruction.items() if k!='stackHeight'}
                for instruction in message['instructions']]
        return normalize_zero_display(body)
    except (KeyError,TypeError):raise EvidenceUnavailable('candidate_economic_fields_missing') from None

def economic_records(family,address,tx,*,endpoint_identity,seen,source):
    scope=FAMILIES[family];index=tx['transactionIndex'];slot=tx['slot']
    signature=tx['transaction']['signatures'][0]
    if type(index) is not int or index<0 or type(slot) is not int or slot<0:
        raise EvidenceUnavailable('candidate_native_order_missing')
    if family=='meteora':
        body=rpc_economic_transaction(tx,rich=True)
        keys=body['transaction']['message']['accountKeys']
        if address not in keys:raise EvidenceUnavailable('candidate_address_membership_missing')
        return [FinalizedRecord(scope+':tx:'+signature,scope,slot,signature,PROGRAMS[family],
            tuple(sorted(set(keys+[PROGRAMS[family]]))),body['blockTime'],body,source,endpoint_identity,seen,
            transaction_index=index,kind='transaction')]
    meta=tx['meta']
    if 'err' not in meta or 'logMessages' not in meta:raise EvidenceUnavailable('candidate_economic_fields_missing')
    if meta['err'] is not None:return []
    logs=meta['logMessages']
    if not isinstance(logs,list) or any('truncat' in line.lower() for line in logs):
        raise EvidenceUnavailable('incomplete_finalized_logs')
    events=(pump_events if family=='pump' else pumpswap_trade_events)(tx)
    rows=[]
    for event in events:
        # A transaction can mention multiple candidates. Acquire it once, but
        # do not put an unrelated event inside this candidate's coverage proof.
        if family=='pumpswap' and event.get('pool')!=address:continue
        if family=='pump' and event.get('mint')!=address and event.get('bonding_curve')!=address:
            from . import pump
            mint=event.get('mint')
            if not mint or pump_curve_address(mint)!=address:continue
        addresses=tuple(sorted({str(event[k]) for k in ('pool','mint','wallet') if event.get(k)}))
        payload=dict(event=event,raw_lineage=dict(logs=logs,err=meta['err']))
        rows.append(FinalizedRecord(f'{scope}:{slot}:{signature}:{event["index"]}',scope,slot,
            signature,PROGRAMS[family],addresses,event['market_time'],payload,source,endpoint_identity,seen,
            event_index=event['index'],transaction_index=index))
    return rows


class SelectiveHistory:
    """Runs exclusively on the existing canonical SQLite owner thread."""
    def __init__(self,writer,endpoint_identity,*,clock=time.time):
        self.writer=writer;self.db=writer.db;self.endpoint_identity=endpoint_identity;self.clock=clock
        self.db.executescript(SCHEMA)

    def observe(self,family,address,*,slot,signature,fields,seen=None):
        """Lossless cheap retention. This record cannot authorize qualification."""
        if family not in FAMILIES or not isinstance(fields,dict):raise EvidenceUnavailable('candidate_scout_shape')
        seen=self.clock() if seen is None else seen
        body=canonical(fields);checksum=digest(fields)
        with self.writer.transaction():
            prior=self.db.execute('SELECT last_slot,last_seen,fields FROM market_observations WHERE family=? AND address=?',(family,address)).fetchone()
            if prior and (slot,seen)<tuple(prior[:2]):return
            if prior:
                fields=dict(json.loads(prior[2]),**fields);body=canonical(fields);checksum=digest(fields)
            self.db.execute('''INSERT INTO market_observations VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(family,address) DO UPDATE SET last_slot=excluded.last_slot,
                last_seen=excluded.last_seen,source_signature=excluded.source_signature,
                fields=excluded.fields,hash=excluded.hash''',
                (family,address,slot,slot,seen,seen,signature,body,checksum))
            if hasattr(self,'lifecycle'):
                self.lifecycle.observe(family,address,slot=slot,seen=seen,signature=signature,fields=fields,
                    activity=fields.get('activity',False))

    def bind(self,family,address,*,market_address=None,aliases=(),metadata=None):
        base=FAMILIES[family];scoped=coverage_scope(family,address)
        with self.writer.transaction():
            current=self.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',
                (family,address)).fetchone()
            # Repeated provider-interest registration must retain an authenticated
            # curve-to-mint upgrade. An explicit different identity still fails.
            market=market_address or (current[0] if current else address)
            # A mint interest must reuse the curve's already proved identity.
            # Conversely, a creation backfill can attach a provisional curve to
            # an existing mint interest without changing its durable scope.
            existing=[self.db.execute('SELECT market_address,coverage_scope FROM evidence_bindings WHERE family=? AND address=?',
                (family,a)).fetchone() for a in dict.fromkeys((address,*aliases))]
            matching={row[1] for row in existing if row and row[0]==market}
            if len(matching)>1:raise EvidenceConflict('candidate_binding_conflict')
            if matching:scoped=matching.pop()
            for alias in dict.fromkeys((address,*aliases)):
                old=self.db.execute('SELECT market_address,coverage_scope FROM evidence_bindings WHERE family=? AND address=?',(family,alias)).fetchone()
                target=(market,scoped)
                if old and tuple(old)!=target:raise EvidenceConflict('candidate_binding_conflict')
                self.db.execute('INSERT OR IGNORE INTO evidence_bindings VALUES(?,?,?,?,?,?)',
                    (family,alias,market,base,scoped,canonical(metadata or {})))
        return scoped

    def scope_for(self,family,address):
        row=self.db.execute('SELECT coverage_scope FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
        return coverage_scope(family,address) if row is None else row[0]

    def request(self,family,address,lo,hi,*,priority,deadline):
        if type(lo) is not int or type(hi) is not int or not 0<=lo<=hi or not 0<=priority<=6:
            raise EvidenceUnavailable('candidate_history_request_shape')
        now=self.clock();identity=digest([family,address,lo,hi])
        with self.writer.transaction():
            self.db.execute('''INSERT OR IGNORE INTO acquisition_jobs VALUES(?,?,?,?,?,?,?,
                'pending',NULL,0,NULL,NULL,?,?,?,NULL)''',
                (identity,family,address,lo,hi,priority,deadline,digest([]),now,now))
            # Reasserting an interval may increase urgency, never reset its cursor.
            self.db.execute('UPDATE acquisition_jobs SET priority=MIN(priority,?),deadline=MIN(deadline,?) WHERE id=?',
                (priority,deadline,identity))
            depth=self.db.execute("SELECT COUNT(*) FROM acquisition_jobs WHERE status='pending'").fetchone()[0]
            if depth>8:self._observation(identity,'capacity_pressure',dict(queue_depth=depth,economic_rejection=False))
        return identity

    def _observation(self,job,kind,body):
        self.db.execute('INSERT INTO acquisition_observations(job,kind,at,body) VALUES(?,?,?,?)',
            (job,kind,self.clock(),canonical(body)))

    def plan(self,*,excluding=()):
        """Priority for safety/positions/continuations, then deadline and age."""
        now=self.clock()
        with self.writer.transaction():
            for identity in [r[0] for r in self.db.execute("SELECT id FROM acquisition_jobs WHERE status='pending' AND deadline<=?",(now,))]:
                self.db.execute("UPDATE acquisition_jobs SET status='deadline_missed',updated=?,error='candidate_decision_deadline_missed' WHERE id=?",(now,identity))
                self._observation(identity,'deadline_missed',dict(economic_rejection=False))
            exclusion='' if not excluding else ' AND id NOT IN ('+','.join('?' for _ in excluding)+')'
            row=self.db.execute('''SELECT id,family,address,lo,hi,priority,deadline,token,pages,last_slot,last_index,lineage
                FROM acquisition_jobs WHERE status='pending'
                '''+exclusion+''' ORDER BY CASE WHEN priority<=2 THEN priority ELSE 3 END,deadline,priority,created,id LIMIT 1''',tuple(excluding)).fetchone()
        if row is None:return None
        job=dict(zip(('id','family','address','lo','hi','priority','deadline','token','pages','last_slot','last_index','lineage'),row))
        config=dict(transactionDetails='full',sortOrder='asc',limit=100,commitment='finalized',
            encoding='json',maxSupportedTransactionVersion=1,filters=dict(slot=dict(gte=job['lo'],lte=job['hi'])))
        if job['token'] is not None:config['paginationToken']=job['token']
        return job,config

    def commit_page(self,job,value,*,finalized_through,seen=None):
        """No page-count discard; every physical page remains bounded to 100."""
        seen=self.clock() if seen is None else seen
        if finalized_through<job['hi']:raise EvidenceUnavailable('repair_upper_boundary_not_finalized')
        if not isinstance(value,dict) or not isinstance(value.get('data'),list) or len(value['data'])>100:
            raise EvidenceUnavailable('address_history_response_shape_unverified')
        token=value.get('paginationToken')
        if token is not None and (not isinstance(token,str) or not token or token==job['token']):
            raise EvidenceUnavailable('repair_pagination_stalled')
        rows=[];last=None if job['last_slot'] is None else (job['last_slot'],job['last_index'])
        for tx in value['data']:
            pair=(tx.get('slot'),tx.get('transactionIndex'))
            if any(type(n) is not int for n in pair) or not job['lo']<=pair[0]<=job['hi'] or pair[1]<0:
                raise EvidenceUnavailable('repair_order_or_bounds')
            if last is not None and pair<=last:raise EvidenceUnavailable('repair_order_or_bounds')
            last=pair
            rows.extend(economic_records(job['family'],job['address'],tx,
                endpoint_identity=self.endpoint_identity,seen=seen,source='alchemy_finalized_repair'))
        scoped=self.scope_for(job['family'],job['address']);lineage=digest([job['lineage'],digest(value)])
        proof=None
        if token is None:
            proof=IntervalProof(scoped,job['lo'],job['hi'],'alchemy_finalized_repair',self.endpoint_identity,
                dict(finalized=True,complete=True,scope=scoped,lower_slot=job['lo'],upper_slot=job['hi'],
                     lineage_hash=lineage,method='getTransactionsForAddress',pagination_exhausted=True,
                     page_count=job['pages']+1,address=job['address'],canonical_scope=FAMILIES[job['family']]),seen)
        with self.writer.transaction():
            input_hash=digest([job['token'],value])
            receipt=self.db.execute('SELECT input_hash,result FROM acquisition_page_receipts WHERE job=? AND page=?',
                (job['id'],job['pages'])).fetchone()
            if receipt:
                if receipt[0]!=input_hash:raise EvidenceConflict('candidate_archive_page_conflict')
                return json.loads(receipt[1])
            current=self.db.execute('SELECT token,pages,status FROM acquisition_jobs WHERE id=?',(job['id'],)).fetchone()
            if current is None or tuple(current)!=(job['token'],job['pages'],'pending'):
                raise EvidenceUnavailable('candidate_page_lease_stale')
            self.ingest(rows)
            if proof is not None:
                if hasattr(self,'lifecycle'):self.lifecycle.defer_proof(proof)
                else:self.prove(proof)
            for row in rows:self.attest_order(row.scope,row.slot,row.signature,row.transaction_index)
            self.db.execute('''UPDATE acquisition_jobs SET token=?,pages=pages+1,last_slot=?,last_index=?,
                lineage=?,status=?,updated=? WHERE id=?''',(token,*((None,None) if last is None else last),
                lineage,'complete' if token is None else 'pending',seen,job['id']))
            if job['pages']+1>16:self._observation(job['id'],'capacity_pressure',dict(pages=job['pages']+1,economic_rejection=False))
            result=dict(complete=token is None,records=len(rows),pages=job['pages']+1)
            self.db.execute('INSERT INTO acquisition_page_receipts VALUES(?,?,?,?,?)',
                (job['id'],job['pages'],input_hash,canonical(result),seen))
        return result

    def ingest(self,rows,*,restored=None):
        """One identity; a bounded shared cache permits late scoped backfill.

        The global hot-retention floor remains monotonic. It cannot prevent an
        older retained candidate being warmed into an address-scoped cache.
        Existing archived bytes must be independently restored and verified;
        neither their immutable content nor original availability is rewritten.
        """
        rows=tuple(rows);restored=restored or {}
        if len(rows)>2048 or sum(len(canonical(r.body()).encode()) for r in rows)>16*1024*1024:
            raise EvidenceUnavailable('ingestion_batch_bound')
        from .solana_evidence_plane import require_storage
        require_storage(self.writer.path,required_bytes=32*1024*1024)
        hot=[];cached=[]
        with self.writer.transaction():
            for row in rows:
                incoming=row.body()
                economic_hash=self.content_hash(incoming)
                receipt=self.db.execute('SELECT economic_hash,transaction_index,first_seen FROM candidate_content_receipts WHERE identity=?',(row.identity,)).fetchone()
                if receipt:
                    if receipt[0]!=economic_hash:raise EvidenceConflict('candidate_economic_content_conflict')
                    if receipt[1] is not None and row.transaction_index is not None and receipt[1]!=row.transaction_index:
                        raise EvidenceConflict('candidate_native_order_conflict')
                    # Global hot maintenance can remove a fully consumed record.
                    # Its immutable receipt remains the original availability on
                    # later selective reconstruction, not the new HTTP delivery.
                    row=replace(row,observed_at=receipt[2])
                old=self.db.execute('SELECT body,hash,first_seen,archive FROM records WHERE identity=?',(row.identity,)).fetchone()
                previous_cache=self.db.execute('SELECT body,hash,first_seen FROM shared_history_cache WHERE identity=?',(row.identity,)).fetchone()
                cold=(self.db.execute('SELECT body,hash,first_seen,archive FROM scoped_cold_records WHERE identity=?',(row.identity,)).fetchone()
                      if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='scoped_cold_records'").fetchone() else None)
                available=next((copy[2] for copy in (previous_cache,old,cold) if copy),row.observed_at)
                self.db.execute('INSERT OR IGNORE INTO candidate_content_receipts VALUES(?,?,?,?)',
                    (row.identity,economic_hash,row.transaction_index,available))
                if row.transaction_index is not None:
                    self.db.execute('UPDATE candidate_content_receipts SET transaction_index=? WHERE identity=? AND transaction_index IS NULL',
                        (row.transaction_index,row.identity))
                if old or previous_cache or cold:
                    # A verified scoped cache is the current body pointer; an
                    # older empty records row must not hide it. All durable
                    # copies still have to agree on hash and first availability.
                    prior=previous_cache if previous_cache and previous_cache[0] is not None else old or cold or previous_cache
                    if any(tuple(copy[1:3])!=tuple(prior[1:3]) for copy in (old,previous_cache,cold) if copy):
                        raise EvidenceConflict('local_evidence_hash_mismatch')
                    if prior[0] is not None:body=decode_body(prior[0],self.db)
                    else:
                        body=restored.get(row.identity)
                        if body is None and cold:
                            from .solana_scoped_retirement import ScopedRetirement
                            body=ScopedRetirement(self).body(row.identity)
                        if body is None and receipt:
                            # A selective physical refetch can restore a globally
                            # archived body, but only as the exact old immutable
                            # body. Native-order enrichment remains an attestation.
                            table='records' if old else 'scoped_cold_records'
                            original_index=self.db.execute('SELECT transaction_index FROM '+table+' WHERE identity=?',(row.identity,)).fetchone()[0]
                            body=dict(incoming,transaction_index=original_index)
                            if digest(body)!=prior[1]:raise EvidenceConflict('local_evidence_hash_mismatch')
                        if body is None:raise EvidenceUnavailable('selective_archive_restore_required')
                    if digest(body)!=prior[1]:raise EvidenceConflict('local_evidence_hash_mismatch')
                    self._compatible(body,incoming)
                    self.attest_order(row.scope,row.slot,row.signature,row.transaction_index)
                    if old and old[0] is not None:continue
                    cached.append((row,body,prior[2]))
                    continue
                floor=self.db.execute('SELECT value FROM meta WHERE key=?',('retention_floor:'+row.scope,)).fetchone()
                from .solana_maintenance_state import PRESERVATION_SECONDS
                historical=row.market_time is not None and row.market_time<=self.clock()-PRESERVATION_SECONDS
                # Backfill and overlapping native replay may introduce evidence
                # whose market-age maintenance lease has already elapsed. Keep
                # its complete body in the candidate cache instead of creating
                # instantly overdue debt in the current global hot pipeline.
                # Both are part of canonical_evidence and use the same pins,
                # scoped retirement guards and physical storage limit.
                if historical or floor and row.slot<int(floor[0]):cached.append((row,incoming,row.observed_at))
                else:hot.append(row)
            self.writer.ingest(hot)
            for row,body,available in cached:
                raw=canonical(body)
                self.db.execute('''INSERT OR IGNORE INTO shared_history_cache VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)''',
                    (row.identity,row.scope,row.slot,row.signature,row.program,row.market_time,
                     body['event_index'],body['transaction_index'],row.kind,raw,digest(body),available))
                for address in body['addresses']:
                    self.db.execute('INSERT OR IGNORE INTO cached_addresses VALUES(?,?)',(row.identity,address))
                self.attest_order(row.scope,row.slot,row.signature,row.transaction_index)
            for row in rows:
                if row.kind=='event':
                    available=self.db.execute('SELECT first_seen FROM canonical_evidence WHERE identity=?',(row.identity,)).fetchone()[0]
                    # A distinct monotonic namespace preserves a consumer's old
                    # records-rowid checkpoint across this one-way cutover.
                    self.db.execute('''INSERT OR IGNORE INTO candidate_outbox
                        SELECT COALESCE(MAX(sequence)+1,4611686018427387904),?,?,?,?
                        FROM candidate_outbox''',(row.identity,row.scope,row.slot,available))
            if hasattr(self,'lifecycle'):self.lifecycle.queue_records(rows)
            # Same physical 2-GiB guard, including metadata and the scoped cache.
            import os
            if sum(os.path.getsize(p) for p in (self.writer.path,str(self.writer.path)+'-wal') if os.path.exists(p))>=self.writer.max_hot_bytes:
                raise EvidenceUnavailable('hot_store_capacity')

    @staticmethod
    def content_hash(body):
        economic=dict(body);economic.pop('transaction_index')
        if economic['kind']=='transaction':
            economic['payload']=rpc_economic_transaction(dict(economic['payload'],transactionIndex=0),rich=True)
        return digest(economic)

    @staticmethod
    def _compatible(old,new):
        old=dict(old);new=dict(new)
        old_index=old.pop('transaction_index');new_index=new.pop('transaction_index')
        if old_index is not None and old_index!=new_index:raise EvidenceConflict('candidate_native_order_conflict')
        if old['kind']=='transaction':
            old['payload']=rpc_economic_transaction(dict(old['payload'],transactionIndex=new_index),rich=True)
            new['payload']=rpc_economic_transaction(dict(new['payload'],transactionIndex=new_index),rich=True)
        if old!=new:raise EvidenceConflict('candidate_economic_content_conflict')

    def prove(self,proof):
        """Compact address coverage without unbounded maintenance scope IDs.

        Each point retains its original availability. A later append/repair can
        never make a prospective interval complete before it actually arrived.
        Compression avoids one repeated JSON proof per candidate per block.
        """
        proof.validate();scope=proof.scope
        if not scope.startswith('candidate:'):raise EvidenceUnavailable('candidate_scope_shape')
        at=float(proof.observed_at);point=[proof.lower_slot,proof.upper_slot,at]
        with self.writer.transaction():
            prior=self.db.execute('''SELECT lo,hi,count,first_available,last_available,points,hash,lineage,source
                FROM candidate_coverage WHERE scope=? ORDER BY lo DESC LIMIT 1''',(scope,)).fetchone()
            append=prior and prior[2]<256 and prior[1]+1==proof.lower_slot and prior[4]<=at and prior[8]==proof.source
            if append:
                points=coverage_points(prior[5],prior[6]);points.append(point)
                lo=prior[0];first=prior[3];lineage=digest([prior[7],proof.witness['lineage_hash']])
            else:points=[point];lo=proof.lower_slot;first=at;lineage=proof.witness['lineage_hash']
            packed=zlib.compress(canonical(points).encode(),1);checksum=hashlib.sha256(packed).hexdigest()
            existing=self.db.execute('SELECT points,hash FROM candidate_coverage WHERE scope=? AND lo=?',(scope,lo)).fetchone()
            if existing and not append:
                # An overlapping later repair stays a distinct version; it may
                # not replace the first point's availability or lineage.
                original=coverage_points(existing[0],existing[1])
                if any(a==point[0] and b==point[1] and available<=at for a,b,available in original):
                    if proof.source=='alchemy_finalized_repair':self._repair_gap_segments(proof,at)
                    return
                points=original+[point];packed=zlib.compress(canonical(points).encode(),1)
                checksum=hashlib.sha256(packed).hexdigest();first=min(p[2] for p in points)
            self.db.execute('INSERT OR REPLACE INTO candidate_coverage VALUES(?,?,?,?,?,?,?,?,?,?)',
                (scope,lo,max(p[1] for p in points),len(points),first,at,packed,checksum,lineage,proof.source))
            if proof.source=='alchemy_finalized_repair':
                self._repair_gap_segments(proof,at)

    def _repair_gap_segments(self,proof,at):
        """Retain the gap audit and only the still-unproved residual intervals."""
        repaired_at=max(at,float(self.clock()))
        rows=self.db.execute('''SELECT id,lo,hi,created,reason FROM candidate_gaps
            WHERE scope=? AND repaired IS NULL AND lo<=? AND (hi IS NULL OR hi>=?)''',
            (proof.scope,proof.upper_slot,proof.lower_slot)).fetchall()
        for identity,lo,hi,created,reason in rows:
            self.db.execute('UPDATE candidate_gaps SET repaired=? WHERE id=?',(repaired_at,identity))
            residual=[]
            if lo<proof.lower_slot:residual.append((lo,proof.lower_slot-1))
            if hi is None or hi>proof.upper_slot:residual.append((proof.upper_slot+1,hi))
            for a,b in residual:
                self.db.execute('INSERT INTO candidate_gaps(scope,lo,hi,created,reason) VALUES(?,?,?,?,?)',
                    (proof.scope,a,b,created,reason))

    def gap(self,scope,lo,hi,reason):
        with self.writer.transaction():
            self.db.execute('INSERT INTO candidate_gaps(scope,lo,hi,created,reason) VALUES(?,?,?,?,?)',
                (scope,lo,hi,self.clock(),reason))

    def attest_order(self,scope,slot,signature,index):
        checksum=digest([scope,slot,signature,index])
        old=self.db.execute('SELECT transaction_index,hash FROM native_order_attestations WHERE scope=? AND slot=? AND signature=?',(scope,slot,signature)).fetchone()
        if old and tuple(old)!=(index,checksum):raise EvidenceConflict('candidate_native_order_conflict')
        self.db.execute('INSERT OR IGNORE INTO native_order_attestations VALUES(?,?,?,?,?)',(scope,slot,signature,index,checksum))

    def delivery(self,family,transport,*,raw_bytes,rpc_cu=0,calls=0,retained_bytes=0,canonical_bytes=0,ipc_bytes=0,seen=None):
        values=(raw_bytes,retained_bytes,canonical_bytes,ipc_bytes,rpc_cu,calls)
        if any(type(n) is not int or n<0 for n in values):raise EvidenceUnavailable('provider_meter_shape')
        if transport not in ('yellowstone','websocket','rpc'):raise EvidenceUnavailable('provider_meter_transport')
        day=int(self.clock() if seen is None else seen)//86400
        with self.writer.transaction():
            self.db.execute('''INSERT INTO provider_delivery VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(day,family,transport) DO UPDATE SET raw_bytes=raw_bytes+excluded.raw_bytes,
                retained_bytes=retained_bytes+excluded.retained_bytes,canonical_bytes=canonical_bytes+excluded.canonical_bytes,
                ipc_bytes=ipc_bytes+excluded.ipc_bytes,rpc_cu=rpc_cu+excluded.rpc_cu,calls=calls+excluded.calls''',
                (day,family,transport,*values))

    def telemetry(self):
        jobs=dict(self.db.execute('SELECT status,COUNT(*) FROM acquisition_jobs GROUP BY status'))
        oldest=self.db.execute("SELECT MIN(created) FROM acquisition_jobs WHERE status='pending'").fetchone()[0]
        return dict(candidates=self.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0],
            jobs=jobs,oldest_queued_seconds=0 if oldest is None else max(0,self.clock()-oldest),
            deadline_misses=self.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='deadline_missed'").fetchone()[0],
            capacity_pressure=self.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='capacity_pressure'").fetchone()[0])


class CandidateReader:
    """Address coverage over a single shared canonical content store."""
    def __init__(self,reader,family,address):
        self.reader=reader;self.db=reader.db;self.family=family;self.address=address
        binding=self.db.execute('SELECT canonical_scope,coverage_scope,market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
        if binding is None:raise EvidenceUnavailable('candidate_binding_incomplete')
        self.base,self.scope,self.market_address=binding
        self.canonical_scope=self.base

    def window(self,scope,lower_slot,upper_slot,*,as_of,address=None,kind='event',limit=10000):
        if scope!=self.scope or address is not None and address!=self.address:
            raise EvidenceUnavailable('candidate_reader_scope_mismatch')
        if not 1<=limit<=10000:raise EvidenceUnavailable('query_bound')
        self.db.execute('BEGIN')
        try:
            if not self.covered(self.scope,lower_slot,upper_slot,as_of=as_of):
                raise EvidenceUnavailable('unresolved_evidence_gap')
            # The proof covers this candidate only. Content identities and first
            # availability remain shared; no global coverage is minted here.
            sql='''SELECT r.body,r.identity,r.hash FROM canonical_evidence r JOIN canonical_addresses a
                ON a.identity=r.identity WHERE a.address=? AND r.scope=?
                AND r.slot BETWEEN ? AND ? AND r.first_seen<=?'''
            args=[self.market_address,self.base,lower_slot,upper_slot,as_of]
            if kind:sql+=' AND r.kind=?';args.append(kind)
            sql+=' ORDER BY r.slot,r.transaction_index,r.event_index,r.identity LIMIT ?'
            rows=self.db.execute(sql,(*args,limit+1)).fetchall()
            if len(rows)>limit:raise EvidenceUnavailable('local_evidence_query_bound')
            result=[]
            for raw,identity,checksum in rows:
                if raw is None:raise EvidenceUnavailable('evidence_requires_offline_archive_restore')
                row=decode_body(raw,self.db)
                if digest(row)!=checksum:raise EvidenceConflict('local_evidence_hash_mismatch')
                if row['transaction_index'] is None:
                    native=self.db.execute('''SELECT transaction_index,hash FROM native_order_attestations
                        WHERE scope=? AND slot=? AND signature=?''',(self.base,row['slot'],row['signature'])).fetchone()
                    if native:
                        if native[1]!=digest([self.base,row['slot'],row['signature'],native[0]]):
                            raise EvidenceConflict('candidate_native_order_conflict')
                        row=dict(row,transaction_index=native[0])
                result.append(row)
            return result
        finally:self.db.execute('ROLLBACK')

    def covered(self,scope,lo,hi,*,as_of):
        self.reader._healthy()
        if scope!=self.scope or type(lo) is not int or type(hi) is not int or not 0<=lo<=hi:
            raise EvidenceUnavailable('invalid_query_window')
        if self.db.execute('''SELECT 1 FROM candidate_gaps WHERE scope=? AND lo<=?
            AND (hi IS NULL OR hi>=?) AND created<=? AND (repaired IS NULL OR repaired>?) LIMIT 1''',
            (scope,hi,lo,as_of,as_of)).fetchone():return False
        intervals=[]
        for packed,checksum in self.db.execute('''SELECT points,hash FROM candidate_coverage
            WHERE scope=? AND hi>=? AND lo<=? AND first_available<=? ORDER BY lo''',(scope,lo,hi,as_of)):
            intervals.extend((a,b) for a,b,at in coverage_points(packed,checksum) if at<=as_of)
        cursor=lo
        for a,b in sorted(intervals):
            if b<cursor:continue
            if a>cursor:return False
            cursor=max(cursor,b+1)
            if cursor>hi:return True
        return False

    def boundary(self,slot,as_of):
        row=self.db.execute('''SELECT MAX(r.slot) FROM canonical_evidence r JOIN canonical_addresses a
            ON a.identity=r.identity WHERE a.address=? AND r.scope=? AND r.kind='transaction'
            AND r.slot<=? AND r.first_seen<=?''',(self.market_address,self.base,slot,as_of)).fetchone()
        return None if not row or row[0] is None else row


def coverage_points(packed,checksum):
    if hashlib.sha256(packed).hexdigest()!=checksum:raise EvidenceConflict('candidate_coverage_corrupt')
    if len(packed)>1024*1024:raise EvidenceUnavailable('candidate_coverage_bound')
    decoder=zlib.decompressobj();raw=decoder.decompress(packed,1024*1024+1)
    if len(raw)>1024*1024 or not decoder.eof:raise EvidenceUnavailable('candidate_coverage_bound')
    points=json.loads(raw)
    if not isinstance(points,list) or not points or len(points)>4096:
        raise EvidenceUnavailable('candidate_coverage_bound')
    return points


class ConsumerReader:
    """Narrow facade: discovery can enumerate content but cannot qualify a market."""
    def __init__(self,reader):
        self.original=reader;self.db=ReadTables(reader.db);self.path=reader.path
    def __getattr__(self,name):return getattr(self.original,name)
    def candidate(self,family,address):return CandidateReader(self.original,family,address)
    def window(self,scope,lo,hi,*,as_of,address=None,kind=None,limit=2048):
        family=next((f for f,s in FAMILIES.items() if s==scope),None)
        if family and address:
            candidate=self.candidate(family,address)
            return candidate.window(candidate.scope,lo,hi,as_of=as_of,address=address,kind=kind,limit=limit)
        raise EvidenceUnavailable('candidate_specific_coverage_required')
    def discovery(self,sequence,*,as_of,limit=5000):
        self.original._healthy()
        if not 1<=limit<=5000:raise EvidenceUnavailable('query_bound')
        rows=self.db.execute('''SELECT o.sequence,r.body,r.slot,r.identity,r.signature,
            r.transaction_index,r.event_index,r.market_time,r.first_seen FROM candidate_outbox o
            JOIN canonical_evidence r ON r.identity=o.identity WHERE o.scope='program:pump'
            AND o.sequence>? AND o.first_seen<=? ORDER BY o.sequence LIMIT ?''',(sequence,as_of,limit)).fetchall()
        if any(row[1] is None for row in rows):raise EvidenceUnavailable('pump_consumer_backlog_archived')
        return rows


class ReadTables:
    """Read-only compatibility for the immutable canonical content views."""
    def __init__(self,db):self.original=db
    def __getattr__(self,name):return getattr(self.original,name)
    def execute(self,sql,params=()):
        import re
        if sql.lstrip().upper().startswith('SELECT'):
            sql=re.sub(r'\brecords\b','canonical_evidence',sql)
            sql=re.sub(r'\baddresses\b','canonical_addresses',sql)
        return self.original.execute(sql,params)
