"""Existing CandidateHistory delivery off-owner; canonical ACK stays single-writer.

The durable outbox and pending proofs are the restart queue. One bounded batch
uses a dedicated consumer thread, independently of the optional historian.
No new database, provider acquisition or evidence authority.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
from .solana_evidence_plane import EvidenceUnavailable,IntervalProof,canonical,digest
from .solana_selective_runtime import CONTROL
from .runtime.operating_families import active_sql,active_scope_sql
from .solana_selective_history import coverage_scope

MAX_BYTES=16*1024*1024


def generation(life):
    db=life.db;stat=life.writer.path.stat()
    session=db.execute('SELECT session FROM prewarm_startup WHERE id=1').fetchone()
    return (session,life.history.endpoint_identity,stat.st_dev,stat.st_ino)


def proof_receipt(life,row):
    rowid,identity,scope,lo,hi,source,endpoint,raw,at=row
    family,address=scope.split(':',2)[1:]
    binding=life.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND coverage_scope=? LIMIT 1',
        (family,scope)).fetchone()
    candidate=address if binding is None else binding[0]
    lower=(0,) if lo==0 else life.db.execute('SELECT market_time FROM stream_receipts WHERE scope=? AND slot=?',(CONTROL,lo)).fetchone()
    upper=life.db.execute('SELECT market_time FROM stream_receipts WHERE scope=? AND slot<=? ORDER BY slot DESC LIMIT 1',(CONTROL,hi)).fetchone()
    lower_identity=life.db.execute('SELECT slot,parent,hash,previous_hash,census,session,sealed FROM stream_receipts WHERE scope=? AND slot=?',(CONTROL,lo)).fetchone()
    upper_identity=life.db.execute('SELECT slot,parent,hash,previous_hash,census,session,sealed FROM stream_receipts WHERE scope=? AND slot<=? ORDER BY slot DESC LIMIT 1',(CONTROL,hi)).fetchone()
    scopes=life.history.rolling.scopes(family,scope)
    gap_state=[(s,life.db.execute('SELECT id,lo,hi,created,reason FROM candidate_gaps WHERE scope=? AND repaired IS NULL AND lo<=? AND (hi IS NULL OR hi>=?) ORDER BY id',
        (s,hi,lo)).fetchall()) for s in scopes]
    members=[] if not address.startswith('group-') else life.db.execute(
        'SELECT address,lower_slot FROM rolling_group_members WHERE scope=? AND family=? ORDER BY address',(scope,family)).fetchall()
    return dict(identity=identity,scope=scope,family=family,address=address,candidate=candidate,
        lo=lo,hi=hi,source=source,endpoint=endpoint,witness=json.loads(raw),observed_at=at,
        lower=lower,upper=upper,lower_identity=lower_identity,upper_identity=upper_identity,
        gap_state=gap_state,members=members,generation=generation(life))


def capture(life):
    if life.db.in_transaction:raise EvidenceUnavailable('candidate_consumer_before_canonical_commit')
    rows=[];size=0;references={}
    for full in life.db.execute('''SELECT id,family,address,kind,body,hash,created,
        json_extract(body,'$.record.identity'),json_extract(body,'$.record.slot'),json_extract(body,'$.available') FROM candidate_history_outbox
        WHERE '''+active_sql('family',solana=True)+''' AND consumed IS NULL ORDER BY priority,created,rowid LIMIT 64'''):
        row=full[:7]
        size+=len(row[4].encode())
        if size>MAX_BYTES:
            if not rows:raise EvidenceUnavailable('candidate_delivery_input_capacity')
            break
        rows.append(row)
        references[row[0]]=full[7:]
    bindings={(family,address):life.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',
        (family,address)).fetchone() for _,family,address,*_ in rows}
    # Reuse the original proof publication cursor. Blocked old proofs cannot
    # prevent another family or newer earlier interval from being visited.
    cursor=getattr(life,'_proof_publication_cursor',None)
    after='' if cursor is None else ' AND (lo,hi,rowid)>(?,?,?)'
    raw_proofs=life.db.execute('SELECT rowid,* FROM candidate_pending_proofs WHERE '+active_scope_sql('scope')+
        after+' ORDER BY lo,hi,rowid LIMIT 64',tuple(cursor or ())).fetchall()
    proofs=[]
    if raw_proofs and life.path.exists():
        with closing(sqlite3.connect(life.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=0)) as consumer:
            consumer.execute('PRAGMA query_only=ON')
            for row in raw_proofs:
                if life.unconsumed(row[2],through=row[4]):continue
                # A completed unchanged proof need not be reserialized and
                # FULL-committed on every turn while canonical control catches up.
                if not verified_proof(life,consumer,row):proofs.append(proof_receipt(life,row))
    elif raw_proofs:
        proofs=[proof_receipt(life,row) for row in raw_proofs if not life.unconsumed(row[2],through=row[4])]
    refresh=[]
    if getattr(life,'_consumer_refresh_requested',False):
        cursor=getattr(life,'_consumer_refresh_cursor',0)
        for rowid,family,address,state,deadline in life.db.execute('SELECT rowid,family,address,state,deadline FROM candidate_lifecycle WHERE '+
                active_sql('family',solana=True)+" AND state IN ('queued','warming','active') AND rowid>? ORDER BY rowid LIMIT 64",(cursor,)):
            promotion=life.db.execute("SELECT id FROM candidate_history_outbox WHERE family=? AND address=? AND kind='promotion' ORDER BY created DESC,rowid DESC LIMIT 1",(family,address)).fetchone()
            refresh.append((rowid,family,address,state,deadline,promotion))
        if not refresh:life._consumer_refresh_requested=False;life._consumer_refresh_cursor=0
    if not rows and not proofs and not refresh:return None
    return dict(rows=rows,bindings=bindings,references=references,proofs=proofs,generation=generation(life),
        refresh=refresh,at=life.clock(),canonical_path=str(life.writer.path.resolve()),candidate_path=str(life.path.resolve()))


def deliver(snapshot):
    """Only the existing nonauthoritative CandidateHistory DB is writable."""
    from .solana_candidate_lifecycle import CandidateLifecycle
    from .runtime.candidate_history import CandidateHistory
    begun=time.monotonic();cpu=time.thread_time()
    life=CandidateLifecycle.__new__(CandidateLifecycle)
    life.path=Path(snapshot['candidate_path'])
    life.clock=lambda:snapshot['at']+(time.monotonic()-begun)
    life.writer=SimpleNamespace(path=Path(snapshot['canonical_path']))
    life.history=SimpleNamespace(rolling=True)
    acknowledgements=life.deliver_rows(snapshot['rows'],snapshot['bindings'])
    # These scheduling/coverage rows are consumer receipts, not canonical
    # completeness. The owner must independently verify and publish each proof.
    refreshed=[]
    with closing(CandidateHistory(life.path,clock=life.clock,write_wait_seconds=0)) as shared:
        with shared.transaction():
            for proof in snapshot['proofs']:
                p=IntervalProof(proof['scope'],proof['lo'],proof['hi'],proof['source'],proof['endpoint'],
                    proof['witness'],proof['observed_at']);p.validate()
                shared.commit_history_readiness('candidate:'+proof['family']+':'+proof['candidate'],
                    proof['lo'],proof['hi'],proof_hash=proof['identity'],available=life.clock())
                if proof['members']:
                    members=dict(proof['members'])
                    targets=shared.db.execute("SELECT DISTINCT candidate FROM work WHERE lane='meteora' AND status IN ('active','pending')").fetchall()
                    for target, in targets:
                        if target in members and members[target]<=proof['hi']:
                            shared.commit_history_readiness('candidate:meteora:'+target,max(proof['lo'],members[target]),
                                proof['hi'],proof_hash=proof['identity'],available=life.clock())
                if proof['family'] in ('pump','pumpswap') and proof['lower'] and proof['upper']:
                    from .solana_selective_history import FAMILIES
                    from .solana_rolling_history import program_scope
                    shared.commit_coverage(FAMILIES[proof['family']],proof['lo'],proof['hi'],
                        int(proof['lower'][0]),int(proof['upper'][0]),proof_hash=proof['identity'],
                        candidate=None if proof['scope']==program_scope(proof['family']) else proof['candidate'])
                raw=canonical(proof)
                shared.db.execute('INSERT OR REPLACE INTO source_receipts VALUES(?,?,?,?,?,?,?)',
                    ('coverage:'+proof['identity'],proof['family'],proof['address'],'coverage',life.clock(),raw,
                     hashlib.sha256(raw.encode()).hexdigest()))
            for rowid,family,address,state,deadline,promotion in snapshot['refresh']:
                work=None if not promotion else shared.db.execute('SELECT status FROM work WHERE id=?',('provider:'+promotion[0],)).fetchone()
                finished=bool(work and work[0] in ('failed','complete','deadline_missed') or deadline is not None and deadline<life.clock())
                if finished and work and work[0] in ('active','pending'):
                    shared.complete('provider:'+promotion[0],now=life.clock())
                refreshed.append((rowid,'demoted' if finished else 'warming' if work and work[0]=='active' else state))
    return dict(acknowledgements=acknowledgements,refreshed=refreshed,
        metrics=dict(wall_seconds=time.monotonic()-begun,cpu_seconds=time.thread_time()-cpu))


def verified_proof(life,db,row):
    expected=proof_receipt(life,row)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='source_receipts'").fetchone():return False
    receipt=db.execute('SELECT body,hash FROM source_receipts WHERE id=?',('coverage:'+expected['identity'],)).fetchone()
    if receipt is None:return False
    if hashlib.sha256(receipt[0].encode()).hexdigest()!=receipt[1]:raise EvidenceUnavailable('candidate_delivery_receipt_corrupt')
    return digest(json.loads(receipt[0]))==digest(expected)


def acknowledge(life,snapshot,result):
    if digest(generation(life))!=digest(snapshot['generation']):return False
    # Verify durable consumer receipts and unchanged outbox obligations before
    # the canonical owner marks even one delivery consumed. A crash repeats the
    # exact batch; CandidateHistory identities retain their old idempotency.
    with closing(sqlite3.connect(life.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=0)) as db:
        db.execute('PRAGMA query_only=ON')
        for identity,family,address,kind,raw,checksum,at in snapshot['rows']:
            current=life.db.execute('SELECT body,hash,consumed FROM candidate_history_outbox WHERE id=?',(identity,)).fetchone()
            if current is None or current[2] is not None or current[:2]!=(raw,checksum):return False
            bind=life.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
            if bind!=snapshot['bindings'][(family,address)]:return False
            receipt=db.execute('SELECT body,hash FROM source_receipts WHERE id=?',(identity,)).fetchone()
            record_id,slot,available=snapshot['references'][identity]
            expected=dict(source_hash=checksum,scope=coverage_scope(family,address),canonical_identity=record_id)
            if (receipt is None or hashlib.sha256(receipt[0].encode()).hexdigest()!=receipt[1]
                    or digest(json.loads(receipt[0]))!=digest(expected)):
                raise EvidenceUnavailable('candidate_delivery_receipt_missing_or_corrupt')
    acknowledgements=result['acknowledgements']
    if [r[0] for r in acknowledgements]!=[r[0] for r in snapshot['rows']]:
        raise EvidenceUnavailable('candidate_delivery_ack_order')
    for row,(identity,compact_raw,compact_hash) in zip(snapshot['rows'],acknowledgements,strict=True):
        if row[3]=='canonical':
            record_id,slot,available=snapshot['references'][identity]
            raw=canonical(dict(source_hash=row[5],record=dict(identity=record_id,slot=slot),available=available))
            if (compact_raw,compact_hash)!=(raw,hashlib.sha256(raw.encode()).hexdigest()):
                raise EvidenceUnavailable('candidate_delivery_ack_content')
        elif compact_raw is not None or compact_hash is not None:
            raise EvidenceUnavailable('candidate_delivery_ack_content')
    life.acknowledge_rows(acknowledgements)
    refreshed=result['refreshed']
    if [r[0] for r in refreshed]!=[r[0] for r in snapshot['refresh']]:
        raise EvidenceUnavailable('candidate_refresh_ack_order')
    with life.writer.transaction():
        for original,(_,target) in zip(snapshot['refresh'],refreshed,strict=True):
            rowid,family,address,state,deadline,promotion=original
            if target not in (state,'warming','demoted'):raise EvidenceUnavailable('candidate_refresh_state')
            current=life.db.execute('SELECT state,deadline FROM candidate_lifecycle WHERE rowid=? AND family=? AND address=?',(rowid,family,address)).fetchone()
            latest=life.db.execute("SELECT id FROM candidate_history_outbox WHERE family=? AND address=? AND kind='promotion' ORDER BY created DESC,rowid DESC LIMIT 1",(family,address)).fetchone()
            if current!=(state,deadline) or latest!=promotion:continue
            if target=='demoted':
                life.db.execute("UPDATE candidate_lifecycle SET state='demoted',deadline=NULL WHERE rowid=?",(rowid,))
                life.emit(family,address,'demoted',dict(reason='observation_work_finished_or_deadline',at=life.clock(),recoverable=True))
            elif target!=state:life.db.execute('UPDATE candidate_lifecycle SET state=? WHERE rowid=?',(target,rowid))
    if snapshot['refresh']:life._consumer_refresh_cursor=snapshot['refresh'][-1][0]
    return True


def readonly_history(path):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=0)
    db.execute('PRAGMA query_only=ON')
    return SimpleNamespace(db=db,close=db.close)
