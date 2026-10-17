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
    require(isinstance(handlers,str) and hashlib.sha256(handlers.encode()).hexdigest()==PROGRAM_GAP_HANDLER_SHA256)
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
    if current is not None:
        body=_retained_census(current)
        if not preserved_current and not economic_current and (not _observation_reference(body) or body['state']!='DRAINED'
                or body['pending_handlers'] or not _committed_census(body)
                or not _current_observation_identity(body)):
            raise EvidenceUnavailable('source_observation_current_drain_unresolved')
    elif program_gap or economic:raise EvidenceUnavailable('source_observation_current_drain_unresolved')
    return dict(eligible=True,historical_source_drain_sha256=HISTORICAL_OBSERVATION_SHA256,
        historical_unknown_handlers=2,historical_recovery_verified=False,
        source_drain_preserved_in_place=True,current_observation_state='PRESERVED_ECONOMIC_REPLAY' if economic_current else 'PRESERVED_PROGRAM_GAP' if preserved_current else 'ABSENT' if current is None else 'DRAINED',
        current_observation_sha256=None if current is None else hashlib.sha256(current.encode()).hexdigest(),**program_gap,**economic)


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
                    or hashlib.sha256(handler_boundary.encode()).hexdigest()!=PROGRAM_GAP_HANDLER_SHA256):
                raise EvidenceUnavailable('source_observation_program_gap_handler_boundary_required')
            failed=_health_from_db(state.writer.db,OBSERVATION_DRAIN_KEY,SOURCE_DRAIN_BYTES)
            if hashlib.sha256(failed.encode()).hexdigest()==PROGRAM_GAP_OBSERVATION_SHA256:
                _preserve_drain_bytes(state,OBSERVATION_DRAIN_KEY,failed,SOURCE_DRAIN_BYTES)
            _preserve_drain_bytes(state,HANDLER_RECOVERY_KEY,handler_boundary,HandlerLedger.maximum_bytes)
        if previous.get('economic_interval_recovered'):
            failed=_health_from_db(state.writer.db,OBSERVATION_DRAIN_KEY,SOURCE_DRAIN_BYTES)
            if hashlib.sha256(failed.encode()).hexdigest()==ECONOMIC_REPLAY_OBSERVATION_SHA256:
                _preserve_drain_bytes(state,OBSERVATION_DRAIN_KEY,failed,SOURCE_DRAIN_BYTES)
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
