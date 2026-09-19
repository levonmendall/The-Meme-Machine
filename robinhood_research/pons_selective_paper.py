"""Independent paper lifecycle for Pons Selective Continuation v1.

Strategy authority, capital, state and results are private to this lane.  The only
shared components are neutral Pons protocol authentication, read-only provider,
finality and paper-execution primitives.  No continuation-v1, Ramses, Pump.fun or
other strategy signal/threshold/state is imported.
"""
from dataclasses import asdict
import time

from . import BoundaryError
from .abi import topic
from .evidence import Store
from .pons_selective_ledger import SelectivePaper
from .pons import CurveState, curve_abi, raw_event
from .pons_natural_observation import _latest_header
from .pons_natural_paper import (
    _curve_quote, _gas_quote, _gas_units, _graduation_transition,
    _rpc as paper_rpc, _v4_quote, _wait_curve_quote,
)
from .pons_selective_acquisition import (
    _batched, _header_search, _rpc as evidence_rpc, _trajectory,
)
from .pons_selective_continuation import (
    EXIT_POLICY, POLICY, POLICY_HASH, demand_metrics, normalized_trade,
    post_graduation_vector, pregraduation_exit_reason, runner_action,
    trajectory_metrics,
)
from .pons_selective_v4 import collect_v4_activity

STRATEGY_NAMESPACE="pons-selective-continuation-v1"
STRATEGY_CAPITAL_QUOTE=10**18
ENTRY_SLIPPAGE_BPS=100
POST_GRAD_OBSERVE_SECONDS=10


def _position_return_bps(position,quote):
    basis=int(position.get("remaining_cost",position["cost"]))
    if basis<=0:
        raise BoundaryError("selective_position_basis")
    net=int(quote.amount_out)-int(quote.gas_quote)
    return (net-basis)*10_000//basis


def _curve_logs(endpoint,curve,current_header,seconds=60):
    current_block=int(current_header["number"],16)
    current_at=int(current_header["timestamp"],16)
    locator=evidence_rpc(endpoint)
    cache={current_block:current_header}
    start_header=_header_search(
        locator,current_block,current_at,max(0,current_at-int(seconds)),cache
    )
    start_block=int(start_header["number"],16)
    locator_telemetry=locator.telemetry()

    sigs=[
        topic("CurveBuy(address,address,uint256,uint256,uint256,uint256)"),
        topic("CurveSell(address,address,uint256,uint256,uint256,uint256)"),
    ]
    calls=[]
    for first in range(start_block,current_block+1,10):
        calls.append(("eth_getLogs",[dict(
            fromBlock=hex(first),toBlock=hex(min(current_block,first+9)),
            address=curve,topics=[sigs],
        )]))
    batches,sessions=_batched(endpoint,calls,"pons_selective_monitor") if calls else ([],[])
    raw=[]
    for rows in batches:
        raw.extend(rows)
    if len(raw)>512:
        raise BoundaryError("selective_monitor_event_capacity")

    hashes=list(dict.fromkeys(event["blockHash"] for event in raw))
    headers_v,more=_batched(
        endpoint,[("eth_getBlockByHash",[h,False]) for h in hashes],"pons_selective_monitor"
    ) if hashes else ([],[])
    sessions.extend(more);headers=dict(zip(hashes,headers_v))
    tx_rows=list(dict.fromkeys((e["transactionHash"],e["blockHash"]) for e in raw))
    receipts_v,more=_batched(
        endpoint,[("eth_getTransactionReceipt",[tx]) for tx,_ in tx_rows],
        "pons_selective_monitor",
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
            out.append(normalized_trade(
                row["decoded"],
                identity=f'{row["block"]}:{row["transaction_hash"]}:{row["log_index"]}',
                event_at=at,
            ))
    return out,[locator_telemetry]+sessions


def _refresh_curve_signal(endpoint,candidate,mark_meta):
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
    return trajectory,demand,[trajectory_session]+sessions


def _delayed_exit(
    endpoint,*,paper,identity,rpc,candidate,gas_units,store,
    transition,v4_key,label,exit_tokens,
):
    paper.advance(
        identity,now=int(time.time()),action="exit_intent",exit_tokens=int(exit_tokens)
    )
    pending=paper._get(identity)
    time.sleep(max(0,pending["due"]-int(time.time())))
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
            time.sleep(0.5)
    position=paper.advance(
        identity,now=quote.stamp.observed_at,action="exit",quote=quote,
        finality_ledger=ledger,
    )
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
        time.sleep(0.5)
    position=paper.advance(
        identity,now=quote.stamp.observed_at,action="exit",quote=quote,
        finality_ledger=ledger,
    )
    return position,meta


def run_lifecycle(endpoint,evaluation,*,db_path):
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
    store=None;rpc=None
    try:
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
            "pons-selective:"+evaluation["token"]+":"+
            evaluation["source_transaction"]
        )
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

        time.sleep(max(0,reserved["due"]-int(time.time())))
        entry,entry_meta,entry_ledger=_wait_curve_quote(
            rpc,candidate,"buy",amount,gas_units,store,"selective-entry",
            reserved["due"],seconds=30,local_freshness=True,
        )
        if entry.amount_out<min_tokens:
            paper.advance(
                identity,now=entry.stamp.observed_at,action="cancel",
                cancel_reason="entry_slippage",
            )
            result.update(
                status="entry_failed",entry_failure="entry_slippage",
                final_position=paper._get(identity),reconciliation=paper.reconcile(),
            )
            return result
        opened=paper.advance(
            identity,now=entry.stamp.observed_at,action="entry",quote=entry,
            finality_ledger=entry_ledger,
        )
        result["entry"]=dict(position=opened,quote=entry_meta)

        # Every strategy-local paper trial must survive restart before monitoring.
        before=paper.reconcile();store.close()
        store=Store(str(db_path),max_records=8192)
        paper=SelectivePaper(
            store,STRATEGY_NAMESPACE,capital,
            delay=EXIT_POLICY["entry_delay_seconds"],
            natural_policy_hash=POLICY_HASH,
        )
        if paper.reconcile()!=before:
            raise BoundaryError("selective_restart_reconciliation")
        result["restart_reconciliation"]=before

        opened_at=opened["last_at"]
        last_block=int(entry_meta["block"])
        transition=None;v4_key=None
        graduation_at=None;graduation_block=None
        post_grad_checked=False
        partial_taken=False
        high_water=-10**9;high_at=opened_at
        last_curve_reference=None
        frozen_eta=vector["trajectory"].get("graduation_eta_seconds")
        preholders={
            str(row["group"]).lower() for row in evaluation["market_events"]
        }
        entry_largest=int(vector["demand"]["largest_buyer_flow_bps"])
        seen_v4_buyers=set()
        pending_transition_exit_reason=None

        while True:
            if rpc.used>145:
                result["provider_sessions"].append(rpc.telemetry())
                rpc=paper_rpc(endpoint);rpc.verify_chain()
            time.sleep(EXIT_POLICY["monitor_seconds"])
            header=_latest_header(rpc)
            block=int(header["number"],16)
            position=paper._get(identity)
            elapsed=int(time.time())-opened_at

            if elapsed>=EXIT_POLICY["max_total_hold_seconds"]:
                if position["status"]=="exit_pending" and transition is not None:
                    position,meta=_complete_pending_v4_exit(
                        paper=paper,identity=identity,rpc=rpc,v4_key=v4_key,
                        gas_units=gas_units,store=store,label="selective-timeout-pending-v4-exit",
                    )
                elif position["status"]=="open":
                    try:
                        position,meta=_delayed_exit(
                            endpoint,paper=paper,identity=identity,rpc=rpc,candidate=candidate,
                            gas_units=gas_units,store=store,transition=transition,v4_key=v4_key,
                            label="selective-timeout-exit",exit_tokens=position["tokens"],
                        )
                    except BoundaryError as exc:
                        if str(exc)=="graduated_during_selective_exit":
                            pending_transition_exit_reason="max_total_hold"
                            continue
                        raise
                else:
                    continue
                result["exit"]=dict(reason="max_total_hold",quote=meta,position=position)
                result["status"]="settled"
                break

            if transition is None:
                maybe=_graduation_transition(
                    rpc,candidate,last_block,block,candidate["report"]
                )
                if maybe is not None:
                    transition,v4_key,grad_header,_=maybe
                    store.put("graduation",transition["proof_hash"],transition)
                    paper.advance(
                        identity,now=int(time.time()),action="transition",
                        transition=transition,
                    )
                    graduation_at=int(grad_header["timestamp"],16)
                    graduation_block=int(grad_header["number"],16)
                    result["graduation_transition"]=dict(
                        transition=transition,block=graduation_block,
                        event_at=graduation_at,
                    )
                    pending=paper._get(identity)
                    if pending["status"]=="exit_pending":
                        position,exit_meta=_complete_pending_v4_exit(
                            paper=paper,identity=identity,rpc=rpc,v4_key=v4_key,
                            gas_units=gas_units,store=store,
                            label="selective-transition-pending-exit",
                        )
                        exit_row=dict(
                            reason=(pending_transition_exit_reason or "pregraduation_exit"),
                            quote=exit_meta,position=position,
                        )
                        result.setdefault("exits",[]).append(exit_row)
                        if position["status"]=="settled":
                            result["exit"]=exit_row
                            result["status"]="settled"
                            break
                        pending_transition_exit_reason=None
                last_block=block

            position=paper._get(identity)
            if transition is None:
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
                last_curve_reference=dict(
                    tokens=position["tokens"],amount_out=mark.amount_out,
                    gas_quote=mark.gas_quote,at=mark.stamp.observed_at,
                )
                trajectory,demand,sessions=_refresh_curve_signal(
                    endpoint,candidate,meta
                )
                result["provider_sessions"].extend(sessions)
                reason=pregraduation_exit_reason(
                    elapsed_seconds=elapsed,frozen_eta_seconds=frozen_eta,
                    trajectory=trajectory,demand=demand,
                    after_cost_return_bps=rbps,
                )
                if rbps>high_water:
                    high_water=rbps;high_at=int(time.time())
                action=(
                    dict(action="full_exit",reason=reason,exit_tokens=position["tokens"])
                    if reason is not None else
                    dict(action="hold",reason=None,exit_tokens=0)
                )
                result["monitor"].append(dict(
                    at=mark.stamp.observed_at,market="curve",available=True,
                    return_bps=rbps,trajectory=trajectory,demand=demand,
                    action=action,pregraduation_exit_reason=reason,quote=meta,
                    profit_taking_deferred_until_post_graduation=True,
                ))
                if action["action"]=="full_exit":
                    try:
                        position,exit_meta=_delayed_exit(
                            endpoint,paper=paper,identity=identity,rpc=rpc,
                            candidate=candidate,gas_units=gas_units,store=store,
                            transition=None,v4_key=None,
                            label="selective-curve-exit",
                            exit_tokens=action["exit_tokens"],
                        )
                    except BoundaryError as exc:
                        if str(exc)=="graduated_during_selective_exit":
                            pending_transition_exit_reason=action["reason"]
                            continue
                        raise
                    result.setdefault("exits",[]).append(dict(
                        reason=action["reason"],quote=exit_meta,position=position,
                    ))
                    if position["status"]=="settled":
                        result["exit"]=result["exits"][-1]
                        result["status"]="settled"
                        break
                continue

            # Authenticated Pons V2 -> V4 transition has occurred.
            if not post_grad_checked:
                wait=max(
                    0,(graduation_at+POST_GRAD_OBSERVE_SECONDS)-int(time.time())
                )
                time.sleep(wait)
                header=_latest_header(rpc);block=int(header["number"],16)
                position=paper._get(identity)
                mark,meta,ledger=_v4_quote(
                    rpc,v4_key,position["market"],position["tokens"],gas_units,store,
                    "selective-postgrad-mark",local_freshness=True,
                )
                activity=collect_v4_activity(
                    endpoint,pool_id=position["market"],key=v4_key,
                    token=evaluation["token"],start_block=graduation_block,
                    end_block=block,preholder_groups=preholders,
                )
                result["provider_sessions"].extend(activity.pop("provider_sessions"))
                if not last_curve_reference or (
                    int(last_curve_reference["tokens"])!=int(position["tokens"])
                ):
                    retention=0
                else:
                    retention=int(mark.amount_out)*10_000//max(
                        1,int(last_curve_reference["amount_out"])
                    )
                post=post_graduation_vector(
                    observed_seconds=max(0,mark.stamp.event_at-graduation_at),
                    price_retention_bps=retention,
                    new_independent_buyers=activity["new_independent_buyers"],
                    buy_quote=activity["buy_quote"],sell_quote=activity["sell_quote"],
                    net_quote=activity["net_quote"],
                    preholder_sell_quote=activity["preholder_sell_quote"],
                    largest_buyer_flow_bps_before=entry_largest,
                    largest_buyer_flow_bps_now=activity["largest_buyer_flow_bps"],
                )
                result["post_graduation"]=dict(
                    vector=post,activity=activity,quote=meta
                )
                seen_v4_buyers.update(activity["buyer_groups"])
                post_grad_checked=True
                if not post["continuation_pass"]:
                    position,exit_meta=_delayed_exit(
                        endpoint,paper=paper,identity=identity,rpc=rpc,
                        candidate=candidate,gas_units=gas_units,store=store,
                        transition=transition,v4_key=v4_key,
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
                rpc,v4_key,position["market"],position["tokens"],gas_units,store,
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
                max(graduation_at,mark.stamp.event_at-15),cache,
            )
            result["provider_sessions"].append(locator.telemetry())
            activity=collect_v4_activity(
                endpoint,pool_id=position["market"],key=v4_key,
                token=evaluation["token"],
                start_block=int(start_header["number"],16),end_block=int(meta["block"]),
                preholder_groups=preholders,
            )
            result["provider_sessions"].extend(activity.pop("provider_sessions"))
            buyers=set(activity["buyer_groups"])
            growth=len(buyers-seen_v4_buyers)
            seen_v4_buyers.update(buyers)
            if rbps>high_water:
                high_water=rbps;high_at=int(time.time())
            action=runner_action(
                tokens=position["tokens"],partial_taken=partial_taken,
                after_cost_return_bps=rbps,high_water_return_bps=high_water,
                seconds_since_high=max(0,int(time.time())-high_at),
                new_buyer_growth=growth,buy_quote=activity["buy_quote"],
                sell_quote=activity["sell_quote"],
            )
            result["monitor"].append(dict(
                at=mark.stamp.observed_at,market="v4",available=True,
                return_bps=rbps,activity=activity,action=action,quote=meta,
            ))
            if action["action"] in ("partial_exit","full_exit"):
                position,exit_meta=_delayed_exit(
                    endpoint,paper=paper,identity=identity,rpc=rpc,candidate=candidate,
                    gas_units=gas_units,store=store,transition=transition,v4_key=v4_key,
                    label="selective-v4-exit",exit_tokens=action["exit_tokens"],
                )
                result.setdefault("exits",[]).append(dict(
                    reason=action["reason"],quote=exit_meta,position=position,
                ))
                partial_taken=partial_taken or position["status"]=="open"
                if position["status"]=="settled":
                    result["exit"]=result["exits"][-1]
                    result["status"]="settled"
                    break

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
        result["reconciliation"]=reconciliation
        result["realized_pnl_quote"]=result["final_position"]["pnl"]
        result["carried_through_graduation"]=transition is not None
        return result
    except BoundaryError as exc:
        result["status"]="boundary"
        result["boundary"]=str(exc)
        if store is not None:
            try:
                result["reconciliation"]=SelectivePaper(
                    store,STRATEGY_NAMESPACE,
                    max(STRATEGY_CAPITAL_QUOTE,1),
                    delay=EXIT_POLICY["entry_delay_seconds"],
                    natural_policy_hash=POLICY_HASH,
                ).reconcile()
            except Exception:
                pass
        return result
    finally:
        if rpc is not None:
            result["provider_sessions"].append(rpc.telemetry())
        if store is not None:
            try:store.close()
            except Exception:pass
        result["ended_at"]=time.time()
