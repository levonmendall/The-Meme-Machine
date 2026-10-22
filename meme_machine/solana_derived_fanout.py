"""Durable canonical intake and bounded derived outbox preparation.

Recipients and dispatch positions are frozen by the sole canonical owner at
queue_records' original point. The existing private preparation worker builds
only those rows. Consumer FULL, fresh owner ACK and proof publication remain
independent authority boundaries; prepared products do not prove delivery.
"""
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .solana_evidence_plane import EvidenceUnavailable,canonical,digest
from .solana_selective_history import FAMILIES
from .runtime.sqlite_failure import connect as diagnostic_connect

MAX_BYTES=32*1024*1024 # Existing canonical reservation/preparation byte bound.
MAX_RECORDS=8*2048 # Existing eight frames and 2048 records per frame.
PAGE=64
PAGE_BYTES=16*1024*1024 # Existing delivery input/result bound.
SCHEMA='''
CREATE TABLE IF NOT EXISTS candidate_derived_fanout(
 id TEXT PRIMARY KEY,record_identity TEXT NOT NULL,scope TEXT NOT NULL,slot INTEGER NOT NULL,
 record_raw TEXT NOT NULL,record_hash TEXT NOT NULL,available REAL NOT NULL,
 recipients_hash TEXT NOT NULL,recipients_count INTEGER NOT NULL,
 position INTEGER NOT NULL,retained_bytes INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS candidate_fanout_record ON candidate_derived_fanout(record_identity);
CREATE INDEX IF NOT EXISTS candidate_fanout_scope ON candidate_derived_fanout(scope,slot);
CREATE TABLE IF NOT EXISTS candidate_fanout_targets(
 outbox_rowid INTEGER PRIMARY KEY,intent TEXT NOT NULL,position INTEGER NOT NULL,
 family TEXT NOT NULL,address TEXT NOT NULL,market TEXT NOT NULL,candidate TEXT NOT NULL,
 created REAL NOT NULL,hash TEXT NOT NULL,UNIQUE(intent,position));
CREATE INDEX IF NOT EXISTS candidate_fanout_address ON candidate_fanout_targets(family,address,intent);
CREATE INDEX IF NOT EXISTS candidate_fanout_candidate ON candidate_fanout_targets(family,candidate,intent);
'''
COLUMNS='id,record_identity,scope,slot,record_raw,record_hash,available,recipients_hash,recipients_count,position,retained_bytes'
TARGET_COLUMNS='outbox_rowid,intent,position,family,address,market,candidate,created,hash'
# Same-consumer predecessor fencing preserves the original metadata fold and
# dispatch order without stopping unrelated candidates or owner maintenance.
DISPATCH_GUARD=''' NOT EXISTS(SELECT 1 FROM candidate_fanout_targets t
 JOIN candidate_derived_fanout f ON f.id=t.intent
 WHERE t.position>=f.position AND t.family=o.family AND (t.address=o.address OR t.candidate=CASE
   WHEN o.family='pump' AND o.kind='canonical' THEN json_extract(o.body,'$.record.payload.event.mint')
   ELSE COALESCE((SELECT market_address FROM evidence_bindings
      WHERE family=o.family AND address=o.address),o.address) END)
 AND (o.kind!='canonical' OR (t.created,t.outbox_rowid)<(o.created,o.rowid))) '''


class FanoutBackpressure(Exception):
    """No mutation admitted: the producer retains its original frame bound."""


@dataclass(frozen=True)
class PreparedFanout:
    generation:tuple
    records:tuple
    bindings:tuple
    checksum:str
    tails:tuple=()


def _placeholder(intent,position,record_identity,slot,available):
    identity='fanout:'+digest([intent,position])
    raw=canonical(dict(available=available,record=dict(identity=record_identity,slot=slot),fanout_pending=True))
    return identity,raw,hashlib.sha256(raw.encode()).hexdigest()


def freeze(life,rows):
    """Freeze exact original recipients inside the intake FULL transaction."""
    if not life.db.in_transaction:raise EvidenceUnavailable('candidate_fanout_before_intake_commit')
    intents=[];targets=[];added_bytes=0;identities=set()
    for row in rows:
        if row.scope not in (FAMILIES['pump'],FAMILIES['pumpswap']) or row.kind!='event':
            life.queue_records((row,));continue
        recipients=life.record_recipients(row)
        if not recipients:continue
        stored=life.db.execute('SELECT body,hash,first_seen FROM canonical_evidence WHERE identity=?',
            (row.identity,)).fetchone()
        if stored is None or type(stored[0]) is not str:raise EvidenceUnavailable('candidate_fanout_source_missing')
        identity=digest([row.identity,stored[1],stored[2],recipients])
        if identity in identities or life.db.execute('SELECT 1 FROM candidate_derived_fanout WHERE id=?',(identity,)).fetchone():continue
        # Leave an individually oversized legacy row on its original emission
        # and delivery-capacity failure path, rather than admit an intent which
        # no existing bounded preparation/delivery page could ever consume.
        routing=max(len(canonical([identity,position,family,address,market,
            row.payload['event']['mint'] if family=='pump' else market]).encode())
            for position,(family,address,market) in enumerate(recipients))
        if len(stored[0].encode())+len(canonical(stored[2]).encode())+routing+1024>PAGE_BYTES:
            life.queue_records((row,));continue
        identities.add(identity);frozen=[];target_bytes=0
        for position,(family,address,market) in enumerate(recipients):
            candidate=row.payload['event']['mint'] if family=='pump' else market
            at=life.clock()
            placeholder,raw,checksum=_placeholder(identity,position,row.identity,row.slot,stored[2])
            inserted=life.db.execute('''INSERT OR IGNORE INTO candidate_history_outbox
                (id,family,address,kind,body,hash,created,consumed,priority) VALUES(?,?,?,'canonical',?,?,?,NULL,0)''',
                (placeholder,family,address,raw,checksum,at))
            if not inserted.rowcount:raise EvidenceUnavailable('candidate_fanout_source_corrupt')
            target=(inserted.lastrowid,identity,position,family,address,market,candidate,at)
            # Small routing/position hashes are frozen here. Full economic
            # envelope hashing and per-alias receipt IDs belong to the worker.
            frozen.append(target)
            target_bytes+=len(canonical(target).encode())+len(raw.encode())+256
        tail='';chained=[]
        for target in reversed(frozen):
            tail=digest([target,tail]);chained.append((*target,tail))
        frozen=tuple(reversed(chained))
        size=len(stored[0].encode())+target_bytes+len(row.identity.encode())+len(row.scope.encode())+256
        if size>MAX_BYTES:raise EvidenceUnavailable('candidate_fanout_input_bound')
        intents.append((identity,row.identity,row.scope,row.slot,*stored,tail,len(frozen),0,size))
        targets.extend(frozen);added_bytes+=size
    if not intents:return
    count,size=life.db.execute('SELECT count(*),coalesce(sum(retained_bytes),0) FROM candidate_derived_fanout').fetchone()
    if count+len(intents)>MAX_RECORDS or size+added_bytes>MAX_BYTES:raise FanoutBackpressure()
    life.db.executemany('INSERT INTO candidate_derived_fanout VALUES(?,?,?,?,?,?,?,?,?,?,?)',intents)
    life.db.executemany('INSERT INTO candidate_fanout_targets VALUES(?,?,?,?,?,?,?,?,?)',targets)
    # Private scheduling revision only. The native owner callback publishes a
    # pulse after its complete outer FULL commit, even if its caller cancels.
    life.history._fanout_intake_revision=getattr(life.history,'_fanout_intake_revision',0)+1
    from .solana_history_notifications import changed
    changed(life.history)


def _checksum(generation,records,bindings,tails=()):
    # Hash metadata only here: the pinned worker validates full source bytes,
    # and fresh owner apply compares those exact durable bytes and positions.
    return digest([generation,[(row[:4]+row[5:],tuple(t for t in targets),
        [(r[0],r[1],r[2],r[3],r[4],r[6],r[7]) for r in outputs])
        for row,targets,outputs in records],bindings,tails])


def prepare(path,endpoint_identity,source_identity):
    """Bounded coherent RO capture, closed before CPU transform or owner wait."""
    path=Path(path).resolve();before=path.stat()
    if (before.st_dev,before.st_ino)!=tuple(source_identity):raise EvidenceUnavailable('candidate_delivery_source_replaced')
    captured=[];bindings={};input_bytes=0;output_bytes=0;count=0
    with closing(diagnostic_connect(path.as_uri()+'?mode=ro',uri=True,timeout=0,
            diagnostic_role='candidate_fanout.prepare_read')) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        try:
            session=db.execute('SELECT session FROM prewarm_startup WHERE id=1').fetchone()
            generation=(session,endpoint_identity,before.st_dev,before.st_ino)
            # Inspect source size before retrieving bodies; complete recipient
            # populations remain in the indexed durable table, not this page.
            keys=db.execute('SELECT id,length(CAST(record_raw AS BLOB)) FROM candidate_derived_fanout ORDER BY rowid LIMIT ?',(PAGE,)).fetchall()
            if not keys:_empty_reservations(db)
            for identity,size in keys:
                if input_bytes+size+512>PAGE_BYTES:
                    if not captured:raise EvidenceUnavailable('candidate_fanout_input_bound')
                    break
                row=db.execute('SELECT '+COLUMNS+' FROM candidate_derived_fanout WHERE id=?',(identity,)).fetchone()
                raw_size=size+len(canonical(row[6]).encode())+26;selected=[];selected_bytes=0
                candidates=db.execute('SELECT '+TARGET_COLUMNS+' FROM candidate_fanout_targets WHERE intent=? AND position>=? ORDER BY position LIMIT ?',
                    (identity,row[9],PAGE-count)).fetchall()
                for target in candidates:
                    target_size=len(canonical(target).encode())+128
                    if input_bytes+size+selected_bytes+target_size+512>PAGE_BYTES or output_bytes+raw_size+256>PAGE_BYTES:break
                    key=(target[3],target[4])
                    if key not in bindings:bindings[key]=db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',key).fetchone()
                    selected.append(target);selected_bytes+=target_size;output_bytes+=raw_size+256;count+=1
                if not selected:
                    if not captured:raise EvidenceUnavailable('candidate_delivery_input_capacity')
                    break
                input_bytes+=size+selected_bytes+512
                end=row[9]+len(selected)
                tail=db.execute('SELECT hash FROM candidate_fanout_targets WHERE intent=? AND position=?',
                    (identity,end)).fetchone() if end<row[8] else ('',)
                if tail is None:raise EvidenceUnavailable('candidate_fanout_source_corrupt')
                captured.append((row,tuple(selected),(identity,end,tail[0])))
                if row[9]+len(selected)<row[8] or count==PAGE:break
            after=path.stat()
            if (after.st_dev,after.st_ino)!=(before.st_dev,before.st_ino):raise EvidenceUnavailable('candidate_delivery_source_replaced')
        finally:db.rollback()
    records=[];tails=[]
    for row,targets,tail in captured:
        if hashlib.sha256(row[4].encode()).hexdigest()!=row[5]:raise EvidenceUnavailable('candidate_fanout_source_corrupt')
        body=json.loads(row[4])
        if (body['identity'],body['scope'],body['slot'])!=tuple(row[1:4]):raise EvidenceUnavailable('candidate_fanout_source_corrupt')
        if not 0<=row[9]<row[8] or not targets:raise EvidenceUnavailable('candidate_fanout_cursor')
        check=tail[2]
        for target in reversed(targets):
            if digest([target[:-1],check])!=target[-1]:raise EvidenceUnavailable('candidate_fanout_source_corrupt')
            check=target[-1]
        if check!=row[7]:raise EvidenceUnavailable('candidate_fanout_source_corrupt')
        raw='{"available":'+canonical(row[6])+',"record":'+row[4]+'}'
        checksum=hashlib.sha256(raw.encode()).hexdigest();outputs=[]
        for offset,target in enumerate(targets):
            outbox_rowid,intent,position,family,address,market,candidate,at,check=target
            if intent!=row[0] or position!=row[9]+offset:raise EvidenceUnavailable('candidate_fanout_source_corrupt')
            identity=hashlib.sha256(('['+','.join(canonical(v) for v in (family,address,'canonical'))+','+raw+']').encode()).hexdigest()
            outputs.append((outbox_rowid,identity,family,address,'canonical',raw,checksum,at))
        records.append((row,targets,tuple(outputs)));tails.append(tail)
    if not records:return None
    records=tuple(records);bindings=tuple(sorted(bindings.items()));tails=tuple(tails)
    return PreparedFanout(generation,records,bindings,_checksum(generation,records,bindings,tails),tails)


def apply(life,prepared):
    """Fresh bindings/source plus atomic original outbox rows and intent cursor."""
    from .solana_history_delivery import generation
    if (type(prepared) is not PreparedFanout or not 0<len(prepared.records)<=PAGE
            or len(prepared.tails)!=len(prepared.records)
            or prepared.checksum!=_checksum(prepared.generation,prepared.records,prepared.bindings,prepared.tails)):
        raise EvidenceUnavailable('candidate_fanout_preparation_changed')
    if generation(life)!=prepared.generation:return False
    if (sum(len(outputs) for _,_,outputs in prepared.records)>PAGE or
            sum(len(output[5].encode())+256 for _,_,outputs in prepared.records for output in outputs)>PAGE_BYTES):
        raise EvidenceUnavailable('candidate_fanout_preparation_changed')
    publication=False
    with life.writer.transaction():
        for key,binding in prepared.bindings:
            if life.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',key).fetchone()!=binding:return False
        for (expected,targets,outputs),tail in zip(prepared.records,prepared.tails,strict=True):
            current=life.db.execute('SELECT '+COLUMNS+' FROM candidate_derived_fanout WHERE id=?',(expected[0],)).fetchone()
            if current!=expected:return False
            source=life.db.execute('SELECT scope,slot,hash,first_seen FROM canonical_evidence WHERE identity=?',(current[1],)).fetchone()
            if source!=(current[2],current[3],current[5],current[6]):raise EvidenceUnavailable('candidate_fanout_source_corrupt')
            actual=life.db.execute('SELECT '+TARGET_COLUMNS+' FROM candidate_fanout_targets WHERE intent=? AND position>=? ORDER BY position LIMIT ?',
                (current[0],current[9],len(targets))).fetchall()
            if tuple(actual)!=targets:return False
            if len(outputs)!=len(targets) or not 0<len(targets)<=current[8]-current[9]:raise EvidenceUnavailable('candidate_fanout_cursor')
            end=current[9]+len(targets)
            boundary=life.db.execute('SELECT hash FROM candidate_fanout_targets WHERE intent=? AND position=?',
                (current[0],end)).fetchone() if end<current[8] else ('',)
            if boundary is None or tail!=(current[0],end,boundary[0]):return False
            raw='{"available":'+canonical(current[6])+',"record":'+current[4]+'}'
            for output,target in zip(outputs,targets,strict=True):
                if (output[0],output[2],output[3],output[4],output[5],output[7])!=(target[0],target[3],target[4],'canonical',raw,target[7]):
                    raise EvidenceUnavailable('candidate_fanout_preparation_changed')
                placeholder,marker,checksum=_placeholder(current[0],target[2],current[1],current[3],current[6])
                reserved=life.db.execute('SELECT id,family,address,kind,body,hash,created,consumed,priority FROM candidate_history_outbox WHERE rowid=?',
                    (target[0],)).fetchone()
                if reserved!=(placeholder,target[3],target[4],'canonical',marker,checksum,target[7],None,0):
                    raise EvidenceUnavailable('candidate_fanout_source_corrupt')
        for (row,targets,outputs),tail in zip(prepared.records,prepared.tails,strict=True):
            for output in outputs:
                rowid,identity,family,address,kind,raw,checksum,at=output
                # INSERT OR IGNORE's original duplicate behavior leaves an
                # existing real row unchanged. A reservation supplies only
                # dispatch position; it can never be acknowledged as delivery.
                existing=life.db.execute('SELECT consumed FROM candidate_history_outbox WHERE id=?',(identity,)).fetchone()
                if existing is not None:
                    # A consumed duplicate has no future FULL/ACK to reopen
                    # proof eligibility after this reservation disappears.
                    publication|=existing[0] is not None
                    life.db.execute('DELETE FROM candidate_history_outbox WHERE rowid=?',(rowid,))
                else:life.db.execute('UPDATE candidate_history_outbox SET id=?,body=?,hash=? WHERE rowid=?',
                    (identity,raw,checksum,rowid))
            end=row[9]+len(targets)
            if end==row[8]:
                life.db.execute('DELETE FROM candidate_fanout_targets WHERE intent=?',(row[0],))
                life.db.execute('DELETE FROM candidate_derived_fanout WHERE id=?',(row[0],))
            else:life.db.execute('UPDATE candidate_derived_fanout SET position=?,recipients_hash=? WHERE id=?',(end,tail[2],row[0]))
        from .solana_history_notifications import changed
        # Genuinely new/unconsumed outputs cannot yet authorize a proof. Their
        # eventual fresh ACK wakes publication; delivery still wakes now.
        changed(life.history,publication=publication)
    return True


def pending(life,scope,through=None):
    """Fence this proof/recipient interval, never unrelated derived work."""
    family,address=scope.split(':',2)[1:]
    if family not in ('pump','pumpswap'):return False
    from .solana_rolling_history import program_scope
    bound='' if through is None else ' AND f.slot<=?'
    args=(FAMILIES[family],*(() if through is None else (through,)))
    if scope==program_scope(family):
        return life.db.execute('SELECT 1 FROM candidate_derived_fanout f WHERE f.scope=?'+bound+' LIMIT 1',args).fetchone() is not None
    aliases={address,*[r[0] for r in life.db.execute('SELECT address FROM evidence_bindings WHERE family=? AND coverage_scope=?',(family,scope))]}
    return any(life.db.execute('''SELECT 1 FROM candidate_fanout_targets t JOIN candidate_derived_fanout f
        ON f.id=t.intent WHERE f.scope=?'''+bound+' AND t.position>=f.position AND t.family=? AND t.address=? LIMIT 1',(*args,family,alias)).fetchone() for alias in aliases)


def record_pending(db,identity):
    """A previous consumer receipt cannot retire a newly frozen obligation."""
    return db.execute('SELECT 1 FROM candidate_derived_fanout WHERE record_identity=? LIMIT 1',
        (identity,)).fetchone() is not None


def pending_counts(life):
    counts=life.db.execute('''SELECT count(*),coalesce(sum(retained_bytes),0),
        coalesce(sum(max(1,recipients_count-position)),0) FROM candidate_derived_fanout''').fetchone()
    if not counts[0]:_empty_reservations(life.db)
    return counts


def _empty_reservations(db):
    # With no intents, neither a target nor a reserved namespace row has an
    # owner. The outbox primary-key range seek avoids a per-event population
    # scan. A fault can never turn an orphan reservation into an empty drain.
    if (db.execute('SELECT 1 FROM candidate_fanout_targets LIMIT 1').fetchone() or
            db.execute("SELECT 1 FROM candidate_history_outbox WHERE id>='fanout:' AND id<'fanout;' LIMIT 1").fetchone()):
        raise EvidenceUnavailable('candidate_fanout_reservation_orphan')
