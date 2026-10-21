"""Existing CandidateHistory delivery off-owner; canonical ACK stays single-writer.

The durable outbox and pending proofs are the restart queue. One bounded batch
uses a dedicated consumer thread, independently of the optional historian.
No new database, provider acquisition or evidence authority.
"""
from contextlib import closing
from dataclasses import dataclass
from functools import wraps
from .runtime.operation_costs import measured
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
from .solana_evidence_plane import EvidenceUnavailable,IntervalProof,canonical,digest
from .solana_selective_runtime import CONTROL
from .runtime.operating_families import active_sql,active_scope_sql
from .runtime.sqlite_failure import connect as diagnostic_connect,boundary
from .solana_selective_history import coverage_scope
from .solana_rolling_history import program_scope

MAX_BYTES=16*1024*1024


@dataclass(frozen=True)
class CaptureContext:
    canonical_path:str
    candidate_path:str
    endpoint_identity:str
    clock:object
    source_identity:tuple|None=None


@dataclass(frozen=True)
class ActorAck:
    accepted:bool
    hint:object
    refresh_cleared:bool=False


def capture_context(life):
    """Initial owner bootstrap only; never transfer its connection or methods."""
    stat=life.writer.path.stat()
    return CaptureContext(str(life.writer.path.resolve()),str(life.path.resolve()),
        life.history.endpoint_identity,life.clock,(stat.st_dev,stat.st_ino))


class _CaptureRolling:
    def __init__(self,db):self.db=db
    def scopes(self,*args,**kwargs):
        from .solana_rolling_history import RollingHistory
        return RollingHistory.scopes(self,*args,**kwargs)
    def pending_slice(self,*args,**kwargs):
        from .solana_rolling_history import RollingHistory
        return RollingHistory.pending_slice(self,*args,**kwargs)


class _CaptureHistory:
    def __init__(self,db,context):
        self.db=db;self.endpoint_identity=context.endpoint_identity
        self.rolling=_CaptureRolling(db)
    def scope_for(self,*args,**kwargs):
        from .solana_selective_history import SelectiveHistory
        return SelectiveHistory.scope_for(self,*args,**kwargs)


class _CaptureReader:
    """The shared selectors receive read helpers, never an owner connection."""
    def __init__(self,db,context,actor,hint):
        self.db=db;self.path=Path(context.candidate_path);self.clock=context.clock
        self.writer=SimpleNamespace(path=Path(context.canonical_path))
        self.history=_CaptureHistory(db,context);self.hint=hint;self._generation=None
        self._proof_delivery_generation=actor.proof_generation
        self._proof_delivery_progress=dict(actor.proof_progress)
        self._consumer_refresh_requested=hint.refresh_requested
        self._consumer_refresh_cursor=actor.refresh_cursor
        self._consumer_refresh_horizon=actor.refresh_horizon
        self._consumer_refresh_revision=actor.refresh_revision
    def unconsumed(self,*args,**kwargs):
        from .solana_candidate_lifecycle import CandidateLifecycle
        return CandidateLifecycle.unconsumed(self,*args,**kwargs)


class CaptureActor:
    """One consumer-thread actor; durable queues remain the restart authority.

    Connections belong to one bounded capture, so cancellation cannot leave a
    canonical WAL reader pinned while the consumer FULL-commits or shuts down.
    Only an accepted owner ACK advances the private scheduling cursors.
    """
    def __init__(self,context):
        self.context=context;self.proof_generation=None;self.proof_progress={}
        self.refresh_token=None;self.refresh_cursor=0;self.refresh_horizon=None;self.refresh_revision=None
        stat=None if context.source_identity is not None else Path(context.canonical_path).stat()
        self.source_identity=context.source_identity if stat is None else (stat.st_dev,stat.st_ino)

    def capture(self,hint,previous=None):
        if previous is not None:
            snapshot,feedback=previous
            if feedback.accepted:
                scan=snapshot.get('proof_scan')
                if (scan and self.proof_generation==scan['generation']
                        and self.proof_progress==scan['base']):
                    self.proof_progress=dict(scan['next'])
                refresh=snapshot.get('refresh_scan')
                if refresh and self.refresh_token==refresh['token']:
                    if refresh['finished']:
                        # A newer commit can add work behind this cursor. Finish
                        # the bounded sweep first, then revisit after cadence.
                        self.refresh_cursor=0;self.refresh_horizon=None;self.refresh_revision=None
                    elif snapshot['refresh']:
                        self.refresh_cursor=snapshot['refresh'][-1][0]
        if hint.refresh_token!=self.refresh_token or not hint.refresh_requested:
            self.refresh_token=hint.refresh_token
            self.refresh_cursor=0;self.refresh_horizon=None;self.refresh_revision=None
        path=Path(self.context.canonical_path);before=path.stat()
        if (before.st_dev,before.st_ino)!=self.source_identity:
            raise EvidenceUnavailable('candidate_delivery_source_replaced')
        with closing(diagnostic_connect(path.as_uri()+'?mode=ro',
                diagnostic_role='candidate_delivery.capture_read',uri=True,timeout=0)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            try:
                reader=_CaptureReader(db,self.context,self,hint)
                snapshot=capture(reader,revision=hint.revision,schedule=True)
                after=path.stat()
                if ((before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino)
                        or reader._generation is not None and reader._generation[2:]!=(before.st_dev,before.st_ino)):
                    raise EvidenceUnavailable('candidate_delivery_source_replaced')
                self.proof_generation=reader._proof_delivery_generation
                self.proof_progress=dict(reader._proof_delivery_progress)
                self.refresh_cursor=reader._consumer_refresh_cursor
                self.refresh_horizon=reader._consumer_refresh_horizon
                self.refresh_revision=reader._consumer_refresh_revision
            except BaseException:
                try:db.rollback()
                except sqlite3.Error:pass
                raise
            else:db.rollback()
        return snapshot


def generation(life):
    if isinstance(life,_CaptureReader) and life._generation is not None:return life._generation
    db=life.db;stat=life.writer.path.stat()
    session=db.execute('SELECT session FROM prewarm_startup WHERE id=1').fetchone()
    result=(session,life.history.endpoint_identity,stat.st_dev,stat.st_ino)
    if isinstance(life,_CaptureReader):life._generation=result
    return result


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


def _proof_page(life,progress,key,where,args,limit,revision):
    """One fixed keyset horizon. Progress is a volatile ACKed scheduling hint."""
    cursor,horizon,finished,cycle_revision=progress.get(key,(None,None,False,revision))
    if finished:
        if cycle_revision==revision:return []
        cursor=horizon=None;cycle_revision=revision
    if horizon is None:
        cycle_revision=revision
        horizon=life.db.execute('SELECT lo,hi,rowid FROM candidate_pending_proofs WHERE '+where+
            ' ORDER BY lo DESC,hi DESC,rowid DESC LIMIT 1',args).fetchone()
    if horizon is None:
        progress[key]=(None,None,True,revision)
        return []
    after='' if cursor is None else ' AND (lo,hi,rowid)>(?,?,?)'
    rows=life.db.execute('SELECT rowid,* FROM candidate_pending_proofs WHERE '+where+
        ' AND (lo,hi,rowid)<=(?,?,?)'+after+' ORDER BY lo,hi,rowid LIMIT ?',
        (*args,*horizon,*(cursor or ()),limit)).fetchall()
    last=None if not rows else (rows[-1][3],rows[-1][4],rows[-1][0])
    finished=len(rows)<limit or last==horizon
    # A relevant commit behind an active cursor must receive another horizon,
    # even if no notification follows its final ACK. Do not reset active pages
    # on each arrival: that would starve their retained tail.
    progress[key]=(None,None,cycle_revision==revision,revision) if finished else (last,horizon,False,cycle_revision)
    return rows


def _proof_selection(life,current_generation,revision):
    """Reuse durable queues; never let publisher progress select consumer work."""
    stamp=digest(current_generation)
    if getattr(life,'_proof_delivery_generation',None)!=stamp:
        life._proof_delivery_generation=stamp;life._proof_delivery_progress={}
    base=dict(life._proof_delivery_progress);progress=dict(base);selected={}
    def add(rows):
        for row in rows:
            if len(selected)<64:selected.setdefault(row[1],row)
    startup=life.db.execute('SELECT session,released FROM prewarm_startup WHERE id=1').fetchone()
    feeds=[] if startup is None else life.db.execute(
        'SELECT family,lo,hi FROM prewarm_startup_feeds WHERE session=? ORDER BY family',(startup[0],)).fetchall()
    feeds=[row for row in feeds if row[0] in ('pump','pumpswap')]
    if startup and not startup[1]:
        for family,lo,hi in feeds:
            add(life.db.execute('SELECT rowid,* FROM candidate_pending_proofs WHERE scope=? AND lo<=? AND hi>=? '
                'ORDER BY lo DESC,hi DESC,rowid DESC LIMIT 1',(program_scope(family),lo,hi)).fetchall())
    # The existing acquisition index supplies its priority/deadline head. Wait
    # queues reuse their existing bounded, fair rowid slices; no population EDF
    # sort, new work store, renewed deadline or provider acquisition is added.
    now=life.clock();demands=[]
    # Seven fixed priority heads use acquisition_priority directly; merging at
    # most56 rows preserves the existing <=2 / EDF ordering without a full
    # CASE-sort of the acquisition population.
    for priority in range(7):
        demands.extend(life.db.execute("SELECT family,address,lo,hi,priority,deadline FROM acquisition_jobs "
            "WHERE status='pending' AND priority=? AND deadline>? AND "+active_sql('family',solana=True)+
            " ORDER BY deadline,created LIMIT 8",(priority,now)))
    for table in ('rolling_publication_waits','rolling_boundary_waits'):
        key='wait:'+table
        columns=('family,address,lo,hi,priority,deadline' if table=='rolling_publication_waits'
            else 'family,address,observed_slot,upper_slot,priority,deadline')
        rows=life.history.rolling.pending_slice(table,columns,limit=4,after=progress.get(key,0))
        progress[key]=rows[-1][0] if rows else 0
        demands.extend(row[1:] for row in rows)
    demands=sorted((row for row in demands if row[0] in ('pump','pumpswap') and row[5]>now),
        key=lambda row:(row[4] if row[4]<=2 else 3,row[5],row[4],row[0],row[1],row[2],row[3]))[:8]
    deadline=min((row[5] for row in demands),default=None)
    for family,address,lo,hi,priority,due in demands:
        for scope in dict.fromkeys((life.history.scope_for(family,address),program_scope(family))):
            # Select an actual covering predecessor: the greatest lower bound
            # alone can be a short noncovering interval. Scope/range predicates
            # use the existing interval index; each demand returns at most two
            # witnesses and never decodes the retained proof population.
            prior=life.db.execute('SELECT rowid,* FROM candidate_pending_proofs WHERE scope=? AND lo<=? AND hi>=? '
                'ORDER BY lo DESC,hi DESC,rowid DESC LIMIT 1',(scope,lo,lo)).fetchone()
            if prior:add((prior,))
            add(life.db.execute('SELECT rowid,* FROM candidate_pending_proofs WHERE scope=? AND lo>=? AND lo<=? '
                'ORDER BY lo,hi,rowid LIMIT 1',(scope,lo,hi)).fetchall())
    # The two current native program tails cannot queue behind pre-start stock.
    # Their independent horizons still revisit every blocked current proof.
    for index,(family,lo,hi) in enumerate(feeds):
        slots=max(1,(63-len(selected))//max(1,len(feeds)-index))
        add(_proof_page(life,progress,'tail:'+family,'scope=? AND lo>=?',(program_scope(family),lo),slots,revision))
    # Reserve one retained proof when current feeds exist, and use all remaining
    # capacity otherwise. Never advance a page past rows dropped by the cap.
    retained_limit=1 if feeds else 64-len(selected)
    if retained_limit:add(_proof_page(life,progress,'retained',active_scope_sql('scope'),(),retained_limit,revision))
    more=any(isinstance(value,tuple) and not value[2] for value in progress.values())
    return list(selected.values()),dict(generation=stamp,revision=revision,base=base,next=progress,more=more),deadline


def _capture_cost(function):
    owner=measured('owner.delivery_capture')(function)
    @wraps(function)
    def call(life,*args,**kwargs):
        return (function if isinstance(life,_CaptureReader) else owner)(life,*args,**kwargs)
    return call


@boundary('candidate_delivery.capture',lambda life:life.writer.path)
@_capture_cost
def capture(life,*,revision=None,schedule=False):
    """Capture consumer work; the runtime also requests ACKed scheduling turns.

    Direct consumer callers retain the original None-when-no-write-work
    contract. The one independent runtime consumer explicitly requests
    publication-only and blocked-page progress, without opening a writer.
    """
    actor=isinstance(life,_CaptureReader)
    if life.db.in_transaction and not actor:raise EvidenceUnavailable('candidate_consumer_before_canonical_commit')
    if actor and not life.db.in_transaction:raise EvidenceUnavailable('candidate_delivery_capture_transaction_required')
    rows=[];size=0;references={}
    for full in life.db.execute('''SELECT id,family,address,kind,body,hash,created,
        body -> '$.record.identity',body -> '$.record.slot',body -> '$.available' FROM candidate_history_outbox
        WHERE '''+active_sql('family',solana=True)+''' AND consumed IS NULL ORDER BY priority,created,rowid LIMIT 64'''):
        row=full[:7]
        row_bytes=len(row[4].encode())
        if size+row_bytes>MAX_BYTES:
            if not rows:raise EvidenceUnavailable('candidate_delivery_input_capacity')
            break
        size+=row_bytes;rows.append(row)
        # JSON text extraction preserves the original numeric lexeme. SQLite's
        # json_extract can round a real epoch timestamp or coerce a large
        # integer; either changes the exact consumer acknowledgement bytes.
        # Decode only these bounded scalars, never the full economic payload.
        references[row[0]]=tuple(None if value is None else json.loads(value) for value in full[7:])
    # The owner turn or explicit read transaction keeps these binding reads
    # coherent. Reuse the first lookup for each key, including a missing one.
    # ACK independently rereads the current binding after the consumer commits.
    bindings={}
    for _,family,address,*_ in rows:
        key=(family,address)
        if key not in bindings:
            bindings[key]=life.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',
                key).fetchone()
    current_generation=generation(life)
    if revision is None:revision=getattr(life.history,'_history_delivery_revision',0)
    if actor and life._proof_delivery_generation!=digest(current_generation):
        life._consumer_refresh_cursor=0;life._consumer_refresh_horizon=None;life._consumer_refresh_revision=None
    raw_proofs,scan,proof_deadline=_proof_selection(life,current_generation,revision)
    proofs=[];publication_ids=[];overflow=False
    consumer=None
    with closing(readonly_history(life.path)) if life.path.exists() else closing(SimpleNamespace(close=lambda:None)) as shared:
        consumer=getattr(shared,'db',None)
        has_receipts=consumer is not None and consumer.execute("SELECT 1 FROM sqlite_master WHERE name='source_receipts'").fetchone()
        for row in raw_proofs:
            if life.unconsumed(row[2],through=row[4]):continue
            proof=proof_receipt(life,row);proof_bytes=len(canonical(proof).encode())
            if size+proof_bytes>MAX_BYTES:
                if not rows and not proofs and not publication_ids:raise EvidenceUnavailable('candidate_delivery_input_capacity')
                overflow=True;break
            size+=proof_bytes
            receipt=None if not has_receipts else consumer.execute('SELECT body,hash FROM source_receipts WHERE id=?',
                ('coverage:'+row[1],)).fetchone()
            verified=False
            if receipt is not None:
                if hashlib.sha256(receipt[0].encode()).hexdigest()!=receipt[1]:raise EvidenceUnavailable('candidate_delivery_receipt_corrupt')
                verified=digest(json.loads(receipt[0]))==digest(proof)
            if not verified:proofs.append(proof)
            # Already durable proofs need exact owner publication too, without
            # another consumer fsync or waiting for its unrelated fair cursor.
            publication_ids.append(row[1])
    if overflow:scan['next']=scan['base'];scan['more']=True
    refresh=[];refresh_scan=None
    if getattr(life,'_consumer_refresh_requested',False):
        cursor=getattr(life,'_consumer_refresh_cursor',0)
        active=active_sql('family',solana=True)+" AND state IN ('queued','warming','active')"
        horizon=getattr(life,'_consumer_refresh_horizon',None) if actor else None
        if actor and horizon is None:
            # The table's rowid head bounds arrivals without sorting/scanning
            # the lifecycle population to find a separate active maximum.
            horizon=life.db.execute('SELECT MAX(rowid) FROM candidate_lifecycle').fetchone()[0] or 0
            life._consumer_refresh_horizon=horizon
            # EOF authenticates this entire fixed sweep. A newer page hint
            # cannot erase a change behind an already ACKed rowid cursor.
            life._consumer_refresh_revision=revision
        bound='' if horizon is None else ' AND rowid<=?'
        for rowid,family,address,state,deadline in life.db.execute('SELECT rowid,family,address,state,deadline FROM candidate_lifecycle WHERE '+
                active+' AND rowid>?'+bound+' ORDER BY rowid LIMIT 64',(cursor,*(() if horizon is None else (horizon,)))):
            promotion=life.db.execute("SELECT id FROM candidate_history_outbox WHERE family=? AND address=? AND kind='promotion' ORDER BY created DESC,rowid DESC LIMIT 1",(family,address)).fetchone()
            refresh.append((rowid,family,address,state,deadline,promotion))
        if actor:
            refresh_scan=dict(token=life.hint.refresh_token,revision=life._consumer_refresh_revision,
                finished=len(refresh)<64 or bool(refresh and refresh[-1][0]==horizon))
        elif not refresh:life._consumer_refresh_requested=False;life._consumer_refresh_cursor=0
    if not rows and not proofs and not refresh:
        scan_work=bool(raw_proofs) or scan['more']
        if not schedule or not publication_ids and not scan_work and proof_deadline is None and refresh_scan is None:return None
    snapshot=dict(rows=rows,bindings=bindings,references=references,proofs=proofs,generation=current_generation,
        refresh=refresh,publication_ids=publication_ids,proof_scan=scan,proof_deadline=proof_deadline,
        at=life.clock(),canonical_path=str(life.writer.path.resolve()),candidate_path=str(life.path.resolve()))
    if actor:snapshot.update(capture_actor=True,refresh_scan=refresh_scan)
    return snapshot


@boundary('candidate_delivery.deliver',lambda snapshot:snapshot['candidate_path'])
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
    # deliver_rows already owns the necessary schema/open and FULL commit,
    # including when rows is empty. An empty proof/refresh phase needs no
    # second schema pass or writer lock. Necessary second-phase failures keep
    # their original transaction, exception and replay behavior.
    if snapshot['proofs'] or snapshot['refresh']:
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


@boundary('candidate_delivery.acknowledge',lambda life,snapshot,result:life.writer.path)
@measured('owner.delivery_ack')
def acknowledge(life,snapshot,result):
    if digest(generation(life))!=digest(snapshot['generation']):return False
    # Verify durable consumer receipts and unchanged outbox obligations before
    # the canonical owner marks even one delivery consumed. A crash repeats the
    # exact batch; CandidateHistory identities retain their old idempotency.
    if snapshot['rows']:
        with closing(diagnostic_connect(life.path.resolve().as_uri()+'?mode=ro',diagnostic_role='candidate_delivery.ack_read',uri=True,timeout=0)) as db:
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
    if acknowledgements:life.acknowledge_rows(acknowledgements)
    refreshed=result['refreshed']
    if [r[0] for r in refreshed]!=[r[0] for r in snapshot['refresh']]:
        raise EvidenceUnavailable('candidate_refresh_ack_order')
    if snapshot['refresh']:
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
    if snapshot['refresh'] and not snapshot.get('capture_actor'):life._consumer_refresh_cursor=snapshot['refresh'][-1][0]
    scan=snapshot.get('proof_scan')
    if not snapshot.get('capture_actor') and scan and getattr(life,'_proof_delivery_generation',None)==scan['generation'] and getattr(life,'_proof_delivery_progress',{})==scan['base']:
        life._proof_delivery_progress=dict(scan['next'])
    return True


def acknowledge_actor(life,snapshot,result):
    """Owner ACK plus conservative refresh EOF feedback, no reader authority."""
    from .solana_history_notifications import delivery_hint
    if not snapshot.get('capture_actor'):raise EvidenceUnavailable('candidate_delivery_actor_snapshot_required')
    entered=delivery_hint(life.history);refresh=snapshot.get('refresh_scan')
    clear=bool(refresh and refresh['finished'] and entered.refresh_requested
        and entered.refresh_token==refresh['token'] and entered.revision==refresh['revision'])
    accepted=acknowledge(life,snapshot,result)
    if accepted and clear:
        life._consumer_refresh_requested=False;life._consumer_refresh_cursor=0
    return ActorAck(accepted,delivery_hint(life.history),accepted and clear)


def readonly_history(path):
    db=diagnostic_connect(Path(path).resolve().as_uri()+'?mode=ro',diagnostic_role='candidate_delivery.history_read',uri=True,timeout=0)
    try:db.execute('PRAGMA query_only=ON')
    except BaseException:
        db.close();raise
    return SimpleNamespace(db=db,close=db.close)
