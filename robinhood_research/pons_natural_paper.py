"""Bounded genuine-natural Pons paper lifecycle proof.

This is deliberately *not* a Robinhood trading policy. The proof authorizes exactly
one isolated paper position selected by an outcome-blind rule: the first current,
authenticated, native-quote Pons V2 curve observed after startup. It exists only to
prove the mechanics:

natural evidence -> reservation -> delayed entry -> monitor -> delayed exit -> settlement

If the held curve naturally graduates, the position is routed only after an authentic
Pons factory + hook + Uniswap V4 lineage proof. V4 exit quotes use the official
Robinhood V4Quoter deployment and remain fail-closed.

No signing, submission, live money, shared allocator or profitability claim.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import time

from . import BoundaryError, CHAIN_ID
from .abi import calldata, topic, words, scalar
from .evidence import Stamp, Store, digest
from .finality import Finality
from .identity import load
from .keccak import keccak256
from .paper import Paper, Quote
from .pons import factory_record, raw_event, curve_abi, prove_v4_lineage
from .pons_natural_observation import (
    RESEARCH_BUY_WEI, RESEARCH_RECIPIENT, ZERO,
    _authenticate_candidate, _call, _current_curve_events, _curve_state,
    _latest_header, _one_word,
)
from .protocols import PoolKey
from .provider import Rpc

REPORT=Path(os.environ.get("MM_ROBINHOOD_PONS_PAPER_REPORT","robinhood-pons-paper-report.json"))
DB=Path(os.environ.get("MM_ROBINHOOD_PONS_PAPER_DB","robinhood-pons-paper.sqlite"))

DISCOVERY_SECONDS=120
MAX_HOLD_SECONDS=180
MONITOR_SECONDS=10
EXIT_RETRY_SECONDS=60
PAPER_AMOUNT=RESEARCH_BUY_WEI
PAPER_CAPITAL=10**18
TAKE_PROFIT_BPS=1500
RISK_BPS=-1000
V4_QUOTER="0x8dc178efb8111bb0973dd9d722ebeff267c98f94"
V4_SELECTOR="aa9d21cb"


def _rpc(endpoint):
    return Rpc(endpoint,limit=200,per_scope=190,retries=0)


def _gas_units(receipt):
    try:
        value=int(receipt["gasUsed"],16)
    except (KeyError,TypeError,ValueError):
        raise BoundaryError("missing_gas_used") from None
    if not 21_000<=value<=5_000_000:
        raise BoundaryError("gas_units_out_of_bounds")
    return value


def _gas_quote(rpc,gas_units):
    price=int(rpc.call("eth_gasPrice",[],scope="pons_paper"),16)
    if price<=0:
        raise BoundaryError("invalid_gas_price")
    return price*int(gas_units),price


def _fresh_stamp(header):
    now=int(time.time()); event_at=int(header["timestamp"],16)
    if now-event_at>5:
        raise BoundaryError("stale_state")
    return Stamp(
        CHAIN_ID,int(header["number"],16),header["hash"],event_at,now,
        "confirmed","natural",
    )


def _ledger_for_quote(store,stamp,parent_hash,label):
    ledger=Finality(store,scope="paper-"+label,max_blocks=4)
    ledger.observe(stamp,parent_hash)
    stamp.check(stamp.observed_at,5,finality_ledger=ledger)
    return ledger


def _curve_quote(rpc,candidate,side,amount,gas_units,store,label):
    header=_latest_header(rpc)
    block=int(header["number"],16)
    state,_=_curve_state(rpc,candidate["curve"],block,candidate["auth"],candidate["report"])
    if state.graduated:
        raise BoundaryError("curve_graduated_requires_transition")
    if side=="buy":
        current_snipe=_one_word(_call(
            rpc,candidate["curve"],"currentSnipeTaxBps(address)",
            (RESEARCH_RECIPIENT,),block,candidate["report"],
        ))
        value=state.buy_with_snipe(amount,current_snipe)
        amount_out=value["tokens_out"]
        fee=value["fee"]+value["creator_tax"]
    elif side=="sell":
        value=state.sell(amount)
        amount_out=value["quote_out"]
        fee=value["fee"]+value["creator_tax"]
    else:
        raise BoundaryError("unsupported_curve_quote_side")
    gas,gas_price=_gas_quote(rpc,gas_units)
    stamp=_fresh_stamp(header)
    # Ensure all state reads completed while the same block was still fresh.
    stamp.check(int(time.time()),5,finality_ledger=_ledger_for_quote(
        store,stamp,header["parentHash"],label,
    ))
    quote=Quote(candidate["curve"],side,amount,amount_out,gas,fee,stamp)
    return quote,dict(
        venue="pons_v2_curve",block=block,block_hash=header["hash"],
        event_at=stamp.event_at,observed_at=stamp.observed_at,gas_price=gas_price,
        gas_units_proxy=gas_units,gas_quote=gas,amount_in=amount,amount_out=amount_out,
        fee_quote=fee,state=asdict(state),
    )


def _wait_curve_quote(rpc,candidate,side,amount,gas_units,store,label,min_event_at,seconds=20):
    deadline=time.monotonic()+seconds
    last=None
    while time.monotonic()<deadline:
        try:
            quote,meta=_curve_quote(rpc,candidate,side,amount,gas_units,store,label)
            if quote.stamp.event_at>=min_event_at:
                return quote,meta,Finality(store,scope="paper-"+label,max_blocks=4)
            last="pre_delay_quote"
        except BoundaryError as exc:
            last=str(exc)
            if last=="curve_graduated_requires_transition":
                raise
        time.sleep(0.5)
    raise BoundaryError(last or "delayed_quote_timeout")


def _factory_record_at(rpc,token,block,report):
    factory=load("pons_v2_factory")["address"].lower()
    raw=_call(rpc,factory,"getLaunchedToken(address)",(token,),block,report)
    return factory_record(raw,"pons_v2_factory")


def _event_topic(role,name):
    abi=load(role)["abi"]
    rows=[x for x in abi if x.get("type")=="event" and x.get("name")==name]
    if len(rows)!=1:
        raise BoundaryError("graduation_event_abi")
    from .abi import signature
    return topic(signature(rows[0]))


def _topic_address(address):
    return "0x"+"0"*24+address.lower()[2:]


def _graduation_transition(rpc,candidate,start_block,end_block,report):
    if end_block<start_block:
        return None
    factory=load("pons_v2_factory")["address"].lower()
    hook=load("pons_v2_hook")["address"].lower()
    manager=load("uniswap_v4_manager")["address"].lower()
    rows=[]
    for first in range(start_block,end_block+1,10):
        rows.extend(rpc.call("eth_getLogs",[dict(
            fromBlock=hex(first),toBlock=hex(min(end_block,first+9)),address=factory,
            topics=[_event_topic("pons_v2_factory","PoolGraduated"),
                    _topic_address(candidate["token"])],
        )],scope="pons_paper"))
    if not rows:
        return None
    if len(rows)!=1:
        raise BoundaryError("ambiguous_natural_graduation")
    raw_grad=rows[0]
    header=rpc.call("eth_getBlockByHash",[raw_grad["blockHash"],False],scope="pons_paper")
    receipt=rpc.receipt(raw_grad["transactionHash"],raw_grad["blockHash"],scope="pons_paper")
    role_for={factory:"pons_v2_factory",hook:"pons_v2_hook",manager:"uniswap_v4_manager"}
    decoded=[]
    for event in receipt["logs"]:
        role=role_for.get(event["address"].lower())
        if not role:
            continue
        try:
            row=raw_event(
                load(role)["abi"],event,address=event["address"],receipt=receipt,header=header,
                observed_at=int(time.time()),confirmation="confirmed",
            )
            row["role"]=role;decoded.append(row)
        except BoundaryError as exc:
            if str(exc) not in ("unsupported_event_signature","unsupported_dynamic_event"):
                raise
    graduation=next((x for x in decoded
                     if x["role"]=="pons_v2_factory" and x["decoded"]["name"]=="PoolGraduated"),None)
    registration=next((x for x in decoded
                       if x["role"]=="pons_v2_hook" and x["decoded"]["name"]=="PoolRegistered"
                       and x["decoded"]["args"]["memecoin"]==candidate["token"]),None)
    initialization=next((x for x in decoded
                         if x["role"]=="uniswap_v4_manager" and x["decoded"]["name"]=="Initialize"
                         and registration
                         and x["decoded"]["args"]["id"]==registration["decoded"]["args"]["poolId"]),None)
    if not all((graduation,registration,initialization)):
        raise BoundaryError("natural_graduation_lineage_incomplete")
    block=int(header["number"],16)
    record=_factory_record_at(rpc,candidate["token"],block,report)
    proof=prove_v4_lineage(
        record=record,registration=registration,initialization=initialization,
        graduation=graduation,hook=hook,manager=manager,
    )
    transition=dict(
        origin="pons_v2_graduated_v4",token=candidate["token"],
        previous_market=candidate["curve"],market=proof["pool_id"],
        position_id=proof["position_id"],proof=proof,
    )
    transition["proof_hash"]=digest(transition)
    key=PoolKey(*sorted((record["token"],record["pairToken"]),key=lambda x:int(x,16)),
                record["poolFee"],record["tickSpacing"],hook)
    return transition,key,header,record


def _word(value):
    if value<0:
        value=(1<<256)+value
    if not 0<=value<1<<256:
        raise BoundaryError("v4_abi_word")
    return value.to_bytes(32,"big")


def _addr(value):
    return _word(int(value,16))


def _v4_quoter_calldata(key,zero_for_one,amount):
    if not 0<amount<1<<128:
        raise BoundaryError("v4_quote_amount")
    signature="quoteExactInputSingle(((address,address,uint24,int24,address),bool,uint128,bytes))"
    selector=keccak256(signature.encode()).hex()[:8]
    if selector!=V4_SELECTOR:
        raise BoundaryError("v4_quoter_selector_disagreement")
    # one dynamic tuple argument: outer offset, then 8-word tuple head + empty bytes.
    body=b"".join([
        _word(32),
        _addr(key.currency0),_addr(key.currency1),_word(key.fee),_word(key.tick_spacing),
        _addr(key.hook),_word(1 if zero_for_one else 0),_word(amount),_word(8*32),
        _word(0),
    ])
    return "0x"+selector+body.hex()


def _v4_quote(rpc,key,pool_id,tokens,gas_units,store,label):
    header=_latest_header(rpc); block=int(header["number"],16)
    manager=load("uniswap_v4_manager")["address"].lower()
    # Authenticate the official deployment's chain wiring before trusting the quote.
    code=rpc.call("eth_getCode",[V4_QUOTER,hex(block)],scope="pons_paper")
    if not code or code=="0x":
        raise BoundaryError("v4_quoter_code_missing")
    pm=_one_word(rpc.call(
        "eth_call",[dict(to=V4_QUOTER,data=calldata("poolManager()")),hex(block)],
        scope="pons_paper",
    ),"address")
    if pm!=manager:
        raise BoundaryError("v4_quoter_manager_disagreement")
    zero_for_one=(key.currency0!=ZERO)  # selling launch token into native quote.
    data=_v4_quoter_calldata(key,zero_for_one,tokens)
    raw=rpc.call("eth_call",[dict(to=V4_QUOTER,data=data),hex(block)],scope="pons_paper")
    values=words(raw)
    if len(values)!=2:
        raise BoundaryError("v4_quoter_output_shape")
    amount_out=scalar("uint256",values[0]); quoter_gas=scalar("uint256",values[1])
    if amount_out<=0:
        raise BoundaryError("v4_unavailable_full_position_exit")
    gas_price=int(rpc.call("eth_gasPrice",[],scope="pons_paper"),16)
    # The quoter gas estimate is simulation gas, not router execution gas; use the
    # larger of the observed curve-tx proxy and 2x quoter estimate.
    units=max(gas_units,quoter_gas*2)
    gas=units*gas_price
    stamp=_fresh_stamp(header)
    ledger=_ledger_for_quote(store,stamp,header["parentHash"],label)
    stamp.check(int(time.time()),5,finality_ledger=ledger)
    quote=Quote(pool_id,"sell",tokens,amount_out,gas,0,stamp)
    return quote,dict(
        venue="uniswap_v4",pool_id=pool_id,block=block,block_hash=header["hash"],
        amount_in=tokens,amount_out=amount_out,v4_quoter=V4_QUOTER,
        quoter_gas_estimate=quoter_gas,gas_units_proxy=units,gas_price=gas_price,
        gas_quote=gas,
    ),ledger


def _discover(rpc,report):
    start=int(_latest_header(rpc)["number"],16)
    cursor=start;attempted=set();deadline=time.monotonic()+DISCOVERY_SECONDS
    while time.monotonic()<deadline:
        latest=int(_latest_header(rpc)["number"],16)
        first=max(cursor+1,latest-9)
        if latest>=first:
            for event in _current_curve_events(rpc,first,latest):
                curve=event.get("address","").lower()
                if curve in attempted:
                    continue
                attempted.add(curve)
                try:
                    item=_authenticate_candidate(rpc,event,report)
                    item["report"]=report
                    return item
                except BoundaryError as exc:
                    report.setdefault("candidate_rejections",[]).append(
                        dict(curve=curve,block=event.get("blockNumber"),reason=str(exc))
                    )
                    if len(report["candidate_rejections"])>50:
                        raise BoundaryError("paper_candidate_rejection_capacity")
            cursor=latest
        time.sleep(0.5)
    raise BoundaryError("no_current_authenticated_pons_candidate")


def _return_bps(position,quote):
    net=quote.amount_out-quote.gas_quote
    return (net-position["cost"])*10000//position["cost"]


def run(endpoint):
    report=dict(
        kind="natural_pons_v2_paper_lifecycle_proof",started_at=time.time(),
        research_only=True,paper_only=True,live_money=False,shared_allocator=False,
        policy_status="not_established",authority="bounded_lifecycle_proof_only",
        selection_rule="first_current_authenticated_pons_v2_curve_after_start",
        exit_rule=dict(take_profit_bps=TAKE_PROFIT_BPS,risk_bps=RISK_BPS,
                       timeout_seconds=MAX_HOLD_SECONDS,proof_only=True),
        paper_amount=PAPER_AMOUNT,monitor=[],provider_sessions=[],
    )
    if DB.exists():
        DB.unlink()
    rpc=_rpc(endpoint)
    store=None
    try:
        rpc.verify_chain()
        candidate=_discover(rpc,report)
        gas_units=_gas_units(candidate["receipt"])
        initial_gas,initial_gas_price=_gas_quote(rpc,gas_units)
        gas_budget=max(initial_gas*10,10**15)
        report["gas_model"]=dict(
            units_proxy=gas_units,source="triggering_authenticated_curve_transaction_gasUsed",
            current_gas_price=initial_gas_price,reservation_budget=gas_budget,
        )
        now=candidate["quote_at"]
        decision=dict(
            asof=now,market=candidate["curve"],authority="bounded_lifecycle_proof_only",
            qualification="policy_not_established",
            selection_rule=report["selection_rule"],outcome_used_for_selection=False,
            token=candidate["token"],source_transaction=candidate["source_event"]["transactionHash"],
            quote_freshness_seconds=candidate["freshness_seconds"],
        )
        store=Store(str(DB),max_records=512)
        paper=Paper(store,"pons-natural-lifecycle-v1",PAPER_CAPITAL,delay=2,natural_proof=True)
        identity="pons:"+candidate["token"]+":"+candidate["source_event"]["transactionHash"]
        reserved=paper.reserve(
            identity,market=candidate["curve"],amount=PAPER_AMOUNT,gas_budget=gas_budget,
            now=now,features=decision,kind="natural",
        )
        report["candidate"]=dict(
            token=candidate["token"],curve=candidate["curve"],
            source_transaction=candidate["source_event"]["transactionHash"],
            source_block=candidate["block"],freshness_seconds=candidate["freshness_seconds"],
        )
        report["reservation"]=reserved

        # Delayed paper fill from a new current state, never the nomination quote.
        time.sleep(max(0,reserved["due"]-int(time.time())))
        entry,entry_meta,entry_ledger=_wait_curve_quote(
            rpc,candidate,"buy",PAPER_AMOUNT,gas_units,store,"entry",
            reserved["due"],seconds=20,
        )
        opened=paper.advance(
            identity,now=entry.stamp.observed_at,action="entry",quote=entry,
            finality_ledger=entry_ledger,
        )
        report["entry"]=dict(position=opened,quote=entry_meta)

        # Prove restart reconciliation immediately after the genuine natural fill.
        before=paper.reconcile();store.close()
        store=Store(str(DB),max_records=512)
        paper=Paper(store,"pons-natural-lifecycle-v1",PAPER_CAPITAL,delay=2,natural_proof=True)
        after=paper.reconcile()
        if before!=after:
            raise BoundaryError("natural_paper_restart_reconciliation")
        report["restart_reconciliation"]=after

        opened_at=opened["last_at"];last_block=entry_meta["block"]
        v4_key=None;transition=None
        reason=None
        while True:
            if rpc.used>145:
                report["provider_sessions"].append(rpc.telemetry())
                rpc=_rpc(endpoint);rpc.verify_chain()
            time.sleep(MONITOR_SECONDS)
            header=_latest_header(rpc);block=int(header["number"],16)
            position=paper._get(identity)
            if position["status"]=="settled":
                break

            if transition is None:
                maybe=_graduation_transition(
                    rpc,candidate,last_block,block,report
                )
                if maybe is not None:
                    transition,v4_key,grad_header,record=maybe
                    store.put("graduation",transition["proof_hash"],transition)
                    paper.advance(
                        identity,now=int(time.time()),action="transition",transition=transition
                    )
                    report["graduation_transition"]=dict(
                        transition=transition,block=int(grad_header["number"],16),
                        transaction_hash=transition["proof"].get("transaction_hash"),
                    )
                last_block=block

            position=paper._get(identity)
            elapsed=int(time.time())-opened_at
            if transition is None:
                try:
                    mark,meta,ledger=_curve_quote(
                        rpc,candidate,"sell",position["tokens"],gas_units,store,
                        "mark-"+str(len(report["monitor"])),
                    )
                except BoundaryError as exc:
                    if str(exc)=="curve_graduated_requires_transition":
                        continue
                    report["monitor"].append(dict(at=int(time.time()),market="curve",
                                                  available=False,reason=str(exc)))
                    if elapsed<MAX_HOLD_SECONDS:
                        continue
                    reason="timeout_unavailable"
                    break
            else:
                try:
                    mark,meta,ledger=_v4_quote(
                        rpc,v4_key,position["market"],position["tokens"],gas_units,store,
                        "v4mark-"+str(len(report["monitor"])),
                    )
                except BoundaryError as exc:
                    report["monitor"].append(dict(at=int(time.time()),market="v4",
                                                  available=False,reason=str(exc)))
                    if elapsed<MAX_HOLD_SECONDS:
                        continue
                    reason="timeout_unavailable"
                    break
            rbps=_return_bps(position,mark)
            report["monitor"].append(dict(
                at=mark.stamp.observed_at,market=("v4" if transition else "curve"),
                available=True,return_bps=rbps,quote=meta,
            ))
            if rbps<=RISK_BPS:
                reason="risk"
            elif rbps>=TAKE_PROFIT_BPS:
                reason="take_profit"
            elif elapsed>=MAX_HOLD_SECONDS:
                reason="timeout"
            else:
                continue

            paper.advance(identity,now=mark.stamp.observed_at,action="exit_intent")
            pending=paper._get(identity)
            time.sleep(max(0,pending["due"]-int(time.time())))
            if transition is None:
                exit_quote,exit_meta,exit_ledger=_wait_curve_quote(
                    rpc,candidate,"sell",pending["tokens"],gas_units,store,
                    "exit",pending["due"],seconds=20,
                )
            else:
                deadline=time.monotonic()+20
                while True:
                    exit_quote,exit_meta,exit_ledger=_v4_quote(
                        rpc,v4_key,pending["market"],pending["tokens"],gas_units,store,"v4exit"
                    )
                    if exit_quote.stamp.event_at>=pending["due"]:
                        break
                    if time.monotonic()>=deadline:
                        raise BoundaryError("v4_delayed_exit_quote_timeout")
                    time.sleep(0.5)
            settled=paper.advance(
                identity,now=exit_quote.stamp.observed_at,action="exit",quote=exit_quote,
                finality_ledger=exit_ledger,
            )
            report["exit"]=dict(reason=reason,quote=exit_meta,position=settled)
            break

        # Fail closed rather than fabricate a settlement after unavailable liquidity.
        final=paper._get(identity)
        if final["status"]!="settled":
            report["unresolved_position"]=final
            raise BoundaryError(reason or "natural_position_unresolved")

        # Recheck every action's paper accounting after another restart.
        reconciliation=paper.reconcile();store.close()
        store=Store(str(DB),max_records=512)
        paper=Paper(store,"pons-natural-lifecycle-v1",PAPER_CAPITAL,delay=2,natural_proof=True)
        if paper.reconcile()!=reconciliation:
            raise BoundaryError("final_restart_reconciliation")
        report["final_position"]=paper._get(identity)
        report["reconciliation"]=reconciliation
        report["completed_lifecycle"]=True
        report["carried_through_graduation"]=transition is not None
        report["profitability_claim"]=False
    except BoundaryError as exc:
        report["boundary"]=str(exc)
        report["completed_lifecycle"]=False
    finally:
        if store is not None:
            try:store.close()
            except Exception:pass
        report["provider_sessions"].append(rpc.telemetry())
        report["ended_at"]=time.time()
    return report


if __name__=="__main__":
    result=run(os.environ.get("MM_ROBINHOOD_READ_RPC_URL",""))
    raw=json.dumps(result,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>2_000_000:
        raise BoundaryError("paper_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps(dict(
        boundary=result.get("boundary"),completed=result.get("completed_lifecycle"),
        graduation=result.get("carried_through_graduation"),
        final_position=result.get("final_position"),
        exit=result.get("exit"),provider_sessions=result["provider_sessions"],
    ),sort_keys=True))
