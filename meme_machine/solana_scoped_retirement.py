"""Retire hot rich content only after durable consumers have advanced.

Candidate identity, compact scouting, normalized economic history, decisions,
funding outcomes, and immutable native order are never deleted here. Cold files
are lossless and hash verified; restoring one candidate does not replay a market.
All byte savings in this module are LOCAL storage savings, not provider credits.
"""
from contextlib import closing
from .runtime.operating_families import active_sql,solana_families
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import time
import zlib

from .runtime.candidate_history import CandidateHistory,retained_reference_path
from .solana_candidate_lifecycle import defer_busy_consumer
from .solana_evidence_plane import EvidenceUnavailable,EvidenceConflict,FinalizedRecord,canonical,digest,decode_body
from .solana_selective_history import FAMILIES,coverage_scope

SCHEMA='''
CREATE TABLE IF NOT EXISTS scoped_cold_records(
 identity TEXT PRIMARY KEY,scope TEXT NOT NULL,slot INTEGER NOT NULL,signature TEXT NOT NULL,
 program TEXT NOT NULL,market_time INTEGER,event_index INTEGER NOT NULL,transaction_index INTEGER,
 kind TEXT NOT NULL,body TEXT,hash TEXT NOT NULL,first_seen REAL NOT NULL,archive TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scoped_cold_manifests(
 id TEXT PRIMARY KEY,path TEXT NOT NULL,hash TEXT NOT NULL,records INTEGER NOT NULL,
 hot_bytes INTEGER NOT NULL,cold_bytes INTEGER NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS scoped_cold_addresses(
 identity TEXT NOT NULL,address TEXT NOT NULL,PRIMARY KEY(identity,address));
CREATE TABLE IF NOT EXISTS scoped_retirement_observations(
 id INTEGER PRIMARY KEY,at REAL NOT NULL,body TEXT NOT NULL);
'''


def cold_record(db,identity,archive,*,cache=None):
    """Resolve a local canonical cold pointer without provider reconstruction."""
    cache={} if cache is None else cache
    if archive not in cache:
        manifest=db.execute('SELECT path,hash FROM scoped_cold_manifests WHERE id=?',(archive,)).fetchone()
        if manifest is None:raise EvidenceUnavailable('scoped_cold_identity_missing')
        main=[row[2] for row in db.execute('PRAGMA database_list') if row[1]=='main']
        source=Path(main[0]) if len(main)==1 and main[0] else None
        candidate=None if source is None else source.with_name('solana-candidate-history.sqlite')
        packed=retained_reference_path(manifest[0],candidate_path=candidate,cold=True,
            canonical_path=source).read_bytes()
        if hashlib.sha256(packed).hexdigest()!=manifest[1]:raise EvidenceConflict('scoped_cold_hash_mismatch')
        decoder=zlib.decompressobj();raw=decoder.decompress(packed,32*1024*1024+1)
        if len(raw)>32*1024*1024 or not decoder.eof:raise EvidenceUnavailable('scoped_cold_restore_bound')
        cache[archive]={x['record']['identity']:x for x in json.loads(raw)}
    item=cache[archive].get(identity)
    if item is None:raise EvidenceUnavailable('scoped_cold_identity_missing')
    return item


class ScopedRetirement:
    def __init__(self,history):
        self.history=history;self.writer=history.writer;self.db=history.db
        self.lifecycle=history.lifecycle;self.clock=history.clock
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='scoped_cold_records'").fetchone():
            if self.db.in_transaction:raise EvidenceUnavailable('scoped_retirement_install_inside_commit')
            self.db.executescript(SCHEMA)
            if hasattr(self.history,'rolling'):self.history.rolling.install_views()
            else:
                # One canonical identity survives hot -> cold -> restored transitions.
                self.db.executescript('''DROP VIEW canonical_evidence;
                    CREATE VIEW canonical_evidence AS
                    SELECT * FROM records WHERE body IS NOT NULL OR NOT EXISTS(
                      SELECT 1 FROM shared_history_cache c WHERE c.identity=records.identity)
                      AND NOT EXISTS(SELECT 1 FROM scoped_cold_records c WHERE c.identity=records.identity)
                    UNION ALL SELECT * FROM shared_history_cache c WHERE NOT EXISTS(
                      SELECT 1 FROM records r WHERE r.identity=c.identity AND r.body IS NOT NULL)
                    UNION ALL SELECT * FROM scoped_cold_records c WHERE NOT EXISTS(
                      SELECT 1 FROM records r WHERE r.identity=c.identity AND r.body IS NOT NULL)
                      AND NOT EXISTS(SELECT 1 FROM shared_history_cache h WHERE h.identity=c.identity);
                    DROP VIEW canonical_addresses;
                    CREATE VIEW canonical_addresses AS SELECT identity,address FROM addresses
                      UNION SELECT identity,address FROM cached_addresses
                      UNION SELECT identity,address FROM scoped_cold_addresses;
                    ''')
        self.db.execute('CREATE INDEX IF NOT EXISTS scoped_cold_address_lookup ON scoped_cold_addresses(address,identity)')
        self.db.execute('''CREATE INDEX IF NOT EXISTS candidate_canonical_consumed_identity
            ON candidate_history_outbox(json_extract(body,'$.record.identity'))
            WHERE kind='canonical' AND consumed IS NOT NULL''')
        # SQLite maintains exact stored-byte lengths on insert/update/delete.
        # Retirement telemetry must not reread every rich body twice per slice.
        # These are covering indexes in the existing database, not counters or
        # cached evidence; canonical identity precedence below is unchanged.
        tables=['records','shared_history_cache','scoped_cold_records']
        if hasattr(self.history,'rolling'):tables.append('rolling_economic_events')
        for table in tables:
            self.db.execute('CREATE INDEX IF NOT EXISTS '+table+'_hot_lengths ON '+table+
                '(length(CAST(body AS BLOB)),identity) WHERE body IS NOT NULL')

    def pinned(self,family,address,lo,hi,shared):
        scope=self.history.scope_for(family,address);base=FAMILIES[family]
        binding=self.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
        market=address if binding is None else binding[0]
        aliases=[a for a, in self.db.execute('SELECT address FROM evidence_bindings WHERE coverage_scope=?',(scope,))]+[market,address]
        placeholders=','.join('?' for _ in aliases)
        active=self.db.execute(f'''SELECT i.lifecycle,i.lower_slot,i.owner FROM interests i JOIN service_interests s
            ON s.owner=i.owner AND s.scope=i.scope WHERE i.active=1 AND i.scope=? AND s.address IN ({placeholders})''',
            [base,*aliases]).fetchall()
        if any(role in ('open','reserved') or lower<=hi for role,lower,owner in active):return 'active_consumer'
        if self.db.execute('''SELECT 1 FROM interests i WHERE i.active=1 AND i.scope=? AND i.lower_slot<=?
            AND NOT EXISTS(SELECT 1 FROM service_interests s WHERE s.owner=i.owner AND s.scope=i.scope) LIMIT 1''',
            (base,hi)).fetchone():return 'global_consumer'
        if self.db.execute('SELECT 1 FROM candidate_evidence_pins WHERE scope=? AND lower_slot<=? LIMIT 1',(scope,hi)).fetchone():return 'explicit_pin'
        states=self.db.execute(f'SELECT state,deadline FROM candidate_lifecycle WHERE family=? AND address IN ({placeholders})',(family,*aliases)).fetchall()
        if any(s in ('queued','warming') or d is not None and d>self.clock() for s,d in states):return 'warming_or_deadline'
        if self.db.execute(f"SELECT 1 FROM acquisition_jobs WHERE family=? AND address IN ({placeholders}) AND status='pending' LIMIT 1",(family,*aliases)).fetchone():return 'pending_replay'
        if self.db.execute('SELECT 1 FROM candidate_pending_proofs WHERE scope=? LIMIT 1',(scope,)).fetchone():return 'pending_proof'
        if self.db.execute('SELECT 1 FROM candidate_gaps WHERE scope=? AND repaired IS NULL AND lo<=? AND (hi IS NULL OR hi>=?) LIMIT 1',(scope,hi,lo)).fetchone():return 'continuity_gap'
        if self.db.execute('SELECT 1 FROM gaps WHERE scope=? AND repaired IS NULL AND lo<=? AND (hi IS NULL OR hi>=?) LIMIT 1',(base,hi,lo)).fetchone():return 'continuity_gap'
        if self.db.execute(f'SELECT 1 FROM candidate_history_outbox WHERE family=? AND address IN ({placeholders}) AND consumed IS NULL LIMIT 1',(family,*aliases)).fetchone():return 'pending_consumer'
        lane='pump' if family in ('pump','pumpswap') else 'meteora'
        if shared.db.execute("SELECT 1 FROM work WHERE lane=? AND candidate=? AND status IN ('active','pending') LIMIT 1",(lane,market)).fetchone():return 'candidate_work'
        if family=='meteora' and hasattr(self.history,'rolling'):
            retention=self.history.rolling.retention(family,address)
            rows=self.db.execute('SELECT MAX(r.market_time) FROM canonical_evidence r JOIN canonical_addresses a ON a.identity=r.identity WHERE r.scope=? AND a.address=? AND r.slot BETWEEN ? AND ?',(base,market,lo,hi)).fetchone()
            # Pump economics remain recoverable through canonical cold pointers
            # and CandidateHistory references. Future eligibility does not pin
            # raw log/hydration bytes in hot storage forever.
            if rows and rows[0] is not None and rows[0]>=self.clock()-retention['window_seconds']:return 'rolling_trigger_and_warmup_history'
        return None

    def _oldest_hot_identities(self,family,address,limit):
        """Bound Python expansion while retaining exact canonical precedence.

        Each storage branch uses its identity index after the shared address
        lookup. Forcing that index avoids SQLite's whole-program ORDER BY path.
        The canonical view still decides visibility, including cold shadows.
        A global top N must occur in a branch's top N; deduplicate before the
        final bound. Long metadata scans remain interruptible owner SQL work.
        """
        tables=['records','shared_history_cache','scoped_cold_records']
        if hasattr(self.history,'rolling'):tables.append('rolling_economic_events')
        parts=[];args=[address]
        for table in tables:
            parts.append('SELECT identity,slot FROM (SELECT r.identity,r.slot FROM ids a CROSS JOIN '+
                table+' r INDEXED BY sqlite_autoindex_'+table+'_1 WHERE r.identity=a.identity '
                'AND r.scope=? AND r.body IS NOT NULL AND EXISTS (SELECT 1 FROM canonical_evidence c '
                'WHERE c.identity=r.identity AND c.scope=r.scope AND c.slot=r.slot AND c.body IS NOT NULL) '
                'ORDER BY r.slot,r.identity LIMIT ?)')
            args.extend((FAMILIES[family],limit))
        query=('WITH ids AS MATERIALIZED (SELECT identity FROM canonical_addresses WHERE address=?) '
            'SELECT DISTINCT identity,slot FROM ('+' UNION ALL '.join(parts)+') ORDER BY slot,identity LIMIT ?')
        return [r[0] for r in self.db.execute(query,(*args,limit))]

    def shared_owners(self,scope,identity):
        # Start with this identity's complete address set. The unconstrained
        # join can instead scan every binding of a program for each hot row.
        # Both existing binding-index keys must participate in the seek; no
        # address or owner is truncated before the original fanout fence.
        return self.db.execute('''WITH addresses AS MATERIALIZED (
                SELECT address FROM canonical_addresses WHERE identity=?)
            SELECT DISTINCT b.family,b.coverage_scope FROM addresses a
            CROSS JOIN evidence_bindings b INDEXED BY evidence_binding_canonical_market
            WHERE b.market_address=a.address AND b.canonical_scope=?
            ORDER BY b.coverage_scope LIMIT 65''',(identity,scope)).fetchall()

    def _plan_hot_page(self,limit,measure_hot_bytes):
        """Bound archival planning inputs, independently of candidate age/population.

        Archival order is housekeeping, not canonical event order. Page through
        the existing hot-length indexes instead of reconstructing every retained
        event for 64 candidates. Every hot representation rotates durably; only
        archive.apply advances these cursors, with the pointer transaction.
        """
        from .solana_history_delivery import generation,readonly_history
        started=time.monotonic();selected={};pinned={};oldest=None;size=0
        before=self.hot_bytes() if measure_hot_bytes else None
        tables=['records','shared_history_cache','scoped_cold_records']
        if hasattr(self.history,'rolling'):tables.append('rolling_economic_events')
        cursors={};previous={};examined=0;scopes=set();seen=set();full=False
        pin_checks={};pin_reuses=0
        enabled_scopes={FAMILIES[f] for f in solana_families()}
        table_key='scoped_retirement_hot_table'
        table_before=self.db.execute('SELECT value FROM meta WHERE key=?',(table_key,)).fetchone()
        first=0 if table_before is None else int(table_before[0])%len(tables)
        tables=tables[first:]+tables[:first];last=None
        budget=min(limit,64)
        with closing(readonly_history(self.lifecycle.path)) as shared:
            for table in tables:
                last=table
                key='scoped_retirement_hot_cursor:'+table
                stored=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
                previous[key]=None if stored is None else stored[0]
                saved=None if stored is None else json.loads(stored[0])
                after=(-1,'') if saved is None else tuple(saved['after'])
                through=None if saved is None else tuple(saved['through'])
                def ceiling():
                    return self.db.execute('SELECT length(CAST(body AS BLOB)),identity FROM '+table+
                        ' INDEXED BY '+table+'_hot_lengths WHERE body IS NOT NULL '
                        'ORDER BY length(CAST(body AS BLOB)) DESC,identity DESC LIMIT 1').fetchone()
                def read_page(lower,upper):
                    if upper is None:return []
                    # Separate exact index ranges avoid rescanning an enormous
                    # equal-length prefix (row-value expression comparisons do
                    # not reliably seek both index terms on all SQLite builds).
                    prefix=('SELECT identity,scope,slot,length(CAST(body AS BLOB)) FROM '+table+
                        ' INDEXED BY '+table+'_hot_lengths WHERE body IS NOT NULL AND ')
                    cap=budget-examined;result=[]
                    condition='length(CAST(body AS BLOB))=? AND identity>?'
                    args=[*lower]
                    if lower[0]==upper[0]:condition+=' AND identity<=?';args.append(upper[1])
                    result.extend(self.db.execute(prefix+condition+' ORDER BY identity LIMIT ?',(*args,cap)))
                    if lower[0]<upper[0] and len(result)<cap:
                        result.extend(self.db.execute(prefix+'length(CAST(body AS BLOB))>? AND '
                            'length(CAST(body AS BLOB))<? ORDER BY length(CAST(body AS BLOB)),identity LIMIT ?',
                            (lower[0],upper[0],cap-len(result))))
                    if lower[0]<upper[0] and len(result)<cap:
                        result.extend(self.db.execute(prefix+'length(CAST(body AS BLOB))=? AND identity<=? '
                            'ORDER BY identity LIMIT ?',(upper[0],upper[1],cap-len(result))))
                    return result
                if through is None:through=ceiling()
                rows=read_page(after,through)
                if not rows and saved is not None:
                    # A fixed cycle ceiling guarantees wrap even while new
                    # work continually extends the tail beyond this cycle.
                    after=(-1,'');through=ceiling();rows=read_page(after,through)
                for identity,scope,slot,stored_bytes in rows:
                    examined+=1;cursors[key]=dict(after=[stored_bytes,identity],through=list(through))
                    if identity in seen:continue
                    seen.add(identity)
                    # Exact canonical precedence still determines visibility;
                    # an older hot representation cannot defeat a cold shadow.
                    canonical_row=self.db.execute('''SELECT scope,slot,body IS NOT NULL,length(CAST(body AS BLOB))
                        FROM canonical_evidence WHERE identity=?''',(identity,)).fetchone()
                    if canonical_row is None or not canonical_row[2]:continue
                    scope,slot=canonical_row[:2]
                    if scope not in enabled_scopes:continue
                    owners=self.shared_owners(scope,identity)
                    if not owners:continue # never guess an unbound consumer released evidence
                    reason='shared_binding_bound' if len(owners)>64 else None
                    owner_scope=owners[0][1]
                    for family,owner_scope in owners if reason is None else ():
                        scopes.add(owner_scope)
                        pin_key=(family,owner_scope,slot)
                        if pin_key not in pin_checks:
                            pin_checks[pin_key]=self.pinned(family,owner_scope.split(':',2)[2],slot,slot,shared)
                        else:pin_reuses+=1
                        # Several economic identities in one block can belong
                        # to the exact same consumer/window. This plan performs
                        # no owner writes. Reuse only that identical pin query;
                        # archive.apply rechecks every current pin independently
                        # before changing a hot pointer. No result survives here.
                        reason=pin_checks[pin_key]
                        if reason:break
                    if reason is None and not self.db.execute('''SELECT 1 FROM candidate_history_outbox
                        WHERE kind='canonical' AND consumed IS NOT NULL
                        AND json_extract(body,'$.record.identity')=? LIMIT 1''',(identity,)).fetchone():
                        reason='batch_bound_or_unacknowledged_consumer'
                    if reason:
                        # Hot-index lengths are accounting of this examined
                        # representation, not bytes of reconstructed history.
                        pinned[identity]=stored_bytes
                        if oldest is None or slot<oldest['slot']:
                            oldest=dict(scope=owner_scope,slot=slot,reason=reason)
                        continue
                    if canonical_row[3]>16*1024*1024-size:continue
                    row=self.db.execute('SELECT * FROM canonical_evidence WHERE identity=?',(identity,)).fetchone()
                    length=len(row[9].encode() if isinstance(row[9],str) else row[9])
                    if size+length>16*1024*1024:
                        # Keep the row hot; the original format cannot prepare
                        # an oversized archive. Rotation must still progress.
                        continue
                    selected[identity]=row;size+=length
                    if len(selected)>=limit:
                        full=True;break
                if full or examined>=budget:break
        return dict(selected=selected,pinned=pinned,oldest=oldest,before=before,
            bindings=[],started=started,canonical_path=str(self.writer.path.resolve()),
            generation=generation(self.lifecycle),limit=limit,hot_cursors=cursors,
            hot_cursor_before=previous,hot_table_before=None if table_before is None else table_before[0],
            hot_table_next=(first+tables.index(last)+1)%len(tables),
            selection=dict(mode='indexed_hot_pages',metadata_rows=examined,
                metadata_row_bound=budget,candidate_scopes=len(scopes),
                preparation_bytes=size,pin_checks=len(pin_checks),pin_check_reuses=pin_reuses,
                oldest_domain='examined hot page only'))

    @defer_busy_consumer
    def retire(self,*,limit=64,measure_hot_bytes=True,plan_only=False):
        if self.db.in_transaction:raise EvidenceUnavailable('retention_inside_source_transaction')
        if not 1<=limit<=1000:raise EvidenceUnavailable('retention_batch_bound')
        if plan_only:return self._plan_hot_page(limit,measure_hot_bytes)
        started=time.monotonic();selected={};pinned={};oldest=None
        # Whole-reservoir totals are optional diagnostics, never retirement
        # permission. Live source maintenance must not scan the growing
        # reservoir twice while authenticated native frames wait for this owner.
        before=self.hot_bytes() if measure_hot_bytes else None
        # The record limit must bound the candidate traversal too. A full
        # population sweep on each one-second turn stalls canonical commits.
        # Rotate durably; this is a maintenance slice, never an admission cap.
        cursor=self.db.execute("SELECT value FROM meta WHERE key='scoped_retirement_cursor'").fetchone()
        cursor='' if cursor is None else cursor[0]
        query='''SELECT DISTINCT family,coverage_scope FROM evidence_bindings WHERE '''+active_sql('family',solana=True)+''' AND coverage_scope>? ORDER BY coverage_scope LIMIT ?'''
        bindings=self.db.execute(query,(cursor,min(limit,64))).fetchall()
        if not bindings and cursor:bindings=self.db.execute(query,('',min(limit,64))).fetchall()
        opener=CandidateHistory(self.lifecycle.path,clock=self.clock,write_wait_seconds=0)
        with closing(opener) as shared:
            for family,scope in bindings:
                address=scope[len('candidate:'+family+':'):]
                binding=self.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
                market=binding[0]
                # Resolve the indexed address set before expanding the canonical
                # union. Scanning an entire program for every candidate blocks
                # urgent owner work even though each result is bounded to 64.
                selected_ids=self._oldest_hot_identities(family,market,limit)
                rows=[self.db.execute('SELECT * FROM canonical_evidence WHERE identity=?',(identity,)).fetchone()
                    for identity in selected_ids]
                if not rows:continue
                reason=self.pinned(family,address,rows[0][2],rows[-1][2],shared)
                if reason:
                    for r in rows:pinned[r[0]]=len(r[9].encode() if isinstance(r[9],str) else r[9])
                    if oldest is None or rows[0][2]<oldest['slot']:oldest=dict(scope=coverage_scope(family,address),slot=rows[0][2],reason=reason)
                    continue
                for row in rows:
                    receipt=self.db.execute('''SELECT 1 FROM candidate_history_outbox WHERE kind='canonical' AND consumed IS NOT NULL
                        AND json_extract(body,'$.record.identity')=? LIMIT 1''',(row[0],)).fetchone()
                    # Legacy evidence lacking a durable consumer receipt cannot
                    # be guessed safe under storage pressure.
                    if receipt and len(selected)<limit:selected[row[0]]=row
            # A row can belong to a pinned consumer outside this fair slice.
            # Check its complete indexed binding set before changing any hot
            # pointer. Large fanout remains hot rather than exceeding this work
            # bound or guessing that unseen owners have released the record.
            for identity,row in tuple(selected.items()):
                owners=self.shared_owners(row[1],identity)
                reason='shared_binding_bound' if len(owners)>64 else None
                if reason:scope=owners[0][1]
                for family,scope in owners if reason is None else ():
                    address=scope[len('candidate:'+family+':'):]
                    reason=self.pinned(family,address,row[2],row[2],shared)
                    if reason:break
                if reason:
                    pinned[identity]=len(row[9].encode() if isinstance(row[9],str) else row[9])
                    if oldest is None or row[2]<oldest['slot']:oldest=dict(scope=scope,slot=row[2],reason=reason)
        # A canonical row shared with a pinned candidate remains pinned even if
        # a different candidate has no current consumer.
        for identity in pinned:selected.pop(identity,None)
        content=[];hot_bytes=0;bounded={}
        for row in selected.values():
            body=decode_body(row[9],self.db)
            if digest(body)!=row[10]:raise EvidenceConflict('local_evidence_hash_mismatch')
            size=len(canonical(body).encode())
            # A bounded row count alone cannot bound large rich transactions.
            # Every written archive must fit the verified restoration bound.
            if hot_bytes+size>16*1024*1024:continue
            bounded[row[0]]=row
            content.append(dict(record=body,available=row[11]));hot_bytes+=size
        selected=bounded
        if content:
            raw=canonical(content).encode();packed=zlib.compress(raw,6);identity=hashlib.sha256(packed).hexdigest()
            directory=self.writer.path.with_suffix('.scoped-cold');directory.mkdir(exist_ok=True)
            path=directory/(identity+'.zlib');temporary=directory/(identity+'.tmp')
            with temporary.open('wb') as handle:
                handle.write(packed);handle.flush();os.fsync(handle.fileno())
            os.replace(temporary,path)
            fd=os.open(directory,os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
            # Content is fsynced before the hot pointer changes. A crash can
            # leave an unused file; it cannot leave a dangling durable pointer.
            with self.writer.transaction():
                self.db.execute('INSERT OR IGNORE INTO scoped_cold_manifests VALUES(?,?,?,?,?,?,?)',
                    (identity,str(path),identity,len(content),hot_bytes,len(packed),self.clock()))
                for row in selected.values():
                    values=list(row);values[9]=None;values[12]=identity
                    self.db.execute('INSERT OR REPLACE INTO scoped_cold_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',values)
                    body=decode_body(row[9],self.db)
                    for address in body['addresses']:
                        self.db.execute('INSERT OR IGNORE INTO scoped_cold_addresses VALUES(?,?)',(row[0],address))
                    self.db.execute('UPDATE records SET body=NULL WHERE identity=?',(row[0],))
                    if hasattr(self.history,'rolling'):
                        self.db.execute('UPDATE rolling_economic_events SET body=NULL,archive=? WHERE identity=?',(identity,row[0]))
                    # Address/index/history metadata remains durable. Cache-only
                    # records keep their address table even after the body leaves.
                    self.db.execute('DELETE FROM shared_history_cache WHERE identity=?',(row[0],))
        after=self.hot_bytes() if measure_hot_bytes else None
        if oldest is None and (after is None or after):
            # A many-to-many join sorts one row per candidate/event binding.
            # Existence is enough to locate the same oldest retained identity;
            # resolve its scope only after the ordered LIMIT, without exploding
            # the rolling reservoir by the number of consumers.
            row=self.oldest_hot_bound_record()
            if row:
                scope=self.db.execute('''SELECT MIN(b.coverage_scope) FROM canonical_addresses a
                    JOIN evidence_bindings b ON b.market_address=a.address AND b.canonical_scope=?
                    WHERE a.identity=?''',(row[1],row[0])).fetchone()[0]
                oldest=dict(scope=scope,slot=row[2],reason='batch_bound_or_unacknowledged_consumer')
        elapsed=time.monotonic()-started
        result=dict(hot_bytes_before=before,hot_bytes_after=after,retired_records=len(content),
            hot_bytes_measurement='exact' if measure_hot_bytes else 'deferred',
            retired_logical_bytes=hot_bytes,pinned_bytes=sum(pinned.values()),oldest_unretired_scope=oldest,
            retirement_seconds=elapsed,records_per_second=len(content)/max(elapsed,1e-9),
            physical_database_bytes=sum(p.stat().st_size for p in (
                self.writer.path,Path(str(self.writer.path)+'-wal')) if p.exists()),
            retained_candidate_history_bytes=Path(self.lifecycle.path).stat().st_size,
            cold_bytes=sum(r[0] for r in self.db.execute('SELECT cold_bytes FROM scoped_cold_manifests')),
            candidate_scopes_examined=len(bindings),candidate_scan_bound=min(limit,64),
            pinned_bytes_domain='examined slice and selected-row shared owners',
            oldest_unretired_scope_domain='examined slice; global fallback when no local witness')
        with self.writer.transaction():
            if bindings:self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('scoped_retirement_cursor',bindings[-1][1]))
            self.db.execute('INSERT INTO scoped_retirement_observations(at,body) VALUES(?,?)',(self.clock(),canonical(result)))
        return result

    def oldest_hot_bound_record(self):
        # A correlated canonical_addresses UNION materializes the entire address
        # population before testing one identity. Seek each representation and
        # scope instead, then take the same global minimum. Both canonical row
        # precedence and the full binding/address set are retained; this is only
        # a diagnostic witness, never permission to retire or seal coverage.
        rolling=hasattr(self.history,'rolling')
        addresses=['addresses','cached_addresses','scoped_cold_addresses']
        representations=[]
        if rolling:
            addresses.insert(0,'rolling_economic_addresses')
            representations.append(('rolling_economic_events','e',[]))
        for table,alias,guards in (
                ('records','r',[]),
                ('shared_history_cache','h',['NOT EXISTS(SELECT 1 FROM records r WHERE r.identity=h.identity AND r.body IS NOT NULL)']),
                ('scoped_cold_records','c',['NOT EXISTS(SELECT 1 FROM records r WHERE r.identity=c.identity AND r.body IS NOT NULL)',
                    'NOT EXISTS(SELECT 1 FROM shared_history_cache h WHERE h.identity=c.identity)'])):
            if rolling:guards=[*guards,'NOT EXISTS(SELECT 1 FROM rolling_economic_events e WHERE e.identity='+alias+'.identity)']
            representations.append((table,alias,guards))
        scopes=[r[0] for r in self.db.execute('SELECT DISTINCT canonical_scope FROM evidence_bindings')]
        oldest=None
        for table,alias,guards in representations:
            bound=' OR '.join('EXISTS(SELECT 1 FROM '+address+' a JOIN evidence_bindings b '
                'ON b.market_address=a.address AND b.canonical_scope='+alias+'.scope '
                'WHERE a.identity='+alias+'.identity)' for address in addresses)
            query=('SELECT '+alias+'.identity,'+alias+'.scope,'+alias+'.slot FROM '+table+' '+alias+
                ' WHERE '+alias+'.scope=? AND '+alias+'.body IS NOT NULL'+''.join(' AND '+g for g in guards)+
                ' AND ('+bound+') ORDER BY '+alias+'.slot,'+alias+'.identity LIMIT 1')
            for scope in scopes:
                row=self.db.execute(query,(scope,)).fetchone()
                if row is not None and (oldest is None or (row[2],row[0])<(oldest[2],oldest[0])):oldest=row
        return oldest

    def hot_bytes(self):
        # Same UNION identity precedence as canonical_evidence. Filtering hot
        # bodies first allows the small length indexes to cover the sum. A cold
        # rolling identity still shadows another representation of that fact.
        rolling=hasattr(self.history,'rolling')
        queries=[]
        if rolling:
            queries.append('SELECT length(CAST(body AS BLOB)) AS bytes FROM rolling_economic_events '
                'INDEXED BY rolling_economic_events_hot_lengths WHERE body IS NOT NULL')
        for table,alias,guards in (
                ('records','r',[]),
                ('shared_history_cache','h',['NOT EXISTS(SELECT 1 FROM records r WHERE r.identity=h.identity AND r.body IS NOT NULL)']),
                ('scoped_cold_records','c',['NOT EXISTS(SELECT 1 FROM records r WHERE r.identity=c.identity AND r.body IS NOT NULL)',
                    'NOT EXISTS(SELECT 1 FROM shared_history_cache h WHERE h.identity=c.identity)'])):
            if rolling:guards=[*guards,'NOT EXISTS(SELECT 1 FROM rolling_economic_events e WHERE e.identity='+alias+'.identity)']
            queries.append('SELECT length(CAST(body AS BLOB)) AS bytes FROM '+table+' '+alias+
                ' INDEXED BY '+table+'_hot_lengths WHERE body IS NOT NULL'+(' AND '+' AND '.join(guards) if guards else ''))
        return self.db.execute('SELECT COALESCE(SUM(bytes),0) FROM ('+' UNION ALL '.join(queries)+')').fetchone()[0]

    def contents(self,archive):
        path,checksum=self.db.execute('SELECT path,hash FROM scoped_cold_manifests WHERE id=?',(archive,)).fetchone()
        packed=Path(path).read_bytes()
        if hashlib.sha256(packed).hexdigest()!=checksum:raise EvidenceConflict('scoped_cold_hash_mismatch')
        decoder=zlib.decompressobj();raw=decoder.decompress(packed,32*1024*1024+1)
        if len(raw)>32*1024*1024 or not decoder.eof:raise EvidenceUnavailable('scoped_cold_restore_bound')
        return json.loads(raw)

    def body(self,identity):
        row=self.db.execute('SELECT archive,hash,first_seen FROM scoped_cold_records WHERE identity=?',(identity,)).fetchone()
        if not row:raise EvidenceUnavailable('scoped_cold_identity_missing')
        for item in self.contents(row[0]):
            if item['record']['identity']==identity:
                if (digest(item['record']),item['available'])!=tuple(row[1:]):raise EvidenceConflict('local_evidence_hash_mismatch')
                return item['record']
        raise EvidenceUnavailable('scoped_cold_identity_missing')

    def restore(self,family,address):
        from .runtime.operating_families import require_active
        require_active(family)
        binding=self.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
        market=address if binding is None else binding[0]
        rows=self.db.execute('''SELECT DISTINCT c.archive FROM scoped_cold_records c JOIN canonical_addresses a ON a.identity=c.identity
            WHERE c.scope=? AND a.address=?''',(FAMILIES[family],market)).fetchall()
        restored=0
        for archive, in rows:
            for item in self.contents(archive):
                body=item['record'];identity=body['identity']
                if market not in body['addresses'] or body['scope']!=FAMILIES[family]:continue
                stored=self.db.execute('SELECT hash,first_seen FROM scoped_cold_records WHERE identity=?',(identity,)).fetchone()
                if not stored:continue
                if (digest(body),item['available'])!=stored:raise EvidenceConflict('local_evidence_hash_mismatch')
                with self.writer.transaction():
                    normalized=hasattr(self.history,'rolling') and self.db.execute(
                        'SELECT 1 FROM rolling_economic_events WHERE identity=?',(identity,)).fetchone()
                    if normalized:
                        self.db.execute('UPDATE rolling_economic_events SET body=?,archive=NULL WHERE identity=?',(canonical(body),identity))
                    else:
                        self.db.execute('''INSERT OR IGNORE INTO shared_history_cache VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)''',
                            (identity,body['scope'],body['slot'],body['signature'],body['program'],body['market_time'],
                             body['event_index'],body['transaction_index'],body['kind'],canonical(body),stored[0],stored[1]))
                        for a in body['addresses']:self.db.execute('INSERT OR IGNORE INTO cached_addresses VALUES(?,?)',(identity,a))
                    self.db.execute('DELETE FROM scoped_cold_records WHERE identity=?',(identity,))
                    self.db.execute('DELETE FROM scoped_cold_addresses WHERE identity=?',(identity,))
                restored+=1
        return restored
