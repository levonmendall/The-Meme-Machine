"""Ownership helpers for the existing bounded source queues, not a second spool.

Closing admission and finishing a queue are separate events.  A received handler
may still be putting its last frame after the stop event has been set.
"""
import asyncio
import json
import os
import hashlib
import threading
import time

CONTROL_RECOVERY_KEY='source_control_recovery'
HANDLER_RECOVERY_KEY='source_handler_recovery'
SOURCE_DRAIN_KEY='source_drain'
SOURCE_DRAIN_BYTES=128*1024
OBSERVATION_DRAIN_KEY='source_drain_observation'
HISTORICAL_OBSERVATION_SHA256='5431d349aa8539ba935861cccb93c1f4c164bce9b0173bf4c77be7b562ffa8c9'
PROGRAM_GAP_OBSERVATION_SHA256='948743b18d0a33cc85391d07ea4a4ae9dad34110c169ca95945a04473d6db228'
PROGRAM_GAP_HANDLER_SHA256='29f00e3d71c40e1d306f50263b84f1ec25e455e20d112a5f04fdef25293d0fb0'
PROGRAM_GAP_SESSION_SHA256='886dc272c37139e53dac962fda1473fc6eca4e8b2daf462495cb50509a831333'
ECONOMIC_REPLAY_OBSERVATION_SHA256='f76e9e06964eb64dd04aefd698780a95bb98af4a852c783a8e1192c0000ca49e'
ECONOMIC_REPLAY_SESSION_SHA256='f10da79b22abdb7342ada4373ab74a235f66cc0e63ac1e8ba356ee20582cb6ac'
ECONOMIC_REPLAY_JOBS={
    'pump':(8,'ea47c379a25a70e6f34492bfcc7a592b76767a07fc6c5d9bc4733b4662958ead',
        '1dff470ee9f02e0162a43be234c8897558c22095e6964ef70d05c35b8e3d7870'),
    'pumpswap':(1,'dd220350327c4f9cf999ae355c517171b6b67c1cc71171e1f208c24ad1850955',
        '9d4886040b969985256b66010c0b593077a83fe0c5168f63b49ffbfd88303538')}
ECONOMIC_REPLAY_NATIVE_HASH='DLLkFkP5LgYop8GpGKkrcmGoFpjRnCQDMbBRJP675rTh'
ECONOMIC_REPLAY_NATIVE_CENSUS={
    'pump':'ff3fa590721311a276b5368983b65179dcdcb9663e7fe00ab1c71d022e356d8c',
    'pumpswap':'355d87eca99a64a3d7306b31ea42d8e99d13e9d2c8302a69b43c76062fda7b93'}


def _retained_health(state,key,maximum):
    return _health_from_db(state.writer.db,key,maximum)


def _health_from_db(db,key,maximum):
    from .solana_evidence_plane import EvidenceUnavailable
    row=db.execute('SELECT length(CAST(value AS BLOB)),CASE WHEN '
        'length(CAST(value AS BLOB))<=? THEN value END FROM service_health WHERE key=?',
        (maximum,key)).fetchone()
    if row is None:return None
    if (type(row[0]) is not int or not 0<=row[0]<=maximum or not isinstance(row[1],str)):
        raise EvidenceUnavailable('source_drain_retained_record_bound')
    return row[1]


def _retained_json(raw):
    from .solana_evidence_plane import EvidenceUnavailable
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError()
            result[key]=value
        return result
    try:return json.loads(raw,object_pairs_hook=unique,
        parse_constant=lambda value:(_ for _ in ()).throw(ValueError()))
    except (ValueError,TypeError,RecursionError):
        raise EvidenceUnavailable('source_drain_retained_record_corrupt') from None


def _retained_census(raw):
    from .solana_evidence_plane import EvidenceUnavailable
    body=_retained_json(raw)
    fields=('accepted_handlers','settled_handlers','pending_handlers')
    if (not isinstance(body,dict) or body.get('state') not in ('RUNNING','DRAINING','DRAINED','RECOVERY_REQUIRED')
            or any(type(body.get(key)) is not int or body[key]<0 for key in fields)
            or body['accepted_handlers']-body['settled_handlers']!=body['pending_handlers']
            or body['state']=='DRAINED' and body['pending_handlers']):
        raise EvidenceUnavailable('source_drain_retained_census_corrupt')
    return body


def _retained_handlers(raw):
    from .solana_evidence_plane import EvidenceUnavailable
    body=_retained_json(raw)
    if (not isinstance(body,dict) or body.get('version')!=1
            or not isinstance(body.get('records'),list) or len(body['records'])>HandlerLedger.maximum_records
            or any(not isinstance(row,dict) for row in body['records'])):
        raise EvidenceUnavailable('source_handler_recovery_corrupt')
    return body['records']


def _committed_census(body):
    queues=body.get('queues')
    return (body.get('terminal') is True and body.get('all_accepted_committed') is True
        and type(body.get('unpreserved_sessions')) is int and body['unpreserved_sessions']==0
        and isinstance(queues,dict) and set(queues)=={'control','scout','rolling','candidate'}
        and all(isinstance(row,dict) and all(type(row.get(key)) is int and row[key]>=0
            for key in ('accepted','committed','pending'))
            and row['accepted']==row['committed'] and row['pending']==0 for row in queues.values()))


def _historical_observation_record(db,*,check_control=True):
    from .solana_evidence_plane import EvidenceUnavailable
    raw=_health_from_db(db,SOURCE_DRAIN_KEY,SOURCE_DRAIN_BYTES)
    if raw is None or hashlib.sha256(raw.encode()).hexdigest()!=HISTORICAL_OBSERVATION_SHA256:
        raise EvidenceUnavailable('source_observation_historical_boundary_unverified')
    body=_retained_census(raw)
    if (body['state']!='RECOVERY_REQUIRED' or not _committed_census(body)
            or (body['accepted_handlers'],body['settled_handlers'],body['pending_handlers'])!=(564488,564486,2)):
        raise EvidenceUnavailable('source_observation_historical_census_unverified')
    if check_control:
        marker=_health_from_db(db,CONTROL_RECOVERY_KEY,SOURCE_DRAIN_BYTES)
        if control_recovery(marker) is not None:
            raise EvidenceUnavailable('source_observation_control_recovery_required')
    return raw


def _observation_reference(body):
    return (body.get('historical_source_drain_sha256')==HISTORICAL_OBSERVATION_SHA256
        and type(body.get('historical_unknown_handlers')) is int and body['historical_unknown_handlers']==2
        and body.get('historical_recovery_verified') is False)


def _current_observation_identity(body):
    run=body.get('run_identity');accounting=body.get('handler_accounting')
    return (isinstance(run,str) and len(run)==32 and all(c in '0123456789abcdef' for c in run)
        and type(body.get('source_pid')) is int and body['source_pid']>0
        and isinstance(accounting,dict) and accounting.get('version')==1 and accounting.get('valid') is True
        and accounting.get('run')==run and accounting.get('pid')==body['source_pid']
        and accounting.get('accepted')==body['accepted_handlers']
        and accounting.get('returned')==body['settled_handlers'] and accounting.get('records')==[])


def _preserved_program_gap_observation(db,handlers,current):
    """One unreturned rolling log stays unavailable, never retrospectively ACKed.

    LOG_BUFFER_WAIT precedes feed_log/economic queue publication in the pinned
    source. Its exact failed census and gap remain evidence, while the original
    fresh rolling/prewarm path must establish a different current interval.
    """
    from .solana_evidence_plane import EvidenceUnavailable
    from .solana_candidate_lifecycle import CandidateLifecycle
    from .solana_rolling_history import program_scope
    def require(condition):
        if not condition:raise EvidenceUnavailable('source_observation_program_gap_unverified')
    require(isinstance(handlers,str))
    if hashlib.sha256(handlers.encode()).hexdigest()!=PROGRAM_GAP_HANDLER_SHA256:
        # Later interrupted handlers append to the original ledger. Preserve
        # the original exact bytes and require its row unchanged in that ledger;
        # the caller separately proves every additional retained disposition.
        live=_retained_handlers(handlers)
        archived=_health_from_db(db,HANDLER_RECOVERY_KEY+'_preserved.'+PROGRAM_GAP_HANDLER_SHA256,
            HandlerLedger.maximum_bytes)
        require(isinstance(archived,str) and hashlib.sha256(archived.encode()).hexdigest()==PROGRAM_GAP_HANDLER_SHA256)
        old=_retained_handlers(archived);require(len(old)==1)
        require([row for row in live if (row.get('run'),row.get('id'))==
            (old[0].get('run'),old[0].get('id'))]==old)
        handlers=archived
    records=_retained_handlers(handlers);require(len(records)==1)
    raw=current if (isinstance(current,str) and hashlib.sha256(current.encode()).hexdigest()==PROGRAM_GAP_OBSERVATION_SHA256) else \
        _health_from_db(db,OBSERVATION_DRAIN_KEY+'_preserved.'+PROGRAM_GAP_OBSERVATION_SHA256,SOURCE_DRAIN_BYTES)
    require(isinstance(raw,str) and hashlib.sha256(raw.encode()).hexdigest()==PROGRAM_GAP_OBSERVATION_SHA256)
    body=_retained_census(raw);record=records[0];accounting=body.get('handler_accounting')
    require(body['state']=='RECOVERY_REQUIRED' and _observation_reference(body) and _committed_census(body)
        and (body['accepted_handlers'],body['settled_handlers'],body['pending_handlers'])==(60346,60345,1)
        and body.get('closed_sessions')==2 and body.get('preserved_partial_sessions')==1
        and body.get('unexpected_cancellation',False) is False
        and body.get('terminal_record_unavailable',False) is False
        and isinstance(accounting,dict) and accounting.get('version')==1 and accounting.get('valid') is True
        and accounting.get('run')==body.get('run_identity')==record.get('run')
        and isinstance(record.get('run'),str) and len(record['run'])==32
        and all(c in '0123456789abcdef' for c in record['run'])
        and type(record.get('source_pid')) is int and record['source_pid']>0
        and accounting.get('pid')==body.get('source_pid')==record['source_pid']
        and accounting.get('accepted')==60346 and accounting.get('returned')==60345
        and all(accounting.get(key)==value for key,value in
            (('active',0),('recoverable',1),('failed',0),('unresolved',0))))
    current_rows=accounting.get('records')
    require(isinstance(current_rows,list) and len(current_rows)==1 and isinstance(current_rows[0],dict)
        and all(record.get(key)==value for key,value in current_rows[0].items()))
    require(all(body['queues'][name]['accepted']==count for name,count in
        (('control',556),('rolling',65),('scout',4120),('candidate',0))))
    scope=program_scope('pumpswap')
    require(all(record.get(key)==value for key,value in (
        ('id',60266),('slot',457794201),('family','candidate_logs'),('transport','websocket'),
        ('kind','log_or_ack'),('phase','LOG_BUFFER_WAIT'),('state','RECOVERABLE'),
        ('failure_state','INTERRUPTED'),('error_type','CancelledError'),('scope_count',1),
        ('scope_hash',HandlerLedger.scope_hash((scope,))),
        ('recovery',dict(kind='CANDIDATE_GAPS',gap_ids=[39593])))))
    session=db.execute('''SELECT kind,at,length(CAST(body AS BLOB)),CASE WHEN
        length(CAST(body AS BLOB))<=? THEN body END FROM acquisition_observations WHERE id=231522''',
        (SOURCE_DRAIN_BYTES,)).fetchone()
    require(session is not None and session[0]=='source_session_drain'
        and isinstance(session[3],str) and session[2]<=SOURCE_DRAIN_BYTES
        and hashlib.sha256(session[3].encode()).hexdigest()==PROGRAM_GAP_SESSION_SHA256)
    observed=_retained_json(session[3])
    require(isinstance(observed,dict) and observed.get('plane')=='rolling'
        and observed.get('session')==record.get('session')=='41265de5e5164b90a108688caf6b1d73'
        and observed.get('drained') is False and observed.get('accepted_pending')==0
        and observed.get('pending_slots')==0 and observed.get('handler_dispositions')==records
        and observed.get('early_log_min_slot')==457794105 and observed.get('early_log_max_slot')==457794201
        and observed.get('recovery_obligations')==[
            dict(scope=program_scope(family),lower_slot=457794040,upper_slot=None)
            for family in ('pump','pumpswap')])
    for identity,family,created in ((39592,'pump',1792187653.1304228),(39593,'pumpswap',1792187653.352859)):
        gap=db.execute('SELECT scope,lo,hi,created,repaired,reason FROM candidate_gaps WHERE id=?',(identity,)).fetchone()
        require(gap is not None and gap[0]==program_scope(family) and gap[1]==457794040
            and (gap[2] is None or type(gap[2]) is int and gap[2]>=457794201)
            and gap[3]==created and gap[3]<=session[1]
            and gap[5]=='candidate_live_disconnect_or_filter_rebuild')
        # Original publication may mark/split the origin after a genuine FULL
        # consumer ACK. Its repaired flag proves neither completion nor loss:
        # retain the origin and require an actual unrepaired same-origin tail
        # covering this session's whole unavailable early-log interval.
        residuals=db.execute('''SELECT id,lo,hi FROM candidate_gaps INDEXED BY candidate_gap_scope_bounds
            WHERE scope=? AND lo>=? AND lo<=? AND (hi IS NULL OR hi>=?)
                AND created=? AND reason=? AND repaired IS NULL AND id>=?
            ORDER BY lo LIMIT 2''',(gap[0],gap[1],observed['early_log_min_slot'],
                observed['early_log_max_slot'],created,gap[5],identity)).fetchall()
        require(len(residuals)==1)
    # Original canonical consumer receipts/ACKs, without DDL or a new cursor.
    lifecycle=object.__new__(CandidateLifecycle);lifecycle.db=db
    require(all(lifecycle.unconsumed(program_scope(family)) is None for family in ('pump','pumpswap')))
    return dict(unreturned_observation_retained=True,retained_unreturned_observations=1,
        current_handler_disposition_verified=False,historical_callback_completion=False,
        preserved_observation_sha256=PROGRAM_GAP_OBSERVATION_SHA256,
        preserved_handler_sha256=PROGRAM_GAP_HANDLER_SHA256,program_gap_unavailable=True,
        retained_missing_range_lower_slot=observed['early_log_min_slot'],
        retained_missing_range_upper_slot=observed['early_log_max_slot'],
        retained_missing_range_scope='PUMP_AND_PUMPSWAP_PROGRAM_EARLY_LOG_BUFFER_ONLY',
        preserved_lost_observation_range_unavailable=True)


def _preserved_economic_replay_observation(db,current):
    """Reconstructed economics do not retrospectively ACK eight lost frames.

    Only this failed session's exhausted address pages and independently FULL
    committed consumer proofs admit a new observation. Native receipts and the
    original false queue census remain unchanged; unproved tail stays a gap.
    """
    from contextlib import closing
    from pathlib import Path
    from types import SimpleNamespace
    import math
    from .solana_evidence_plane import EvidenceUnavailable,IntervalProof,digest
    from .solana_selective_history import PROGRAMS,archive_interval_witness,coverage_points
    from .solana_candidate_lifecycle import CandidateLifecycle
    from .solana_rolling_history import RollingHistory,program_scope,_subtract_intervals
    from .solana_history_delivery import readonly_history
    def require(condition):
        if not condition:raise EvidenceUnavailable('source_observation_economic_replay_unverified')
    def hexadecimal(value):
        return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)
    def positive(value):
        return type(value) in (int,float) and math.isfinite(value) and value>0
    direct=isinstance(current,str) and hashlib.sha256(current.encode()).hexdigest()==ECONOMIC_REPLAY_OBSERVATION_SHA256
    raw=current if direct else _health_from_db(db,
        OBSERVATION_DRAIN_KEY+'_preserved.'+ECONOMIC_REPLAY_OBSERVATION_SHA256,SOURCE_DRAIN_BYTES)
    require(isinstance(raw,str) and hashlib.sha256(raw.encode()).hexdigest()==ECONOMIC_REPLAY_OBSERVATION_SHA256)
    body=_retained_census(raw);accounting=body.get('handler_accounting')
    require(body['state']=='RECOVERY_REQUIRED' and body.get('terminal') is True
        and _observation_reference(body) and _current_observation_identity(body)
        and (body['accepted_handlers'],body['settled_handlers'],body['pending_handlers'])==(118783,118783,0)
        and body.get('all_accepted_committed') is False
        and body.get('closed_sessions')==2 and body.get('preserved_partial_sessions')==1
        and type(body.get('unpreserved_sessions')) is int and body['unpreserved_sessions']==0
        and body.get('unexpected_cancellation',False) is False
        and body.get('terminal_record_unavailable',False) is False
        and all(type(accounting.get(key)) is int and accounting[key]==0
            for key in ('active','recoverable','failed','unresolved'))
        and body.get('queues')=={name:dict(accepted=a,committed=c,pending=a-c)
            for name,a,c in (('control',782,782),('rolling',191,183),('scout',5594,5594),('candidate',0,0))})
    session=db.execute('''SELECT kind,at,length(CAST(body AS BLOB)),CASE WHEN
        length(CAST(body AS BLOB))<=? THEN body END FROM acquisition_observations WHERE id=232141''',
        (SOURCE_DRAIN_BYTES,)).fetchone()
    require(session is not None and session[0]=='source_session_drain' and positive(session[1])
        and isinstance(session[3],str) and session[2]<=SOURCE_DRAIN_BYTES
        and hashlib.sha256(session[3].encode()).hexdigest()==ECONOMIC_REPLAY_SESSION_SHA256)
    observed=_retained_json(session[3])
    require(isinstance(observed,dict) and observed.get('plane')=='rolling'
        and observed.get('session')=='7d1d60314f4c4f018738ef154437e2c8'
        and observed.get('drained') is False and observed.get('accepted_pending')==8
        and observed.get('completed')==457828563 and observed.get('pending_slots')==1
        and observed.get('early_log_min_slot')==457828564 and observed.get('early_log_max_slot')==457828663
        and observed.get('recovery_obligations')==[
            dict(scope=program_scope(family),lower_slot=457828373,upper_slot=None)
            for family in ('pump','pumpswap')])
    provider=_health_from_db(db,'provider',SOURCE_DRAIN_BYTES)
    provider=None if provider is None else _retained_json(provider)
    require(isinstance(provider,dict) and provider.get('provider')=='alchemy_solana_mainnet'
        and provider.get('network')=='solana-mainnet' and hexadecimal(provider.get('endpoint_identity')))
    endpoint=provider['endpoint_identity']
    files=db.execute('PRAGMA database_list').fetchall()
    main=[row[2] for row in files if row[1]=='main']
    require(len(main)==1 and isinstance(main[0],str) and bool(main[0]))
    canonical_path=Path(main[0]);path=canonical_path.parent/'solana-candidate-history.sqlite'
    require(canonical_path.is_absolute() and canonical_path.resolve()==canonical_path
        and not canonical_path.is_symlink() and path.is_file() and not path.is_symlink()
        and Path(os.environ.get('MM_SOLANA_CANDIDATE_HISTORY_DB') or path)==path)
    lifecycle=object.__new__(CandidateLifecycle);lifecycle.db=db
    rolling=object.__new__(RollingHistory);rolling.db=db
    rolling.history=SimpleNamespace(db=db,clock=time.time)
    # The original gap-aware predicate authenticates compressed coverage and
    # availability. It does not treat a checkpoint or repaired origin as proof.
    proof_ids={};tail_unavailable=False
    with closing(readonly_history(path)) as shared:
        shared.db.execute('BEGIN')
        def consumer_proof(identity,family,scope,lo,hi):
            receipt=shared.db.execute('''SELECT length(CAST(body AS BLOB)),CASE WHEN
                length(CAST(body AS BLOB))<=? THEN body END,hash FROM source_receipts WHERE id=?''',
                (SOURCE_DRAIN_BYTES,'coverage:'+identity)).fetchone()
            require(receipt is not None and isinstance(receipt[1],str) and receipt[0]<=SOURCE_DRAIN_BYTES
                and hexadecimal(receipt[2]) and hashlib.sha256(receipt[1].encode()).hexdigest()==receipt[2])
            consumed=_retained_json(receipt[1])
            require(isinstance(consumed,dict) and all(consumed.get(key)==value for key,value in (
                ('identity',identity),('family',family),('address',PROGRAMS[family]),('scope',scope),
                ('lo',lo),('hi',hi),('endpoint',endpoint))) and positive(consumed.get('observed_at'))
                and isinstance(consumed.get('witness'),dict))
            IntervalProof(scope,lo,hi,consumed.get('source'),endpoint,consumed['witness'],
                consumed['observed_at']).validate()
            require(digest([scope,lo,hi,consumed['witness']])==identity
                and db.execute('SELECT 1 FROM candidate_pending_proofs WHERE id=?',(identity,)).fetchone() is None)
            return consumed
        for family,origin,created in (('pump',39941,1792195108.9836082),
                ('pumpswap',39942,1792195108.9970887)):
            scope=program_scope(family);address=PROGRAMS[family]
            gap=db.execute('SELECT scope,lo,hi,created,reason FROM candidate_gaps WHERE id=?',(origin,)).fetchone()
            require(gap is not None and gap[0]==scope and gap[1]==457828373
                and (gap[2] is None or type(gap[2]) is int and gap[2]>=457828663)
                and gap[3]==created and gap[3]<=session[1]
                and gap[4]=='candidate_live_disconnect_or_filter_rebuild')
            missing_tail=rolling.missing(family,scope,457828564,457828663)
            require(len(missing_tail)<=100)
            # Later real replay can recover some or all of the old tail. Each
            # remaining missing piece must still be an original-origin durable
            # gap; its complement needs independently FULL consumer proofs.
            if direct:require(missing_tail==[(457828564,457828663)])
            for lower,upper in missing_tail:
                tails=db.execute('''SELECT id,lo,hi FROM candidate_gaps INDEXED BY candidate_gap_scope_bounds
                    WHERE scope=? AND lo>=? AND lo<=? AND (hi IS NULL OR hi>=?)
                        AND created=? AND reason=? AND repaired IS NULL AND id>=?
                    ORDER BY lo LIMIT 2''',(scope,gap[1],lower,upper,created,gap[4],origin)).fetchall()
                require(len(tails)==1)
            tail_unavailable=tail_unavailable or bool(missing_tail)
            if direct:
                native=db.execute('SELECT slot,parent,hash,session,census_hash FROM candidate_blocks WHERE scope=?',
                    (scope,)).fetchone()
                require(native==(457828555,457828554,ECONOMIC_REPLAY_NATIVE_HASH,
                    observed['session'],ECONOMIC_REPLAY_NATIVE_CENSUS[family]))
            identity=digest([family,address,457828555,457828563])
            job=db.execute('''SELECT family,address,lo,hi,status,token,pages,lineage
                FROM acquisition_jobs WHERE id=?''',(identity,)).fetchone()
            pages,lineage,proof_id=ECONOMIC_REPLAY_JOBS[family]
            require(job==(family,address,457828555,457828563,'complete',None,pages,lineage))
            receipts=db.execute('''SELECT page,input_hash,length(CAST(result AS BLOB)),CASE WHEN
                length(CAST(result AS BLOB))<=? THEN result END,committed
                FROM acquisition_page_receipts WHERE job=? ORDER BY page LIMIT ?''',
                (SOURCE_DRAIN_BYTES,identity,pages+1)).fetchall()
            require(len(receipts)==pages)
            supplemented=False
            for page,row in enumerate(receipts):
                require(row[0]==page and hexadecimal(row[1]) and isinstance(row[3],str)
                    and row[2]<=SOURCE_DRAIN_BYTES and positive(row[4]))
                result=_retained_json(row[3])
                require(isinstance(result,dict) and result.get('complete') is (page==pages-1)
                    and type(result.get('pages')) is int and result['pages']==page+1
                    and type(result.get('records')) is int and result['records']>=0)
                supplements=result.get('archive_log_supplements',[])
                require(isinstance(supplements,list) and len(supplements)<=100)
                supplemented=supplemented or bool(supplements)
            witness=archive_interval_witness(dict(family=family,address=address,lo=457828555,
                hi=457828563,pages=pages),scope,lineage,supplemented=supplemented)
            require(digest([scope,457828555,457828563,witness])==proof_id)
            require(db.execute('SELECT 1 FROM candidate_pending_proofs WHERE id=?',(proof_id,)).fetchone() is None
                and lifecycle.unconsumed(scope) is None)
            consumed=consumer_proof(proof_id,family,scope,457828555,457828563)
            require(consumed.get('source')=='alchemy_finalized_repair' and consumed['witness']==witness)
            coverage=db.execute('SELECT points,hash FROM candidate_coverage WHERE scope=? AND lo<=? AND hi>=?',
                (scope,457828555,457828563)).fetchall()
            require(any(any(lo==457828555 and hi==457828563 and at<=time.time()
                for lo,hi,at in coverage_points(packed,checksum)) for packed,checksum in coverage))
            require(rolling.missing(family,scope,457828555,457828563)==[])
            covered_tail=_subtract_intervals(((457828564,457828663),),missing_tail)
            if covered_tail:
                receipts=shared.db.execute('''SELECT id,lo,hi,available,hash FROM work_history_proofs
                    INDEXED BY work_history_proof_scope WHERE scope=? AND lo<=? AND hi>=?
                    ORDER BY lo,hi LIMIT 257''',(scope,457828663,457828564)).fetchall()
                require(len(receipts)<=256)
                published=[]
                for scheduling,lo,hi,available,identity in receipts:
                    require(type(lo) is int and type(hi) is int and 0<=lo<=hi
                        and positive(available) and available<=time.time() and hexadecimal(identity)
                        and scheduling==digest(dict(scope=scope,lo=lo,hi=hi,proof_hash=identity)))
                    consumed=consumer_proof(identity,family,scope,lo,hi)
                    points=db.execute('SELECT points,hash FROM candidate_coverage WHERE scope=? AND lo<=? AND hi>=?',
                        (scope,lo,hi)).fetchall()
                    require(any(any(a==lo and b==hi and at==consumed['observed_at'] and at<=time.time()
                        for a,b,at in coverage_points(packed,checksum)) for packed,checksum in points))
                    published.append((lo,hi))
                require(not _subtract_intervals(covered_tail,published))
            proof_ids[family]=proof_id
    return dict(economic_interval_recovered=True,original_queue_acknowledgement_verified=False,
        original_source_drain_pass=False,preserved_economic_observation_sha256=ECONOMIC_REPLAY_OBSERVATION_SHA256,
        preserved_economic_session_sha256=ECONOMIC_REPLAY_SESSION_SHA256,
        economic_replay_lower_slot=457828555,economic_replay_upper_slot=457828563,
        economic_replay_proof_ids=proof_ids,retained_economic_tail_lower_slot=457828564,
        retained_economic_tail_upper_slot=457828663,retained_economic_tail_unavailable=tail_unavailable,
        economic_tail_continuity_verified=True,economic_tail_recovered=not tail_unavailable)


def _economic_db(state_or_db):
    return state_or_db.writer.db if hasattr(state_or_db,'writer') else state_or_db


def _economic_require(condition):
    from .solana_evidence_plane import EvidenceUnavailable
    if not condition:raise EvidenceUnavailable('source_session_economic_recovery_unverified')


def _economic_descriptor_rows(db,checksum=None):
    """An existing-table index keeps retrospective admission reads bounded."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name="
            "'acquisition_observations_recovery_kind_job'").fetchone():return []
    where='' if checksum is None else ' AND job=?'
    rows=db.execute('''SELECT id,job,length(CAST(body AS BLOB)),CASE WHEN
        length(CAST(body AS BLOB))<=? THEN body END FROM acquisition_observations
        INDEXED BY acquisition_observations_recovery_kind_job
        WHERE kind='source_economic_recovery_descriptor' '''+where+' ORDER BY id LIMIT 65',
        (SOURCE_DRAIN_BYTES,*(() if checksum is None else (checksum,)))).fetchall()
    _economic_require(len(rows)<=64)
    for row in rows:
        _economic_require(isinstance(row[3],str) and row[2]<=SOURCE_DRAIN_BYTES)
    return rows


def _economic_descriptor(db,reference):
    from .solana_evidence_plane import canonical
    if isinstance(reference,dict) and {'observation_id','sha256'}<=set(reference)<={'observation_id','sha256','descriptor'}:
        _economic_require(type(reference['observation_id']) is int and reference['observation_id']>0)
        row=db.execute('''SELECT kind,job,length(CAST(body AS BLOB)),CASE WHEN
            length(CAST(body AS BLOB))<=? THEN body END FROM acquisition_observations WHERE id=?''',
            (SOURCE_DRAIN_BYTES,reference['observation_id'])).fetchone()
        _economic_require(row is not None and row[0]=='source_economic_recovery_descriptor'
            and isinstance(row[3],str) and row[2]<=SOURCE_DRAIN_BYTES
            and hashlib.sha256(row[3].encode()).hexdigest()==reference['sha256'])
        descriptor=_retained_json(row[3]);_economic_require(isinstance(descriptor,dict)
            and descriptor.get('failed_census_sha256')==row[1])
        _economic_require('descriptor' not in reference or reference['descriptor']==descriptor)
        return descriptor,{key:reference[key] for key in ('observation_id','sha256')}
    _economic_require(isinstance(reference,dict))
    rows=_economic_descriptor_rows(db,reference.get('failed_census_sha256'))
    raw=canonical(reference)
    _economic_require(len(rows)==1 and rows[0][3]==raw)
    return reference,dict(observation_id=rows[0][0],sha256=hashlib.sha256(raw.encode()).hexdigest())


def _economic_failed_inputs(db,raw,handlers,session_id,*,heads=None,expected_origins=None):
    """Read the genuine interrupted queue boundary; no proof or cursor writes."""
    import math
    from .solana_evidence_plane import digest
    from .solana_selective_history import PROGRAMS
    from .solana_rolling_history import program_scope
    require=_economic_require
    require(isinstance(raw,str) and isinstance(handlers,str))
    body=_retained_census(raw);accounting=body.get('handler_accounting');queues=body.get('queues')
    require(body['state']=='RECOVERY_REQUIRED' and body.get('terminal') is True
        and _observation_reference(body) and body.get('all_accepted_committed') is False
        and type(body.get('unpreserved_sessions')) is int and body['unpreserved_sessions']==0
        and body.get('terminal_record_unavailable',False) is False
        and body.get('unexpected_cancellation',False) is False
        and isinstance(accounting,dict) and accounting.get('version')==1
        and accounting.get('valid') is True and accounting.get('run')==body.get('run_identity')
        and accounting.get('pid')==body.get('source_pid') and type(body.get('source_pid')) is int
        and body['source_pid']>0 and isinstance(body.get('run_identity'),str)
        and len(body['run_identity'])==32 and all(c in '0123456789abcdef' for c in body['run_identity'])
        and accounting.get('accepted')==body['accepted_handlers']
        and accounting.get('returned')==body['settled_handlers']
        and all(type(accounting.get(k)) is int and accounting[k]==0 for k in ('active','failed','unresolved'))
        and isinstance(queues,dict) and set(queues)=={'control','scout','rolling','candidate'})
    for plane,row in queues.items():
        require(isinstance(row,dict) and set(row)=={'accepted','committed','pending'}
            and all(type(row.get(k)) is int and row[k]>=0 for k in row)
            and row['accepted']-row['committed']==row['pending']
            and (plane=='rolling' or row['pending']==0))
    require(0<queues['rolling']['pending']<=8)
    current=accounting.get('records');retained=_retained_handlers(handlers)
    require(isinstance(current,list) and len(current)<=HandlerLedger.maximum_records
        and len(current)==body['pending_handlers']==accounting.get('recoverable'))
    run_rows=[r for r in retained if r.get('run')==body['run_identity']]
    require(len(run_rows)==len(current) and all(r.get('source_pid')==body['source_pid'] for r in run_rows))
    identities=[]
    for record in current:
        require(isinstance(record,dict) and type(record.get('id')) is int
            and 1<=record['id']<=body['accepted_handlers'] and record['id'] not in identities)
        identities.append(record['id'])
        matches=[r for r in retained if r.get('run')==body['run_identity'] and r.get('id')==record['id']]
        require(len(matches)==1 and all(matches[0].get(k)==v for k,v in record.items()))
        require(matches[0].get('source_pid')==body['source_pid']
            and matches[0].get('kind') in ('block_meta','transaction_status','slot')
            and all(matches[0].get(k)==v for k,v in (('state','RECOVERABLE'),('phase','CANDIDATE_QUEUE'),
                ('transport','yellowstone'),('family','pump'),('failure_state','INTERRUPTED'),('error_type','CancelledError'))))
    session=db.execute('''SELECT kind,at,length(CAST(body AS BLOB)),CASE WHEN
        length(CAST(body AS BLOB))<=? THEN body END FROM acquisition_observations WHERE id=?''',
        (SOURCE_DRAIN_BYTES,session_id)).fetchone()
    require(session is not None and session[0]=='source_session_drain' and isinstance(session[3],str)
        and session[2]<=SOURCE_DRAIN_BYTES and type(session[1]) in (int,float) and math.isfinite(session[1]))
    observed=_retained_json(session[3]);scope_list=[program_scope(f) for f in ('pump','pumpswap')]
    require(isinstance(observed,dict) and observed.get('plane')=='rolling' and observed.get('drained') is False
        and observed.get('accepted_pending')==queues['rolling']['pending']
        and isinstance(observed.get('session'),str) and len(observed['session'])==32
        and all(c in '0123456789abcdef' for c in observed['session'])
        and type(observed.get('completed')) is int and observed['completed']>0
        and type(observed.get('pending_slots')) is int and observed['pending_slots']>=0
        and observed.get('handler_dispositions',[])==[r for r in retained
            if r.get('run')==body['run_identity'] and r.get('source_pid')==body['source_pid']])
    obligations=observed.get('recovery_obligations')
    require(isinstance(obligations,list) and len(obligations)==2 and all(isinstance(r,dict) for r in obligations)
        and [r.get('scope') for r in obligations]==scope_list
        and all(type(r.get('lower_slot')) is int and r['lower_slot']>0 and r.get('upper_slot') is None for r in obligations))
    fields=('scope','slot','parent','hash','previous_hash','market_time','seen','session','census_hash')
    actual=heads
    if actual is None:
        actual={}
        for family in ('pump','pumpswap'):
            row=db.execute('SELECT slot,parent,hash,previous_hash,market_time,seen,session,census_hash '
                'FROM candidate_blocks WHERE scope=?',(program_scope(family),)).fetchone()
            require(row is not None)
            actual[family]=dict(zip(fields,(program_scope(family),*row)))
    require(isinstance(actual,dict) and set(actual)=={'pump','pumpswap'})
    for family,head in actual.items():
        require(isinstance(head,dict) and set(head)==set(fields) and head['scope']==program_scope(family)
            and type(head['slot']) is int and type(head['parent']) is int and 0<head['slot']>head['parent']>=0
            and head['session']==observed['session'] and head['slot']<=observed['completed']
            and all(isinstance(head[k],str) and len(head[k])==64 and all(c in '0123456789abcdef' for c in head[k])
                for k in ('census_hash',))
            and all(isinstance(head[k],str) and 32<=len(head[k])<=44
                and all(c in '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz' for c in head[k])
                for k in ('hash','previous_hash'))
            and type(head['market_time']) is int and head['market_time']>0
            and type(head['seen']) in (int,float) and math.isfinite(head['seen']) and head['seen']>0)
    require(all(actual['pump'][key]==actual['pumpswap'][key]
        for key in ('slot','parent','hash','previous_hash','market_time','session')))
    lo=actual['pump']['slot'];hi=observed['completed']
    required_upper=max((hi,*(value for value in (observed.get('early_log_max_slot'),observed.get('oldest_slot'))
        if type(value) is int)))
    require(expected_origins is None or isinstance(expected_origins,dict)
        and set(expected_origins)=={'pump','pumpswap'})
    origins={}
    for family,obligation in zip(('pump','pumpswap'),obligations):
        scopes=(program_scope(family),)
        records=[r for r in retained if r.get('run')==body['run_identity']]
        ids={i for r in records for i in r.get('recovery',{}).get('gap_ids',[])}
        # A zero-handler queue failure still has genuine disconnect origins.
        if not ids:
            rows=db.execute('''SELECT id FROM candidate_gaps INDEXED BY candidate_gap_scope_bounds
                WHERE scope=? AND lo=? AND created<=? AND reason='candidate_live_disconnect_or_filter_rebuild'
                ORDER BY id DESC LIMIT 2''',(scopes[0],obligation['lower_slot'],session[1])).fetchall()
            require(len(rows)==1);ids={rows[0][0]}
        gaps=[(i,db.execute('SELECT scope,lo,hi,created,reason FROM candidate_gaps WHERE id=?',(i,)).fetchone()) for i in sorted(ids)]
        matching=[(i,r) for i,r in gaps if r is not None and r[0]==scopes[0]]
        require(len(matching)==1);identity,gap=matching[0]
        require(gap[1]==obligation['lower_slot'] and gap[1]<=lo
            and (gap[2] is None or type(gap[2]) is int and gap[2]>=required_upper)
            and type(gap[3]) in (int,float) and math.isfinite(gap[3]) and 0<gap[3]<=session[1]
            and gap[4]=='candidate_live_disconnect_or_filter_rebuild')
        origin=dict(zip(('id','scope','lo','hi','created','reason'),(identity,*gap)))
        if expected_origins is not None:
            preserved=expected_origins[family]
            require(isinstance(preserved,dict) and set(preserved)==set(origin)
                and all(preserved[key]==origin[key] for key in ('id','scope','lo','created','reason'))
                and (preserved['hi']==origin['hi'] or preserved['hi'] is None
                    and type(origin['hi']) is int and origin['hi']>=required_upper))
            # The authentic post-ACK handoff may bound an open origin, including
            # a repaired audit row. Retain the captured input bytes, while every
            # remaining missing segment still needs its actual residual gap.
            origin=preserved
        origins[family]=origin
    for r in retained:
        if r.get('run')!=body['run_identity']:continue
        require(r.get('session')==observed['session'] and type(r.get('slot')) is int and lo<=r['slot']<=hi
            and r.get('scope_count')==2 and r.get('scope_hash')==HandlerLedger.scope_hash(scope_list)
            and r.get('recovery')==dict(kind='CANDIDATE_GAPS',gap_ids=[origins[f]['id'] for f in ('pump','pumpswap')]))
    tail_lo=observed.get('early_log_min_slot');tail_hi=observed.get('early_log_max_slot');oldest=observed.get('oldest_slot')
    if tail_lo is None:
        require(tail_hi is None)
        tail_lo=tail_hi=oldest
    else:
        require(type(tail_lo) is int and type(tail_hi) is int and hi<tail_lo<=tail_hi)
        if oldest is not None:
            require(type(oldest) is int and oldest>hi);tail_lo=min(tail_lo,oldest);tail_hi=max(tail_hi,oldest)
    require(tail_lo is None or type(tail_lo) is int and type(tail_hi) is int and hi<tail_lo<=tail_hi)
    provider=_retained_json(_health_from_db(db,'provider',SOURCE_DRAIN_BYTES))
    require(isinstance(provider,dict) and provider.get('provider')=='alchemy_solana_mainnet'
        and provider.get('network')=='solana-mainnet' and isinstance(provider.get('endpoint_identity'),str)
        and len(provider['endpoint_identity'])==64 and all(c in '0123456789abcdef' for c in provider['endpoint_identity']))
    return dict(version=1,kind='ROLLING_ECONOMIC_REPLAY_INPUTS',failed_census_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        handler_ledger_sha256=hashlib.sha256(handlers.encode()).hexdigest(),run_identity=body['run_identity'],
        source_pid=body['source_pid'],session=observed['session'],session_observation_id=session_id,
        session_sha256=hashlib.sha256(session[3].encode()).hexdigest(),endpoint_identity=provider['endpoint_identity'],
        lower_slot=lo,upper_slot=hi,tail_lower_slot=tail_lo,tail_upper_slot=tail_hi,
        accepted_pending=queues['rolling']['pending'],handler_records=[r for r in retained if r.get('run')==body['run_identity']],
        native_heads=actual,gap_origins=origins,job_ids={f:digest([f,PROGRAMS[f],lo,hi]) for f in ('pump','pumpswap')})


def current_economic_recovery_descriptor(state_or_db):
    """Select only an authentic current queue incident, never caller bounds."""
    db=_economic_db(state_or_db)
    raw=_health_from_db(db,OBSERVATION_DRAIN_KEY,SOURCE_DRAIN_BYTES)
    if raw is None:return None
    body=_retained_census(raw)
    if body['state']!='RECOVERY_REQUIRED':return None
    if hashlib.sha256(raw.encode()).hexdigest() in (PROGRAM_GAP_OBSERVATION_SHA256,ECONOMIC_REPLAY_OBSERVATION_SHA256):return None
    _historical_observation_record(db)
    handlers=_health_from_db(db,HANDLER_RECOVERY_KEY,HandlerLedger.maximum_bytes)
    checksum=hashlib.sha256(raw.encode()).hexdigest();prior=_economic_descriptor_rows(db,checksum)
    if prior:
        _economic_require(len(prior)==1)
        descriptor=_retained_json(prior[0][3])
        actual=_economic_failed_inputs(db,raw,handlers,descriptor['session_observation_id'])
        _economic_require(actual==descriptor)
        return descriptor
    sessions=[]
    rows=db.execute('''SELECT id,kind,length(CAST(body AS BLOB)),CASE WHEN
        length(CAST(body AS BLOB))<=? THEN body END FROM acquisition_observations ORDER BY id DESC LIMIT 128''',
        (SOURCE_DRAIN_BYTES,)).fetchall()
    for identity,kind,size,observed_raw in rows:
        if kind!='source_session_drain':continue
        _economic_require(isinstance(observed_raw,str) and size<=SOURCE_DRAIN_BYTES)
        observed=_retained_json(observed_raw)
        if observed.get('plane')!='rolling':continue
        session=observed.get('session')
        records=body.get('handler_accounting',{}).get('records',[])
        head=db.execute('SELECT session FROM candidate_blocks WHERE scope=?',
            ('candidate:pump:6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P',)).fetchone()
        if head is not None and session==head[0] and all(r.get('session')==session for r in records):sessions.append(identity)
    _economic_require(len(sessions)==1)
    return _economic_failed_inputs(db,raw,handlers,sessions[0])


def preserve_economic_recovery_descriptor(state,descriptor):
    """Preserve inputs once; an acquisition binding never asserts completion."""
    from .solana_evidence_plane import canonical
    with state.writer.transaction():
        _economic_require(current_economic_recovery_descriptor(state)==descriptor)
        db=state.writer.db
        db.execute('CREATE INDEX IF NOT EXISTS acquisition_observations_recovery_kind_job '
            'ON acquisition_observations(kind,job,id)')
        rows=_economic_descriptor_rows(db,descriptor['failed_census_sha256']);raw=canonical(descriptor)
        _economic_require(len(raw.encode())<=SOURCE_DRAIN_BYTES and len(rows)<=1)
        if rows:
            _economic_require(rows[0][3]==raw);identity=rows[0][0]
        else:
            identity=db.execute('INSERT INTO acquisition_observations(job,kind,at,body) VALUES(?,?,?,?)',
                (descriptor['failed_census_sha256'],'source_economic_recovery_descriptor',time.time(),raw)).lastrowid
        return dict(observation_id=identity,sha256=hashlib.sha256(raw.encode()).hexdigest(),descriptor=descriptor)


def verify_economic_recovery_descriptor(state_or_db,descriptor_or_reference):
    """Original exhausted pages, FULL receipts, ACKs and gap-aware coverage."""
    from contextlib import closing
    from pathlib import Path
    from types import SimpleNamespace
    import math
    from .solana_evidence_plane import digest,IntervalProof
    from .solana_selective_history import PROGRAMS,archive_interval_witness,coverage_points
    from .solana_candidate_lifecycle import CandidateLifecycle
    from .solana_rolling_history import RollingHistory,program_scope,_subtract_intervals
    from .solana_history_delivery import readonly_history
    db=_economic_db(state_or_db);require=_economic_require
    descriptor,reference=_economic_descriptor(db,descriptor_or_reference)
    checksum=descriptor.get('failed_census_sha256')
    current=_health_from_db(db,OBSERVATION_DRAIN_KEY,SOURCE_DRAIN_BYTES)
    direct=current is not None and hashlib.sha256(current.encode()).hexdigest()==checksum
    failed=current if direct else _health_from_db(db,OBSERVATION_DRAIN_KEY+'_preserved.'+str(checksum),SOURCE_DRAIN_BYTES)
    ledger=_health_from_db(db,HANDLER_RECOVERY_KEY,HandlerLedger.maximum_bytes)
    old_ledger=ledger if direct and ledger is not None and hashlib.sha256(ledger.encode()).hexdigest()==descriptor.get('handler_ledger_sha256') else \
        _health_from_db(db,HANDLER_RECOVERY_KEY+'_preserved.'+str(descriptor.get('handler_ledger_sha256')),HandlerLedger.maximum_bytes)
    require(failed is not None and hashlib.sha256(failed.encode()).hexdigest()==checksum
        and old_ledger is not None and hashlib.sha256(old_ledger.encode()).hexdigest()==descriptor.get('handler_ledger_sha256'))
    require(_economic_failed_inputs(db,failed,old_ledger,descriptor['session_observation_id'],
        heads=None if direct else descriptor['native_heads'],expected_origins=descriptor['gap_origins'])==descriptor)
    live=[] if ledger is None else _retained_handlers(ledger)
    for record in _retained_handlers(old_ledger):
        require([r for r in live if (r.get('run'),r.get('id'))==(record.get('run'),record.get('id'))]==[record])
    main=[r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main']
    require(len(main)==1 and bool(main[0]));canonical=Path(main[0]);path=canonical.parent/'solana-candidate-history.sqlite'
    require(canonical.is_absolute() and canonical.resolve()==canonical and not canonical.is_symlink()
        and path.is_file() and not path.is_symlink() and Path(os.environ.get('MM_SOLANA_CANDIDATE_HISTORY_DB') or path)==path)
    life=object.__new__(CandidateLifecycle);life.db=db
    rolling=object.__new__(RollingHistory);rolling.db=db;rolling.history=SimpleNamespace(db=db,clock=time.time)
    lo=descriptor['lower_slot'];hi=descriptor['upper_slot'];endpoint=descriptor['endpoint_identity'];proofs={};tail_missing=False
    def points_cover(scope,a,b,at=None):
        rows=db.execute('SELECT points,hash FROM candidate_coverage WHERE scope=? AND lo<=? AND hi>=?',(scope,a,b)).fetchall()
        return any(any(x==a and y==b and t<=time.time() and (at is None or t==at)
            for x,y,t in coverage_points(raw,checksum)) for raw,checksum in rows)
    with closing(readonly_history(path)) as shared:
        shared.db.execute('BEGIN')
        def full(identity,family,a,b,witness=None):
            row=shared.db.execute('''SELECT length(CAST(body AS BLOB)),CASE WHEN
                length(CAST(body AS BLOB))<=? THEN body END,hash FROM source_receipts WHERE id=?''',
                (SOURCE_DRAIN_BYTES,'coverage:'+identity)).fetchone()
            require(row is not None and isinstance(row[1],str) and row[0]<=SOURCE_DRAIN_BYTES
                and hashlib.sha256(row[1].encode()).hexdigest()==row[2])
            body=_retained_json(row[1]);scope=program_scope(family)
            require(isinstance(body,dict) and all(body.get(k)==v for k,v in (('identity',identity),('family',family),
                ('address',PROGRAMS[family]),('scope',scope),('lo',a),('hi',b),('endpoint',endpoint)))
                and isinstance(body.get('witness'),dict) and (witness is None or body['witness']==witness))
            IntervalProof(scope,a,b,body.get('source'),endpoint,body['witness'],body.get('observed_at',0)).validate()
            require(digest([scope,a,b,body['witness']])==identity
                and db.execute('SELECT 1 FROM candidate_pending_proofs WHERE id=?',(identity,)).fetchone() is None)
            return body
        for family in ('pump','pumpswap'):
            scope=program_scope(family);identity=descriptor['job_ids'][family]
            row=db.execute('SELECT family,address,lo,hi,status,token,pages,lineage FROM acquisition_jobs WHERE id=?',(identity,)).fetchone()
            require(row is not None and row[:6]==(family,PROGRAMS[family],lo,hi,'complete',None)
                and type(row[6]) is int and row[6]>0 and isinstance(row[7],str) and len(row[7])==64
                and all(c in '0123456789abcdef' for c in row[7]))
            pages,lineage=row[6:]
            require(db.execute('SELECT count(*),min(page),max(page) FROM acquisition_page_receipts WHERE job=?',
                (identity,)).fetchone()==(pages,0,pages-1))
            receipts=db.execute('''SELECT page,input_hash,length(CAST(result AS BLOB)),CASE WHEN
                length(CAST(result AS BLOB))<=? THEN result END,committed
                FROM acquisition_page_receipts WHERE job=? ORDER BY page''',(SOURCE_DRAIN_BYTES,identity))
            supplemented=False
            for index,receipt in enumerate(receipts):
                require(receipt[0]==index and isinstance(receipt[1],str) and len(receipt[1])==64
                    and all(c in '0123456789abcdef' for c in receipt[1]) and isinstance(receipt[3],str)
                    and receipt[2]<=SOURCE_DRAIN_BYTES and type(receipt[4]) in (int,float)
                    and math.isfinite(receipt[4]) and receipt[4]>0)
                result=_retained_json(receipt[3])
                require(isinstance(result,dict) and result.get('complete') is (index==pages-1)
                    and type(result.get('pages')) is int and result['pages']==index+1
                    and type(result.get('records')) is int and result['records']>=0
                    and isinstance(result.get('archive_log_supplements',[]),list)
                    and len(result.get('archive_log_supplements',[]))<=100)
                supplements=result.get('archive_log_supplements',[]);bound=[]
                for supplement in supplements:
                    require(isinstance(supplement,dict) and type(supplement.get('observation_id')) is int)
                    observed=db.execute('''SELECT job,kind,length(CAST(body AS BLOB)),CASE WHEN
                        length(CAST(body AS BLOB))<=16777216 THEN body END FROM acquisition_observations WHERE id=?''',
                        (supplement['observation_id'],)).fetchone()
                    require(observed is not None and observed[:2]==(identity,'archive_log_supplement')
                        and isinstance(observed[3],str) and observed[2]<=16777216
                        and hashlib.sha256(observed[3].encode()).hexdigest()==supplement.get('observation_body_hash'))
                    value=_retained_json(observed[3])
                    require(isinstance(value,dict) and 'response' in value
                        and digest(value['response'])==supplement.get('fetched_transaction_hash')
                        and {k:v for k,v in value.items() if k!='response'}==
                            {k:v for k,v in supplement.items() if k not in ('observation_id','observation_body_hash')}
                        and value.get('endpoint_identity')==endpoint and value.get('method')=='getTransaction'
                        and value.get('commitment')=='finalized' and type(value.get('slot')) is int
                        and lo<=value['slot']<=hi and type(value.get('transaction_index')) is int
                        and value['transaction_index']>=0 and type(value.get('original_prefix_length')) is int
                        and value['original_prefix_length']>=0)
                    logs=value['response'].get('meta',{}).get('logMessages') if isinstance(value['response'],dict) else None
                    require(isinstance(logs,list) and value['original_prefix_length']<=len(logs)
                        and not any(isinstance(line,str) and 'truncat' in line.lower() for line in logs))
                    bound.append({k:v for k,v in supplement.items() if k!='observation_id'})
                if supplements:
                    require(digest(dict(method='getTransactionsForAddress+getTransaction',
                        archive_page_hash=result.get('archive_page_hash'),archive_log_supplements=bound))
                        ==result.get('archive_supplemented_page_hash'))
                supplemented=supplemented or bool(supplements)
            witness=archive_interval_witness(dict(family=family,address=PROGRAMS[family],lo=lo,hi=hi,pages=pages),scope,lineage,supplemented=supplemented)
            proof=digest([scope,lo,hi,witness]);consumer=full(proof,family,lo,hi,witness)
            require(consumer.get('source')=='alchemy_finalized_repair' and points_cover(scope,lo,hi)
                and life.unconsumed(scope) is None and rolling.missing(family,scope,lo,hi)==[])
            proofs[family]=proof
            a=descriptor['tail_lower_slot'];b=descriptor['tail_upper_slot'];origin=descriptor['gap_origins'][family]
            if a is None:continue
            missing=rolling.missing(family,scope,a,b);tail_missing=tail_missing or bool(missing)
            require(len(missing)<=4096)
            for x,y in missing:
                rows=db.execute('''SELECT id FROM candidate_gaps INDEXED BY candidate_gap_scope_bounds
                    WHERE scope=? AND lo>=? AND lo<=? AND (hi IS NULL OR hi>=?) AND created=?
                    AND reason=? AND repaired IS NULL AND id>=? ORDER BY lo LIMIT 2''',
                    (scope,origin['lo'],x,y,origin['created'],origin['reason'],origin['id'])).fetchall()
                require(len(rows)==1)
            covered=_subtract_intervals(((a,b),),missing)
            if covered:
                rows=shared.db.execute('''SELECT id,lo,hi,available,hash FROM work_history_proofs INDEXED BY work_history_proof_scope
                    WHERE scope=? AND lo<=? AND hi>=? ORDER BY lo,hi LIMIT 4097''',(scope,b,a)).fetchall()
                require(len(rows)<=4096);published=[]
                for scheduling,x,y,available,proof in rows:
                    require(type(x) is int and type(y) is int and 0<=x<=y
                        and type(available) in (int,float) and math.isfinite(available) and 0<available<=time.time()
                        and scheduling==digest(dict(scope=scope,lo=x,hi=y,proof_hash=proof)))
                    consumer=full(proof,family,x,y)
                    require(points_cover(scope,x,y,consumer['observed_at']));published.append((x,y))
                require(not _subtract_intervals(covered,published))
    return dict(reference=reference,descriptor=descriptor,economic_interval_recovered=True,
        original_queue_acknowledgement_verified=False,original_source_drain_pass=False,
        callback_completion_demonstrated=False,lower_slot=lo,upper_slot=hi,proof_ids=proofs,
        economic_tail_continuity_verified=True,economic_tail_recovered=not tail_missing,
        retained_economic_tail_unavailable=tail_missing)


def _session_economic_boundaries(db,current,handlers):
    """Every appended handler retains its own independently recovered input."""
    rows=_economic_descriptor_rows(db);body=None if current is None else _retained_census(current)
    carried=[] if body is None else body.get('session_economic_recovery_references',[])
    _economic_require(isinstance(carried,list) and len(carried)<=HandlerLedger.maximum_records)
    references=[dict(observation_id=r[0],sha256=hashlib.sha256(r[3].encode()).hexdigest()) for r in rows]
    if body is not None and body['state']=='DRAINED':_economic_require(carried==references)
    elif carried:
        _economic_require(all(reference in references for reference in carried)
            and len({r['observation_id'] for r in carried})==len(carried))
    proofs=[verify_economic_recovery_descriptor(db,reference) for reference in references]
    live=[] if handlers is None else _retained_handlers(handlers)
    if proofs:
        old=_health_from_db(db,HANDLER_RECOVERY_KEY+'_preserved.'+PROGRAM_GAP_HANDLER_SHA256,HandlerLedger.maximum_bytes)
        _economic_require(isinstance(old,str) and hashlib.sha256(old.encode()).hexdigest()==PROGRAM_GAP_HANDLER_SHA256)
        expected={(r.get('run'),r.get('id')):r for r in _retained_handlers(old)}
        for proof in proofs:
            for row in proof['descriptor']['handler_records']:
                key=(row.get('run'),row.get('id'))
                _economic_require(key not in expected or expected[key]==row);expected[key]=row
        _economic_require(len(live)==len(expected) and all(expected.get((r.get('run'),r.get('id')))==r for r in live))
    elif len(live)>1:
        _economic_require(False)
    summaries=[]
    for proof in proofs:
        d=proof['descriptor']
        summaries.append(dict(reference=proof['reference'],failed_census_sha256=d['failed_census_sha256'],
            session_sha256=d['session_sha256'],session=d['session'],lower_slot=proof['lower_slot'],
            upper_slot=proof['upper_slot'],proof_ids=proof['proof_ids'],handler_count=len(d['handler_records']),
            economic_interval_recovered=True,original_queue_acknowledgement_verified=False,
            original_source_drain_pass=False,callback_completion_demonstrated=False,
            retained_economic_tail_lower_slot=d['tail_lower_slot'],retained_economic_tail_upper_slot=d['tail_upper_slot'],
            retained_economic_tail_unavailable=proof['retained_economic_tail_unavailable'],
            economic_tail_continuity_verified=True,economic_tail_recovered=proof['economic_tail_recovered']))
    return dict(session_economic_recovery_verified=True,session_economic_recovery_references=references,
        session_economic_recoveries=summaries) if references else {}


def historical_observation_boundary(state_or_db):
    """Observe one retained incident; never discharge its unknown callbacks.

    The ordinary source guard still refuses these incidents. A previous current
    observation must have fully drained or match an exact independently proved
    retained boundary. RUNNING still contains crashes without a terminal.
    """
    from .solana_evidence_plane import EvidenceUnavailable
    db=state_or_db.writer.db if hasattr(state_or_db,'writer') else state_or_db
    _historical_observation_record(db)
    handlers=_health_from_db(db,HANDLER_RECOVERY_KEY,HandlerLedger.maximum_bytes)
    current=_health_from_db(db,OBSERVATION_DRAIN_KEY,SOURCE_DRAIN_BYTES)
    program_gap={}
    if handlers is not None and _retained_handlers(handlers):
        program_gap=_preserved_program_gap_observation(db,handlers,current)
    preserved_current=bool(program_gap) and hashlib.sha256((current or '').encode()).hexdigest()==PROGRAM_GAP_OBSERVATION_SHA256
    economic={}
    economic_current=hashlib.sha256((current or '').encode()).hexdigest()==ECONOMIC_REPLAY_OBSERVATION_SHA256
    archived_economic=_health_from_db(db,OBSERVATION_DRAIN_KEY+'_preserved.'+ECONOMIC_REPLAY_OBSERVATION_SHA256,SOURCE_DRAIN_BYTES)
    # The original immutable session/jobs retain the incident's existence even
    # if its preserved raw health row is missing. A later DRAINED marker cannot
    # erase that obligation by falling back to the older observation boundary.
    tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('acquisition_observations','acquisition_jobs')")}
    economic_retained=('acquisition_observations' in tables and db.execute(
        'SELECT 1 FROM acquisition_observations WHERE id=232141').fetchone() is not None)
    if 'acquisition_jobs' in tables:
        economic_retained=economic_retained or db.execute('SELECT 1 FROM acquisition_jobs WHERE id IN (?,?) LIMIT 1',
            ('14d4934f494420ad68ebcb7d3e2a2916ccdef01480a2276678190c7f71dfca10',
             '7284a3d280600866471e2814a2fc12c7a5682e8138756262b68379e32f32d43b')).fetchone() is not None
    if economic_current or archived_economic is not None or economic_retained:
        if not program_gap:raise EvidenceUnavailable('source_observation_economic_replay_unverified')
        economic=_preserved_economic_replay_observation(db,current)
    sessions=_session_economic_boundaries(db,current,handlers)
    session_current=any(row['failed_census_sha256']==hashlib.sha256((current or '').encode()).hexdigest()
        for row in sessions.get('session_economic_recoveries',[]))
    if current is not None:
        body=_retained_census(current)
        if not preserved_current and not economic_current and not session_current and (not _observation_reference(body) or body['state']!='DRAINED'
                or body['pending_handlers'] or not _committed_census(body)
                or not _current_observation_identity(body)):
            raise EvidenceUnavailable('source_observation_current_drain_unresolved')
    elif program_gap or economic or sessions:raise EvidenceUnavailable('source_observation_current_drain_unresolved')
    return dict(eligible=True,historical_source_drain_sha256=HISTORICAL_OBSERVATION_SHA256,
        historical_unknown_handlers=2,historical_recovery_verified=False,
        source_drain_preserved_in_place=True,current_observation_state='PRESERVED_SESSION_ECONOMIC_REPLAY' if session_current else 'PRESERVED_ECONOMIC_REPLAY' if economic_current else 'PRESERVED_PROGRAM_GAP' if preserved_current else 'ABSENT' if current is None else 'DRAINED',
        current_observation_sha256=None if current is None else hashlib.sha256(current.encode()).hexdigest(),**program_gap,**economic,**sessions)


def _require_observation_funding_closed():
    """Read the existing selected PAPER admission and Budget; never create one."""
    from contextlib import closing
    from pathlib import Path
    import sqlite3
    from .solana_evidence_plane import EvidenceUnavailable
    try:
        if os.environ.get('MM_MODE')!='PAPER' or os.environ.get('MM_OPERATIONAL_PHASE')!='OBSERVATION':
            raise ValueError()
        from .operational.admission import require_normal
        profile=require_normal(startup=True)
        root=Path(os.environ['MM_STATE_ROOT']);path=Path(os.environ['MM_PROVIDER_USAGE_DB'])
        if root.resolve()!=root or path.resolve()!=path or path.is_symlink() or not path.is_file():
            raise ValueError()
        from .operational.bounded_provider import Budget,resource_configuration
        # A Budget constructor can preserve a configuration failure by writing
        # it. This guard uses its original verifier on an existing read-only
        # snapshot instead, without schema setup, orphan reaping or admission.
        budget=object.__new__(Budget);budget.prefix='';budget.continuous=True
        budget.envelope=profile
        budget.configuration=resource_configuration(profile['limits'],None,None,None,continuous=True)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            usage=budget.read(db)
            if (budget.verify_configuration(usage) or usage.get('new_risk_ready')!='false'
                    or usage.get('reason')!=''):
                raise ValueError()
        from .shared_capital.runtime import selected
        from .shared_capital.reporting import read_authority
        from .runtime.policy_compatibility import require_flat_portfolio
        shared=selected(root/'portfolio.sqlite')
        if shared is None or shared!=root/'shared-capital.sqlite':raise ValueError()
        with closing(sqlite3.connect(shared.as_uri()+'?mode=ro',uri=True,timeout=0)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            ledger=read_authority(db).ledger()
            require_flat_portfolio(ledger)
            scope=ledger.get('runtime_admission',{})
            if (ledger.get('epoch_id')!=os.environ.get('MM_PAPER_EPOCH') or scope.get('mode')!='OBSERVATION'
                    or scope.get('provider_db')!=str(path) or scope.get('continuous_provider_db')!=str(path)):
                raise ValueError()
    except Exception:
        raise EvidenceUnavailable('source_observation_funding_closed_unverified') from None


def retained_source_drain(state,*,contained_observation=False):
    """Read the old census before startup can overwrite its missing locators.

    A same-count ledger from another run supplies no disposition. Known durable
    rows retain their existing recovery semantics; this grants no recovery PASS.
    """
    from .solana_evidence_plane import EvidenceUnavailable
    raw=_retained_health(state,SOURCE_DRAIN_KEY,SOURCE_DRAIN_BYTES)
    handlers=_retained_health(state,HANDLER_RECOVERY_KEY,HandlerLedger.maximum_bytes)
    records=[] if handlers is None else _retained_handlers(handlers)
    if contained_observation:
        _require_observation_funding_closed()
        historical_observation_boundary(state)
        return raw
    if raw is None:return None
    body=_retained_census(raw)
    if not body['pending_handlers']:return raw
    run=body.get('run_identity');pid=body.get('source_pid')
    matches=[row for row in records if row.get('run')==run and row.get('source_pid')==pid]
    identities=[row.get('id') for row in matches]
    if (not isinstance(run,str) or not run or len(run)>128 or type(pid) is not int or pid<=0
            or len(matches)!=body['pending_handlers']
            or any(type(number) is not int or not 1<=number<=body['accepted_handlers'] for number in identities)
            or len(set(identities))!=len(identities)
            or any(row.get('state') not in ('ACTIVE','FAILED','INTERRUPTED','RECOVERABLE') for row in matches)):
        raise EvidenceUnavailable('source_drain_historical_handlers_unlocated')
    return raw


def assert_source_drain_boundary(state,boundary,*,handler_boundary=None):
    """The old exact bytes and known identities cannot change underneath us."""
    from .solana_evidence_plane import EvidenceUnavailable
    if _retained_health(state,SOURCE_DRAIN_KEY,SOURCE_DRAIN_BYTES)!=boundary:
        raise EvidenceUnavailable('source_drain_retained_boundary_changed')
    if handler_boundary is not None:
        original=_retained_handlers(handler_boundary)
        current=_retained_health(state,HANDLER_RECOVERY_KEY,HandlerLedger.maximum_bytes)
        records=[] if current is None else _retained_handlers(current)
        for old in original:
            matches=[row for row in records if (row.get('run'),row.get('id'))==(old.get('run'),old.get('id'))]
            if matches!=[old]:raise EvidenceUnavailable('source_drain_retained_handlers_changed')


def _preserve_drain_bytes(state,key,raw,maximum):
    from .solana_evidence_plane import EvidenceUnavailable
    encoded=raw.encode()
    if len(encoded)>maximum:raise EvidenceUnavailable('source_drain_retained_record_bound')
    archive=key+'_preserved.'+hashlib.sha256(encoded).hexdigest()
    prior=_retained_health(state,archive,maximum)
    if prior is not None and prior!=raw:
        raise EvidenceUnavailable('source_drain_preserved_record_conflict')
    if prior is None:state.writer.db.execute('INSERT INTO service_health VALUES(?,?)',(archive,raw))


def begin_source_observation(state,boundary,body,*,handler_boundary=None):
    """Retain a current RUNNING census before any provider admission."""
    from .solana_evidence_plane import EvidenceUnavailable
    with state.writer.transaction():
        previous=historical_observation_boundary(state)
        assert_source_drain_boundary(state,boundary,handler_boundary=handler_boundary)
        current=_retained_census(json.dumps(body))
        if (current['state']!='RUNNING' or current.get('terminal') is not False
                or current['pending_handlers'] or not _current_observation_identity(current)
                or not _observation_reference(current)):
            raise EvidenceUnavailable('source_observation_start_census_unverified')
        if previous.get('unreturned_observation_retained'):
            if (not isinstance(handler_boundary,str)
                    or hashlib.sha256(handler_boundary.encode()).hexdigest()!=PROGRAM_GAP_HANDLER_SHA256
                    and previous.get('session_economic_recovery_verified') is not True):
                raise EvidenceUnavailable('source_observation_program_gap_handler_boundary_required')
            failed=_health_from_db(state.writer.db,OBSERVATION_DRAIN_KEY,SOURCE_DRAIN_BYTES)
            if hashlib.sha256(failed.encode()).hexdigest()==PROGRAM_GAP_OBSERVATION_SHA256:
                _preserve_drain_bytes(state,OBSERVATION_DRAIN_KEY,failed,SOURCE_DRAIN_BYTES)
            _preserve_drain_bytes(state,HANDLER_RECOVERY_KEY,handler_boundary,HandlerLedger.maximum_bytes)
        if previous.get('economic_interval_recovered'):
            failed=_health_from_db(state.writer.db,OBSERVATION_DRAIN_KEY,SOURCE_DRAIN_BYTES)
            if hashlib.sha256(failed.encode()).hexdigest()==ECONOMIC_REPLAY_OBSERVATION_SHA256:
                _preserve_drain_bytes(state,OBSERVATION_DRAIN_KEY,failed,SOURCE_DRAIN_BYTES)
        if previous.get('session_economic_recovery_verified'):
            failed=_retained_health(state,OBSERVATION_DRAIN_KEY,SOURCE_DRAIN_BYTES)
            if _retained_census(failed)['state']=='RECOVERY_REQUIRED':
                _preserve_drain_bytes(state,OBSERVATION_DRAIN_KEY,failed,SOURCE_DRAIN_BYTES)
            _preserve_drain_bytes(state,HANDLER_RECOVERY_KEY,handler_boundary,HandlerLedger.maximum_bytes)
            current['session_economic_recovery_references']=previous['session_economic_recovery_references']
        state.fence._health(OBSERVATION_DRAIN_KEY,current)
        return _retained_health(state,OBSERVATION_DRAIN_KEY,SOURCE_DRAIN_BYTES)


def publish_source_drain(state,boundary,body,*,handler_boundary=None,
        contained_observation=False,observation_boundary=None):
    """Publish this run atomically without hiding its retained historical drain."""
    with state.writer.transaction():
        if contained_observation:
            from .solana_evidence_plane import EvidenceUnavailable
            # Current teardown may legitimately preserve its own new replay
            # obligation. Record it honestly; only a subsequent start demands
            # that the original canonical recovery mechanism has completed it.
            _historical_observation_record(state.writer.db,check_control=False)
            assert_source_drain_boundary(state,boundary,handler_boundary=handler_boundary)
            current=_retained_health(state,OBSERVATION_DRAIN_KEY,SOURCE_DRAIN_BYTES)
            if observation_boundary is None or current!=observation_boundary:
                raise EvidenceUnavailable('source_observation_current_boundary_changed')
            started=_retained_census(current)
            if (started['state']!='RUNNING' or not _observation_reference(body)
                    or any(started.get(key)!=body.get(key) for key in ('source_pid','run_identity'))):
                raise EvidenceUnavailable('source_observation_current_identity_changed')
            if started.get('session_economic_recovery_references'):
                body=dict(body,session_economic_recovery_references=started['session_economic_recovery_references'])
            _retained_census(json.dumps(body))
            state.fence._health(OBSERVATION_DRAIN_KEY,body)
            return
        retained_source_drain(state)
        assert_source_drain_boundary(state,boundary,handler_boundary=handler_boundary)
        if boundary is not None:
            old=_retained_census(boundary)
            if old['state']!='DRAINED' or old['pending_handlers']:
                _preserve_drain_bytes(state,SOURCE_DRAIN_KEY,boundary,SOURCE_DRAIN_BYTES)
        if handler_boundary is not None:
            _preserve_drain_bytes(state,HANDLER_RECOVERY_KEY,handler_boundary,HandlerLedger.maximum_bytes)
        state.fence._health(SOURCE_DRAIN_KEY,body)


class HandlerLedger:
    """Only active/interrupted callbacks, not another market-event journal.

    Successful callbacks are counted and removed. Returning a callback is not
    a durable commit: queue and session fences remain independently mandatory.
    """
    maximum_records=64
    maximum_bytes=48*1024

    def __init__(self,run):
        self.run=run;self.accepted=0;self.returned=0;self.records={};self.tasks={}
        self.valid=True;self.pid=os.getpid();self.native_thread_id=threading.get_native_id()

    def accept(self,stream,session,transport,family,kind,seen,*,slot=None,identity=None,scopes=()):
        from .solana_evidence_plane import EvidenceUnavailable
        if len(self.records)>=self.maximum_records or (identity is not None and (not isinstance(identity,str) or len(identity)>128)):
            self.valid=False;raise EvidenceUnavailable('source_handler_record_bound')
        self.accepted+=1;number=self.accepted
        row=dict(id=number,stream=stream,session=session,transport=transport,
            family=family,kind=kind,slot=slot,identity=identity,seen=seen,
            scope_hash=self.scope_hash(scopes),scope_count=len(set(scopes)),
            started_monotonic=time.monotonic(),phase='HANDLER',state='ACTIVE')
        self.records[number]=row;self.tasks[asyncio.current_task()]=number
        return number

    def phase(self,phase,**facts):
        if not isinstance(phase,str) or not phase.isidentifier() or len(phase)>40 or set(facts)-{'slot','identity','scope'}:
            raise ValueError('source_handler_phase')
        if 'identity' in facts and (not isinstance(facts['identity'],str) or len(facts['identity'])>128):raise ValueError('source_handler_identity')
        if 'scope' in facts:
            scope=facts.pop('scope');facts.update(scope_hash=self.scope_hash((scope,)),scope_count=1)
        number=self.tasks.get(asyncio.current_task())
        if number is not None:self.records[number].update(phase=phase,**facts)

    @staticmethod
    def scope_hash(scopes):
        return hashlib.sha256(json.dumps(sorted(set(scopes)),separators=(',',':')).encode()).hexdigest()

    def finish(self,number):
        self.records.pop(number);self.returned+=1
        self.tasks.pop(asyncio.current_task(),None)

    def fail(self,number,error):
        # Never include third-party text, expanded SQL, raw packets or secrets.
        row=self.records[number];row['state']='INTERRUPTED' if isinstance(error,asyncio.CancelledError) else 'FAILED'
        row['failure_state']=row['state']
        row['error_type']=type(error).__name__[:64]
        self.tasks.pop(asyncio.current_task(),None)

    def pending(self,session):
        return [dict(row) for row in self.records.values() if row['session']==session and row['state']!='ACTIVE']

    def preserved(self,rows):
        for row in rows:
            current=self.records.get(row['id'])
            if current is not None:current.update(state=row['state'],recovery=row.get('recovery'))

    def snapshot(self):
        rows=[dict(r) for r in self.records.values()]
        size=len(json.dumps(rows,separators=(',',':')).encode())
        if size>self.maximum_bytes:self.valid=False
        return dict(version=1,run=self.run,pid=self.pid,native_thread_id=self.native_thread_id,
            valid=self.valid,accepted=self.accepted,returned=self.returned,
            active=sum(r['state']=='ACTIVE' for r in rows),
            recoverable=sum(r['state']=='RECOVERABLE' for r in rows),
            failed=sum(r['state']=='FAILED' for r in rows),
            unresolved=sum(r['state']=='INTERRUPTED' for r in rows),
            records=rows if size<=self.maximum_bytes else None,record_bytes=size,
            scope='RETURNED_CALLBACKS_REQUIRE_SEPARATE_QUEUE_COMMIT_AND_SESSION_RECOVERY_FENCES')


def preserve_handlers(state,ledger,rows,recovery):
    """Atomically associate interrupted identities with existing durable gaps.

    This is a bounded diagnostic/recovery locator in existing canonical health,
    never a coverage proof or a second acquisition/monetary authority. Old rows
    are retained; this function cannot clear them on a prospective head jump.
    """
    if not rows:return []
    from .solana_evidence_plane import EvidenceUnavailable,canonical
    with state.writer.transaction():
        prior=state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(HANDLER_RECOVERY_KEY,)).fetchone()
        body=json.loads(prior[0]) if prior else dict(version=1,records=[])
        if body.get('version')!=1 or not isinstance(body.get('records'),list):
            raise EvidenceUnavailable('source_handler_recovery_corrupt')
        records={(r['run'],r['id']):r for r in body['records']}
        retained=[]
        for row in rows:
            item=dict(row,run=ledger.run,source_pid=ledger.pid,native_thread_id=ledger.native_thread_id)
            valid_slot=type(row.get('slot')) is int and row['slot']>0
            if valid_slot and recovery is not None:
                verified=False
                if recovery.get('kind')=='CONTROL_REPLAY':
                    current=state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(CONTROL_RECOVERY_KEY,)).fetchone()
                    required=control_recovery(current[0]) if current else None
                    verified=(required is not None and recovery==dict(kind='CONTROL_REPLAY',**required)
                        and required['lower_slot']<=row['slot']<=required['upper_slot']
                        and row.get('scope_count')==1 and row.get('scope_hash')==ledger.scope_hash(('control:solana',)))
                elif recovery.get('kind')=='CANDIDATE_GAPS':
                    ids=recovery.get('gap_ids')
                    if isinstance(ids,list) and 0<len(ids)<=48 and all(type(i) is int and i>0 for i in ids):
                        gaps=[state.writer.db.execute('SELECT scope,lo,hi FROM candidate_gaps WHERE id=?',(i,)).fetchone() for i in ids]
                        verified=(all(g is not None and g[1]<=row['slot'] and (g[2] is None or row['slot']<=g[2]) for g in gaps)
                            and row.get('scope_count')==len({g[0] for g in gaps if g is not None})
                            and row.get('scope_hash')==ledger.scope_hash(g[0] for g in gaps if g is not None))
                if not verified:raise EvidenceUnavailable('source_handler_recovery_unverified')
                item.update(state='RECOVERABLE',recovery=recovery)
            else:item.update(recovery=None)
            key=(ledger.run,row['id']);old=records.get(key)
            if old is not None and old!=item:raise EvidenceUnavailable('source_handler_recovery_conflict')
            records[key]=item;retained.append(item)
        body=dict(version=1,records=list(records.values()))
        if len(records)>ledger.maximum_records or len(canonical(body).encode())>ledger.maximum_bytes:
            raise EvidenceUnavailable('source_handler_record_bound')
        state.fence._health(HANDLER_RECOVERY_KEY,body)
        return retained


async def finish_owned(task,deadline):
    """A repeated coordinator cancel cannot cut its one owned teardown in half.

    The existing source shutdown deadline still ends this wait. A timeout is a
    failed drain, never permission to return a successful terminal census.
    """
    while True:
        remaining=deadline-asyncio.get_running_loop().time()
        if remaining<=0:
            task.cancel()
            raise TimeoutError('source_owned_drain_deadline')
        try:return await asyncio.wait_for(asyncio.shield(task),remaining)
        except TimeoutError:
            if not task.done():task.cancel()
            raise
        except asyncio.CancelledError:
            if task.done():return task.result()


def control_recovery(raw):
    """An acquisition obligation, never a substitute for canonical coverage."""
    if raw is None:return None
    try:
        value=json.loads(raw)
        if value is None:return None
        lo,hi,after=(value[name] for name in ('lower_slot','upper_slot','coverage_after_id'))
        if (type(lo) is not int or type(hi) is not int or type(after) is not int
                or not 1<=lo<=hi or after<0):raise ValueError()
        return dict(lower_slot=lo,upper_slot=hi,coverage_after_id=after)
    except (ValueError,TypeError,KeyError):
        from .solana_evidence_plane import EvidenceUnavailable
        raise EvidenceUnavailable('control_recovery_obligation_invalid') from None


def preserve_control_recovery(state,lower,upper):
    """The existing canonical owner records the exact unfinished source range."""
    with state.writer.transaction():
        row=state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(CONTROL_RECOVERY_KEY,)).fetchone()
        prior=control_recovery(None if row is None else row[0])
        after=state.writer.db.execute('SELECT COALESCE(MAX(id),0) FROM coverage').fetchone()[0]
        value=dict(lower_slot=lower,upper_slot=upper,coverage_after_id=after)
        if prior:
            value=dict(lower_slot=min(lower,prior['lower_slot']),upper_slot=max(upper,prior['upper_slot']),
                coverage_after_id=min(after,prior['coverage_after_id']))
        state.fence._health(CONTROL_RECOVERY_KEY,value)
        return value


def complete_control_recovery(state,scope):
    """Clear only after newly authenticated coverage spans the whole obligation.

    A later newest head, an old coverage row, or a partial replay cannot clear
    this floor. The coverage writer retains its original proof validation.
    """
    row=state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(CONTROL_RECOVERY_KEY,)).fetchone()
    required=control_recovery(None if row is None else row[0])
    if required is None:return None
    cursor=required['lower_slot']
    rows=state.writer.db.execute('''SELECT lo,hi FROM coverage WHERE scope=? AND id>?
        AND lo<=? AND hi>=? ORDER BY lo,hi LIMIT 512''',
        (scope,required['coverage_after_id'],required['upper_slot'],cursor))
    for lo,hi in rows:
        if lo>cursor:break
        cursor=max(cursor,hi+1)
        if cursor>required['upper_slot']:
            state.fence._health(CONTROL_RECOVERY_KEY,None)
            return None
    if cursor>required['lower_slot']:
        # Bound one owner turn, but retain durable progress across pages. This
        # advances only the *acquisition obligation*, after real contiguous
        # coverage; it never advances a canonical checkpoint or skips a hole.
        required=dict(required,lower_slot=cursor)
        state.fence._health(CONTROL_RECOVERY_KEY,required)
    return required

INTAKE_CLOSED=object()


async def receive_until_closed(receive,stop,*,closed_task=None):
    """Wake an idle socket on stop; finish a read already delivered in the race."""
    read=asyncio.create_task(receive());closed=closed_task or asyncio.create_task(stop.wait())
    try:
        await asyncio.wait((read,closed),return_when=asyncio.FIRST_COMPLETED)
        return read.result() if read.done() else INTAKE_CLOSED
    finally:
        cleanup=(read,) if closed_task is not None else (read,closed)
        for task in cleanup:
            if not task.done():task.cancel()
        await asyncio.gather(*cleanup,return_exceptions=True)


class StopEither:
    def __init__(self,*events):self.events=events
    def is_set(self):return any(event.is_set() for event in self.events)
    async def wait(self):
        tasks=[asyncio.create_task(event.wait()) for event in self.events]
        try:await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)


async def next_owned(queue,producer_done):
    """Return an admitted item, or None only after its producer has settled."""
    if producer_done.is_set() and queue.empty():return None
    get=asyncio.create_task(queue.get());closed=asyncio.create_task(producer_done.wait())
    try:
        await asyncio.wait((get,closed),return_when=asyncio.FIRST_COMPLETED)
        # A simultaneous close cannot take an already delivered item away.
        if get.done():return get.result()
        get.cancel();await asyncio.gather(get,return_exceptions=True)
        return None if queue.empty() else queue.get_nowait()
    finally:
        for task in (get,closed):
            if not task.done():task.cancel()
        await asyncio.gather(get,closed,return_exceptions=True)


async def join_owned(queue,worker):
    """A failed consumer cannot leave an unfulfillable queue.join hanging."""
    joined=asyncio.create_task(queue.join())
    try:
        done,_=await asyncio.wait((joined,worker),return_when=asyncio.FIRST_COMPLETED)
        if worker in done:
            worker.result()
            if not joined.done():
                # task_done releases join's waiter on the next event-loop turn.
                await asyncio.sleep(0)
                if not joined.done():raise RuntimeError('source_commit_stopped_with_pending_frames')
        await joined
    finally:
        if not joined.done():joined.cancel()
        await asyncio.gather(joined,return_exceptions=True)


async def settle_owned(producers,consumers):
    """Settle handlers while watching consumers which can free their capacity.

    A consumer may fail *after* shutdown began. Waiting only on producers in
    that case would deadlock a producer's capacity-blocked final put.
    """
    pending=set(producers);watch=pending|set(consumers)
    while pending:
        done,_=await asyncio.wait(watch,return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task in consumers and (task.cancelled() or task.exception() is not None):
                for producer in pending:
                    if not producer.done():producer.cancel()
        pending.difference_update(done);watch.difference_update(done)
    return await asyncio.gather(*producers,return_exceptions=True)


class AcceptedQueue(asyncio.Queue):
    """The existing FIFO plus a census which includes its owner-held batch."""
    def __init__(self,maxsize,changed):
        super().__init__(maxsize=maxsize);self.changed=changed
    async def put(self,item):
        await super().put(item);self.changed(1,0)
    def committed(self,rows):
        for _ in rows:self.task_done()
        self.changed(0,len(rows))
