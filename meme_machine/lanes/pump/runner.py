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

from meme_machine.runtime.request_scheduling import position_work
from meme_machine.runtime.execution_capacity import resize, turnover_capacity
from meme_machine.lanes.pump import pump
from meme_machine.lanes.pump.concentration import ConcentrationReader
from meme_machine.lanes.pump.engine import GAS
from meme_machine.lanes.pump.postgrad import (
    PostGraduationAdapter,buy_quote,graduation_handoff,pumpswap_pool,sell_quote,
)
from meme_machine.lanes.pump.provider import PumpAdapter,Unavailable
from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
from meme_machine.lanes.pump.pump_acceleration_evidence import (
    curve_progress_bps,early_holder_sell_share_bps,late_curve_trajectory,
    postgrad_volume_acceleration_bps,price_return_bps,
    reserve_price_parts,second_leg_shape,
)
from meme_machine.lanes.pump.solana_evidence_runtime import RuntimeEvidence,LocalPumpHistory,LocalPumpTape,LocalInterestRegistry,PUMP_SCOPE,SWAP_SCOPE
from meme_machine.lanes.pump.pipeline import Pipeline,censor_class
from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
from meme_machine.lanes.pump.pump_acceleration_strategy import (
    MODE_LATE_CURVE,MODE_POSTGRAD,MODE_SECOND_LEG,POLICY,STRATEGY_ID,
    SignalVector,entry_signal_persistence,flow_metrics,policy_hash,qualify,mode_max_hold_s,
)
from meme_machine.lanes.pump.solana_evidence_broker import (
    DEFAULT_BROKER_DB,EvidenceBroker,
)
from meme_machine.lanes.pump.solana_read_rpc import discovery_ws_url,new_rpc,primary_rpc_url
from meme_machine.lanes.pump.stream import PumpLogStream,PumpTape,WINDOW_SECONDS


REPORT=Path(os.environ.get("MM_PUMP_ACCELERATION_REPORT","pump-acceleration-natural-prospective.json"))
DISCOVERY_SECONDS=max(600,min(int(os.environ.get("MM_PUMP_ACCELERATION_DISCOVERY_SECONDS","3300")),3300))
FOLLOWUP_SECONDS=max(300,min(int(os.environ.get("MM_PUMP_ACCELERATION_FOLLOWUP_SECONDS","1000")),1200))
MAX_CREATED=5000
MAX_EXPENSIVE_POSTGRAD_PER_TURN=1
# Legacy thresholds expose pressure only; neither controls cheap retention.
MAX_POSTGRAD_CANDIDATES=12
MAX_FULL_ATTEMPTS=120
GENESIS_SOL_USD_MICROS=97_840_000
INITIAL_USD_MICROS=500_000_000
INITIAL_LAMPORTS=INITIAL_USD_MICROS*1_000_000_000//GENESIS_SOL_USD_MICROS
ENTRY_BUDGET=INITIAL_LAMPORTS*POLICY.entry_fraction_bps//10_000

def _current_pump_sizing():
    from meme_machine.runtime.directional_sleeve import open_sleeve
    sleeve=open_sleeve('pump',INITIAL_LAMPORTS)
    if sleeve is None:
        return dict(realized_equity=INITIAL_LAMPORTS,target=ENTRY_BUDGET,
                    allocatable_target=ENTRY_BUDGET,available=INITIAL_LAMPORTS)
    try:return sleeve.sizing_basis(POLICY.entry_fraction_bps)
    finally:sleeve.close()
ENTRY_DELAY_SECONDS=2
ENTRY_FILL_TIMEOUT_SECONDS=20
FROZEN_POLICY_HASH="89d2e6ac286e82f3d645feecc4de4193687cd9ba4e4f9006b7d57f1357c5b972"
FILL_PERSISTENCE_CONTEXT=None
ACCOUNTING=None
PIPELINE=None
CANDIDATE_HISTORY=None

def _progress(candidate,stage,reason=None,**details):
    if PIPELINE is not None:
        if stage in ("prospect_screened","rejected","evidence_not_required"):
            classification="strategy_rejection"
        elif stage=="prospect_incomplete":
            # No full-evidence request has been authorized at this point. Keep
            # the missing prospect signal visible without inventing an admitted
            # reconstruction failure or a successful strategy rejection.
            classification="pre_admission_evidence_incomplete"
        elif reason=="postgrad_entry_horizon_expired":
            # Normal candidate retirement is not an acquisition failure. Earlier
            # incomplete attempts remain append-only and retain their own class.
            classification="superseded_candidate_state"
        elif (details.get("mode")==MODE_SECOND_LEG
              and (details.get("history") or {}).get("complete") is True
              and reason in ("insufficient_second_leg_history",
                             "missing_preconsolidation_peak","missing_pullback",
                             "missing_consolidation")):
            # An authenticated complete history can simply have no required
            # second-leg shape; collecting more old transactions cannot rescue it.
            classification="strategy_rejection"
        else:
            classification=censor_class(reason) if reason else None
        PIPELINE.record(candidate,stage,reason,classification,**details)


def _save(report):
    if PIPELINE is not None:report["opportunity_coverage"]=PIPELINE.snapshot()
    if ACCOUNTING is not None:
        report["accounting"]=ACCOUNTING.reconcile()
        report["accounting_replay"]=ACCOUNTING.replay()
    from meme_machine.lanes.pump.durable_publication import publish_report
    report['publication']=publish_report(REPORT,report,asynchronous=bool(os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB')))


class Sessions:
    def __init__(self):
        self.pacer=None;self.history=[];self.plane=None
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

    def prepare_reserved(self,row):
        from meme_machine.lanes.pump.pump_evidence_execution import prepare_reserved
        return prepare_reserved(self,row,new_rpc=new_rpc)

    def execution_interest(self,snapshot,*,owner=None,lifecycle='candidate'):
        from meme_machine.lanes.pump.pump_evidence_execution import execution_addresses
        if self.plane is None:raise Unavailable('execution_evidence_plane_required')
        scope=SWAP_SCOPE if snapshot.get('surface')=='pumpswap' else PUMP_SCOPE
        addresses=execution_addresses(snapshot,self)
        self.plane.interest(scope,lower_slot=snapshot['slot'],addresses=addresses,
            lifecycle=lifecycle,priority=1 if lifecycle=='reserved' else 3,
            owner=owner or 'pump:candidate:'+snapshot['mint'])
        return dict(scope=scope,addresses=addresses,mint=snapshot['mint'])

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


def _late_roundtrip_loss_bps(snapshot, budget=ENTRY_BUDGET):
    """Immediate executable after-cost downside for the exact paper entry size."""
    curve=pump.curve(snapshot["accounts"][0])
    supply,_=pump.mint_info(snapshot["accounts"][1])
    entry_rates=pump.fees(snapshot["accounts"][2],curve,supply)
    tokens,cost,entry_fee=pump.buy(curve,budget,entry_rates)
    gross=max(0,int(cost)-int(entry_fee))
    after=pump.Curve(
        token=int(curve.token)-int(tokens),
        sol=int(curve.sol)+gross,
        real_token=int(curve.real_token)-int(tokens),
        real_sol=int(curve.real_sol)+gross,
        supply=int(curve.supply),
        complete=False,
        creator=curve.creator,
    )
    exit_rates=pump.fees(snapshot["accounts"][2],after,supply)
    proceeds,_=pump.sell(after,tokens,exit_rates)
    basis=int(cost)+GAS
    executable=max(0,int(proceeds)-GAS)
    return max(0,(basis-executable)*10_000//max(1,basis))



def _capacity(snapshot, turnover, intended=None):
    # Qualification tests the strategy's ordinary target. Available funding is
    # consulted only at reservation; a committed sleeve cannot erase downside
    # evidence. Fill/scaling callers pass their actual execution budget explicitly.
    if intended is None:intended=_current_pump_sizing()["target"]
    cap=turnover_capacity(turnover,authenticated=turnover is not None)
    def loss(n):
        try:
            if isinstance(snapshot.get("accounts"),(list,tuple)):
                return _late_roundtrip_loss_bps(snapshot,n)
            buy=buy_quote(snapshot,n)
            proceeds=sell_quote(snapshot,buy.output_amount).output_amount
            basis=buy.input_amount+GAS
            return max(0,(basis-max(0,proceeds-GAS))*10000//basis)
        except (ValueError,Unavailable,ZeroDivisionError):
            return None
    answer=resize(min(intended,cap),1,loss,ordinary_limit=POLICY.max_immediate_roundtrip_loss_bps)
    execution_capacity=resize(intended,1,loss,ordinary_limit=POLICY.max_immediate_roundtrip_loss_bps)
    telemetry=answer.telemetry()
    telemetry.update(decision_size=intended,capital_cap=intended,turnover_cap=cap,
        liquidity_execution_cap=execution_capacity.final_size,
        binding_cap=answer.binding_reason if answer.final_size<min(intended,cap)
            else "turnover" if cap<intended else "capital")
    return answer,telemetry


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
        buyer_growth=flow["buyer_growth"],
        repeat_buyer_clusters=flow["repeat_buyer_clusters"],
        repeat_buy_share_bps=flow["repeat_buy_share_bps"],
        net_buy_share_bps=flow["net_buy_share_bps"],
        concentration_bps=int(concentration_bps),
        extension_bps=int(trajectory["extension_bps"]),
        authenticated_recent_turnover=flow["gross_buy"]+flow["gross_sell"],
        immediate_roundtrip_loss_bps=_capacity(snapshot,flow["gross_buy"]+flow["gross_sell"])[0].ordinary_loss_bps,
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
        buyer_growth=flow["buyer_growth"],repeat_buyer_clusters=flow["repeat_buyer_clusters"],repeat_buy_share_bps=flow["repeat_buy_share_bps"],net_buy_share_bps=flow["net_buy_share_bps"],
        concentration_bps=0,
        extension_bps=int(trajectory["extension_bps"]),
        skilled_wallet_clusters=int(confirmation["skilled_wallet_clusters"]),
        creator_quality_bps=confirmation["creator_quality_bps"],
        creator_history_launches=int(confirmation["creator_history_launches"]),
        quote_relative_return_bps=int(trajectory["quote_relative_return_bps"]),
    ),trajectory,confirmation



def _late_stream_prospect(signal):
    """Admit only on evidence available in the finalized stream.

    The missing executable-downside field is a known full-evidence dependency,
    not a zero-cost assumption. Final qualification remains fail-closed until the
    authoritative RPC snapshot supplies that evidence.
    """
    decision=qualify(signal)
    reasons=tuple(
        reason for reason in decision.reasons
        if reason!="executable_downside_unavailable"
    )
    return decision,reasons

def _postgrad_concentration_required(*decisions):
    """Holder concentration can only turn an optimistic pass into a rejection."""
    return any(row is not None and bool(row.qualified) for row in decisions)


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
    history=state["history"]
    events=history.refresh(
        None,now,research=research,hydration_kind=hydration_kind)
    state["history_status"]=history.status(now)
    if CANDIDATE_HISTORY is not None:
        mint=str(state["mint"])
        CANDIDATE_HISTORY.observe(
            'pump',mint,surface='pumpswap',
            observed_at=int(state["graduation_time"]),
            decision_deadline=int(state["graduation_time"])+
                max(POLICY.max_postgrad_entry_age_s,600),
            metadata=dict(pool=state["pool"],source='pump_graduation'))
        records=getattr(history,'candidate_history_rows',None)
        if records is None or len(records)!=len(events):
            raise Unavailable('candidate_history_canonical_record_missing')
        for record,order in records:
            CANDIDATE_HISTORY.retain_pumpswap_record(mint,record,order)
    return events


def _retain_pump_source_history(rows):
    """Persist normalized Pump economics before any Current->PumpSwap promotion."""
    if CANDIDATE_HISTORY is None:return 0
    return CANDIDATE_HISTORY.retain_pump_source_history(
        rows,graduation_horizon=max(POLICY.max_postgrad_entry_age_s,600))


def _restore_observed_pump_candidates(created,postgrad,pumpswap_stream,plane,confirmations,now):
    """Rebuild cheap observation state from the shared ordered history after restart."""
    if CANDIDATE_HISTORY is None:return 0
    restored=0
    for candidate in CANDIDATE_HISTORY.candidates(lane='pump'):
        mint=candidate['candidate']
        if mint in created:continue
        economic=[
            row for row in CANDIDATE_HISTORY.events('pump',mint)
            if str(row.get('kind','')).startswith('pump_')
            and not str(row.get('kind','')).startswith('pumpswap_')
        ]
        if not economic:continue
        events=[dict(row['payload']) for row in economic]
        creation=next((row for row in events if row.get('event_type')=='create'),None)
        if creation is None:continue
        confirmations.observe_creation(creation)
        graduation_rows=[
            row for row in events
            if row.get('event_type')=='migration'
            or (row.get('event_type')=='trade'
                and int(row.get('real_token_reserves',-1))==0)
        ]
        graduation_time=(None if not graduation_rows else
            min(int(row['market_time']) for row in graduation_rows))
        pregrad_wallets=set()
        for row in events:
            if (row.get('wallet')
                    and (graduation_time is None or int(row.get('market_time',0))<=graduation_time)
                    and len(pregrad_wallets)<500):
                pregrad_wallets.add(row['wallet'])
        state=dict(creation=creation,pregrad_wallets=pregrad_wallets,
                   graduated=graduation_time is not None)
        if graduation_time is not None:
            state['graduation_time']=graduation_time
            confirmations.observe_graduation(mint,graduation_time)
        created[mint]=state;restored+=1
        if (graduation_time is None
                or int(now)-graduation_time>max(POLICY.max_postgrad_entry_age_s,600)
                or mint in postgrad):
            continue
        migration=next((row for row in graduation_rows if row.get('event_type')=='migration'),None)
        pool=str((migration or {}).get('pool') or pumpswap_pool(mint))
        pumpswap_stream.add_address(pool)
        postgrad[mint]=dict(
            mint=mint,creation=creation,graduation_time=graduation_time,
            pregrad_wallets=set(pregrad_wallets),pool=pool,
            history=LocalPumpHistory(plane,pool,graduation_time),
            history_status={},graduation_price=None)
    return restored


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
        authenticated_recent_turnover=flow["gross_buy"]+flow["gross_sell"],
        buyer_growth=flow["buyer_growth"],
        repeat_buyer_clusters=flow["repeat_buyer_clusters"],
        repeat_buy_share_bps=flow["repeat_buy_share_bps"],
        net_buy_share_bps=flow["net_buy_share_bps"],
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


def _reserve_position(
    report,pending,active,signal,qualification,snapshot,mode,concentration=0,
    *,decision_id=None
):
    key=(qualification.mint,mode)
    if key in pending or key in active:
        return False
    if any(x["mint"]==qualification.mint and x["mode"]==mode for x in report["qualifiers"]):
        return False
    # Qualification is already final and durable at this point.  Capital is an
    # execution admission input only; it must never change the qualification.
    reserved_at=max(int(snapshot["available_time"]),int(time.time()))
    sizing=_current_pump_sizing()
    intended=min(sizing['target'],max(0,sizing['available']-GAS))
    if intended<=0:
        # Strategy qualification already completed. Funding is a later execution
        # decision and may not erase the opportunity or suppress Survivor.
        unfunded=dict(
            mint=qualification.mint,mode=mode,qualified_at=qualification.observed_at,
            policy_hash=qualification.policy_hash,
            entry_status='qualified_but_capital_unavailable',
            funding_reason='directional_realized_equity_unavailable',
            sizing=dict(sizing),
        )
        report.setdefault('qualified_unfunded',[]).append(unfunded)
        _progress(qualification.mint,'qualified_but_capital_unavailable',
                  'directional_realized_equity_unavailable',
                  mode=mode,qualified_at=qualification.observed_at,
                  economic_rejection=False)
        reason='directional_realized_equity_unavailable'
        denial=dict(
            mint=qualification.mint,mode=mode,qualified_at=qualification.observed_at,
            decision_id=decision_id,status='denied',reason=reason,
            at=reserved_at,sizing=sizing,economic_rejection=False)
        report.setdefault('funding_denials',[]).append(denial)
        if CANDIDATE_HISTORY is not None and decision_id is not None:
            CANDIDATE_HISTORY.record_funding(
                decision_id,'pump',qualification.mint,status='denied',
                at=reserved_at,reason=reason,details=sizing)
        _progress(qualification.mint,'funding_denied',reason,mode=mode,
                  decision_id=decision_id,qualification_preserved=True)
        return False

    import uuid
    lifecycle_id=(ACCOUNTING.identity["run_id"] if ACCOUNTING else "research")+":"+uuid.uuid4().hex
    from meme_machine.runtime.lifecycle_identity import issue
    lifecycle_id=issue(lifecycle_id)
    from dataclasses import asdict,is_dataclass
    context=FILL_PERSISTENCE_CONTEXT or {}
    states=context.get('postgrad',{}) if mode!=MODE_LATE_CURVE else context.get('created',{})
    native_state=states.get(qualification.mint,{})
    execution=native_state.get('execution_context')
    confirmations=context.get('confirmations')
    recovery=dict(mode=mode,concentration=int(concentration),
        confirmation_state=(dict(creator_launches=confirmations.creator_launches,mint_creator=confirmations.mint_creator) if confirmations is not None else None),
        signal=asdict(signal) if is_dataclass(signal) else dict(vars(signal)),
        state={k:sorted(v) if isinstance(v,set) else v for k,v in native_state.items()
               if k not in ('history','history_status')},execution=execution)
    evidence=dict(snapshot,_runtime_recovery=recovery)
    interest_acquired=False
    if context.get('plane') is not None:
        if execution is None:raise Unavailable('reservation_execution_interest_missing')
        context['plane'].interest(execution['scope'],lower_slot=int(snapshot['slot']),
            addresses=execution['addresses'],owner=lifecycle_id,lifecycle='reserved',priority=1)
        interest_acquired=True
    life=PumpAccelerationPaperLifecycle(book=ACCOUNTING,lifecycle_id=lifecycle_id,
                                       entry_evidence=evidence)
    try:
        life.reserve(qualification,intended+GAS,reserved_at)
    except ValueError as exc:
        reason=str(exc)
        if reason not in ('sleeve_capital_exhausted','paper_capital_exhausted'):
            raise
        denial=dict(
            mint=qualification.mint,mode=mode,qualified_at=qualification.observed_at,
            decision_id=decision_id,status='denied',reason=reason,
            at=reserved_at,sizing=sizing,economic_rejection=False)
        report.setdefault('funding_denials',[]).append(denial)
        if CANDIDATE_HISTORY is not None and decision_id is not None:
            CANDIDATE_HISTORY.record_funding(
                decision_id,'pump',qualification.mint,status='denied',
                at=reserved_at,reason=reason,details=sizing)
        if getattr(life,'sleeve',None) is not None:
            life.sleeve.close();life.sleeve=None
        if interest_acquired:
            try:context['plane'].command(
                op='release',owner=lifecycle_id,scope=execution['scope'],resolved=False)
            except Exception:pass
        unfunded=dict(
            mint=qualification.mint,mode=mode,qualified_at=qualification.observed_at,
            policy_hash=qualification.policy_hash,
            entry_status='qualified_but_capital_unavailable',
            funding_reason='sleeve_capital_exhausted',
            sizing=dict(sizing),
        )
        report.setdefault('qualified_unfunded',[]).append(unfunded)
        _progress(qualification.mint,'qualified_but_capital_unavailable',
                  'sleeve_capital_exhausted',mode=mode,
                  qualified_at=qualification.observed_at,economic_rejection=False)
        _progress(qualification.mint,'funding_denied',reason,mode=mode,
                  decision_id=decision_id,qualification_preserved=True)
        return False

    if CANDIDATE_HISTORY is not None and decision_id is not None:
        CANDIDATE_HISTORY.record_funding(
            decision_id,'pump',qualification.mint,status='funded',
            at=reserved_at,details=dict(lifecycle_id=lifecycle_id,
                intended=intended,gas=GAS,sizing=sizing))
    _progress(qualification.mint,"entry_reserved",lifecycle_id=lifecycle_id)
    qrow=dict(
        lifecycle_id=lifecycle_id,decision_id=decision_id,
        mint=qualification.mint,mode=mode,qualified_at=qualification.observed_at,
        score=qualification.score,reasons=list(qualification.reasons),
        confirmations=list(qualification.confirmations),
        policy_hash=qualification.policy_hash,
        entry_status="reserved",reserved_at=reserved_at,
        decision_evidence_available_at=int(snapshot["available_time"]),
        fill_due=reserved_at+ENTRY_DELAY_SECONDS,
        decision_slot=int(snapshot["slot"]),
        decision_repeat_buyer_clusters=int(signal.repeat_buyer_clusters),
        decision_repeat_buy_share_bps=int(signal.repeat_buy_share_bps),
    )
    report["qualifiers"].append(qrow)
    pending[key]=dict(
        lifecycle=life,reserved_at=reserved_at,due=reserved_at+ENTRY_DELAY_SECONDS,
        decision_slot=int(snapshot["slot"]),qualifier_row=qrow,
        last_concentration=int(concentration),decision_signal=signal,execution_context=execution,
    )
    return True


@position_work
def _fill_pending(
    report,pending,active,sessions,postgrad,now,*,
    tape=None,created=None,confirmations=None
):
    context=FILL_PERSISTENCE_CONTEXT or {}
    tape=tape if tape is not None else context.get("tape")
    created=created if created is not None else context.get("created")
    confirmations=(
        confirmations if confirmations is not None
        else context.get("confirmations")
    )
    base_sessions=sessions
    for key,row in list(pending.items()):
        sessions=base_sessions
        if now<int(row["due"]):
            continue
        mint,mode=key
        life=row["lifecycle"]
        try:
            _assert_fill_deadline(row)
            if hasattr(sessions,"prepare_reserved"):
                sessions=sessions.prepare_reserved(row)
            sessions.ensure(20)
            if mode==MODE_LATE_CURVE:
                sessions.ensure(35)
                snapshot=sessions.pump.snapshot(mint,now,priority=True)
                _assert_fill_deadline(row)
                curve=pump.curve(snapshot["accounts"][0])
                if curve.complete or curve.real_token==0:
                    raise ValueError("graduated_before_delayed_fill")
                if int(snapshot["slot"])<=int(row["decision_slot"]) or int(snapshot["market_time"])<int(row["due"]):
                    raise Unavailable("no_fresh_post_delay_quote")

                if tape is None or created is None or confirmations is None:
                    raise Unavailable("entry_persistence_context_unavailable")
                creation=created[mint]["creation"]
                ev=tape.window(
                    mint,int(snapshot["market_time"]),max_slot=snapshot["slot"]
                )
                concentration,meta=sessions.reader.read(
                    mint,snapshot,priority=True
                )
                fill_signal,trajectory,confirmation=_late_signal(
                    creation,ev,snapshot,concentration,confirmations
                )
                persistence=entry_signal_persistence(
                    row["decision_signal"],fill_signal
                )
                row["qualifier_row"]["fill_persistence"]=dict(
                    persistence,
                    reasons=list(persistence["reasons"]),
                    fill_trajectory=trajectory,
                    concentration_source=meta.get("source"),
                    confirmation_evidence=_confirmation_meta(confirmation),
                )
                if not persistence["persistent"]:
                    raise ValueError(
                        "entry_signal_decay:"+",".join(persistence["reasons"])
                    )
                row["last_concentration"]=int(concentration)
                _assert_fill_deadline(row)

                supply,_=pump.mint_info(snapshot["accounts"][1])
                rates=pump.fees(snapshot["accounts"][2],curve,supply)
                capacity,capacity_telemetry=_capacity(snapshot,fill_signal.authenticated_recent_turnover,life.reservation["budget_quote_units"]-GAS)
                if capacity.final_size<=0:raise ValueError("entry_capacity_unavailable")
                tokens,cost,fee=pump.buy(curve,capacity.final_size,rates)
                surface="pump.fun"
                entry=dict(tokens=tokens,cost=cost,fee=fee,gas=GAS)
            else:
                state=postgrad.get(mint)
                if state is None:
                    raise Unavailable("missing_postgrad_state")
                if confirmations is None:
                    raise Unavailable("entry_persistence_context_unavailable")
                sessions.ensure(85)
                graduation=sessions.postgrad.graduation_snapshot(mint,now,priority=True)
                handoff=graduation_handoff(
                    graduation,max(now,int(graduation["available_time"])))
                snapshot=sessions.postgrad.pumpswap_snapshot(handoff,now,priority=True)
                _assert_fill_deadline(row)
                if int(snapshot["slot"])<=int(row["decision_slot"]) or int(snapshot["market_time"])<int(row["due"]):
                    raise Unavailable("no_fresh_post_delay_quote")

                state["history"].bind_snapshot(snapshot)
                events=_refresh_pool_events(
                    state,sessions,now,
                    research=(mode==MODE_SECOND_LEG),
                    hydration_kind="entry_persistence",
                )
                if mode==MODE_POSTGRAD:
                    window_status=state["history"].decision_window_status(now,30)
                    if not window_status["complete"]:
                        raise Unavailable("incomplete_pumpswap_entry_window")
                    fill_events=state["history"].decision_rows(now,30)
                else:
                    if not state["history"].complete(now):
                        raise Unavailable("incomplete_pumpswap_entry_history")
                    fill_events=events
                concentration=_postgrad_concentration(sessions.rpc,snapshot)
                fill_signal,confirmation=_volume_price_signal(
                    state,snapshot,fill_events,mode,concentration,confirmations
                )
                persistence=entry_signal_persistence(
                    row["decision_signal"],fill_signal
                )
                row["qualifier_row"]["fill_persistence"]=dict(
                    persistence,
                    reasons=list(persistence["reasons"]),
                    history_status=state["history"].status(now),
                    confirmation_evidence=_confirmation_meta(confirmation),
                )
                if not persistence["persistent"]:
                    raise ValueError(
                        "entry_signal_decay:"+",".join(persistence["reasons"])
                    )
                row["last_concentration"]=int(concentration)
                _assert_fill_deadline(row)

                capacity,capacity_telemetry=_capacity(snapshot,fill_signal.authenticated_recent_turnover,life.reservation["budget_quote_units"]-GAS)
                if capacity.final_size<=0:raise ValueError("entry_capacity_unavailable")
                quote=buy_quote(snapshot,capacity.final_size)
                tokens=quote.output_amount;cost=quote.input_amount;surface="pumpswap"
                entry=dict(tokens=tokens,cost=cost,fee=quote.fee_amount,gas=GAS)

            row["qualifier_row"]["execution_capacity"]=capacity_telemetry
            entry["execution_capacity"]=capacity_telemetry
            basis=cost+GAS
            if life.book is not None:life.book.checkpoint_runtime(life.lifecycle_id,'fill_context',dict(entry=entry,concentration=int(row.get('last_concentration',0)),reserved_fill_latency=dict(row.get('reserved_fill_latency',{}),total_seconds=int(snapshot['available_time'])-row['reserved_at'])))
            life.fill(tokens,basis,int(snapshot["available_time"]),surface,
                      evidence=dict(snapshot=snapshot,entry=entry))
            if getattr(base_sessions,'plane',None) is not None:
                execution=row['execution_context']
                base_sessions.plane.interest(execution['scope'],lower_slot=row['decision_slot'],addresses=execution['addresses'],owner=life.lifecycle_id,lifecycle='open',priority=0)
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
            row['qualifier_row']['reserved_fill_latency']=dict(row.get('reserved_fill_latency',{}),total_seconds=int(snapshot['available_time'])-row['reserved_at'])
            if getattr(base_sessions,'plane',None) is not None:base_sessions.plane.count('pump.reserved_fills')
            pending.pop(key,None)
        except (Unavailable,ValueError,KeyError,TypeError) as exc:
            reason=str(exc) or type(exc).__name__
            decision_now=int(time.time())
            if (reason in ("graduated_before_delayed_fill","entry_fill_timeout") or
                    reason.startswith("entry_signal_decay:") or
                    decision_now-int(row["reserved_at"])>=ENTRY_FILL_TIMEOUT_SECONDS):
                try:
                    life.cancel(reason,decision_now)
                    _progress(mint,"entry_cancelled",reason,lifecycle_id=getattr(life,"lifecycle_id",None))
                except ValueError:
                    pass
                row["qualifier_row"].update(
                    entry_status="cancelled",cancelled_at=decision_now,entry_limitation=reason)
                plane=getattr(base_sessions,'plane',None)
                if plane is not None:
                    cause='missing_current_state' if row.get('refresh_failed') or 'refresh' in row.get('qualifier_row',{}).get('last_fill_limitation','') else 'finalized_coverage_or_thesis'
                    row['qualifier_row']['timeout_cause']=cause
                    plane.count('pump.entry_cancelled.'+cause)
                    if row.get('execution_context'):plane.command(op='release',owner=life.lifecycle_id,scope=row['execution_context']['scope'],resolved=True)
                pending.pop(key,None)
            else:
                row["qualifier_row"]["last_fill_limitation"]=reason

def _service_pending_entries(report,pending,active,sessions,postgrad,*,monitor):
    """Give reserved entries lifecycle authority before more research can block.

    Stream threads continue broad finalized observation. Pending entries keep their
    original delay and timeout; a too-early finalized quote schedules another
    position check, not a long synchronous candidate/history evaluation.
    """
    while pending:
        monitor()
        _fill_pending(report,pending,active,sessions,postgrad,int(time.time()))
        if pending:_stop_sleep(1)

def _record_attempt(report,signal,q,stage,extra=None,*,snapshot=None):
    plane=(FILL_PERSISTENCE_CONTEXT or {}).get('plane')
    if stage=='full_point_in_time' and plane is not None:plane.count('pump.decisions_fully_local')
    if stage=="full_point_in_time":
        _progress(signal.mint,"evidence_complete",mode=signal.phase,
                  decision_at=signal.observed_at)
    elif stage=="optimistic_preflight" and not q.qualified:
        _progress(signal.mint,"evidence_not_required",mode=signal.phase,
                  decision_at=signal.observed_at,
                  reasons=list(q.reasons),remaining_evidence="concentration")
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
        buyer_growth=signal.buyer_growth,
        repeat_buyer_clusters=signal.repeat_buyer_clusters,
        repeat_buy_share_bps=signal.repeat_buy_share_bps,
        net_buy_share_bps=signal.net_buy_share_bps,
        concentration_bps=signal.concentration_bps,
        extension_bps=signal.extension_bps,
        immediate_roundtrip_loss_bps=signal.immediate_roundtrip_loss_bps,
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
    from dataclasses import asdict
    if CANDIDATE_HISTORY is not None:
        row['decision_id']=CANDIDATE_HISTORY.record_decision(
            'pump',signal.mint,mode=signal.phase,
            observed_at=int(signal.observed_at),qualified=bool(q.qualified),
            decision=dict(vector=asdict(signal),qualification=asdict(q),
                          policy_hash=policy_hash(),stage=stage))
    from meme_machine.runtime.directional_sleeve import open_sleeve
    sleeve=open_sleeve('pump',INITIAL_LAMPORTS)
    if sleeve is not None:
        try:
            from meme_machine.runtime.opportunity_telemetry import pump_context
            context=pump_context(signal,snapshot,stage)
            from meme_machine.runtime.journal import digest as receipt_digest
            decision_id=signal.mint+':'+signal.phase+':'+stage+':'+str(signal.observed_at)+':'+receipt_digest([context,asdict(signal),asdict(q)])
            sleeve.opportunity(signal.mint,identity=decision_id,
                regime='current',status='qualified' if q.qualified else 'rejected',
                at=int(signal.observed_at),decision=dict(vector=asdict(signal),qualification=asdict(q),
                    policy=asdict(POLICY),context=context))
        except Exception as error:
            row['opportunity_error']='receipt_capture_failed:'+type(error).__name__
            print('opportunity publication failed:',type(error).__name__,flush=True)
        finally:sleeve.close()

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
    return row


@position_work
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
            demand_score=0;confirmed=False;current=None;cq=None
            continuation_due=(now-position.opened_at>=mode_max_hold_s(position.mode)*(1+position.hold_extensions_used)
                or (position.first_tail_crossed_at is not None and now-position.first_tail_crossed_at>=900))
            if position.surface=="pump.fun":
                snapshot=sessions.pump.snapshot(mint,now,priority=True)
                curve=pump.curve(snapshot["accounts"][0])
                if curve.complete or curve.real_token==0:
                    graduation=sessions.postgrad.graduation_snapshot(mint,now,priority=True)
                    handoff=graduation_handoff(graduation,max(now,int(graduation["available_time"])))
                    native=postgrad.get(mint)
                    if native is None:
                        prior=created[mint]
                        native=dict(mint=mint,creation=prior['creation'],pregrad_wallets=set(prior['pregrad_wallets']),
                            pool=pumpswap_pool(mint),graduation_time=int(graduation['market_time']),graduation_price=None)
                        native['history']=LocalPumpHistory(sessions.plane,native['pool'],native['graduation_time'])
                        postgrad[mint]=native
                    if life.book is not None:
                        life.book.checkpoint_runtime(life.lifecycle_id,'postgrad_context',
                            {k:sorted(v) if isinstance(v,set) else v for k,v in native.items() if k not in ('history','history_status')})
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
                        if continuation_due:
                            concentration,_=sessions.reader.read(mint,snapshot,priority=True)
                            current,_trajectory,_confirmation=_late_signal(creation,ev,snapshot,concentration,confirmations)
                        cq=qualify(current);demand_score=cq.score
                    except Exception:
                        demand_score=0
            else:
                state=postgrad.get(mint)
                if state is None:
                    raise Unavailable("missing_postgrad_state")
                graduation=sessions.postgrad.graduation_snapshot(mint,now,priority=True)
                handoff=graduation_handoff(graduation,max(now,int(graduation["available_time"])))
                snapshot=sessions.postgrad.pumpswap_snapshot(handoff,now,priority=True)
                state["history"].bind_snapshot(snapshot)
                events=_refresh_pool_events(
                    state,sessions,now,research=False,
                    hydration_kind="position_monitor")
                quote=sell_quote(snapshot,life.position.tokens)
                proceeds=max(0,quote.output_amount-GAS)
                concentration=_postgrad_concentration(sessions.rpc,snapshot)
                current,_confirmation=_volume_price_signal(
                    state,snapshot,events,MODE_POSTGRAD,concentration,confirmations)
                cq=qualify(current);demand_score=cq.score;confirmed=cq.qualified

            facts=_pump_continuation_facts(life,current,cq,snapshot,proceeds,now)
            mark_evidence=dict(snapshot=snapshot,net_proceeds=proceeds,
                               network_cost=GAS,continuation=facts)
            mark=life.mark(proceeds,now,demand_score,confirmed,evidence=mark_evidence)
            if mark.get("partial_harvest_bps"):
                tokens_before=int(life.position.tokens)
                if tokens_before>1:
                    harvest_tokens=max(
                        1,tokens_before*int(mark["partial_harvest_bps"])//10_000)
                    harvest_tokens=min(tokens_before-1,harvest_tokens)
                    if life.position.surface=="pump.fun":
                        curve=pump.curve(snapshot["accounts"][0])
                        supply,_=pump.mint_info(snapshot["accounts"][1])
                        rates=pump.fees(snapshot["accounts"][2],curve,supply)
                        partial_raw,_=pump.sell(curve,harvest_tokens,rates)
                        harvest_proceeds=max(0,partial_raw-GAS)
                    else:
                        partial_quote=sell_quote(snapshot,harvest_tokens)
                        harvest_proceeds=max(0,partial_quote.output_amount-GAS)
                    harvest_evidence=dict(
                        snapshot=snapshot,tokens_sold=harvest_tokens,
                        net_proceeds=harvest_proceeds,network_cost=GAS)
                    harvest=life.harvest(
                        harvest_tokens,harvest_proceeds,now,
                        evidence=harvest_evidence)
                    report.setdefault("harvests",[]).append(dict(
                        lifecycle_id=life.lifecycle_id,mint=mint,mode=mode,
                        opened=row["opened"],observed_at=now,
                        return_bps=mark["return_bps"],**harvest))
            if mark['exit_reason'] is None and not mark.get('partial_harvest_bps'):
                _scale_current(life,row,current,cq,snapshot,facts,now)
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
                if getattr(sessions,'plane',None) is not None:
                    for scope in (PUMP_SCOPE,SWAP_SCOPE):sessions.plane.command(op='release',owner=life.lifecycle_id,scope=scope,resolved=True)
                active.pop(key,None)
        except (Unavailable,ValueError,KeyError,TypeError) as exc:
            row.setdefault("monitor_failures",[]).append(dict(
                observed_at=now,reason=str(exc) or type(exc).__name__))
            row["monitor_failures"]=row["monitor_failures"][-20:]



def _pump_continuation_facts(life,current,qualification,snapshot,proceeds,now):
    p=life.position
    valid=current is not None and qualification is not None
    basis=p.basis_quote_units
    fresh=0<=now-int(snapshot['available_time'])<=5
    return dict(current_after_cost_return_positive=proceeds>basis,
        after_cost_return_bps=(proceeds-basis)*10000//basis,
        fresh_generation_state=fresh,fresh_executable_exit_quote=fresh,
        canonical_lineage_and_venue=bool(snapshot.get('mint')==p.mint),
        creator_distribution_safe=valid and current.creator_quality_bps is not None and current.creator_quality_bps>=0,
        hard_concentration_safe=valid and current.concentration_bps<=(POLICY.max_concentration_bps if p.surface=="pump.fun" else POLICY.max_postgrad_concentration_bps),
        executable_exit_liquidity=proceeds>0,
        no_persistent_confirmed_demand_failure=valid and p.demand_deterioration_streak<POLICY.demand_exit_confirmations,
        no_irreversible_exit_intent=p.exit_reason is None,
        fresh_strategy_requalified=valid and qualification.qualified)


def _scale_current(life,row,current,qualification,snapshot,facts,now):
    from meme_machine.runtime.directional_continuation import scale_budget,native_sync
    from meme_machine.runtime.execution_capacity import breadth_retained
    p=life.position
    if (life.sleeve is None or p.scale_committed or not p.partial_harvest_taken
            or p.first_tail_crossed_at is None or now-p.first_tail_crossed_at<900
            or p.exit_reason or qualification is None or not qualification.qualified):return None
    if not breadth_retained(life.entry_evidence.get('_runtime_recovery',{}).get('signal',{}).get('independent_buyer_clusters',0),
            current.independent_buyer_clusters,5000):return None
    target=min(life.sleeve.sizing_basis(250)['allocatable_target'],p.original_basis//2)
    if target<=GAS:return None
    capacity,telemetry=_capacity(snapshot,current.authenticated_recent_turnover,target-GAS)
    state=dict(opened_at=p.opened_at,realization_taken=p.partial_harvest_taken,high_water_bps=p.peak_return_bps,
        first_tail_crossed_at=p.first_tail_crossed_at,original_basis=p.original_basis,
        scale_committed=p.scale_committed,pending_exit=p.exit_reason)
    amount=scale_budget(state,dict(facts,fresh_execution_requalified=capacity.final_size>0),
        now=now,sleeve=life.sleeve,execution_allowance=capacity.final_size+GAS)
    if amount<=GAS:return None
    if p.surface=='pump.fun':
        curve=pump.curve(snapshot['accounts'][0]);supply,_=pump.mint_info(snapshot['accounts'][1])
        rates=pump.fees(snapshot['accounts'][2],curve,supply)
        quantity,cost,fee=pump.buy(curve,amount-GAS,rates)
    else:
        quote=buy_quote(snapshot,amount-GAS);quantity,cost,fee=quote.output_amount,quote.input_amount,quote.fee_amount
    cost+=GAS;request=life.lifecycle_id+':scale:1'
    if cost>amount:raise ValueError('scale_execution_overdraw')
    life.sleeve.reserve_scale(life.lifecycle_id,amount=cost,original_basis=p.original_basis,at=now,request=request)
    try:
        with life.sleeve.scale_fence(life.lifecycle_id,request):
            if not 0<=int(time.time())-int(snapshot['available_time'])<=5:raise ValueError('scale_stale_quote')
            life.add(cost,quantity,now,request=request,evidence=dict(snapshot=snapshot,network_cost=GAS,fee=fee,
                qualification=qualification.__dict__,capacity=telemetry))
    except BaseException:
        life.book.replay();native=life.book._load(life.lifecycle_id)
        life.sleeve.recover_scale(life.lifecycle_id,request=request,native_verified=True,
            committed=native.get('scale_request')==request)
        raise
    native_sync(life.book,life.sleeve,life.lifecycle_id)
    return life.snapshot()


class RollingAttemptBudget:
    """Legacy work pressure telemetry; never candidate admission authority."""
    def __init__(self,limit=MAX_FULL_ATTEMPTS,window=3300):
        self.limit=limit;self.window=window;self.admitted=deque()

    def take(self,now):
        while self.admitted and self.admitted[0]<=now-self.window:self.admitted.popleft()
        if len(self.admitted)>=self.limit:return False
        self.admitted.append(now);return True


def _terminal(report,row):
    from meme_machine.runtime.storage import jsonl_ring
    jsonl_ring(REPORT.with_suffix('.terminal.jsonl'),dict(policy_hash=policy_hash(),**row))
    counts=report.setdefault('terminal_reason_counts',{})
    _progress(row.get("mint","unknown"),"terminal",row["terminal_reason"])
    reason=row['terminal_reason'];counts[reason]=counts.get(reason,0)+1


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


def _smoke_tail_admission_closed(smoke_flat_tail,now,discovery_end):
    return bool(smoke_flat_tail and int(now)>=int(discovery_end))


def _smoke_tail_should_exit(smoke_flat_tail,now,discovery_end,pending,active):
    return bool(
        _smoke_tail_admission_closed(smoke_flat_tail,now,discovery_end)
        and not pending and not active
    )


def restore_runtime(book,plane,confirmations,*,bind_allocation=True):
    """Actual startup reconstruction; JSON reports are never consulted."""
    created={};postgrad={};pending={};active={};qualifiers=[]
    book.replay()
    rows=book.db.execute('SELECT id,body FROM positions ORDER BY id').fetchall()
    for identity,raw in rows:
        projection=json.loads(raw)
        life=PumpAccelerationPaperLifecycle.restore(book,identity)
        if bind_allocation:
            from meme_machine.runtime.directional_sleeve import bind_pump_recovered_allocation
            bind_pump_recovered_allocation(book,life)
        state=life.entry_evidence.get('_runtime_recovery')
        if state is None:
            if life.position or life.reservation:raise Unavailable('legacy_runtime_context_unavailable')
            continue
        signal=SignalVector(**state['signal']);mode=state['mode'];mint=signal.mint;key=(mint,mode)
        original=life.entry_evidence
        q=life.history[0]
        qrow=dict(lifecycle_id=identity,mint=mint,mode=mode,entry_status=projection['status'],
            reserved_at=q['reserved_at'],policy_hash=policy_hash())
        qualifiers.append(qrow)
        saved=state.get('confirmation_state') or {}
        for creator,launches in saved.get('creator_launches',{}).items():
            confirmations.creator_launches.setdefault(creator,{}).update(launches)
        confirmations.mint_creator.update(saved.get('mint_creator',{}))
        native=dict(state['state'])
        if 'pregrad_wallets' in native:native['pregrad_wallets']=set(native['pregrad_wallets'])
        if mode==MODE_LATE_CURVE:created[mint]=native
        else:
            native['history']=LocalPumpHistory(plane,native['pool'],native['graduation_time'])
            postgrad[mint]=native
        if life.reservation is not None:
            pending[key]=dict(lifecycle=life,reserved_at=q['reserved_at'],due=q['reserved_at']+ENTRY_DELAY_SECONDS,
                decision_slot=original['slot'],qualifier_row=qrow,last_concentration=state['concentration'],
                decision_signal=signal,execution_context=state['execution'])
        saved_postgrad=book.runtime_state(identity,'postgrad_context')
        if saved_postgrad:
            saved_postgrad['pregrad_wallets']=set(saved_postgrad['pregrad_wallets'])
            saved_postgrad['history']=LocalPumpHistory(plane,saved_postgrad['pool'],saved_postgrad['graduation_time'])
            postgrad[mint]=saved_postgrad
        if life.position is not None:
            fill_context=book.runtime_state(identity,'fill_context') or {}
            active[key]=dict(lifecycle=life,opened=life.position.opened_at,next_monitor=0,
                entry=fill_context.get('entry',{}),marks={},last_concentration=fill_context.get('concentration',state['concentration']))
        if life.position is not None or life.reservation is not None:
            execution=state['execution']
            plane.interest(execution['scope'],lower_slot=original['slot'],addresses=execution['addresses'],
                owner=identity,lifecycle='open' if life.position else 'reserved',priority=0 if life.position else 1)
    return created,postgrad,pending,active,qualifiers


def main(*,campaign=False,discovery_seconds=None):
    global ACCOUNTING,PIPELINE,FILL_PERSISTENCE_CONTEXT,CANDIDATE_HISTORY
    from meme_machine.lanes.pump.paper_accounting import PaperBook
    import uuid
    if type(campaign) is not bool:raise ValueError('pump_campaign_flag')
    discovery_seconds=DISCOVERY_SECONDS if discovery_seconds is None else int(discovery_seconds)
    if not 600<=discovery_seconds<=(21600 if campaign else 3300):
        raise ValueError('pump_discovery_runtime_bound')
    smoke_flat_tail=bool(campaign and os.environ.get('MM_OPERATIONAL_PHASE')=='smoke')
    actual_policy_hash=policy_hash()
    from meme_machine.runtime.candidate_history import open_candidate_history
    CANDIDATE_HISTORY=open_candidate_history()
    if actual_policy_hash!=FROZEN_POLICY_HASH:
        raise RuntimeError("frozen_policy_hash_changed")
    confirmations=ConfirmationBook.from_files()
    run_id=os.environ.get("MM_PAPER_EPOCH") or uuid.uuid4().hex
    accounting_path=REPORT.with_suffix(".accounting.sqlite3")
    if accounting_path.exists():
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(accounting_path.resolve().as_uri()+'?mode=ro',uri=True)) as prior:
            genesis=json.loads(prior.execute('SELECT body FROM genesis').fetchone()[0])
        if os.environ.get('MM_PAPER_EPOCH') not in (None,genesis['run_id']):
            raise RuntimeError('paper_recovery_run_identity_mismatch')
        run_id=genesis['run_id']
    ACCOUNTING=PaperBook(str(accounting_path),run_id=run_id,lane=STRATEGY_ID,
                         policy_hash=actual_policy_hash,initial=INITIAL_LAMPORTS)
    from meme_machine.runtime.directional_sleeve import recover_pump_terminals
    recover_pump_terminals(ACCOUNTING)
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
        evidence_source="alchemy_finalized_local_evidence_plane",
        evidence_acquisition_mode=(
            "continuous_finalized_ingestion_local_history_explicit_gap_repair"),
        curve_progress_definition="prospectively observed CreateEvent initial_real_token_reserves -> reserve depletion",
        velocity_window_seconds=30,extension_lookback_seconds=10,
        entry_budget_lamports=ENTRY_BUDGET,entry_fraction_bps=POLICY.entry_fraction_bps,
        entry_delay_seconds=ENTRY_DELAY_SECONDS,entry_fill_timeout_seconds=ENTRY_FILL_TIMEOUT_SECONDS,
        discovery_seconds=discovery_seconds,followup_seconds=FOLLOWUP_SECONDS,continuous_campaign=campaign,
        started=int(time.time()),stream={},sessions=[],counts={},limitations=[],
        run_id=run_id,accounting_path=str(accounting_path),
        confirmation_evidence=confirmations.status(),
        attempts=[],full_evidence_candidates=[],qualifiers=[],funding_denials=[],settled=[],
        open_positions=[],postgrad=[],
    )
    report['operational_configuration']=dict(campaign=campaign,discovery_seconds=discovery_seconds,
        full_attempt_limit=None,full_attempt_window_seconds=None,
        cheap_postgrad_candidate_limit=None,
        expensive_postgrad_per_turn=MAX_EXPENSIVE_POSTGRAD_PER_TURN,
        expensive_scheduler='shared_edf',
        followup_seconds=FOLLOWUP_SECONDS,
        candidate_limits_are_pressure_only=True,
        open_positions_before_candidate_hydration=True)
    import hashlib
    report['operational_configuration_hash']=hashlib.sha256(json.dumps(
        report['operational_configuration'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    _save(report)

    from meme_machine.lanes.pump.solana_evidence_health import HealthWatch
    evidence_watch=HealthWatch(time.monotonic())
    plane=RuntimeEvidence(owner='pump')
    tape=LocalPumpTape(plane)
    discovery_tape=PumpTape()
    broker_path=os.environ.get("MM_SOLANA_EVIDENCE_BROKER_DB",DEFAULT_BROKER_DB)
    broker=EvidenceBroker(broker_path)
    stop=threading.Event();ready=threading.Event()
    stream=PumpLogStream(primary_rpc_url(required=True),discovery_tape,ws_url=discovery_ws_url())
    pumpswap_stream=LocalInterestRegistry(plane)
    thread=threading.Thread(target=stream.run,args=(stop,ready),daemon=True)
    thread.start()
    if not ready.wait(15):report['limitations'].append('public_discovery_start_timeout')

    sessions=Sessions();sessions.plane=plane
    survivor=None
    if os.environ.get('MM_DIRECTIONAL_COMPOSITE_REQUIRED')=='1':
        from meme_machine.runtime.survivor_history import Worker
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime
        survivor=Worker(lambda:Runtime(REPORT.parent/'pump-survivor',INITIAL_LAMPORTS,run_id,confirmations))
        report['active_regimes']=[STRATEGY_ID,'pumpswap-survivor-momentum-v1']
    cursor=0;full_attempts=0
    attempt_budget=RollingAttemptBudget()
    created,postgrad,pending,active,recovered=restore_runtime(ACCOUNTING,plane,confirmations)
    report['restored_observed_candidates']=_restore_observed_pump_candidates(
        created,postgrad,pumpswap_stream,plane,confirmations,int(time.time()))
    if survivor is not None:survivor.prime()
    from meme_machine.runtime.status import update
    update('MANAGING' if active or pending else 'DISCOVERING',reconciled=True,restored_positions=len(active)+len(pending))
    report["qualifiers"].extend(recovered)
    FILL_PERSISTENCE_CONTEXT=dict(
        tape=tape,created=created,postgrad=postgrad,plane=plane,confirmations=confirmations
    )
    last_eval={};last_postgrad_eval={};last_save=0
    discovery_end=int(time.time())+discovery_seconds
    end=discovery_end+FOLLOWUP_SECONDS
    report["discovery_deadline"]=discovery_end

    try:
        while int(time.time())<end:
            now=int(time.time())
            _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,now)
            _service_pending_entries(report,pending,active,sessions,postgrad,monitor=lambda: _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,int(time.time())))
            if survivor is not None:report['survivor']=survivor.tick(now,admit=now<discovery_end)
            if campaign:_retire_postgrad(report,postgrad,pending,active,pumpswap_stream,int(time.time()))
            health=plane.health(PUMP_SCOPE)
            if health['usable']:health=plane.health(SWAP_SCOPE)
            evidence_watch.observe(health,time.monotonic())
            report['evidence_liveness']=evidence_watch.snapshot()
            if evidence_watch.failure:
                report['infrastructure_failure']=evidence_watch.failure
                if not pending and not active:break
            if _smoke_tail_should_exit(
                    smoke_flat_tail,now,discovery_end,pending,active):
                report['smoke_tail_exit']='flat_after_discovery'
                report['discovery_completed_at']=now
                break
            try:
                fresh,cursor=tape.events_since(cursor)
                report['pump_history_events_retained']=report.get('pump_history_events_retained',0)+\
                    _retain_pump_source_history(tape.candidate_history_rows)
            except ValueError as exc:
                report["evidence_plane_wait"]=str(exc)
                if now-last_save>=2:
                    report['stream']=plane.telemetry();_save(report);last_save=now
                _stop_sleep(.25);continue
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
                    if len(postgrad)>=MAX_POSTGRAD_CANDIDATES and not position_needs_stream:
                        # The historical count is a pressure threshold only.  A
                        # recoverable graduation may not disappear because the
                        # deep-watch set is busy.
                        report['postgrad_candidate_capacity_pressure']=(
                            report.get('postgrad_candidate_capacity_pressure',0)+1)
                        _progress(event['mint'],'capacity_pressure',
                                  'postgrad_candidate_capacity_pressure',
                                  economic_rejection=False)
                    pool=pumpswap_pool(event["mint"])
                    stream_key=pumpswap_stream.add_address(pool)
                    postgrad[event["mint"]]=dict(
                        mint=event["mint"],creation=state["creation"],
                        graduation_time=int(event["market_time"]),
                        pregrad_wallets=set(state["pregrad_wallets"]),pool=pool,
                        history=LocalPumpHistory(
                            plane,pool,int(event["market_time"])),
                        history_status={},graduation_price=None,
                    )
                    if CANDIDATE_HISTORY is not None:
                        CANDIDATE_HISTORY.observe(
                            'pump',event["mint"],surface='pumpswap',
                            observed_at=int(event["market_time"]),
                            decision_deadline=int(event["market_time"])+
                                max(POLICY.max_postgrad_entry_age_s,600),
                            metadata=dict(pool=pool,source='pump_graduation'))

            # New late-curve entries stop at discovery_end; follow-up never backfills
            # another pre-graduation decision.
            if now<discovery_end and tape.covered(now):
                for event in fresh:
                    _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,int(time.time()))
                    _service_pending_entries(report,pending,active,sessions,postgrad,monitor=lambda: _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,int(time.time())))
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
                    _progress(mint,"prospect_observed",mode=MODE_LATE_CURVE)
                    try:
                        stream_time=int(event["market_time"])
                        from meme_machine.runtime.candidate_history import economic_event_cursor
                        stream_events=[row for row in tape.window(
                            mint,stream_time,max_slot=int(event["slot"]))
                            if economic_event_cursor(row)<=economic_event_cursor(event)]
                        prospect,prospect_trajectory,prospect_confirmation=_late_stream_signal(
                            creation,stream_events,event,confirmations)
                        prospect_q,prospect_reasons=_late_stream_prospect(prospect)
                    except (ValueError,KeyError,TypeError) as exc:
                        reason=str(exc) or type(exc).__name__
                        _progress(mint,"prospect_incomplete",reason,mode=MODE_LATE_CURVE)
                        counts=report.setdefault("prospect_screen_incomplete_counts",{})
                        counts[reason]=counts.get(reason,0)+1
                        continue
                    if prospect_reasons:
                        reason="strategy_prospect:"+",".join(prospect_reasons)
                        _progress(mint,"prospect_screened",reason,mode=MODE_LATE_CURVE)
                        counts=report.setdefault("prospect_screen_rejection_counts",{})
                        for item in prospect_reasons:
                            counts[item]=counts.get(item,0)+1
                        continue
                    _progress(mint,"prospect_admitted",mode=MODE_LATE_CURVE)
                    _progress(mint,"screened",mode=MODE_LATE_CURVE)
                    _progress(mint,"admitted",mode=MODE_LATE_CURVE)
                    _progress(mint,"evidence_requested",mode=MODE_LATE_CURVE,decision_at=now)
                    _progress(mint,"decision_evidence_requested",mode=MODE_LATE_CURVE,decision_at=now)
                    try:
                        sessions.ensure(25)
                        snapshot=sessions.pump.snapshot(mint,now,priority=True)
                        created[mint]["execution_context"]=sessions.execution_interest(snapshot)
                        ev=tape.window(mint,int(snapshot["market_time"]),max_slot=snapshot["slot"])
                        pre_signal,trajectory,confirmation=_late_signal(
                            creation,ev,snapshot,0,confirmations)
                        _progress(mint,"decision_evidence_complete",mode=MODE_LATE_CURVE,
                                  decision_at=now,signal_at=pre_signal.observed_at)
                        preq=qualify(pre_signal)
                        # concentration=0 is the optimistic preflight.  If even that
                        # cannot qualify, an expensive holder scan cannot rescue it.
                        if not preq.qualified:
                            _record_attempt(
                                report,pre_signal,preq,"optimistic_preflight",
                                {"trajectory":trajectory,
                                 "confirmation_evidence":_confirmation_meta(confirmation)},snapshot=snapshot)
                            continue
                        _progress(mint,"evidence_required",mode=MODE_LATE_CURVE,
                                  decision_at=pre_signal.observed_at,
                                  remaining_evidence="concentration")
                        capacity_pressure=(
                            not attempt_budget.take(time.monotonic())
                            if campaign else full_attempts>=MAX_FULL_ATTEMPTS)
                        if capacity_pressure:
                            # Preserve opportunity breadth.  The old cap is now
                            # telemetry that exposes a capacity deficit; it never
                            # converts an otherwise evaluable candidate to terminal.
                            report['full_evidence_attempt_pressure']=(
                                report.get('full_evidence_attempt_pressure',0)+1)
                            _progress(mint,'capacity_pressure',
                                      'full_evidence_attempt_pressure',
                                      mode=MODE_LATE_CURVE,
                                      economic_rejection=False)
                        full_attempts+=1
                        _progress(mint,"full_evidence_requested",mode=MODE_LATE_CURVE,
                                  decision_at=pre_signal.observed_at,
                                  remaining_evidence="concentration")
                        concentration,meta=sessions.reader.read(mint,snapshot,priority=True)
                        signal,trajectory,confirmation=_late_signal(
                            creation,ev,snapshot,concentration,confirmations)
                        q=qualify(signal)
                        decision_row=_record_attempt(
                            report,signal,q,"full_point_in_time",
                            {"concentration_source":meta.get("source"),
                             "trajectory":trajectory,
                             "confirmation_evidence":_confirmation_meta(confirmation)},snapshot=snapshot)
                        if q.qualified and not any(
                                x["mint"]==mint and x["mode"]==MODE_LATE_CURVE
                                for x in report["qualifiers"]):
                            _reserve_position(
                                report,pending,active,signal,q,snapshot,
                                MODE_LATE_CURVE,concentration,
                                decision_id=decision_row.get('decision_id'))
                    except (Unavailable,ValueError,KeyError,TypeError) as exc:
                        _progress(mint,"terminal",str(exc),mode=MODE_LATE_CURVE)
                        report["attempts"].append(dict(
                            mint=mint,mode=MODE_LATE_CURVE,observed_at=now,
                            stage="incomplete",qualified=False,
                            limitation=str(exc) or type(exc).__name__))

            # Natural post-graduation and second-leg candidates are retained
            # without a count cap. Only expensive PumpSwap watch/qualification work
            # is serialized through the shared earliest-deadline-first scheduler.
            postgrad_work=None;scheduled_mint=None
            if CANDIDATE_HISTORY is not None:
                from meme_machine.runtime.candidate_history import CandidateDeadlineMissed
                for queued_mint,queued_state in list(postgrad.items()):
                    grad=int(queued_state["graduation_time"])
                    deadline_at=grad+max(POLICY.max_postgrad_entry_age_s,600)
                    CANDIDATE_HISTORY.observe(
                        'pump',queued_mint,surface='pumpswap',observed_at=grad,
                        decision_deadline=deadline_at,
                        metadata=dict(pool=queued_state["pool"],source='pump_graduation'))
                    CANDIDATE_HISTORY.enqueue(
                        'pump',queued_mint,kind='pumpswap_watch',
                        ready_at=grad+5,deadline=deadline_at,estimate_seconds=15,
                        priority=20,payload=dict(mint=queued_mint),
                        identity='pump:pumpswap_watch:'+queued_mint+':'+str(grad))
                try:
                    postgrad_work=CANDIDATE_HISTORY.claim(
                        'pump-postgrad:'+str(os.getpid()),lane='pump')
                except CandidateDeadlineMissed as exc:
                    report.setdefault('candidate_deadline_misses',[]).append(exc.work)
                    _progress(exc.work['candidate'],'evidence_incomplete',
                              'candidate_decision_deadline_missed',economic_rejection=False)
                    # A missed candidate deadline cannot stop position management
                    # or prevent other retained candidates from being serviced.
                    postgrad_work=None
                if postgrad_work is not None:
                    scheduled_mint=postgrad_work['candidate']
                    postgrad_items=(
                        [(scheduled_mint,postgrad[scheduled_mint])]
                        if scheduled_mint in postgrad else [])
                else:
                    postgrad_items=[]
            else:
                postgrad_items=list(postgrad.items())
            for mint,state in postgrad_items:
                _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,int(time.time()))
                _service_pending_entries(report,pending,active,sessions,postgrad,monitor=lambda: _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,int(time.time())))
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
                _progress(mint,"decision_evidence_requested",mode=MODE_POSTGRAD,decision_at=now)
                try:
                    sessions.ensure(85)
                    graduation=sessions.postgrad.graduation_snapshot(mint,now,priority=True)
                    handoff=graduation_handoff(graduation,max(now,int(graduation["available_time"])))
                    snapshot=sessions.postgrad.pumpswap_snapshot(handoff,now,priority=True)
                    state["execution_context"]=sessions.execution_interest(snapshot)
                    state["history"].bind_snapshot(snapshot)
                    events=_refresh_pool_events(
                        state,sessions,now,
                        research=(age>=POLICY.min_second_leg_age_s))
                    window_status=state["history"].decision_window_status(now,30)
                    if not window_status["complete"]:
                        raise Unavailable("incomplete_pumpswap_decision_window")
                    _progress(mint,"decision_evidence_complete",mode=MODE_POSTGRAD,
                              decision_at=now,history_window=window_status)
                    decision_events=state["history"].decision_rows(now,30)
                    # Concentration is the only expensive holder-level input here.
                    # First evaluate both entry modes optimistically with zero
                    # concentration; if neither can qualify, a holder scan cannot
                    # rescue the candidate and is deliberately skipped.
                    post_signal0,post_confirmation0=_volume_price_signal(
                        state,snapshot,decision_events,MODE_POSTGRAD,0,confirmations)
                    post_q0=qualify(post_signal0)
                    second_signal0=second_confirmation0=second_q0=None
                    if age>=POLICY.min_second_leg_age_s:
                        try:
                            if not state["history"].complete(now):
                                raise Unavailable("incomplete_pumpswap_second_leg_history")
                            second_signal0,second_confirmation0=_volume_price_signal(
                                state,snapshot,events,MODE_SECOND_LEG,0,confirmations)
                            second_q0=qualify(second_signal0)
                        except (Unavailable,ValueError,KeyError,TypeError) as exc:
                            _progress(mint,"terminal",str(exc),mode=MODE_SECOND_LEG,
                                      decision_at=now,history=state["history"].status(now))
                            report["attempts"].append(dict(
                                mint=mint,mode=MODE_SECOND_LEG,observed_at=now,
                                stage="shape_incomplete",qualified=False,
                                limitation=str(exc) or type(exc).__name__))

                    if not post_q0.qualified:
                        _record_attempt(
                            report,post_signal0,post_q0,"optimistic_preflight",
                            {"history_status":state["history"].status(now),
                             "concentration_scan_skipped":True,
                             "confirmation_evidence":_confirmation_meta(post_confirmation0)},snapshot=snapshot)
                    if second_q0 is not None and not second_q0.qualified:
                        _record_attempt(
                            report,second_signal0,second_q0,"optimistic_preflight",
                            {"history_status":state["history"].status(now),
                             "concentration_scan_skipped":True,
                             "confirmation_evidence":_confirmation_meta(second_confirmation0)},snapshot=snapshot)

                    if not _postgrad_concentration_required(post_q0,second_q0):
                        continue

                    for candidate_signal,candidate_q in ((post_signal0,post_q0),(second_signal0,second_q0)):
                        if candidate_q is not None and candidate_q.qualified:
                            _progress(mint,"evidence_required",mode=candidate_signal.phase,
                                      decision_at=candidate_signal.observed_at,
                                      remaining_evidence="concentration")
                            _progress(mint,"full_evidence_requested",mode=candidate_signal.phase,
                                      decision_at=candidate_signal.observed_at,
                                      remaining_evidence="concentration")
                    concentration=_postgrad_concentration(sessions.rpc,snapshot)
                    if post_q0.qualified:
                        signal,confirmation=_volume_price_signal(
                            state,snapshot,decision_events,MODE_POSTGRAD,concentration,confirmations)
                        q=qualify(signal)
                        decision_row=_record_attempt(
                            report,signal,q,"full_point_in_time",
                            {"history_status":state["history"].status(now),
                             "confirmation_evidence":_confirmation_meta(confirmation)},snapshot=snapshot)
                        if q.qualified and not any(
                                x["mint"]==mint and x["mode"]==MODE_POSTGRAD
                                for x in report["qualifiers"]):
                            _reserve_position(
                                report,pending,active,signal,q,snapshot,
                                MODE_POSTGRAD,concentration,
                                decision_id=decision_row.get('decision_id'))

                    if second_q0 is not None and second_q0.qualified:
                        second,confirmation2=_volume_price_signal(
                            state,snapshot,events,MODE_SECOND_LEG,concentration,confirmations)
                        q2=qualify(second)
                        decision_row2=_record_attempt(
                            report,second,q2,"full_point_in_time",
                            {"history_status":state["history"].status(now),
                             "confirmation_evidence":_confirmation_meta(confirmation2)},snapshot=snapshot)
                        if q2.qualified and not any(
                                x["mint"]==mint and x["mode"]==MODE_SECOND_LEG
                                for x in report["qualifiers"]):
                            _reserve_position(
                                report,pending,active,second,q2,snapshot,
                                MODE_SECOND_LEG,concentration,
                                decision_id=decision_row2.get('decision_id'))
                except (Unavailable,ValueError,KeyError,TypeError) as exc:
                    _progress(mint,"terminal",str(exc),mode=MODE_POSTGRAD,
                              decision_at=now,history=state["history"].status(now))
                    report["postgrad"].append(dict(
                        mint=mint,observed_at=now,age_seconds=age,
                        complete=False,limitation=str(exc) or type(exc).__name__,
                        history_status=(
                            state["history"].status(now)
                            if state.get("history") is not None else None)))
                    report["postgrad"]=report["postgrad"][-300:]

            if CANDIDATE_HISTORY is not None and postgrad_work is not None:
                mint=postgrad_work['candidate']
                state=postgrad.get(mint)
                horizon=(None if state is None else
                    int(state["graduation_time"])+max(POLICY.max_postgrad_entry_age_s,600))
                owns_position=any(key[0]==mint for key in (*pending,*active))
                if state is None or owns_position or (horizon is not None and int(time.time())>=horizon):
                    CANDIDATE_HISTORY.complete(postgrad_work['id'],status='complete')
                else:
                    CANDIDATE_HISTORY.complete(
                        postgrad_work['id'],status='deferred',
                        details=dict(delay_seconds=10))

            # Paper entries use the repository-standard two-second delay and a fresh
            # executable quote. This is execution realism, not a strategy threshold.
            _service_pending_entries(report,pending,active,sessions,postgrad,monitor=lambda: _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,int(time.time())))

            _monitor_positions(report,active,sessions,created,postgrad,tape,confirmations,int(time.time()))

            if now-last_save>=15:
                report["created_mints_observed"]=len(created)
                report["full_evidence_attempts"]=full_attempts
                report["active_provider"]=sessions.rpc.provider_telemetry()
                report["evidence_broker"]=broker.telemetry()
                if CANDIDATE_HISTORY is not None:
                    report["candidate_history"]=CANDIDATE_HISTORY.telemetry()
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
            _stop_sleep(1)
    finally:
        if survivor is not None:report['survivor']=survivor.close()
        stop.set();thread.join(timeout=5)
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
        if CANDIDATE_HISTORY is not None:
            report["candidate_history"]=CANDIDATE_HISTORY.telemetry()
        _save(report)
        broker.close();plane.close()
        FILL_PERSISTENCE_CONTEXT=None
        if CANDIDATE_HISTORY is not None:
            CANDIDATE_HISTORY.close();CANDIDATE_HISTORY=None
        ACCOUNTING.close();ACCOUNTING=None
        PIPELINE.close();PIPELINE=None
    print(json.dumps(report,sort_keys=True))
    if report.get('infrastructure_failure'):raise Unavailable(report['infrastructure_failure'])


if __name__=="__main__":
    main()


def _stop_sleep(seconds):
    from meme_machine.runtime.stop import sleep
    return sleep(seconds,sleeper=time.sleep)
