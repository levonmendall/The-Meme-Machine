"""Freeze one conservative venue-wide Ramses cost anchor for Branch B certification.

Cost economics are unchanged from ramses-receipt-cost-v1.  This module only
makes sample acquisition robust: it discovers bounded historical Ramses
economic transaction identities from the index, then re-authenticates every
accepted sample from the canonical Robinhood receipt/header and Ramses event
ABI before its gasUsed value can enter the cost model.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json, os
from pathlib import Path

from . import BoundaryError
from .identity import authenticate, load
from .ramses import decode_ramses_event
from .ramses_capture import BoundedMultiRpc
from .ramses_costs import observe_receipt_gas, current_native_cycle
from .ramses_historical_quiet_mint_counterfactual import gql, addr
from .ramses_universe import _enumerate_factory

OUT=Path("ramses-branch-b-cost-anchor.json")
CHAIN=4663
INDEX_LIMIT_PER_EVENT=64
EVENT_SOURCES=(
    ("DLMMSwap","Swap","unwind"),
    ("DLMMMint","DepositedToBins","add_liquidity"),
    ("DLMMBurn","WithdrawnFromBins","remove_liquidity"),
)


def _txhash(value):
    raw=str(value or "").split(":")[-1].lower()
    if not raw.startswith("0x") or len(raw)!=66:
        raise BoundaryError("branch_b_cost_transaction_identity")
    try:
        int(raw,16)
    except ValueError:
        raise BoundaryError("branch_b_cost_transaction_identity") from None
    return raw


def _indexed_candidates(*,gql_fn=gql,limit=INDEX_LIMIT_PER_EVENT):
    if type(limit) is not int or not 1<=limit<=256:
        raise BoundaryError("branch_b_cost_index_limit")
    out=[]
    for root,event_name,category in EVENT_SOURCES:
        query=f"""query($limit:Int!){{{root}(
          limit:$limit,where:{{chainId:{{_eq:{CHAIN}}}}},
          order_by:{{timestamp:desc}}){{transaction pool timestamp}}
        }}"""
        rows=(gql_fn(query,{"limit":limit}) or {}).get(root) or []
        seen=set()
        for row in rows:
            try:
                tx=_txhash(row.get("transaction"))
            except BoundaryError:
                continue
            pool=addr(row.get("pool"))
            if not pool or tx in seen:
                continue
            seen.add(tx)
            out.append(dict(
                root=root,event_name=event_name,category=category,
                transaction_hash=tx,pool=pool,
                indexed_timestamp=int(row.get("timestamp") or 0),
            ))
    return out


def _verified_historical_cost_events(
    rpc, factory_addresses, finalized_block, *, gql_fn=gql,
):
    """Return canonical Ramses economic events plus seeded receipt gas state."""
    allowed={str(a).lower() for a in factory_addresses}
    candidates=[
        row for row in _indexed_candidates(gql_fn=gql_fn)
        if row["pool"].lower() in allowed
    ]
    by_tx=defaultdict(list)
    for row in candidates:
        by_tx[row["transaction_hash"]].append(row)
    txs=sorted(by_tx)
    if not txs:
        return [],{},dict(
            indexed_candidates=0,verified_events=0,verified_transactions=0,
            rejected={"no_indexed_candidates":1},
        )

    receipts=[]
    for first in range(0,len(txs),16):
        receipts.extend(rpc.batch(
            [("eth_getTransactionReceipt",[tx]) for tx in txs[first:first+16]],
            scope="branch_b_cost_history_receipts",
        ))
    receipt_by_tx={tx:receipt for tx,receipt in zip(txs,receipts)}

    block_numbers=[]
    for receipt in receipts:
        if not isinstance(receipt,dict) or not receipt.get("blockNumber"):
            continue
        try:
            block_numbers.append(int(receipt["blockNumber"],16))
        except (TypeError,ValueError):
            continue
    headers=rpc.blocks(sorted(set(block_numbers)),scope="branch_b_cost_history_headers")
    header_by_number={int(h["number"],16):h for h in headers}

    abi=load("ramses_pool_implementation")["abi"]
    verified=[]
    transactions={}
    rejected=Counter()
    accepted_by_category=Counter()
    accepted_txs_by_category=defaultdict(set)

    for tx in txs:
        receipt=receipt_by_tx.get(tx)
        if not isinstance(receipt,dict):
            rejected["missing_receipt"]+=1;continue
        try:
            status=int(receipt.get("status","0x0"),16)
            block=int(receipt["blockNumber"],16)
            gas_used=int(receipt["gasUsed"],16)
        except (KeyError,TypeError,ValueError):
            rejected["malformed_receipt"]+=1;continue
        if status!=1 or gas_used<=0:
            rejected["failed_or_zero_gas_receipt"]+=1;continue
        if block>int(finalized_block):
            rejected["not_finalized_at_anchor"]+=1;continue
        header=header_by_number.get(block)
        if not header or header.get("hash")!=receipt.get("blockHash"):
            rejected["canonical_header_mismatch"]+=1;continue
        if receipt.get("transactionHash","").lower()!=tx:
            rejected["receipt_transaction_mismatch"]+=1;continue

        tx_events=[]
        for cand in by_tx[tx]:
            matched=False
            for event in receipt.get("logs") or []:
                if event.get("removed") or event.get("address","").lower()!=cand["pool"].lower():
                    continue
                if event.get("blockHash")!=receipt.get("blockHash"):
                    continue
                if event.get("transactionHash","").lower()!=tx:
                    continue
                try:
                    decoded=decode_ramses_event(abi,event)
                except BoundaryError:
                    continue
                if decoded["name"]==cand["event_name"]:
                    matched=True
                    break
            if not matched:
                rejected["indexed_event_not_in_canonical_receipt"]+=1
                continue
            tx_events.append(dict(
                pool=cand["pool"],category=cand["category"],block=block,
                block_hash=receipt["blockHash"],transaction_hash=tx,
            ))
            accepted_by_category[cand["category"]]+=1
            accepted_txs_by_category[cand["category"]].add(tx)

        if not tx_events:
            continue
        transactions[tx]=dict(
            block_hash=receipt["blockHash"],gas_used=gas_used,
        )
        verified.extend(tx_events)

    state={"transactions":transactions}
    if verified:
        observe_receipt_gas(rpc,verified,state)
    meta=dict(
        indexed_candidates=len(candidates),
        indexed_transactions=len(txs),
        verified_events=len(verified),
        verified_transactions=len(transactions),
        verified_events_by_category=dict(accepted_by_category),
        verified_transactions_by_category={
            k:len(v) for k,v in accepted_txs_by_category.items()
        },
        rejected=dict(rejected),
        acquisition=(
            "bounded indexed Ramses economic identities; canonical receipt/header "
            "and Ramses ABI event reauthentication before gasUsed admission"
        ),
    )
    return verified,state,meta


def main():
    endpoint=os.environ.get("MM_ROBINHOOD_DLMM_RPC_URL") or os.environ.get("MM_ROBINHOOD_READ_RPC_URL") or ""
    rpc=BoundedMultiRpc(
        endpoint,max_sessions=80,batch_size=16,batch_pause=.30,
        rate_retries=3,rate_cooldown=6.0,adaptive_batch_floor=2,
    )
    rpc.verify_chain()
    frontier=rpc.call("eth_getBlockByNumber",["finalized",False],scope="branch_b_cost")
    end=int(frontier["number"],16)
    factory_pin=load("ramses_factory")
    factory=factory_pin["address"]
    code=rpc.call("eth_getCode",[factory,hex(end)],scope="branch_b_cost")
    identity=authenticate("ramses_factory",factory,code)
    addresses=_enumerate_factory(
        rpc,factory,end,factory_runtime_sha256=identity["runtime_sha256"]
    )

    cost_events,state,acquisition=_verified_historical_cost_events(
        rpc,addresses,end,
    )
    native,meta=current_native_cycle(rpc,state)
    if native is None:
        raise RuntimeError(
            "branch_b_cost_anchor_unavailable:"
            +json.dumps(acquisition,sort_keys=True,separators=(",",":"))
        )

    samples=state.get("samples") or {}
    body=dict(
        kind="ramses_branch_b_cost_anchor_v1",
        frozen=True,
        research_only=True,
        strategy_parameters_changed=False,
        cost_model_changed=False,
        cost_model_version=meta.get("model_version"),
        finalized_block=end,
        finalized_hash=frontier["hash"],
        finalized_timestamp=int(frontier["timestamp"],16),
        factory_pool_count=len(addresses),
        acquisition_source="verified_historical_ramses_receipts",
        acquisition=acquisition,
        economic_events=len(cost_events),
        economic_transactions=len(state.get("transactions") or {}),
        gas_sample_counts={k:len(v) for k,v in samples.items()},
        native_costs={k:int(v) for k,v in native.items()},
        native_cycle_cost_raw=sum(int(v) for v in native.values()),
        model=meta,
        provider=rpc.telemetry(),
    )
    OUT.write_text(json.dumps(body,indent=2,sort_keys=True))
    print(json.dumps({
        "kind":body["kind"],
        "finalized_block":body["finalized_block"],
        "economic_transactions":body["economic_transactions"],
        "gas_sample_counts":body["gas_sample_counts"],
        "native_cycle_cost_raw":body["native_cycle_cost_raw"],
        "proxy_categories":body["model"].get("proxy_categories"),
    },sort_keys=True))

if __name__=="__main__":
    main()
