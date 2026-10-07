"""Durable scout handoff and recovery for candidate-scoped evidence.

This owner has observation authority only. An activity wake requests evidence;
the native lane still constructs and evaluates its unchanged economic vector.
The cross-database outbox is committed in the canonical store first, consumed
idempotently in CandidateHistory second, and checkpointed last.
"""
from contextlib import closing
import json
import os
import time

from .runtime.candidate_history import CandidateHistory
from .solana_evidence_plane import EvidenceUnavailable,IntervalProof,canonical,digest,decode_body
from .solana_selective_history import FAMILIES,coverage_scope,coverage_points

SCHEMA='''
CREATE TABLE IF NOT EXISTS candidate_lifecycle(
 family TEXT NOT NULL,address TEXT NOT NULL,state TEXT NOT NULL,epoch INTEGER NOT NULL,
 first_slot INTEGER NOT NULL,last_slot INTEGER NOT NULL,first_seen REAL NOT NULL,
 last_seen REAL NOT NULL,deadline REAL,lower_slot INTEGER NOT NULL,
 PRIMARY KEY(family,address));
CREATE TABLE IF NOT EXISTS candidate_history_outbox(
 id TEXT PRIMARY KEY,family TEXT NOT NULL,address TEXT NOT NULL,kind TEXT NOT NULL,
 body TEXT NOT NULL,hash TEXT NOT NULL,created REAL NOT NULL,consumed REAL);
CREATE INDEX IF NOT EXISTS candidate_history_pending ON candidate_history_outbox(consumed,created);
CREATE TABLE IF NOT EXISTS candidate_checkpoints(
 scope TEXT PRIMARY KEY,slot INTEGER NOT NULL,receipt TEXT NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS candidate_evidence_pins(
 scope TEXT NOT NULL,owner TEXT NOT NULL,reason TEXT NOT NULL,lower_slot INTEGER NOT NULL,
 PRIMARY KEY(scope,owner,reason));
CREATE TABLE IF NOT EXISTS candidate_pending_proofs(
 id TEXT PRIMARY KEY,scope TEXT NOT NULL,lo INTEGER NOT NULL,hi INTEGER NOT NULL,
 source TEXT NOT NULL,endpoint TEXT NOT NULL,body TEXT NOT NULL,available REAL NOT NULL);
CREATE TABLE IF NOT EXISTS candidate_activity_receipts(
 family TEXT NOT NULL,address TEXT NOT NULL,slot INTEGER NOT NULL,signature TEXT NOT NULL,
 PRIMARY KEY(family,address,slot,signature));
'''


class CandidateLifecycle:
    def __init__(self,history,*,candidate_path=None):
        self.history=history;self.writer=history.writer;self.db=history.db;self.clock=history.clock
        self.path=candidate_path or os.environ.get('MM_SOLANA_CANDIDATE_HISTORY_DB') or (
            self.writer.path.parent/'solana-candidate-history.sqlite')
        if str(self.path)==str(self.writer.path):raise EvidenceUnavailable('candidate_history_store_must_be_separate')
        self.db.executescript(SCHEMA)
        if 'priority' not in {r[1] for r in self.db.execute('PRAGMA table_info(candidate_history_outbox)')}:
            self.db.execute('ALTER TABLE candidate_history_outbox ADD COLUMN priority INTEGER NOT NULL DEFAULT 3')
            self.db.execute("UPDATE candidate_history_outbox SET priority=CASE kind WHEN 'canonical' THEN 0 WHEN 'promotion' THEN 1 ELSE 3 END")
        self.db.execute('CREATE INDEX IF NOT EXISTS candidate_history_dispatch ON candidate_history_outbox(consumed,priority,created)')
        self.db.execute('CREATE INDEX IF NOT EXISTS candidate_history_identity_pending ON candidate_history_outbox(family,address,consumed)')

    def emit(self,family,address,kind,body,*,at=None):
        at=self.clock() if at is None else at
        identity=digest([family,address,kind,body])
        priority=0 if kind=='canonical' else 1 if kind=='promotion' else 3
        if priority==3:
            active=self.db.execute("SELECT 1 FROM candidate_lifecycle WHERE family=? AND address=? AND state IN ('queued','warming','active')",(family,address)).fetchone()
            pinned=self.db.execute('SELECT 1 FROM service_interests s JOIN interests i ON i.owner=s.owner AND i.scope=s.scope WHERE i.active=1 AND s.address=? AND s.scope=? LIMIT 1',(address,FAMILIES[family])).fetchone()
            if active or pinned:priority=2
        self.db.execute('INSERT OR IGNORE INTO candidate_history_outbox(id,family,address,kind,body,hash,created,consumed,priority) VALUES(?,?,?,?,?,?,?,NULL,?)',
            (identity,family,address,kind,canonical(body),digest(body),at,priority))
        return identity

    def observe(self,family,address,*,slot,seen,fields,activity=False,signature=''):
        """Retain every scope locator. Ranking and capital are absent."""
        with self.writer.transaction():
            old=self.db.execute('SELECT state,epoch,last_slot FROM candidate_lifecycle WHERE family=? AND address=?',
                (family,address)).fetchone()
            if old and slot<old[2]:return
            self.db.execute('''INSERT INTO candidate_lifecycle VALUES(?,?,'cheap_retained',0,?,?,?,?,NULL,?)
                ON CONFLICT(family,address) DO UPDATE SET last_slot=MAX(last_slot,excluded.last_slot),
                last_seen=MAX(last_seen,excluded.last_seen)''',(family,address,slot,slot,seen,seen,slot))
            self.emit(family,address,'scout',dict(slot=slot,seen=seen,fields=fields,signature=signature),at=seen)
            if activity:
                self.wake(family,address,slot=slot,seen=seen,signature=signature,
                    evidence=dict(fields,source='finalized_account_write'))

    def wake(self,family,address,*,slot,seen,signature,evidence):
        """Accept a conservative activity superset without inventing an event."""
        with self.writer.transaction():
            old=self.db.execute('SELECT state,epoch,last_slot FROM candidate_lifecycle WHERE family=? AND address=?',
                (family,address)).fetchone()
            if old is None:return False
            if slot<old[2]:return False
            inserted=self.db.execute('INSERT OR IGNORE INTO candidate_activity_receipts VALUES(?,?,?,?)',
                (family,address,slot,signature)).rowcount
            if not inserted:return False
            receipt=self.emit(family,address,'activity',dict(slot=slot,seen=seen,signature=signature,
                evidence=evidence,economic_event=False,entry_authority=False),at=seen)
            if old[0] in ('reactivated','queued','warming','active'):return False
            # A native bin-array locator alone does not certify WSOL pairing.
            locator=self.db.execute('SELECT fields FROM market_observations WHERE family=? AND address=?',
                (family,address)).fetchone()
            if family=='meteora' and (not locator or not json.loads(locator[0]).get('wsol_pair_locator')):
                return False
            epoch=old[1]+1
            self.db.execute("UPDATE candidate_lifecycle SET state='reactivated',epoch=?,last_slot=?,last_seen=? WHERE family=? AND address=?",
                (epoch,slot,seen,family,address))
            self.emit(family,address,'reactivated',dict(epoch=epoch,slot=slot,seen=seen,receipt=receipt),at=seen)
            return True

    def promote(self,family,address,*,deadline,lower_slot=None):
        """Promotion allocates observation work, never entry or funding."""
        with self.writer.transaction():
            row=self.db.execute('SELECT state,epoch,first_slot,last_seen,lower_slot,first_seen FROM candidate_lifecycle WHERE family=? AND address=?',
                (family,address)).fetchone()
            if row is None:return None
            if row[0] in ('queued','warming','active'):return None
            if deadline<=self.clock():raise EvidenceUnavailable('candidate_decision_deadline_missed')
            lo=row[4] if lower_slot is None else lower_slot
            self.history.bind(family,address)
            if family=='meteora' and hasattr(self.history,'rolling') and lower_slot is None:
                # Meteora begins its exact warmup AFTER fresh compatibility and
                # a new swap. The old structural discovery timestamp supplies
                # no historical qualification authority or cold-RPC obligation.
                scopes=self.history.rolling.scopes(family,self.history.scope_for(family,address))
                head=self.db.execute('SELECT MAX(slot) FROM candidate_blocks WHERE scope IN ('+','.join('?' for _ in scopes)+')',
                    scopes).fetchone() if self.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='candidate_blocks'").fetchone() else None
                if head and head[0] is not None:lo=head[0]
            self.db.execute("UPDATE candidate_history_outbox SET priority=MIN(priority,2) WHERE family=? AND address=? AND consumed IS NULL",(family,address))
            self.db.execute("UPDATE candidate_lifecycle SET state='queued',deadline=?,lower_slot=? WHERE family=? AND address=?",
                (deadline,lo,family,address))
            if hasattr(self.history,'rolling'):
                from .solana_selective_runtime import CONTROL
                upper=self.db.execute('SELECT MAX(hi) FROM coverage WHERE scope=?',(CONTROL,)).fetchone()[0]
                # Structural Meteora exact history starts at its authoritative
                # fresh compatibility snapshot, then the native trigger/warmup.
                # An old scout slot is not an instruction to cold-rebuild state.
                if upper is not None and upper>=lo and (family!='meteora' or lower_slot is not None):
                    self.history.rolling.prepare(family,address,lo,upper,deadline=deadline)
            body=dict(epoch=row[1],first_slot=row[2],observed_at=row[3],first_seen=row[5],ready_at=self.clock(),
                decision_deadline=deadline,lower_slot=lo,entry_authority=False)
            return self.emit(family,address,'promotion',body)

    def demote(self,family,address,*,reason):
        with self.writer.transaction():
            self.db.execute("UPDATE candidate_lifecycle SET state='demoted' WHERE family=? AND address=?",(family,address))
            self.emit(family,address,'demoted',dict(reason=reason,at=self.clock(),recoverable=True))

    def queue_records(self,rows):
        """Called inside the canonical ingestion transaction."""
        for row in rows:
            for family,address,market in self.db.execute('''SELECT DISTINCT family,
                substr(coverage_scope,length('candidate:'||family||':')+1),market_address
                FROM evidence_bindings WHERE canonical_scope=? AND market_address IN ('''+','.join('?' for _ in row.addresses)+')',
                (row.scope,*row.addresses)):
                if market not in row.addresses:continue
                # Preserve the original first availability on duplicate delivery.
                stored=self.db.execute('SELECT body,first_seen FROM canonical_evidence WHERE identity=?',(row.identity,)).fetchone()
                body=decode_body(stored[0],self.db)
                self.emit(family,address,'canonical',dict(record=body,available=stored[1]))

    def flush(self,*,limit=64):
        """Canonical commit -> CandidateHistory commit -> durable consumed receipt.

        A crash after the external commit repeats the same identity, not a new
        observation, work item, decision, or funding disposition.
        """
        if self.db.in_transaction:raise EvidenceUnavailable('candidate_consumer_before_canonical_commit')
        rows=self.db.execute('''SELECT id,family,address,kind,body,hash,created FROM candidate_history_outbox
            WHERE consumed IS NULL ORDER BY priority,created,rowid LIMIT ?''',(limit,)).fetchall()
        if not rows:return 0
        with closing(CandidateHistory(self.path,clock=self.clock)) as shared:
            shared.db.execute('''CREATE TABLE IF NOT EXISTS source_receipts(
                id TEXT PRIMARY KEY,family TEXT NOT NULL,address TEXT NOT NULL,kind TEXT NOT NULL,
                at REAL NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL)''')
            with shared.transaction():
                for identity,family,address,kind,raw,checksum,at in rows:
                    body=json.loads(raw)
                    if digest(body)!=checksum:raise EvidenceUnavailable('candidate_history_outbox_corrupt')
                    lane='pump' if family in ('pump','pumpswap') else 'meteora'
                    bind=self.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
                    candidate=address if not bind else bind[0]
                    if kind=='scout':
                        shared.observe(lane,candidate,surface='meteora-dlmm' if family=='meteora' else family,
                            observed_at=int(at),metadata=dict(structural_scout=body['fields'],recoverable=True))
                    elif kind=='canonical':
                        r=body['record']
                        if family=='pump':
                            event=dict(r['payload']['event'],_economic_order=r['transaction_index'],available_time=int(body['available']))
                            mint=event['mint'];prior=shared.candidate('pump',mint)
                            shared.observe('pump',mint,surface='pumpswap' if event['event_type']=='migration' or prior and prior['surface']=='pumpswap' else 'pump.fun',
                                observed_at=event['market_time'],metadata=dict(source='solana_finalized_evidence_plane',
                                    **{k:event[k] for k in ('creator','pool') if event.get(k)}))
                            if hasattr(self.history,'rolling'):
                                shared.append_reference('pump',mint,r,path=self.writer.path,
                                    identity='pump-source:'+r['identity'],kind='pump_'+event['event_type'],
                                    payload_fields=dict(_economic_order=r['transaction_index'],available_time=int(body['available'])))
                            else:
                                shared.retain_pump_source_history([dict(identity=r['identity'],slot=r['slot'],
                                    transaction_index=r['transaction_index'],event_index=r['event_index'],market_time=r['market_time'],event=event)])
                        elif family=='pumpswap':
                            event=r['payload']['event']
                            if hasattr(self.history,'rolling'):
                                shared.append_reference('pump',candidate,r,path=self.writer.path,
                                    identity=str(event.get('id') or r['identity']),kind='pumpswap_trade',
                                    payload_fields=dict(_economic_order=r['transaction_index']))
                            else:shared.retain_pumpswap_record(candidate,r,r['transaction_index'])
                        elif family=='meteora' and hasattr(self.history,'rolling'):
                            shared.append_reference('meteora',candidate,r,path=self.writer.path,
                                identity=r['identity'],kind='meteora_economic_packet',
                                payload_fields=dict(pool=candidate,_economic_order=r['transaction_index']))
                    elif kind=='promotion':
                        shared.observe(lane,candidate,surface='meteora-dlmm' if family=='meteora' else family,
                            observed_at=int(body['first_seen']),decision_deadline=int(body['decision_deadline']),
                            metadata=dict(provider_promotion=identity,evidence_state='queued',recoverable=True))
                        if family=='meteora':
                            item=dict(address=address,signal_observed_at=int(body['observed_at']),
                                provider_structural=True,provider_promotion_id=identity,
                                decision_deadline=body['decision_deadline'],lower_slot=body['lower_slot'])
                            shared.enqueue(lane,candidate,kind='warmup',ready_at=body['ready_at'],
                                deadline=body['decision_deadline'],estimate_seconds=147,priority=30,
                                identity='provider:'+identity,payload=dict(candidate=item))
                    else:
                        shared.observe(lane,candidate,surface='meteora-dlmm' if family=='meteora' else family,
                            observed_at=int(at),metadata=dict(evidence_state=kind,recoverable=True))
                    receipt=dict(source_hash=checksum,scope=coverage_scope(family,address),
                        canonical_identity=(body.get('record') or {}).get('identity'))
                    with shared.transaction():
                        shared.db.execute('INSERT OR IGNORE INTO source_receipts VALUES(?,?,?,?,?,?,?)',
                            (identity,family,address,kind,at,canonical(receipt),digest(receipt)))
            # Coverage/ACK may advance only after the external FULL commit.
            # Failure here replays the identical receipt batch idempotently.
            with self.writer.transaction():
                for identity,family,address,kind,raw,checksum,at in rows:
                    body=json.loads(raw)
                    if kind=='canonical':
                        compact=dict(source_hash=checksum,record=dict(identity=body['record']['identity'],
                            slot=body['record']['slot']),available=body['available'])
                        self.db.execute('UPDATE candidate_history_outbox SET consumed=?,body=?,hash=? WHERE id=?',
                            (self.clock(),canonical(compact),digest(compact),identity))
                    else:self.db.execute('UPDATE candidate_history_outbox SET consumed=? WHERE id=?',(self.clock(),identity))
        return len(rows)

    def missing(self,scope,lo,hi):
        """Return exactly the unproved intervals, including unresolved gaps."""
        if hi<lo:return []
        if hasattr(self.history,'rolling'):
            return self.history.rolling.missing(scope.split(':',2)[1],scope,lo,hi)
        spans=[]
        for packed,checksum in self.db.execute('SELECT points,hash FROM candidate_coverage WHERE scope=? AND hi>=? AND lo<=?',(scope,lo,hi)):
            spans.extend((a,b) for a,b,at in coverage_points(packed,checksum) if at<=self.clock())
        result=[];cursor=lo
        for a,b in sorted(spans):
            if b<cursor:continue
            if a>cursor:result.append((cursor,min(a-1,hi)))
            cursor=max(cursor,b+1)
            if cursor>hi:break
        if cursor<=hi:result.append((cursor,hi))
        result.extend((max(lo,a),min(hi,b if b is not None else hi)) for a,b in self.db.execute(
            '''SELECT lo,hi FROM candidate_gaps WHERE scope=? AND created<=?
                AND (repaired IS NULL OR repaired>?) AND lo<=? AND (hi IS NULL OR hi>=?)''',
            (scope,self.clock(),self.clock(),hi,lo)))
        merged=[]
        for a,b in sorted(result):
            if merged and a<=merged[-1][1]+1:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
            else:merged.append((a,b))
        return merged

    def repair(self,desired,tip):
        """Restore original deadlines and EDF priority, without restarting age."""
        jobs=[]
        with self.writer.transaction():
            for row in sorted(desired,key=lambda r:(r['priority'],r['deadline'])):
                checkpoint=self.db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',(row['scope'],)).fetchone()
                lo=row['lower_slot'] if checkpoint is None else max(row['lower_slot'],checkpoint[0]+1)
                for a,b in self.missing(row['scope'],lo,tip):
                    # Pending work is an obligation, never a coverage proof.
                    # Rebuilds may share that obligation across authenticated
                    # aliases instead of restarting the same archive at zero.
                    remaining=[(a,b)]
                    pending=self.db.execute('''SELECT id,address,lo,hi FROM acquisition_jobs
                        WHERE family=? AND status='pending' AND deadline>? AND lo<=? AND hi>=?
                        ORDER BY lo,hi''',(row['family'],self.clock(),b,a)).fetchall()
                    for identity,address,p,q in pending:
                        if self.history.scope_for(row['family'],address)!=row['scope']:continue
                        if not any(p<=y and q>=x for x,y in remaining):continue
                        self.db.execute('UPDATE acquisition_jobs SET priority=MIN(priority,?),deadline=MIN(deadline,?) WHERE id=?',
                            (row['priority'],row['deadline'],identity))
                        if identity not in jobs:jobs.append(identity)
                        tail=[]
                        for x,y in remaining:
                            if p>y or q<x:tail.append((x,y));continue
                            if x<p:tail.append((x,p-1))
                            if q<y:tail.append((q+1,y))
                        remaining=tail
                    for x,y in remaining:
                        self.history.gap(row['scope'],x,y,'candidate_restart_or_subscription_rebuild')
                        job=self.history.request(row['family'],row['address'],x,y,
                            priority=row['priority'],deadline=row['deadline'])
                        jobs.append(job)
                        if hasattr(self.history,'rolling'):
                            self.db.execute('INSERT OR IGNORE INTO backfill_reasons VALUES(?,?,?)',
                                (job,'RECOVERY_GAP',canonical(dict(scope=row['scope'],lo=x,hi=y))))
        return jobs

    def checkpoint(self,scope,slot,receipt):
        # This method is called in the same transaction as the complete proof.
        if self.unconsumed(scope,through=slot):
            raise EvidenceUnavailable('candidate_checkpoint_ahead_of_history')
        old=self.db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',(scope,)).fetchone()
        if old and slot<old[0]:return
        self.db.execute('INSERT OR REPLACE INTO candidate_checkpoints VALUES(?,?,?,?)',(scope,slot,receipt,self.clock()))

    def unconsumed(self,scope,*,through=None):
        family,address=scope.split(':',2)[1:]
        from .solana_rolling_history import program_scope
        bound='' if through is None else " AND (kind!='canonical' OR json_extract(body,'$.record.slot')<=?)"
        tail=() if through is None else (through,)
        if family in ('pump','pumpswap') and scope==program_scope(family):
            return self.db.execute("SELECT 1 FROM candidate_history_outbox WHERE family=? AND kind='canonical' AND consumed IS NULL"+bound+' LIMIT 1',(family,*tail)).fetchone()
        if hasattr(self.history,'rolling') and address.startswith('group-'):
            return self.db.execute('''SELECT 1 FROM candidate_history_outbox o JOIN rolling_group_members m
                ON m.family=o.family AND m.address=o.address WHERE m.scope=? AND o.consumed IS NULL'''+bound+' LIMIT 1',(scope,*tail)).fetchone()
        aliases=list({address,*[r[0] for r in self.db.execute('SELECT address FROM evidence_bindings WHERE family=? AND coverage_scope=?',(family,scope))]})
        return self.db.execute('SELECT 1 FROM candidate_history_outbox WHERE consumed IS NULL AND family=? AND address IN ('+
            ','.join('?' for _ in aliases)+')'+bound+' LIMIT 1',(family,*aliases,*tail)).fetchone()

    def defer_proof(self,proof):
        identity=digest([proof.scope,proof.lower_slot,proof.upper_slot,proof.witness])
        self.db.execute('INSERT OR IGNORE INTO candidate_pending_proofs VALUES(?,?,?,?,?,?,?,?)',
            (identity,proof.scope,proof.lower_slot,proof.upper_slot,proof.source,
             proof.endpoint_identity,canonical(proof.witness),proof.observed_at))

    def publish(self):
        """Proofs become visible only after all source receipts are durable."""
        if self.db.in_transaction:raise EvidenceUnavailable('candidate_consumer_before_canonical_commit')
        self.flush()
        with closing(CandidateHistory(self.path,clock=self.clock)) as shared, self.writer.transaction():
            for identity,scope,lo,hi,source,endpoint,raw,at in self.db.execute(
                    'SELECT * FROM candidate_pending_proofs ORDER BY lo,hi').fetchall():
                family,address=scope.split(':',2)[1:]
                if self.unconsumed(scope,through=hi):continue
                proof=IntervalProof(scope,lo,hi,source,endpoint,json.loads(raw),at)
                proof.validate()
                binding=self.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND coverage_scope=? LIMIT 1',
                    (family,scope)).fetchone()
                candidate=address if binding is None else binding[0]
                # Publish a scheduling receipt only after every canonical row's
                # external consumer receipt is durable. The receipt proves this
                # candidate interval, never program-wide market completeness.
                shared.commit_history_readiness('candidate:'+family+':'+candidate,lo,hi,
                    proof_hash=identity,available=self.clock())
                if hasattr(self.history,'rolling') and address.startswith('group-'):
                    # Fan out scheduler readiness only for actual pending
                    # consumers, not one duplicate history per quiet pool.
                    # Finish the WAL read statement before opening a write
                    # transaction. A concurrent worker commit otherwise leaves
                    # this cursor with a stale snapshot (SQLITE_BUSY_SNAPSHOT).
                    targets=shared.db.execute("SELECT DISTINCT candidate FROM work WHERE lane='meteora' AND status IN ('active','pending')").fetchall()
                    for target, in targets:
                        member=self.db.execute('SELECT lower_slot FROM rolling_group_members WHERE scope=? AND family=? AND address=?',(scope,family,target)).fetchone()
                        if member and member[0]<=hi:
                            shared.commit_history_readiness('candidate:meteora:'+target,max(lo,member[0]),hi,
                                proof_hash=identity,available=self.clock())
                if family in ('pump','pumpswap'):
                    from .solana_selective_runtime import CONTROL
                    lower=(0,) if lo==0 else self.db.execute('SELECT market_time FROM stream_receipts WHERE scope=? AND slot=?',
                        (CONTROL,lo)).fetchone()
                    upper=self.db.execute('SELECT market_time FROM stream_receipts WHERE scope=? AND slot<=? ORDER BY slot DESC LIMIT 1',
                        (CONTROL,hi)).fetchone()
                    if lower and upper:
                        from .solana_rolling_history import program_scope
                        shared.commit_coverage(FAMILIES[family],lo,hi,int(lower[0]),int(upper[0]),
                            proof_hash=identity,candidate=None if scope==program_scope(family) else candidate)
                self.history.prove(proof)
                old=self.db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',(scope,)).fetchone()
                # A later isolated complete island is not a contiguous checkpoint.
                unresolved=self.db.execute('SELECT 1 FROM candidate_gaps WHERE scope=? AND repaired IS NULL AND lo<=? LIMIT 1',(scope,hi)).fetchone()
                if not unresolved and (old is None or lo<=old[0]+1):self.checkpoint(scope,hi,identity)
                self.db.execute('DELETE FROM candidate_pending_proofs WHERE id=?',(identity,))

    def refresh(self):
        """Finish observation leases after native work; keep identities recoverable."""
        rows=self.db.execute("SELECT family,address,deadline FROM candidate_lifecycle WHERE state IN ('queued','warming','active')").fetchall()
        if not rows:return
        with closing(CandidateHistory(self.path,clock=self.clock)) as shared:
            for family,address,deadline in rows:
                promotion=self.db.execute("SELECT id FROM candidate_history_outbox WHERE family=? AND address=? AND kind='promotion' ORDER BY created DESC,rowid DESC LIMIT 1",(family,address)).fetchone()
                work=None if not promotion else shared.db.execute('SELECT status FROM work WHERE id=?',('provider:'+promotion[0],)).fetchone()
                if work and work[0]=='active':
                    self.db.execute("UPDATE candidate_lifecycle SET state='warming' WHERE family=? AND address=?",(family,address))
                if work and work[0] in ('failed','complete','deadline_missed') or deadline is not None and deadline<self.clock():
                    if work and work[0] in ('active','pending'):shared.complete('provider:'+promotion[0],now=self.clock())
                    with self.writer.transaction():
                        self.db.execute("UPDATE candidate_lifecycle SET state='demoted',deadline=NULL WHERE family=? AND address=?",(family,address))
                        self.emit(family,address,'demoted',dict(reason='observation_work_finished_or_deadline',at=self.clock(),recoverable=True))

    def pin(self,scope,owner,reason,lower_slot):
        family,address=scope.split(':',2)[1:];scope=self.history.scope_for(family,address)
        with self.writer.transaction():self.db.execute('INSERT OR REPLACE INTO candidate_evidence_pins VALUES(?,?,?,?)',(scope,owner,reason,lower_slot))

    def unpin(self,scope,owner,reason):
        family,address=scope.split(':',2)[1:];scope=self.history.scope_for(family,address)
        with self.writer.transaction():self.db.execute('DELETE FROM candidate_evidence_pins WHERE scope=? AND owner=? AND reason=?',(scope,owner,reason))

    def rebind_pins(self,old_scope,new_scope):
        with self.writer.transaction():
            for owner,reason,lo in self.db.execute('SELECT owner,reason,lower_slot FROM candidate_evidence_pins WHERE scope=?',(old_scope,)).fetchall():
                self.db.execute('''INSERT INTO candidate_evidence_pins VALUES(?,?,?,?)
                    ON CONFLICT(scope,owner,reason) DO UPDATE SET lower_slot=MIN(lower_slot,excluded.lower_slot)''',
                    (new_scope,owner,reason,lo))
            self.db.execute('DELETE FROM candidate_evidence_pins WHERE scope=?',(old_scope,))
