"""Prospective wallet-cluster DLMM candidate test.

Strictly post-freeze. Watches only the frozen trigger-wallet set, accepts only
fully authenticated one-sided-SOL add_liquidity2 signals in the frozen eligible
pool definition, mirrors the source 70-bin SOL weights at 0.1 SOL paper capital,
holds 491 seconds, and settles from verified forward market evidence.

No signing, submission, live-money authority, retrospective entry, or threshold
adaptation exists in this module.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import time

from meme_machine import dlmm
from meme_machine.dlmm_paper import CAPITAL, ENTRY_COST, EXIT_COST
from meme_machine.dlmm_tape import (
    _keys, _ordered_instructions, _un58_data, ADD_LIQUIDITY2_IX,
    apply_external_adjustment, ordered_tape_actions, replay_swap_event,
    transaction_swaps,
)
from meme_machine.provider import Unavailable
from tests import dlmm_alchemy_provider as alchemy_provider
from tests import dlmm_boundary_acquisition as boundary
from tests import dlmm_wallet_strategy_discovery as wallet_study
from tests.dlmm_strategy_point_in_time import _withdraw, _liquidation_value

CANDIDATE_PATH=Path("DLMM_WALLET_CLUSTER_CANDIDATE_V1.json")
REPORT_PATH=Path("dlmm-wallet-cluster-prospective.json")
WATCH_SECONDS=360
POLL_LIMIT=64
POOL_PAGE_SIZE=100
MAX_POOL_PAGES=5
TARGET_WIDTH=70
TARGET_HOLD_SECONDS=491
MAX_FORWARD_WALL_SECONDS=780
RPC_ROTATE_AT=200
MAX_TOTAL_LOGICAL_RPC=1800


def load_candidate():
    body=json.loads(CANDIDATE_PATH.read_text())
    if body.get("kind")!="dlmm_wallet_cluster_candidate_v1":
        raise RuntimeError("dlmm_wallet_candidate_kind")
    if body.get("status")!="frozen_exploratory_pre_prospective":
        raise RuntimeError("dlmm_wallet_candidate_not_frozen")
    if body.get("allocation_authority") is not False or body.get("live_money") is not False:
        raise RuntimeError("dlmm_wallet_candidate_authority")
    policy=body.get("prospective_policy") or {}
    cluster=body.get("exploratory_cluster") or {}
    if int(policy.get("hold_seconds") or 0)!=TARGET_HOLD_SECONDS:
        raise RuntimeError("dlmm_wallet_candidate_hold_drift")
    if int(cluster.get("exact_width_bins") or 0)!=TARGET_WIDTH:
        raise RuntimeError("dlmm_wallet_candidate_width_drift")
    wallets=cluster.get("trigger_wallets") or []
    if len(wallets)!=14 or len(set(wallets))!=14:
        raise RuntimeError("dlmm_wallet_candidate_wallet_set")
    return body


def eligible_pools():
    pools={}
    for page in range(1,MAX_POOL_PAGES+1):
        payload=wallet_study._json_get("/pools",dict(
            page=page,page_size=POOL_PAGE_SIZE,
            sort_by="fee_tvl_ratio_24h:desc",
            filter_by="is_blacklisted=false && tvl>=50000 && volume_24h>=25000",
        ))
        rows=payload.get("data") if isinstance(payload,dict) else None
        if not isinstance(rows,list):
            raise RuntimeError("dlmm_wallet_prospective_pool_shape")
        for row in rows:
            if not isinstance(row,dict) or not wallet_study._sol_paired(row):
                continue
            address=row.get("address")
            x=(row.get("token_x") or {}).get("address")
            y=(row.get("token_y") or {}).get("address")
            if isinstance(address,str) and isinstance(x,str) and isinstance(y,str):
                pools[address]=dict(address=address,x=x,y=y,name=row.get("name"))
        if len(rows)<POOL_PAGE_SIZE:
            break
    if not pools:
        raise RuntimeError("dlmm_wallet_prospective_no_eligible_pools")
    return pools


def _candidate_adds(tx,wallet):
    meta=tx.get("meta") or {}
    message=(tx.get("transaction") or {}).get("message") or {}
    keys=_keys(meta,message)
    required=int((message.get("header") or {}).get("numRequiredSignatures",0))
    candidates=[]
    for outer,inner,ix in _ordered_instructions(meta,message):
        pi=ix.get("programIdIndex")
        if type(pi) is not int or not 0<=pi<len(keys) or keys[pi]!=dlmm.PROGRAM:
            continue
        raw=_un58_data(ix.get("data") or "")
        if raw[:8]!=ADD_LIQUIDITY2_IX:
            continue
        accounts=ix.get("accounts") or []
        if len(accounts)<=9:
            continue
        if any(type(accounts[i]) is not int or not 0<=accounts[i]<len(keys)
               for i in (0,1,9)):
            continue
        if accounts[9]>=required or keys[accounts[9]]!=wallet:
            continue
        pool=keys[accounts[1]];position=keys[accounts[0]]
        effects=[]
        transaction_swaps(tx,pool,terminal_adjustments=effects)
        matches=[
            e for e in effects
            if e.get("kind")=="add_liquidity2"
            and e.get("sender")==wallet and e.get("position")==position
        ]
        if len(matches)!=1:
            raise Unavailable("dlmm_wallet_signal_add_effect_ambiguous")
        candidates.append(dict(
            wallet=wallet,pool=pool,position=position,
            execution_order=[outer,inner],effect=matches[0],
        ))
    return candidates


def _qualify_signal(event,pool_info):
    effect=event["effect"]
    deposits=[
        row for row in (effect.get("bin_deposits") or [])
        if int(row.get("x") or 0)>0 or int(row.get("y") or 0)>0
    ]
    if not deposits:
        return None,"empty_source_distribution"
    bids=[int(row["bin_id"]) for row in deposits]
    width=max(bids)-min(bids)+1
    if width!=TARGET_WIDTH:
        return None,f"source_width_not_{TARGET_WIDTH}"
    x=pool_info["x"];y=pool_info["y"]
    if x==dlmm.WSOL:
        if int(effect.get("amount_x") or 0)<=0 or int(effect.get("amount_y") or 0)!=0:
            return None,"source_not_one_sided_sol"
        weights={int(row["bin_id"]):int(row.get("x") or 0) for row in deposits}
    elif y==dlmm.WSOL:
        if int(effect.get("amount_y") or 0)<=0 or int(effect.get("amount_x") or 0)!=0:
            return None,"source_not_one_sided_sol"
        weights={int(row["bin_id"]):int(row.get("y") or 0) for row in deposits}
    else:
        return None,"pool_not_sol_paired"
    weights={bid:value for bid,value in weights.items() if value>0}
    if not weights or sum(weights.values())<=0:
        return None,"source_sol_distribution_empty"
    return dict(width_bins=width,source_sol_weights=weights),None


def _paper_deposit(state,signal,capital=CAPITAL):
    weights={int(k):int(v) for k,v in signal["source_sol_weights"].items()}
    if max(weights)-min(weights)+1!=TARGET_WIDTH:
        raise Unavailable("dlmm_wallet_paper_width")
    total=sum(weights.values())
    if total<=0:
        raise Unavailable("dlmm_wallet_paper_distribution")
    v=deepcopy(state)
    sol_y=state["y"]==dlmm.WSOL
    amounts={bid:capital*weight//total for bid,weight in weights.items()}
    idle=capital-sum(amounts.values())
    shares={};fee_start={}
    for bid in sorted(amounts):
        amount=amounts[bid]
        if amount<=0:
            continue
        b=v["bins"].get(str(bid))
        if b is None:
            raise Unavailable("dlmm_wallet_paper_missing_bin")
        # A post-signal mirror remains one-sided SOL. If the market moved enough
        # that the source range is no longer valid for one-sided SOL, reject rather
        # than invent an entry composition.
        if b["x" if sol_y else "y"]:
            raise Unavailable("dlmm_wallet_paper_post_signal_composition_changed")
        x,y=(0,amount) if sol_y else (amount,0)
        share=dlmm.deposit_share(b,x,y)
        if share<=0 or share+b["supply"]>dlmm.U128:
            raise Unavailable("dlmm_wallet_paper_invalid_share")
        shares[str(bid)]=share
        fee_start[str(bid)]={"x":b["fee_x"],"y":b["fee_y"]}
        b["x"]+=x;b["y"]+=y;b["supply"]+=share
    if not shares:
        raise Unavailable("dlmm_wallet_paper_empty_position")
    return dict(
        shares=shares,fee_start=fee_start,virtual=v,idle_sol=idle,
        lower=min(map(int,shares)),upper=max(map(int,shares)),
        entry_active=state["active"],entry_slot=state["slot"],entry_time=state["time"],
    )


def _apply_tape(position,tape):
    v=deepcopy(position["virtual"])
    for kind,item in ordered_tape_actions(tape):
        if kind=="swap":
            v,_=replay_swap_event(v,item)
        else:
            v=apply_external_adjustment(v,item,counterfactual=True)
        v["slot"]=item["cursor"][0]
    v["slot"]=tape.terminal["slot"]
    v["time"]=tape.terminal["time"]
    p=deepcopy(position);p["virtual"]=v
    return p


def _settle(position):
    state,assets=_withdraw(position)
    sol_side="x" if state["x"]==dlmm.WSOL else "y"
    token_side="y" if sol_side=="x" else "x"
    sol=assets[sol_side]+assets["fee_"+sol_side]+position["idle_sol"]
    tokens=assets[token_side]+assets["fee_"+token_side]
    full_liq=_liquidation_value(
        deepcopy(state),tokens,sol_side,state["time"]) if tokens else 0
    ending=sol+full_liq
    costs=ENTRY_COST+EXIT_COST
    pnl=ending-CAPITAL-costs
    return dict(
        resolved=True,capital_lamports=CAPITAL,fixed_cost_lamports=costs,
        ending_sol_lamports=ending,pnl_lamports=pnl,
        pnl_bps=pnl*10000/CAPITAL,
        gross_fee_sol_inventory=assets["fee_"+sol_side],
        token_inventory=assets[token_side],
        fee_token_inventory=assets["fee_"+token_side],
        token_liquidation_lamports=full_liq,
        lower=position["lower"],upper=position["upper"],
        entry_active=position["entry_active"],ending_active=position["virtual"]["active"],
        entry_time=position["entry_time"],exit_time=state["time"],
    )


class RPCPool:
    def __init__(self):
        self.pacer=alchemy_provider.AlchemyPacer()
        self.instances=[]
        self.rpc=None
        self.rotate()
    def rotate(self):
        self.rpc=alchemy_provider.new_rpc(limit=240,pacer=self.pacer)
        self.instances.append(self.rpc)
        return self.rpc
    def current(self):
        if self.rpc.calls>=RPC_ROTATE_AT:
            self.rotate()
        return self.rpc
    def total_calls(self):
        return sum(r.calls for r in self.instances)
    def telemetry(self):
        return dict(
            instances=len(self.instances),
            logical_calls=self.total_calls(),
            http_requests=sum(r.http_requests for r in self.instances),
            failures=sum(r.failures for r in self.instances),
            retries=sum(r.retries for r in self.instances),
            failure_kinds={
                k:sum((r.failure_kinds or {}).get(k,0) for r in self.instances)
                for k in sorted({k for r in self.instances for k in (r.failure_kinds or {})})
            },
            pacer=self.pacer.telemetry(),
        )


def _signature_cursors(rpc_pool,wallets):
    rpc=rpc_pool.current()
    params=[[w,dict(limit=1,commitment="finalized")] for w in wallets]
    rows=rpc.call_many("getSignaturesForAddress",params,True,batch_size=7)
    cursors={}
    for wallet,result in zip(wallets,rows):
        first=result[0]["signature"] if isinstance(result,list) and result else None
        cursors[wallet]=first
    return cursors


def _new_wallet_rows(rpc_pool,wallets,cursors):
    rpc=rpc_pool.current()
    params=[]
    for wallet in wallets:
        cfg=dict(limit=POLL_LIMIT,commitment="finalized")
        if cursors.get(wallet):
            cfg["until"]=cursors[wallet]
        params.append([wallet,cfg])
    results=rpc.call_many("getSignaturesForAddress",params,True,batch_size=7)
    pending=[]
    for wallet,rows in zip(wallets,results):
        if not isinstance(rows,list):
            raise Unavailable("dlmm_wallet_signal_signature_shape")
        if len(rows)>=POLL_LIMIT:
            raise Unavailable("dlmm_wallet_signal_signature_overflow")
        if rows:
            cursors[wallet]=rows[0]["signature"]
        for row in reversed(rows):
            if isinstance(row,dict) and not row.get("err") and isinstance(row.get("signature"),str):
                pending.append(dict(wallet=wallet,**row))
    return pending


def watch_for_signal(candidate,pools,rpc_pool):
    wallets=list(candidate["exploratory_cluster"]["trigger_wallets"])
    cursors=_signature_cursors(rpc_pool,wallets)
    started=time.time();observations=0;rejections=[]
    while time.time()-started<WATCH_SECONDS:
        if rpc_pool.total_calls()>=MAX_TOTAL_LOGICAL_RPC:
            raise Unavailable("dlmm_wallet_prospective_rpc_bound")
        pending=_new_wallet_rows(rpc_pool,wallets,cursors)
        observations+=len(pending)
        if pending:
            unique={}
            for row in pending:
                unique[(row["wallet"],row["signature"])]=row
            ordered=sorted(unique.values(),key=lambda r:(int(r.get("slot") or 0),r["signature"],r["wallet"]))
            rpc=rpc_pool.current()
            params=[[r["signature"],dict(
                encoding="json",commitment="finalized",
                maxSupportedTransactionVersion=1,
            )] for r in ordered]
            txs=rpc.call_many("getTransaction",params,True,batch_size=4) if params else []
            for row,tx in zip(ordered,txs):
                if not tx or (tx.get("meta") or {}).get("err"):
                    continue
                try:
                    adds=_candidate_adds(tx,row["wallet"])
                except (Unavailable,ValueError,KeyError,TypeError) as exc:
                    rejections.append(dict(signature=row["signature"],wallet=row["wallet"],
                                           reason=str(exc)[:140]))
                    continue
                for add in adds:
                    info=pools.get(add["pool"])
                    if info is None:
                        rejections.append(dict(signature=row["signature"],wallet=row["wallet"],
                                               pool=add["pool"],reason="pool_outside_frozen_eligibility"))
                        continue
                    qualified,reason=_qualify_signal(add,info)
                    if qualified is None:
                        rejections.append(dict(signature=row["signature"],wallet=row["wallet"],
                                               pool=add["pool"],reason=reason))
                        continue
                    return dict(
                        observer_started_unix=started,
                        observed_at_unix=time.time(),
                        wallet=row["wallet"],signature=row["signature"],
                        slot=int(tx.get("slot") or row.get("slot") or 0),
                        block_time=tx.get("blockTime"),
                        pool=add["pool"],position=add["position"],
                        execution_order=add["execution_order"],
                        **qualified,
                        source_effect=dict(
                            amount_x=add["effect"].get("amount_x"),
                            amount_y=add["effect"].get("amount_y"),
                            active=add["effect"].get("active"),
                            recipient_auth=add["effect"].get("recipient_auth"),
                        ),
                        wallet_rows_observed=observations,
                        rejections_before_signal=rejections[-100:],
                    )
        time.sleep(2.0)
    return None,dict(
        observer_started_unix=started,observer_ended_unix=time.time(),
        wallet_rows_observed=observations,rejections=rejections[-200:])


def capture_entry_state(signal,rpc_pool):
    last=None
    for _ in range(4):
        rpc=rpc_pool.current();adapter=dlmm.Adapter(rpc)
        snap=adapter.snapshot(signal["pool"],int(time.time()),True,fresh=True)
        state=dlmm.validate(snap,snap["available_time"],"real")
        last=(adapter,state,snap)
        if state["slot"]>=signal["slot"]:
            return last
        time.sleep(1.0)
    raise Unavailable("dlmm_wallet_entry_state_pre_signal")


def forward_and_settle(signal,position,entry_state,rpc_pool):
    current=entry_state
    cursor=[current["slot"],2**31-1,2**31-1]
    target_market_time=position["entry_time"]+TARGET_HOLD_SECONDS
    started=time.time();chunks=[];all_actions=0
    while current["time"]<target_market_time:
        if time.time()-started>MAX_FORWARD_WALL_SECONDS:
            raise Unavailable("dlmm_wallet_forward_wall_bound")
        if rpc_pool.total_calls()>=MAX_TOTAL_LOGICAL_RPC:
            raise Unavailable("dlmm_wallet_prospective_rpc_bound")
        rpc=rpc_pool.current();adapter=dlmm.Adapter(rpc)
        try:
            tape,cursor,tx_count=boundary.capture_chunk(adapter,current,cursor)
        except (Unavailable,ValueError,KeyError,TypeError) as exc:
            raise Unavailable("dlmm_wallet_forward_incomplete:"+str(exc)) from None
        if tape.terminal["slot"]<current["slot"] or tape.terminal["time"]<current["time"]:
            raise Unavailable("dlmm_wallet_forward_regression")
        position=_apply_tape(position,tape)
        actions=list(ordered_tape_actions(tape))
        all_actions+=len(actions)
        chunks.append(dict(
            start_slot=current["slot"],end_slot=tape.terminal["slot"],
            start_time=current["time"],end_time=tape.terminal["time"],
            transactions=tx_count,actions=len(actions),
            swaps=len(tape.events),
            adjustments=len(tape.terminal_adjustments),
        ))
        current=tape.terminal
        # If the endpoint did not advance at all, allow finalized state to move.
        if chunks[-1]["end_slot"]==chunks[-1]["start_slot"]:
            time.sleep(1.0)
    result=_settle(position)
    result.update(
        target_hold_seconds=TARGET_HOLD_SECONDS,
        realized_hold_seconds=result["exit_time"]-result["entry_time"],
        verified_chunks=len(chunks),
        verified_actions=all_actions,
        chunks=chunks[-120:],
    )
    return result


def run():
    candidate=load_candidate()
    pools=eligible_pools()
    rpc_pool=RPCPool()
    report=dict(
        kind="dlmm_wallet_cluster_prospective_v1",
        candidate_commit="cc828d1282be6f5f64b8c2cce4ef0d381e31cb45",
        candidate_status=candidate["status"],
        scope="meme_machine_solana_dlmm_only",
        allocation_authority=False,signing=False,submission=False,live_money=False,
        legacy_60_second_strategy_status="research_hold",
        post_freeze_only=True,
        eligible_pool_count=len(pools),
        watch_seconds=WATCH_SECONDS,
        target_width_bins=TARGET_WIDTH,
        target_hold_seconds=TARGET_HOLD_SECONDS,
        result=None,
    )
    try:
        signal,watch=watch_for_signal(candidate,pools,rpc_pool)
        report["watch"]=watch if signal is None else dict(
            observer_started_unix=signal["observer_started_unix"],
            observed_at_unix=signal["observed_at_unix"],
            wallet_rows_observed=signal["wallet_rows_observed"],
            rejections_before_signal=signal["rejections_before_signal"],
        )
        if signal is None:
            report["status"]="completed_no_natural_signal"
            report["signal"]=None
            return report
        report["signal"]=signal
        adapter,entry_state,snap=capture_entry_state(signal,rpc_pool)
        signal_for_deposit=dict(source_sol_weights=signal["source_sol_weights"])
        position=_paper_deposit(entry_state,signal_for_deposit)
        report["entry"]=dict(
            slot=entry_state["slot"],market_time=entry_state["time"],
            active_bin=entry_state["active"],
            lower=position["lower"],upper=position["upper"],
            snapshot_hash=wallet_study.digest(snap) if hasattr(wallet_study,"digest") else None,
        )
        report["result"]=forward_and_settle(signal,position,entry_state,rpc_pool)
        report["status"]="settled_natural_prospective_paper"
        return report
    except Exception as exc:
        report["status"]="prospective_test_incomplete"
        report["error"]=str(exc)[:240]
        return report
    finally:
        report["provider"]=rpc_pool.telemetry()
        REPORT_PATH.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
        print(json.dumps(dict(
            status=report.get("status"),
            signal=None if report.get("signal") is None else report["signal"].get("signature"),
            pnl_bps=None if not report.get("result") else report["result"].get("pnl_bps"),
            provider_calls=report["provider"]["logical_calls"],
        ),sort_keys=True))


if __name__=="__main__":
    run()
