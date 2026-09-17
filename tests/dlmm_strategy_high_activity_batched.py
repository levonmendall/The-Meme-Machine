"""High-activity DLMM replay with verified bounded interval chunking.

Meteora's API remains discovery-only. Candidate token mints are screened in one
finalized batch before expensive pool snapshots, then every survivor still passes
PR #4's complete finalized pool/bin validation. Dense activity is handled by a
sequence of independently terminal-verified chunks; MAX_TRANSACTIONS is unchanged.
"""
from __future__ import annotations

import argparse
import json
import time

from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import MAX_TRANSACTIONS,chain_verified_tapes,reconstruct,transaction_swaps
from meme_machine.provider import Unavailable
from meme_machine.store import digest,encode
from tests import dlmm_strategy_high_activity as research

TARGET_SUPPORTED_POOLS=3
DEEP_DISCOVERY_POOL_MULTIPLIER=12
DEEP_DISCOVERY_PAGE=80
CHUNK_SECONDS=4
ADVANCE_DIAGNOSTICS=[]
ENDPOINT_DIAGNOSTICS=[]


def _capture_chunk(adapter,start,cursor):
    rpc=adapter.rpc
    end_snapshot=adapter.snapshot(start['pool'],int(time.time()),True,fresh=True)
    signatures=rpc.call('getSignaturesForAddress',
        [start['pool'],dict(limit=64,commitment='finalized')],True)
    relevant=[s for s in signatures if start['slot']<s['slot']<=end_snapshot['slot'] and not s.get('err')]
    if len(relevant)>MAX_TRANSACTIONS:
        raise Unavailable('dlmm_transaction_bound')
    params=[[sig['signature'],dict(encoding='json',commitment='finalized',maxSupportedTransactionVersion=0)]
            for sig in relevant]
    values=rpc.call_many('getTransaction',params,True,batch_size=4)
    transactions={sig['signature']:tx for sig,tx in zip(relevant,values)}
    if len(encode(transactions))>2_000_000:
        raise Unavailable('dlmm_interval_evidence_bound')
    now=int(time.time())
    tape=reconstruct(start,end_snapshot,signatures,transactions,now,cursor)
    next_cursor=list(tape.events[-1]['cursor']) if tape.events else list(cursor)
    return tape,next_cursor,len(relevant)


def _chunk_meta(round_index,start,tape,tx_count):
    times=[e['time'] for e in tape.events]
    return dict(
        round=round_index,start_slot=start['slot'],end_slot=tape.terminal['slot'],
        transactions=tx_count,swaps=len(tape.events),terminal_adjustments=list(tape.terminal_adjustments),
        start_last_update=start['last_update'],end_last_update=tape.terminal['last_update'],
        filter_period=start['parameters']['filter_period'],decay_period=start['parameters']['decay_period'],
        event_times=times,event_instructions=[e.get('instruction') for e in tape.events],
        first_elapsed_from_last_update=None if not times else times[0]-start['last_update'],
        last_elapsed_from_last_update=None if not times else times[-1]-start['last_update'],
    )


def batched_advance(adapter,states,wait_seconds):
    if wait_seconds<=0:raise ValueError('dlmm_chunk_wait')
    current=dict(states);cursors={a:[s['slot'],2**31-1,2**31-1] for a,s in states.items()}
    chunks={a:[] for a in states};meta={a:[] for a in states};errors=[]
    remaining=wait_seconds;round_index=0
    while remaining>0 and current:
        sleep_for=min(CHUNK_SECONDS,remaining);time.sleep(sleep_for);remaining-=sleep_for
        for address in list(current):
            start=current[address]
            try:
                tape,cursor,tx_count=_capture_chunk(adapter,start,cursors[address])
                chunks[address].append(tape);cursors[address]=cursor;current[address]=tape.terminal
                meta[address].append(_chunk_meta(round_index,start,tape,tx_count))
            except (Unavailable,ValueError,KeyError,TypeError) as exc:
                errors.append(dict(pool=address,chunk=round_index,reason=str(exc),
                    start_last_update=start.get('last_update'),filter_period=(start.get('parameters') or {}).get('filter_period'),
                    start_time=start.get('time')))
                current.pop(address,None)
        round_index+=1
    advanced={};tapes={};diag={}
    for address in current:
        if not chunks[address]:continue
        try:
            tape=chain_verified_tapes(states[address],chunks[address])
            advanced[address]=tape.terminal;tapes[address]=tape
            diag[address]=dict(chunks=meta[address],combined_swaps=len(tape.events),
                               terminal_adjustments=list(tape.terminal_adjustments))
        except (Unavailable,ValueError,KeyError,TypeError) as exc:
            errors.append(dict(pool=address,chunk='chain',reason=str(exc)))
    ADVANCE_DIAGNOSTICS.append(diag)
    return advanced,tapes,errors


def efficient_discover_and_revalidate(adapter,now):
    candidates,api_error=research.discovery_candidates();rpc=adapter.rpc;rejections=[]
    mint_by_candidate=[];unique_mints=[]
    for candidate in candidates:
        x,y=candidate.get('token_x'),candidate.get('token_y')
        token=y if x==dlmm.WSOL else x if y==dlmm.WSOL else None
        mint_by_candidate.append(token)
        if token and token not in unique_mints:unique_mints.append(token)
    valid_mints=set()
    if unique_mints:
        response=rpc.call('getMultipleAccounts',[unique_mints,dict(encoding='base64',commitment='finalized')],True)
        values=response.get('value') if isinstance(response,dict) else None
        if not isinstance(values,list) or len(values)!=len(unique_mints):
            raise Unavailable('dlmm_research_mint_prefilter_shape')
        for mint,account in zip(unique_mints,values):
            try:
                if not account or account.get('owner')!=pump.TOKEN_PROGRAM:
                    raise ValueError('dlmm_unsupported_token_program_or_version')
                pump.mint_info(account);valid_mints.add(mint)
            except (ValueError,KeyError,TypeError) as exc:
                rejections.append(dict(pool=None,mint=mint,reason=str(exc)[:140],stage='mint_prefilter'))
    states={};accepted=[]
    for candidate,token in zip(candidates,mint_by_candidate):
        address=candidate['address']
        if token and token not in valid_mints:
            rejections.append(dict(pool=address,name=candidate.get('name'),reason='mint_prefilter_rejected',stage='mint_prefilter'))
            continue
        try:
            snap=adapter.snapshot(address,int(time.time()),True);state=dlmm.validate(snap,snap['available_time'],'real')
            if candidate.get('token_x') and candidate.get('token_y'):
                dlmm.scout(snap,snap['available_time'],dict(pool=address,x=candidate['token_x'],y=candidate['token_y']))
            states[address]=state
            accepted.append(dict(**candidate,finalized_slot=state['slot'],active_bin=state['active'],
                                 onchain_bin_step=state['step'],evidence_hash=digest(snap),
                                 last_update=state['last_update'],filter_period=state['parameters']['filter_period'],
                                 decay_period=state['parameters']['decay_period'],market_time=state['time']))
        except (Unavailable,ValueError,KeyError,TypeError) as exc:
            rejections.append(dict(pool=address,name=candidate.get('name'),reason=str(exc)[:140],stage='pool_revalidation'))
        if len(states)>=TARGET_SUPPORTED_POOLS:break
    return states,accepted,rejections,api_error


def historical_last_update_reference():
    """Pinned PR4 authentic interval diagnostic; no live or strategy authority."""
    from tests.test_dlmm_reference import mainnet_swap_interval
    capture=mainnet_swap_interval()
    start=dlmm.validate(capture['start'],capture['start']['available_time'],'real')
    selected=[s for s in capture['signatures'] if start['slot']<s['slot']<=capture['end']['slot'] and not s.get('err')]
    events=[]
    for sig in sorted(selected,key=lambda s:(s['slot'],s['transactionIndex'])):
        events.extend(transaction_swaps(capture['transactions'][sig['signature']],start['pool']))
    end=dlmm.validate(capture['end'],capture['end']['available_time'],'real')
    return dict(start_last_update=start['last_update'],end_last_update=end['last_update'],
        filter_period=start['parameters']['filter_period'],decay_period=start['parameters']['decay_period'],
        event_times=[e['time'] for e in events],instructions=[e['instruction'] for e in events],
        elapsed_to_first=None if not events else events[0]['time']-start['last_update'],
        elapsed_to_last=None if not events else events[-1]['time']-start['last_update'])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cycles',type=int,default=1);parser.add_argument('--window-seconds',type=int,default=12)
    args=parser.parse_args();ADVANCE_DIAGNOSTICS.clear();ENDPOINT_DIAGNOSTICS.clear()
    original_advance=research._advance;original_fetch=research.fetch_high_activity
    original_discover=research.discover_and_revalidate;original_max_pools=research.MAX_POOLS
    def deep_fetch(_limit=24):
        research.MAX_POOLS=DEEP_DISCOVERY_POOL_MULTIPLIER
        try:return original_fetch(DEEP_DISCOVERY_PAGE)
        finally:research.MAX_POOLS=TARGET_SUPPORTED_POOLS
    research.MAX_POOLS=TARGET_SUPPORTED_POOLS;research._advance=batched_advance
    research.fetch_high_activity=deep_fetch;research.discover_and_revalidate=efficient_discover_and_revalidate
    try:report=research.run_live(args.cycles,args.window_seconds)
    finally:
        research._advance=original_advance;research.fetch_high_activity=original_fetch
        research.discover_and_revalidate=original_discover;research.MAX_POOLS=original_max_pools
    report['research_rpc_provider']='solana_labs_public_mainnet'
    report['transaction_retrieval']='bounded_call_many_batch_size_4'
    report['candidate_prefilter']='single_finalized_getMultipleAccounts_classic_spl_mints'
    report['activity_rank_rows_examined_max']=DEEP_DISCOVERY_PAGE
    report['supported_pool_target']=TARGET_SUPPORTED_POOLS
    report['verified_chunk_seconds']=CHUNK_SECONDS
    report['evidence_extension_diagnostics']=ADVANCE_DIAGNOSTICS
    report['endpoint_snapshot_diagnostics']=ENDPOINT_DIAGNOSTICS
    report['historical_last_update_reference']=historical_last_update_reference()
    research.REPORT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(provider=report['research_rpc_provider'],conclusion=report['conclusion'],
        pools=report['distinct_pools'],initial_pools=len(report['initial_pools']),opportunities=report['opportunity_count'],
        nonempty_warmups=report['nonempty_warmup_count'],nonempty_outcomes=report['nonempty_outcome_count'],
        selected_trades=report['selected_trade_count'],selected_median_pnl_bps=report['selected_median_pnl_bps'],
        rpc_calls=report['rpc_calls'],rpc_failures=report['rpc_failures'],
        historical_last_update_reference=report['historical_last_update_reference']),sort_keys=True))


if __name__=='__main__':main()
