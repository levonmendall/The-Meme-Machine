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
from collections import Counter
from pathlib import Path

from meme_machine import pump
from meme_machine.concentration import ConcentrationReader
from meme_machine.engine import GAS
from meme_machine.market_native_shadow import discover_market_native
from meme_machine.postgrad import (
    PostGraduationAdapter,buy_quote,graduation_handoff,pumpswap_pool,sell_quote,
)
from meme_machine.provider import PumpAdapter,Unavailable
from meme_machine.pump_acceleration_evidence import (
    curve_progress_bps,early_holder_sell_share_bps,late_curve_trajectory,
    postgrad_volume_acceleration_bps,price_return_bps,pumpswap_trade_events,
    reserve_price_parts,second_leg_shape,
)
from meme_machine.pump_acceleration_paper import PumpAccelerationPaperLifecycle
from meme_machine.pump_acceleration_strategy import (
    MODE_LATE_CURVE,MODE_POSTGRAD,MODE_SECOND_LEG,POLICY,STRATEGY_ID,
    SignalVector,flow_metrics,policy_hash,qualify,
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


def _save(report):
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True))


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


def _late_signal(creation,events,snapshot,concentration_bps):
    now=int(snapshot["market_time"])
    curve=pump.curve(snapshot["accounts"][0])
    trajectory=late_curve_trajectory(creation,events,curve,now)
    flow=flow_metrics(events,now)
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
        skilled_wallet_clusters=0,creator_quality_bps=None,creator_history_launches=0,
        quote_relative_return_bps=int(trajectory["quote_relative_return_bps"]),
    ),trajectory


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


def _refresh_pool_events(state,sessions,now):
    sessions.ensure(70)
    pool=state["pool"]
    rows=sessions.rpc.call(
        "getSignaturesForAddress",
        [pool,{"limit":40,"commitment":"finalized"}],True,
    )
    if not isinstance(rows,list):
        raise Unavailable("invalid_pumpswap_history")
    times=[int(x["blockTime"]) for x in rows if x.get("blockTime") is not None]
    if any(x.get("blockTime") is None for x in rows):
        state["history_complete"]=False
    if len(rows)==40 and times and min(times)>int(state["graduation_time"]):
        state["history_complete"]=False
        state["history_capacity_loss"]=True
    elif len(rows)<40 or (times and min(times)<=int(state["graduation_time"])):
        state["history_complete"]=True

    new=[x for x in rows if not x.get("err") and x.get("signature") not in state["signatures"]]
    params=[[x["signature"],{"encoding":"json","commitment":"finalized",
                            "maxSupportedTransactionVersion":0}] for x in new]
    txs=sessions.rpc.call_many("getTransaction",params,True,batch_size=8) if params else []
    for sig,tx in zip(new,txs):
        state["signatures"].add(sig["signature"])
        if tx is None:
            state["history_complete"]=False
            continue
        for event in pumpswap_trade_events(tx):
            if event["pool"]!=pool:
                continue
            event["id"]=f'{sig["signature"]}:{event["index"]}'
            state["events"][event["id"]]=event
    cutoff=int(now)-300
    state["events"]={k:v for k,v in state["events"].items()
                     if int(v["market_time"])>=cutoff}
    return sorted(state["events"].values(),
                  key=lambda e:(int(e["market_time"]),int(e["slot"]),int(e["index"])))


def _volume_price_signal(state,snapshot,events,mode,concentration):
    now=int(snapshot["market_time"])
    flow=flow_metrics(events,now)
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
        concentration_bps=int(concentration),skilled_wallet_clusters=0,
        creator_quality_bps=None,creator_history_launches=0,
        quote_relative_return_bps=int(rel),graduated=True,
        seconds_since_graduation=max(0,now-int(state["graduation_time"])),
        price_vs_graduation_bps=int(rel),
        volume_acceleration_bps=postgrad_volume_acceleration_bps(events,now),
        early_holder_sell_share_bps=early_holder_sell_share_bps(
            events,state["pregrad_wallets"]),
    )
    if mode==MODE_POSTGRAD:
        return SignalVector(**common)
    shape=second_leg_shape(
        events,state["graduation_time"],now,current)
    return SignalVector(**common,**{
        k:shape[k] for k in (
            "pullback_depth_bps","recovery_bps","consolidation_seconds","breakout_bps")
    })


def _open_position(report,active,qualification,snapshot,mode):
    if (qualification.mint,mode) in active:
        return
    life=PumpAccelerationPaperLifecycle()
    life.reserve(qualification,ENTRY_BUDGET+GAS,int(snapshot["available_time"]))
    if snapshot.get("protocol")=="pump.fun":
        curve=pump.curve(snapshot["accounts"][0])
        supply,_=pump.mint_info(snapshot["accounts"][1])
        rates=pump.fees(snapshot["accounts"][2],curve,supply)
        tokens,cost,fee=pump.buy(curve,ENTRY_BUDGET,rates)
        surface="pump.fun"
        entry=dict(tokens=tokens,cost=cost,fee=fee,gas=GAS)
    else:
        quote=buy_quote(snapshot,ENTRY_BUDGET)
        tokens=quote.output_amount;cost=quote.input_amount;surface="pumpswap"
        entry=dict(tokens=tokens,cost=cost,fee=quote.fee_amount,gas=GAS)
    basis=cost+GAS
    life.fill(tokens,basis,int(snapshot["available_time"]),surface)
    key=(qualification.mint,mode)
    active[key]=dict(
        lifecycle=life,opened=int(snapshot["available_time"]),next_monitor=int(snapshot["available_time"])+5,
        entry=entry,marks={},last_concentration=0,
    )
    report["qualifiers"].append(dict(
        mint=qualification.mint,mode=mode,qualified_at=qualification.observed_at,
        score=qualification.score,reasons=list(qualification.reasons),
        confirmations=list(qualification.confirmations),entry=entry,
        policy_hash=qualification.policy_hash,
    ))


def _record_attempt(report,signal,q,stage,extra=None):
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
    report["attempts"].append(row)
    report["attempts"]=report["attempts"][-1000:]


def main():
    report=dict(
        kind="pump_acceleration_natural_prospective",
        strategy_id=STRATEGY_ID,policy_hash=policy_hash(),
        frozen_policy=True,threshold_changes_allowed=False,threshold_changes_made=False,
        selection_uses_future_outcomes=False,outcomes_can_change_policy=False,
        order_authority=False,signing_authority=False,transaction_submission_authority=False,
        live_money_authority=False,shared_portfolio_mutation=False,
        discovery_source="finalized_public_pump_logs",
        evidence_source="alchemy_http_primary_no_rescue",
        curve_progress_definition="prospectively observed CreateEvent initial_real_token_reserves -> reserve depletion",
        velocity_window_seconds=30,extension_lookback_seconds=10,
        entry_budget_lamports=ENTRY_BUDGET,entry_fraction_bps=POLICY.entry_fraction_bps,
        discovery_seconds=DISCOVERY_SECONDS,followup_seconds=FOLLOWUP_SECONDS,
        started=int(time.time()),stream={},sessions=[],counts={},limitations=[],
        attempts=[],qualifiers=[],settled=[],open_positions=[],postgrad=[],
    )
    _save(report)

    tape=PumpTape()
    stop=threading.Event();ready=threading.Event()
    stream=PumpLogStream(primary_rpc_url(),tape,ws_url=discovery_ws_url())
    thread=threading.Thread(target=stream.run,args=(stop,ready),daemon=True)
    thread.start()
    if not ready.wait(15):
        report["limitations"].append("pump_stream_start_timeout")
        _save(report)
        raise SystemExit(1)

    sessions=Sessions()
    cursor=0;created={};postgrad={};active={};full_attempts=0
    last_eval={};last_postgrad_eval={};last_save=0
    discovery_end=int(time.time())+DISCOVERY_SECONDS
    end=discovery_end+FOLLOWUP_SECONDS

    try:
        while int(time.time())<end:
            now=int(time.time())
            fresh,cursor=tape.events_since(cursor)
            for event in fresh:
                creation=tape.creation(event["mint"])
                if creation is None:
                    continue
                state=created.setdefault(event["mint"],dict(
                    creation=creation,pregrad_wallets=set(),graduated=False))
                if len(state["pregrad_wallets"])<500 and event.get("wallet"):
                    state["pregrad_wallets"].add(event["wallet"])
                if int(event.get("real_token_reserves",-1))==0 and not state["graduated"]:
                    state["graduated"]=True
                    state["graduation_time"]=int(event["market_time"])
                    if len(postgrad)<MAX_POSTGRAD_CANDIDATES:
                        postgrad[event["mint"]]=dict(
                            mint=event["mint"],graduation_time=int(event["market_time"]),
                            pregrad_wallets=set(state["pregrad_wallets"]),pool=pumpswap_pool(event["mint"]),
                            signatures=set(),events={},history_complete=False,
                            history_capacity_loss=False,graduation_price=None,
                        )

            # New late-curve entries stop at discovery_end; follow-up never backfills
            # another pre-graduation decision.
            if now<discovery_end and tape.covered(now):
                for event in fresh:
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
                        sessions.ensure(25)
                        snapshot=sessions.pump.snapshot(mint,now,priority=True)
                        ev=tape.window(mint,int(snapshot["market_time"]),max_slot=snapshot["slot"])
                        pre_signal,trajectory=_late_signal(creation,ev,snapshot,0)
                        preq=qualify(pre_signal)
                        # concentration=0 is the optimistic preflight.  If even that
                        # cannot qualify, an expensive holder scan cannot rescue it.
                        if not preq.qualified:
                            _record_attempt(report,pre_signal,preq,"optimistic_preflight",
                                            {"trajectory":trajectory})
                            continue
                        if full_attempts>=MAX_FULL_ATTEMPTS:
                            report["limitations"].append("full_evidence_attempt_cap")
                            continue
                        full_attempts+=1
                        concentration,meta=sessions.reader.read(mint,snapshot,priority=True)
                        signal,trajectory=_late_signal(creation,ev,snapshot,concentration)
                        q=qualify(signal)
                        _record_attempt(report,signal,q,"full_point_in_time",
                                        {"concentration_source":meta.get("source"),
                                         "trajectory":trajectory})
                        if q.qualified and not any(
                                x["mint"]==mint and x["mode"]==MODE_LATE_CURVE
                                for x in report["qualifiers"]):
                            _open_position(report,active,q,snapshot,MODE_LATE_CURVE)
                    except (Unavailable,ValueError,KeyError,TypeError) as exc:
                        report["attempts"].append(dict(
                            mint=mint,mode=MODE_LATE_CURVE,observed_at=now,
                            stage="incomplete",qualified=False,
                            limitation=str(exc) or type(exc).__name__))

            # Natural post-graduation and second-leg entries may occur during the
            # follow-up because their decision time is necessarily after migration.
            for mint,state in list(postgrad.items()):
                age=now-int(state["graduation_time"])
                if age<5 or now-int(last_postgrad_eval.get(mint,0))<10:
                    continue
                if age>max(POLICY.max_postgrad_entry_age_s,600):
                    continue
                last_postgrad_eval[mint]=now
                try:
                    sessions.ensure(85)
                    graduation=sessions.postgrad.graduation_snapshot(mint,now,priority=True)
                    handoff=graduation_handoff(graduation,max(now,int(graduation["available_time"])))
                    snapshot=sessions.postgrad.pumpswap_snapshot(handoff,now,priority=True)
                    events=_refresh_pool_events(state,sessions,now)
                    if not state["history_complete"]:
                        raise Unavailable("incomplete_pumpswap_history")
                    concentration=_postgrad_concentration(sessions.rpc,snapshot)
                    signal=_volume_price_signal(state,snapshot,events,MODE_POSTGRAD,concentration)
                    q=qualify(signal)
                    _record_attempt(report,signal,q,"full_point_in_time")
                    if q.qualified and not any(
                            x["mint"]==mint and x["mode"]==MODE_POSTGRAD
                            for x in report["qualifiers"]):
                        _open_position(report,active,q,snapshot,MODE_POSTGRAD)

                    if age>=POLICY.min_second_leg_age_s:
                        try:
                            second=_volume_price_signal(
                                state,snapshot,events,MODE_SECOND_LEG,concentration)
                            q2=qualify(second)
                            _record_attempt(report,second,q2,"full_point_in_time")
                            if q2.qualified and not any(
                                    x["mint"]==mint and x["mode"]==MODE_SECOND_LEG
                                    for x in report["qualifiers"]):
                                _open_position(report,active,q2,snapshot,MODE_SECOND_LEG)
                        except (ValueError,KeyError,TypeError) as exc:
                            report["attempts"].append(dict(
                                mint=mint,mode=MODE_SECOND_LEG,observed_at=now,
                                stage="shape_incomplete",qualified=False,
                                limitation=str(exc) or type(exc).__name__))
                except (Unavailable,ValueError,KeyError,TypeError) as exc:
                    report["postgrad"].append(dict(
                        mint=mint,observed_at=now,age_seconds=age,
                        complete=False,limitation=str(exc) or type(exc).__name__))
                    report["postgrad"]=report["postgrad"][-300:]

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
                                current,_=_late_signal(
                                    creation,ev,snapshot,int(row.get("last_concentration",0)))
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
                        events=_refresh_pool_events(state,sessions,now)
                        quote=sell_quote(snapshot,life.position.tokens)
                        proceeds=max(0,quote.output_amount-GAS)
                        concentration=_postgrad_concentration(sessions.rpc,snapshot)
                        current=_volume_price_signal(
                            state,snapshot,events,MODE_POSTGRAD,concentration)
                        cq=qualify(current);demand_score=cq.score;confirmed=cq.qualified

                    mark=life.mark(proceeds,now,demand_score,confirmed)
                    age=now-int(row["opened"])
                    for horizon in (15,60,300,900):
                        if age>=horizon and str(horizon) not in row["marks"]:
                            row["marks"][str(horizon)]=dict(
                                observed_at=now,return_bps=mark["return_bps"],
                                proceeds=proceeds)
                    if mark["exit_reason"] is not None:
                        closed=life.settle(proceeds,now)
                        report["settled"].append(dict(
                            mint=mint,mode=mode,opened=row["opened"],closed=now,
                            exit_reason=closed["exit_reason"],
                            realized_quote_units=closed["realized_quote_units"],
                            marks=dict(row["marks"]),history=life.snapshot()["history"]))
                        active.pop(key,None)
                except (Unavailable,ValueError,KeyError,TypeError) as exc:
                    row.setdefault("monitor_failures",[]).append(dict(
                        observed_at=now,reason=str(exc) or type(exc).__name__))
                    row["monitor_failures"]=row["monitor_failures"][-20:]

            if now-last_save>=15:
                counts=Counter()
                for attempt in report["attempts"]:
                    counts[f'{attempt.get("mode")}:{attempt.get("stage")}']+=1
                    if attempt.get("qualified"):
                        counts[f'{attempt.get("mode")}:qualified']+=1
                report["counts"]=dict(counts)
                report["stream"]=tape.status(now)
                report["open_positions"]=[
                    dict(mint=k[0],mode=k[1],opened=v["opened"],
                         marks=dict(v["marks"]),snapshot=v["lifecycle"].snapshot())
                    for k,v in active.items()]
                _save(report);last_save=now
            time.sleep(1)
    finally:
        stop.set();thread.join(timeout=5)
        sessions.finish()
        report["sessions"]=sessions.history
        report["stream"]=tape.status(int(time.time()))
        report["ended"]=int(time.time())
        report["full_evidence_attempts"]=full_attempts
        report["created_mints_observed"]=len(created)
        report["postgrad_candidates"]=len(postgrad)
        report["open_positions"]=[
            dict(mint=k[0],mode=k[1],opened=v["opened"],
                 marks=dict(v["marks"]),snapshot=v["lifecycle"].snapshot())
            for k,v in active.items()]
        report["threshold_changes_made"]=False
        _save(report)
    print(json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
