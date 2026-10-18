"""One guarded qualified program interval, never callback or NORMAL authority.

The protected caller acquires original stopped/apply fences and the absolute
request clock. This module neither acquires those premises from JSON nor opens
a database/provider. All SQL handles and provider operations are the original
native ones supplied by that caller. Short readonly scopes close before work.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
import sqlite3
import stat
import threading
import time

from .normal_boot_record import canonical,digest,hex_value,require
from .normal_source_recovery import verify_qualified_recovery_target

TABLE='qualified_source_program_recovery'
MAX_BODY=16384
MAX_PAGES=100000
MAX_INPUT_BYTES=32*1024*1024
PROVIDER_CLOSING_SECONDS=30
_ISSUER=object()
JOB_COLUMNS=('id','family','address','lo','hi','priority','deadline','status','token',
    'pages','last_slot','last_index','lineage','created','updated','error')


class QualifiedProgramRecoveryRun:
    """Detached input binding tethered to the caller's still-owned apply fence.

    ``rejoin`` must open fresh original readonly scopes, rederive the actual
    source target/financial replay, and close them before returning its value.
    The code-pinned protected adapter owns that premise, not this callback's
    returned Boolean. There is no inherited short SQL connection here.
    """
    __slots__=('_value','_sha','_owner','_guard','_rejoin','_cancelled','_deadline','_request','_closed',
        '_rejoins','_rejoin_seconds','_source_path','_source_identity','_known_upper')
    def __init__(self,value,guard,rejoin,deadline,request,cancelled,source_path,known_upper,*,_issuer=None):
        require(_issuer is _ISSUER,'qualified_run_private_issuer')
        self._value=deepcopy(value);self._sha=digest(value)
        self._owner=(os.getpid(),threading.get_ident())
        self._guard=guard;self._rejoin=rejoin;self._cancelled=cancelled
        self._deadline=deadline;self._request=deepcopy(request);self._closed=False
        self._rejoins=0;self._rejoin_seconds=0.
        self._source_path=source_path
        info=source_path.lstat();require(stat.S_ISREG(info.st_mode),'qualified_run_source_identity')
        self._source_identity=(info.st_dev,info.st_ino)
        self._known_upper=known_upper

    def __setattr__(self,name,value):
        require(not hasattr(self,name),'qualified_run_immutable')
        object.__setattr__(self,name,value)

    @property
    def deadline(self):return self._deadline
    @property
    def request(self):return deepcopy(self._request)
    @property
    def rejoins(self):return self._rejoins
    @property
    def rejoin_seconds(self):return self._rejoin_seconds

    def guard(self):
        require(not self._closed and self._owner==(os.getpid(),threading.get_ident()),'qualified_run_owner')
        require(self._cancelled() is False,'qualified_run_cancelled')
        require(time.monotonic()<self.deadline,'qualified_run_deadline')
        require(self._guard() is None,'qualified_run_guard')
        info=self._source_path.lstat()
        require(stat.S_ISREG(info.st_mode) and (info.st_dev,info.st_ino)==self._source_identity,
            'qualified_run_source_identity')
        require(time.monotonic()<self.deadline and self._cancelled() is False,'qualified_run_deadline')

    def check(self):
        self.guard();started=time.monotonic()
        value=self._rejoin()
        require(digest(value)==self._sha,'qualified_run_inputs_changed')
        object.__setattr__(self,'_rejoins',self._rejoins+1)
        object.__setattr__(self,'_rejoin_seconds',self._rejoin_seconds+time.monotonic()-started)
        self.guard()

    def before_provider(self):
        self.guard()
        require(time.monotonic()<self.deadline-PROVIDER_CLOSING_SECONDS,
            'qualified_run_provider_closing_reserve')

    def close(self):
        require(self._owner==(os.getpid(),threading.get_ident()),'qualified_run_owner')
        object.__setattr__(self,'_closed',True)

    def __reduce__(self):raise TypeError('qualified_run_is_process_private')


def detach_qualified_program_run(target,*,validate_fences,rejoin,deadline,request,cancelled=lambda:False):
    """Only the protected caller may supply actual fences/request and rejoin.

    Validate while the original target's short scope remains open. That scope
    must close before this run is used for providers or an EvidenceWriter.
    """
    verify_qualified_recovery_target(target)
    require(callable(validate_fences) and callable(rejoin) and callable(cancelled),'qualified_run_guard')
    require(type(deadline) in (int,float) and math.isfinite(deadline)
        and time.monotonic()<deadline<=time.monotonic()+120,'qualified_run_window')
    require(type(request) is dict and set(request)=={'request_id','application_commit',
        'application_tree','administration_commit','epoch_id','inception_sha256'},'qualified_run_request')
    value=target.value()
    require(request['epoch_id']==value['epoch_id'] and request['inception_sha256']==value['inception_sha256'],
        'qualified_run_epoch')
    # A crash need not have a terminal census. Its real same-COMMIT plane
    # observations remain a lower bound for any freshly finalized upper,
    # independently of the retained failed handler's own slot.
    from . import normal_source_registry as registry
    with target._context.database(target._context.root/'shared/solana-evidence.sqlite') as db:
        row=db.execute('SELECT CASE WHEN octet_length(body)<=? THEN body END,'
            'CASE WHEN octet_length(hash)=64 THEN hash END FROM '+registry.GENERATION_TABLE+
            ' WHERE id=?',(registry.MAX_BODY,value['generation'])).fetchone()
        require(row is not None,'qualified_run_registry_missing')
        generation=registry._validate_generation(registry._read(*row))
        require(digest(generation)==value['registry_sha256'],'qualified_run_registry_changed')
        known_upper=max((point['last_slot'] or 0 for point in generation['planes'].values()),default=0)
    run=QualifiedProgramRecoveryRun(value,validate_fences,rejoin,deadline,request,cancelled,
        target._context.root/'shared/solana-evidence.sqlite',known_upper,_issuer=_ISSUER)
    target._context.verify_boundary();run.guard()
    return run


def _run(value):
    require(type(value) is QualifiedProgramRecoveryRun,'qualified_run_required')
    value.guard();return value


def selection(run):
    run=_run(run)
    rows=[row for row in run._value['obligations'] if row['kind']=='CANONICAL_INTERVAL_DELIVERY_AND_PROOF'
        and row['scope'] in ('program:pump','program:pumpswap')]
    require(rows,'qualified_program_interval_missing')
    scope=min(row['scope'] for row in rows);rows=[row for row in rows if row['scope']==scope]
    require(scope in run._value['active_programs'],'qualified_program_not_active')
    lower=min(row['lower_slot'] for row in rows)
    require(type(lower) is int and lower>0,'qualified_program_lower')
    known=max(run._known_upper,max((row['retained_upper_slot'] or 0 for row in rows),default=0))
    for frontier in (run._value['initial_frontiers'],run._value['retained_frontiers']):
        point=None if frontier is None else frontier['programs'][scope.split(':')[1]]
        if point is not None:known=max(known,point[0])
        if frontier is not None:known=max(known,frontier['control_slot'] or 0)
    return scope,lower,max(lower,known)


def _read(db,identity):
    row=db.execute('SELECT CASE WHEN octet_length(body)<=? THEN body END,'
        'CASE WHEN octet_length(hash)=64 THEN hash END FROM '+TABLE+' WHERE id=?',(MAX_BODY,identity)).fetchone()
    if row is None:return None
    require(type(row[0]) is str and hex_value(row[1],64)
        and hashlib.sha256(row[0].encode()).hexdigest()==row[1],'qualified_program_record')
    value=json.loads(row[0]);require(type(value) is dict,'qualified_program_record')
    return value


def _job(db,descriptor):
    bounds={'id':64,'family':16,'address':128,'status':32,'token':MAX_BODY,'lineage':64,'error':MAX_BODY}
    columns=','.join(('CASE WHEN octet_length('+key+')<='+str(bounds[key])+' THEN '+key+' END')
        if key in bounds else key for key in JOB_COLUMNS)
    row=db.execute('SELECT '+columns+',token IS NULL FROM acquisition_jobs WHERE id=?',
        (descriptor['job_id'],)).fetchone()
    require(row is not None,'qualified_program_job_missing')
    job=dict(zip(JOB_COLUMNS,row[:-1]))
    require(job['token'] is not None or row[-1]==1,'qualified_program_job_changed')
    require((job['family'],job['address'],job['lo'],job['hi'])==
        (descriptor['family'],descriptor['address'],descriptor['lower_slot'],descriptor['upper_slot'])
        and job['id']==descriptor['job_id'] and job['deadline']==descriptor['original_job_deadline']
        and job['status'] in ('pending','complete'),'qualified_program_job_changed')
    require(type(job['pages']) is int and 0<=job['pages']<=MAX_PAGES and hex_value(job['lineage'],64)
        and (job['token'] is None or type(job['token']) is str and 0<len(job['token'].encode())<=MAX_BODY),
        'qualified_program_job_changed')
    # No revival of an expired/failed/deadline_missed original job.
    require(type(job['deadline']) in (int,float) and math.isfinite(job['deadline'])
        and (job['status']=='complete' or time.time()<job['deadline']),
        'qualified_program_original_job_expired')
    return job


def _bound_descriptor(run,db,descriptor):
    from meme_machine.solana_evidence_plane import digest as native_digest
    from meme_machine.solana_selective_history import PROGRAMS
    require(type(descriptor) is dict and hex_value(descriptor.get('id'),64),'qualified_program_record')
    actual=_read(db,descriptor['id']);scope,lower,minimum=selection(run);family=scope.split(':')[1]
    require(actual is not None and actual==descriptor and actual['schema']=='qualified-source-program-target-v1'
        and actual['id']==digest(['qualified-source-program-target-v1',run._value['generation'],scope])
        and actual['target_sha256']==run._sha and actual['scope']==scope
        and actual['lower_slot']==lower and type(actual['upper_slot']) is int and minimum<=actual['upper_slot']<2**63
        and actual['family']==family and actual['address']==PROGRAMS[family]
        and actual['job_id']==native_digest([family,PROGRAMS[family],lower,actual['upper_slot']]),
        'qualified_program_target_changed')
    for key in ('generation','identity_sha256','failed_raw_sha256','registry_sha256','provider_identity',
            'epoch_id','inception_sha256','native_clock_sha256'):
        require(actual[key]==run._value[key],'qualified_program_target_changed')
    require(actual['upper_method']=='getSlot' and actual['upper_commitment']=='finalized'
        and type(actual['upper_observed_at']) in (int,float) and math.isfinite(actual['upper_observed_at'])
        and all(actual[key] is False for key in ('whole_generation_recovered','original_callback_completion',
            'historical_handler_disposition_verified','funding_authority','safe_for_normal')),
        'qualified_program_target_changed')
    return actual


def prepare(run,history,rpc):
    """The original RPC validates network and obtains the real finalized upper."""
    from meme_machine.solana_selective_history import PROGRAMS
    run=_run(run);run.check()
    scope,lower,minimum=selection(run);family=scope.split(':')[1]
    require(history.endpoint_identity==run._value['provider_identity'],'qualified_program_endpoint')
    run.before_provider();rpc.validate_network();run.check()
    run.before_provider();upper=rpc.call('getSlot',[dict(commitment='finalized')],False);run.check()
    require(type(upper) is int and minimum<=upper<2**63,'qualified_program_finalized_upper')
    identity=digest(['qualified-source-program-target-v1',run._value['generation'],scope])
    with history.writer.transaction():
        history.db.execute('CREATE TABLE IF NOT EXISTS '+TABLE+
            '(id TEXT PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL)')
        descriptor=_read(history.db,identity)
        if descriptor is None:
            from meme_machine.solana_evidence_plane import digest as native_digest
            job_id=native_digest([family,PROGRAMS[family],lower,upper])
            prior=history.db.execute('SELECT deadline,status FROM acquisition_jobs WHERE id=?',(job_id,)).fetchone()
            if prior is not None:
                require(prior[1] in ('pending','complete') and prior[0]>time.time(),
                    'qualified_program_original_job_expired')
            job_deadline=(time.time()+max(0,run.deadline-time.monotonic())) if prior is None else prior[0]
            descriptor=dict(schema='qualified-source-program-target-v1',id=identity,target_sha256=run._sha,
                generation=run._value['generation'],identity_sha256=run._value['identity_sha256'],
                failed_raw_sha256=run._value['failed_raw_sha256'],registry_sha256=run._value['registry_sha256'],
                provider_identity=history.endpoint_identity,epoch_id=run._value['epoch_id'],
                inception_sha256=run._value['inception_sha256'],native_clock_sha256=run._value['native_clock_sha256'],
                scope=scope,family=family,address=PROGRAMS[family],lower_slot=lower,upper_slot=upper,
                upper_method='getSlot',upper_commitment='finalized',upper_observed_at=time.time(),
                request=deepcopy(run.request),job_id=job_id,original_job_deadline=job_deadline,
                whole_generation_recovered=False,original_callback_completion=False,
                historical_handler_disposition_verified=False,funding_authority=False,safe_for_normal=False)
            raw=canonical(descriptor);require(len(raw)<=MAX_BODY,'qualified_program_record_bound')
            history.db.execute('INSERT INTO '+TABLE+' VALUES(?,?,?)',
                (identity,raw.decode(),hashlib.sha256(raw).hexdigest()))
            require(history.request(family,PROGRAMS[family],lower,upper,priority=1,deadline=job_deadline)==job_id,
                'qualified_program_job_identity')
        require(descriptor['target_sha256']==run._sha and descriptor['scope']==scope
            and descriptor['lower_slot']==lower and minimum<=descriptor['upper_slot']<=upper,
            'qualified_program_target_changed')
        _bound_descriptor(run,history.db,descriptor);_job(history.db,descriptor)
    run.check();return descriptor


def advance_page(run,history,rpc,descriptor):
    """One original bounded archive page and its genuine transaction receipt."""
    from meme_machine.solana_selective_history import (missing_archive_log_transactions,
        join_archive_log_supplement,archive_page_evidence)
    from meme_machine.solana_evidence_plane import canonical as native_canonical
    run=_run(run);run.check();descriptor=_bound_descriptor(run,history.db,descriptor);job=_job(history.db,descriptor)
    if job['status']=='complete':return False
    config=dict(transactionDetails='full',sortOrder='asc',limit=100,commitment='finalized',
        encoding='json',maxSupportedTransactionVersion=1,
        filters=dict(slot=dict(gte=job['lo'],lte=job['hi'])))
    if job['token'] is not None:config['paginationToken']=job['token']
    run.before_provider();page,delivered=rpc.call_delivered('getTransactionsForAddress',[job['address'],config],1)
    run.check();supplements=[];size=0
    for transaction in missing_archive_log_transactions(job['family'],page):
        run.check();signature=transaction['transaction']['signatures'][0]
        run.before_provider();full,_=rpc.call_delivered('getTransaction',[signature,dict(commitment='finalized',
            encoding='json',maxSupportedTransactionVersion=1)],1)
        size+=len(native_canonical(full).encode())
        require(size<=16*1024*1024,'qualified_program_supplement_bound')
        supplements.append(join_archive_log_supplement(transaction,full,endpoint_identity=history.endpoint_identity))
    run.check();expected=archive_page_evidence(job,page,endpoint_identity=history.endpoint_identity,
        supplements=tuple(supplements),supplemented_before=history.has_archive_log_supplements(job['id']))
    with history.writer.transaction():
        before=_observed_cursors(history.db)
        result=history.commit_page(job,page,finalized_through=descriptor['upper_slot'],supplements=tuple(supplements))
        after=_observed_cursors(history.db)
        for scope in before.keys()|after.keys():
            prior,current=before.get(scope),after.get(scope)
            if scope!=descriptor['scope']:
                require(current==prior,'qualified_program_other_cursor_changed')
            elif current!=prior:
                slots=[transaction['slot'] for transaction in page['data']]
                require(current is not None and slots and (prior is None or current[0]>=prior[0])
                    and current[0]<=max(slots+([] if prior is None else [prior[0]])),
                    'qualified_program_page_cursor_mismatch')
        actual=_job(history.db,descriptor)
        row=history.db.execute('SELECT input_hash,result FROM acquisition_page_receipts WHERE job=? AND page=?',
            (job['id'],job['pages'])).fetchone()
        require(actual['pages']==job['pages']+1 and actual['lineage']==expected['lineage_hash']
            and row is not None and row[0]==expected['input_hash'] and json.loads(row[1])==result,
            'qualified_program_page_receipt')
    run.check();return True


def _observed_cursors(db):
    rows=db.execute('SELECT CASE WHEN octet_length(scope)<=256 THEN scope END,slot,updated '
        'FROM cursors ORDER BY scope LIMIT 513').fetchall()
    require(len(rows)<=512,'qualified_program_cursor_bound')
    require(all(type(scope) is str and scope and type(slot) is int and 0<=slot<2**63
        and type(updated) in (int,float) and math.isfinite(updated) for scope,slot,updated in rows),
        'qualified_program_cursor_bound')
    return {scope:(slot,updated) for scope,slot,updated in rows}


def job_proof(history,descriptor):
    from meme_machine.solana_selective_history import archive_interval_witness
    from meme_machine.solana_evidence_plane import digest as native_digest
    job=_job(history.db,descriptor)
    if job['status']!='complete':return job,None,None
    scope=history.scope_for(job['family'],job['address'])
    witness=archive_interval_witness(job,scope,job['lineage'],
        supplemented=history.has_archive_log_supplements(job['id']))
    return job,native_digest([scope,job['lo'],job['hi'],witness]),witness


def deliver_once(run,history,descriptor):
    """Original consumer FULL, verified canonical ACK and exact publication."""
    from meme_machine.solana_history_delivery import capture,deliver,acknowledge,proof_receipt,MAX_BYTES
    run=_run(run);run.check();descriptor=_bound_descriptor(run,history.db,descriptor)
    job,proof_id,witness=job_proof(history,descriptor)
    require(proof_id is not None,'qualified_program_archive_pending')
    life=history.lifecycle;snapshot=capture(life,schedule=True)
    if snapshot is None:return False
    row=history.db.execute('SELECT rowid,* FROM candidate_pending_proofs WHERE id=?',(proof_id,)).fetchone()
    proofs=[];publications=[]
    if row is not None and not life.unconsumed(row[2],through=row[4]):
        proof=proof_receipt(life,row)
        if sum(len(item[4].encode()) for item in snapshot['rows'])+len(canonical(proof))<=MAX_BYTES:
            proofs=[proof];publications=[proof_id]
    scan=snapshot.get('proof_scan')
    snapshot=dict(snapshot,proofs=proofs,publication_ids=publications,refresh=[],proof_deadline=None,
        proof_scan=None if scan is None else dict(scan,next=scan['base'],more=False))
    run.check();result=deliver(snapshot);run.check()
    require(acknowledge(life,snapshot,result),'qualified_program_full_ack')
    run.check();life.publish(proof_ids=publications);run.check()
    return bool(snapshot['rows'] or proofs or publications)


def verify_program_interval(run,source_db,consumer_db,identity):
    previous=[]
    try:
        for db in (source_db,consumer_db):
            old=db.getlimit(sqlite3.SQLITE_LIMIT_LENGTH);previous.append((db,old))
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,min(old,MAX_INPUT_BYTES))
        value=_verify_program_interval(run,source_db,consumer_db,identity)
    finally:
        for db,old in reversed(previous):db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,old)
    _run(run).guard();return value


def _verify_program_interval(run,source_db,consumer_db,identity):
    """Constructor-free rejoin of original page, FULL and published proof rows.

    The caller owns fresh query-only transactions and their original inode/
    physical fences. This verifies only the selected finite program interval.
    """
    from types import SimpleNamespace
    from meme_machine.solana_selective_history import archive_interval_witness,coverage_points
    from meme_machine.solana_evidence_plane import digest as native_digest
    run=_run(run);run.check()
    require(source_db.in_transaction and consumer_db.in_transaction
        and source_db.execute('PRAGMA query_only').fetchone()==(1,)
        and consumer_db.execute('PRAGMA query_only').fetchone()==(1,),'qualified_program_read_snapshot')
    descriptor=_read(source_db,identity)
    descriptor=_bound_descriptor(run,source_db,descriptor)
    job=_job(source_db,descriptor)
    require(job['status']=='complete' and job['token'] is None and 0<job['pages']<=MAX_PAGES,
        'qualified_program_archive_pending')
    count=0;size=0;supplemented=False;chain='0'*64
    for page,checksum,raw in source_db.execute('SELECT page,CASE WHEN octet_length(input_hash)=64 THEN input_hash END,'
            'CASE WHEN octet_length(result)<=? THEN result END FROM acquisition_page_receipts WHERE job=? ORDER BY page',
            (MAX_BODY,job['id'])):
        run.guard();require(page==count and type(raw) is str and hex_value(checksum,64),'qualified_program_page_lineage')
        size+=len(raw.encode())+64;require(size<=MAX_INPUT_BYTES,'qualified_program_receipt_bound')
        result=json.loads(raw)
        require(type(result) is dict and result.get('pages')==page+1 and type(result.get('records')) is int
            and result['records']>=0 and result.get('complete') is (page+1==job['pages']),
            'qualified_program_page_lineage')
        supplemented=supplemented or bool(result.get('archive_log_supplements'))
        chain=digest([chain,page,checksum,result]);count+=1
    require(count==job['pages'],'qualified_program_page_lineage')
    from meme_machine.solana_rolling_history import program_scope
    scope=program_scope(job['family'])
    witness=archive_interval_witness(job,scope,job['lineage'],supplemented=supplemented)
    proof_id=native_digest([scope,job['lo'],job['hi'],witness])
    require(source_db.execute('SELECT 1 FROM candidate_pending_proofs WHERE id=?',(proof_id,)).fetchone() is None,
        'qualified_program_proof_pending')
    from meme_machine.solana_candidate_lifecycle import CandidateLifecycle
    life=object.__new__(CandidateLifecycle);life.db=source_db;life.history=SimpleNamespace()
    require(not life.unconsumed(scope,through=job['hi']),'qualified_program_consumer_pending')
    row=consumer_db.execute('SELECT CASE WHEN octet_length(body)<=? THEN body END,'
        'CASE WHEN octet_length(hash)=64 THEN hash END '
        'FROM source_receipts WHERE id=?',(128*1024,'coverage:'+proof_id)).fetchone()
    require(row is not None and type(row[0]) is str and hashlib.sha256(row[0].encode()).hexdigest()==row[1],
        'qualified_program_consumer_receipt')
    body=json.loads(row[0])
    session=source_db.execute('SELECT session FROM prewarm_startup WHERE id=1').fetchone()
    expected_generation=(session,descriptor['provider_identity'],*run._source_identity)
    require(body.get('identity')==proof_id and body.get('scope')==scope and body.get('witness')==witness
        and body.get('lo')==job['lo'] and body.get('hi')==job['hi']
        and body.get('endpoint')==descriptor['provider_identity']
        and digest(body.get('generation'))==digest(expected_generation),'qualified_program_consumer_receipt')
    covered=False
    for packed,checksum in source_db.execute('SELECT CASE WHEN length(points)<=1048576 THEN points END,'
            'CASE WHEN octet_length(hash)=64 THEN hash END FROM candidate_coverage WHERE scope=? AND lo<=? AND hi>=?',
            (scope,job['lo'],job['hi'])):
        run.guard();require(type(packed) is bytes and hex_value(checksum,64),'qualified_program_receipt_bound')
        size+=len(packed)+64;require(size<=MAX_INPUT_BYTES,'qualified_program_receipt_bound')
        covered=covered or any(lo==job['lo'] and hi==job['hi'] for lo,hi,at in coverage_points(packed,checksum))
    require(covered,'qualified_program_publication_missing')
    value=dict(schema='qualified-source-program-recovery-receipt-v1',state='ECONOMIC_INTERVAL_RECOVERED_ONLY',
        target_id=identity,target_sha256=run._sha,generation=descriptor['generation'],
        failed_raw_sha256=descriptor['failed_raw_sha256'],registry_sha256=descriptor['registry_sha256'],
        epoch_id=descriptor['epoch_id'],inception_sha256=descriptor['inception_sha256'],
        scope=scope,lower_slot=job['lo'],upper_slot=job['hi'],job_id=job['id'],
        pages=count,page_receipts_sha256=chain,lineage_sha256=job['lineage'],proof_id=proof_id,
        consumer_receipt_sha256=row[1],target_record_sha256=digest(descriptor),
        original_job_deadline=job['deadline'],deadline_renewed=False,
        economic_interval_recovered=True,whole_generation_recovered=False,
        original_callback_completion=False,historical_handler_disposition_verified=False,
        scout_nomination_history_recovered=False,native_endpoint_completion_verified=False,
        funding_authority=False,safe_for_normal=False)
    run.check();return value
