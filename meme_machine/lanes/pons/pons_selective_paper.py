"""Independent paper lifecycle for Pons Selective Continuation v1.

Strategy authority, capital, state and results are private to this lane.  The only
shared components are neutral Pons protocol authentication, read-only provider,
finality and paper-execution primitives.  No continuation-v1, Ramses, Pump.fun or
other strategy signal/threshold/state is imported.
"""
from meme_machine.runtime.execution_capacity import resize


def _entry_capacity(metadata,amount,gas_quote):
    from .pons import CurveState
    from .pons_selective_continuation import roundtrip_loss_bps,ENTRY_THRESHOLDS
    from . import BoundaryError
    try:state=CurveState(**metadata['state'])
    except (KeyError,TypeError,ValueError):raise BoundaryError('selective_capacity_state_missing') from None
    return resize(amount,1,lambda n:roundtrip_loss_bps(state,n,int(gas_quote)*2),
                  ordinary_limit=ENTRY_THRESHOLDS['max_roundtrip_loss_bps'])
from dataclasses import asdict
import time
import uuid
from contextlib import nullcontext

from . import BoundaryError
from .provider_admission import position_work
from .position_sessions import PositionSessions
from .abi import topic, calldata
from .evidence import Store, digest, canonical
from .finality import Finality
from .pons_selective_capital import CohortCapital
from .pons_selective_ledger import SelectivePaper
from .pons import CurveState, curve_abi, raw_event
from .pons_natural_observation import _latest_header, _curve_state
from .pons_natural_paper import (
    _curve_quote as _native_curve_quote, _gas_quote, _gas_units, _graduation_transition,
    _rpc as paper_rpc, _wait_curve_quote as _native_wait_curve_quote,
    RESEARCH_RECIPIENT, _fresh_stamp, _ledger_for_quote,
)
from .pons_quotes import v4_quote as _v4_quote
from .pons_selective_acquisition import (
    _batched, _header_search, _rpc as evidence_rpc, _trajectory, SelectiveEvidenceContext,
)
from .pons_selective_continuation import (
    ENTRY_THRESHOLDS, EXIT_POLICY, POLICY, POLICY_HASH, demand_metrics,
    entry_signal_persistence, normalized_trade, post_graduation_vector,
    _buy_price_impact_bps, roundtrip_loss_bps,
    pregraduation_action, pregraduation_exit_reason,
    pregraduation_soft_deterioration, runner_action,
    runner_soft_deterioration, trajectory_metrics,
)
from .pons_selective_v4 import collect_v4_activity
from .pons_current_history import with_history

STRATEGY_NAMESPACE="pons-selective-continuation-v1"
STRATEGY_CAPITAL_QUOTE=10**18
ENTRY_SLIPPAGE_BPS=100
POST_GRAD_OBSERVE_SECONDS=10
POSITION_TRANSIENT_BOUNDARIES=frozenset((
    "provider_rpc_429","provider_http_429","provider_http_500",
    "provider_http_502","provider_http_503","provider_http_504",
    "provider_transport_failure","provider_shared_admission_deadline",
    "provider_shared_queue_capacity",
))


class _PinnedQuoteReads:
    """One fresh head plus one batch of the identical pinned execution reads.

    Called inside the native quote's original acquisition timer. Each retry gets
    a new head and cache; no timestamp/deadline or strategy economics is changed.
    """
    def __init__(self,rpc,curve,side):
        self.rpc=rpc;self.curve=curve;self.side=side;self.header=None;self.cache=None;self.snipe=None

    def call(self,method,params,*,scope):
        if method=='eth_getBlockByNumber' and params==['latest',False]:
            self.header=self.rpc.call(method,params,scope=scope);self.cache=None
            return self.header
        if self.header is None:raise BoundaryError('selective_quote_head_required')
        if self.cache is None:
            block=hex(int(self.header['number'],16))
            calls=[('eth_call',[dict(to=self.curve,data=calldata(sig)),block])
                for sig in ('getReserves()','realQuoteReserve()','reservedTokens()','graduated()')]
            calls.append(('eth_getBlockByNumber',[block,False]))
            if self.side=='buy':
                calls.append(('eth_call',[dict(to=self.curve,data=calldata('currentSnipeTaxBps(address)',RESEARCH_RECIPIENT)),block]))
            calls.append(('eth_gasPrice',[]))
            values=self.rpc.batch(calls,scope='pons_selective_paper_quote')
            if len(values)!=len(calls):raise BoundaryError('selective_quote_batch_incomplete')
            pinned=values[4]
            if any(pinned.get(k)!=self.header.get(k) for k in ('number','hash','parentHash','timestamp')):
                raise BoundaryError('selective_quote_header_changed')
            self.cache={canonical([m,p]):v for (m,p),v in zip(calls,values)}
        key=canonical([method,params])
        if key not in self.cache:raise BoundaryError('selective_quote_read_not_pinned')
        value=self.cache.pop(key)
        if method=='eth_call' and params[0].get('data')==calldata('currentSnipeTaxBps(address)',RESEARCH_RECIPIENT):
            self.snipe=int(value,16)
        return value


def _curve_quote(rpc,candidate,side,*args,**kwargs):
    return _native_curve_quote(_PinnedQuoteReads(rpc,candidate['curve'],side),candidate,side,*args,**kwargs)


def _wait_curve_quote(rpc,candidate,side,*args,**kwargs):
    pinned=_PinnedQuoteReads(rpc,candidate['curve'],side)
    quote,meta,ledger=_native_wait_curve_quote(pinned,candidate,side,*args,**kwargs)
    if side=='buy':meta['current_snipe_bps']=pinned.snipe
    return quote,meta,ledger


def _cancel_proven_unfilled(paper,identity,capital_guard,reason):
    """Release only a replay-proven zero-fill reservation, with a native cancel."""
    positions={p['id']:p for p in paper.positions()}
    position=positions.get(identity)
    if (position is None or position['status']!='reserved'
            or any(position.get(k)!=0 for k in ('tokens','entry_tokens','cost','remaining_cost','realized_proceeds'))):
        return None
    if not paper.accounting(identity)['replay_verified']:
        raise BoundaryError('selective_unfilled_cancel_replay_required')
    now=int(time.time())
    cancelled=paper.advance(identity,now=now,action='cancel',cancel_reason=reason)
    if capital_guard is not None:capital_guard.settle(identity,cancelled,at=now)
    return cancelled


def _fresh_fill_full_exit_check(entry_meta,tokens):
    """Execution-only invariant: a fresh paper fill cannot start already unexitable."""
    state=entry_meta.get("state")
    if not isinstance(state,dict):
        raise BoundaryError("selective_fill_state_missing")
    checked=CurveState(**state).sell(int(tokens))
    return dict(
        executable=True,tokens=int(tokens),
        gross_quote=int(checked["gross_quote"]),
        quote_out=int(checked["quote_out"]),
        real_quote=int(state["real_quote"]),
    )


def _prove_impossible_full_exit(rpc,candidate,position,store):
    """Reauthenticate full remaining exposure before a zero-proceeds writeoff.

    The native quote can reject its arithmetic before checking freshness. Its
    exception alone is therefore not a terminal accounting proof.
    """
    started=time.monotonic()
    pinned=_PinnedQuoteReads(rpc,candidate['curve'],'sell')
    header=_latest_header(pinned)
    state,_=_curve_state(pinned,candidate['curve'],int(header['number'],16),
                         candidate['auth'],candidate['report'])
    age=time.monotonic()-started
    stamp=_fresh_stamp(header,local_freshness_seconds=age)
    label='selective-writeoff-'+str(position['version'])
    _ledger_for_quote(store,stamp,header['parentHash'],label,
                      local_freshness_seconds=age)
    if state.graduated:
        raise BoundaryError('graduated_during_selective_exit')
    try:
        state.sell(int(position['tokens']))
    except BoundaryError as exc:
        if str(exc)!='impossible_full_position_exit':raise
    else:
        return None
    proof=dict(position_id=position['id'],position_version=position['version'],
               tokens=int(position['tokens']),state=asdict(state),stamp=asdict(stamp),
               acquisition_seconds=age,reason='impossible_full_position_exit',
               sale_proceeds=0,finality_scope='paper-'+label)
    store.put('selective_writeoff_proof',digest(proof),proof)
    return proof


def _position_return_bps(position,quote):
    basis=int(position.get("remaining_cost",position["cost"]))
    if basis<=0:
        raise BoundaryError("selective_position_basis")
    net=int(quote.amount_out)-int(quote.gas_quote)
    if position.get('scale_request'):
        from meme_machine.runtime.directional_continuation import reference_return
        return reference_return(net,position['tokens'],position['original_basis'],position['original_quantity'])
    return (net-basis)*10_000//basis


def _curve_logs(endpoint,curve,current_header,seconds=60,*,after_block=None):
    from .pons_current_history import _active
    history=_active.get()
    if history is None or after_block is not None:
        return _read_curve_logs(endpoint,curve,current_header,seconds,after_block=after_block)
    old=history.get(curve);block=int(current_header['number'],16);at=int(current_header['timestamp'],16)
    if old and block==old['block'] and current_header['hash']!=old['block_hash']:
        history.invalidate(curve,'pons_current_history_reorg')
        old=None
    if old is None:
        if seconds>60:raise BoundaryError('pons_current_history_not_caught_up')
        events,sessions=_read_curve_logs(endpoint,curve,current_header,seconds)
        history.remember(curve,current_header,events,from_time=max(0,at-seconds))
    elif block-old['block']>40 or at-old['through']>60:
        # A restart/provider gap never triggers a large urgent reconstruction.
        # Resume current safety flow immediately; the add's 900-second window
        # must accumulate again before it can grant scaling authority.
        history.invalidate(curve,'pons_current_history_observation_gap')
        events,sessions=_read_curve_logs(endpoint,curve,current_header,60)
        history.remember(curve,current_header,events,from_time=max(0,at-60))
    elif block>old['block']:
        try:
            events,sessions=_read_curve_logs(endpoint,curve,current_header,900,
                after_block=old['block'],expected_previous_hash=old['block_hash'])
        except BoundaryError as exc:
            if str(exc)!='pons_current_history_reorg':raise
            history.invalidate(curve,str(exc))
            events,sessions=_read_curve_logs(endpoint,curve,current_header,60)
            history.remember(curve,current_header,events,from_time=max(0,at-60))
        else:
            history.remember(curve,current_header,events,from_time=old['through'],delta_from=old['block'])
    else:sessions=[]
    result=history.facts(curve,current_header,seconds)
    history.maintain(time.time())
    return result,sessions


def _read_curve_logs(endpoint,curve,current_header,seconds=60,*,after_block=None,expected_previous_hash=None):
    current_block=int(current_header["number"],16)
    current_at=int(current_header["timestamp"],16)
    if after_block is None:
        locator=evidence_rpc(endpoint)
        cache={current_block:current_header}
        lower=max(0,current_at-int(seconds))
        start_block=(0 if lower==0 else int(_header_search(
            locator,current_block,current_at,lower-1,cache)['number'],16)+1)
        locator_telemetry=locator.telemetry()
    else:
        # One exact, bounded delta; never a new historical window or head search.
        start_block=int(after_block)+1
        if not 0<=current_block-int(after_block)<=256:
            raise BoundaryError("selective_entry_delta_block_capacity")
        locator_telemetry={}

    sigs=[
        topic("CurveBuy(address,address,uint256,uint256,uint256,uint256)"),
        topic("CurveSell(address,address,uint256,uint256,uint256,uint256)"),
    ]
    calls=[]
    if expected_previous_hash is not None:
        # Numeric, deliberately unpinned: an immutable old hash cannot prove
        # that the retained prefix still belongs to today's canonical chain.
        calls.append(('eth_getBlockByNumber',[hex(after_block),False]))
    chunk=10
    for first in range(start_block,current_block+1,chunk):
        calls.append(("eth_getLogs",[dict(
            fromBlock=hex(first),toBlock=hex(min(current_block,first+chunk-1)),
            address=curve,topics=[sigs],
        )]))
    batches,sessions=_batched(endpoint,calls,"pons_selective_monitor") if calls else ([],[])
    if expected_previous_hash is not None:
        previous=batches.pop(0)
        if (int(previous['number'],16)!=after_block or previous['hash']!=expected_previous_hash):
            raise BoundaryError('pons_current_history_reorg')
    if any(not isinstance(rows,list) for rows in batches):
        raise BoundaryError('selective_monitor_range_incomplete')
    raw=[]
    for rows in batches:
        raw.extend(rows)

    if after_block is not None and any(
            not start_block<=int(e["blockNumber"],16)<=current_block or e.get("removed")
            or e.get("address", "").lower()!=curve.lower() for e in raw):
        raise BoundaryError("selective_entry_delta_log_identity")
    hashes=list(dict.fromkeys(event["blockHash"] for event in raw))
    headers_v,more=_batched(
        endpoint,[("eth_getBlockByHash",[h,False]) for h in hashes],"pons_selective_monitor"
    ) if hashes else ([],[])
    sessions.extend(more);headers=dict(zip(hashes,headers_v))
    tx_rows=list(dict.fromkeys((e["transactionHash"],e["blockHash"]) for e in raw))
    # Reuse receipts only under the exact block hash authenticated below. Without
    # these pins every overlapping monitor window rehydrates the same bodies.
    context=SelectiveEvidenceContext(endpoint)
    for block_hash,header in headers.items():
        if header.get('hash')!=block_hash:
            raise BoundaryError('selective_monitor_header_identity')
    context.receipt_pins=dict(tx_rows)
    if len(context.receipt_pins)!=len(tx_rows):
        raise BoundaryError('selective_monitor_receipt_block_conflict')
    receipts_v,more=_batched(
        endpoint,[("eth_getTransactionReceipt",[tx]) for tx,_ in tx_rows],
        "pons_selective_monitor",evidence_context=context,
    ) if tx_rows else ([],[])
    sessions.extend(more)
    receipts={}
    for (tx,bh),receipt in zip(tx_rows,receipts_v):
        if receipt["transactionHash"]!=tx or receipt["blockHash"]!=bh:
            raise BoundaryError("selective_monitor_receipt_identity")
        receipts[(tx,bh)]=receipt

    out=[];observed=int(time.time())
    for event in raw:
        bh=event["blockHash"]
        row=raw_event(
            curve_abi(),event,address=curve,receipt=receipts[(event["transactionHash"],bh)],
            header=headers[bh],observed_at=observed,confirmation="confirmed",
        )
        at=int(row["event_at"])
        if current_at-int(seconds)<=at<=current_at:
            normalized=normalized_trade(
                row["decoded"],
                identity=f'{row["block"]}:{row["transaction_hash"]}:{row["log_index"]}',
                event_at=at,
            )
            normalized['canonical_order']=[row['block'],row['transaction_index'],row['log_index']]
            out.append(normalized)
    return out,[locator_telemetry]+sessions


def _refresh_curve_signal(endpoint,candidate,mark_meta,*,entry_evidence=None):
    current_state=CurveState(**mark_meta["state"])
    current_header=dict(
        number=hex(int(mark_meta["block"])),
        hash=mark_meta["block_hash"],
        timestamp=hex(int(mark_meta["event_at"])),
    )
    now_candidate=dict(candidate)
    now_candidate.update(
        block=int(mark_meta["block"]),header=current_header,state=current_state
    )
    snapshots,_,trajectory_session=_trajectory(endpoint,now_candidate)
    trajectory=trajectory_metrics(snapshots,int(mark_meta["event_at"]))
    events,sessions=_curve_logs(
        endpoint,candidate["curve"],current_header,seconds=60
    )
    creator_groups=(
        candidate["record"].get("deployer"),
        candidate["record"].get("creatorFeeRecipient"),
    )
    demand=demand_metrics(
        events,asof=int(mark_meta["event_at"]),creator_groups=creator_groups
    )
    if entry_evidence is not None:
        entry_evidence.update(events=events,frontier=dict(mark_meta),complete=True)
    return trajectory,demand,[trajectory_session]+sessions


def _refresh_entry_persistence_signal(endpoint,candidate,entry_meta):
    """Dedicated fill-time thesis revalidation hook.

    Production uses the same authenticated trajectory/demand acquisition as normal
    monitoring. Keeping the hook separate prevents recovery tests from conflating
    pre-entry persistence with deliberately injected post-entry provider failures.
    """
    evidence={}
    trajectory,demand,sessions=_refresh_curve_signal(
        endpoint,candidate,entry_meta,entry_evidence=evidence)
    return trajectory,dict(demand,_entry_evidence=evidence),sessions



def _entry_generation(evaluation):
    path=evaluation.get('candidate_plane_path')
    if path:
        from meme_machine.runtime.robinhood.plane import Plane
        plane=Plane(path)
        try:
            if not plane.decision(evaluation['candidate_broker_identity'],
                    evaluation['candidate_broker_generation'],'entry_confirmation'):
                raise BoundaryError('candidate_generation_superseded_before_entry')
        finally:plane.close()


def _confirm_entry_delta(endpoint,candidate,anchor,final,trajectory,demand,vector):
    """Authenticate only the interval after persistence, using immutable receipt reuse.

    Rolling rows alone do not prove interval completeness. The exact authoritative
    log query is mandatory when the quote frontier advances; no empty-cache proof.
    """
    first,last=int(anchor['block']),int(final['block'])
    if last<first or int(final['event_at'])<int(anchor['event_at']):
        raise BoundaryError('selective_entry_frontier_regression')
    if last==first:
        if any(final[k]!=anchor[k] for k in ('block_hash','event_at','state')):
            raise BoundaryError('selective_entry_frontier_conflict')
        return demand,[],dict(mode='same_authenticated_frontier',events_reused=0)
    evidence=demand.get('_entry_evidence',{})
    if (not evidence.get('complete') or evidence.get('frontier')!=anchor
            or last-first>256 or int(final['event_at'])-int(anchor['event_at'])>=60):
        raise BoundaryError('selective_entry_delta_unprovable')
    # Recheck both pins; a changed branch cannot extend authenticated history.
    headers,sessions=_batched(endpoint,[('eth_getBlockByNumber',[hex(n),False])
        for n in (first,last)],'pons_selective_entry_delta')
    if len(headers)!=2 or any(h.get('hash')!=m['block_hash']
            or int(h.get('number','-1'),16)!=m['block']
            or int(h.get('timestamp','-1'),16)!=m['event_at']
            for h,m in zip(headers,(anchor,final))):
        raise BoundaryError('selective_entry_delta_header_identity')
    events,more=_curve_logs(endpoint,candidate['curve'],headers[1],after_block=first)
    sessions.extend(more)
    asof=int(final['event_at'])
    retained=[r for r in evidence['events'] if asof-60<=int(r['event_at'])<=asof]
    current=demand_metrics(retained+events,asof=asof,creator_groups=(
        candidate['record'].get('deployer'),candidate['record'].get('creatorFeeRecipient')))
    verdict=entry_signal_persistence(vector,trajectory,current)
    if not verdict['persistent']:
        raise BoundaryError('entry_signal_decay:'+','.join(verdict['reasons']))
    return current,sessions,dict(mode='authenticated_incremental_delta',
        first_block=first+1,last_block=last,events_reused=len(retained),delta_events=len(events))


def _validate_final_entry(entry,meta,anchor_quote,amount,started_wall):
    if entry is anchor_quote or int(entry.stamp.observed_at)<int(started_wall):
        raise BoundaryError('selective_entry_quote_not_new')
    if any(meta.get(k)!=v for k,v in dict(block=entry.stamp.block,
            block_hash=entry.stamp.block_hash,event_at=entry.stamp.event_at,
            observed_at=entry.stamp.observed_at,amount_in=entry.amount_in,
            amount_out=entry.amount_out,gas_quote=entry.gas_quote).items()):
        raise BoundaryError('selective_entry_quote_metadata_identity')
    if meta.get('current_snipe_bps')!=0:
        raise BoundaryError('snipe_tax_nonzero')
    state=CurveState(**meta['state'])
    value=state.buy_with_snipe(amount,0)
    if state.graduated or value['refund'] or value['ready_to_graduate']:
        raise BoundaryError('selective_entry_structural_boundary')
    if value['tokens_out']!=entry.amount_out:
        raise BoundaryError('selective_entry_quote_state_identity')
    impact=_buy_price_impact_bps(state,amount)
    if impact is None or impact>ENTRY_THRESHOLDS['max_entry_impact_bps']:
        raise BoundaryError('selective_entry_impact')
    loss=roundtrip_loss_bps(state,amount,int(entry.gas_quote)*2)
    if loss is None or loss>ENTRY_THRESHOLDS['max_roundtrip_loss_bps']:
        raise BoundaryError('selective_entry_execution_economics')


def _delayed_exit(
    endpoint,*,paper,identity,rpc,candidate,gas_units,store,
    transition,v4_key,label,exit_tokens,
):
    pending=paper._get(identity)
    if pending["status"]=="open":
        paper.advance(
            identity,now=int(time.time()),action="exit_intent",exit_tokens=int(exit_tokens)
        )
        pending=paper._get(identity)
    elif (pending["status"]!="exit_pending" or
          int(pending.get("pending_exit_tokens") or 0)!=int(exit_tokens)):
        raise BoundaryError("selective_pending_exit_identity")
    # A retry resumes the existing intent, amount and due time; never a new exit.
    _stop_sleep(max(0,pending["due"]-int(time.time())))
    amount=int(pending["pending_exit_tokens"])
    if transition is None:
        try:
            quote,meta,ledger=_wait_curve_quote(
                rpc,candidate,"sell",amount,gas_units,store,label,
                pending["due"],seconds=20,local_freshness=True,
            )
        except BoundaryError as exc:
            if str(exc)!="curve_graduated_requires_transition":
                raise
            raise BoundaryError("graduated_during_selective_exit") from None
    else:
        deadline=time.monotonic()+20
        while True:
            quote,meta,ledger=_v4_quote(
                rpc,v4_key,pending["market"],amount,gas_units,store,label,
                local_freshness=True,
            )
            if quote.stamp.observed_at>=pending["due"]:
                break
            if time.monotonic()>=deadline:
                raise BoundaryError("selective_v4_delayed_exit_timeout")
            _stop_sleep(0.5)
    position=paper.advance(
        identity,now=quote.stamp.observed_at,action="exit",quote=quote,
        finality_ledger=ledger,
    )
    if position['status'] not in ('open','settled'):
        raise BoundaryError(position.get('reason') or 'selective_exit_not_realized')
    return position,meta


def _complete_pending_v4_exit(*,paper,identity,rpc,v4_key,gas_units,store,label):
    pending=paper._get(identity)
    if pending["status"]!="exit_pending":
        raise BoundaryError("selective_pending_exit_missing")
    amount=int(pending.get("pending_exit_tokens") or 0)
    if amount<=0:
        raise BoundaryError("selective_pending_exit_amount")
    deadline=time.monotonic()+20
    while True:
        quote,meta,ledger=_v4_quote(
            rpc,v4_key,pending["market"],amount,gas_units,store,label
        )
        if quote.stamp.observed_at>=pending["due"]:
            break
        if time.monotonic()>=deadline:
            raise BoundaryError("selective_pending_v4_exit_timeout")
        _stop_sleep(0.5)
    position=paper.advance(
        identity,now=quote.stamp.observed_at,action="exit",quote=quote,
        finality_ledger=ledger,
    )
    if position['status'] not in ('open','settled'):
        raise BoundaryError(position.get('reason') or 'selective_exit_not_realized')
    return position,meta


@position_work
@with_history
def _run_lifecycle(endpoint,evaluation,*,db_path,capital_path=None,_recovery=None,slice_seconds=None):
    deadline=time.monotonic()+slice_seconds if slice_seconds is not None else None
    vector=evaluation["vector"]
    if not vector.get("current_threshold_pass"):
        raise BoundaryError("selective_unqualified_lifecycle")
    if vector.get("policy_hash")!=POLICY_HASH:
        raise BoundaryError("selective_policy_hash_drift")

    candidate=evaluation["candidate"]
    result=dict(
        kind="pons-selective-continuation-v1-paper",
        namespace=STRATEGY_NAMESPACE,policy=POLICY,policy_hash=POLICY_HASH,
        independent_strategy=True,shared_allocator=False,paper_only=True,
        live_money=False,qualification_vector=vector,
        token=evaluation["token"],curve=evaluation["curve"],
        source_transaction=evaluation["source_transaction"],
        provider_sessions=[],monitor=[],started_at=time.time(),
    )
    store=None;rpc=None;capital_guard=None;identity=None
    def observe_commit(paper,position):
        if state is not None:state.acknowledge(position)
        if capital_guard is not None:capital_guard.observe(paper,position)
        path=evaluation.get('candidate_plane_path')
        if path:
            from meme_machine.runtime.robinhood.plane import project_native_position
            project_native_position(path,'pons',evaluation['candidate_broker_identity'],position,
                ledger_path=db_path,policy=POLICY_HASH)
    state=None
    try:
        if _recovery is None:
            gas_units=_gas_units(candidate["receipt"])
            rpc=paper_rpc(endpoint);rpc.verify_chain()
            initial_gas,gas_price=_gas_quote(rpc,gas_units)
            amount=int(vector["proposed_size"]["amount_quote"])
            if amount<=0:
                raise BoundaryError("selective_zero_entry")
            gas_budget=max(initial_gas*10,10**15)
            capital=max(STRATEGY_CAPITAL_QUOTE,amount+gas_budget)

            store=Store(str(db_path),max_records=8192)
            paper=SelectivePaper(
                store,STRATEGY_NAMESPACE,capital,
                delay=EXIT_POLICY["entry_delay_seconds"],
                natural_policy_hash=POLICY_HASH,
            )
            now=int(vector["evidence_available_at"])
            decision=dict(
                asof=now,market=candidate["curve"],authority="frozen_policy_paper",
                qualification="qualified",policy=POLICY,policy_hash=POLICY_HASH,
                strategy_namespace=STRATEGY_NAMESPACE,shared_allocator=False,
                source_transaction=evaluation["source_transaction"],
                token=evaluation["token"],outcome_used_for_selection=False,
            )
            identity=(
                "pons-selective:"+(digest(dict(candidate=evaluation['candidate_broker_identity'],generation=evaluation['candidate_broker_generation']))
                    if 'candidate_broker_identity' in evaluation else str(uuid.uuid4()))+":"+evaluation["token"]+":"+
                evaluation["source_transaction"]
            )
            from meme_machine.runtime.lifecycle_identity import issue
            identity=issue(identity)
            result["lifecycle_id"]=identity
            if evaluation.get('candidate_plane_path'):
                from meme_machine.runtime.robinhood.plane import Plane
                plane=Plane(evaluation['candidate_plane_path'])
                try:
                    if not plane.decision(evaluation['candidate_broker_identity'],
                            evaluation['candidate_broker_generation'],'entry_reserved',
                            native_reservation_intent=identity,native_ledger=str(db_path)):
                        raise BoundaryError('candidate_generation_superseded_before_reservation')
                finally:plane.close()
            if capital_path is not None:
                capital_guard=CohortCapital(capital_path,STRATEGY_CAPITAL_QUOTE)
                result["cohort_reservation"]=capital_guard.reserve(
                    identity,amount+gas_budget,at=now,
                    decision_hash=digest(decision),trial_path=db_path,
                    native_reservation_intent=dict(market=candidate['curve'],amount=amount,
                        gas_budget=gas_budget,now=now,features=decision,kind='natural'),
                )
            paper.on_commit=observe_commit
            reserved=paper.reserve(
                identity,market=candidate["curve"],amount=amount,gas_budget=gas_budget,
                now=now,features=decision,kind="natural",
            )
            result["reservation"]=reserved
            reference=candidate["state"].buy_with_snipe(amount,0)
            if reference["refund"] or reference["ready_to_graduate"]:
                raise BoundaryError("selective_reference_entry_boundary")
            min_tokens=reference["tokens_out"]*(10_000-ENTRY_SLIPPAGE_BPS)//10_000
            result["minimum_fill_tokens"]=min_tokens
            result["gas_model"]=dict(
                units_proxy=gas_units,gas_price=gas_price,reservation_budget=gas_budget
            )

            _stop_sleep(max(0,reserved["due"]-int(time.time())))
            entry,entry_meta,entry_ledger=_wait_curve_quote(
                rpc,candidate,"buy",amount,gas_units,store,"selective-entry",
                reserved["due"],seconds=30,local_freshness=True,
            )
            anchor_quote,anchor_meta=entry,entry_meta
            persistence_started=time.monotonic()
            trajectory_now,demand_now,persistence_sessions=_refresh_entry_persistence_signal(
                endpoint,candidate,entry_meta
            )
            persistence_elapsed=time.monotonic()-persistence_started
            result["provider_sessions"].extend(persistence_sessions)
            persistence=entry_signal_persistence(vector,trajectory_now,demand_now)
            result["entry_persistence"]=dict(
                persistence,
                reasons=list(persistence["reasons"]),
                trajectory=trajectory_now,demand={k:v for k,v in demand_now.items() if k!='_entry_evidence'},
                persistence_elapsed_seconds=persistence_elapsed,
            )
            if persistence['persistent']:
                _entry_generation(evaluation)
                result['entry_persistence']['final_quote_provider_before']=rpc.telemetry()
                final_started_wall=time.time();final_started=time.monotonic()
                original_amount=amount;capacity_probes=[];capacity_binding=None
                for capacity_attempt in range(4):
                    entry,entry_meta,entry_ledger=_wait_curve_quote(
                        rpc,candidate,"buy",amount,gas_units,store,"selective-entry-final",
                        reserved["due"],seconds=30,local_freshness=True,
                    )
                    capacity=_entry_capacity(entry_meta,amount,entry.gas_quote)
                    capacity_probes.append(capacity.telemetry())
                    if capacity.final_size<amount and capacity_binding is None:capacity_binding=capacity.binding_reason
                    result['execution_capacity']=dict(capacity.telemetry(),original_size=original_amount,
                        binding_reason=capacity_binding or capacity.binding_reason,sizing_attempts=capacity_probes)
                    if capacity.final_size<=0:
                        raise BoundaryError('selective_execution_capacity')
                    if capacity.final_size==amount:break
                    amount=capacity.final_size
                    paper.resize_reservation(identity,amount,int(time.time()))
                    reference=candidate['state'].buy_with_snipe(amount,0)
                    min_tokens=reference['tokens_out']*(10000-ENTRY_SLIPPAGE_BPS)//10000
                    result['minimum_fill_tokens']=min_tokens
                    _entry_generation(evaluation)
                else:
                    raise BoundaryError('selective_capacity_state_unstable')
                final_received=time.monotonic()
                result['entry_persistence']['final_quote_provider_after']=rpc.telemetry()
                result['entry_persistence']['final_quote_acquisition_seconds']=final_received-final_started
                _validate_final_entry(entry,entry_meta,anchor_quote,amount,final_started_wall)
                demand_now,delta_sessions,delta=_confirm_entry_delta(
                    endpoint,candidate,anchor_meta,entry_meta,trajectory_now,demand_now,vector)
                result['provider_sessions'].extend(delta_sessions)
                result['entry_persistence']['provider_sessions_after_final_quote']=delta_sessions
                result['entry_persistence']['final_delta']=delta
                result['entry_persistence']['broad_reconstruction_after_final_quote']=0
                _entry_generation(evaluation)
            quote_age=max(0,int(time.time())-int(entry.stamp.observed_at))
            result["entry_persistence"]["quote_age_after_confirmation_seconds"]=quote_age
            if not persistence["persistent"] or quote_age>ENTRY_THRESHOLDS["max_state_age_seconds"]:
                failure=("entry_signal_decay" if not persistence["persistent"]
                         else "entry_quote_stale_after_confirmation")
                paper.advance(
                    identity,now=int(time.time()),action="cancel",
                    cancel_reason=failure,
                )
                result.update(
                    status="entry_failed",entry_failure=failure,
                    final_position=paper._get(identity),reconciliation=paper.reconcile(),
                )
                if capital_guard is not None:
                    result["cohort_reconciliation"]=capital_guard.settle(
                        identity,result["final_position"],at=int(time.time()))
                return result
            if entry.amount_out<min_tokens:
                paper.advance(
                    identity,now=entry.stamp.observed_at,action="cancel",
                    cancel_reason="entry_slippage",
                )
                result.update(
                    status="entry_failed",entry_failure="entry_slippage",
                    final_position=paper._get(identity),reconciliation=paper.reconcile(),
                )
                if capital_guard is not None:
                    result["cohort_reconciliation"]=capital_guard.settle(
                        identity,result["final_position"],at=int(time.time()))
                return result
            try:
                result["fill_full_exit_check"]=_fresh_fill_full_exit_check(
                    entry_meta,entry.amount_out)
            except BoundaryError as exc:
                if str(exc)!="impossible_full_position_exit":
                    raise
                cancelled=paper.advance(
                    identity,now=entry.stamp.observed_at,action="cancel",
                    cancel_reason="fill_full_exit_unavailable",
                )
                if capital_guard is not None:
                    result["cohort_reconciliation"]=capital_guard.settle(
                        identity,cancelled,at=entry.stamp.observed_at)
                result.update(
                    status="entry_failed",
                    entry_failure="fill_full_exit_unavailable",
                    fill_exit_boundary=str(exc),
                    final_position=cancelled,
                    reconciliation=paper.reconcile(),
                )
                return result
            # Hold the generation fence through the native commit. Projection callbacks
            # execute afterward because they open their own connection to the Plane.
            plane=None
            if evaluation.get('candidate_plane_path'):
                from meme_machine.runtime.robinhood.plane import Plane
                plane=Plane(evaluation['candidate_plane_path'])
            callback=paper.on_commit
            try:
                with plane.transaction() if plane is not None else nullcontext():
                    if plane is not None:
                        current=plane.get(evaluation['candidate_broker_identity'])
                        if (not current or current['generation']!=evaluation['candidate_broker_generation']
                                or current['completed']!=current['desired']
                                or plane.clock()>=current['deadline']):
                            raise BoundaryError('candidate_generation_superseded_before_entry')
                    decision_at=time.time()
                    quote_age=max(float(decision_at)-float(entry.stamp.observed_at),
                        float(getattr(entry,'acquisition_latency_seconds',0))+time.monotonic()-final_received)
                    result['entry_persistence']['quote_age_at_decision_seconds']=quote_age
                    if quote_age>ENTRY_THRESHOLDS['max_state_age_seconds']:
                        raise BoundaryError('entry_quote_stale_after_confirmation')
                    from .pons_selective_recovery import LifecycleState
                    state=LifecycleState.create(store,identity,evaluation,capital,gas_units,
                        opened_at=int(decision_at),last_block=int(entry_meta['block']))
                    paper.controller_context=state.checkpoint
                    paper.on_commit=None
                    opened=paper.advance(
                        identity,now=int(decision_at),action="entry",quote=entry,
                        finality_ledger=entry_ledger,
                    )
            finally:
                paper.on_commit=callback
                if plane is not None:plane.close()
            if callback:callback(paper,opened)
            result["entry"]=dict(position=opened,quote=entry_meta)

            # Every strategy-local paper trial must survive restart before monitoring.
            before=paper.reconcile();store.close()
            store=Store(str(db_path),max_records=8192)
            paper=SelectivePaper(
                store,STRATEGY_NAMESPACE,capital,
                delay=EXIT_POLICY["entry_delay_seconds"],
                natural_policy_hash=POLICY_HASH,
                on_commit=observe_commit,
            )
            if paper.reconcile()!=before:
                raise BoundaryError("selective_restart_reconciliation")
            result["restart_reconciliation"]=before
            paper.controller_context=state.checkpoint

        else:
            from .pons_selective_recovery import LifecycleState
            store=Store(str(db_path),max_records=8192)
            capital=_recovery['capital'];identity=_recovery['identity']
            gas_units=_recovery['gas_units']
            paper=SelectivePaper(store,STRATEGY_NAMESPACE,capital,
                delay=EXIT_POLICY['entry_delay_seconds'],natural_policy_hash=POLICY_HASH,
                on_commit=observe_commit)
            state=LifecycleState.restore(paper,identity)
            paper.controller_context=state.checkpoint
            if capital_path is not None:
                capital_guard=CohortCapital(capital_path,STRATEGY_CAPITAL_QUOTE)
                capital_guard.observe(paper,paper._get(identity))
            rpc=paper_rpc(endpoint);rpc.verify_chain()
            result.update(lifecycle_id=identity,resumed=True,entry_authority=False)

        def record_session_rotation(telemetry,row):
            if telemetry is not None:result["provider_sessions"].append(telemetry)
            rotations=result.setdefault("provider_session_rotations",[])
            row=dict(row,at=time.time(),opened_at=state.opened_at,lifecycle_id=identity,
                     elapsed_seconds=int(time.time())-state.opened_at,process_restart=False)
            rotations.append(row)
            store.put("selective_provider_session_rotation",identity+":"+str(uuid.uuid4()),row)
        rpc=PositionSessions(rpc,lambda:paper_rpc(endpoint),record_session_rotation)

        while paper._get(identity)['status']!='settled':
            if deadline is not None and time.monotonic()>=deadline:
                result.update(status='handoff_required',entry_authority=False)
                break
            try:
                rpc.rotate_if_needed()
                _stop_sleep(EXIT_POLICY["monitor_seconds"])
                header=_latest_header(rpc)
                block=int(header["number"],16)
                position=paper._get(identity)
                elapsed=int(time.time())-state.opened_at

                if (elapsed>=(129600 if getattr(state,'bridged',False) else EXIT_POLICY["max_total_hold_seconds"]) and
                        not (not getattr(state,'bridge_probe_failed',False) and elapsed<129600
                            and state.partial_taken and state.high_water>=5000
                            and position['status']=='open' and state.pending_action is None) and
                        not (position["status"]=="exit_pending" and state.transition is None)):
                    if position["status"]=="exit_pending" and state.transition is not None:
                        position,meta=_complete_pending_v4_exit(
                            paper=paper,identity=identity,rpc=rpc,v4_key=state.v4_key,
                            gas_units=gas_units,store=store,label="selective-timeout-pending-v4-exit",
                        )
                    elif position["status"]=="open":
                        try:
                            state.recovery_exit_reason="max_total_hold"
                            position,meta=_delayed_exit(
                                endpoint,paper=paper,identity=identity,rpc=rpc,candidate=candidate,
                                gas_units=gas_units,store=store,transition=state.transition,v4_key=state.v4_key,
                                label="selective-timeout-exit",exit_tokens=position["tokens"],
                            )
                        except BoundaryError as exc:
                            if str(exc)=="graduated_during_selective_exit":
                                state.pending_transition_exit_reason="max_total_hold"
                                continue
                            raise
                    else:
                        continue
                    if position['status']=='open':
                        # A pre-existing partial intent remains partial even when
                        # its fill arrives after max hold. Exit the remainder on
                        # the next fresh observation before claiming settlement.
                        result.setdefault('exits',[]).append(dict(
                            reason=state.recovery_exit_reason,quote=meta,position=position))
                        continue
                    result["exit"]=dict(reason="max_total_hold",quote=meta,position=position)
                    result["status"]="settled"
                    break

                if state.transition is None:
                    maybe=_graduation_transition(
                        rpc,candidate,state.last_block,block,candidate["report"]
                    )
                    if maybe is not None:
                        state.transition,state.v4_key,grad_header,_=maybe
                        store.put("graduation",state.transition["proof_hash"],state.transition)
                        state.graduation_at=int(grad_header["timestamp"],16)
                        state.graduation_block=int(grad_header["number"],16)
                        paper.advance(
                            identity,now=int(time.time()),action="transition",
                            transition=state.transition,
                        )
                        result["graduation_transition"]=dict(
                            transition=state.transition,block=state.graduation_block,
                            event_at=state.graduation_at,
                        )
                        pending=paper._get(identity)
                        if pending["status"]=="exit_pending":
                            position,exit_meta=_complete_pending_v4_exit(
                                paper=paper,identity=identity,rpc=rpc,v4_key=state.v4_key,
                                gas_units=gas_units,store=store,
                                label="selective-transition-pending-exit",
                            )
                            exit_row=dict(
                                reason=(state.pending_transition_exit_reason or "pregraduation_exit"),
                                quote=exit_meta,position=position,
                            )
                            result.setdefault("exits",[]).append(exit_row)
                            if position["status"]=="settled":
                                result["exit"]=exit_row
                                result["status"]="settled"
                                break
                            state.pending_transition_exit_reason=None
                    state.last_block=block

                position=paper._get(identity)
                if position["status"]=="open" and state.pending_action is not None:
                    pending=state.pending_action
                    if pending['before_tokens']!=position['tokens']:
                        raise BoundaryError('selective_recovery_action_quantity')
                    state.recovery_exit_reason=pending['reason']
                    paper.advance(identity,now=int(time.time()),action="exit_intent",
                        exit_tokens=pending['exit_tokens'])
                    position=paper._get(identity)
                if position["status"]=="exit_pending":
                    try:
                        position,exit_meta=_delayed_exit(
                            endpoint,paper=paper,identity=identity,rpc=rpc,candidate=candidate,
                            gas_units=gas_units,store=store,transition=state.transition,v4_key=state.v4_key,
                            label="selective-provider-recovery-exit",
                            exit_tokens=position["pending_exit_tokens"],
                        )
                    except BoundaryError as exc:
                        if str(exc)=="graduated_during_selective_exit":
                            state.pending_transition_exit_reason=state.recovery_exit_reason
                            continue
                        raise
                    exit_row=dict(reason=state.recovery_exit_reason,quote=exit_meta,position=position)
                    result.setdefault("exits",[]).append(exit_row)
                    if position["status"]=="settled":
                        result["exit"]=exit_row;result["status"]="settled"
                        break
                    state.partial_taken=True;state.recovery_streak=0
                    continue
                if state.transition is None:
                    try:
                        mark,meta=_curve_quote(
                            rpc,candidate,"sell",position["tokens"],gas_units,store,
                            "selective-curve-mark-"+str(len(result["monitor"])),
                            local_freshness=True,
                        )
                    except BoundaryError as exc:
                        if str(exc)=="curve_graduated_requires_transition":
                            continue
                        result["monitor"].append(dict(
                            at=int(time.time()),market="curve",available=False,
                            reason=str(exc),elapsed_seconds=elapsed,
                        ))
                        continue
                    rbps=_position_return_bps(position,mark)
                    state.last_curve_reference=dict(
                        tokens=position["tokens"],amount_out=mark.amount_out,
                        gas_quote=mark.gas_quote,at=mark.stamp.observed_at,
                    )
                    trajectory,demand,sessions=_refresh_curve_signal(
                        endpoint,candidate,meta
                    )
                    result["provider_sessions"].extend(sessions)
                    if rbps>state.high_water:
                        state.high_water=rbps;state.high_at=int(time.time())
                    if state.high_water>=10000 and getattr(state,'first_tail_crossed_at',None) is None:
                        state.first_tail_crossed_at=int(time.time())
                    soft=pregraduation_soft_deterioration(trajectory,demand)
                    state.pregrad_soft_deterioration_streak=(
                        state.pregrad_soft_deterioration_streak+1 if soft else 0
                    )
                    action=pregraduation_action(
                        tokens=position["tokens"],partial_taken=state.partial_taken,
                        elapsed_seconds=elapsed,frozen_eta_seconds=state.frozen_eta,
                        trajectory=trajectory,demand=demand,
                        after_cost_return_bps=rbps,
                        high_water_return_bps=state.high_water,
                        soft_deterioration_streak=state.pregrad_soft_deterioration_streak,
                    )
                    facts=_continuation_facts(position,mark,meta,candidate,rbps,
                        demand=demand,soft_streak=state.pregrad_soft_deterioration_streak,action=action)
                    action=_bridge_action(state,facts,action,position,now=int(time.time()))
                    state.remember_action(action,position)
                    paper.advance(identity,now=mark.stamp.observed_at,action="mark",quote=mark,
                        finality_ledger=Finality(store,scope="paper-selective-curve-mark-"+str(len(result["monitor"])),max_blocks=4))
                    result["monitor"].append(dict(
                        at=mark.stamp.observed_at,market="curve",available=True,
                        return_bps=rbps,trajectory=trajectory,demand=demand,
                        action=action,
                        soft_deterioration_streak=state.pregrad_soft_deterioration_streak,
                        quote=meta,pregraduation_profit_harvest_enabled=True,
                    ))
                    if action["action"] in ("partial_exit","full_exit"):
                        try:
                            state.recovery_exit_reason=action["reason"]
                            position,exit_meta=_delayed_exit(
                                endpoint,paper=paper,identity=identity,rpc=rpc,
                                candidate=candidate,gas_units=gas_units,store=store,
                                transition=None,v4_key=None,
                                label="selective-curve-exit",
                                exit_tokens=action["exit_tokens"],
                            )
                        except BoundaryError as exc:
                            if str(exc)=="graduated_during_selective_exit":
                                state.pending_transition_exit_reason=action["reason"]
                                continue
                            raise
                        result.setdefault("exits",[]).append(dict(
                            reason=action["reason"],quote=exit_meta,position=position,
                        ))
                        state.partial_taken=state.partial_taken or position["status"]=="open"
                        if position["status"]=="settled":
                            result["exit"]=result["exits"][-1]
                            result["status"]="settled"
                            break
                    if action['action']=='hold':
                        _attempt_current_scale(endpoint,rpc,paper,identity,state,candidate,gas_units,store,
                            facts,position,trajectory=trajectory,demand=demand)
                    state.recovery_streak=0
                    continue

                # Authenticated Pons V2 -> V4 transition has occurred.
                if not state.post_grad_checked:
                    wait=max(
                        0,(state.graduation_at+POST_GRAD_OBSERVE_SECONDS)-int(time.time())
                    )
                    _stop_sleep(wait)
                    header=_latest_header(rpc);block=int(header["number"],16)
                    position=paper._get(identity)
                    mark,meta,ledger=_v4_quote(
                        rpc,state.v4_key,position["market"],position["tokens"],gas_units,store,
                        "selective-postgrad-mark",local_freshness=True,
                    )
                    activity=collect_v4_activity(
                        endpoint,pool_id=position["market"],key=state.v4_key,
                        token=evaluation["token"],start_block=state.graduation_block,
                        end_block=block,preholder_groups=state.preholders,
                    )
                    result["provider_sessions"].extend(activity.pop("provider_sessions"))
                    if not state.last_curve_reference or (
                        int(state.last_curve_reference["tokens"])!=int(position["tokens"])
                    ):
                        retention=0
                    else:
                        retention=int(mark.amount_out)*10_000//max(
                            1,int(state.last_curve_reference["amount_out"])
                        )
                    post=post_graduation_vector(
                        observed_seconds=max(0,mark.stamp.event_at-state.graduation_at),
                        price_retention_bps=retention,
                        new_independent_buyers=activity["new_independent_buyers"],
                        buy_quote=activity["buy_quote"],sell_quote=activity["sell_quote"],
                        net_quote=activity["net_quote"],
                        preholder_sell_quote=activity["preholder_sell_quote"],
                        largest_buyer_flow_bps_before=state.entry_largest,
                        largest_buyer_flow_bps_now=activity["largest_buyer_flow_bps"],
                    )
                    result["post_graduation"]=dict(
                        vector=post,activity=activity,quote=meta
                    )
                    state.seen_v4_buyers.update(activity["buyer_groups"])
                    state.post_grad_checked=True
                    if not post["continuation_pass"]:
                        state.remember_action(dict(action="full_exit",reason="post_graduation_failure",
                            exit_tokens=position["tokens"]),position)
                    paper.advance(identity,now=mark.stamp.observed_at,action="mark",quote=mark,finality_ledger=ledger)
                    if not post["continuation_pass"]:
                        state.recovery_exit_reason="post_graduation_failure"
                        position,exit_meta=_delayed_exit(
                            endpoint,paper=paper,identity=identity,rpc=rpc,
                            candidate=candidate,gas_units=gas_units,store=store,
                            transition=state.transition,v4_key=state.v4_key,
                            label="selective-postgrad-failure-exit",
                            exit_tokens=position["tokens"],
                        )
                        result["exit"]=dict(
                            reason="post_graduation_failure",quote=exit_meta,
                            position=position,
                        )
                        result["status"]="settled"
                        break

                position=paper._get(identity)
                mark,meta,ledger=_v4_quote(
                    rpc,state.v4_key,position["market"],position["tokens"],gas_units,store,
                    "selective-v4-mark-"+str(len(result["monitor"])),
                    local_freshness=True,
                )
                rbps=_position_return_bps(position,mark)
                current_header=dict(
                    number=hex(int(meta["block"])),hash=meta["block_hash"],
                    timestamp=hex(int(mark.stamp.event_at)),
                )
                locator=evidence_rpc(endpoint);cache={int(meta["block"]):current_header}
                start_header=_header_search(
                    locator,int(meta["block"]),mark.stamp.event_at,
                    max(state.graduation_at,mark.stamp.event_at-15),cache,
                )
                result["provider_sessions"].append(locator.telemetry())
                activity=collect_v4_activity(
                    endpoint,pool_id=position["market"],key=state.v4_key,
                    token=evaluation["token"],
                    start_block=int(start_header["number"],16),end_block=int(meta["block"]),
                    preholder_groups=state.preholders,
                )
                result["provider_sessions"].extend(activity.pop("provider_sessions"))
                buyers=set(activity["buyer_groups"])
                growth=len(buyers-state.seen_v4_buyers)
                state.seen_v4_buyers.update(buyers)
                if rbps>state.high_water:
                    state.high_water=rbps;state.high_at=int(time.time())
                if state.high_water>=10000 and getattr(state,'first_tail_crossed_at',None) is None:
                    state.first_tail_crossed_at=int(time.time())
                seconds_since_high=max(0,int(time.time())-state.high_at)
                soft=runner_soft_deterioration(
                    seconds_since_high=seconds_since_high,
                    new_buyer_growth=growth,
                )
                state.runner_soft_deterioration_streak=(
                    state.runner_soft_deterioration_streak+1 if soft else 0
                )
                action=runner_action(
                    tokens=position["tokens"],partial_taken=state.partial_taken,
                    after_cost_return_bps=rbps,high_water_return_bps=state.high_water,
                    seconds_since_high=seconds_since_high,
                    new_buyer_growth=growth,buy_quote=activity["buy_quote"],
                    sell_quote=activity["sell_quote"],
                    soft_deterioration_streak=state.runner_soft_deterioration_streak,
                )
                facts=_continuation_facts(position,mark,meta,candidate,rbps,
                    demand=activity,soft_streak=state.runner_soft_deterioration_streak,action=action)
                action=_bridge_action(state,facts,action,position,now=int(time.time()))
                state.remember_action(action,position)
                paper.advance(identity,now=mark.stamp.observed_at,action="mark",quote=mark,finality_ledger=ledger)
                result["monitor"].append(dict(
                    at=mark.stamp.observed_at,market="v4",available=True,
                    return_bps=rbps,activity=activity,action=action,quote=meta,
                    soft_deterioration_streak=state.runner_soft_deterioration_streak,
                ))
                if action["action"] in ("partial_exit","full_exit"):
                    state.recovery_exit_reason=action["reason"]
                    position,exit_meta=_delayed_exit(
                        endpoint,paper=paper,identity=identity,rpc=rpc,candidate=candidate,
                        gas_units=gas_units,store=store,transition=state.transition,v4_key=state.v4_key,
                        label="selective-v4-exit",exit_tokens=action["exit_tokens"],
                    )
                    result.setdefault("exits",[]).append(dict(
                        reason=action["reason"],quote=exit_meta,position=position,
                    ))
                    state.partial_taken=state.partial_taken or position["status"]=="open"
                    if position["status"]=="settled":
                        result["exit"]=result["exits"][-1]
                        result["status"]="settled"
                        break
                if action['action']=='hold':
                    _attempt_current_scale(endpoint,rpc,paper,identity,state,candidate,gas_units,store,
                        facts,position,demand=activity)
                state.recovery_streak=0
            except BoundaryError as exc:
                state.bridge_probe_failed=True
                # A provider outage after a fill is not a terminal strategy event.
                # Retry a fresh observation on the SAME ledger and original hold
                # clock. Any pending exit keeps its original intent/amount/due.
                position=paper._get(identity)
                if (str(exc)=="impossible_full_position_exit" and state.transition is None
                        and position["status"] in ("open","exit_pending")):
                    # Keep the original exit intent/clock while waiting for the
                    # original maximum hold. Never infer a writeoff from transport.
                    if int(time.time())-state.opened_at<EXIT_POLICY["max_total_hold_seconds"]:
                        result["monitor"].append(dict(at=int(time.time()),available=False,
                            reason=str(exc),pending_exit_preserved=True))
                        continue
                    try:
                        proof=_prove_impossible_full_exit(rpc,candidate,position,store)
                    except BoundaryError as verification:
                        if str(verification)=="graduated_during_selective_exit":
                            state.pending_transition_exit_reason=state.recovery_exit_reason or "max_total_hold"
                            continue
                        exc=verification
                    else:
                        if proof is None:continue  # liquidity returned; retry the same exit
                        position=paper.advance(identity,now=int(time.time()),
                            action="liquidity_writeoff",cancel_reason="impossible_full_position_exit")
                        result["settlement_kind"]="liquidity_writeoff"
                        result["exit"]=dict(reason="max_total_hold",position=position,
                            quote=dict(venue="paper_liquidity_writeoff",amount_out=0,
                                       executable=False,proof=proof))
                        result["status"]="settled"
                        break
                if (str(exc) not in POSITION_TRANSIENT_BOUNDARIES or
                        position["status"] not in ("open","exit_pending")):
                    raise exc
                state.recovery_streak+=1
                if state.recovery_streak>5:
                    raise BoundaryError("selective_position_provider_recovery_exhausted") from None
                row=dict(at=time.time(),reason=str(exc),position_status=position["status"],
                    opened_at=state.opened_at,elapsed_seconds=int(time.time())-state.opened_at,
                    attempt=state.recovery_streak,pending_exit_tokens=position.get("pending_exit_tokens"),
                    pending_due=position.get("due"),process_restart=False)
                recoveries=result.setdefault("provider_recoveries",[]);recoveries.append(row)
                store.put("selective_provider_recovery",identity+":"+str(uuid.uuid4()),row)
                result["monitor"].append(dict(available=False,reason=str(exc),provider_recovery=True))
                _stop_sleep(min(8,2**state.recovery_streak))

        reconciliation=paper.reconcile();store.close();store=None
        store=Store(str(db_path),max_records=8192)
        paper=SelectivePaper(
            store,STRATEGY_NAMESPACE,capital,
            delay=EXIT_POLICY["entry_delay_seconds"],
            natural_policy_hash=POLICY_HASH,
        )
        if paper.reconcile()!=reconciliation:
            raise BoundaryError("selective_final_restart_reconciliation")
        result["final_position"]=paper._get(identity)
        if result["final_position"]["status"]=="settled":result["status"]="settled"
        result["reconciliation"]=reconciliation
        result["realized_pnl_quote"]=result["final_position"]["pnl"]
        result["carried_through_graduation"]=state.transition is not None
        if capital_guard is not None:
            if result["final_position"]["status"]=="settled":
                if _recovery is not None:
                    from .pons_selective_recovery import settle_recovered
                    result["cohort_reconciliation"]=settle_recovered(
                        capital_guard,paper,result["final_position"],at=int(time.time()))
                else:
                    result["cohort_reconciliation"]=capital_guard.settle(
                        identity,result["final_position"],at=int(time.time()))
            else:
                result["cohort_reconciliation"]=capital_guard.reconcile()
        return result
    except BoundaryError as exc:
        result["status"]="boundary"
        result["boundary"]=str(exc)
        if store is not None:
            try:
                recovery=SelectivePaper(
                    store,STRATEGY_NAMESPACE,capital,
                    delay=EXIT_POLICY["entry_delay_seconds"],
                    natural_policy_hash=POLICY_HASH,
                    on_commit=observe_commit,
                )
                cancelled=_cancel_proven_unfilled(recovery,identity,capital_guard,str(exc))
                if cancelled is not None:
                    result.update(status='entry_failed',entry_failure=str(exc),final_position=cancelled)
                result['reconciliation']=recovery.reconcile()
            except Exception as cleanup:
                # Ambiguous exposure remains reserved and explicitly blocks meme_machine.runtime.
                result['cancellation_failure']=type(cleanup).__name__
        return result
    finally:
        try:
            if capital_guard is not None:
                # Ambiguous native exits keep capital occupied and fail meme_machine.runtime.
                result["cohort_reconciliation"]=capital_guard.reconcile()
            if rpc is not None:
                result["provider_sessions"].append(rpc.telemetry())
        finally:
            if store is not None:
                try:store.close()
                except Exception:pass
            result["ended_at"]=time.time()


def _continuation_facts(position,mark,meta,candidate,rbps,*,demand,soft_streak,action):
    now=int(time.time());fresh=0<=now-int(mark.stamp.observed_at)<=5
    creator=int(demand.get('creator_sell_quote_15s',0))
    record=candidate.get('record') or {}
    creators={str(record.get(k,'')).lower() for k in ('deployer','creatorFeeRecipient')}
    creator+=sum(int(e.get('quote',0)) for e in demand.get('swaps',demand.get('events',[]))
        if (e.get('side')=='sell' or e.get('buy') is False) and str(e.get('group','')).lower() in creators)
    largest=demand.get('largest_buyer_flow_bps')
    top3=demand.get('top3_buyer_flow_bps')
    concentration=(largest is not None and int(largest)<=ENTRY_THRESHOLDS['max_largest_buyer_flow_bps']
        and (top3 is None or int(top3)<=ENTRY_THRESHOLDS['max_top3_buyer_flow_bps']))
    return dict(observed_at=now,current_after_cost_return_positive=rbps>0,after_cost_return_bps=rbps,
        fresh_generation_state=fresh and bool(meta.get('block_hash')),
        fresh_executable_exit_quote=fresh,canonical_lineage_and_venue=bool(candidate.get('auth')),
        creator_distribution_safe=bool(record) and creator==0,hard_concentration_safe=concentration,
        executable_exit_liquidity=mark.amount_out>mark.gas_quote,
        no_persistent_confirmed_demand_failure=soft_streak<EXIT_POLICY['soft_deterioration_confirmations'],
        no_irreversible_exit_intent=position['status']=='open' and action['action']=='hold')


def _bridge_action(state,facts,action,position,*,now):
    from meme_machine.runtime.directional_continuation import bridge_state
    if action['action']!='hold':return action
    view=dict(opened_at=state.opened_at,realization_taken=state.partial_taken,
        high_water_bps=state.high_water,bridged=getattr(state,'bridged',False))
    updated,expired=bridge_state(view,facts,now=now,
        ordinary_expired=now-state.opened_at>=EXIT_POLICY['max_total_hold_seconds'])
    for name in ('bridged','bridged_at','bridge_deadline'):
        if name in updated:setattr(state,name,updated[name])
    state.bridge_probe_failed=False
    if expired:return dict(action='full_exit',reason='max_total_hold',exit_tokens=position['tokens'])
    return action



def _ongoing_scale_evidence(endpoint,rpc,paper,identity,state,candidate,gas_units,store,sleeve):
    """Authenticate a rolling horizon and a current executable exit independently."""
    from collections import defaultdict
    from .pons_selective_continuation import curve_progress_bps
    started=time.time();position=paper._get(identity)
    if state.transition is None:
        mark,meta,_=_curve_quote(rpc,candidate,'sell',position['tokens'],gas_units,store,
            'selective-scale-current-exit',local_freshness=True)
    else:
        mark,meta,_=_v4_quote(rpc,state.v4_key,position['market'],position['tokens'],gas_units,store,
            'selective-scale-current-exit',local_freshness=True)
    head=dict(number=hex(int(meta['block'])),hash=meta['block_hash'],timestamp=hex(int(meta['event_at'])))
    asof=int(meta['event_at']);creators={str(candidate['record'].get(k,'')).lower()
        for k in ('deployer','creatorFeeRecipient')}
    if state.transition is None:
        events,_=_curve_logs(endpoint,candidate['curve'],head,seconds=900)
        trajectory,demand,_=_refresh_curve_signal(endpoint,candidate,meta)
        curve=CurveState(**meta['state'])
        progress=curve_progress_bps(curve.real_quote,candidate['record']['graduationThreshold'])
        snipe=int(rpc.call('eth_call',[dict(to=candidate['curve'],
            data=calldata('currentSnipeTaxBps(address)',RESEARCH_RECIPIENT)),hex(int(meta['block']))],
            scope='pons_ongoing_scale_requalification'),16)
        structural=(not curve.graduated and snipe==0
            and curve.creator_tax_bps<=ENTRY_THRESHOLDS['max_creator_tax_bps']
            and ENTRY_THRESHOLDS['min_curve_progress_bps']<=progress<=ENTRY_THRESHOLDS['max_curve_progress_bps'])
        action=pregraduation_action(tokens=position['tokens'],partial_taken=state.partial_taken,
            elapsed_seconds=int(time.time())-state.opened_at,frozen_eta_seconds=state.frozen_eta,
            trajectory=trajectory,demand=demand,after_cost_return_bps=_position_return_bps(position,mark),
            high_water_return_bps=state.high_water,
            soft_deterioration_streak=state.pregrad_soft_deterioration_streak)
        phase='pregraduation'
    else:
        locator=evidence_rpc(endpoint)
        start=_header_search(locator,int(meta['block']),asof,max(0,asof-900),{int(meta['block']):head})
        activity=collect_v4_activity(endpoint,pool_id=position['market'],key=state.v4_key,
            token=candidate['token'],start_block=int(start['number'],16),end_block=int(meta['block']),
            preholder_groups=state.preholders,max_events=ENTRY_THRESHOLDS['max_market_events'])
        events=[r for r in activity['swaps'] if asof-900<=int(r['event_at'])<=asof]
        recent=[r for r in events if int(r['event_at'])>=asof-15
            and str(r['group']).lower() not in creators
            and str(r.get('actor',r['group'])).lower() not in creators]
        flows=defaultdict(int)
        for r in recent:
            if r['side']=='buy':flows[r['group']]+=int(r['quote'])
        total=sum(flows.values());ordered=sorted(flows.values(),reverse=True)
        buy=sum(int(r['quote']) for r in recent if r['side']=='buy')
        sell=sum(int(r['quote']) for r in recent if r['side']=='sell')
        prices=[int(r['price_index']) for r in events]
        demand=dict(buy_quote=buy,sell_quote=sell,net_quote=buy-sell,
            new_independent_buyers=len(set(flows)-set(state.preholders)),
            largest_buyer_flow_bps=10000 if not total else max(ordered)*10000//total,
            top3_buyer_flow_bps=10000 if not total else sum(ordered[:3])*10000//total,
            preholder_sell_quote=sum(int(r['quote']) for r in recent
                if r['side']=='sell' and r['group'] in state.preholders),
            price_retention_bps=0 if not prices else prices[-1]*10000//max(prices))
        trajectory=None;structural=bool(state.transition and state.v4_key)
        action=runner_action(tokens=position['tokens'],partial_taken=state.partial_taken,
            after_cost_return_bps=_position_return_bps(position,mark),high_water_return_bps=state.high_water,
            seconds_since_high=int(time.time())-state.high_at,new_buyer_growth=len(set(flows)-state.seen_v4_buyers),
            buy_quote=buy,sell_quote=sell,soft_deterioration_streak=state.runner_soft_deterioration_streak)
        phase='postgraduation'
    independent=defaultdict(int);buy=sell=creator_sell=0
    for r in events:
        if not asof-900<=int(r['event_at'])<=asof:raise BoundaryError('scale_window_identity')
        amount=int(r['quote']);group=str(r['group']).lower()
        excluded=group in creators or str(r.get('actor',group)).lower() in creators
        if excluded:
            if r['side']=='sell':creator_sell+=amount
            continue
        if r['side']=='buy':
            buy+=amount;independent[group]+=amount
        else:sell+=amount
    total=sum(independent.values());ordered=sorted(independent.values(),reverse=True)
    horizon=dict(independent_groups=len(independent),buy_quote=buy,sell_quote=sell,net_quote=buy-sell,
        largest_buyer_flow_bps=10000 if not total else ordered[0]*10000//total,
        top3_buyer_flow_bps=10000 if not total else sum(ordered[:3])*10000//total)
    base=store.get('pons_selective_recovery_base',identity)
    if not base or any(candidate.get(k)!=base['evaluation']['candidate'].get(k)
            for k in ('token','curve','auth','record')):
        raise BoundaryError('scale_authenticated_lifecycle_identity')
    if mark.market!=position['market']:raise BoundaryError('scale_market_identity')
    held=sleeve.get(identity) or {};reservation=held.get('scale_reservation') or {}
    evidence=dict(phase=phase,window_seconds=900,window_ending_at=asof,
        acquisition_started_at=started,block_hash=meta['block_hash'],block=meta['block'],
        authenticated=bool(candidate.get('auth')),structural_safe=structural,
        originally_qualified=bool(base and base['evaluation']['vector'].get('current_threshold_pass')
            and base['evaluation']['vector'].get('policy_hash')==POLICY_HASH),
        outstanding_scale_reservation=reservation.get('status')=='reserved',
        no_exit_condition=action['action']=='hold',creator_safe=creator_sell==0,
        exit_liquidity=mark.amount_out>mark.gas_quote,
        after_cost_return_bps=_position_return_bps(position,mark),entry_largest=state.entry_largest,
        horizon=horizon,trajectory=trajectory,demand=demand,events_digest=digest(events),
        original_demand_reference=base['evaluation']['vector'].get('demand') or {})
    return evidence,position,mark,meta


def _attempt_current_scale(endpoint,rpc,paper,identity,state,candidate,gas_units,store,facts,position,*,trajectory=None,demand):
    from contextlib import closing
    from meme_machine.runtime.directional_sleeve import open_sleeve
    from meme_machine.runtime.directional_continuation import scale_budget
    from .pons_selective_continuation import ongoing_scale_requalification
    now=int(time.time())
    if (getattr(state,'scale_committed',False) or position.get('scale_request') or not state.partial_taken
            or getattr(state,'first_tail_crossed_at',None) is None
            or now-state.first_tail_crossed_at<900 or state.pending_action is not None):return None
    sleeve=open_sleeve('pons',STRATEGY_CAPITAL_QUOTE)
    if sleeve is None:return None
    with closing(sleeve):
        try:
            current,position,mark,mark_meta=_ongoing_scale_evidence(
                endpoint,rpc,paper,identity,state,candidate,gas_units,store,sleeve)
        except BoundaryError:return None
        result=ongoing_scale_requalification(position=position,controller=vars(state),
            evidence=current,now=time.time())
        requalified=result['scale_qualified']
        facts=_continuation_facts(position,mark,mark_meta,candidate,current['after_cost_return_bps'],
            demand=current['demand'],soft_streak=(state.pregrad_soft_deterioration_streak if state.transition is None
                else state.runner_soft_deterioration_streak),action={'action':'hold'})
        if not requalified:return None
        view=dict(opened_at=state.opened_at,original_basis=position['original_basis'],
            realization_taken=state.partial_taken,high_water_bps=state.high_water,
            first_tail_crossed_at=state.first_tail_crossed_at,scale_committed=position.get('scale_request') is not None,
            pending_exit=state.pending_action)
        budget=min(sleeve.sizing_basis(250)['allocatable_target'],view['original_basis']//2)
        if budget<=0 or not requalified:return None
        allowance=max(0,int(current['demand'].get('current_net_quote',current['demand'].get('net_quote',0))))*ENTRY_THRESHOLDS['independent_net_size_bps']//10000
        budget=min(budget,allowance)
        budget=scale_budget(view,dict(facts,fresh_strategy_requalified=requalified,fresh_execution_requalified=True),
            now=now,sleeve=sleeve,execution_allowance=budget)
        gas,_=_gas_quote(rpc,gas_units)
        budget-=gas
        if budget<=0:return None
        try:
            _stop_sleep(EXIT_POLICY['entry_delay_seconds'])
            if state.transition is None:
                entry,meta,ledger=_wait_curve_quote(rpc,candidate,'buy',budget,gas_units,store,'selective-scale',now+EXIT_POLICY['entry_delay_seconds'],seconds=5,local_freshness=True)
                capacity=_entry_capacity(meta,budget,entry.gas_quote)
                if capacity.final_size<=0:return None
                if capacity.final_size<budget:
                    entry,meta,ledger=_wait_curve_quote(rpc,candidate,'buy',capacity.final_size,gas_units,store,'selective-scale-resized',now+EXIT_POLICY['entry_delay_seconds'],seconds=5,local_freshness=True)
                _validate_final_entry(entry,meta,mark,entry.amount_in,now+EXIT_POLICY['entry_delay_seconds'])
                _fresh_fill_full_exit_check(meta,position['tokens']+entry.amount_out)
            else:
                def quote_loss(amount):
                    if amount<=0:return None
                    buy,_,_=_v4_quote(rpc,state.v4_key,position['market'],amount,gas_units,store,'selective-scale-probe',local_freshness=True,side='buy')
                    sell,_,_=_v4_quote(rpc,state.v4_key,position['market'],buy.amount_out,gas_units,store,'selective-scale-unwind-probe',local_freshness=True)
                    cost=buy.amount_in+buy.gas_quote;net=max(0,sell.amount_out-sell.gas_quote)
                    return max(0,(cost-net)*10000//cost)
                capacity=resize(budget,1,quote_loss,ordinary_limit=ENTRY_THRESHOLDS['max_roundtrip_loss_bps'])
                if capacity.final_size<=0:return None
                entry,meta,ledger=_v4_quote(rpc,state.v4_key,position['market'],capacity.final_size,gas_units,store,'selective-scale-entry',local_freshness=True,side='buy')
                full_exit,_,_=_v4_quote(rpc,state.v4_key,position['market'],position['tokens']+entry.amount_out,
                    gas_units,store,'selective-scale-full-exit',local_freshness=True)
                if full_exit.amount_out<=full_exit.gas_quote:return None
            # Qualification is reacquired after execution probing. Neither a
            # historical vector nor a stale capacity/market result can commit.
            current,position,mark,mark_meta=_ongoing_scale_evidence(
                endpoint,rpc,paper,identity,state,candidate,gas_units,store,sleeve)
            result=ongoing_scale_requalification(position=position,controller=vars(state),
                evidence=current,now=time.time())
            if not result['scale_qualified']:return None
            if not 0<=time.time()-entry.stamp.observed_at<=5:return None
            facts=_continuation_facts(position,mark,mark_meta,candidate,current['after_cost_return_bps'],
            demand=current['demand'],soft_streak=(state.pregrad_soft_deterioration_streak if state.transition is None
                else state.runner_soft_deterioration_streak),action={'action':'hold'})
            allowance=max(0,int(current['demand'].get('current_net_quote',current['demand'].get('net_quote',0))))*ENTRY_THRESHOLDS['independent_net_size_bps']//10000
            if entry.amount_in>allowance:return None
            store.put('pons_ongoing_scale_requalification',digest(dict(identity=identity,evidence=current)),
                dict(identity=identity,evidence=current,result=result,executable_quote=asdict(entry)))
            cost=entry.amount_in+entry.gas_quote
            size=scale_budget(view,dict(facts,fresh_strategy_requalified=requalified,fresh_execution_requalified=True),
                now=int(time.time()),sleeve=sleeve,execution_allowance=cost)
            if cost>size:return None
            request=identity+':scale:1'
            sleeve.reserve_scale(identity,amount=cost,original_basis=view['original_basis'],at=int(time.time()),request=request,
                scale_state=view,scale_facts=dict(facts,fresh_strategy_requalified=requalified,fresh_execution_requalified=True))
            callback=paper.on_commit;paper.on_commit=None
            try:
                with sleeve.scale_fence(identity,request):
                    if state.pending_action is not None or paper._get(identity)['status']!='open':raise BoundaryError('scale_pending_exit')
                    position=paper.advance(identity,now=int(time.time()),action='scale_add',quote=entry,
                        finality_ledger=ledger,cancel_reason=request)
                state.scale_committed=True
            except BaseException:
                paper.positions();native=paper._get(identity)
                sleeve.recover_scale(identity,request=request,native_verified=True,committed=native.get('scale_request')==request)
                raise
            finally:paper.on_commit=callback
            if callback:callback(paper,position)
            return position
        except BoundaryError:
            # Incremental failure never produces a new exit or modifies the original lot.
            return None


# Public recovery entrypoint reuses the same frozen-policy monitor above.
from .pons_selective_recovery import resume_lifecycle,exclusive_lifecycle

@exclusive_lifecycle
def run_lifecycle(endpoint,evaluation,*,db_path,capital_path=None):
    result=_run_lifecycle(endpoint,evaluation,db_path=db_path,capital_path=capital_path)
    if evaluation.get('candidate_plane_path') and evaluation.get('candidate_broker_identity'):
        from meme_machine.runtime.robinhood.plane import Plane
        from .pons_attempts import Attempts,failure_category
        plane=Plane(evaluation['candidate_plane_path'])
        try:
            position=result.get('final_position') or {}
            funded=int(position.get('entry_tokens',0))>0
            reason='paper_filled' if funded else result.get('entry_failure') or result.get('boundary') or result['status']
            Attempts(plane).record(evaluation['candidate_broker_identity'],evaluation['candidate_broker_generation'],
                'funding','OTHER_EXPLICIT_REASON' if funded else failure_category(reason,qualified=True),
                at=evaluation['vector'].get('asof',evaluation['vector'].get('evidence_available_at')),
                reason=reason,execution=dict(lifecycle_id=result.get('lifecycle_id'),funded=funded))
        finally:plane.close()
    return result


def _stop_sleep(seconds):
    from meme_machine.runtime.stop import sleep
    return sleep(seconds,sleeper=time.sleep)
