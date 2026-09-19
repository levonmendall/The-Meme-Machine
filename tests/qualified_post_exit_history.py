"""Read-only post-exit follow-up for a proven qualified paper trade.

The original paper exit is immutable. This asks the counterfactual research question:
what happened to the same token after the +15% take-profit exit? Historical Pump trade
marks are sampled at fixed horizons, and a current executable read-only quote is added
when the token remains on Pump or has verifiably graduated to PumpSwap.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from meme_machine import pump
from meme_machine.outcome_research import POST_EXIT_HORIZONS, return_bps
from meme_machine.postgrad import PostGraduationAdapter, graduation_handoff, sell_quote
from meme_machine.provider import RPC, PumpAdapter, Unavailable

REPORT=Path('qualified-post-exit-history.json')


def _trade_mark(tx,mint,target):
    rows=[e for e in pump.trade_events(tx) if e.get('mint')==mint]
    if not rows:
        return None
    row=min(rows,key=lambda e:(abs(int(e['market_time'])-int(target)),int(e.get('index',0))))
    return dict(market_time=int(row['market_time']),amount=int(row['amount']),tokens=int(row['tokens']))


def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--seed',default='research/post_exit_35301686960.json')
    args=ap.parse_args(argv)
    seed=json.loads(Path(args.seed).read_text())
    mint=seed['mint'];exit_time=int(seed['exit_time']);held_tokens=int(seed['tokens'])
    base_num=int(seed['exit_proceeds_lamports']);base_den=held_tokens
    url='https://api.mainnet-beta.solana.com'
    rpc=RPC(url,limit=240);adapter=PumpAdapter(rpc)
    pool=pump.pda([b'bonding-curve',pump.un58(mint)])
    signatures=rpc.call('getSignaturesForAddress',[
        pool,{'limit':1000,'commitment':'finalized'}],priority=True)
    successful=[s for s in signatures if not s.get('err') and s.get('blockTime') is not None]
    successful.sort(key=lambda s:int(s['blockTime']))

    chosen={}
    for horizon in POST_EXIT_HORIZONS:
        target=exit_time+horizon
        later=[s for s in successful if int(s['blockTime'])>=target]
        if later:
            chosen[str(horizon)]=later[0]
    if successful:
        chosen['latest']=successful[-1]
    unique={s['signature']:s for s in chosen.values()}
    params=[[sig,{'encoding':'json','commitment':'finalized','maxSupportedTransactionVersion':0}]
            for sig in unique]
    txs=rpc.call_many('getTransaction',params,priority=True,batch_size=8) if params else []
    tx_by_sig={sig:tx for sig,tx in zip(unique,txs)}

    marks={}
    for key,sigrow in chosen.items():
        target=(exit_time+int(key)) if key!='latest' else int(sigrow['blockTime'])
        tx=tx_by_sig.get(sigrow['signature'])
        mark=_trade_mark(tx,mint,target) if tx else None
        if mark:
            mark['return_vs_exit_bps']=return_bps(
                base_num,base_den,mark['amount'],mark['tokens'])
            mark['block_time']=int(sigrow['blockTime'])
            marks[key]=mark

    current=dict(available=False)
    now=int(time.time())
    try:
        snap=adapter.snapshot(mint,now,priority=True)
        c=pump.curve(snap['accounts'][0])
        rates=pump.fees(snap['accounts'][2],c,snap['mint_supply'])
        if not c.complete:
            proceeds,_fee=pump.sell(c,held_tokens,rates)
            current=dict(
                available=True,surface='pump.fun',time=now,proceeds_lamports=proceeds,
                return_vs_exit_bps=return_bps(base_num,base_den,proceeds,held_tokens))
        else:
            handoff=graduation_handoff(snap,now)
            post=PostGraduationAdapter(rpc,scan_rpc=object()).pumpswap_snapshot(
                handoff,now,priority=True)
            quote=sell_quote(post,held_tokens)
            current=dict(
                available=True,surface='pumpswap',time=now,
                proceeds_lamports=quote.output_amount,
                return_vs_exit_bps=return_bps(base_num,base_den,quote.output_amount,held_tokens))
    except (Unavailable,ValueError,KeyError,TypeError) as exc:
        current=dict(available=False,limitation=str(exc) or type(exc).__name__)

    earliest=min((int(s['blockTime']) for s in successful),default=None)
    report=dict(
        kind='qualified_post_exit_history',research_only=True,order_authority=False,
        source_seed=seed,post_exit_marks=marks,current_counterfactual_hold=current,
        signature_census=dict(count=len(signatures),earliest_block_time=earliest,
                              covers_exit=bool(earliest is not None and earliest<=exit_time)),
        provider=dict(logical_requests=rpc.calls,transport_requests=rpc.http_requests,
                      failures=rpc.failures,retries=rpc.retries),
        note='Original +15% paper exit is unchanged; this is counterfactual hold research only.',
    )
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True))
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    main()
