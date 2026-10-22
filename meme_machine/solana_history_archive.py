"""Existing scoped archive format, prepared off-owner and revalidated on-owner."""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import time
import zlib
from .solana_evidence_plane import EvidenceUnavailable,EvidenceConflict,canonical,digest,decode_body
from .solana_history_delivery import generation,readonly_history
from .solana_scoped_retirement import ScopedRetirement


def prepare(plan):
    from .solana_history_work import CPUBudget
    started=time.monotonic();cpu=time.process_time();budget=CPUBudget(.25)
    selected={};items=[];addresses={};hot_bytes=0;body_hashes={}
    # No explicit read transaction: chunk references are immutable and checked
    # by decode_body. Each indexed lookup finishes before Python calculation.
    with closing(sqlite3.connect(Path(plan['canonical_path']).as_uri()+'?mode=ro',uri=True,timeout=.1,isolation_level=None)) as db:
        db.execute('PRAGMA query_only=ON')
        for identity,row in plan['selected'].items():
            body=decode_body(row[9],db);raw=canonical(body);checksum=hashlib.sha256(raw.encode()).hexdigest()
            if checksum!=row[10]:raise EvidenceConflict('local_evidence_hash_mismatch')
            size=len(raw.encode())
            if hot_bytes+size>16*1024*1024:continue
            selected[identity]=row;addresses[identity]=body['addresses'];body_hashes[identity]=checksum
            items.append('{"available":'+canonical(row[11])+',"record":'+raw+'}');hot_bytes+=size;budget()
    receipt=None
    if items:
        packed=zlib.compress(('['+','.join(items)+']').encode(),6);identity=hashlib.sha256(packed).hexdigest()
        directory=Path(plan['canonical_path']).with_suffix('.scoped-cold');directory.mkdir(exist_ok=True)
        path=directory/(identity+'.zlib');temporary=directory/(identity+'.tmp')
        with temporary.open('wb') as handle:handle.write(packed);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path);fd=os.open(directory,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        receipt=dict(identity=identity,path=str(path),bytes=len(packed),hot_bytes=hot_bytes)
    budget()
    return dict(selected=selected,addresses=addresses,body_hashes=body_hashes,receipt=receipt,
        worker=dict(cpu_seconds=time.process_time()-cpu,wall_seconds=time.monotonic()-started))


def apply(history,plan,result):
    """Hot pointers remain unchanged unless every current original pin passes."""
    retirement=ScopedRetirement(history);db=history.db
    if digest(generation(history.lifecycle))!=digest(plan['generation']):return False
    for key,expected in plan.get('hot_cursor_before',{}).items():
        actual=db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        if (None if actual is None else actual[0])!=expected:return False
    if 'hot_table_next' in plan:
        actual=db.execute("SELECT value FROM meta WHERE key='scoped_retirement_hot_table'").fetchone()
        if (None if actual is None else actual[0])!=plan['hot_table_before']:return False
    with closing(readonly_history(history.lifecycle.path)) as shared:
        for identity,row in result['selected'].items():
            from .solana_derived_fanout import record_pending
            if record_pending(db,identity):return False
            if plan['selected'].get(identity)!=row or db.execute('SELECT * FROM canonical_evidence WHERE identity=?',(identity,)).fetchone()!=row:return False
            if result['body_hashes'].get(identity)!=row[10]:raise EvidenceConflict('local_evidence_hash_mismatch')
            if not db.execute("SELECT 1 FROM candidate_history_outbox WHERE kind='canonical' AND consumed IS NOT NULL AND json_extract(body,'$.record.identity')=? LIMIT 1",(identity,)).fetchone():return False
            owners=retirement.shared_owners(row[1],identity)
            if not owners or len(owners)>64:return False
            for family,scope in owners:
                if retirement.pinned(family,scope.split(':',2)[2],row[2],row[2],shared):return False
            actual={r[0] for r in db.execute('SELECT address FROM canonical_addresses WHERE identity=?',(identity,))}
            if set(result['addresses'][identity])!=actual:raise EvidenceConflict('scoped_archive_addresses')
    receipt=result['receipt'];selected=result['selected']
    if bool(receipt)!=bool(selected):raise EvidenceUnavailable('scoped_archive_receipt')
    with history.writer.transaction():
        if receipt:
            identity=receipt['identity']
            if Path(receipt['path']).stat().st_size!=receipt['bytes']:raise EvidenceUnavailable('scoped_archive_file_bound')
            db.execute('INSERT OR IGNORE INTO scoped_cold_manifests VALUES(?,?,?,?,?,?,?)',
                (identity,receipt['path'],identity,len(selected),receipt['hot_bytes'],receipt['bytes'],history.clock()))
            for row in selected.values():
                values=list(row);values[9]=None;values[12]=identity
                db.execute('INSERT OR REPLACE INTO scoped_cold_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',values)
                db.executemany('INSERT OR IGNORE INTO scoped_cold_addresses VALUES(?,?)',[(row[0],a) for a in result['addresses'][row[0]]])
                db.execute('UPDATE records SET body=NULL WHERE identity=?',(row[0],))
                db.execute('UPDATE rolling_economic_events SET body=NULL,archive=? WHERE identity=?',(identity,row[0]))
                db.execute('DELETE FROM shared_history_cache WHERE identity=?',(row[0],))
        if plan['bindings']:db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('scoped_retirement_cursor',plan['bindings'][-1][1]))
        for key,value in plan.get('hot_cursors',{}).items():
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,canonical(value)))
        if 'hot_table_next' in plan:
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('scoped_retirement_hot_table',str(plan['hot_table_next'])))
        oldest=plan['oldest']
        if oldest is None and 'selection' not in plan:
            row=retirement.oldest_hot_bound_record()
            if row:
                scope=db.execute('''SELECT MIN(b.coverage_scope) FROM canonical_addresses a
                    JOIN evidence_bindings b ON b.market_address=a.address AND b.canonical_scope=?
                    WHERE a.identity=?''',(row[1],row[0])).fetchone()[0]
                oldest=dict(scope=scope,slot=row[2],reason='batch_bound_or_unacknowledged_consumer')
        status=dict(hot_bytes_before=plan['before'],hot_bytes_after=None,hot_bytes_measurement='deferred',
            retired_records=len(selected),retired_logical_bytes=0 if receipt is None else receipt['hot_bytes'],
            pinned_bytes=sum(plan['pinned'].values()),oldest_unretired_scope=oldest,
            candidate_scopes_examined=len(plan['bindings']),candidate_scan_bound=min(plan['limit'],64),
            retirement_seconds=time.monotonic()-plan['started'],worker=result['worker'],off_owner_preparation=True,
            canonical_generation_revalidated=True)
        if 'selection' in plan:
            status.update(selection=plan['selection'],
                candidate_scopes_examined=plan['selection']['candidate_scopes'],
                candidate_scan_bound=plan['selection']['metadata_row_bound']*64,
                cold_bytes_measurement='deferred')
        status.update(records_per_second=len(selected)/max(status['retirement_seconds'],1e-9),
            physical_database_bytes=sum(p.stat().st_size for p in (history.writer.path,Path(str(history.writer.path)+'-wal')) if p.exists()),
            retained_candidate_history_bytes=history.lifecycle.path.stat().st_size,
            cold_bytes=(None if 'selection' in plan else db.execute(
                'SELECT COALESCE(SUM(cold_bytes),0) FROM scoped_cold_manifests').fetchone()[0]),
            pinned_bytes_domain=('examined hot representations' if 'selection' in plan else
                'examined slice and selected-row shared owners'),
            oldest_unretired_scope_domain=('examined hot page only' if 'selection' in plan else
                'examined slice; global fallback when no local witness'))
        db.execute('INSERT INTO scoped_retirement_observations(at,body) VALUES(?,?)',(history.clock(),canonical(status)))
    return status
