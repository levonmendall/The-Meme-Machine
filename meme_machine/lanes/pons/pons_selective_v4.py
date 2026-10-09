"""Uniswap V4 continuation evidence for Pons Selective Continuation v1.

The Pons strategy owns these measurements.  No other strategy cohort or wallet score
is read.  V4 activity is authenticated from PoolManager Swap logs plus transaction
senders and reduced to a strategy-local second-wave demand vector.
"""
from collections import defaultdict
import time

from . import BoundaryError
from .abi import signature, topic
from .identity import metadata as load
from .pons import raw_event
from .pons_selective_acquisition import _batched, SelectiveEvidenceContext
from .log_windows import LogWindows,CheckpointHints


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


def acquisition_windows(endpoint, pool_ids, state=None,*,batch_elements=4):
    return LogWindows(endpoint, dict(address=load('uniswap_v4_manager')['address'].lower(),
        topics=[_event_topic('uniswap_v4_manager','Swap'),list(pool_ids)]),state=state,batch_elements=batch_elements)


def _transport(endpoint,*,pool_ids,start_block,end_block,max_events,acquisition_state=None,evidence_context=None,log_batch_elements=4):
    manager=load("uniswap_v4_manager")["address"].lower()
    # One range planner serves both strategies. Wider queries require an exact
    # credential/filter comparison; unverified endpoints retain ten blocks.
    raw=[];sessions=[]
    context=evidence_context() if callable(evidence_context) else evidence_context
    context=context or SelectiveEvidenceContext(endpoint)
    from meme_machine.runtime.robinhood.provider_authority import reference
    if context.endpoint!=reference(endpoint):raise BoundaryError('selective_v4_provider_context_disagreement')
    # A long-lived context shares only immutable hash/receipt facts. Numeric
    # membership is reacquired on every range, including quiet markets and forks.
    context.cache.headers_by_number.clear()
    context.receipt_pins={};context.timing={}
    def acquire(calls):
        return _batched(endpoint,calls,'pons_selective_v4',evidence_context=context)[0]
    windows=acquisition_windows(endpoint,pool_ids,acquisition_state,batch_elements=log_batch_elements)
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
    tx_rows=list(dict.fromkeys(
        (event["transactionHash"],event["blockHash"]) for event in raw
    ))
    context.receipt_pins=dict(tx_rows)
    # Canonical membership must succeed before receipt acquisition. An orphan
    # economic block must neither authorize evidence nor purchase receipt work.
    previous_force=context.canonical_numbers;context.canonical_numbers=True
    try:
        headers_v=acquire([("eth_getBlockByNumber",[hex(n),False]) for n,_ in blocks])
    finally:context.canonical_numbers=previous_force
    if any(header.get('hash')!=h or int(header['number'],16)!=n for (n,h),header in zip(blocks,headers_v)):
        raise BoundaryError('selective_v4_canonical_header_membership')
    hashes=[h for _,h in blocks]
    headers=dict(zip(hashes,headers_v))
    # The existing dense selector must see fresh authenticated canonical headers.
    # Unknown capability/resource limits retain the original individual graph.
    dense=context.acquire_dense_receipts(tx_rows,headers=headers,scope='pons_selective_v4')
    individual=[pair for pair in tx_rows if pair not in dense]
    fetched=dict(zip(individual,acquire([("eth_getTransactionReceipt",[tx]) for tx,_ in individual])))
    receipts_v=[dense[pair] if pair in dense else fetched[pair] for pair in tx_rows]
    # Authenticated standard receipts carry the transaction sender. Keep the
    # original transaction-body path for providers/captures missing that field.
    senders={k:context.block_reads.get(('authenticated_v4_sender',*k)) for k in tx_rows}
    missing=[(tx,bh) for (tx,bh),r in zip(tx_rows,receipts_v) if not r.get('from') and not senders[(tx,bh)]]
    txs_v=acquire([("eth_getTransactionByHash",[tx]) for tx,_ in missing])
    fallback=dict(zip(missing,txs_v))
    receipts={};txs={}
    for keyrow,receipt in zip(tx_rows,receipts_v):
        tx,bh=keyrow
        sender=receipt.get('from')
        if sender and (not isinstance(sender,str) or len(sender)!=42 or
                not sender.startswith('0x') or any(c not in '0123456789abcdef' for c in sender[2:].lower())):
            raise BoundaryError('selective_v4_receipt_sender_identity')
        txrow=(fallback[keyrow] if not sender and not senders[keyrow]
            else dict(hash=tx,blockHash=bh,**{'from':sender or senders[keyrow]}))
        sender=txrow.get('from')
        if (not isinstance(sender,str) or len(sender)!=42 or not sender.startswith('0x')
                or any(c not in '0123456789abcdef' for c in sender[2:].lower())):
            raise BoundaryError('selective_v4_transaction_sender_identity')
        if receipt["transactionHash"]!=tx or receipt["blockHash"]!=bh:
            raise BoundaryError("selective_v4_receipt_identity")
        if txrow["hash"]!=tx or txrow["blockHash"]!=bh:
            raise BoundaryError("selective_v4_transaction_identity")
        receipts[keyrow]=receipt;txs[keyrow]=txrow

    telemetry=context.telemetry()
    sessions=list(telemetry['completed_sessions'])
    if telemetry['current_session']:sessions.append(telemetry['current_session'])
    if sessions:sessions[-1]=dict(sessions[-1],log_windows=windows.telemetry())
    return dict(raw=raw,sessions=sessions,headers=headers,receipts=receipts,txs=txs,context=context)


def collect_v4_activity(
    endpoint,*,pool_id,key,token,start_block,end_block,
    preholder_groups=(),max_events=256,_shared=None,acquisition_state=None,evidence_context=None,log_batch_elements=4,
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
        acquisition_state=acquisition_state,evidence_context=evidence_context,log_batch_elements=log_batch_elements)
    raw=[e for e in shared['raw'] if e['topics'][1]==pool_id]
    sessions=shared['sessions'];headers=shared['headers'];receipts=shared['receipts'];txs=shared['txs']

    preholders={str(x).lower() for x in preholder_groups}
    token=str(token).lower()
    token_is_0=token==key.currency0.lower()
    token_is_1=token==key.currency1.lower()
    if token_is_0==token_is_1:
        raise BoundaryError("selective_v4_token_currency_identity")

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
        elif token_delta>0 and quote_delta<0:
            side="sell";quote=-quote_delta;tokens=token_delta
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

    # Publish optional immutable cache facts only after every required native
    # receipt/header/ABI/sender check succeeds. Fresh numeric membership remains
    # mandatory even on cache hits; old orphan bodies grant no range authority.
    context=shared.get('context')
    if context is not None:
        used={(event['transactionHash'],event['blockHash']) for event in raw}
        for bh in {bh for _,bh in used}:
            header=headers[bh];old=context.cache.header_by_number(int(header['number'],16))
            if old and old['hash']!=header['hash']:context.cache.invalidate_canonical_aliases()
            context.cache.remember_header(header)
        for tx,bh in used:
            receipt=receipts[(tx,bh)]
            context.cache.remember_receipt(tx,bh,receipt)
            context.block_reads[('authenticated_v4_sender',tx,bh)]=txs[(tx,bh)]['from']
            while len(context.block_reads)>4096:context.block_reads.popitem(last=False)
    return activity_summary(rows,preholder_groups=preholder_groups,provider_sessions=sessions)


def activity_summary(rows,*,preholder_groups=(),provider_sessions=()):
    """Reduce the same authenticated swaps, including durable Current history."""
    preholders={str(x).lower() for x in preholder_groups}
    buyer_flow=defaultdict(int);buyers=set();buy_quote=sell_quote=preholder_sell=0
    for row in rows:
        group=row['group'];quote=row['quote']
        if row['side']=='buy':
            buyers.add(group);buyer_flow[group]+=quote;buy_quote+=quote
        else:
            sell_quote+=quote
            if group in preholders:preholder_sell+=quote
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
        provider_sessions=list(provider_sessions),
    )


def rolling_position_activity(endpoint,*,rpc,history,pool_id,key,token,header,seconds=15,preholder_groups=()):
    """Existing Current history, fresh membership, and only the uncovered tail.

    The native quote supplies the authenticated current frontier. The previous
    frontier must still be canonical before any old event can influence risk.
    No time search, event or numeric alias can substitute for those witnesses.
    """
    from .pons_quotes import canonical_boundary
    from .pons_selective_acquisition import _header_search
    block=int(header['number'],16);at=int(header['timestamp'],16)
    old=history.get(pool_id)
    if old:
        try:canonical_boundary(rpc,dict(number=hex(old['block']),hash=old['block_hash']),'pons_selective_v4')
        except BoundaryError:
            history.invalidate(pool_id,'v4_position_canonical_membership_failure')
            history.v4_header_cache={};raise
        if block<old['block']:raise BoundaryError('pons_current_history_frontier_regression')
    cutoff=max(0,at-seconds)
    complete=old is not None and old['from_time']<=cutoff<=old['through']
    context=getattr(history,'v4_evidence_context',None)
    if context is None:
        context=SelectiveEvidenceContext(endpoint);history.v4_evidence_context=context
    if complete:
        first=old['block']+1;lower=old['from_time']
        retained=history.v4_window_candidates(pool_id,cutoff)
    else:
        # Cold/incomplete history still purchases the original bounded search.
        headers=dict(getattr(history,'v4_header_cache',{})) if old else {}
        headers[block]=header
        first_header=_header_search(rpc,block,at,cutoff,headers)
        history.v4_header_cache={n:h for n,h in sorted(headers.items())[-256:]}
        first=int(first_header['number'],16);lower=int(first_header['timestamp'],16)
        retained=[]
    tape=collect_v4_activity(endpoint,pool_id=pool_id,key=key,token=token,
        start_block=first,end_block=block,preholder_groups=preholder_groups,
        acquisition_state=CheckpointHints(history.plane),evidence_context=context,log_batch_elements=5)
    events=[dict(row,canonical_order=[row['block'],row['transaction_index'],row['log_index']]) for row in tape['swaps']]
    candidates=retained+events
    if complete:
        # F = last block with timestamp <= cutoff. Only the LAST economic block
        # <= cutoff can equal F. Its successor proves inclusion/exclusion with
        # one header, regardless of the number of intervening empty blocks.
        older=[e for e in candidates if e['event_at']<=cutoff]
        boundary=max((e['block'] for e in older),default=None)
        include_boundary=boundary==block
        if boundary is not None and boundary<block:
            previous_pins=getattr(rpc,'evidence_pins',{});rpc.evidence_pins={}
            try:successor=rpc.call('eth_getBlockByNumber',[hex(boundary+1),False],scope='pons_selective_v4')
            finally:rpc.evidence_pins=previous_pins
            if (not isinstance(successor,dict) or int(successor['number'],16)!=boundary+1
                    or not successor.get('hash')):raise BoundaryError('pons_current_history_successor_identity')
            successor_at=int(successor['timestamp'],16)
            if not max(e['event_at'] for e in older)<=successor_at<=at:
                raise BoundaryError('pons_current_history_successor_timestamp')
            include_boundary=successor_at>cutoff
        candidates=[e for e in candidates if e['event_at']>cutoff or
            (include_boundary and e['block']==boundary)]
    else:
        candidates=[e for e in candidates if e['block']>=first]
    # A fork during acquisition cannot publish a complete interval. Fencing the
    # old and new boundary also makes immutable receipt reuse safe on restart.
    expected={block:header['hash']}
    if old:expected[old['block']]=old['block_hash']
    previous_pins=getattr(rpc,'evidence_pins',{});rpc.evidence_pins={}
    try:members=rpc.batch([('eth_getBlockByNumber',[hex(n),False]) for n in expected],scope='pons_selective_v4')
    finally:rpc.evidence_pins=previous_pins
    if (not isinstance(members,list) or len(members)!=len(expected) or any(not isinstance(h,dict) or int(h['number'],16)!=n or h['hash']!=bh
            for (n,bh),h in zip(expected.items(),members))):
        raise BoundaryError('pons_quote_canonical_membership_disagreement')
    if history.get(pool_id)!=old:raise BoundaryError('pons_current_history_frontier_superseded')
    # The successful range acquisition and fresh old/new membership witnesses
    # are history authority. An isolated quote cannot create this checkpoint.
    from meme_machine.runtime.journal import digest
    coverage=dict(first_block=first,last_block=block,end_hash=header['hash'],
        previous_checkpoint_hash=digest(old) if old else None,
        events_sha256=digest(events),event_count=len(events),
        kind='already_complete_no_delta' if first>block else 'authenticated_complete_log_interval',
        empty_interval=not events)
    retain_ids=tuple(e['identity'] for e in candidates if e['event_at']<at-900)
    history.remember(pool_id,header,events,from_time=lower,delta_from=old['block'] if complete else None,
        coverage=coverage,retain_ids=retain_ids)
    # canonical_order is the durable history's sorting metadata; consumers see
    # exactly the original authenticated trade shape and economic inputs.
    rows=[{k:v for k,v in e.items() if k!='canonical_order'} for e in
        sorted(candidates,key=lambda e:tuple(e['canonical_order']))]
    return activity_summary(rows,preholder_groups=preholder_groups,
        provider_sessions=tape['provider_sessions'])


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
