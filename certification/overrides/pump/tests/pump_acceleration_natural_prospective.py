"""Natural prospective test for pump-acceleration-independent-v1.

The strategy and thresholds are frozen before this collector observes outcomes.
Discovery is the public finalized Pump stream.  HTTP evidence is the repository's
authoritative Alchemy lane.  No Engine.consider call, Store order, signing,
transaction submission, live money, or threshold adaptation exists here.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter,deque
from pathlib import Path
from types import SimpleNamespace

from meme_machine import pump
from meme_machine.concentration import ConcentrationReader
from meme_machine.engine import GAS
from meme_machine.market_native_shadow import discover_market_native
from meme_machine.postgrad import (
    PostGraduationAdapter,buy_quote,graduation_handoff,pumpswap_pool,sell_quote,
)
from meme_machine.provider import PumpAdapter,Unavailable
from meme_machine.pump_acceleration_confirmations import ConfirmationBook
from meme_machine.pump_acceleration_evidence import (
    curve_progress_bps,early_holder_sell_share_bps,late_curve_trajectory,
    postgrad_volume_acceleration_bps,price_return_bps,pumpswap_trade_events,
    reserve_price_parts,second_leg_shape,
)
from meme_machine.pump_acceleration_history import IncrementalPumpSwapHistory
from meme_machine.solana_evidence_consumers import StreamEvidenceService
from meme_machine.pipeline import Pipeline,censor_class
from meme_machine.pump_acceleration_paper import PumpAccelerationPaperLifecycle
from meme_machine.pump_acceleration_strategy import (
    MODE_LATE_CURVE,MODE_POSTGRAD,MODE_SECOND_LEG,POLICY,STRATEGY_ID,
    SignalVector,flow_metrics,policy_hash,qualify,
)
from meme_machine.solana_evidence_broker import (
    DEFAULT_BROKER_DB,DynamicAddressLogStream,EvidenceBroker,
)
from meme_machine.solana_read_rpc import discovery_ws_url,new_rpc,primary_rpc_url
from meme_machine.stream import PumpLogStream,PumpTape,WINDOW_SECONDS


REPORT=Path(os.environ.get("MM_PUMP_ACCELERATION_REPORT","pump-acceleration-natural-prospective.json"))
DISCOVERY_SECONDS=max(600,min(int(os.environ.get("MM_PUMP_ACCELERATION_DISCOVERY_SECONDS","3300")),3300))
FOLLOWUP_SECONDS=max(300,min(int(os.environ.get("MM_PUMP_ACCELERATION_FOLLOWUP_SECONDS","1000")),1200))
MAX_CREATED=5000
MAX_FULL_ATTEMPTS=120
MAX_POSTGRAD_CANDIDATES=12
GENESIS_SOL_USD_MICROS=97_840_000
INITIAL_USD_MICROS=500_000_000
INITIAL_LAMPORTS=INITIAL_USD_MICROS*1_000_000_000//GENESIS_SOL_USD_MICROS
ENTRY_BUDGET=INITIAL_LAMPORTS*POLICY.entry_fraction_bps//10_000
ENTRY_DELAY_SECONDS=2
ENTRY_FILL_TIMEOUT_SECONDS=20
FROZEN_POLICY_HASH="bb2631d83f5be287a0afc01dfc6d7a4da8b7086ae0afd09dfbf27df6d9d66a6e"
ACCOUNTING=None
PIPELINE=None

def _progress(candidate,stage,reason=None,**details):
    if PIPELINE is not None:
        classification=("strategy_rejection" if stage=="prospect_screened"
                        else (censor_class(reason) if reason else None))
        PIPELINE.record(candidate,stage,reason,classification,**details)


def _save(report):
    if PIPELINE is not None:report["opportunity_coverage"]=PIPELINE.snapshot()
    if ACCOUNTING is not None:
        report["accounting"]=ACCOUNTING.reconcile()
        report["accounting_replay"]=ACCOUNTING.replay()
    temporary=REPORT.with_suffix(REPORT.suffix+".tmp")
    temporary.write_text(json.dumps(report,indent=2,sort_keys=True))
    os.replace(temporary,REPORT)


class Sessions:
    def __init__(self):
        self.pacer=None;self.history=[]
        self.rotate("initial")

    def rotate(self,reason):
        if hasattr(self,"rpc"):
            self.history[-1].update(
                ended=int(time.time()),logical_requests=self.rpc.calls,
                transport_requests=self.rpc.http_requests,failures=self.rpc.failures,
                retries=self.rpc.retries,
                provider=self.rpc.provider_telemetry(),
                concentration=self.reader.status(),
            )
            self.pacer=self.rpc.read_pacer
        self.rpc=new_rpc(limit=240,pacer=self.pacer)
        self.pump=PumpAdapter(self.rpc)
        self.reader=ConcentrationReader(self.rpc)
        self.postgrad=PostGraduationAdapter(self.rpc,scan_rpc=None)
        self.history.append(dict(started=int(time.time()),reason=reason))

    def ensure(self,needed=20):
        if self.rpc.calls+int(needed)>190:
            self.rotate("bounded_evidence_session_rotation")
        program=self.reader.status()
        if int(program.get("program_scan_logical_requests",0))>=28:
            self.rotate("bounded_concentration_session_rotation")

    def finish(self):
        self.history[-1].update(
            ended=int(time.time()),logical_requests=self.rpc.calls,
            transport_requests=self.rpc.http_requests,failures=self.rpc.failures,
            retries=self.rpc.retries,
            provider=self.rpc.provider_telemetry(),
            concentration=self.reader.status(),
        )


def _attempt_key(mint,mode,now):
    return f"{mint}:{mode}:{int(now)}"


def _assert_fill_deadline(row, observed_now=None):
    """Fail closed if a blocking provider call returns after the fill deadline."""
    checked=int(time.time() if observed_now is None else observed_now)
    if checked-int(row["reserved_at"])>=ENTRY_FILL_TIMEOUT_SECONDS:
        raise ValueError("entry_fill_timeout")
    return checked


def _confirmation_meta(value):
    return dict(
        skilled_wallets_observed=int(value.get("skilled_wallets_observed",0)),
        skilled_wallet_clusters=int(value.get("skilled_wallet_clusters",0)),
        explicit_funding_groups_observed=int(value.get("explicit_funding_groups_observed",0)),
        creator_history_launches=int(value.get("creator_history_launches",0)),
        creator_quality_bps=value.get("creator_quality_bps"),
        excluded_clusters=sorted(value.get("excluded_clusters") or []),
    )


def _late_signal(creation,events,snapshot,concentration_bps,confirmation_book):
    now=int(snapshot["market_time"])
    curve=pump.curve(snapshot["accounts"][0])
    trajectory=late_curve_trajectory(creation,events,curve,now)
    creator=str(creation.get("creator") or curve.creator)
    confirmation=confirmation_book.signal_inputs(
        events,now,creator,snapshot["mint"])
    flow=flow_metrics(
        events,now,cluster_map=confirmation["cluster_map"],
        excluded_clusters=confirmation["excluded_clusters"])
    return SignalVector(
        mint=snapshot["mint"],observed_at=now,surface="pump.fun",phase=MODE_LATE_CURVE,
        quote_asset="SOL",
        curve_progress_bps=trajectory["curve_progress_bps"],
        curve_velocity_bps_per_s=trajectory["curve_velocity_bps_per_s"],
        curve_acceleration_bps_per_s2=trajectory["curve_acceleration_bps_per_s2"],
        independent_buyer_clusters=flow["independent_buyer_clusters"],
        buyer_growth=flow["buyer_growth"],net_buy_share_bps=flow["net_buy_share_bps"],
        concentration_bps=int(concentration_bps),
        extension_bps=int(trajectory["extension_bps"]),
        skilled_wallet_clusters=int(confirmation["skilled_wallet_clusters"]),
        creator_quality_bps=confirmation["creator_quality_bps"],
        creator_history_launches=int(confirmation["creator_history_launches"]),
        quote_relative_return_bps=int(trajectory["quote_relative_return_bps"]),
    ),trajectory,confirmation


def _late_stream_signal(creation,events,event,confirmation_book):
    """Cheap finalized-stream prospect screen; never grants trade authority.

    It applies only strategy fields already present in authenticated Pump logs.
    A pass merely permits the authoritative RPC snapshot/concentration path.
    A later fresh event can be reconsidered, so temporary non-qualification here
    does not remove a mint from observation.
    """
    now=int(event["market_time"])
    curve=SimpleNamespace(
        real_token=int(event["real_token_reserves"]),
        sol=int(event["virtual_quote_reserves"]),
        token=int(event["virtual_token_reserves"]),
        creator=str(creation.get("creator") or ""),
    )
    trajectory=late_curve_trajectory(creation,events,curve,now)
    creator=str(creation.get("creator") or "")
    confirmation=confirmation_book.signal_inputs(
        events,now,creator,event["mint"])
    flow=flow_metrics(
        events,now,cluster_map=confirmation["cluster_map"],
        excluded_clusters=confirmation["excluded_clusters"])
    return SignalVector(
        mint=event["mint"],observed_at=now,surface="pump.fun",phase=MODE_LATE_CURVE,
        quote_asset="SOL",
        curve_progress_bps=trajectory["curve_progress_bps"],
        curve_velocity_bps_per_s=trajectory["curve_velocity_bps_per_s"],
        curve_acceleration_bps_per_s2=trajectory["curve_acceleration_bps_per_s2"],
        independent_buyer_clusters=flow["independent_buyer_clusters"],
        buyer_growth=flow["buyer_growth"],net_buy_share_bps=flow["net_buy_share_bps"],
        concentration_bps=0,
        extension_bps=int(trajectory["extension_bps"]),
        skilled_wallet_clusters=int(confirmation["skilled_wallet_clusters"]),
        creator_quality_bps=confirmation["creator_quality_bps"],
        creator_history_launches=int(confirmation["creator_history_launches"]),
        quote_relative_return_bps=int(trajectory["quote_relative_return_bps"]),
    ),trajectory,confirmation


def _postgrad_concentration(rpc,snapshot):
    result=rpc.call("getTokenLargestAccounts",
                    [snapshot["mint"],{"commitment":"finalized"}],True)
    if not isinstance(result,dict) or "context" not in result or "value" not in result:
        raise Unavailable("invalid_postgrad_concentration")
    if int(result["context"].get("slot",-1)) < int(snapshot["slot"])-32:
        raise Unavailable("stale_postgrad_concentration")
    custody=snapshot["state"]["base_vault"]
    amounts=sorted(
        (int(x["amount"]) for x in result["value"] if x.get("address")!=custody),
        reverse=True,
    )
    supply=int(snapshot["state"]["mint_supply"])
    if supply<=0:
        raise ValueError("invalid_postgrad_supply")
    return sum(amounts[:5])*10_000//supply


def _refresh_pool_events(
    state,sessions,now,*,research=False,hydration_kind="pump_window"
):
    sessions.ensure(90)
    history=state["history"]
    events=history.refresh(
        sessions.rpc,now,research=research,hydration_kind=hydration_kind)
    state["history_status"]=history.status(now)
    return events


def _volume_price_signal(state,snapshot,events,mode,concentration,confirmation_book):
    now=int(snapshot["market_time"])
    creator=str((state.get("creation") or {}).get("creator") or snapshot.get("creator") or "")
    confirmation=confirmation_book.signal_inputs(
        events,now,creator,snapshot["mint"])
    flow=flow_metrics(
        events,now,cluster_map=confirmation["cluster_map"],
        excluded_clusters=confirmation["excluded_clusters"])
    current=reserve_price_parts(snapshot["state"]["base_reserve"],
                                snapshot["state"]["quote_reserve"])
    first=state.get("graduation_price")
    if first is None:
        state["graduation_price"]=list(current)
        first=current
    rel=price_return_bps(first[0],first[1],current[0],current[1])
    common=dict(
        mint=snapshot["mint"],observed_at=now,surface="pumpswap",phase=mode,
        quote_asset="SOL",independent_buyer_clusters=flow["independent_buyer_clusters"],
        buyer_growth=flow["buyer_growth"],net_buy_share_bps=flow["net_buy_share_bps"],
        concentration_bps=int(concentration),
        skilled_wallet_clusters=int(confirmation["skilled_wallet_clusters"]),
        creator_quality_bps=confirmation["creator_quality_bps"],
        creator_history_launches=int(confirmation["creator_history_launches"]),
        quote_relative_return_bps=int(rel),graduated=True,
        seconds_since_graduation=max(0,now-int(state["graduation_time"])),
        price_vs_graduation_bps=int(rel),
        volume_acceleration_bps=postgrad_volume_acceleration_bps(events,now),
        early_holder_sell_share_bps=early_holder_sell_share_bps(
            events,state["pregrad_wallets"]),
    )
    if mode==MODE_POSTGRAD:
        return SignalVector(**common),confirmation
    shape=second_leg_shape(
        events,state["graduation_time"],now,current)
    return SignalVector(**common,**{
        k:shape[k] for k in (
            "pullback_depth_bps","recovery_bps","consolidation_seconds","breakout_bps")
    }),confirmation


def _reserve_position(report,pending,active,qualification,snapshot,mode,concentration=0):
    key=(qualification.mint,mode)
    if key in pending or key in active:
        return
    if any(x["mint"]==qualification.mint and x["mode"]==mode for x in report["qualifiers"]):
        return
    reserved_at=int(snapshot["available_time"])
    import uuid
    lifecycle_id=(ACCOUNTING.identity["run_id"] if ACCOUNTING else "research")+":"+uuid.uuid4().hex
    life=PumpAccelerationPaperLifecycle(book=ACCOUNTING,lifecycle_id=lifecycle_id,
                                       entry_evidence=snapshot)
    life.reserve(qualification,ENTRY_BUDGET+GAS,reserved_at)
    _progress(qualification.mint,"entry_reserved",lifecycle_id=lifecycle_id)
    qrow=dict(
        lifecycle_id=lifecycle_id,
        mint=qualification.mint,mode=mode,qualified_at=qualification.observed_at,
        score=qualification.score,reasons=list(qualification.reasons),
        confirmations=list(qualification.confirmations),
        policy_hash=qualification.policy_hash,
        entry_status="reserved",reserved_at=reserved_at,
        fill_due=reserved_at+ENTRY_DELAY_SECONDS,
        decision_slot=int(snapshot["slot"]),
    )
    report["qualifiers"].append(qrow)
    pending[key]=dict(
        lifecycle=life,reserved_at=reserved_at,due=reserved_at+ENTRY_DELAY_SECONDS,
        decision_slot=int(snapshot["slot"]),qualifier_row=qrow,
        last_concentration=int(concentration),
    )


def _fill_pending(report,pending,active,sessions,postgrad,now):
    for key,row in list(pending.items()):
        if now<int(row["due"]):
            continue
        mint,mode=key
        life=row["lifecycle"]
        try:
            sessions.ensure(20)
            if mode==MODE_LATE_CURVE:
                snapshot=sessions.pump.snapshot(mint,now,priority=True)
                _assert_fill_deadline(row)
                curve=pump.curve(snapshot["accounts"][0])
                if curve.complete or curve.real_token==0:
                    raise ValueError("graduated_before_delayed_fill")
                if int(snapshot["slot"])<=int(row["decision_slot"]) or int(snapshot["market_time"])<int(row["due"]):
                    raise Unavailable("no_fresh_post_delay_quote")
                supply,_=pump.mint_info(snapshot["accounts"][1])
                rates=pump.fees(snapshot["accounts"][2],curve,supply)
                tokens,cost,fee=pump.buy(curve,ENTRY_BUDGET,rates)
                surface="pump.fun"
                entry=dict(tokens=tokens,cost=cost,fee=fee,gas=GAS)
            else:
                state=postgrad.get(mint)
                if state is None:
                    raise Unavailable("missing_postgrad_state")
                graduation=sessions.postgrad.graduation_snapshot(mint,now,priority=True)
                handoff=graduation_handoff(
                    graduation,max(now,int(graduation["available_time"])))
                snapshot=sessions.postgrad.pumpswap_snapshot(handoff,now,priority=True)
                _assert_fill_deadline(row)
                if int(snapshot["slot"])<=int(row["decision_slot"]) or int(snapshot["market_time"])<int(row["due"]):
                    raise Unavailable("no_fresh_post_delay_quote")
                quote=buy_quote(snapshot,ENTRY_BUDGET)
                tokens=quote.output_amount;cost=quote.input_amount;surface="pumpswap"
                entry=dict(tokens=tokens,cost=cost,fee=quote.fee_amount,gas=GAS)

            basis=cost+GAS
            life.fill(tokens,basis,int(snapshot["available_time"]),surface,
                      evidence=dict(snapshot=snapshot,entry=entry))
            active[key]=dict(
                lifecycle=life,opened=int(snapshot["available_time"]),
                next_monitor=int(snapshot["available_time"])+5,
                entry=entry,marks={},
                last_concentration=int(row.get("last_concentration",0)),
            )
            row["qualifier_row"].update(
                entry_status="filled",filled_at=int(snapshot["available_time"]),
                fill_slot=int(snapshot["slot"]),entry=entry,
            )
            _progress(mint,"entry_filled",lifecycle_id=life.lifecycle_id)
            pending.pop(key,None)
        except (Unavailable,ValueError,KeyError,TypeError) as exc:
            reason=str(exc) or type(exc).__name__
            decision_now=int(time.time())
            if (reason in ("graduated_before_delayed_fill","entry_fill_timeout") or
                    decision_now-int(row["reserved_at"])>=ENTRY_FILL_TIMEOUT_SECONDS):
                try:
                    life.cancel(reason,decision_now)
                    _progress(mint,"entry_cancelled",reason,lifecycle_id=getattr(life,"lifecycle_id",None))
                except ValueError:
                    pass
                row["qualifier_row"].update(
                    entry_status="cancelled",cancelled_at=decision_now,entry_limitation=reason)
                pending.pop(key,None)
            else:
                row["qualifier_row"]["last_fill_limitation"]=reason

def _record_attempt(report,signal,q,stage,extra=None):
    if stage=="full_point_in_time":_progress(signal.mint,"evidence_complete",mode=signal.phase)
    _progress(signal.mint,"evaluated",mode=signal.phase)
    _progress(signal.mint,"qualified" if q.qualified else "rejected",mode=signal.phase)
    row=dict(
        mint=signal.mint,mode=signal.phase,observed_at=signal.observed_at,
        stage=stage,score=q.score,qualified=q.qualified,reasons=list(q.reasons),
        confirmations=list(q.confirmations),
        curve_progress_bps=signal.curve_progress_bps,
        velocity=signal.curve_velocity_bps_per_s,
        acceleration=signal.curve_acceleration_bps_per_s2,
        independent_buyers=signal.independent_buyer_clusters,
        buyer_growth=signal.buyer_growth,net_buy_share_bps=signal.net_buy_share_bps,
        concentration_bps=signal.concentration_bps,
        extension_bps=signal.extension_bps,
        seconds_since_graduation=signal.seconds_since_graduation,
        price_vs_graduation_bps=signal.price_vs_graduation_bps,
        volume_acceleration_bps=signal.volume_acceleration_bps,
        early_holder_sell_share_bps=signal.early_holder_sell_share_bps,
        pullback_depth_bps=signal.pullback_depth_bps,
        recovery_bps=signal.recovery_bps,
        consolidation_seconds=signal.consolidation_seconds,
        breakout_bps=signal.breakout_bps,
    )
    if extra:
        row.update(extra)
    if ACCOUNTING is not None:
        with REPORT.with_suffix(".candidates.jsonl").open("a") as sink:
            sink.write(json.dumps(dict(policy_hash=policy_hash(),**row),sort_keys=True)+"\n")
            sink.flush();os.fsync(sink.fileno())
    if stage=="full_point_in_time":
        # Full-evidence rows are an append-only experiment ledger and are never
        # removed by the rolling UI/debug attempt buffer.
        report["full_evidence_candidates"].append(dict(row))
    report["attempts"].append(row)
    report["attempts"]=report["attempts"][-1000:]


def _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,now):
    # Exact frozen exit controller on natural qualifiers.  Each qualifier is
    # an isolated research lifecycle; no shared Store capital is mutated.
    for key,row in list(active.items()):
        if now<int(row["next_monitor"]):
            continue
        mint,mode=key
        row["next_monitor"]=now+5
        life=row["lifecycle"]
        try:
            sessions.ensure(20)
            position=life.position
            if position is None:
                active.pop(key,None);continue
            demand_score=0;confirmed=False
            if position.surface=="pump.fun":
                snapshot=sessions.pump.snapshot(mint,now,priority=True)
                curve=pump.curve(snapshot["accounts"][0])
                if curve.complete or curve.real_token==0:
                    graduation=sessions.postgrad.graduation_snapshot(mint,now,priority=True)
                    handoff=graduation_handoff(graduation,max(now,int(graduation["available_time"])))
                    life.authenticate_graduation(now,True)
                    snapshot=sessions.postgrad.pumpswap_snapshot(handoff,now,priority=True)
                    quote=sell_quote(snapshot,life.position.tokens)
                    proceeds=max(0,quote.output_amount-GAS)
                else:
                    supply,_=pump.mint_info(snapshot["accounts"][1])
                    rates=pump.fees(snapshot["accounts"][2],curve,supply)
                    proceeds_raw,_=pump.sell(curve,life.position.tokens,rates)
                    proceeds=max(0,proceeds_raw-GAS)
                    try:
                        creation=created[mint]["creation"]
                        ev=tape.window(mint,int(snapshot["market_time"]),max_slot=snapshot["slot"])
                        current,_trajectory,_confirmation=_late_signal(
                            creation,ev,snapshot,
                            int(row.get("last_concentration",0)),confirmations)
                        demand_score=qualify(current).score
                    except Exception:
                        demand_score=0
            else:
                state=postgrad.get(mint)
                if state is None:
                    raise Unavailable("missing_postgrad_state")
                graduation=sessions.postgrad.graduation_snapshot(mint,now,priority=True)
                handoff=graduation_handoff(graduation,max(now,int(graduation["available_time"])))
                snapshot=sessions.postgrad.pumpswap_snapshot(handoff,now,priority=True)
                events=_refresh_pool_events(
                    state,sessions,now,research=False,
                    hydration_kind="position_monitor")
                quote=sell_quote(snapshot,life.position.tokens)
                proceeds=max(0,quote.output_amount-GAS)
                concentration=_postgrad_concentration(sessions.rpc,snapshot)
                current,_confirmation=_volume_price_signal(
                    state,snapshot,events,MODE_POSTGRAD,concentration,confirmations)
                cq=qualify(current);demand_score=cq.score;confirmed=cq.qualified

            mark_evidence=dict(snapshot=snapshot,net_proceeds=proceeds,
                               network_cost=GAS)
            mark=life.mark(proceeds,now,demand_score,confirmed,evidence=mark_evidence)
            age=now-int(row["opened"])
            for horizon in (15,60,300,900):
                if age>=horizon and str(horizon) not in row["marks"]:
                    row["marks"][str(horizon)]=dict(
                        observed_at=now,return_bps=mark["return_bps"],
                        proceeds=proceeds)
            if mark["exit_reason"] is not None:
                _progress(mint,"unwind",lifecycle_id=life.lifecycle_id)
                closed=life.settle(proceeds,now,evidence=mark_evidence)
                _progress(mint,"settled",lifecycle_id=life.lifecycle_id)
                report["settled"].append(dict(
                    lifecycle_id=life.lifecycle_id,
                    mint=mint,mode=mode,opened=row["opened"],closed=now,
                    exit_reason=closed["exit_reason"],
                    realized_quote_units=closed["realized_quote_units"],
                    marks=dict(row["marks"]),history=life.snapshot()["history"]))
                active.pop(key,None)
        except (Unavailable,ValueError,KeyError,TypeError) as exc:
            row.setdefault("monitor_failures",[]).append(dict(
                observed_at=now,reason=str(exc) or type(exc).__name__))
            row["monitor_failures"]=row["monitor_failures"][-20:]


class RollingAttemptBudget:
    def __init__(self,limit=MAX_FULL_ATTEMPTS,window=3300):
        self.limit=limit;self.window=window;self.admitted=deque()

    def take(self,now):
        while self.admitted and self.admitted[0]<=now-self.window:self.admitted.popleft()
        if len(self.admitted)>=self.limit:return False
        self.admitted.append(now);return True


def _terminal(report,row):
    with REPORT.with_suffix('.terminal.jsonl').open('a') as sink:
        sink.write(json.dumps(dict(policy_hash=policy_hash(),**row),sort_keys=True)+'\n')
        sink.flush();os.fsync(sink.fileno())
    counts=report.setdefault('terminal_reason_counts',{})
    _progress(row.get("mint","unknown"),"terminal",row["terminal_reason"])
    reason=row['terminal_reason'];counts[reason]=counts.get(reason,0)+1


def _pumpswap_prefetch_filter(address,value,slot):
    """Use public stream logs only as hydration hints, never as economics."""
    tx={'slot':int(slot),'meta':{'err':value.get('err'),
        'logMessages':value.get('logs') or []}}
    return any(event.get('pool')==str(address) for event in pumpswap_trade_events(tx))


def _retire_postgrad(report,postgrad,pending,active,stream,now):
    protected={key[0] for key in pending}|{key[0] for key in active}
    for mint,state in list(postgrad.items()):
        if mint in protected or now-int(state['graduation_time'])<=max(POLICY.max_postgrad_entry_age_s,600):
            continue
        # Durable terminal evidence is written before releasing the stream slot.
        row=dict(mint=mint,observed_at=now,terminal_reason='postgrad_entry_horizon_expired',
                 history_status=state['history'].status(now))
        _terminal(report,row)
        stream.remove_address(state['pool'])
        del postgrad[mint]
        report['retired_postgrad_candidates']=report.get('retired_postgrad_candidates',0)+1


def main(*,campaign=False,discovery_seconds=None):
    global ACCOUNTING,PIPELINE
    from meme_machine.paper_accounting import PaperBook
    import uuid
    if type(campaign) is not bool:raise ValueError('pump_campaign_flag')
    discovery_seconds=DISCOVERY_SECONDS if discovery_seconds is None else int(discovery_seconds)
    if not 600<=discovery_seconds<=(21600 if campaign else 3300):
        raise ValueError('pump_discovery_runtime_bound')
    actual_policy_hash=policy_hash()
    if actual_policy_hash!=FROZEN_POLICY_HASH:
        raise RuntimeError("frozen_policy_hash_changed")
    confirmations=ConfirmationBook.from_files()
    run_id=os.environ.get("MM_CERTIFICATION_RUN_ID") or uuid.uuid4().hex
    accounting_path=REPORT.with_suffix(".accounting.sqlite3")
    if accounting_path.exists():
        raise RuntimeError("existing_paper_book_requires_explicit_recovery")
    ACCOUNTING=PaperBook(str(accounting_path),run_id=run_id,lane=STRATEGY_ID,
                         policy_hash=actual_policy_hash,initial=INITIAL_LAMPORTS)
    PIPELINE=Pipeline(REPORT.with_suffix(".pipeline.sqlite"),"pump",actual_policy_hash)
    report=dict(
        kind="pump_acceleration_natural_prospective",
        strategy_id=STRATEGY_ID,policy_hash=actual_policy_hash,
        expected_policy_hash=FROZEN_POLICY_HASH,
        frozen_policy=True,threshold_changes_allowed=False,threshold_changes_made=False,
        selection_uses_future_outcomes=False,outcomes_can_change_policy=False,
        order_authority=False,signing_authority=False,transaction_submission_authority=False,
        live_money_authority=False,shared_portfolio_mutation=False,
        discovery_source="finalized_public_pump_logs",
        market_observation_scope="all finalized Pump events for observability",
        prospect_universe_rule=(
            "late-curve RPC evaluation only after finalized-stream progress, "
            "trajectory, independent-demand and extension gates can qualify; "
            "post-graduation modes observe authenticated graduations within their entry horizons"),
        evidence_source="alchemy_http_primary_no_rescue",
        evidence_acquisition_mode=(
            "candidate_pool_finalized_stream_plus_bounded_decision_bootstrap_"
            "plus_incremental_durable_http_hydration"),
        curve_progress_definition="prospectively observed CreateEvent initial_real_token_reserves -> reserve depletion",
        velocity_window_seconds=30,extension_lookback_seconds=10,
        entry_budget_lamports=ENTRY_BUDGET,entry_fraction_bps=POLICY.entry_fraction_bps,
        entry_delay_seconds=ENTRY_DELAY_SECONDS,entry_fill_timeout_seconds=ENTRY_FILL_TIMEOUT_SECONDS,
        discovery_seconds=discovery_seconds,followup_seconds=FOLLOWUP_SECONDS,continuous_campaign=campaign,
        started=int(time.time()),stream={},sessions=[],counts={},limitations=[],
        run_id=run_id,accounting_path=str(accounting_path),
        confirmation_evidence=confirmations.status(),
        attempts=[],full_evidence_candidates=[],qualifiers=[],settled=[],
        open_positions=[],postgrad=[],
    )
    report['operational_configuration']=dict(campaign=campaign,discovery_seconds=discovery_seconds,
        full_attempt_limit=MAX_FULL_ATTEMPTS,full_attempt_window_seconds=3300 if campaign else None,
        concurrent_postgrad_limit=MAX_POSTGRAD_CANDIDATES,followup_seconds=FOLLOWUP_SECONDS,
        open_positions_before_candidate_hydration=True)
    import hashlib
    report['operational_configuration_hash']=hashlib.sha256(json.dumps(
        report['operational_configuration'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    _save(report)

    tape=PumpTape()
    broker_path=os.environ.get(
        "MM_SOLANA_EVIDENCE_BROKER_DB",DEFAULT_BROKER_DB)
    broker=EvidenceBroker(broker_path)
    stop=threading.Event();ready=threading.Event();pumpswap_ready=threading.Event()
    stream=PumpLogStream(primary_rpc_url(),tape,ws_url=discovery_ws_url())
    # Additional acquisition concurrency is allowed only underneath the shared
    # cross-process governor. Standalone runners retain their original transport cap.
    incremental=bool(campaign and os.environ.get('MM_CERT_GOVERNOR_DB'))
    pumpswap_stream=DynamicAddressLogStream(
        discovery_ws_url(),broker,"pumpswap_pool",coverage_seconds=30,prefetch=incremental,
        prefetch_filter=_pumpswap_prefetch_filter)
    evidence_service=StreamEvidenceService(broker,lambda:new_rpc(limit=240)) if incremental else None
    thread=threading.Thread(target=stream.run,args=(stop,ready),daemon=True)
    pumpswap_thread=threading.Thread(
        target=pumpswap_stream.run,args=(stop,pumpswap_ready),daemon=True)
    thread.start();pumpswap_thread.start()
    if not ready.wait(15):
        report["limitations"].append("pump_stream_start_timeout")
        _save(report)
        raise SystemExit(1)
    if not pumpswap_ready.wait(15):
        report["limitations"].append("pumpswap_stream_start_timeout")

    sessions=Sessions()
    cursor=0;created={};postgrad={};pending={};active={};full_attempts=0
    last_eval={};last_postgrad_eval={};last_save=0
    discovery_end=int(time.time())+discovery_seconds
    attempt_budget=RollingAttemptBudget()
    end=discovery_end+FOLLOWUP_SECONDS

    try:
        if evidence_service:evidence_service.start()
        while int(time.time())<end:
            if evidence_service:evidence_service.check()
            now=int(time.time())
            _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,now)
            _fill_pending(report,pending,active,sessions,postgrad,int(time.time()))
            if campaign:_retire_postgrad(report,postgrad,pending,active,pumpswap_stream,int(time.time()))
            fresh,cursor=tape.events_since(cursor)
            for event in fresh:
                creation=tape.creation(event["mint"])
                if creation is None:
                    continue
                if event["mint"] not in created:
                    created[event["mint"]]=dict(
                        creation=creation,pregrad_wallets=set(),graduated=False)
                    _progress(event["mint"],"discovered")
                    confirmations.observe_creation(creation)
                state=created[event["mint"]]
                if len(state["pregrad_wallets"])<500 and event.get("wallet"):
                    state["pregrad_wallets"].add(event["wallet"])
                if int(event.get("real_token_reserves",-1))==0 and not state["graduated"]:
                    state["graduated"]=True
                    state["graduation_time"]=int(event["market_time"])
                    confirmations.observe_graduation(
                        event["mint"],int(event.get("available_time") or now))
                    position_needs_stream=any(key[0]==event['mint'] for key in (*pending,*active))
                    if len(postgrad)<MAX_POSTGRAD_CANDIDATES or position_needs_stream:
                        pool=pumpswap_pool(event["mint"])
                        stream_key=pumpswap_stream.add_address(pool)
                        postgrad[event["mint"]]=dict(
                            mint=event["mint"],creation=state["creation"],
                            graduation_time=int(event["market_time"]),
                            pregrad_wallets=set(state["pregrad_wallets"]),pool=pool,
                            history=IncrementalPumpSwapHistory(
                                pool,int(event["market_time"]),broker=broker,
                                stream_key=stream_key),
                            history_status={},graduation_price=None,
                        )
                    else:
                        _terminal(report,dict(mint=event['mint'],observed_at=now,
                            terminal_reason='postgrad_candidate_capacity',economic_rejection=False))

            # New late-curve entries stop at discovery_end; follow-up never backfills
            # another pre-graduation decision.
            if now<discovery_end and tape.covered(now):
                for event in fresh:
                    _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,int(time.time()))
                    _fill_pending(report,pending,active,sessions,postgrad,int(time.time()))
                    now=int(time.time())
                    if now>=discovery_end:break
                    mint=event.get("mint")
                    state=created.get(mint)
                    if state is None or state.get("graduated"):
                        continue
                    if now-int(last_eval.get(mint,0))<5:
                        continue
                    creation=state["creation"]
                    try:
                        progress=curve_progress_bps(
                            creation["initial_real_token_reserves"],
                            event["real_token_reserves"])
                    except (KeyError,ValueError,TypeError):
                        continue
                    if progress<POLICY.min_curve_progress_bps:
                        continue
                    last_eval[mint]=now
                    try:
                        stream_time=int(event["market_time"])
                        stream_events=tape.window(
                            mint,stream_time,max_slot=int(event["slot"]))
                        prospect,prospect_trajectory,prospect_confirmation=_late_stream_signal(
                            creation,stream_events,event,confirmations)
                        prospect_q=qualify(prospect)
                    except (ValueError,KeyError,TypeError) as exc:
                        reason=str(exc) or type(exc).__name__
                        counts=report.setdefault("prospect_screen_incomplete_counts",{})
                        counts[reason]=counts.get(reason,0)+1
                        continue
                    if not prospect_q.qualified:
                        reason="strategy_prospect:"+",".join(prospect_q.reasons)
                        _progress(mint,"prospect_screened",reason,mode=MODE_LATE_CURVE)
                        counts=report.setdefault("prospect_screen_rejection_counts",{})
                        for item in prospect_q.reasons:
                            counts[item]=counts.get(item,0)+1
                        continue
                    _progress(mint,"screened",mode=MODE_LATE_CURVE)
                    _progress(mint,"admitted",mode=MODE_LATE_CURVE)
                    _progress(mint,"evidence_requested",mode=MODE_LATE_CURVE,decision_at=now)
                    try:
                        sessions.ensure(25)
                        snapshot=sessions.pump.snapshot(mint,now,priority=True)
                        ev=tape.window(mint,int(snapshot["market_time"]),max_slot=snapshot["slot"])
                        pre_signal,trajectory,confirmation=_late_signal(
                            creation,ev,snapshot,0,confirmations)
                        preq=qualify(pre_signal)
                        # concentration=0 is the optimistic preflight.  If even that
                        # cannot qualify, an expensive holder scan cannot rescue it.
                        if not preq.qualified:
                            _record_attempt(
                                report,pre_signal,preq,"optimistic_preflight",
                                {"trajectory":trajectory,
                                 "confirmation_evidence":_confirmation_meta(confirmation)})
                            continue
                        if (not attempt_budget.take(time.monotonic()) if campaign else full_attempts>=MAX_FULL_ATTEMPTS):
                            _terminal(report,dict(mint=mint,observed_at=now,
                                terminal_reason='full_evidence_attempt_cap',economic_rejection=False))
                            if "full_evidence_attempt_cap" not in report["limitations"]:
                                report["limitations"].append("full_evidence_attempt_cap")
                            continue
                        full_attempts+=1
                        concentration,meta=sessions.reader.read(mint,snapshot,priority=True)
                        signal,trajectory,confirmation=_late_signal(
                            creation,ev,snapshot,concentration,confirmations)
                        q=qualify(signal)
                        _record_attempt(
                            report,signal,q,"full_point_in_time",
                            {"concentration_source":meta.get("source"),
                             "trajectory":trajectory,
                             "confirmation_evidence":_confirmation_meta(confirmation)})
                        if q.qualified and not any(
                                x["mint"]==mint and x["mode"]==MODE_LATE_CURVE
                                for x in report["qualifiers"]):
                            _reserve_position(
                                report,pending,active,q,snapshot,MODE_LATE_CURVE,concentration)
                    except (Unavailable,ValueError,KeyError,TypeError) as exc:
                        _progress(mint,"terminal",str(exc),mode=MODE_LATE_CURVE)
                        report["attempts"].append(dict(
                            mint=mint,mode=MODE_LATE_CURVE,observed_at=now,
                            stage="incomplete",qualified=False,
                            limitation=str(exc) or type(exc).__name__))

            # Natural post-graduation and second-leg entries may occur during the
            # follow-up because their decision time is necessarily after migration.
            for mint,state in list(postgrad.items()):
                _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,int(time.time()))
                _fill_pending(report,pending,active,sessions,postgrad,int(time.time()))
                now=int(time.time())
                if campaign and now>=discovery_end:break
                age=now-int(state["graduation_time"])
                if age<5 or now-int(last_postgrad_eval.get(mint,0))<10:
                    continue
                if age>max(POLICY.max_postgrad_entry_age_s,600):
                    continue
                last_postgrad_eval[mint]=now
                _progress(mint,"admitted")
                _progress(mint,"evidence_requested",mode=MODE_POSTGRAD,decision_at=now)
                try:
                    sessions.ensure(85)
                    graduation=sessions.postgrad.graduation_snapshot(mint,now,priority=True)
                    handoff=graduation_handoff(graduation,max(now,int(graduation["available_time"])))
                    snapshot=sessions.postgrad.pumpswap_snapshot(handoff,now,priority=True)
                    events=_refresh_pool_events(
                        state,sessions,now,
                        research=(age>=POLICY.min_second_leg_age_s))
                    window_status=state["history"].decision_window_status(now,30)
                    if not window_status["complete"]:
                        raise Unavailable("incomplete_pumpswap_decision_window")
                    decision_events=state["history"].decision_rows(now,30)
                    concentration=_postgrad_concentration(sessions.rpc,snapshot)
                    signal,confirmation=_volume_price_signal(
                        state,snapshot,decision_events,MODE_POSTGRAD,concentration,confirmations)
                    q=qualify(signal)
                    _record_attempt(
                        report,signal,q,"full_point_in_time",
                        {"history_status":state["history"].status(now),
                         "confirmation_evidence":_confirmation_meta(confirmation)})
                    if q.qualified and not any(
                            x["mint"]==mint and x["mode"]==MODE_POSTGRAD
                            for x in report["qualifiers"]):
                        _reserve_position(
                            report,pending,active,q,snapshot,MODE_POSTGRAD,concentration)

                    if age>=POLICY.min_second_leg_age_s:
                        try:
                            if not state["history"].complete(now):
                                raise Unavailable("incomplete_pumpswap_second_leg_history")
                            second,confirmation2=_volume_price_signal(
                                state,snapshot,events,MODE_SECOND_LEG,concentration,confirmations)
                            q2=qualify(second)
                            _record_attempt(
                                report,second,q2,"full_point_in_time",
                                {"history_status":state["history"].status(now),
                                 "confirmation_evidence":_confirmation_meta(confirmation2)})
                            if q2.qualified and not any(
                                    x["mint"]==mint and x["mode"]==MODE_SECOND_LEG
                                    for x in report["qualifiers"]):
                                _reserve_position(
                                    report,pending,active,q2,snapshot,MODE_SECOND_LEG,concentration)
                        except (Unavailable,ValueError,KeyError,TypeError) as exc:
                            _progress(mint,"terminal",str(exc),mode=MODE_SECOND_LEG,history=state["history"].status(now))
                            report["attempts"].append(dict(
                                mint=mint,mode=MODE_SECOND_LEG,observed_at=now,
                                stage="shape_incomplete",qualified=False,
                                limitation=str(exc) or type(exc).__name__))
                except (Unavailable,ValueError,KeyError,TypeError) as exc:
                    _progress(mint,"terminal",str(exc),mode=MODE_POSTGRAD)
                    report["postgrad"].append(dict(
                        mint=mint,observed_at=now,age_seconds=age,
                        complete=False,limitation=str(exc) or type(exc).__name__,
                        history_status=(
                            state["history"].status(now)
                            if state.get("history") is not None else None)))
                    report["postgrad"]=report["postgrad"][-300:]

            # Paper entries use the repository-standard two-second delay and a fresh
            # executable quote. This is execution realism, not a strategy threshold.
            _fill_pending(report,pending,active,sessions,postgrad,now)

            _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,int(time.time()))

            if now-last_save>=15:
                report["created_mints_observed"]=len(created)
                report["full_evidence_attempts"]=full_attempts
                report["active_provider"]=sessions.rpc.provider_telemetry()
                report["evidence_broker"]=broker.telemetry()
                counts=Counter()
                for attempt in report["attempts"]:
                    counts[f'{attempt.get("mode")}:{attempt.get("stage")}']+=1
                    if attempt.get("qualified"):
                        counts[f'{attempt.get("mode")}:qualified']+=1
                report["counts"]=dict(counts)
                report["stream"]=tape.status(now)
                report["pending_entries"]=[
                    dict(mint=k[0],mode=k[1],reserved_at=v["reserved_at"],
                         due=v["due"],snapshot=v["lifecycle"].snapshot())
                    for k,v in pending.items()]
                report["open_positions"]=[
                    dict(mint=k[0],mode=k[1],opened=v["opened"],
                         marks=dict(v["marks"]),snapshot=v["lifecycle"].snapshot())
                    for k,v in active.items()]
                _save(report);last_save=now
            time.sleep(1)
    finally:
        stop.set();thread.join(timeout=5);pumpswap_thread.join(timeout=5)
        if evidence_service:
            evidence_service.close()
            report['stream_evidence_sessions']=evidence_service.sessions
        sessions.finish()
        report["sessions"]=sessions.history
        report["stream"]=tape.status(int(time.time()))
        report["pumpswap_stream"]=pumpswap_stream.status()
        report["evidence_broker"]=broker.telemetry()
        report["ended"]=int(time.time())
        report["pending_entries"]=[dict(mint=k[0],mode=k[1],snapshot=v["lifecycle"].snapshot())
                                    for k,v in pending.items()]
        report["open_positions"]=[dict(mint=k[0],mode=k[1],snapshot=v["lifecycle"].snapshot())
                                   for k,v in active.items()]
        report["full_evidence_attempts"]=full_attempts
        report["created_mints_observed"]=len(created)
        report["postgrad_candidates"]=len(postgrad)
        report["confirmation_evidence"]=confirmations.status()
        report["postgrad_history_status"]={
            mint:state["history"].status(int(time.time()))
            for mint,state in postgrad.items() if state.get("history") is not None
        }
        report["pending_entries"]=[
            dict(mint=k[0],mode=k[1],reserved_at=v["reserved_at"],
                 due=v["due"],snapshot=v["lifecycle"].snapshot())
            for k,v in pending.items()]
        report["open_positions"]=[
            dict(mint=k[0],mode=k[1],opened=v["opened"],
                 marks=dict(v["marks"]),snapshot=v["lifecycle"].snapshot())
            for k,v in active.items()]
        report["threshold_changes_made"]=False
        _save(report)
        broker.close()
        ACCOUNTING.close();ACCOUNTING=None
        PIPELINE.close();PIPELINE=None
    print(json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
