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
from .pons_selective_acquisition import _batched, SelectiveEvidenceContext
from .log_windows import LogWindows


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


def acquisition_windows(endpoint, pool_ids, state=None):
    return LogWindows(endpoint, dict(address=load('uniswap_v4_manager')['address'].lower(),
        topics=[_event_topic('uniswap_v4_manager','Swap'),list(pool_ids)]),state=state)


def _transport(endpoint,*,pool_ids,start_block,end_block,max_events,acquisition_state=None):
    manager=load("uniswap_v4_manager")["address"].lower()
    # One range planner serves both strategies. Wider queries require an exact
    # credential/filter comparison; unverified endpoints retain ten blocks.
    raw=[];sessions=[]
    context=SelectiveEvidenceContext(endpoint)
    def acquire(calls):
        return _batched(endpoint,calls,'pons_selective_v4',evidence_context=context)[0]
    windows=acquisition_windows(endpoint,pool_ids,acquisition_state)
    raw=windows.read(int(start_block),int(end_block),acquire)
    for event in raw:
        if (event.get('address','').lower()!=manager or len(event.get('topics',[]))<2
                or event['topics'][1] not in pool_ids
                or not int(start_block)<=int(event['blockNumber'],16)<=int(end_block)):
            raise BoundaryError('selective_v4_range_or_pool_identity')
    raw.sort(key=lambda e:(int(e['blockNumber'],16),int(e['transactionIndex'],16),int(e['logIndex'],16)))
    blocks=list(dict.fromkeys((int(event['blockNumber'],16),event['blockHash']) for event in raw))
    # Hash bodies can survive a reorganization in the immutable cache. Numeric
    # reads establish current canonical membership for every economic block.
    headers_v=acquire([("eth_getBlockByNumber",[hex(n),False]) for n,_ in blocks])
    if any(header.get('hash')!=h or int(header['number'],16)!=n for (n,h),header in zip(blocks,headers_v)):
        raise BoundaryError('selective_v4_canonical_header_membership')
    hashes=[h for _,h in blocks]
    headers=dict(zip(hashes,headers_v))
    tx_rows=list(dict.fromkeys(
        (event["transactionHash"],event["blockHash"]) for event in raw
    ))
    context.receipt_pins=dict(tx_rows)
    receipts_v=acquire([("eth_getTransactionReceipt",[tx]) for tx,_ in tx_rows])
    # Authenticated standard receipts carry the transaction sender. Keep the
    # original transaction-body path for providers/captures missing that field.
    missing=[(tx,bh) for (tx,bh),r in zip(tx_rows,receipts_v) if not r.get('from')]
    txs_v=acquire([("eth_getTransactionByHash",[tx]) for tx,_ in missing])
    fallback=dict(zip(missing,txs_v))
    receipts={};txs={}
    for keyrow,receipt in zip(tx_rows,receipts_v):
        tx,bh=keyrow
        sender=receipt.get('from')
        if sender and (not isinstance(sender,str) or len(sender)!=42 or
                not sender.startswith('0x') or any(c not in '0123456789abcdef' for c in sender[2:].lower())):
            raise BoundaryError('selective_v4_receipt_sender_identity')
        txrow=fallback[keyrow] if not sender else dict(hash=tx,blockHash=bh,**{'from':sender})
        if receipt["transactionHash"]!=tx or receipt["blockHash"]!=bh:
            raise BoundaryError("selective_v4_receipt_identity")
        if txrow["hash"]!=tx or txrow["blockHash"]!=bh:
            raise BoundaryError("selective_v4_transaction_identity")
        receipts[keyrow]=receipt;txs[keyrow]=txrow

    telemetry=context.telemetry()
    sessions=list(telemetry['completed_sessions'])
    if telemetry['current_session']:sessions.append(telemetry['current_session'])
    if sessions:sessions[-1]=dict(sessions[-1],log_windows=windows.telemetry())
    return dict(raw=raw,sessions=sessions,headers=headers,receipts=receipts,txs=txs)


def collect_v4_activity(
    endpoint,*,pool_id,key,token,start_block,end_block,
    preholder_groups=(),max_events=256,_shared=None,acquisition_state=None,
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
        start_block=start_block,end_block=end_block,max_events=max_events,
        acquisition_state=acquisition_state)
    raw=[e for e in shared['raw'] if e['topics'][1]==pool_id]
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
            transaction_index=int(event['transactionIndex'],16),log_index=row['log_index'],
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


def collect_v4_activities(endpoint,*,markets,start_block,end_block,max_events=256,acquisition_state=None):
    """One authenticated bounded range for at most 64 independent markets.

    Shared transport does not share candidate populations: each result traverses
    the same native receipt/ABI/transaction-sender authentication and pool filter.
    """
    if not markets or len(markets)>64:
        raise BoundaryError('survivor_shared_range_bound')
    ids=[_pool_topic(m['pool_id']) for m in markets]
    if len(set(ids))!=len(ids):raise BoundaryError('survivor_duplicate_pool')
    windows=acquisition_windows(endpoint,ids,acquisition_state)
    if not 0<=end_block-start_block<min(160,4*windows.ceiling):
        raise BoundaryError('survivor_shared_range_bound')
    shared=_transport(endpoint,pool_ids=ids,start_block=start_block,end_block=end_block,
        max_events=max_events*len(markets),acquisition_state=acquisition_state)
    return {m['token']:collect_v4_activity(endpoint,**m,start_block=start_block,
        end_block=end_block,max_events=max_events,_shared=shared) for m in markets}
