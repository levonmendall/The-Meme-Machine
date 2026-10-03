"""Uniswap V4 continuation evidence for Pons Selective Continuation v1.

The Pons strategy owns these measurements.  No other strategy cohort or wallet score
is read.  V4 activity is authenticated from PoolManager Swap logs plus transaction
senders and reduced to a strategy-local second-wave demand vector.
"""
from collections import defaultdict
import time

from . import BoundaryError
from .abi import signature, topic
from .identity import load
from .pons import raw_event
from .pons_selective_acquisition import _batched


def _event_topic(role,name):
    abi=load(role)["abi"]
    rows=[x for x in abi if x.get("type")=="event" and x.get("name")==name]
    if len(rows)!=1:
        raise BoundaryError("selective_v4_event_abi")
    return topic(signature(rows[0]))


def _pool_topic(pool_id):
    value=str(pool_id).lower()
    if not value.startswith("0x") or len(value)!=66:
        raise BoundaryError("invalid_v4_pool_id")
    return value


def _signed(value,bits=128):
    value=int(value)
    limit=1<<bits
    if value>=limit:
        raise BoundaryError("v4_signed_width")
    if value>=(1<<(bits-1)):
        value-=limit
    return value


def _transport(endpoint,*,pool_ids,start_block,end_block,max_events):
    manager=load("uniswap_v4_manager")["address"].lower()
    # Each logical request retains the canonical ten-block range bound.
    raw=[];sessions=[]
    calls=[("eth_getLogs",[dict(
        fromBlock=hex(first),toBlock=hex(min(int(end_block),first+9)),
        address=manager,topics=[_event_topic("uniswap_v4_manager","Swap"),list(pool_ids)],
    )]) for first in range(int(start_block),int(end_block)+1,10)]
    # Bound physical batches too; the canonical context owns rate admission.
    for offset in range(0,len(calls),4):
        values,telem=_batched(endpoint,calls[offset:offset+4],"pons_selective_v4")
        sessions.extend(telem)
        for value in values:raw.extend(value)
        if len(raw)>int(max_events):raise BoundaryError("selective_v4_event_capacity")
    for event in raw:
        if (event.get('address','').lower()!=manager or len(event.get('topics',[]))<2
                or event['topics'][1] not in pool_ids
                or not int(start_block)<=int(event['blockNumber'],16)<=int(end_block)):
            raise BoundaryError('selective_v4_range_or_pool_identity')
    raw.sort(key=lambda e:(int(e['blockNumber'],16),int(e['transactionIndex'],16),int(e['logIndex'],16)))
    hashes=list(dict.fromkeys(event["blockHash"] for event in raw))
    headers_v,telem=_batched(
        endpoint,[("eth_getBlockByHash",[h,False]) for h in hashes],"pons_selective_v4"
    )
    sessions.extend(telem);headers=dict(zip(hashes,headers_v))
    tx_rows=list(dict.fromkeys(
        (event["transactionHash"],event["blockHash"]) for event in raw
    ))
    receipts_v,telem=_batched(
        endpoint,[("eth_getTransactionReceipt",[tx]) for tx,_ in tx_rows],"pons_selective_v4"
    )
    sessions.extend(telem)
    txs_v,telem=_batched(
        endpoint,[("eth_getTransactionByHash",[tx]) for tx,_ in tx_rows],"pons_selective_v4"
    )
    sessions.extend(telem)
    receipts={};txs={}
    for keyrow,receipt,txrow in zip(tx_rows,receipts_v,txs_v):
        tx,bh=keyrow
        if receipt["transactionHash"]!=tx or receipt["blockHash"]!=bh:
            raise BoundaryError("selective_v4_receipt_identity")
        if txrow["hash"]!=tx or txrow["blockHash"]!=bh:
            raise BoundaryError("selective_v4_transaction_identity")
        receipts[keyrow]=receipt;txs[keyrow]=txrow

    return dict(raw=raw,sessions=sessions,headers=headers,receipts=receipts,txs=txs)


def collect_v4_activity(
    endpoint,*,pool_id,key,token,start_block,end_block,
    preholder_groups=(),max_events=256,_shared=None,
):
    manager=load("uniswap_v4_manager")["address"].lower()
    if int(end_block)<int(start_block):
        return dict(
            swaps=[],new_independent_buyers=0,buy_quote=0,sell_quote=0,net_quote=0,
            preholder_sell_quote=0,largest_buyer_flow_bps=0,buyer_groups=[],
            price_indices=[],last_price_index=None,high_price_index=None,
            low_price_index=None,provider_sessions=[],
        )

    shared=_shared or _transport(endpoint,pool_ids=[_pool_topic(pool_id)],
        start_block=start_block,end_block=end_block,max_events=max_events)
    raw=[e for e in shared['raw'] if e['topics'][1]==pool_id]
    if len(raw)>int(max_events):raise BoundaryError("selective_v4_event_capacity")
    sessions=shared['sessions'];headers=shared['headers'];receipts=shared['receipts'];txs=shared['txs']

    preholders={str(x).lower() for x in preholder_groups}
    token=str(token).lower()
    token_is_0=token==key.currency0.lower()
    token_is_1=token==key.currency1.lower()
    if token_is_0==token_is_1:
        raise BoundaryError("selective_v4_token_currency_identity")

    buyer_flow=defaultdict(int)
    buyers=set();buy_quote=sell_quote=preholder_sell=0
    rows=[];observed=int(time.time())
    for event in raw:
        bh=event["blockHash"];tx=event["transactionHash"]
        row=raw_event(
            load("uniswap_v4_manager")["abi"],event,address=manager,
            receipt=receipts[(tx,bh)],header=headers[bh],
            observed_at=observed,confirmation="confirmed",
        )
        if row["decoded"]["name"]!="Swap":
            raise BoundaryError("selective_v4_non_swap")
        args=row["decoded"]["args"]
        amount0=_signed(args["amount0"]);amount1=_signed(args["amount1"])
        token_delta=amount0 if token_is_0 else amount1
        quote_delta=amount1 if token_is_0 else amount0
        group=str(txs[(tx,bh)].get("from","")).lower()
        if not group:
            raise BoundaryError("selective_v4_sender_missing")
        if token_delta<0 and quote_delta>0:
            side="buy";quote=quote_delta;tokens=-token_delta
            buyers.add(group);buyer_flow[group]+=quote;buy_quote+=quote
        elif token_delta>0 and quote_delta<0:
            side="sell";quote=-quote_delta;tokens=token_delta
            sell_quote+=quote
            if group in preholders:
                preholder_sell+=quote
        else:
            raise BoundaryError("selective_v4_swap_direction")
        sqrt_price=int(args["sqrtPriceX96"])
        if sqrt_price<=0:
            raise BoundaryError("selective_v4_invalid_price")
        q192=1<<192
        price_index=(
            sqrt_price*sqrt_price*10**18//q192
            if token_is_0 else
            q192*10**18//(sqrt_price*sqrt_price)
        )
        rows.append(dict(
            identity=f'{row["block"]}:{tx}:{row["log_index"]}',
            block=row["block"],event_at=row["event_at"],group=group,
            side=side,quote=int(quote),tokens=int(tokens),
            sqrt_price_x96=sqrt_price,price_index=price_index,
        ))

    total_buy=sum(buyer_flow.values())
    largest=(
        0 if total_buy==0 else max(buyer_flow.values())*10_000//total_buy
    )
    new_buyers=sorted(group for group in buyers if group not in preholders)
    return dict(
        swaps=rows,new_independent_buyers=len(new_buyers),
        new_independent_buyer_groups=new_buyers,
        buy_quote=buy_quote,sell_quote=sell_quote,
        net_quote=buy_quote-sell_quote,
        preholder_sell_quote=preholder_sell,
        largest_buyer_flow_bps=largest,
        buyer_groups=sorted(buyers),
        price_indices=[row["price_index"] for row in rows],
        last_price_index=(None if not rows else rows[-1]["price_index"]),
        high_price_index=(None if not rows else max(row["price_index"] for row in rows)),
        low_price_index=(None if not rows else min(row["price_index"] for row in rows)),
        provider_sessions=sessions,
    )


def collect_v4_activities(endpoint,*,markets,start_block,end_block,max_events=256):
    """One authenticated bounded range for at most 64 independent markets.

    Shared transport does not share candidate populations: each result traverses
    the same native receipt/ABI/transaction-sender authentication and pool filter.
    """
    if not markets or len(markets)>64 or not 0<=end_block-start_block<40:
        raise BoundaryError('survivor_shared_range_bound')
    ids=[_pool_topic(m['pool_id']) for m in markets]
    if len(set(ids))!=len(ids):raise BoundaryError('survivor_duplicate_pool')
    shared=_transport(endpoint,pool_ids=ids,start_block=start_block,end_block=end_block,
        max_events=max_events*len(markets))
    return {m['token']:collect_v4_activity(endpoint,**m,start_block=start_block,
        end_block=end_block,max_events=max_events,_shared=shared) for m in markets}
