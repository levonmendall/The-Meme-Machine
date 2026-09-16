"""Full live qualification diagnostic with no order/reservation authority.

Uses explicitly recorded unvalidated public seeds and continuation-v1 exactly as
implemented. It may call Engine.qualify, but never Engine.consider/fill/monitor, so
a transient GitHub runner cannot create a paper position that it cannot resume.
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

WATCHLIST=Path('evidence/unvalidated_seed_watchlist.json')
CAPTURE=Path('tests/fixtures/mainnet_trade.json')
# Same explicit same-day reference used by the first prospective smoke. It is only
# a validation experiment genesis; no performance continuity with that lost local DB.
GENESIS_SOL_USD_MICROS=97_840_000
GENESIS_SOURCE='2026-09-16 recorded validation reference: $97.84/SOL; new shadow experiment, not performance continuity'


def _failure(result, stage, exc):
    """Attach a safe stage label without exposing RPC URLs or provider bodies."""
    result.update(reason='unavailable_executable_evidence',evidence_stage=stage,limitation=str(exc))
    return result


def main():
    watch=json.loads(WATCHLIST.read_text())
    capture=json.loads(CAPTURE.read_text())
    captured_seed=pump.trade_events(capture['response'])[0]['wallet']
    seeds=[x['wallet'] for x in watch['seeds']]
    if captured_seed not in seeds:
        seeds.append(captured_seed)
    seeds=seeds[:4]
    now=int(time.time())
    report=dict(kind='real_shadow_full_qualification',network='solana-mainnet',protocol='pump.fun',
                seeds=seeds,seed_provenance=dict(watchlist=str(WATCHLIST),captured_signature=capture['signature']),
                started=now,paper_trades=0,order_authority=False,portfolio_performance_claim=False,
                seed_windows=[],results=[],limitations=[])
    rpc=RPC(os.environ.get('MM_SOLANA_RPC_URL','https://api.mainnet-beta.solana.com'),limit=120)
    with tempfile.TemporaryDirectory() as td:
        store=Store(str(Path(td)/'shadow.db'),'prospective',GENESIS_SOL_USD_MICROS,GENESIS_SOURCE)
        engine=Engine(store,seeds)
        initial=store.state['cash']
        try:
            adapter=PumpAdapter(rpc)
            nominations=[]
            for seed in seeds:
                try:
                    observed=int(time.time())
                    events,covered=adapter.history(seed,observed,priority=True)
                    found=engine.scout(events,int(time.time()))
                    report['seed_windows'].append(dict(seed=seed,covered=covered,events=len(events),nominations=len(found)))
                    nominations.extend(found)
                except (Unavailable,ValueError) as exc:
                    report['seed_windows'].append(dict(seed=seed,covered=False,events=None,nominations=0,
                                                       evidence_stage='seed_history',limitation=str(exc)))
            # Deduplicate nominations by immutable event id before full evidence work.
            unique={n['id']:n for n in nominations}
            report['nominations']=len(unique)
            for nomination in list(unique.values())[:2]:
                result=dict(mint=nomination['mint'],nomination_id=nomination['id'],
                            scout_wallet=nomination['wallet'],
                            signal_age_seconds=max(0,int(time.time())-nomination['market_time']))
                observed=int(time.time())
                try:
                    snap=adapter.snapshot(nomination['mint'],observed,priority=True)
                except (Unavailable,ValueError,KeyError,TypeError) as exc:
                    report['results'].append(_failure(result,'initial_snapshot',exc));continue
                try:
                    market,market_covered=adapter.history(snap['pool'],observed,priority=True)
                except (Unavailable,ValueError,KeyError,TypeError) as exc:
                    report['results'].append(_failure(result,'pool_history',exc));continue
                try:
                    concentration=adapter.concentration(nomination['mint'],snap,priority=True)
                except (Unavailable,ValueError,KeyError,TypeError) as exc:
                    report['results'].append(_failure(result,'concentration',exc));continue
                try:
                    snap=adapter.snapshot(nomination['mint'],int(time.time()),priority=True)
                except (Unavailable,ValueError,KeyError,TypeError) as exc:
                    report['results'].append(_failure(result,'final_snapshot',exc));continue
                evidence=dict(snapshot=snap,events=market,covered=market_covered,concentration_bps=concentration)
                try:
                    reason=engine.qualify(nomination,evidence,int(time.time()))
                    curve=pump.curve(snap['accounts'][0])
                except (Unavailable,ValueError,KeyError,TypeError) as exc:
                    report['results'].append(_failure(result,'qualification',exc));continue
                result.update(reason=reason,evidence_stage='complete',market_window_covered=market_covered,
                              market_events=len(market),concentration_bps=concentration,
                              real_sol_lamports=curve.real_sol,
                              quote_age_seconds=int(time.time())-snap['market_time'])
                report['results'].append(result)
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
