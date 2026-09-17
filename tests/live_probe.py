"""Small authorized read-only probe. Never initializes a portfolio or submits transactions."""
import json
import os
import time
from pathlib import Path
from meme_machine import pump
from meme_machine.provider import RPC,PumpAdapter,Unavailable


def main():
    capture=json.loads(Path('tests/fixtures/mainnet_trade.json').read_text())
    seed=pump.trade_events(capture['response'])[0]['wallet']
    rpc=RPC(os.environ.get('MM_SOLANA_RPC_URL','https://api.mainnet-beta.solana.com'),limit=80)
    report=dict(kind='real_read_only_probe',seed=seed,seed_provenance=capture['signature'],
        started=int(time.time()),paper_trades=0,portfolio_initialized=False,
        completed_lifecycle=False,qualification_claim=False,observations=[],limitations=[])
    try:
        adapter=PumpAdapter(rpc)
        events,covered=adapter.history(seed,int(time.time()),priority=True)
        report.update(wallet_events=len(events),wallet_window_covered=covered,
                      buy_nominations=sum(e['buy'] for e in events))
        for e in events[-2:]:
            try:
                snap=adapter.snapshot(e['mint'],int(time.time()),priority=True)
                c=pump.curve(snap['accounts'][0]);rates=pump.fees(snap['accounts'][2],c)
                report['observations'].append(dict(mint=e['mint'],slot=snap['slot'],real_sol_lamports=c.real_sol,
                    quote_age_seconds=int(time.time())-snap['market_time'],protocol_fee_bps=rates[0],creator_fee_bps=rates[1],
                    mechanical_gate='exit_liquidity' if c.real_sol<10_000_000_000 else 'requires_full_independent_evidence'))
            except (Unavailable,ValueError) as exc:
                report['limitations'].append(str(exc))
    except (Unavailable,ValueError) as exc:
        report['limitations'].append(str(exc))
    report.update(ended=int(time.time()),requests=rpc.calls,failures=rpc.failures,
                  cache_hits=rpc.cache_hits,provider_spend_usd=0,infrastructure_spend_usd=0)
    print(json.dumps(report,sort_keys=True))
if __name__=='__main__':main()
