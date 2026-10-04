"""Prospective independent natural cohort for Pons Selective Continuation v1.

The cohort does not read or write any other strategy's state.  It owns a dedicated
result directory, dedicated wallet-skill ledger, dedicated paper databases, policy
hash, qualification rows and lifecycle outcomes.
"""
from concurrent.futures import ThreadPoolExecutor, Future
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

from . import BoundaryError
from .abi import topic
from meme_machine.runtime.robinhood.pons import Broker, durable_cache, plane_path, save_cohort_checkpoint, recover_cohort, provider_totals
from .pipeline import Pipeline,censor_class
from .provider_admission import foreground_work
from .pons_natural_observation import (
    _current_curve_events, _next_discovery_end as _next_single_discovery_end,
)
from .provider_topology import configured_discovery_rpc
from .sequencer_feed import SequencerBlockClock, SequencerTransportError
from .pons_selective_acquisition import (
    SelectiveEvidenceContext, authenticated_early_rejection,
    evaluate_candidate, public_evaluation,
)
from .pons_selective_continuation import (
    POLICY, POLICY_HASH, REENTRY_POLICY, reentry_regime_reset, wallet_convergence,
)
from .pons_selective_paper import (
    STRATEGY_CAPITAL_QUOTE, STRATEGY_NAMESPACE, run_lifecycle,
)
from .pons_selective_wallets import WalletSkillBook

REPORT=Path(os.environ.get(
    "MM_PONS_SELECTIVE_COHORT_REPORT","pons-selective-continuation-v1-cohort.json"
))
ROOT=Path(os.environ.get(
    "MM_PONS_SELECTIVE_COHORT_DIR","pons-selective-continuation-v1-cohort"
))
SKILL_DB=ROOT/"pons-selective-wallet-skill.sqlite"

COHORT_TARGET=100
MAX_ENROLLED=20_000
DISCOVERY_SECONDS=int(os.environ.get("MM_PONS_SELECTIVE_DISCOVERY_SECONDS","14400"))
if not 60<=DISCOVERY_SECONDS<=14_400:
    raise BoundaryError("invalid_pons_selective_discovery_seconds")
TAPE_WARM_SECONDS=65
TAPE_WARM_REQUIRED_CHAIN_SECONDS=60
TAPE_WARM_MAX_SECONDS=120
MAX_TAPE_EVENTS=40_000

def _warmup_state(start_ts,latest_ts,wall_seconds):
    covered=max(0,int(latest_ts or 0)-int(start_ts))
    wall=max(0.0,float(wall_seconds))
    return dict(
        covered_seconds=covered,
        ready=(wall>=TAPE_WARM_SECONDS
               and covered>=TAPE_WARM_REQUIRED_CHAIN_SECONDS),
        exhausted=wall>=TAPE_WARM_MAX_SECONDS,
    )
MAX_CONCURRENT_LIFECYCLES=8
MIN_REEVALUATION_SECONDS=2.0
POLL_SECONDS=0.5
# Bound transport batching; every logical log read retains the ten-block ceiling.
DISCOVERY_BATCH_RANGES=4
DISCOVERY_RANGE_BLOCKS=10
DISCOVERY_RANGE_EVENTS=1000
CHECKPOINT_SECONDS=15.0
SEQUENCER_RECONNECT_ATTEMPTS=5
SEQUENCER_RECONNECT_SLEEP_SECONDS=0.5
PROVIDER_RECOVERY_ATTEMPTS=3
PROVIDER_RECOVERY_SLEEP_SECONDS=0.5
PROVIDER_RATE_LIMIT_ATTEMPTS=5
PROVIDER_RATE_LIMIT_BASE_SLEEP_SECONDS=2.0
RATE_LIMIT_PROVIDER_BOUNDARIES=frozenset((
    "provider_http_429",
    "provider_rpc_429",
))
LOCAL_CAPACITY_BOUNDARIES=frozenset((
    "provider_shared_admission_deadline",
    "provider_shared_queue_capacity",
))
RECOVERABLE_PROVIDER_BOUNDARIES=frozenset((
    "provider_http_500",
    "provider_http_502",
    "provider_http_503",
    "provider_http_504",
    "provider_transport_failure",
))
PROGRESS=ROOT/"cohort-progress.json"
ROWS_LOG=ROOT/"candidate-rows.jsonl"
QUALIFIERS_LOG=ROOT/"qualifiers.jsonl"
PROVIDER_LOG=ROOT/"provider-sessions.jsonl"
RECOVERY_LOG=ROOT/"sequencer-recoveries.jsonl"


def _append_jsonl(path,row):
    from meme_machine.runtime.storage import jsonl_ring
    jsonl_ring(path,row)

def _atomic_json(path,row):
    raw=json.dumps(row,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>4_000_000:
        raise BoundaryError("selective_checkpoint_capacity")
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp,path)


def _enrolled_count(result):
    return result.get('archived_observations',{}).get('count',0)+len(result['rows'])


def _qualifier_count(result):
    return result.get('archived_trials',{}).get('qualifiers',0)+len(result['qualifiers'])


def _next_trial_index(result):
    return max([result.get('archived_trials',{}).get('next_index',0)]+[q['index']+1 for q in result['qualifiers']])


def _summary_snapshot(result):
    rejection_counts=dict(result.get('archived_observations',{}).get('rejections',{}))
    for row in result["rows"]:
        vector=row.get("vector") or {}
        for reason in vector.get("all_rejections") or []:
            rejection_counts[reason]=rejection_counts.get(reason,0)+1
    lifecycle_status_counts=dict(result.get('archived_trials',{}).get('lifecycle_status_counts',{}))
    realized=[]
    for life in result["lifecycles"]:
        status=life.get("status","unknown")
        lifecycle_status_counts[status]=lifecycle_status_counts.get(status,0)+1
        if life.get("realized_pnl_quote") is not None:
            realized.append(int(life["realized_pnl_quote"]))
    return dict(
        enrolled=_enrolled_count(result),
        qualified=_qualifier_count(result),
        qualifiers_with_wallet_convergence=result.get('archived_trials',{}).get('wallet_converged',0)+sum(
            bool(q["wallet_convergence"].get("converged"))
            for q in result["qualifiers"]
        ),
        lifecycle_status_counts=dict(sorted(lifecycle_status_counts.items())),
        rejection_counts=dict(sorted(rejection_counts.items())),
        realized_pnl_quote=realized,
        archived_realized_pnl_quote=result.get('archived_trials',{}).get('realized_pnl_quote',0),
        graduated_lifecycles=result.get('archived_trials',{}).get('graduated_lifecycles',0)+sum(
            bool(x.get("carried_through_graduation"))
            for x in result["lifecycles"]
        ),
    )


def _record_candidate_boundary(pipeline,identity,event,sequence,context,boundary,
                               *,dispatch,observed_monotonic,candidate_generation=None,record=None):
    """Retain quote failures while separating proven preflight vetoes from loss."""
    from functools import partial
    record=record or partial(pipeline.record,identity,candidate_generation=candidate_generation)
    evidence=getattr(context,'boundary_evidence',None)
    screen=authenticated_early_rejection(str(boundary),evidence)
    row=dict(timing=dict(context.timing),source_log_index=int(event['logIndex'],16),
        sequence=sequence,source_transaction=event.get('transactionHash'),
        source_block=event.get('blockNumber'),boundary=str(boundary))
    if screen is not None:
        reason='strategy_current_state:'+','.join(screen['reasons'])
        from meme_machine.runtime.robinhood.accounting import classify,screen_outcome
        classification=classify(screen_outcome(screen))[1]
        record('prospect_screened',reason,classification,
                        authenticated_evidence=screen['authenticated_evidence'])
        record('evidence_not_required')
        record('rejected',reason,classification)
        row.update(status='screened_out',screened_out=True,screened_stage='current_state',
            stale_stage=None,prospect_preflight=screen,causal_bucket=screen['causal_bucket'],
            vector=dict(complete=False,current_threshold_pass=False,
                qualification='strategy_prospect_screen',all_rejections=screen['reasons'],
                prospect_screen_only=True))
        return row
    stale_stage=('stale_in_queue' if dispatch-observed_monotonic>5 else
        'stale_during_evidence') if 'stale' in str(boundary) or 'admission_deadline' in str(boundary) else None
    if evidence and isinstance(evidence.get('decision_age_seconds'),(int,float)) and evidence['decision_age_seconds']>5:
        stale_stage='stale_during_evidence'
    reason=stale_stage or str(boundary)
    record('terminal',reason,censor_class(reason),timing=context.timing)
    row.update(status='incomplete',stale_stage=stale_stage,
               authenticated_boundary_evidence=evidence)
    return row


def _checkpoint(result,*,cursor,feed,rpc,phase):
    active_provider=rpc.telemetry()
    from meme_machine.runtime.pons_terminal_archive import retire_controller
    retire_controller(result)
    save_cohort_checkpoint(result,cursor,phase)
    snapshot=dict(
        kind="pons-selective-continuation-v1-checkpoint",
        namespace=STRATEGY_NAMESPACE,
        policy=POLICY,
        policy_hash=POLICY_HASH,
        independent_strategy=True,
        shared_allocator=False,
        live_money=False,
        checkpoint_at=time.time(),
        phase=str(phase),
        started_at=result["started_at"],
        canonical_discovery_cursor=int(cursor),
        summary=_summary_snapshot(result),
        survivor=result.get('survivor'),active_regimes=result.get('active_regimes'),
        discovery_sessions=list(result["discovery_sessions"][-16:]),
        discovery_session_count=len(result['discovery_sessions']),
        provider_session_archive=str(PROVIDER_LOG),
        active_discovery_provider=active_provider,
        sequencer_recoveries=list((result.get("sequencer_recoveries") or [])[-16:]),
        sequencer_recovery_count=len(result.get('sequencer_recoveries') or []),
        sequencer_recovery_archive=str(RECOVERY_LOG),
        cohort_accounting=_cohort_accounting() if (ROOT/'pons-selective-cohort-capital.sqlite').exists() else result.get('cohort_accounting'),
        sequencer_discovery=feed.status(),
        warmup=result.get("warmup"),
        target_reached=result.get("target_reached"),
        boundary=result.get("boundary"),
        evidence_queue=result.get('evidence_queue'),
        opportunity_coverage=result.get("opportunity_coverage"),
        evidence_acquisition=result.get('evidence_acquisition'),
        capacity_censored=result.get('capacity_censored',0),
        persisted_candidate_rows=len(result["rows"]),
        persisted_qualifiers=_qualifier_count(result),
    )
    _atomic_json(PROGRESS,snapshot)
    return snapshot


def _recover_sequencer(feed,cursor,recoveries):
    last=None
    for attempt in range(1,SEQUENCER_RECONNECT_ATTEMPTS+1):
        try:
            feed.reconnect()
            anchor=feed.wait_for_after(-1,timeout=5.0)
            if anchor is None:
                raise SequencerTransportError("sequencer_reconnect_no_anchor")
        except SequencerTransportError as exc:
            last=str(exc)
            if attempt<SEQUENCER_RECONNECT_ATTEMPTS:
                _stop_sleep(SEQUENCER_RECONNECT_SLEEP_SECONDS)
            continue
        row=dict(
            recovered_at=time.time(),
            attempt=attempt,
            canonical_cursor_before=int(cursor),
            sequencer_anchor=int(anchor),
            canonical_cursor_advanced=False,
            catchup_authority="authenticated_discovery_rpc",
            catchup_from=int(cursor)+1,
            catchup_to=int(anchor),
        )
        recoveries.append(row)
        _append_jsonl(RECOVERY_LOG,row)
        return int(anchor)
    raise BoundaryError("sequencer_reconnect_exhausted:"+str(last or "unknown"))


@foreground_work
def _discovery(endpoint):
    rpc=configured_discovery_rpc(endpoint,limit=200,per_scope=190,retries=0)
    rpc.verify_chain()
    return rpc


def _recoverable_provider_boundary(exc):
    boundary=str(exc)
    return (
        boundary in RECOVERABLE_PROVIDER_BOUNDARIES
        or boundary in RATE_LIMIT_PROVIDER_BOUNDARIES
        or boundary in LOCAL_CAPACITY_BOUNDARIES
    )


def _recover_discovery(
    endpoint,rpc,cursor,sessions,recoveries,*,on_failure=None,
):
    """Rotate only after a proven transient provider/session boundary."""
    boundary=str(getattr(rpc,"_last_boundary","") or "provider_session_failure")
    telemetry=dict(rpc.telemetry())
    telemetry["terminal_boundary"]=boundary
    sessions.append(telemetry)
    _append_jsonl(PROVIDER_LOG,telemetry)
    if on_failure is not None:
        on_failure(rpc,boundary,int(cursor))

    rate_limited=boundary in RATE_LIMIT_PROVIDER_BOUNDARIES
    capacity_limited=boundary in LOCAL_CAPACITY_BOUNDARIES
    pacer=getattr(rpc,"pacer",None)
    rps_before=(
        None if pacer is None
        else float(getattr(pacer,"requests_per_second",0) or 0)
    )
    if rate_limited and pacer is not None and rps_before:
        pacer.slow_to(max(1.0,rps_before/2.0))
    rps_after=(
        None if pacer is None
        else float(getattr(pacer,"requests_per_second",0) or 0)
    )

    last=boundary
    attempts=(
        PROVIDER_RATE_LIMIT_ATTEMPTS
        if rate_limited or capacity_limited else PROVIDER_RECOVERY_ATTEMPTS
    )
    for attempt in range(1,attempts+1):
        if rate_limited or capacity_limited:
            _stop_sleep(PROVIDER_RATE_LIMIT_BASE_SLEEP_SECONDS*attempt)
        elif attempt>1:
            _stop_sleep(PROVIDER_RECOVERY_SLEEP_SECONDS)
        try:
            replacement=_discovery(endpoint)
        except BoundaryError as exc:
            last=str(exc)
            if not _recoverable_provider_boundary(exc):
                raise
            if str(exc) in RATE_LIMIT_PROVIDER_BOUNDARIES:
                rate_limited=True
                attempts=max(attempts,PROVIDER_RATE_LIMIT_ATTEMPTS)
            continue
        row=dict(
            kind=("provider_rate_limit_recovery" if rate_limited else
                  "local_admission_recovery" if capacity_limited else "provider_recovery"),
            recovered_at=time.time(),
            attempt=attempt,
            boundary=boundary,
            canonical_cursor_before=int(cursor),
            canonical_cursor_advanced=False,
            catchup_authority="authenticated_discovery_rpc",
            catchup_from=int(cursor)+1,
            rate_limited=bool(rate_limited),local_capacity_limited=bool(capacity_limited),
            pacer_rps_before=rps_before,
            pacer_rps_after=rps_after,
        )
        recoveries.append(row)
        _append_jsonl(RECOVERY_LOG,row)
        return replacement
    raise BoundaryError("provider_recovery_exhausted:"+str(last))


def _next_discovery_end(feed,cursor,discovery,*,timeout):
    """Coalesce queued observation ranges within the original poll clock.

    This does not advance the authenticated discovery cursor. Only _poll can
    advance that cursor after every requested range has been acquired.
    """
    deadline=time.monotonic()+max(0.0,float(timeout))
    end=int(cursor)
    for _ in range(DISCOVERY_BATCH_RANGES):
        remaining=deadline-time.monotonic()
        if remaining<=0:
            break
        latest=_next_single_discovery_end(
            feed,end,discovery,timeout=remaining,
        )
        if latest is None:
            break
        latest=int(latest)
        if not end<latest<=end+DISCOVERY_RANGE_BLOCKS:
            raise BoundaryError("selective_discovery_range_identity")
        end=latest
    return end if end>int(cursor) else None


def _discovery_curve_events(rpc,start,end):
    """One physical batch of separate, bounded, contiguous log queries."""
    if end<start:
        return []
    if end-start+1>DISCOVERY_BATCH_RANGES*DISCOVERY_RANGE_BLOCKS:
        raise BoundaryError("selective_discovery_batch_capacity")
    if end-start+1<=DISCOVERY_RANGE_BLOCKS:
        return _current_curve_events(rpc,start,end)
    signatures=[
        topic("CurveBuy(address,address,uint256,uint256,uint256,uint256)"),
        topic("CurveSell(address,address,uint256,uint256,uint256,uint256)"),
    ]
    calls=[
        ("eth_getLogs",[dict(
            fromBlock=hex(first),
            toBlock=hex(min(end,first+DISCOVERY_RANGE_BLOCKS-1)),
            topics=[signatures],
        )])
        for first in range(start,end+1,DISCOVERY_RANGE_BLOCKS)
    ]
    pages=rpc.batch(calls,scope="pons_natural")
    if not isinstance(pages,list) or len(pages)!=len(calls):
        raise BoundaryError("selective_discovery_batch_shape")
    rows=[]
    for page in pages:
        if not isinstance(page,list):
            raise BoundaryError("selective_discovery_log_shape")
        if len(page)>DISCOVERY_RANGE_EVENTS:
            raise BoundaryError("natural_event_capacity")
        rows.extend(page)
    rows.sort(key=lambda event:(
        int(event["blockNumber"],16),int(event["transactionIndex"],16),
        int(event["logIndex"],16),
    ))
    return rows


def _single_block_range(rpc,start,end):
    rows=[]
    for block in range(int(start),int(end)+1):
        rows.extend(_current_curve_events(rpc,block,block))
    return rows


def _read_curve_range(rpc,first,observed_end):
    try:
        return observed_end,_discovery_curve_events(rpc,first,observed_end)
    except BoundaryError as exc:
        if str(exc)!="provider_rpc_-32602":
            raise
        frontier=int(
            rpc.call("eth_blockNumber",[],scope="pons_selective_frontier"),16
        )
        if frontier<first:
            return first-1,[]
        if frontier>=observed_end:
            return observed_end,_single_block_range(rpc,first,observed_end)
        observed_end=min(observed_end,frontier)
        return observed_end,_discovery_curve_events(rpc,first,observed_end)


@foreground_work
def _poll(
    endpoint,rpc,cursor,tape,feed,sessions,recoveries=None,
    on_provider_failure=None,
):
    if recoveries is None:
        recoveries=[]
    if rpc.used>150:
        try:replacement=_discovery(endpoint)
        except BoundaryError as exc:
            if not _recoverable_provider_boundary(exc):raise
            rpc._last_boundary=str(exc)
            rpc=_recover_discovery(endpoint,rpc,cursor,sessions,recoveries,
                on_failure=on_provider_failure)
        else:
            telemetry=rpc.telemetry()
            sessions.append(telemetry)
            _append_jsonl(PROVIDER_LOG,telemetry)
            rpc=replacement

    while True:
        try:
            latest=_next_discovery_end(feed,cursor,rpc,timeout=POLL_SECONDS)
            break
        except SequencerTransportError:
            _recover_sequencer(feed,cursor,recoveries)
            continue
        except BoundaryError as exc:
            if not _recoverable_provider_boundary(exc):
                raise
            rpc._last_boundary=str(exc)
            rpc=_recover_discovery(
                endpoint,rpc,cursor,sessions,recoveries,
                on_failure=on_provider_failure,
            )

    if latest is None:
        return rpc,cursor,[]
    first=cursor+1;fresh=[]
    if latest>=first:
        observed_end=latest
        while True:
            try:
                observed_end,fresh=_read_curve_range(rpc,first,observed_end)
                break
            except BoundaryError as exc:
                if not _recoverable_provider_boundary(exc):
                    raise
                rpc._last_boundary=str(exc)
                rpc=_recover_discovery(
                    endpoint,rpc,cursor,sessions,recoveries,
                    on_failure=on_provider_failure,
                )
        if observed_end<first:
            return rpc,cursor,[]
        tape.extend(fresh)
        if len(tape)>MAX_TAPE_EVENTS:
            del tape[:-MAX_TAPE_EVENTS]
        cursor=observed_end
    return rpc,cursor,fresh


def _attach_wallet_overlay(vector,skill_book):
    profiles=skill_book.profiles(asof=int(vector["asof"]))
    overlay=wallet_convergence(
        profiles,vector["demand"].get("recent_buy_groups",()),
        asof=int(vector["asof"]),candidate_related_groups=(),
    )
    vector["wallet_convergence"]=overlay
    return overlay


def _record_completed_lifecycle(result,life):
    from meme_machine.runtime.robinhood.pons import coalesce_lifecycle_rows
    merged=coalesce_lifecycle_rows(result['lifecycles']+[life])
    _append_jsonl(ROOT/'completed-lifecycles.jsonl',life)
    result['lifecycles']=merged


def _collect_completed(result,futures):
    remaining=[]
    for qindex,future in futures:
        if not future.done():
            remaining.append((qindex,future));continue
        try:
            life=future.result()
        except Exception as exc:
            life=dict(status="unexpected_boundary",boundary=type(exc).__name__)
        life["index"]=qindex
        _record_completed_lifecycle(result,life)
    return remaining


def _cohort_accounting():
    from .pons_selective_capital import CohortCapital
    return CohortCapital(ROOT/'pons-selective-cohort-capital.sqlite',STRATEGY_CAPITAL_QUOTE).reconcile()


def persist_terminal(result):
    """Retain the complete result durably and keep the terminal view bounded."""
    archive=ROOT/'complete-result.json.gz'
    with archive.open('wb') as file:
        with gzip.GzipFile(fileobj=file,mode='wb') as compressed:
            for piece in json.JSONEncoder(sort_keys=True,separators=(',',':')).iterencode(result):
                compressed.write(piece.encode())
        file.flush();os.fsync(file.fileno())
    with archive.open('rb') as file:checksum=hashlib.file_digest(file,'sha256').hexdigest()
    compact={k:v for k,v in result.items() if k not in (
        'rows','qualifiers','discovery_sessions','sequencer_recoveries','lifecycles')}
    compact['observation_archive']=dict(path=str(archive),sha256=checksum,complete=True,
        candidate_rows=len(result['rows']),qualifiers=len(result['qualifiers']),
        lifecycles=len(result['lifecycles']),provider_sessions=len(result['discovery_sessions']))
    compact['lifecycles']=[{k:v for k,v in life.items() if k in (
        'index','status','boundary','lifecycle_id','settlement_kind','final_position','reconciliation','realized_pnl_quote',
        'carried_through_graduation','capital_reconciliation')} for life in result['lifecycles']]
    raw=json.dumps(compact,sort_keys=True,separators=(',',':')).encode()
    if len(raw)>12_000_000:raise BoundaryError('selective_cohort_report_capacity')
    temporary=REPORT.with_suffix(REPORT.suffix+'.tmp')
    with temporary.open('wb') as file:file.write(raw);file.flush();os.fsync(file.fileno())
    os.replace(temporary,REPORT)
    return compact


def _window_observations(result):
    offset=result.get('autonomous_observation_offset',0)
    if type(offset) is not int or not 0<=offset<=len(result['rows']):
        raise BoundaryError('selective_window_observation_offset')
    return len(result['rows'])-offset


def run(endpoint,*,campaign=False):
    if type(campaign) is not bool:raise BoundaryError('selective_campaign_flag')
    ROOT.mkdir(parents=True,exist_ok=True)
    # Preserve existing evidence and lane capital on repeated invocation.
    occupied=list(ROOT.glob("trial-*.sqlite*"))
    occupied += [p for p in (PROGRESS,ROWS_LOG,QUALIFIERS_LOG,PROVIDER_LOG,RECOVERY_LOG,REPORT,
                            ROOT/"pons-selective-cohort-capital.sqlite") if p.exists()]
    recovered=(recover_cohort(plane_path(ROOT/"candidate-evidence.sqlite"),POLICY_HASH) if occupied else None)

    from .pons_selective_capital import CohortCapital
    CohortCapital(ROOT/'pons-selective-cohort-capital.sqlite',STRATEGY_CAPITAL_QUOTE).recover_shared_terminals(release_absent=True)
    initial_accounting=_cohort_accounting()
    started=time.time()
    result=dict(
        kind="pons-selective-continuation-v1-independent-cohort",
        namespace=STRATEGY_NAMESPACE,policy=POLICY,policy_hash=POLICY_HASH,
        independent_strategy=True,shared_allocator=False,live_money=False,
        cohort_target=COHORT_TARGET,max_enrolled=MAX_ENROLLED,continuous_campaign=campaign,
        cohort_accounting=initial_accounting,
        operational_configuration=dict(campaign=campaign,discovery_seconds=DISCOVERY_SECONDS,
            max_concurrent_lifecycles=MAX_CONCURRENT_LIFECYCLES,
            observation_capacity=MAX_ENROLLED,exhausted_capacity='continue_authenticated_discovery_and_censor'),
        market_observation_scope="all authenticated Pons V2 buy/sell logs for observability",
        selection_rule=(
            "distinct Pons V2 buys receive minimal current-state authentication; "
            "trajectory evaluation is admitted only when current ungraduated native-quote "
            "state satisfies profitability-v1 progress, snipe-tax and creator-tax; receipt-window "
            "reconstruction is admitted only after token-age, velocity, acceleration and ETA "
            "trajectory gates pass; friction and demand remain full qualification evidence; "
            "paper entry additionally requires a terminal/flat prior same-curve "
            "lifecycle plus a point-in-time regime reset; at most one screen per "
            "curve generation; repeated observations coalesce; no outcome reranking"
        ),
        reentry_policy=dict(REENTRY_POLICY),
        outcome_blind=True,reranking=False,replacement=False,
        wallet_skill_namespace=STRATEGY_NAMESPACE,
        strategy_capital_quote=_current_pons_realized_equity(),
        rows=[],qualifiers=[],lifecycles=[],discovery_sessions=[],
        sequencer_recoveries=[],evidence_acquisition=None,started_at=started,
    )

    if recovered:
        result=recovered
        from meme_machine.runtime.robinhood.pons import restore_position_needs
        from .pons_selective_recovery import submit_existing_lifecycles
        restore_position_needs(plane_path(ROOT/'candidate-evidence.sqlite'),ROOT/'pons-selective-cohort-capital.sqlite')
        result['cohort_accounting']=_cohort_accounting()
    result['candidate_plane_path']=str(plane_path(ROOT/'candidate-evidence.sqlite'))
    result['native_archive_paths']=dict(rows=str(ROWS_LOG),qualifiers=str(QUALIFIERS_LOG),
        lifecycles=str(ROOT/'completed-lifecycles.jsonl'),discovery_sessions=str(PROVIDER_LOG),
        sequencer_recoveries=str(RECOVERY_LOG))
    result['operational_configuration_hash']=hashlib.sha256(json.dumps(
        result['operational_configuration'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    skill=WalletSkillBook(str(SKILL_DB))
    pipeline=Pipeline(ROOT/"opportunity-pipeline.sqlite","pons",POLICY_HASH)
    queue=None
    def coverage(*,drain=False):
        if queue is not None:queue.report_to(pipeline,drain=drain)
        result["opportunity_coverage"]=pipeline.snapshot()
        result['capacity_censored']=result['opportunity_coverage']['unique_classes']['capacity_censored']
    rpc=_discovery(endpoint)
    survivor=None
    if os.environ.get('MM_DIRECTIONAL_COMPOSITE_REQUIRED')=='1':
        from meme_machine.runtime.survivor_history import Worker
        from .pons_survivor_runtime import Runtime
        run_id=os.environ['MM_PAPER_EPOCH']
        survivor=Worker(lambda:Runtime(ROOT/'pons-survivor',STRATEGY_CAPITAL_QUOTE,run_id,endpoint))
        result['active_regimes']=['pons-selective-continuation-v1','pons-postgrad-survivor-momentum-v1']
    feed=SequencerBlockClock();feed.connect()
    cursor=feed.wait_for_after(-1,timeout=5.0)
    if cursor is None:
        coverage();pipeline.close()
        skill.close();feed.close()
        raise BoundaryError("selective_sequencer_start_timeout")

    start_ts=feed.state.latest_header_timestamp
    if start_ts is None:
        coverage();pipeline.close()
        skill.close();feed.close()
        raise BoundaryError("selective_sequencer_timestamp_missing")
    tape=[]
    queue=Broker(plane_path(ROOT/'candidate-evidence.sqlite'),POLICY_HASH,clock=time.time,source=endpoint,config=result['operational_configuration_hash'])
    def record_work(identity,stage,reason=None,classification=None,**details):
        queue.report_to(pipeline,drain=True)
        generation=scheduled['work']['generation']
        with queue.plane.lock:
            if queue.plane.get(identity)['generation']!=generation:
                stage,reason,classification='candidate_superseded','obsolete_consumer_result','superseded_generation'
            return pipeline.record(identity,stage,reason,classification,
                                   candidate_generation=generation,**details)
    # Checkpointed effects dominate an outbox replay after a crash between the
    # checkpoint and acknowledgement. Native position authority remains separate.
    consumed={(row.get('candidate_identity'),row.get('candidate_generation')) for row in result['rows']}
    for pending,_value in queue.committed():
        if (pending['key'],pending['work']['generation']) in consumed:queue.acknowledge(pending)
    domain=hashlib.sha256(endpoint.encode()).hexdigest()+':'+POLICY_HASH
    evidence_context=SelectiveEvidenceContext(endpoint,cache=durable_cache(queue.plane,domain))
    hydration_pool=ThreadPoolExecutor(max_workers=1)
    discovery_pool=ThreadPoolExecutor(max_workers=1)
    discovery_future=None
    discovery_failures=[]
    hydration=None
    hydration_stages=[]
    hydration_started=None

    def _checkpoint_provider_failure(failed_rpc,boundary,current_cursor):
        result["last_transient_provider_boundary"]=str(boundary)
        _checkpoint(
            result,cursor=current_cursor,feed=feed,rpc=failed_rpc,
            phase="provider_recovery",
        )

    def _discover_observations(*args,**kwargs):
        discovered=_poll(*args,**kwargs)
        observed=time.time()
        for event in discovered[2]:
            is_buy=bool(event.get('topics') and event['topics'][0].lower()==topic(
                'CurveBuy(address,address,uint256,uint256,uint256,uint256)'))
            queue.enqueue(event,now=observed,needs_work=is_buy)
        return discovered

    pool=None;futures=[]
    try:
        pool=ThreadPoolExecutor(max_workers=MAX_CONCURRENT_LIFECYCLES)
        futures=[]
        active_curve_futures={}
        last_authorized_vector={r['curve']:r['vector'] for r in result['qualifiers']}
        last_terminal_by_curve={r['curve']:r for r in result['lifecycles'] if r.get('curve')}
        collected_futures=set()

        def collect_curve_future(curve):
            item=active_curve_futures.get(curve)
            if item is None:
                return None
            qindex,future=item
            if not future.done():
                return None
            try:
                life=future.result()
            except Exception as exc:
                life=dict(
                    index=qindex,status="unexpected_boundary",
                    boundary=type(exc).__name__,
                )
            life["index"]=qindex
            _record_completed_lifecycle(result,life)
            last_terminal_by_curve[curve]=life
            collected_futures.add(id(future))
            active_curve_futures.pop(curve,None)
            return life

        if recovered:
            for qindex,curve,future in submit_existing_lifecycles(endpoint,ROOT,
                    result['qualifiers'],result['lifecycles'],pool=pool):
                futures.append((qindex,future));active_curve_futures[curve]=(qindex,future)

        warm_started=time.monotonic()
        warm_min_deadline=warm_started+TAPE_WARM_SECONDS
        warm_hard_deadline=warm_started+TAPE_WARM_MAX_SECONDS
        covered=0
        while time.monotonic()<warm_hard_deadline:
            warm_state=_warmup_state(
                start_ts,feed.state.latest_header_timestamp,
                time.monotonic()-warm_started,
            )
            covered=warm_state["covered_seconds"]
            if warm_state["ready"]:
                break
            rpc,cursor,_=_poll(
                endpoint,rpc,cursor,tape,feed,result["discovery_sessions"],
                result["sequencer_recoveries"],
                on_provider_failure=_checkpoint_provider_failure,
            )
        wall_seconds=max(0.0,time.monotonic()-warm_started)
        warm_state=_warmup_state(
            start_ts,feed.state.latest_header_timestamp,wall_seconds,
        )
        covered=warm_state["covered_seconds"]
        result["warmup"]=dict(
            covered_seconds=covered,events=len(tape),end_block=cursor,
            wall_seconds=wall_seconds,
            required_chain_seconds=TAPE_WARM_REQUIRED_CHAIN_SECONDS,
            maximum_wall_seconds=TAPE_WARM_MAX_SECONDS,
            ready=warm_state["ready"],exhausted=warm_state["exhausted"],
        )
        _checkpoint(result,cursor=cursor,feed=feed,rpc=rpc,phase="warmup_complete")
        if covered<TAPE_WARM_REQUIRED_CHAIN_SECONDS:
            raise BoundaryError("selective_tape_warmup_incomplete")

        if 'discovery_ends_at' not in result:result['discovery_ends_at']=time.time()+DISCOVERY_SECONDS
        deadline=time.monotonic()+max(0,result['discovery_ends_at']-time.time())
        save_cohort_checkpoint(result,cursor,'discovery_ready')
        next_checkpoint=time.monotonic()+CHECKPOINT_SECONDS
        while (
            time.monotonic()<deadline
            and (campaign or (len(result["rows"])<MAX_ENROLLED
                              and _qualifier_count(result)<COHORT_TARGET))
        ):
            if discovery_future is None:
                discovery_future=discovery_pool.submit(_discover_observations,
                    endpoint,rpc,cursor,tape,feed,result['discovery_sessions'],
                    result['sequencer_recoveries'],
                    on_provider_failure=lambda *args:discovery_failures.append(args))
            fresh=[]
            if discovery_future.done():
                rpc,cursor,fresh=discovery_future.result();discovery_future=None
            while discovery_failures:_checkpoint_provider_failure(*discovery_failures.pop(0))
            if not fresh and (hydration is None or not hydration.done()):_stop_sleep(.005)
            for curve_key in list(active_curve_futures):
                collect_curve_future(curve_key)
            futures=[item for item in futures if id(item[1]) not in collected_futures]
            now=time.time()
            now_monotonic=time.monotonic()
            if survivor is not None:result['survivor']=survivor.tick(now,admit=True)
            for event in fresh:
                identity=(event["transactionHash"],event["logIndex"])
                is_buy=bool(event.get('topics') and event['topics'][0].lower()==topic(
                    "CurveBuy(address,address,uint256,uint256,uint256,uint256)"))
                # Every newer event updates the durable curve, including sells.
                # Only buys nominate qualification; sells fence an older buy.
                queue.enqueue(event,now=now,needs_work=is_buy)
                queue.report_to(pipeline,drain=True)
                current=queue.plane.get(queue.identity(event))
                if is_buy and current['latest_id']==event['transactionHash']+':'+event['logIndex']:
                    pipeline.record(queue.identity(event),'screened',candidate_generation=current['generation'])
                    pipeline.record(queue.identity(event),'current_state_queued',candidate_generation=current['generation'],first_observed_at=now,
                        original_deadline=now+5,sequencer_last_received_at=getattr(feed.state,'last_received_at',None))

            coverage()
            result['evidence_queue']=queue.telemetry()
            if time.monotonic()>=next_checkpoint:
                _checkpoint(
                    result,cursor=cursor,feed=feed,rpc=rpc,phase="discovery"
                )
                next_checkpoint=time.monotonic()+CHECKPOINT_SECONDS
            replayed=False
            if hydration is None:
                committed=next(queue.committed(),None)
                if committed is not None:
                    scheduled,value=committed
                    if queue.clock()>=scheduled['deadline']:
                        queue.plane.decision(scheduled['key'],scheduled['work']['generation'],
                            'freshness_deadline_censored','committed_result_expired_before_consumer')
                        queue.acknowledge(scheduled)
                        continue
                    hydration=Future();hydration.set_result(value)
                    replayed=True
                    hydration_stages=[];hydration_started=time.monotonic()
                    sequence=_enrolled_count(result);dispatch=time.monotonic()
                    observed_monotonic=dispatch-max(0,time.time()-scheduled['queued_at'])
            if hydration is None:
                scheduled=queue.pop(now=time.time())
                if scheduled is None:continue
                event=scheduled['event']
                observed_at=float(scheduled['queued_at'])
                elapsed=time.time()-observed_at
                if elapsed<0:raise BoundaryError('candidate_observation_clock_regression')
                observed_monotonic=time.monotonic()-elapsed
                identity=queue.identity(event)
                sequence=_enrolled_count(result)
                dispatch=time.monotonic()
                if campaign and _window_observations(result)>=MAX_ENROLLED:
                    queue.failure(scheduled,'selective_campaign_observation_capacity')
                    continue
                evidence_context.adjacent=list(queue.rows.values())
                evidence_context.generation_guard=lambda work=scheduled['work']:queue.plane.current(work)
                hydration_stages=[]
                hydration_started=time.monotonic()
                provider_before=provider_totals(evidence_context)
                record_work(identity,'current_state_requested',queue_wait_seconds=elapsed)
                def hydration_stage(stage,work=scheduled['work']):
                    hydration_stages.append(stage)
                    if stage=='trajectory_admitted' and queue.plane.promote(work):
                        from .provider_admission import _decision_priority
                        _decision_priority.set(10)
                hydration=hydration_pool.submit(
                    evaluate_candidate,endpoint,event,list(tape),
                    strategy_capital_quote=_current_pons_realized_equity(),
                    wallet_histories=None,creator_history=None,
                    evidence_observed_at=observed_at,
                    evidence_observed_monotonic=observed_monotonic,
                    evidence_context=evidence_context,
                    on_stage=hydration_stage)
                continue
            if not hydration.done():continue
            finished=hydration;hydration=None
            event=scheduled["event"]
            identity=queue.identity(event)
            try:
                evaluation=finished.result()
                from meme_machine.runtime.directional_sleeve import open_sleeve
                sleeve=open_sleeve('pons',STRATEGY_CAPITAL_QUOTE)
                if sleeve is not None:
                    try:sleeve.opportunity(evaluation['token'],identity=identity,regime='current',
                        status=evaluation['vector'].get('qualification','evaluated'),at=int(time.time()),
                        decision=dict(vector=evaluation['vector']))
                    finally:sleeve.close()

                provider_after=provider_totals(evidence_context)
                delta=[None if a is None or b is None else max(0,a-b) for a,b in zip(provider_after,provider_before)] if not replayed else [None,None]
                if not replayed and not queue.finish(scheduled,evaluation,time.monotonic()-hydration_started,logical=delta[0],physical=delta[1]):
                    continue
                for stage in hydration_stages:record_work(identity,stage)
                if evaluation.get("screened_out"):
                    screen=(evaluation.get("trajectory_preflight")
                            if evaluation.get("screened_stage")=="trajectory"
                            else evaluation.get("prospect_preflight")) or {}
                    reasons=screen.get("reasons") or ["strategy_prospect"]
                    queue.plane.decision(identity,scheduled["work"]["generation"],"strategy_rejected",",".join(reasons))
                    stage=evaluation.get("screened_stage") or "current_state"
                    reason="strategy_"+stage+":"+",".join(reasons)
                    record_work(identity,"prospect_screened",reason,"strategy_rejection")
                    record_work(identity,"evidence_not_required")
                    record_work(identity,"rejected",reason,"strategy_rejection")
                    coverage()
                    public=public_evaluation(evaluation)
                    public["candidate_identity"]=identity
                    public["candidate_generation"]=scheduled["work"]["generation"]
                    public["sequence"]=sequence
                    public["wallet_convergence"]=None
                    result["rows"].append(public)
                    result["evidence_acquisition"]=evidence_context.telemetry()
                    _append_jsonl(ROWS_LOG,public)
                    continue
                record_work(identity,'evidence_complete')
                record_work(identity,'evaluated')
                if evaluation.get('stale_stage'):
                    record_work(identity,'terminal',evaluation['stale_stage'],censor_class(evaluation['stale_stage']),timing=evaluation.get('timing'))
                elif evaluation['vector'].get('current_threshold_pass'):
                    record_work(identity,'qualified')
                else:record_work(identity,'rejected','strategy_rejection:'+','.join(evaluation['vector'].get('all_rejections') or ['unspecified']),'strategy_rejection')
                coverage()
                decision_state='qualified' if evaluation['vector'].get('current_threshold_pass') else 'strategy_rejected'
                if not queue.plane.decision(identity,scheduled['work']['generation'],decision_state):continue
                overlay=_attach_wallet_overlay(evaluation["vector"],skill)
                public=public_evaluation(evaluation)
                public["candidate_identity"]=identity
                public["candidate_generation"]=scheduled["work"]["generation"]
                public["sequence"]=sequence
                public["wallet_convergence"]=overlay
                authorization_rejection=None
                curve=evaluation["curve"]
                if evaluation["vector"].get("current_threshold_pass"):
                    completed=collect_curve_future(curve)
                    active=active_curve_futures.get(curve)
                    if active is not None and not active[1].done():
                        authorization_rejection="same_curve_lifecycle_active"
                    elif curve in last_authorized_vector:
                        terminal=last_terminal_by_curve.get(curve)
                        terminal_status=(terminal or {}).get("status")
                        terminal_reconciliation=(terminal or {}).get("reconciliation") or {}
                        terminal_flat=bool(
                            terminal_status in ("settled","entry_failed")
                            and int(terminal_reconciliation.get("open_exposure",0) or 0)==0
                        )
                        if not terminal_flat:
                            authorization_rejection="prior_curve_lifecycle_not_flat"
                        elif not reentry_regime_reset(
                            last_authorized_vector[curve],evaluation["vector"]
                        ):
                            authorization_rejection="reentry_regime_not_reset"
                if authorization_rejection is not None:
                    public["live_authorization"]="rejected"
                    public["authorization_rejection"]=authorization_rejection
                elif evaluation["vector"].get("current_threshold_pass"):
                    public["live_authorization"]="authorized"

                result["rows"].append(public)
                result["evidence_acquisition"]=evidence_context.telemetry()
                _append_jsonl(ROWS_LOG,public)
                if (
                    evaluation["vector"].get("current_threshold_pass")
                    and authorization_rejection is None
                ):
                    qindex=_next_trial_index(result)
                    qualifier=dict(
                        index=qindex,sequence=sequence,token=evaluation["token"],
                        curve=curve,
                        source_transaction=evaluation["source_transaction"],
                        vector=evaluation["vector"],
                        wallet_convergence=overlay,
                        live_authorization="authorized",
                    )
                    result["qualifiers"].append(qualifier)
                    _append_jsonl(QUALIFIERS_LOG,qualifier)
                    _checkpoint(
                        result,cursor=cursor,feed=feed,rpc=rpc,
                        phase="qualifier_persisted",
                    )
                    next_checkpoint=time.monotonic()+CHECKPOINT_SECONDS
                    if len(futures)>=MAX_CONCURRENT_LIFECYCLES:
                        life=dict(index=qindex,status='capacity_censored',
                            boundary='selective_concurrent_position_capacity',economic_rejection=False)
                        result['lifecycles'].append(life)
                        _append_jsonl(ROOT/'completed-lifecycles.jsonl',life)
                        continue
                    if not queue.plane.decision(identity,scheduled['work']['generation'],'entry_confirmation'):
                        continue
                    evaluation["candidate_plane_path"]=result["candidate_plane_path"]
                    evaluation["candidate_broker_identity"]=identity
                    evaluation["candidate_broker_generation"]=scheduled["work"]["generation"]
                    future=pool.submit(
                        run_lifecycle,endpoint,evaluation,
                        db_path=ROOT/f"trial-{qindex:03d}.sqlite",
                        capital_path=ROOT/"pons-selective-cohort-capital.sqlite",
                    )
                    futures.append((qindex,future))
                    active_curve_futures[curve]=(qindex,future)
                    last_authorized_vector[curve]=evaluation["vector"]
            except BoundaryError as exc:
                screen=authenticated_early_rejection(str(exc),getattr(evidence_context,'boundary_evidence',None))
                queue.failure(scheduled,str(exc),screen=screen)
                queue.report_to(pipeline,drain=True)
                if str(exc)=='candidate_generation_superseded' or queue.plane.get(identity)['generation']!=scheduled['work']['generation']:continue
                incomplete=_record_candidate_boundary(
                    pipeline,identity,event,sequence,evidence_context,str(exc),
                    dispatch=dispatch,observed_monotonic=observed_monotonic,
                    candidate_generation=scheduled['work']['generation'],
                    record=lambda stage,*args,**details:record_work(identity,stage,*args,**details))
                coverage()
                result["rows"].append(incomplete)
                result["evidence_acquisition"]=evidence_context.telemetry()
                _append_jsonl(ROWS_LOG,incomplete)
            finally:
                if queue.plane.get(scheduled['key']).get('result') is not None:
                    save_cohort_checkpoint(result,cursor,'candidate_consumed')
                    queue.acknowledge(scheduled)

        terminal_provider=rpc.telemetry()
        result["discovery_sessions"].append(terminal_provider)
        _append_jsonl(PROVIDER_LOG,terminal_provider)
        result["target_reached"]=_qualifier_count(result)>=COHORT_TARGET
        if not result["target_reached"]:
            result["boundary"]="selective_cohort_target_not_reached_in_bounded_window"

    except BoundaryError as exc:
        result["boundary"]=str(exc)
        terminal_provider=rpc.telemetry()
        result["discovery_sessions"].append(terminal_provider)
        _append_jsonl(PROVIDER_LOG,terminal_provider)
    finally:
        # Resolve any externally in-flight work; its durable generation still fences it.
        if survivor is not None:result['survivor']=survivor.close()
        discovery_pool.shutdown(wait=True)
        hydration_pool.shutdown(wait=True)
        if hydration is not None:
            try:
                tail=hydration.result()
                queue.finish(scheduled,tail,time.monotonic()-hydration_started)
            except BoundaryError as exc:queue.failure(scheduled,str(exc))
        if pool is not None:
            # Drain all admitted positions under their own frozen policy even if
            # discovery failed. No future may be discarded from terminal evidence.
            try:
                for qindex,future in futures:
                    if id(future) in collected_futures:
                        continue
                    try:life=future.result()
                    except Exception as exc:life=dict(status='unexpected_boundary',boundary=type(exc).__name__)
                    life['index']=qindex
                    _record_completed_lifecycle(result,life)
                    collected_futures.add(id(future))
                    _checkpoint(result,cursor=cursor,feed=feed,rpc=rpc,phase='position_drain')
            finally:pool.shutdown(wait=True)
        # Remaining queued observations retain their original clocks and an
        # explicit shutdown terminal, never a synthetic fresh evaluation.
        # Pending identities remain durable and measurable. No synthetic fresh clocks.
        queue.plane.recover()
        result['evidence_queue']=queue.telemetry()
        result['cohort_accounting']=_cohort_accounting()
        result["evidence_acquisition"]=evidence_context.telemetry()
        result["sequencer_discovery"]=feed.status()
        coverage(drain=True)
        _checkpoint(
            result,cursor=cursor,feed=feed,rpc=rpc,phase="finalizing"
        )
        pipeline.close()
        feed.close();skill.close();queue.close()

    result["lifecycles"].sort(key=lambda row:row.get("index",-1))
    counts=dict(result.get('archived_observations',{}).get('rejections',{}))
    for row in result["rows"]:
        vector=row.get("vector") or {}
        for reason in vector.get("all_rejections") or []:
            counts[reason]=counts.get(reason,0)+1
    statuses=dict(result.get("archived_trials",{}).get("lifecycle_status_counts",{}))
    returns=[]
    for life in result["lifecycles"]:
        status=life.get("status","unknown")
        statuses[status]=statuses.get(status,0)+1
        if life.get("realized_pnl_quote") is not None:
            returns.append(int(life["realized_pnl_quote"]))
    result["summary"]=dict(
        enrolled=_enrolled_count(result),
        qualified=_qualifier_count(result),
        qualifiers_with_wallet_convergence=result.get('archived_trials',{}).get('wallet_converged',0)+sum(
            bool(q["wallet_convergence"].get("converged"))
            for q in result["qualifiers"]
        ),
        lifecycle_status_counts=statuses,
        rejection_counts=dict(sorted(counts.items())),
        realized_pnl_quote=returns,
        archived_realized_pnl_quote=result.get("archived_trials",{}).get("realized_pnl_quote",0),
        graduated_lifecycles=result.get('archived_trials',{}).get('graduated_lifecycles',0)+sum(
            bool(x.get("carried_through_graduation"))
            for x in result["lifecycles"]
        ),
    )
    result["ended_at"]=time.time()
    return result



def _current_pons_realized_equity():
    from meme_machine.runtime.directional_sleeve import open_sleeve
    sleeve=open_sleeve('pons',STRATEGY_CAPITAL_QUOTE)
    if sleeve is None:return STRATEGY_CAPITAL_QUOTE
    try:return max(0,sleeve.sizing_basis(500)['realized_equity'])
    finally:sleeve.close()


if __name__=="__main__":
    output=run(os.environ.get("MM_ROBINHOOD_READ_RPC_URL",""))
    output=persist_terminal(output)
    print(json.dumps(dict(
        policy_hash=output["policy_hash"],boundary=output.get("boundary"),
        summary=output["summary"],
        elapsed_seconds=round(output["ended_at"]-output["started_at"],2),
    ),sort_keys=True))



def _stop_sleep(seconds):
    from meme_machine.runtime.stop import sleep
    return sleep(seconds,sleeper=time.sleep)
