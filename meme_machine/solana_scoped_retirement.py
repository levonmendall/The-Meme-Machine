"""Retire hot rich content only after durable consumers have advanced.

Candidate identity, compact scouting, normalized economic history, decisions,
funding outcomes, and immutable native order are never deleted here. Cold files
are lossless and hash verified; restoring one candidate does not replay a market.
All byte savings in this module are LOCAL storage savings, not provider credits.
"""
from contextlib import closing
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import time
import zlib

from .runtime.candidate_history import CandidateHistory
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
        packed=Path(manifest[0]).read_bytes()
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
        if hasattr(self.history,'rolling'):
            retention=self.history.rolling.retention(family,address)
            rows=self.db.execute('SELECT MAX(r.market_time) FROM canonical_evidence r JOIN canonical_addresses a ON a.identity=r.identity WHERE r.scope=? AND a.address=? AND r.slot BETWEEN ? AND ?',(base,market,lo,hi)).fetchone()
            # Pump economics remain recoverable through canonical cold pointers
            # and CandidateHistory references. Future eligibility does not pin
            # raw log/hydration bytes in hot storage forever.
            if family=='meteora' and rows and rows[0] is not None and rows[0]>=self.clock()-retention['window_seconds']:return 'rolling_trigger_and_warmup_history'
        return None

    def retire(self,*,limit=64):
        if self.db.in_transaction:raise EvidenceUnavailable('retention_inside_source_transaction')
        if not 1<=limit<=1000:raise EvidenceUnavailable('retention_batch_bound')
        started=time.monotonic();selected={};pinned={};oldest=None
        before=self.hot_bytes()
        with closing(CandidateHistory(self.lifecycle.path,clock=self.clock)) as shared:
            for family,address in self.db.execute('''SELECT DISTINCT family,
                    substr(coverage_scope,length('candidate:'||family||':')+1) FROM evidence_bindings''').fetchall():
                binding=self.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
                market=binding[0]
                # Resolve the indexed address set before expanding the canonical
                # union. Scanning an entire program for every candidate blocks
                # urgent owner work even though each result is bounded to 64.
                identities=[r[0] for r in self.db.execute(
                    'SELECT identity FROM canonical_addresses WHERE address=?',(market,))]
                if not identities:continue
                # SQLite distributes ORDER BY through the canonical UNION ALL
                # and otherwise chooses a whole-program scope scan per quiet
                # view. Resolve compact metadata by primary identity first;
                # only the bounded selected rows expand their economic bodies.
                metadata=[]
                for start in range(0,len(identities),256):
                    chunk=identities[start:start+256]
                    metadata.extend(r for r in self.db.execute(
                        'SELECT identity,scope,slot,body IS NOT NULL FROM canonical_evidence WHERE identity IN ('+
                        ','.join('?' for _ in chunk)+')',chunk)
                        if r[1]==FAMILIES[family] and r[3])
                selected_ids=[r[0] for r in sorted(metadata,key=lambda r:(r[2],r[0]))[:limit]]
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
        elapsed=time.monotonic()-started;after=self.hot_bytes()
        if oldest is None and after:
            row=self.db.execute('''SELECT b.coverage_scope,r.slot FROM canonical_evidence r
                JOIN canonical_addresses a ON a.identity=r.identity
                JOIN evidence_bindings b ON b.market_address=a.address AND b.canonical_scope=r.scope
                WHERE r.body IS NOT NULL ORDER BY r.slot,r.identity LIMIT 1''').fetchone()
            if row:oldest=dict(scope=row[0],slot=row[1],reason='batch_bound_or_unacknowledged_consumer')
        result=dict(hot_bytes_before=before,hot_bytes_after=after,retired_records=len(content),
            retired_logical_bytes=hot_bytes,pinned_bytes=sum(pinned.values()),oldest_unretired_scope=oldest,
            retirement_seconds=elapsed,records_per_second=len(content)/max(elapsed,1e-9),
            physical_database_bytes=sum(p.stat().st_size for p in (
                self.writer.path,Path(str(self.writer.path)+'-wal')) if p.exists()),
            retained_candidate_history_bytes=Path(self.lifecycle.path).stat().st_size,
            cold_bytes=sum(r[0] for r in self.db.execute('SELECT cold_bytes FROM scoped_cold_manifests')))
        with self.writer.transaction():self.db.execute('INSERT INTO scoped_retirement_observations(at,body) VALUES(?,?)',(self.clock(),canonical(result)))
        return result

    def hot_bytes(self):
        return self.db.execute('SELECT COALESCE(SUM(length(CAST(body AS BLOB))),0) FROM canonical_evidence WHERE body IS NOT NULL').fetchone()[0]

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
