"""Independent live evidence acquisition for Pons Selective Continuation v1.

This module does not import any other strategy or cohort.  It reuses only neutral
Robinhood/Pons transport, ABI, protocol-authentication and evidence primitives.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import asdict
import time
import json
import os
from pathlib import Path
import hashlib

from . import BoundaryError
from .abi import calldata
from .pons import curve_abi, raw_event
from .pons_natural_observation import (
    RESEARCH_RECIPIENT, _authenticate_candidate, _one_word,
)
from .provider_topology import configured_rpc
from .provider_admission import foreground_work, decision_work
from .pons_selective_continuation import (
    ENTRY_THRESHOLDS, curve_progress_bps, normalized_trade, qualification_vector,
    trajectory_metrics,
)

HEADER_BATCH=50
RECEIPT_BATCH=50
MAX_TRAJECTORY_LOOKBACK_BLOCKS=8192
CACHE_HEADERS=4096
INDEX_NEIGHBORHOOD=32
CACHE_RECEIPTS=8192
CACHE_LAUNCHES=4096
EVIDENCE_SESSION_ROTATE_AT=180


class ImmutableEvidenceCache:
    """Bounded cross-candidate cache for already authenticated immutable evidence."""

    def __init__(self):
        self.headers_by_hash=OrderedDict()
        self.headers_by_number=OrderedDict()
        self.receipts=OrderedDict()
        self.launch_at=OrderedDict()
        self.real_quote=OrderedDict()
        self.counts=Counter()

    @staticmethod
    def _remember(store,key,value,limit,conflict):
        old=store.get(key)
        if old is not None:
            if old!=value:
                raise BoundaryError(conflict)
            store.move_to_end(key)
            return False
        store[key]=value
        while len(store)>int(limit):
            store.popitem(last=False)
        return True

    def header_by_hash(self,block_hash):
        row=self.headers_by_hash.get(str(block_hash))
        self.counts["header_hash_hit" if row is not None else "header_hash_miss"]+=1
        return row

    def header_by_number(self,block):
        row=self.headers_by_number.get(int(block))
        self.counts["header_number_hit" if row is not None else "header_number_miss"]+=1
        return row

    def remember_header(self,header):
        if not isinstance(header,dict) or not header.get("hash") or header.get("number") is None:
            raise BoundaryError("selective_cached_header_shape")
        number=int(header["number"],16)
        block_hash=str(header["hash"])
        old_hash=self.headers_by_hash.get(block_hash)
        old_number=self.headers_by_number.get(number)
        if old_hash is not None and old_hash!=header:
            raise BoundaryError("selective_cached_header_hash_conflict")
        if old_number is not None and old_number.get("hash")!=block_hash:
            raise BoundaryError("selective_cached_header_number_conflict")
        self._remember(
            self.headers_by_hash,block_hash,header,CACHE_HEADERS,
            "selective_cached_header_hash_conflict",
        )
        self._remember(
            self.headers_by_number,number,header,CACHE_HEADERS,
            "selective_cached_header_number_conflict",
        )
        self.counts["header_store"]+=1
        return header

    def receipt(self,tx,block_hash):
        key=(str(tx),str(block_hash))
        row=self.receipts.get(key)
        self.counts["receipt_hit" if row is not None else "receipt_miss"]+=1
        return row

    def remember_receipt(self,tx,block_hash,receipt):
        if (
            not isinstance(receipt,dict)
            or receipt.get("transactionHash")!=tx
            or receipt.get("blockHash")!=block_hash
        ):
            raise BoundaryError("selective_cached_receipt_identity")
        self._remember(
            self.receipts,(str(tx),str(block_hash)),receipt,CACHE_RECEIPTS,
            "selective_cached_receipt_conflict",
        )
        self.counts["receipt_store"]+=1
        return receipt

    def launch(self,curve):
        key=str(curve).lower()
        value=self.launch_at.get(key)
        self.counts["launch_hit" if value is not None else "launch_miss"]+=1
        return value

    def remember_launch(self,curve,value):
        key=str(curve).lower();value=int(value)
        self._remember(
            self.launch_at,key,value,CACHE_LAUNCHES,
            "selective_cached_launch_conflict",
        )
        self.counts["launch_store"]+=1
        return value

    def real_quote_at(self,curve,block):
        key=(str(curve).lower(),int(block))
        value=self.real_quote.get(key)
        self.counts["real_quote_hit" if value is not None else "real_quote_miss"]+=1
        return value

    def remember_real_quote(self,curve,block,value):
        key=(str(curve).lower(),int(block));value=int(value)
        self._remember(
            self.real_quote,key,value,CACHE_HEADERS,
            "selective_cached_real_quote_conflict",
        )
        self.counts["real_quote_store"]+=1
        return value

    def telemetry(self):
        return dict(
            header_hashes=len(self.headers_by_hash),
            header_numbers=len(self.headers_by_number),
            receipts=len(self.receipts),
            launches=len(self.launch_at),
            real_quotes=len(self.real_quote),
            **dict(self.counts),
        )


class SelectiveEvidenceContext:
    """Reuse one bounded authoritative RPC lane and immutable evidence across candidates."""

    def __init__(self,endpoint,cache=None):
        from meme_machine.runtime.robinhood.provider_authority import reference
        self.endpoint=reference(endpoint)
        self.cache=cache or ImmutableEvidenceCache()
        self.rpc=None
        self.completed_sessions=[]
        self.adjacent=[]
        self.block_reads=OrderedDict()
        self.factory_hints=OrderedDict()
        self.pin=None
        self.timing={}
        self.boundary_evidence=None
        self.deadline=None
        self.generation_guard=None
        self.receipt_pins={}
        self.block_receipts_supported=False
        self.view_batch_state={"supported":False}
        cap=os.environ.get('MM_CERTIFICATION_RPC_CAPABILITIES')
        if cap:
            from . import CHAIN_ID
            domain=hashlib.sha256((str(CHAIN_ID)+':'+endpoint).encode()).hexdigest()
            try:self.block_receipts_supported=json.loads(Path(cap).read_text())['endpoints'][domain]['methods']['eth_getBlockReceipts']['supported'] is True
            except (OSError,ValueError,KeyError):pass
            try:self.view_batch_state['supported']=json.loads(Path(cap).read_text())['endpoints'][domain]['methods']['eth_callMany']['supported'] is True
            except (OSError,ValueError,KeyError):pass

    @foreground_work
    def _rotate(self):
        if self.rpc is not None:
            self.completed_sessions.append(self.rpc.telemetry())
            if len(self.completed_sessions)>32:
                self.completed_sessions=self.completed_sessions[-32:]
        # Archive a completed session once, even if replacement authentication fails.
        # An unauthenticated replacement never becomes the current session.
        self.rpc=None
        self.rpc=(_rpc(self.endpoint) if self.deadline is None else
                  _rpc(self.endpoint,evidence_deadline=self.deadline))
        return self.rpc

    def acquire(self,needed=1,scope="pons_selective"):
        needed=int(needed)
        if needed<1 or needed>50:
            raise BoundaryError("selective_evidence_request_bound")
        if self.rpc is None:
            return self._rotate()
        if (
            self.rpc.used+needed>EVIDENCE_SESSION_ROTATE_AT
            or self.rpc.counts[scope]+needed>self.rpc.per_scope
        ):
            return self._rotate()
        return self.rpc

    def call(self,method,params,scope):
        return self.batch([(method,params)],scope)[0]

    def batch(self,calls,scope):
        if self.generation_guard is not None and not self.generation_guard():
            raise BoundaryError("candidate_generation_superseded")
        calls=list(calls);requested=len(calls)
        out=[None]*len(calls);missing=[];keys=[];seen={};followers={}
        # Only exact block-scoped reads can cross candidates. Never cache gasPrice,
        # latest/pending state, provider errors, or a read from a different block hash.
        for index,(method,params) in enumerate(calls):
            key=None;cached=None
            if hasattr(self.cache,'immutable_curve') and method in ('eth_getCode','eth_call') and isinstance(params[-1],str) and params[-1].startswith('0x'):
                from .abi import calldata
                address=params[0] if method=='eth_getCode' else params[0].get('to','')
                immutable=self.cache.immutable_curve(address,int(params[-1],16))
                if immutable and method=='eth_getCode':cached=immutable['code']
                elif immutable and params[0].get('data')==calldata('token()'):
                    cached='0x'+immutable['token'][2:].zfill(64)
            if cached is not None:
                out[index]=cached;continue
            if method=='eth_getBlockByNumber' and params and str(params[0]).startswith('0x'):
                cached=self.cache.header_by_number(int(params[0],16))
            elif method=='eth_getBlockByHash' and params:
                cached=self.cache.header_by_hash(params[0])
            elif method=='eth_getTransactionReceipt' and params[0] in self.receipt_pins:
                cached=self.cache.receipt(params[0],self.receipt_pins[params[0]])
            elif method in ('eth_call','eth_getCode') and self.pin and params[-1]==hex(self.pin[0]):
                key=(self.pin[1],method,json.dumps(params,sort_keys=True))
                cached=self.block_reads.get(key)
            if cached is not None:out[index]=cached
            else:
                identity=json.dumps([method,params],sort_keys=True)
                if identity in seen:followers[index]=seen[identity]
                else:seen[identity]=index;missing.append((index,(method,params),key))
        for group in _chunks(missing,50):
            if self.generation_guard is not None and not self.generation_guard():
                raise BoundaryError('candidate_generation_superseded')
            from .view_batch import grouped
            extra=len(grouped([x[1] for x in group])) if self.view_batch_state.get('supported') and not self.view_batch_state.get('parity_verified') else 0
            rpc=self.acquire(min(50,len(group)+extra),scope)
            rpc.evidence_deadline=self.deadline
            rpc.evidence_pins={hex(n):h['hash'] for n,h in self.cache.headers_by_number.items()}
            if self.pin:rpc.evidence_pins[hex(self.pin[0])]=self.pin[1]
            rpc.evidence_receipts=self.receipt_pins
            original=self.timing.get('first_observation_monotonic')
            rpc.evidence_cost_epoch=(self.pin[1],original,self.deadline) if self.pin and original is not None and self.deadline is not None else None
            rpc.evidence_timing=self.timing
            before=time.monotonic()
            if self.timing.get('first_transport_submitted_monotonic') is None:
                self.timing['first_transport_submitted_monotonic']=before
            from .view_batch import batch as view_batch
            values=view_batch(rpc,[x[1] for x in group],scope,self.view_batch_state) if scope in ('pons_natural','pons_selective_trajectory') else rpc.batch([x[1] for x in group],scope=scope)
            self.timing['rpc_batch_seconds']=self.timing.get('rpc_batch_seconds',0)+time.monotonic()-before
            for (index,(method,params),key),value in zip(group,values):
                out[index]=value
                if key is not None:
                    self.block_reads[key]=value
                    while len(self.block_reads)>4096:self.block_reads.popitem(last=False)
        if self.generation_guard is not None and not self.generation_guard():
            raise BoundaryError('candidate_generation_superseded')
        for index,source in followers.items():out[index]=out[source]
        return out[:requested]

    def prefetch_adjacent_headers(self,calls):
        # Fill spare slots of an already-needed batch; never add a transport or
        # evaluate a neighbour early. Normal receipt/log authentication still runs.
        extras=[];seen={json.dumps(x,sort_keys=True) for x in calls}
        for row in self.adjacent:
            if row['deadline']<=time.time():continue
            event=row['event'];block=int(event['blockNumber'],16)
            if self.cache.header_by_number(block) is not None:continue
            call=('eth_getBlockByNumber',[hex(block),False]);key=json.dumps(call,sort_keys=True)
            if key in seen:continue
            seen.add(key);extras.append((call,event['blockHash'],block))
            if len(extras)>=max(0,50-len(calls)):break
        return extras if len(calls)<50 else []

    def acquire_dense_receipts(self,tx_rows):
        from .immutable_rpc import choose_block_receipts
        groups={}
        for tx,bh in tx_rows:
            if self.cache.receipt(tx,bh) is None:groups.setdefault(bh,set()).add(tx)
        for bh,required in groups.items():
            header=self.cache.header_by_hash(bh)
            transactions=header.get('transactions') if header else None
            total=len(transactions) if isinstance(transactions,list) else None
            remaining=0 if self.deadline is None else self.deadline-time.monotonic()
            if not choose_block_receipts(len(required),total,supported=self.block_receipts_supported,remaining_seconds=remaining):continue
            try:rows=self.call('eth_getBlockReceipts',[bh],'pons_selective_window')
            except BoundaryError as exc:
                if str(exc) not in ('provider_rpc_-32601','provider_rpc_-32602'):raise
                self.block_receipts_supported=False
                continue  # standard receipt acquisition retains the same deadline
            if not isinstance(rows,list) or len(rows)!=total:raise BoundaryError('block_receipt_census_disagreement')
            expected=set(transactions)
            if len(expected)!=total or {r.get('transactionHash') for r in rows}!=expected:
                raise BoundaryError('block_receipt_census_disagreement')
            for r in rows:
                if r.get('blockHash')!=bh or r.get('blockNumber')!=header['number']:
                    raise BoundaryError('block_receipt_identity_disagreement')
            for r in rows:self.cache.remember_receipt(r['transactionHash'],bh,r)

    def factory_token_hint(self,curve):
        # Only a request-shaping hint. Current token(), current factory record,
        # and compiled deployment authentication are still mandatory.
        if hasattr(self.cache,'immutable_curve') and self.pin:
            value=self.cache.immutable_curve(curve,self.pin[0])
            if value:return value['token']
        return self.factory_hints.get(curve.lower())

    def remember_compiled_identity(self,curve,token,code,block,header,auth):
        if hasattr(self.cache,'remember_compiled'):
            self.cache.remember_compiled(curve,token,code,block,header,auth)

    def remember_factory_identity(self,curve,token):
        self.factory_hints[curve.lower()]=token
        self.factory_hints.move_to_end(curve.lower())
        while len(self.factory_hints)>4096:self.factory_hints.popitem(last=False)

    def remember_candidate(self,candidate):
        self.remember_factory_identity(candidate['curve'],candidate['token'])
        self.cache.remember_header(candidate["header"])
        self.cache.remember_receipt(
            candidate["receipt"]["transactionHash"],
            candidate["receipt"]["blockHash"],
            candidate["receipt"],
        )
        self.cache.remember_real_quote(
            candidate["curve"],candidate["block"],candidate["state"].real_quote
        )

    def telemetry(self):
        current=None if self.rpc is None else self.rpc.telemetry()
        return dict(
            completed_sessions=list(self.completed_sessions),
            current_session=current,
            cache=self.cache.telemetry(),view_batch=dict(self.view_batch_state),
        )


def _rpc(endpoint,*,evidence_deadline=None):
    rpc=configured_rpc(endpoint,limit=200,per_scope=190,retries=0)
    # Chain authentication is part of this consumer's acquisition budget.
    rpc.evidence_deadline=evidence_deadline
    rpc.verify_chain()
    from meme_machine.runtime.robinhood.provider_authority import require_canonical
    try:require_canonical(rpc)
    except ValueError as exc:raise BoundaryError(str(exc)) from None
    return rpc


def _chunks(rows,size):
    for i in range(0,len(rows),size):
        yield rows[i:i+size]


def _batched(endpoint,calls,scope,*,evidence_context=None):
    """Run bounded read batches, reusing an authoritative session when supplied."""
    ctx=evidence_context or SelectiveEvidenceContext(endpoint)
    before=len(ctx.completed_sessions)
    out=ctx.batch(calls,scope) if calls else []
    telemetry=list(ctx.completed_sessions[before:])
    if ctx.rpc is not None:
        telemetry.append(ctx.rpc.telemetry())
    return out,telemetry


def _window_events(candidate,tape):
    end_block=int(candidate['block']);curve=candidate['curve'].lower()
    raw=[event for event in tape if event.get('address','').lower()==curve
         and int(event['blockNumber'],16)<=end_block]
    return raw[-ENTRY_THRESHOLDS['max_market_events']*4:]


def _window_prefetch(cache,candidate,tape,limit):
    """Only fill spare slots of an already-required immutable state batch.

    Authentication/normalization still runs in _authenticate_window. Cached
    receipts must match both transaction and block identity before reuse.
    """
    if tape is None or limit<=0:return [],[]
    raw=_window_events(candidate,tape);calls=[];labels=[]
    for block_hash in dict.fromkeys(event['blockHash'] for event in raw):
        if cache.header_by_hash(block_hash) is None:
            calls.append(('eth_getBlockByHash',[block_hash,False]));labels.append(('header',block_hash))
    for tx,block_hash in dict.fromkeys((event['transactionHash'],event['blockHash']) for event in raw):
        if cache.receipt(tx,block_hash) is None:
            calls.append(('eth_getTransactionReceipt',[tx]));labels.append(('receipt',(tx,block_hash)))
    return calls[:limit],labels[:limit]


def _remember_window_prefetch(cache,labels,values):
    for (kind,key),value in zip(labels,values):
        if kind=='header':
            if value['hash']!=key:raise BoundaryError('selective_window_header_disagreement')
            cache.remember_header(value)
        else:
            tx,block_hash=key;cache.remember_receipt(tx,block_hash,value)


def _authenticate_window(
    endpoint,candidate,tape,seconds=60,*,evidence_context=None
):
    """Authenticate one market window with a shared immutable header/receipt cache.

    Missing block headers and receipts are deliberately fetched in one combined
    bounded batch graph. Receipt reads may include a few events later excluded by
    the 60-second timestamp filter; this trades redundant sequencing for fewer
    physical transports without changing the evidence or event-cap rules.
    """
    ctx=evidence_context or SelectiveEvidenceContext(endpoint)
    cache=ctx.cache
    end_time=int(candidate["stamp"].event_at)
    end_block=int(candidate["block"])
    curve=candidate["curve"].lower()
    raw=_window_events(candidate,tape)

    hashes=list(dict.fromkeys(event["blockHash"] for event in raw))
    tx_rows=list(dict.fromkeys(
        (event["transactionHash"],event["blockHash"]) for event in raw
    ))
    if hasattr(ctx,"acquire_dense_receipts"):ctx.acquire_dense_receipts(tx_rows)
    headers={}
    receipts={}
    pending=[]
    labels=[]

    for block_hash in hashes:
        header=cache.header_by_hash(block_hash)
        if header is None:
            labels.append(("header",block_hash))
            pending.append(("eth_getBlockByHash",[block_hash,False]))
        else:
            headers[block_hash]=header

    for tx,block_hash in tx_rows:
        receipt=cache.receipt(tx,block_hash)
        if receipt is None:
            labels.append(("receipt",(tx,block_hash)))
            pending.append(("eth_getTransactionReceipt",[tx]))
        else:
            receipts[(tx,block_hash)]=receipt

    before=len(ctx.completed_sessions)
    values=ctx.batch(pending,"pons_selective_window") if pending else []
    for label,value in zip(labels,values):
        kind,key=label
        if kind=="header":
            block_hash=key
            if value["hash"]!=block_hash:
                raise BoundaryError("selective_window_header_disagreement")
            cache.remember_header(value)
            headers[block_hash]=value
        else:
            tx,block_hash=key
            cache.remember_receipt(tx,block_hash,value)
            receipts[(tx,block_hash)]=value

    selected=[]
    for event in raw:
        header=headers[event["blockHash"]]
        if header["hash"]!=event["blockHash"]:
            raise BoundaryError("selective_window_header_disagreement")
        at=int(header["timestamp"],16)
        if end_time-int(seconds)<=at<=end_time:
            selected.append(event)
    selected.sort(key=lambda e:(
        int(e["blockNumber"],16),
        int(e["transactionIndex"],16),
        int(e["logIndex"],16),
    ))
    if len(selected)>ENTRY_THRESHOLDS["max_market_events"]:
        raise BoundaryError("selective_event_capacity")

    observed=int(time.time())
    normalized=[]
    for event in selected:
        block_hash=event["blockHash"]
        receipt=receipts[(event["transactionHash"],block_hash)]
        from meme_machine.runtime.robinhood.pons import normalized_cached
        def build(event=event,receipt=receipt):
            row=raw_event(
                curve_abi(),event,address=curve,receipt=receipt,
                header=headers[event['blockHash']],observed_at=observed,
                confirmation="confirmed",
            )
            return normalized_trade(
                row["decoded"],
                identity=f'{row["block"]}:{row["transaction_hash"]}:{row["log_index"]}',
                event_at=row["event_at"],
            )
        normalized.append(normalized_cached(ctx,event,build))

    telemetry=list(ctx.completed_sessions[before:])
    if ctx.rpc is not None:
        telemetry.append(ctx.rpc.telemetry())
    return normalized,telemetry


def _header_search(rpc,current_block,current_at,target_at,cache):
    """Find latest block whose timestamp is <= target_at with bounded reads."""
    current_block=int(current_block);current_at=int(current_at);target_at=int(target_at)
    if target_at>=current_at:
        return dict(number=hex(current_block),timestamp=hex(current_at))
    if current_block<=0:
        raise BoundaryError("trajectory_history_incomplete")

    def read(block):
        block=max(0,int(block))
        if block not in cache:
            header=rpc.call(
                "eth_getBlockByNumber",[hex(block),False],scope="pons_selective_trajectory"
            )
            if int(header["number"],16)!=block:
                raise BoundaryError("trajectory_block_identity")
            cache[block]=header
        return cache[block]

    high=current_block
    delta=4
    low=None
    while delta<=MAX_TRAJECTORY_LOOKBACK_BLOCKS:
        probe=max(0,current_block-delta)
        header=read(probe)
        if int(header["timestamp"],16)<=target_at:
            low=probe
            break
        if probe==0:
            break
        high=probe
        delta*=2
    if low is None:
        raise BoundaryError("trajectory_history_incomplete")

    # high may already be <= target after the first probe; ensure the upper bound
    # is a block later than target for the binary search.
    high=max(high,low)
    if high==low:
        high=current_block
    while low+1<high:
        mid=(low+high)//2
        header=read(mid)
        if int(header["timestamp"],16)<=target_at:
            low=mid
        else:
            high=mid
    return read(low)


def _indexed_header_plan(cache,current_header,launch_at):
    """Use authenticated timestamp brackets; hints never select an anchor.

    Every returned anchor needs its immediately following header strictly after
    the target (or is the candidate block). Missing brackets hydrate a bounded
    interpolated neighbourhood in one shared batch, then prove that boundary.
    """
    end=int(current_header['number'],16);at=int(current_header['timestamp'],16)
    rows={n:h for n,h in cache.headers_by_number.items() if max(0,end-MAX_TRAJECTORY_LOOKBACK_BLOCKS)<=n<=end}
    rows[end]=current_header;needed=set();complete=True
    if len(rows)<2:return None,rows
    for horizon in (15,5):
        target=max(int(launch_at or 0),at-horizon)
        low=max((n for n,h in rows.items() if int(h['timestamp'],16)<=target),default=None)
        if low==end:continue
        if low is not None and low+1 in rows and int(rows[low+1]['timestamp'],16)>target:continue
        complete=False
        high=min((n for n,h in rows.items() if int(h['timestamp'],16)>target),default=end)
        if low is None:
            # Cold historical edge keeps the original bounded contiguous search.
            start=min(rows)-1
            needed.update(range(max(0,start-48),start+1));continue
        gap=high-low-1
        if gap<=0:raise BoundaryError('trajectory_header_time_regression')
        if gap<=INDEX_NEIGHBORHOOD:needed.update(range(low+1,high))
        else:
            lo_at=int(rows[low]['timestamp'],16);hi_at=int(rows[high]['timestamp'],16)
            if hi_at<=lo_at:raise BoundaryError('trajectory_header_time_regression')
            hint=low+(target-lo_at)*(high-low)//(hi_at-lo_at)
            first=max(low+1,min(high-INDEX_NEIGHBORHOOD,hint-INDEX_NEIGHBORHOOD//2+1))
            needed.update(range(first,min(high,first+INDEX_NEIGHBORHOOD)))
    if complete:return [],rows
    return sorted(n for n in needed if n not in rows)[:49],rows


def _trajectory(endpoint,candidate,*,evidence_context=None,window_tape=None,
                screen_launch_age=False):
    """Resolve 5s/15s trajectory anchors from dense batched recent headers.

    The old binary search serialized one request per probe. This path walks recent
    blocks in contiguous batches, so both target anchors are proven from the same
    header set and every immutable header is reusable by later candidates.
    """
    ctx=evidence_context or SelectiveEvidenceContext(endpoint)
    cache=ctx.cache
    current_block=int(candidate["block"])
    current_header=candidate["header"]
    current_at=int(current_header["timestamp"],16)
    curve=candidate["curve"].lower()
    cache.remember_header(current_header)

    launch_at=cache.launch(curve)
    next_block=current_block-1
    looked=0
    collected={current_block:current_header}
    first=True
    indexed_enabled=len(cache.headers_by_number)>1
    before=len(ctx.completed_sessions)

    while True:
        room=49 if first and launch_at is None else 50
        low=max(0,next_block-room+1)
        blocks=list(range(next_block,low-1,-1)) if next_block>=0 else []
        indexed,known=_indexed_header_plan(cache,current_header,launch_at) if indexed_enabled else (None,{})
        if indexed is not None:
            blocks=indexed;collected.update(known)
        labels=[];calls=[]

        if first and launch_at is None:
            labels.append(("launch",curve))
            calls.append((
                "eth_call",
                [dict(to=curve,data=calldata("launchedAt()")),hex(current_block)],
            ))

        for block in blocks:
            header=cache.header_by_number(block)
            if header is None:
                labels.append(("header",block))
                calls.append(("eth_getBlockByNumber",[hex(block),False]))
            else:
                collected[block]=header

        extras=ctx.prefetch_adjacent_headers(calls) if calls and hasattr(ctx,'prefetch_adjacent_headers') else []
        combined=calls+[x[0] for x in extras]
        values=ctx.batch(combined,"pons_selective_trajectory") if combined else []
        for (_,expected_hash,expected_block),header in zip(extras,values[len(calls):]):
            if header.get('hash')!=expected_hash or int(header['number'],16)!=expected_block:
                raise BoundaryError('adjacent_candidate_header_identity')
            cache.remember_header(header)
        values=values[:len(calls)]
        for label,value in zip(labels,values):
            kind,key=label
            if kind=="launch":
                launch_at=_one_word(value)
                cache.remember_launch(curve,launch_at)
            else:
                block=int(key)
                if int(value["number"],16)!=block:
                    raise BoundaryError("trajectory_block_identity")
                cache.remember_header(value)
                collected[block]=value

        if launch_at is None or not 0<=int(launch_at)<=current_at:
            raise BoundaryError("invalid_curve_launch_time")
        if screen_launch_age and _launch_age_rejection(current_at,launch_at) is not None:
            # The newly authenticated launch time already proves the frozen age
            # veto. Do not fetch further history, reserve anchors or receipts.
            telemetry=list(ctx.completed_sessions[before:])
            if ctx.rpc is not None:telemetry.append(ctx.rpc.telemetry())
            return [],int(launch_at),dict(
                sessions=telemetry,batched_recent_headers=True,
                recent_headers_considered=len(collected),
                launch_age_screen_only=True,cache=cache.telemetry(),
            )
        for block in blocks:
            header=cache.header_by_number(block)
            if header is not None:
                collected[block]=header

        min_target=max(int(launch_at),current_at-15)
        oldest=min(
            (int(h["timestamp"],16) for h in collected.values()),
            default=current_at,
        )
        looked+=len(blocks)
        if indexed is None and oldest<=min_target:
            break
        if indexed is not None:
            remaining,_=_indexed_header_plan(cache,current_header,launch_at)
            if remaining==[]:break
        if low==0 or looked>=MAX_TRAJECTORY_LOOKBACK_BLOCKS or (indexed is not None and not blocks and not calls):
            raise BoundaryError("trajectory_history_incomplete")
        next_block=low-1
        first=False

    ordered=[collected[b] for b in sorted(collected)]
    prior_at=None
    for header in ordered:
        at=int(header["timestamp"],16)
        if prior_at is not None and at<prior_at:
            raise BoundaryError("trajectory_header_time_regression")
        prior_at=at

    targets=[
        max(int(launch_at),current_at-15),
        max(int(launch_at),current_at-5),
    ]
    prior_headers=[]
    for target in targets:
        eligible=[
            h for h in ordered
            if int(h["timestamp"],16)<=int(target)
        ]
        if not eligible:
            raise BoundaryError("trajectory_history_incomplete")
        chosen=max(eligible,key=lambda h:int(h["number"],16))
        cache.header_by_number(int(chosen['number'],16))
        prior_headers.append(chosen)

    unique_blocks=list(dict.fromkeys(
        int(h["number"],16) for h in prior_headers
    ))
    reserve_by_block={}
    missing_blocks=[]
    for block in unique_blocks:
        cached=cache.real_quote_at(curve,block)
        if cached is None:
            missing_blocks.append(block)
        else:
            reserve_by_block[block]=cached
    reserve_calls=[
        ("eth_call",[
            dict(to=curve,data=calldata("realQuoteReserve()")),hex(block)
        ])
        for block in missing_blocks
    ]
    extra_calls,extra_labels=_window_prefetch(cache,candidate,window_tape,
        50-len(reserve_calls) if reserve_calls else 0)
    combined=reserve_calls+extra_calls
    reads=ctx.batch(combined,"pons_selective_trajectory") if combined else []
    _remember_window_prefetch(cache,extra_labels,reads[len(reserve_calls):])
    reads=reads[:len(reserve_calls)]
    for block,raw in zip(missing_blocks,reads):
        reserve_by_block[block]=cache.remember_real_quote(
            curve,block,_one_word(raw)
        )

    threshold=int(candidate["record"]["graduationThreshold"])
    snapshots=[]
    for header in prior_headers:
        block=int(header["number"],16)
        real=int(reserve_by_block[block])
        snapshots.append(dict(
            at=int(header["timestamp"],16),block=block,
            real_quote=real,
            progress_bps=curve_progress_bps(real,threshold),
        ))
    snapshots.append(dict(
        at=current_at,block=current_block,
        real_quote=int(candidate["state"].real_quote),
        progress_bps=curve_progress_bps(candidate["state"].real_quote,threshold),
    ))
    dedup={}
    for row in snapshots:
        dedup[(row["at"],row["block"])]=row

    telemetry=list(ctx.completed_sessions[before:])
    if ctx.rpc is not None:
        telemetry.append(ctx.rpc.telemetry())
    return (
        sorted(dedup.values(),key=lambda r:(r["at"],r["block"])),
        int(launch_at),
        dict(
            sessions=telemetry,
            batched_recent_headers=True,
            recent_headers_considered=len(collected),
            cache=cache.telemetry(),
        ),
    )


def strategy_prospect_preflight(candidate):
    """Strategy-static screen after minimal authenticated current-state evidence.

    This is not qualification authority. It prevents trajectory/window acquisition
    for curves that cannot satisfy the frozen selective-continuation thesis at the
    observed state. Broad CurveBuy discovery remains intact for observability.
    """
    state=candidate["state"]
    record=candidate["record"]
    progress=curve_progress_bps(
        state.real_quote,record["graduationThreshold"])
    reasons=([] if str(record.get("pairToken","0x"+"00"*20)).lower()==("0x"+"00"*20) else ["non_native_quote"])
    if state.graduated:
        reasons.append("already_graduated")
    if int(candidate["current_snipe_bps"])!=0:
        reasons.append("snipe_tax_nonzero")
    if not (
        ENTRY_THRESHOLDS["min_curve_progress_bps"]
        <= progress
        <= ENTRY_THRESHOLDS["max_curve_progress_bps"]
    ):
        reasons.append("curve_progress")
    if int(state.creator_tax_bps)>ENTRY_THRESHOLDS["max_creator_tax_bps"]:
        reasons.append("creator_tax")
    return dict(
        eligible=not reasons,
        reasons=reasons,
        progress_bps=int(progress),
        graduated=bool(state.graduated),
        current_snipe_bps=int(candidate["current_snipe_bps"]),
        creator_tax_bps=int(state.creator_tax_bps),
        screen_authority="strategy_prospect_admission_only",
        full_qualification_required=True,
        full_evidence_required_for_decision=False if reasons else None,
    )


def _launch_age_rejection(asof,launch_at):
    """A complete age veto makes all later qualification evidence unnecessary."""
    if launch_at is None:return None
    if not 0<=int(launch_at)<=int(asof):
        raise BoundaryError('invalid_curve_launch_time')
    age=int(asof)-int(launch_at)
    if ENTRY_THRESHOLDS['min_token_age_seconds']<=age<=ENTRY_THRESHOLDS['max_token_age_seconds']:
        return None
    return dict(
        eligible=False,reasons=['token_age'],token_age_seconds=age,
        trajectory=dict(complete=False,acquired=False,reason='immutable_launch_age_veto'),
        screen_authority='authenticated_immutable_launch_age_only',
        full_qualification_required=True,full_evidence_required_for_decision=False,
    )


def authenticated_early_rejection(boundary,evidence):
    """Classify only a fresh, authenticated proof of an existing frozen veto.

    A bare exception string or an incomplete authentication remains a failure.
    The native quote boundary and raw rate are retained unchanged.
    """
    if not evidence or evidence.get('boundary')!=boundary or evidence.get('authentication_complete') is not True:
        return None
    age=evidence.get('decision_age_seconds')
    if not isinstance(age,(int,float)) or not 0<=age<=ENTRY_THRESHOLDS['max_state_age_seconds']:
        return None
    reason=None;bucket=None
    if (boundary=='natural_non_native_quote_not_supported'
            and evidence.get('pair_token') not in (None,'0x'+'00'*20)):
        reason='non_native_quote';bucket='valid_early_structural_rejection'
    if boundary=='invalid_current_snipe_bps':
        rate=evidence.get('current_snipe_bps');fee=evidence.get('fee_bps');tax=evidence.get('creator_tax_bps')
        if (all(type(x) is int for x in (rate,fee,tax)) and rate>0
                and fee>=0 and tax>=0 and fee+tax<=2000
                and rate>9900-fee-tax):
            reason='snipe_tax_nonzero';bucket='valid_early_strategy_rejection'
    if reason is None:return None
    return dict(eligible=False,reasons=[reason],causal_bucket=bucket,
        screen_authority='authenticated_current_state_rejection_only',
        full_qualification_required=True,full_evidence_required_for_decision=False,
        authenticated_evidence=dict(evidence))


def strategy_trajectory_preflight(candidate,snapshots,launch_at):
    """Reject trajectory-domain misses before receipt/window reconstruction.

    Every check is an existing frozen qualification rule using evidence already
    acquired for trajectory authentication. It never grants entry authority.
    """
    asof=int(candidate["stamp"].event_at)
    trajectory=trajectory_metrics(snapshots,asof)
    token_age=asof-int(launch_at)
    reasons=[]
    if (
        token_age < ENTRY_THRESHOLDS["min_token_age_seconds"]
        or token_age > ENTRY_THRESHOLDS["max_token_age_seconds"]
    ):
        reasons.append("token_age")
    if not trajectory.get("complete"):
        reasons.append("trajectory_history")
    else:
        if trajectory["progress_15s_bps"] < ENTRY_THRESHOLDS["min_progress_15s_bps"]:
            reasons.append("curve_velocity")
        if ENTRY_THRESHOLDS["require_curve_acceleration"] and not trajectory["accelerating"]:
            reasons.append("curve_deceleration")
        eta=trajectory["graduation_eta_seconds"]
        if (
            eta is None
            or eta < ENTRY_THRESHOLDS["min_graduation_eta_seconds"]
            or eta > ENTRY_THRESHOLDS["max_graduation_eta_seconds"]
        ):
            reasons.append("graduation_eta")
    return dict(
        eligible=not reasons,reasons=reasons,token_age_seconds=token_age,
        trajectory=trajectory,screen_authority="strategy_trajectory_admission_only",
        full_qualification_required=True,
        full_evidence_required_for_decision=not reasons,
    )


@decision_work(4)
def evaluate_candidate(
    endpoint,event,tape,*,strategy_capital_quote,wallet_histories=None,
    creator_history=None,quote_relative_strength_bps=None,
    evidence_observed_at=None,evidence_observed_monotonic=None,
    evidence_context=None,on_stage=None,
):
    """Freeze one outcome-blind qualification vector from Pons-only evidence."""
    sessions=[]
    ctx=evidence_context or SelectiveEvidenceContext(endpoint)
    ctx.boundary_evidence=None
    started=time.monotonic()
    ctx.timing=dict(evidence_started_monotonic=started,first_observation_monotonic=evidence_observed_monotonic,
        queue_wait_seconds=None if evidence_observed_monotonic is None else started-float(evidence_observed_monotonic),
        first_transport_submitted_monotonic=None)
    ctx.deadline=None if evidence_observed_monotonic is None else float(evidence_observed_monotonic)+ENTRY_THRESHOLDS['max_state_age_seconds']
    ctx.pin=(int(event['blockNumber'],16),event['blockHash'])
    ctx.receipt_pins={x['transactionHash']:x['blockHash'] for x in tape}
    ctx.receipt_pins[event['transactionHash']]=event['blockHash']
    if evidence_observed_monotonic is not None:
        preflight_latency=time.monotonic()-float(evidence_observed_monotonic)
        if preflight_latency<0:
            raise BoundaryError("future_evidence_observation")
        if preflight_latency>ENTRY_THRESHOLDS["max_state_age_seconds"]:
            raise BoundaryError("stale_evidence_acquisition")
    rpc=ctx.acquire(16,"pons_natural")
    auth_started=time.monotonic()
    report=dict(reads=[],timing=ctx.timing)
    try:
        candidate=_authenticate_candidate(
            ctx,event,report,
            evidence_observed_at=evidence_observed_at,
            evidence_observed_monotonic=evidence_observed_monotonic,
            max_evidence_latency_seconds=ENTRY_THRESHOLDS["max_state_age_seconds"],
        )
    except BoundaryError:
        ctx.boundary_evidence=report.get('authenticated_rejection')
        raise
    ctx.timing["header_receipt_quote_authentication_seconds"]=time.monotonic()-auth_started
    candidate["report"]=report
    ctx.remember_candidate(candidate)
    sessions.append(rpc.telemetry())
    if candidate["decoded_event"]["decoded"]["name"]!="CurveBuy":
        raise BoundaryError("selective_nomination_not_buy")

    if on_stage is not None:on_stage('current_state_complete')
    prospect=strategy_prospect_preflight(candidate)
    if not prospect["eligible"]:
        available=int(time.time())
        completed_monotonic=time.monotonic()
        acquisition_latency=(
            float(available-int(candidate["stamp"].event_at))
            if evidence_observed_monotonic is None
            else completed_monotonic-float(evidence_observed_monotonic)
        )
        ctx.timing.update(
            prospect_screen_only=True,
            evidence_completed_monotonic=completed_monotonic,
            evidence_acquisition_seconds=completed_monotonic-started,
            decision_age_seconds=acquisition_latency,
            chain_event_at=candidate["stamp"].event_at,
            chain_timestamp_lag_seconds=(
                None if evidence_observed_at is None
                else evidence_observed_at-candidate["stamp"].event_at
            ),
        )
        vector=dict(
            complete=False,
            current_threshold_pass=False,
            qualification="strategy_prospect_screen",
            all_rejections=list(prospect["reasons"]),
            progress_bps=int(prospect["progress_bps"]),
            asof=int(candidate["stamp"].event_at),
            demand={"recent_buy_groups":[]},
            thresholds=dict(ENTRY_THRESHOLDS),
            prospect_screen_only=True,
        )
        return dict(
            token=candidate["token"],curve=candidate["curve"],
            source_transaction=event["transactionHash"],
            source_block=candidate["block"],
            source_log_index=int(event["logIndex"],16),
            candidate=candidate,market_events=[],
            trajectory_snapshots=[],launch_at=None,
            vector=vector,provider_sessions=sessions,
            timing=dict(ctx.timing),stale_stage=None,
            screened_out=True,prospect_preflight=prospect,
            evaluation_completed_at=available,
            evidence_observed_at=evidence_observed_at,
            evidence_acquisition_latency_seconds=acquisition_latency,
            chain_timestamp_lag_seconds=(
                None if evidence_observed_at is None
                else float(evidence_observed_at)-float(candidate["stamp"].event_at)
            ),
            evidence_context=ctx.telemetry(),
        )

    if on_stage is not None:
        on_stage('prospect_admitted')
    tape=list(tape)
    trajectory_started=time.monotonic()
    # A previously authenticated immutable launch time can already prove the
    # frozen age veto. It cannot qualify a candidate or replace fresh state.
    launch_at=ctx.cache.launch(candidate['curve'])
    asof=int(candidate['stamp'].event_at)
    trajectory_prospect=_launch_age_rejection(asof,launch_at)
    if trajectory_prospect is not None:
        snapshots=[]
        ctx.timing['cached_launch_age_screen_only']=True
    else:
        if on_stage is not None:on_stage('trajectory_requested')
        snapshots,launch_at,trajectory_session=_trajectory(
            endpoint,candidate,evidence_context=ctx,window_tape=tape,
            screen_launch_age=True,
        )
        sessions.append(trajectory_session)
        trajectory_prospect=_launch_age_rejection(asof,launch_at)
        if trajectory_prospect is None:
            trajectory_prospect=strategy_trajectory_preflight(candidate,snapshots,launch_at)
            if on_stage is not None and trajectory_prospect['trajectory'].get('complete'):
                on_stage('trajectory_complete')
        else:ctx.timing['authenticated_launch_age_screen_only']=True
    ctx.timing["trajectory_seconds"]=time.monotonic()-trajectory_started
    if not trajectory_prospect["eligible"]:
        available=int(time.time())
        completed_monotonic=time.monotonic()
        acquisition_latency=(
            float(available-int(candidate["stamp"].event_at))
            if evidence_observed_monotonic is None
            else completed_monotonic-float(evidence_observed_monotonic)
        )
        ctx.timing.update(
            trajectory_screen_only=True,
            evidence_completed_monotonic=completed_monotonic,
            evidence_acquisition_seconds=completed_monotonic-started,
            decision_age_seconds=acquisition_latency,
            chain_event_at=candidate["stamp"].event_at,
            chain_timestamp_lag_seconds=(
                None if evidence_observed_at is None
                else evidence_observed_at-candidate["stamp"].event_at
            ),
        )
        vector=dict(
            complete=False,current_threshold_pass=False,
            qualification="strategy_trajectory_screen",
            all_rejections=list(trajectory_prospect["reasons"]),
            progress_bps=int(prospect["progress_bps"]),
            token_age_seconds=int(trajectory_prospect["token_age_seconds"]),
            trajectory=trajectory_prospect["trajectory"],
            asof=int(candidate["stamp"].event_at),
            demand={"recent_buy_groups":[]},thresholds=dict(ENTRY_THRESHOLDS),
            prospect_screen_only=False,trajectory_screen_only=True,
        )
        return dict(
            token=candidate["token"],curve=candidate["curve"],
            source_transaction=event["transactionHash"],
            source_block=candidate["block"],
            source_log_index=int(event["logIndex"],16),
            candidate=candidate,market_events=[],
            trajectory_snapshots=snapshots,launch_at=launch_at,
            vector=vector,provider_sessions=sessions,
            timing=dict(ctx.timing),stale_stage=None,screened_out=True,
            screened_stage="trajectory",prospect_preflight=prospect,
            trajectory_preflight=trajectory_prospect,
            evaluation_completed_at=available,
            evidence_observed_at=evidence_observed_at,
            evidence_acquisition_latency_seconds=acquisition_latency,
            chain_timestamp_lag_seconds=(
                None if evidence_observed_at is None
                else float(evidence_observed_at)-float(candidate["stamp"].event_at)
            ),
            evidence_context=ctx.telemetry(),
        )
    if on_stage is not None:
        on_stage('trajectory_admitted');on_stage('evidence_required')
        on_stage('admitted');on_stage('evidence_requested')
    window_started=time.monotonic()
    market,market_sessions=_authenticate_window(
        endpoint,candidate,list(tape),seconds=60,evidence_context=ctx
    )
    sessions.extend(market_sessions)
    ctx.timing["receipt_window_authentication_seconds"]=time.monotonic()-window_started

    available=int(time.time())
    completed_monotonic=time.monotonic()
    acquisition_latency=(
        float(available-int(candidate["stamp"].event_at))
        if evidence_observed_monotonic is None
        else completed_monotonic-float(evidence_observed_monotonic)
    )
    ctx.timing.update(evidence_completed_monotonic=completed_monotonic,
        evidence_acquisition_seconds=completed_monotonic-started,
        decision_age_seconds=acquisition_latency,chain_event_at=candidate['stamp'].event_at,
        chain_timestamp_lag_seconds=None if evidence_observed_at is None else evidence_observed_at-candidate['stamp'].event_at)
    creator_groups=(
        candidate["record"].get("deployer"),
        candidate["record"].get("creatorFeeRecipient"),
    )
    decision_started=time.monotonic()
    vector=qualification_vector(
        state=candidate["state"],
        graduation_threshold=candidate["record"]["graduationThreshold"],
        launch_at=launch_at,
        snapshots=snapshots,
        events=market,
        creator_groups=creator_groups,
        current_snipe_bps=candidate["current_snipe_bps"],
        lifecycle_gas_quote=candidate["roundtrip_gas_wei"],
        strategy_capital_quote=int(strategy_capital_quote),
        asof=candidate["stamp"].event_at,
        evidence_available_at=available,
        evidence_observed_at=evidence_observed_at,
        evidence_acquisition_latency_seconds=acquisition_latency,
        pair_token=candidate["record"].get("pairToken"),
        wallet_histories=wallet_histories,
        creator_history=creator_history,
        quote_relative_strength_bps=quote_relative_strength_bps,
    )
    ctx.timing["decision_computation_seconds"]=time.monotonic()-decision_started
    ctx.timing["first_transport_delay_seconds"]=(None if ctx.timing.get("first_transport_monotonic") is None
        else ctx.timing["first_transport_monotonic"]-started)
    return dict(
        token=candidate["token"],curve=candidate["curve"],
        source_transaction=event["transactionHash"],
        source_block=candidate["block"],
        source_log_index=int(event["logIndex"],16),
        candidate=candidate,market_events=market,
        trajectory_snapshots=snapshots,launch_at=launch_at,
        vector=vector,provider_sessions=sessions,
        timing=dict(ctx.timing),
        stale_stage=("stale_after_complete_evidence" if acquisition_latency>ENTRY_THRESHOLDS["max_state_age_seconds"] else None),
        evaluation_completed_at=available,
        evidence_observed_at=evidence_observed_at,
        evidence_acquisition_latency_seconds=acquisition_latency,
        chain_timestamp_lag_seconds=(
            None if evidence_observed_at is None
            else float(evidence_observed_at)-float(candidate["stamp"].event_at)
        ),
        evidence_context=ctx.telemetry(),
    )


def public_evaluation(row):
    """Remove non-JSON dataclass/runtime objects before a study report is persisted."""
    candidate=row["candidate"]
    return dict(
        token=row["token"],curve=row["curve"],
        source_transaction=row["source_transaction"],
        source_block=row["source_block"],
        source_log_index=row["source_log_index"],
        market_events=row["market_events"],
        trajectory_snapshots=row["trajectory_snapshots"],
        launch_at=row["launch_at"],vector=row["vector"],
        timing=row.get("timing"),stale_stage=row.get("stale_stage"),
        screened_out=bool(row.get("screened_out")),
        screened_stage=row.get("screened_stage"),
        prospect_preflight=row.get("prospect_preflight"),
        trajectory_preflight=row.get("trajectory_preflight"),
        evaluation_completed_at=row["evaluation_completed_at"],
        evidence_observed_at=row.get("evidence_observed_at"),
        evidence_acquisition_latency_seconds=row.get(
            "evidence_acquisition_latency_seconds"
        ),
        chain_timestamp_lag_seconds=row.get("chain_timestamp_lag_seconds"),
        evidence_context=row.get("evidence_context"),
        candidate=dict(
            token=candidate["token"],curve=candidate["curve"],block=candidate["block"],
            record=candidate["record"],auth=candidate["auth"],
            state=asdict(candidate["state"]),quote=candidate["quote"],
            freshness_seconds=candidate["freshness_seconds"],
            evidence_observed_at=candidate.get("evidence_observed_at"),
            evidence_acquisition_latency_seconds=candidate.get(
                "evidence_acquisition_latency_seconds"
            ),
            chain_timestamp_lag_seconds=candidate.get(
                "chain_timestamp_lag_seconds"
            ),
            current_snipe_bps=candidate["current_snipe_bps"],
            gas_meta=candidate["gas_meta"],
        ),
        provider_sessions=row["provider_sessions"],
    )
