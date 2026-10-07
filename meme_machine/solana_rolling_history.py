"""Model B uses canonical economics once, candidate views and proved intervals.

No capital or entry authority. Checkpoints never seal an interval. Cold archive
acquisition is requested only for an explicitly missing interval.
"""
import json
from .runtime.operating_families import active_sql
from .solana_evidence_plane import EvidenceUnavailable,digest,canonical,decode_body
from .solana_selective_history import FAMILIES,PROGRAMS,coverage_scope,coverage_points

MODEL_A='MODEL_A_PROMOTION_TIME_BACKFILL'
MODEL_B='MODEL_B_ROLLING_NORMALIZED_PREWARM'
SCHEMA='''
CREATE TABLE IF NOT EXISTS rolling_origins(
 family TEXT NOT NULL,address TEXT NOT NULL,lower_slot INTEGER NOT NULL,
 market_time INTEGER NOT NULL,receipt TEXT NOT NULL,PRIMARY KEY(family,address));
CREATE TABLE IF NOT EXISTS promotion_history_metrics(
 id TEXT PRIMARY KEY,family TEXT NOT NULL,address TEXT NOT NULL,at REAL NOT NULL,
 body TEXT NOT NULL,hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS backfill_reasons(
 job TEXT PRIMARY KEY,reason TEXT NOT NULL,fields TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rolling_boundary_waits(
 family TEXT NOT NULL,address TEXT NOT NULL,observed_slot INTEGER NOT NULL,
 upper_slot INTEGER NOT NULL,deadline REAL NOT NULL,priority INTEGER NOT NULL,
 created REAL NOT NULL,status TEXT NOT NULL,PRIMARY KEY(family,address));
CREATE TABLE IF NOT EXISTS rolling_publication_waits(
 family TEXT NOT NULL,address TEXT NOT NULL,lo INTEGER NOT NULL,hi INTEGER NOT NULL,
 deadline REAL NOT NULL,priority INTEGER NOT NULL,created REAL NOT NULL,status TEXT NOT NULL,
 PRIMARY KEY(family,address,lo,hi));
CREATE TABLE IF NOT EXISTS rolling_group_members(
 scope TEXT NOT NULL,family TEXT NOT NULL,address TEXT NOT NULL,lower_slot INTEGER NOT NULL,
 PRIMARY KEY(scope,family,address));
CREATE INDEX IF NOT EXISTS rolling_member_address ON rolling_group_members(family,address);
CREATE TABLE IF NOT EXISTS rolling_economic_events(
 identity TEXT PRIMARY KEY,scope TEXT NOT NULL,slot INTEGER NOT NULL,signature TEXT NOT NULL,
 program TEXT NOT NULL,market_time INTEGER,event_index INTEGER NOT NULL,transaction_index INTEGER,
 kind TEXT NOT NULL,body TEXT,hash TEXT NOT NULL,first_seen REAL NOT NULL,archive TEXT);
CREATE INDEX IF NOT EXISTS rolling_event_order ON rolling_economic_events(scope,slot,transaction_index,event_index);
CREATE TABLE IF NOT EXISTS rolling_economic_addresses(
 identity TEXT NOT NULL,address TEXT NOT NULL,PRIMARY KEY(identity,address));
CREATE INDEX IF NOT EXISTS rolling_address_lookup ON rolling_economic_addresses(address,identity);
CREATE TABLE IF NOT EXISTS rolling_event_lineage(
 identity TEXT NOT NULL,source TEXT NOT NULL,endpoint TEXT NOT NULL,observed REAL NOT NULL,
 PRIMARY KEY(identity,source,endpoint));
'''


def program_scope(family):return coverage_scope(family,PROGRAMS[family])


class RollingHistory:
    def __init__(self,history):
        self.history=history;self.db=history.db
        self.db.executescript(SCHEMA)
        self.install_views()

    @property
    def clock(self):return self.history.clock

    def install_views(self):
        """Extend the existing canonical view, not a competing event database."""
        cold=self.db.execute("SELECT 1 FROM sqlite_master WHERE name='scoped_cold_records'").fetchone()
        tail='' if not cold else ''' UNION ALL SELECT * FROM scoped_cold_records c
            WHERE NOT EXISTS(SELECT 1 FROM rolling_economic_events e WHERE e.identity=c.identity)
            AND NOT EXISTS(SELECT 1 FROM records r WHERE r.identity=c.identity AND r.body IS NOT NULL)
            AND NOT EXISTS(SELECT 1 FROM shared_history_cache h WHERE h.identity=c.identity)'''
        cold_guard='' if not cold else ' AND NOT EXISTS(SELECT 1 FROM scoped_cold_records c WHERE c.identity=records.identity)'
        script=('''DROP VIEW IF EXISTS canonical_evidence;
            CREATE VIEW canonical_evidence AS SELECT * FROM rolling_economic_events
            UNION ALL SELECT * FROM records WHERE NOT EXISTS(SELECT 1 FROM rolling_economic_events e WHERE e.identity=records.identity)
            AND (body IS NOT NULL OR (NOT EXISTS(SELECT 1 FROM shared_history_cache c WHERE c.identity=records.identity)'''+cold_guard+'''))
            UNION ALL SELECT * FROM shared_history_cache c WHERE NOT EXISTS(SELECT 1 FROM rolling_economic_events e WHERE e.identity=c.identity)
            AND NOT EXISTS(SELECT 1 FROM records r WHERE r.identity=c.identity AND r.body IS NOT NULL)'''+tail+''';
            DROP VIEW IF EXISTS canonical_addresses;
            CREATE VIEW canonical_addresses AS SELECT identity,address FROM rolling_economic_addresses
            UNION SELECT identity,address FROM addresses UNION SELECT identity,address FROM cached_addresses'''+
            ('' if not cold else ' UNION SELECT identity,address FROM scoped_cold_addresses')+';')
        with self.history.writer.transaction():
            for statement in script.split(';'):
                if statement.strip():self.db.execute(statement)

    def store(self,row):
        """The event body lives once, independently of raw/hydration eviction."""
        from dataclasses import replace
        from .solana_evidence_plane import EvidenceConflict
        original=row.body();legacy=None
        if not self.db.execute('SELECT 1 FROM rolling_economic_events WHERE identity=?',(row.identity,)).fetchone():
            legacy=self.db.execute('SELECT body,hash,first_seen FROM canonical_evidence WHERE identity=?',(row.identity,)).fetchone()
        payload=row.payload
        if 'raw_lineage' in payload:
            row=replace(row,payload=dict(event=payload['event'],raw_lineage_hash=digest(payload['raw_lineage'])))
        body=row.body();checksum=digest(body)
        if legacy and legacy[0] is not None:
            old=decode_body(legacy[0],self.db)
            self.history._compatible(old,original)
            # Preserve the original immutable representation on migration.
            # Only newly acquired events omit raw logs from durable economics.
            body=old;checksum=legacy[1]
        prior=self.db.execute('SELECT hash,first_seen,body,transaction_index FROM rolling_economic_events WHERE identity=?',(row.identity,)).fetchone()
        if prior and prior[0]!=checksum:
            original_body=dict(original,transaction_index=prior[3])
            if digest(original_body)!=prior[0]:raise EvidenceConflict('candidate_economic_content_conflict')
            body=original_body;checksum=prior[0]
        receipt=self.db.execute('SELECT first_seen FROM candidate_content_receipts WHERE identity=?',(row.identity,)).fetchone()
        available=prior[1] if prior else (legacy[2] if legacy else receipt[0] if receipt else row.observed_at)
        if prior and prior[2] is None:
            # A physically paid duplicate can restore only this exact immutable
            # normalized body; its first availability and identity do not move.
            self.db.execute('UPDATE rolling_economic_events SET body=?,archive=NULL WHERE identity=?',(canonical(body),row.identity))
        inserted=self.db.execute('INSERT OR IGNORE INTO rolling_economic_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)',
            (row.identity,row.scope,row.slot,row.signature,row.program,row.market_time,row.event_index,body['transaction_index'],
             row.kind,canonical(body),checksum,available)).rowcount
        for address in row.addresses:self.db.execute('INSERT OR IGNORE INTO rolling_economic_addresses VALUES(?,?)',(row.identity,address))
        self.db.execute('INSERT OR IGNORE INTO candidate_content_receipts VALUES(?,?,?,?)',
            (row.identity,self.history.content_hash(body),row.transaction_index,available))
        self.history.attest_order(row.scope,row.slot,row.signature,row.transaction_index)
        self.db.execute('INSERT OR IGNORE INTO rolling_event_lineage VALUES(?,?,?,?)',(row.identity,row.source,row.endpoint_identity,available))
        self.db.execute('INSERT INTO cursors VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET slot=MAX(slot,excluded.slot),updated=excluded.updated',
            (row.scope,row.slot,self.clock()))
        if inserted:self.history.writer._count('ingested_event')
        return row

    def adopt(self,rows):
        """First authoritative create/migration establishes the lower boundary.

        A scout timestamp alone cannot establish creation or graduation. Never
        move a lower boundary forward to make an old candidate seem complete.
        """
        for row in rows:
            if row.kind!='event':continue
            e=row.payload.get('event') or {};family=next(f for f,s in FAMILIES.items() if s==row.scope)
            if family=='pumpswap' and e.get('pool'):
                # The fixed canonical feed already covers every swap and its
                # native order. Wake retained pools from that receipt, without
                # acquiring an additional status feed per quiet-candidate shard.
                self.history.lifecycle.wake(family,e['pool'],slot=row.slot,
                    seen=row.observed_at,signature=row.signature,
                    evidence=dict(source='canonical_program_event',identity=row.identity))
            if family=='pump' and e.get('event_type')=='create':
                mint=e['mint'];curve=e['bonding_curve']
                old=self.db.execute("SELECT coverage_scope,market_address FROM evidence_bindings WHERE family='pump' AND address=?",(curve,)).fetchone()
                if old and old[1]!=mint:
                    self.db.execute("DELETE FROM evidence_bindings WHERE family='pump' AND coverage_scope=?",(old[0],))
                scope=self.history.bind('pump',mint,market_address=mint,aliases=(curve,))
                if old and old[0]!=scope:self.history.lifecycle.rebind_pins(old[0],scope)
                self.db.execute('INSERT OR IGNORE INTO rolling_origins VALUES(?,?,?,?,?)',('pump',mint,row.slot,row.market_time,row.identity))
                self.history.observe('pump',curve,slot=row.slot,signature=row.signature,seen=row.observed_at,
                    fields=dict(mint=mint,creation_slot=row.slot,economic_event=True,activity=False))
            if family=='pump' and e.get('event_type')=='migration':
                pool=e['pool'];self.history.bind('pumpswap',pool)
                self.db.execute('INSERT OR IGNORE INTO rolling_origins VALUES(?,?,?,?,?)',('pumpswap',pool,row.slot,row.market_time,row.identity))
                self.history.observe('pumpswap',pool,slot=row.slot,signature=row.signature,seen=row.observed_at,
                    fields=dict(mint=e['mint'],graduation=e['market_time'],economic_event=True,activity=True))

    def scopes(self,family,scope):
        # Program-filtered Pump/PumpSwap delivery really covers every candidate.
        # It must never be inferred from an address-filtered receipt.
        if family in ('pump','pumpswap'):return (scope,program_scope(family))
        address=scope.split(':',2)[2]
        return (scope,*[s for s, in self.db.execute('SELECT scope FROM rolling_group_members WHERE family=? AND address=?',(family,address))])

    def missing(self,family,scope,lo,hi,*,as_of=None):
        at=self.clock() if as_of is None else as_of
        if hi<lo:return []
        if family=='pump':
            binding=self.db.execute('SELECT market_address FROM evidence_bindings WHERE coverage_scope=? LIMIT 1',(scope,)).fetchone()
            origin=None if not binding else self.db.execute('SELECT lower_slot,receipt FROM rolling_origins WHERE family=? AND address=?',(family,binding[0])).fetchone()
            if origin and origin[0]>lo and self.db.execute('SELECT 1 FROM canonical_evidence WHERE identity=? AND first_seen<=?',(origin[1],at)).fetchone():
                # No mint economics precede its authenticated creation. This is
                # a creation proof, never an inference from a quiet interval.
                lo=origin[0]
                if hi<lo:return []
        scopes=self.scopes(family,scope);marks=','.join('?' for _ in scopes);spans=[]
        for packed,checksum in self.db.execute('SELECT points,hash FROM candidate_coverage WHERE scope IN ('+marks+') AND hi>=? AND lo<=?',(*scopes,lo,hi)):
            spans.extend((a,b) for a,b,available in coverage_points(packed,checksum) if available<=at)
        # Remove unsealed gaps from their own coverage branch. An independently
        # proved overlapping program/candidate branch may genuinely repair one.
        valid=[]
        for source in scopes:
            branch=[]
            floor=self.db.execute('SELECT lower_slot FROM rolling_group_members WHERE scope=? AND family=? AND address=?',
                (source,family,scope.split(':',2)[2])).fetchone()
            for packed,checksum in self.db.execute('SELECT points,hash FROM candidate_coverage WHERE scope=? AND hi>=? AND lo<=?',(source,lo,hi)):
                branch.extend((max(lo,a,0 if floor is None else floor[0]),min(hi,b)) for a,b,t in coverage_points(packed,checksum) if t<=at)
            for a,b in branch:
                pieces=[(a,b)]
                for x,y in self.db.execute('SELECT lo,COALESCE(hi,?) FROM candidate_gaps WHERE scope=? AND created<=? AND (repaired IS NULL OR repaired>?) AND lo<=? AND (hi IS NULL OR hi>=?)',(hi,source,at,at,b,a)):
                    pieces=[p for c,d in pieces for p in ((c,min(d,x-1)),(max(c,y+1),d)) if p[0]<=p[1]]
                valid.extend(pieces)
        result=[];cursor=lo
        for a,b in sorted(valid):
            if b<cursor:continue
            if a>cursor:result.append((cursor,a-1))
            cursor=max(cursor,b+1)
            if cursor>hi:break
        if cursor<=hi:result.append((cursor,hi))
        return result

    def prepare(self,family,address,lo,hi,*,deadline,priority=4,reason=None):
        scope=self.history.scope_for(family,address)
        binding=self.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
        market=address if not binding else binding[0]
        origin=self.db.execute('SELECT lower_slot FROM rolling_origins WHERE family=? AND address=?',(family,market)).fetchone()
        if family=='pump' and lo==0 and not origin:
            observed=self.db.execute("SELECT first_slot FROM candidate_lifecycle WHERE family='pump' AND address=?",(address,)).fetchone()
            observed_slot=hi if observed is None else observed[0]
            start=self.db.execute('SELECT MIN(lo) FROM candidate_coverage WHERE scope=?',(program_scope(family),)).fetchone()[0]
            # An account notification may beat the native log join/publication.
            # First prove that observation slot before classifying an unseen
            # creation as late discovery. Waiting is durable and has no proof
            # or new deadline authority.
            if (start is None or observed_slot>=start) and self.missing(family,program_scope(family),observed_slot,observed_slot):
                self.db.execute('''INSERT INTO rolling_boundary_waits VALUES(?,?,?,?,?,?,?,'pending')
                    ON CONFLICT(family,address) DO UPDATE SET
                    upper_slot=MAX(upper_slot,excluded.upper_slot),deadline=MIN(deadline,excluded.deadline),
                    priority=MIN(priority,excluded.priority)''',
                    (family,address,observed_slot,hi,deadline,priority,self.clock()))
                return dict(model=MODEL_B,history_already_complete_at_promotion=False,
                    missing_intervals=None,backfill_jobs=[],boundary_state='LOWER_BOUND_PENDING_ROLLING_PUBLICATION',
                    decision_deadline=deadline,entry_authority=False)
        # Genesis can be replaced ONLY by the authenticated creation boundary,
        # not first sight, promotion, a timeout or an arbitrary retention floor.
        if lo==0 and origin and family=='pump':lo=origin[0]
        prior_wait=self.db.execute('SELECT deadline,priority FROM rolling_publication_waits WHERE family=? AND address=? AND lo=? AND hi=?',
            (family,address,lo,hi)).fetchone()
        if prior_wait:deadline=min(deadline,prior_wait[0]);priority=min(priority,prior_wait[1])
        gaps=self.missing(family,scope,lo,hi)
        # A control/finality tip is not a normalized publication frontier. Even
        # with an authenticated creation, the recent tail may still be joining
        # logs and native order. Repair only a deficit behind durable published
        # coverage; wait for the open tail without turning it into an RPC gap.
        sources=self.scopes(family,scope);marks=','.join('?' for _ in sources)
        frontier=self.db.execute('SELECT MAX(hi) FROM candidate_coverage WHERE scope IN ('+marks+')',sources).fetchone()[0]
        jobs=[];waiting=[]
        for a,b in gaps:
            closed=None if frontier is None else min(b,frontier)
            if closed is not None and a<=closed:
                job=self.history.request(family,address,a,closed,priority=priority,deadline=deadline)
                why=reason or ('LATE_DISCOVERY' if not origin and lo==0 else 'PROVIDER_GAP')
                self.db.execute('INSERT OR IGNORE INTO backfill_reasons VALUES(?,?,?)',(job,why,canonical(dict(scope=scope,lo=a,hi=closed))))
                jobs.append(job)
            tail=a if closed is None else max(a,closed+1)
            if tail<=b:waiting.append((tail,b))
        if waiting:
            self.db.execute('''INSERT INTO rolling_publication_waits VALUES(?,?,?,?,?,?,?,'pending')
                ON CONFLICT(family,address,lo,hi) DO UPDATE SET
                deadline=MIN(deadline,excluded.deadline),priority=MIN(priority,excluded.priority)''',
                (family,address,lo,hi,deadline,priority,self.clock()))
            deadline=self.db.execute('SELECT deadline FROM rolling_publication_waits WHERE family=? AND address=? AND lo=? AND hi=?',
                (family,address,lo,hi)).fetchone()[0]
        metric=dict(model=MODEL_B,lower_slot=lo,upper_slot=hi,
            history_already_complete_at_promotion=not gaps,history_gap_slots_at_promotion=sum(b-a+1 for a,b in gaps),
            history_gap_seconds_at_promotion=None,missing_intervals=gaps,backfill_jobs=jobs,
            publication_pending_intervals=waiting,
            backfill_calls_at_promotion=0,backfill_bytes_at_promotion=0,transaction_bodies_at_promotion=0,
            decision_deadline=deadline,entry_authority=False)
        if waiting:metric['boundary_state']='UPPER_BOUND_PENDING_ROLLING_PUBLICATION'
        identity=digest([family,address,lo,hi,deadline])
        self.db.execute('INSERT OR IGNORE INTO promotion_history_metrics VALUES(?,?,?,?,?,?)',
            (identity,family,address,self.clock(),canonical(metric),digest(metric)))
        return metric

    def resume_boundaries(self):
        """A sealed native observation resolves a first-sight publication race."""
        for family,address,observed,upper,deadline,priority,created in self.db.execute(
                "SELECT family,address,observed_slot,upper_slot,deadline,priority,created FROM rolling_boundary_waits WHERE "+active_sql('family',solana=True)+" AND status='pending'").fetchall():
            if self.clock()>=deadline:
                self.db.execute("UPDATE rolling_boundary_waits SET status='deadline_missed' WHERE family=? AND address=?",(family,address))
                self.history._observation(None,'boundary_deadline_missed',dict(family=family,address=address,
                    observed_slot=observed,deadline=deadline,created=created,deadline_reset=False))
                continue
            binding=self.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
            origin=self.db.execute('SELECT 1 FROM rolling_origins WHERE family=? AND address=?',
                (family,address if binding is None else binding[0])).fetchone()
            start=self.db.execute('SELECT MIN(lo) FROM candidate_coverage WHERE scope=?',(program_scope(family),)).fetchone()[0]
            if not origin and (start is None or observed>=start) and self.missing(family,program_scope(family),observed,observed):continue
            result=self.prepare(family,address,0,upper,deadline=deadline,priority=priority,
                reason=None if origin else 'LATE_DISCOVERY')
            if result.get('boundary_state'):continue
            self.db.execute("UPDATE rolling_boundary_waits SET status='resolved' WHERE family=? AND address=?",(family,address))

    def resume_publication(self):
        """Release waits only on durable publication, preserving first deadline."""
        for family,address,lo,hi,deadline,priority in self.db.execute(
                "SELECT family,address,lo,hi,deadline,priority FROM rolling_publication_waits WHERE "+active_sql('family',solana=True)+" AND status='pending'").fetchall():
            if self.clock()>=deadline:
                status='deadline_missed'
                self.history._observation(None,'publication_deadline_missed',dict(
                    family=family,address=address,lo=lo,hi=hi,deadline=deadline,deadline_reset=False))
            else:
                result=self.prepare(family,address,lo,hi,deadline=deadline,priority=priority)
                if result['missing_intervals']:continue
                status='resolved'
            self.db.execute('UPDATE rolling_publication_waits SET status=? WHERE family=? AND address=? AND lo=? AND hi=?',
                (status,family,address,lo,hi))

    def repair_required_checkpoint_prefixes(self):
        """Only a proven prefix before installed rolling coverage needs RPC.

        A worker's authoritative snapshot may precede first-sight native
        membership by a few slots. Its durable requirement supplies the exact
        lower bound; an actually published interval proves the retained floor.
        The unpublished live tail waits for the publisher and is never fetched.
        """
        from contextlib import closing
        from .runtime.candidate_history import CandidateHistory
        with closing(CandidateHistory(self.history.lifecycle.path,clock=self.clock)) as shared:
            requirements=shared.db.execute('''SELECT r.scope,r.lo,r.hi,w.deadline
                FROM work_history_requirements r JOIN work w ON w.id=r.work_id
                WHERE w.status IN ('pending','active') AND w.deadline>?
                ORDER BY w.deadline''',(self.clock(),)).fetchall()
        jobs=[]
        for scope,lo,hi,deadline in requirements:
            family,address=scope.split(':',2)[1:]
            if family!='meteora':continue
            scopes=self.scopes(family,scope);marks=','.join('?' for _ in scopes)
            floor=self.db.execute('SELECT MIN(lo) FROM candidate_coverage WHERE scope IN ('+marks+')',scopes).fetchone()[0]
            if floor is not None and lo<floor:
                metric=self.prepare(family,address,lo,min(hi,floor-1),deadline=deadline,
                    priority=4,reason='CHECKPOINT_GAP')
                jobs.extend(metric['backfill_jobs'])
        return jobs

    def retention(self,family,address):
        """Maximum future need, not a new eligibility gate or ranking cap."""
        if family in ('pump','pumpswap'):
            binding=self.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
            market=address if not binding else binding[0]
            row=self.db.execute('SELECT fields FROM market_observations WHERE family=? AND address=?',(family,address)).fetchone()
            fields={} if not row else json.loads(row[0]);graduation=fields.get('graduation')
            if graduation is None:
                # Pre-graduation trajectory can still be required arbitrarily
                # late. It cannot be truncated to a guessed launch-age limit.
                migrations=self.db.execute("SELECT body FROM canonical_evidence r JOIN canonical_addresses a ON a.identity=r.identity WHERE a.address=? AND r.scope='program:pump' AND r.kind='event' AND r.body IS NOT NULL",(market,)).fetchall()
                for raw, in migrations:
                    e=decode_body(raw,self.db)['payload'].get('event',{})
                    if e.get('event_type')=='migration':graduation=e['market_time']
            if graduation is None:return dict(retain_until=None,reason='future_current_and_survivor_trajectory')
            from .lanes.pump.pumpswap_survivor import POLICY
            return dict(retain_until=graduation+POLICY['maximum_age_seconds'],reason='survivor_maximum_future_age')
        from .lanes.meteora import runner,dlmm
        window=runner.FRESH_SWAP_TRIGGER_MAX_SECONDS+runner.load_policy()['range']['warmup_seconds']+dlmm.MAX_AGE
        return dict(retain_until=self.clock(),window_seconds=window,reason='trigger_warmup_freshness_plus_existing_pins')
