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

    def emit(self,family,address,kind,body,*,at=None):
        at=self.clock() if at is None else at
        identity=digest([family,address,kind,body])
        self.db.execute('INSERT OR IGNORE INTO candidate_history_outbox VALUES(?,?,?,?,?,?,?,NULL)',
            (identity,family,address,kind,canonical(body),digest(body),at))
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
                    evidence=dict(source='finalized_account_write',**fields))

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
            if old[0] in ('queued','warming','active'):return False
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
            self.db.execute("UPDATE candidate_lifecycle SET state='queued',deadline=?,lower_slot=? WHERE family=? AND address=?",
                (deadline,lo,family,address))
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
                FROM evidence_bindings WHERE canonical_scope=?''',(row.scope,)):
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
            WHERE consumed IS NULL ORDER BY CASE kind WHEN 'canonical' THEN 0 WHEN 'promotion' THEN 1 ELSE 2 END,
            created,rowid LIMIT ?''',(limit,)).fetchall()
        if not rows:return 0
        with closing(CandidateHistory(self.path,clock=self.clock)) as shared:
            shared.db.execute('''CREATE TABLE IF NOT EXISTS source_receipts(
                id TEXT PRIMARY KEY,family TEXT NOT NULL,address TEXT NOT NULL,kind TEXT NOT NULL,
                at REAL NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL)''')
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
                        shared.retain_pump_source_history([dict(identity=r['identity'],slot=r['slot'],
                            transaction_index=r['transaction_index'],event_index=r['event_index'],market_time=r['market_time'],event=event)])
                    elif family=='pumpswap':shared.retain_pumpswap_record(candidate,r,r['transaction_index'])
                    # Meteora raw records remain canonical. Its native verified
                    # tape commits normalized economics through the existing lane.
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
                with self.writer.transaction():
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
            'SELECT lo,hi FROM candidate_gaps WHERE scope=? AND repaired IS NULL AND lo<=? AND (hi IS NULL OR hi>=?)',(scope,hi,lo)))
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
                    self.history.gap(row['scope'],a,b,'candidate_restart_or_subscription_rebuild')
                    jobs.append(self.history.request(row['family'],row['address'],a,b,
                        priority=row['priority'],deadline=row['deadline']))
        return jobs

    def checkpoint(self,scope,slot,receipt):
        # This method is called in the same transaction as the complete proof.
        if self.unconsumed(scope):
            raise EvidenceUnavailable('candidate_checkpoint_ahead_of_history')
        old=self.db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',(scope,)).fetchone()
        if old and slot<old[0]:return
        self.db.execute('INSERT OR REPLACE INTO candidate_checkpoints VALUES(?,?,?,?)',(scope,slot,receipt,self.clock()))

    def unconsumed(self,scope):
        family,address=scope.split(':',2)[1:]
        aliases=list({address,*[r[0] for r in self.db.execute('SELECT address FROM evidence_bindings WHERE family=? AND coverage_scope=?',(family,scope))]})
        return self.db.execute('SELECT 1 FROM candidate_history_outbox WHERE consumed IS NULL AND family=? AND address IN ('+
            ','.join('?' for _ in aliases)+') LIMIT 1',(family,*aliases)).fetchone()

    def defer_proof(self,proof):
        identity=digest([proof.scope,proof.lower_slot,proof.upper_slot,proof.witness])
        self.db.execute('INSERT OR IGNORE INTO candidate_pending_proofs VALUES(?,?,?,?,?,?,?,?)',
            (identity,proof.scope,proof.lower_slot,proof.upper_slot,proof.source,
             proof.endpoint_identity,canonical(proof.witness),proof.observed_at))

    def publish(self):
        """Proofs become visible only after all source receipts are durable."""
        if self.db.in_transaction:raise EvidenceUnavailable('candidate_consumer_before_canonical_commit')
        self.flush()
        with self.writer.transaction():
            for identity,scope,lo,hi,source,endpoint,raw,at in self.db.execute(
                    'SELECT * FROM candidate_pending_proofs ORDER BY lo,hi').fetchall():
                family,address=scope.split(':',2)[1:]
                if self.unconsumed(scope):continue
                self.history.prove(IntervalProof(scope,lo,hi,source,endpoint,json.loads(raw),at))
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
