"""Candidate-specific cold decoding in the existing bounded history worker.

The owner publishes only byte-verified original cold records. No new writer,
archive format, provider acquisition or duplicated market subscription.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import zlib
from types import SimpleNamespace
from .solana_evidence_plane import EvidenceUnavailable,EvidenceConflict,canonical,digest
from .solana_selective_history import FAMILIES
from .solana_history_delivery import generation

ROWS=64
RAW_BYTES=32*1024*1024 # Existing ScopedRetirement.contents decoded limit.


def metadata(history,family,address):
    db=history.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='scoped_cold_records'").fetchone():return None
    binding=db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
    market=address if binding is None else binding[0]
    rows=db.execute('''SELECT c.* FROM scoped_cold_records c JOIN scoped_cold_addresses a ON a.identity=c.identity
        WHERE c.scope=? AND a.address=? ORDER BY c.slot,c.transaction_index,c.event_index,c.identity LIMIT ?''',
        (FAMILIES[family],market,ROWS)).fetchall()
    if not rows:return None
    archive=rows[0][-1];rows=[r for r in rows if r[-1]==archive]
    manifest=db.execute('SELECT path,hash FROM scoped_cold_manifests WHERE id=?',(archive,)).fetchone()
    if manifest is None:raise EvidenceUnavailable('scoped_cold_manifest_missing')
    return dict(binding=binding,market=market,rows=rows,archive=archive,manifest=manifest,
        generation=generation(history.lifecycle))


def prepare(path,job):
    from .solana_history_work import CPUBudget,READ_SECONDS,INPUT_BYTES
    started=time.monotonic();cpu=time.process_time();spec=job['spec']
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
        db.execute('PRAGMA query_only=ON');until=time.monotonic()+READ_SECONDS
        db.set_progress_handler(lambda:int(time.monotonic()>until),1000);db.execute('BEGIN')
        history=SimpleNamespace(db=db)
        history.lifecycle=SimpleNamespace(db=db,writer=SimpleNamespace(path=Path(path)),history=SimpleNamespace(endpoint_identity=job['endpoint_identity']))
        snapshot=metadata(history,spec['family'],spec['address']);db.execute('ROLLBACK')
    output=[];budget=CPUBudget(.25);size=0
    if snapshot:
        path,checksum=snapshot['manifest']
        # Bound before reading an archive. Existing archive raw bytes and format
        # remain unchanged; decompression runs after the read snapshot closes.
        with Path(path).open('rb') as source:packed=source.read(RAW_BYTES+1024*1024+1)
        if len(packed)>RAW_BYTES+1024*1024:raise EvidenceUnavailable('scoped_cold_restore_bound')
        if hashlib.sha256(packed).hexdigest()!=checksum:raise EvidenceConflict('scoped_cold_hash_mismatch')
        decoder=zlib.decompressobj();raw=decoder.decompress(packed,RAW_BYTES+1)
        if len(raw)>RAW_BYTES or not decoder.eof:raise EvidenceUnavailable('scoped_cold_restore_bound')
        expected={r[0]:r for r in snapshot['rows']}
        for index,item in enumerate(json.loads(raw)):
            if index%64==0:budget()
            body=item['record'];identity=body['identity'];row=expected.get(identity)
            if row is None:continue
            if snapshot['market'] not in body['addresses'] or body['scope']!=FAMILIES[spec['family']]:continue
            serialized=canonical(body)
            if (hashlib.sha256(serialized.encode()).hexdigest(),item['available'])!=(row[10],row[11]):
                raise EvidenceConflict('local_evidence_hash_mismatch')
            size+=len(serialized.encode())
            if size>INPUT_BYTES:raise EvidenceUnavailable('historical_input_capacity')
            output.append((identity,serialized));budget()
        if {r[0] for r in output}!=set(expected):raise EvidenceUnavailable('scoped_cold_identity_missing')
    return dict(id=job['id'],token=job['token'],spec=spec,snapshot=snapshot,records=output,
        result_hash=digest(output),metrics=dict(wall_seconds=time.monotonic()-started,cpu_seconds=time.process_time()-cpu))


def apply(tasks,job,result):
    h=tasks.history;db=h.db
    if (result['id'],result['token'],result['spec'],result['result_hash'])!=(job['id'],job['token'],job['spec'],digest(result['records'])):
        raise EvidenceUnavailable('historical_restore_result_identity')
    with tasks.writer.transaction():
        lease=db.execute("SELECT deadline FROM rolling_preparation_jobs WHERE id=? AND token=? AND status='active'",(job['id'],job['token'])).fetchone()
        if lease is None:return False
        if tasks.clock()>=lease[0]:return tasks.defer(job,'original_deadline_expired',stale=True)
        fresh=metadata(h,job['spec']['family'],job['spec']['address'])
        if digest(fresh)!=digest(result['snapshot']):return tasks.defer(job,'cold_source_changed',stale=True)
        expected={} if fresh is None else {r[0]:r for r in fresh['rows']}
        if {r[0] for r in result['records']}!=set(expected):raise EvidenceUnavailable('historical_restore_records')
        for identity,raw in result['records']:
            row=expected[identity]
            if hashlib.sha256(raw.encode()).hexdigest()!=row[10]:raise EvidenceConflict('local_evidence_hash_mismatch')
            normalized=db.execute('SELECT 1 FROM rolling_economic_events WHERE identity=?',(identity,)).fetchone()
            if normalized:db.execute('UPDATE rolling_economic_events SET body=?,archive=NULL WHERE identity=?',(raw,identity))
            else:
                db.execute('INSERT OR IGNORE INTO shared_history_cache VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)',(*row[:9],raw,row[10],row[11]))
                db.execute('INSERT OR IGNORE INTO cached_addresses SELECT identity,address FROM scoped_cold_addresses WHERE identity=?',(identity,))
            db.execute('DELETE FROM scoped_cold_records WHERE identity=?',(identity,))
            db.execute('DELETE FROM scoped_cold_addresses WHERE identity=?',(identity,))
        remaining=metadata(h,job['spec']['family'],job['spec']['address']) is not None
        db.execute("UPDATE rolling_preparation_jobs SET status=?,token=NULL,lease_until=NULL,updated=?,result_hash=? WHERE id=?",
            ('pending' if remaining else 'complete',tasks.clock(),result['result_hash'],job['id']))
        h._observation(job['id'],'historical_cold_restored',dict(records=len(result['records']),remaining=remaining,
            worker=result['metrics'],entry_authority=False,deadline_reset=False))
    return dict(restored=len(result['records']),complete=not remaining,entry_authority=False)
