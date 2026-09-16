"""Full live qualification diagnostic with no order/reservation authority.

Uses the existing captured public seed and continuation-v1 exactly as implemented.
It may call Engine.qualify, but never Engine.consider/fill/monitor, so a transient
GitHub runner cannot create an authoritative paper position that it cannot resume.
"""
import json
import os
import tempfile
import time
from pathlib import Path
from meme_machine import pump
from meme_machine.engine import Engine
from meme_machine.provider import RPC,PumpAdapter,Unavailable
from meme_machine.store import Store

SEED_CAPTURE=Path('tests/fixtures/mainnet_trade.json')
# Same explicit same-day reference used by the first prospective smoke. It is only
# a validation experiment genesis; no performance continuity with that lost local DB.
GENESIS_SOL_USD_MICROS=97_840_000
GENESIS_SOURCE='2026-09-16 recorded validation reference: $97.84/SOL; new shadow experiment, not performance continuity'


def main():
    capture=json.loads(SEED_CAPTURE.read_text())
    seed=pump.trade_events(capture['response'])[0]['wallet']
    now=int(time.time())
    report=dict(kind='real_shadow_full_qualification',network='solana-mainnet',protocol='pump.fun',
                seed=seed,seed_provenance=capture['signature'],started=now,paper_trades=0,
                order_authority=False,portfolio_performance_claim=False,results=[],limitations=[])
    rpc=RPC(os.environ.get('MM_SOLANA_RPC_URL','https://api.mainnet-beta.solana.com'),limit=120)
    with tempfile.TemporaryDirectory() as td:
        store=Store(str(Path(td)/'shadow.db'),'prospective',GENESIS_SOL_USD_MICROS,GENESIS_SOURCE)
        engine=Engine(store,[seed])
        initial=store.state['cash']
        try:
            adapter=PumpAdapter(rpc)
            events,seed_covered=adapter.history(seed,now,priority=True)
            nominations=engine.scout(events,int(time.time()))
            report.update(seed_window_covered=seed_covered,seed_events=len(events),nominations=len(nominations))
            for nomination in nominations[:2]:
                try:
                    observed=int(time.time())
                    snap=adapter.snapshot(nomination['mint'],observed,priority=True)
                    market,market_covered=adapter.history(snap['pool'],observed,priority=True)
                    concentration=adapter.concentration(nomination['mint'],snap,priority=True)
                    snap=adapter.snapshot(nomination['mint'],int(time.time()),priority=True)
                    evidence=dict(snapshot=snap,events=market,covered=market_covered,concentration_bps=concentration)
                    reason=engine.qualify(nomination,evidence,int(time.time()))
                    curve=pump.curve(snap['accounts'][0])
                    report['results'].append(dict(mint=nomination['mint'],nomination_id=nomination['id'],
                        reason=reason,market_window_covered=market_covered,market_events=len(market),
                        concentration_bps=concentration,real_sol_lamports=curve.real_sol,
                        quote_age_seconds=int(time.time())-snap['market_time']))
                except (Unavailable,ValueError,KeyError,TypeError) as exc:
                    report['results'].append(dict(mint=nomination.get('mint'),nomination_id=nomination.get('id'),
                                                  reason='unavailable_executable_evidence',limitation=str(exc)))
        except (Unavailable,ValueError) as exc:
            report['limitations'].append(str(exc))
        finally:
            report.update(orders=len(store.state['orders']),positions=len(store.state['positions']),
                          cash_unchanged=store.state['cash']==initial,reserved_lamports=store.state['reserved'])
            store.close()
    report.update(ended=int(time.time()),requests=rpc.calls,failures=rpc.failures,cache_hits=rpc.cache_hits,
                  provider_spend_usd=0,infrastructure_spend_usd=0)
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    main()
