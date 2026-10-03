"""Hand-written SQLite states and exact frozen read functions; no native service."""
from contextlib import closing, contextmanager
import importlib
import json
from pathlib import Path
import sqlite3
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from core import canonical, file_sha
from overload import capture_stale_refusals
from preserve import inventory, persist
from regression_fixtures import safe_overload_row
from review import source_checkout
from verify import SCOPES, restart_raw_state, stress_member_result

WALL = 1800000001.0


@contextmanager
def native_reads():
    """Only import frozen pure readers/predicates, never service/workload code."""
    with patch.dict(sys.modules):
        for name in list(sys.modules):
            if name == 'meme_machine' or name.startswith('meme_machine.'):
                sys.modules.pop(name)
        package = ModuleType('meme_machine')
        package.__path__ = [str(source_checkout()/'meme_machine')]
        sys.modules['meme_machine'] = package
        plane = importlib.import_module('meme_machine.solana_evidence_plane')
        health = importlib.import_module('meme_machine.solana_evidence_health')
        runtime = importlib.import_module('meme_machine.solana_evidence_runtime')
        yield SimpleNamespace(plane=plane,health=health,runtime=runtime)


def raw_state(path, native):
    with closing(native.plane.EvidenceReader(path)) as reader:
        reader.db.execute('BEGIN')
        return restart_raw_state(reader.db)


def make_restart(root, native, *, reason='evidence_discontinuous', full_profile=False):
    """Represent FAILED -> WARMING -> OFF with no service/frame/provider work."""
    root = Path(root);root.mkdir(parents=True,exist_ok=True)
    row = safe_overload_row()
    proof = row['native_restart']
    original_health = proof['before']['health']
    protected = proof['before']['protected']
    for table in protected:
        if table not in ('integrity','stream_receipts'):
            protected[table] = [[table,'UNIT ONLY']]
    protected['stream_receipts'] = [[scope,11,10,1,'unit-before'] for scope in SCOPES]
    original_gaps = [['unit-scope',0,0,'unit-prior-gap']]
    for phase,name in [('before','before-restart-native-state/db'),('warming','d/db')]:
        path = root/name;path.parent.mkdir()
        health = json.loads(canonical(original_health))
        health['heartbeat'] = WALL
        health['storage_maintenance']['maintenance_arbiter']['generation'] = 'unit-before' if phase == 'before' else 'unit-after'
        for scope in SCOPES:
            health['finalized_frontier:'+scope] = dict(slot=11,time=WALL-(61 if reason == 'evidence_finalized_stale' else 1),seen=WALL)
        gaps = list(original_gaps)
        if phase == 'warming':
            health['phase'] = 'WARMING'
            gaps += [[scope,10,None,'service_restart'] for scope in SCOPES]
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            for table in protected:
                if table not in ('integrity','stream_receipts'):
                    db.execute('CREATE TABLE '+table+'(a,b)')
                    db.executemany('INSERT INTO '+table+' VALUES(?,?)',protected[table])
            db.executescript('CREATE TABLE stream_receipts(scope,slot,parent,sealed,session);'
                'CREATE TABLE coverage(scope,lo,hi,available);'
                'CREATE TABLE maintenance_progress(scope,side,work); CREATE TABLE maintenance_episodes(scope,side,started);'
                'CREATE TABLE records(identity,hash,scope,slot,archive,market_time,first_seen);'
                'CREATE TABLE counters(key,value); CREATE TABLE meta(key,value); CREATE TABLE service_health(key,value);'
                'CREATE TABLE gaps(scope,lo,hi,reason,created,repaired);')
            db.executemany('INSERT INTO stream_receipts VALUES(?,?,?,?,?)',protected['stream_receipts'])
            db.executemany('INSERT INTO coverage VALUES(?,?,?,?)',[(scope,10,11,WALL-1) for scope in SCOPES])
            db.execute('INSERT INTO maintenance_progress VALUES(?,?,?)',('unit-scope','archive',1))
            db.execute('INSERT INTO maintenance_episodes VALUES(?,?,?)',('unit-scope','archive',WALL-2))
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?)',('unit-identity','unit-hash','unit-scope',1,None,1.0,1.0))
            db.executemany('INSERT INTO counters VALUES(?,?)',proof['before']['counters'].items())
            db.execute('INSERT INTO meta VALUES(?,?)',('retention_floor:unit-scope',0))
            db.executemany('INSERT INTO service_health VALUES(?,?)',[(k,json.dumps(v)) for k,v in health.items()])
            db.executemany('INSERT INTO gaps VALUES(?,?,?,?,?,NULL)',[r+[WALL-2] for r in gaps])
            db.commit()
    times = [WALL+.125,WALL+.375,WALL+.625]
    plane = native.runtime.RuntimeEvidence(root/'d/db',owner='UNIT ONLY',clock=iter(times).__next__)
    try:
        proof['stale_refusals'] = capture_stale_refusals(plane,SCOPES,root,generation='unit-after')
    finally:
        plane.close()
    with closing(sqlite3.connect(root/'d/db')) as db:
        db.execute('UPDATE service_health SET value=? WHERE key=?',(json.dumps('OFF'),'phase'))
        db.execute('UPDATE service_health SET value=? WHERE key=?',(json.dumps(WALL+2),'heartbeat'))
        db.commit()
    proof['before'] = dict(raw_state(root/'before-restart-native-state/db',native),wall=WALL)
    proof['after'] = dict(raw_state(root/'d/db',native),wall=WALL+2)
    receipt = root/'BEFORE_RESTART_INVENTORY.json'
    persist(receipt,{'artifacts':inventory(root/'before-restart-native-state')})
    proof['preserved_original_inventory_sha256'] = file_sha(receipt)
    row.update(workload_valid=full_profile,observation_valid=True)
    row.update(stress_member_result(row))
    return row


def rewrite_refusal(root, refusal):
    """Counterfactual unit receipt: let SQL recomputation reject coherent forgeries."""
    path = Path(root)/refusal['receipt_path']
    recorded = {k:v for k,v in refusal.items() if k not in ('receipt_path','receipt_sha256')}
    path.write_bytes(canonical(recorded)+b'\n')
    refusal['receipt_sha256'] = file_sha(path)


def rebind_raw(root, row):
    for refusal in row['native_restart']['stale_refusals']:
        path = Path(root)/refusal['raw_state_path']
        refusal.update(raw_state_sha256=file_sha(path),raw_state_bytes=path.stat().st_size)
        rewrite_refusal(root,refusal)
