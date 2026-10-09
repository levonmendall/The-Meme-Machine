"""Pons-native authenticated held-pool mutation coverage.

An interval consists of successful filtered canonical eth_getLogs reads for
BOTH the native V4 manager and Pons V2 hook, including all global control
events. It is not an eth_subscribe delivery counter or a public-price scout.
This component uses the ALREADY OWNED authenticated RPC/governor and the
existing bounded LogWindows reader. No subscription/service/provider fallback
is created. Every uncertainty raises BoundaryError; it never certifies quiet.

Empty logs cannot alone prove a stable executable quote: caller separately
must prove token/hook semantics and fee/gas bounds before quote suppression.
"""
from dataclasses import dataclass
from functools import lru_cache
import time

from . import BoundaryError
from .abi import signature, topic
from .identity import load
from .log_windows import LogWindows
from .held_quote_wakeup import WindowProof, classify_native_log

_ROLES=('uniswap_v4_manager','pons_v2_hook')
_SOURCE='authenticated_canonical_manager_hook_and_token'
_MAX_INTERVAL_BLOCKS=160
_SCOPE='pons_held_event_coverage'


def _normalize_block(row):
    try:
        num=int(row['number'],16)
        block_hash=row['hash'].lower()
        if num<0 or len(block_hash)!=66 or not block_hash.startswith('0x'):
            raise ValueError()
        int(block_hash[2:],16)
        return num,block_hash
    except (KeyError,ValueError,TypeError,AttributeError):
        raise BoundaryError('held_coverage_header_invalid') from None


@lru_cache(maxsize=1)
def native_coverage_filters():
    """Derive ALL manager/hook ABI events, not only trading events.

    Pool-indexed events use topic1=id/poolId. Any event not proven to have
    that shape is queried as global, including unrelated-pool control events.
    Never assume an unseen event is harmless when proving a quiet interval.
    """
    scoped=set()
    global_topics=set()
    addresses=[]
    for role in _ROLES:
        pin=load(role)
        addresses.append(pin['address'].lower())
        rows=[x for x in pin['abi'] if x.get('type')=='event']
        if not rows:
            raise BoundaryError('held_coverage_abi_events_missing')
        for event in rows:
            sig=topic(signature(event)).lower()
            inputs=event.get('inputs',[])
            is_pool=(bool(inputs) and inputs[0].get('indexed') is True
                and inputs[0].get('type')=='bytes32'
                and inputs[0].get('name') in ('id','poolId'))
            (scoped if is_pool else global_topics).add(sig)
    if not scoped or not global_topics:
        raise BoundaryError('held_coverage_filter_incomplete')
    return tuple(sorted(set(addresses))),tuple(sorted(scoped)),tuple(sorted(global_topics))


def _fingerprint_rpc(rpc):
    """Never treat a public or unverified RPC as canonical proof authority."""
    if getattr(rpc,'canonical_authority',False) is not True:
        raise BoundaryError('held_coverage_canonical_authority_missing')
    if getattr(rpc,'chain_verified',False) is not True:
        raise BoundaryError('held_coverage_chain_unverified')
    fp=getattr(rpc,'provider_fingerprint',None)
    if not isinstance(fp,str) or not fp:
        raise BoundaryError('held_coverage_provider_identity_missing')
    return fp


@dataclass(frozen=True)
class CoverageResult:
    """Authenticated observation. Nonempty/missing proofs may NEVER skip quotes."""
    outcome: str
    reason: str
    window: WindowProof | None
    current_head: dict
    events: tuple
    intervals: int
    scoped_elements: int
    global_elements: int

    @property
    def can_consider_quiet(self):
        return self.outcome=='QUIET_PROVED' and self.window is not None


class NativeHeldCoverage:
    """Bounded complete interval reading by one preexisting authenticated RPC.

    The caller supplies a fresh canonical latest header and quote pin, normally
    from the existing same-turn Pons owner. The quote hash must still be on the
    canonical number chain after acquisition, including on empty responses.
    An advancing head after acquisition may need the next safety turn; a fork
    discovered during the read refuses certification.
    """
    def __init__(self,rpc,endpoint,*,clock=time.monotonic,maximum_blocks=40):
        if type(maximum_blocks) is not int or not 1<=maximum_blocks<=_MAX_INTERVAL_BLOCKS:
            raise ValueError('held_coverage_maximum_blocks')
        self.rpc=rpc
        self.endpoint=str(endpoint)
        self.clock=clock
        self.maximum_blocks=maximum_blocks

    def _read_filter(self,query,start,end):
        planner=LogWindows(self.endpoint,query,batch_elements=4)
        calls=[0]
        def acquire(batch):
            calls[0]+=len(batch)
            return self.rpc.batch(batch,scope=_SCOPE)
        rows=planner.read(start,end,acquire)
        return rows,calls[0]

    def observe(self,*,pool_id,quote_head,current_head,token_behavior_proven=False,
                hook_time_invariant_proven=False,gas_and_fee_bound_valid=False):
        _fingerprint_rpc(self.rpc)
        pool_id=str(pool_id).lower()
        if not (pool_id.startswith('0x') and len(pool_id)==66):
            raise BoundaryError('held_coverage_pool_id_invalid')
        try:int(pool_id[2:],16)
        except ValueError:raise BoundaryError('held_coverage_pool_id_invalid') from None
        previous,previous_hash=_normalize_block(quote_head)
        target,target_hash=_normalize_block(current_head)
        if target<previous or target-previous>self.maximum_blocks:
            raise BoundaryError('held_coverage_gap_exceeds_finite_window')
        # A block hash says nothing about present membership without fresh
        # numeric lookup. Never use a durable hash cache as this witness.
        exact=self.rpc.batch([
            ('eth_getBlockByNumber',[hex(previous),False]),
            ('eth_getBlockByNumber',[hex(target),False]),
        ],scope=_SCOPE)
        if (not isinstance(exact,list) or len(exact)!=2 or
                _normalize_block(exact[0])!=(previous,previous_hash) or
                _normalize_block(exact[1])!=(target,target_hash)):
            raise BoundaryError('held_coverage_canonical_head_changed')

        events=[]
        scoped_calls=global_calls=0
        if target>previous:
            addresses,scoped,globals_=native_coverage_filters()
            scoped_query=dict(address=list(addresses),topics=[list(scoped),pool_id])
            global_query=dict(address=list(addresses),topics=[list(globals_)])
            # Both must succeed; no event from an unfinished batch is a
            # complete coverage claim.
            pool_rows,scoped_calls=self._read_filter(scoped_query,previous+1,target)
            control_rows,global_calls=self._read_filter(global_query,previous+1,target)
            seen={}
            for row in pool_rows+control_rows:
                order=(row.get('blockHash'),row.get('transactionHash'),row.get('logIndex'))
                old=seen.get(order)
                if old is not None and old!=row:
                    raise BoundaryError('held_coverage_duplicate_disagreement')
                seen[order]=row
                label=classify_native_log(row,pool_id)
                if label not in ('WAKE','OTHER_POOL'):
                    raise BoundaryError('held_coverage_unknown_event')
                if label=='WAKE':
                    events.append(row)
            # A fork between the log ranges and the new boundary cannot
            # publish quiet coverage. Block memberships are re-read with
            # deliberately uncached numeric header calls.
            after=self.rpc.batch([
                ('eth_getBlockByNumber',[hex(previous),False]),
                ('eth_getBlockByNumber',[hex(target),False]),
            ],scope=_SCOPE)
            if (not isinstance(after,list) or len(after)!=2 or
                    _normalize_block(after[0])!=(previous,previous_hash) or
                    _normalize_block(after[1])!=(target,target_hash)):
                raise BoundaryError('held_coverage_boundary_reorg')
        if events:
            return CoverageResult('QUOTE_REQUIRED','pool_or_hook_mutation',
                None,dict(current_head),tuple(events),target-previous,
                scoped_calls,global_calls)
        # Successful native economic-window proof is necessary, not sufficient.
        # Token transfers/blacklists and hook time-dependent return deltas
        # require separately authenticated invariants; absent them, no skip.
        safe=(token_behavior_proven is True and hook_time_invariant_proven is True
              and gas_and_fee_bound_valid is True)
        window=WindowProof(
            pool_id=pool_id,quote_block=previous,quote_block_hash=previous_hash,
            through_block=target,through_hash=target_hash,
            observed_monotonic=self.clock(),
            source=_SOURCE if safe else 'unproven_token_hook_or_fee_semantics',
            canonical_contiguous=True,exact_manager_scope_complete=True,
            exact_hook_scope_complete=True,
            token_behavior_proven=token_behavior_proven is True
                and hook_time_invariant_proven is True,
            gas_and_fee_bound_valid=gas_and_fee_bound_valid is True,
            mutation_count=0,unknown_count=0)
        return CoverageResult('QUIET_PROVED' if safe else 'QUOTE_REQUIRED',
            'authenticated_empty_mutation_interval' if safe
                else 'token_hook_or_fee_equivalence_unproven',
            window,dict(current_head),(),target-previous,scoped_calls,global_calls)
