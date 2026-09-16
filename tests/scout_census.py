"""Bounded public Pump.fun scout census for prospective-validation diagnostics.

This never initializes a portfolio, nominates for authority, or claims wallet skill.
It only answers whether recent finalized Pump activity contains observable buyers
that could be recorded as explicit unvalidated scout seeds in a later experiment.
"""
import json
import os
import time
from meme_machine import pump
from meme_machine.provider import RPC,PumpAdapter,Unavailable


def main():
    now=int(time.time())
    rpc=RPC(os.environ.get('MM_SOLANA_RPC_URL','https://api.mainnet-beta.solana.com'),limit=80)
    report=dict(kind='real_read_only_scout_census',network='solana-mainnet',protocol='pump.fun',
                started=now,portfolio_initialized=False,paper_trades=0,skill_claim=False,
                candidate_seed_authority=False,observations=[],limitations=[])
    try:
        adapter=PumpAdapter(rpc)
        events,covered=adapter.history(pump.PROGRAM,now,priority=True)
        buys=[e for e in events if e.get('buy')]
        seen=set()
        observations=[]
        for e in reversed(buys):
            if e['wallet'] in seen:
                continue
            seen.add(e['wallet'])
            observations.append(dict(wallet=e['wallet'],mint=e['mint'],market_time=e['market_time'],
                                     available_time=e['available_time'],slot=e['slot'],event_id=e['id']))
            if len(observations)>=8:
                break
        report.update(program_window_covered=covered,decoded_trade_events=len(events),
                      decoded_buy_events=len(buys),unique_recent_buyers=len({e['wallet'] for e in buys}),
                      observations=observations)
    except (Unavailable,ValueError) as exc:
        report['limitations'].append(str(exc))
    report.update(ended=int(time.time()),requests=rpc.calls,failures=rpc.failures,
                  cache_hits=rpc.cache_hits,provider_spend_usd=0,infrastructure_spend_usd=0)
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    main()
