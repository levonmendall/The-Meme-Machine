"""Bounded finalized-log prospective qualification with no order authority.

The stream must be continuously subscribed for the entire unchanged 60-second
continuation-v1 window before any scout event can nominate. A disconnect, parse
loss, or tape-capacity loss removes coverage and forces a new full warmup.

Research instrumentation emits a complete qualification vector for every completed
natural nomination. Engine.qualify remains frozen and authoritative; the vector and
counterfactual sensitivity fields are shadow-only and cannot create reservations.
"""
import json
import math
import os
import tempfile
import threading
import time
from pathlib import Path

from meme_machine import pump
from meme_machine.concentration import ConcentrationReader
from meme_machine.engine import Engine
from meme_machine.provider import RPC, PumpAdapter, Unavailable
from meme_machine.research import qualification_vector
from meme_machine.store import Store
from meme_machine.stream import PumpLogStream, PumpTape, WINDOW_SECONDS

WATCHLIST=Path('evidence/unvalidated_seed_watchlist.json')
CAPTURE=Path('tests/fixtures/mainnet_trade.json')
GENESIS_SOL_USD_MICROS=97_840_000
GENESIS_SOURCE='2026-09-16 recorded validation reference: $97.84/SOL; new shadow experiment, not performance continuity'
DEFAULT_OBSERVE_SECONDS=105
MIN_OBSERVE_SECONDS=30
MAX_OBSERVE_SECONDS=3300
MAX_EVIDENCE_CANDIDATE_LIMIT=80
OBSERVE_SECONDS=max(MIN_OBSERVE_SECONDS,min(
    int(os.environ.get('MM_STREAM_OBSERVE_SECONDS',str(DEFAULT_OBSERVE_SECONDS))),
    MAX_OBSERVE_SECONDS))
def evidence_candidate_budget(observe_seconds, override=None):
    """Bound evidence work across the full observation window without changing policy."""
    if override not in (None, ''):
        return max(1,min(int(override),MAX_EVIDENCE_CANDIDATE_LIMIT))
    # Prior live evidence exhausted 20 candidates after ~1,299 seconds of a
    # 3,300-second window. Size the default to cover the requested observation
    # at ~1.25 completed evidence candidates/minute, with a 20-candidate floor.
    return max(20,min(
        MAX_EVIDENCE_CANDIDATE_LIMIT,
        int(math.ceil((observe_seconds/60.0)*1.25))))

MAX_EVIDENCE_CANDIDATES=evidence_candidate_budget(
    OBSERVE_SECONDS,os.environ.get('MM_STREAM_MAX_EVIDENCE_CANDIDATES'))


def _failure(result, stage, exc):
    result.update(reason='unavailable_executable_evidence',evidence_stage=stage,
                  limitation=str(exc))
    return result


def admissible_after(events, admission):
    return [e for e in events if e['wallet'] in admission and
            int(e['market_time']) > int(admission[e['wallet']])]


def evaluate_nomination(engine, adapter, concentration_reader, tape, nomination):
    result=dict(mint=nomination['mint'],nomination_id=nomination['id'],
                scout_wallet=nomination['wallet'],natural_nomination=True,
                signal_age_seconds=max(0,int(time.time())-nomination['market_time']))
    observed=int(time.time())
    if not tape.covered(observed):
        return dict(result,reason='incomplete_market_window',evidence_stage='stream_window',
                    market_window_covered=False)
    try:
        initial=adapter.snapshot(nomination['mint'],observed,priority=True)
    except (Unavailable,ValueError,KeyError,TypeError) as exc:
        return _failure(result,'initial_snapshot',exc)

    # Establish and publish the exact pool-history boundary before any unrelated
    # concentration/final-snapshot RPC can fail. The finalized stream has already
    # been uninterrupted for >=60s; mint identity uniquely selects this Pump curve.
    history_observed_at=int(time.time())
    if not tape.covered(history_observed_at):
        return dict(result,reason='incomplete_market_window',evidence_stage='stream_window',
                    market_window_covered=False)
    initial_market=tape.window(nomination['mint'],history_observed_at,
                               max_slot=initial['slot'])
    result.update(market_window_covered=True,market_events=len(initial_market),
                  history_observed_at=history_observed_at,
                  history_snapshot_slot=initial['slot'])

    try:
        concentration,concentration_meta=concentration_reader.read(
            nomination['mint'],initial,priority=True)
        result.update(concentration_source=concentration_meta['source'],
                      concentration_slot=concentration_meta['slot'])
    except (Unavailable,ValueError,KeyError,TypeError) as exc:
        return _failure(result,'concentration',exc)
    try:
        final=adapter.snapshot(nomination['mint'],int(time.time()),priority=True)
    except (Unavailable,ValueError,KeyError,TypeError) as exc:
        return _failure(result,'final_snapshot',exc)
    qualified_at=int(time.time())
    if not tape.covered(qualified_at):
        return dict(result,reason='incomplete_market_window',evidence_stage='stream_window',
                    market_window_covered=False)
    market=tape.window(nomination['mint'],qualified_at,max_slot=final['slot'])
    evidence=dict(snapshot=final,events=market,covered=True,
                  concentration_bps=concentration)
    try:
        vector=qualification_vector(engine,nomination,evidence,qualified_at)
        curve=pump.curve(final['accounts'][0])
    except (Unavailable,ValueError,KeyError,TypeError) as exc:
        return _failure(result,'qualification',exc)
    result.update(reason=vector['actual_reason'],evidence_stage='complete',
                  market_window_covered=True,market_events=len(market),
                  concentration_bps=concentration,real_sol_lamports=curve.real_sol,
                  quote_age_seconds=qualified_at-final['market_time'],
                  initial_snapshot_slot=initial['slot'],final_snapshot_slot=final['slot'],
                  qualification_vector=vector)
    return result


def main():
    watch=json.loads(WATCHLIST.read_text())
    capture=json.loads(CAPTURE.read_text())
    captured_seed=pump.trade_events(capture['response'])[0]['wallet']
    admitted=int(watch.get('created_at_unix',0))
    records=[dict(wallet=x['wallet'],eligible_after=int(x.get('eligible_after_unix',admitted)),source='watchlist')
             for x in watch['seeds']]
    if captured_seed not in {x['wallet'] for x in records}:
        records.append(dict(wallet=captured_seed,eligible_after=0,source='captured_fixture'))
    records=records[:4]
    seeds=[x['wallet'] for x in records]
    admission={x['wallet']:x['eligible_after'] for x in records}
    started=int(time.time())
    report=dict(kind='real_stream_shadow_full_qualification',network='solana-mainnet',
                protocol='pump.fun',window_seconds=WINDOW_SECONDS,
                observe_seconds=OBSERVE_SECONDS,max_evidence_candidates=MAX_EVIDENCE_CANDIDATES,
                acquisition='finalized_logsSubscribe',seeds=seeds,seed_admission=admission,
                started=started,paper_trades=0,order_authority=False,
                qualification_policy='continuation-v1',qualification_policy_frozen=True,
                research_authority_only=True,portfolio_performance_claim=False,
                results=[],limitations=[])
    url=os.environ.get('MM_SOLANA_RPC_URL','https://api.mainnet-beta.solana.com')
    # No external service is required by default. An explicitly configured secondary
    # remains available for experiments, but current free proof uses the same primary
    # endpoint with a compact program-account amount slice before the legacy method.
    concentration_url=os.environ.get('MM_SOLANA_CONCENTRATION_RPC_URL','').strip()
    rpc=RPC(url,limit=120)
    concentration_reader=ConcentrationReader(rpc,secondary_url=concentration_url)
    tape=PumpTape()
    stop=threading.Event();ready=threading.Event()
    stream=PumpLogStream(url,tape)
    thread=threading.Thread(target=stream.run,args=(stop,ready),daemon=True)
    thread.start()
    with tempfile.TemporaryDirectory() as td:
        store=Store(str(Path(td)/'shadow.db'),'prospective',GENESIS_SOL_USD_MICROS,GENESIS_SOURCE)
        engine=Engine(store,seeds)
        initial_cash=store.state['cash']
        cursor=None
        attempted=set()
        nomination_ids=set()
        coverage_ready_at=None
        evidence_budget_exhausted_at=None
        try:
            adapter=PumpAdapter(rpc)
            if not ready.wait(15) or stream.error_kind:
                report['limitations'].append('stream_subscription_unavailable')
            else:
                deadline=time.monotonic()+WINDOW_SECONDS+OBSERVE_SECONDS+5
                while time.monotonic()<deadline:
                    now=int(time.time())
                    if stream.error_kind:
                        report['limitations'].append('stream_continuity_lost')
                        report.setdefault('qualification_observation_ended_at',now)
                        break
                    if not tape.covered(now):
                        cursor=None
                        time.sleep(0.25)
                        continue
                    if cursor is None:
                        # A scout trade received before full uninterrupted warmup
                        # cannot nominate prospectively. Start authority here.
                        cursor=tape.latest_sequence()
                        coverage_ready_at=now
                        report['coverage_ready_at']=now
                        time.sleep(0.25)
                        continue
                    fresh,cursor=tape.events_since(cursor)
                    eligible=admissible_after(fresh,admission)
                    if not eligible:
                        time.sleep(0.25)
                        continue
                    found=engine.scout(eligible,now)
                    for nomination in sorted(found,key=lambda n:n['market_time']):
                        nomination_ids.add(nomination['id'])
                        if nomination['mint'] in attempted:
                            continue
                        if len(attempted)>=MAX_EVIDENCE_CANDIDATES:
                            continue
                        attempted.add(nomination['mint'])
                        outcome=evaluate_nomination(engine,adapter,concentration_reader,tape,nomination)
                        report['results'].append(outcome)
                        if len(attempted)>=MAX_EVIDENCE_CANDIDATES and evidence_budget_exhausted_at is None:
                            evidence_budget_exhausted_at=int(time.time())
                            report['evidence_candidate_budget_exhausted_at']=evidence_budget_exhausted_at
                            report['qualification_observation_ended_at']=evidence_budget_exhausted_at
                            report['limitations'].append('evidence_candidate_budget_exhausted')
                    time.sleep(0.25)
                report['nominations']=len(nomination_ids)
                report['evidence_candidates_attempted']=len(attempted)
                report['complete_qualification_vectors']=sum(
                    row.get('evidence_stage')=='complete' and 'qualification_vector' in row
                    for row in report['results'])
                policy_pass_rows=[
                    row for row in report['results']
                    if row.get('evidence_stage')=='complete'
                    and row.get('qualification_vector',{}).get('current_threshold_pass') is True
                ]
                report['research_policy_passes']=len(policy_pass_rows)
                report['research_policy_pass_mints']=[row['mint'] for row in policy_pass_rows]
                report['authorized_qualifications']=0
                report['qualification_semantics']=(
                    'research_policy_passes counts shadow vectors that satisfy frozen continuation-v1; '
                    'authorized_qualifications remains zero because this diagnostic has no order authority'
                )
                if coverage_ready_at is None and not report['limitations']:
                    report['limitations'].append('stream_never_reached_complete_60_second_warmup')
        except (Unavailable,ValueError) as exc:
            report['limitations'].append(str(exc))
        finally:
            captured_at=int(time.time())
            if coverage_ready_at is not None:
                qualification_ended=int(report.get('qualification_observation_ended_at',captured_at))
                report.setdefault('qualification_observation_ended_at',qualification_ended)
                report.update(
                    stream_observation_ended_at=captured_at,
                    stream_observation_seconds=max(0,captured_at-coverage_ready_at),
                    qualification_observation_seconds=max(0,qualification_ended-coverage_ready_at),
                    evidence_candidate_budget_exhausted=evidence_budget_exhausted_at is not None,
                )
            report.update(stream=tape.status(captured_at),orders=len(store.state['orders']),
                          positions=len(store.state['positions']),reserved_lamports=store.state['reserved'],
                          cash_unchanged=store.state['cash']==initial_cash,
                          funnel=store.state.get('funnel',{}),
                          concentration_retrieval=concentration_reader.status())
            store.close()
            stop.set();thread.join(timeout=3)
    report.update(ended=int(time.time()),http_logical_requests=rpc.calls,
                  http_transport_requests=rpc.http_requests,http_failures=rpc.failures,
                  http_retries=rpc.retries,http_failure_kinds=rpc.failure_kinds,
                  stream_error_kind=stream.error_kind,
                  provider_spend_usd=0 if url=='https://api.mainnet-beta.solana.com' else None,
                  infrastructure_spend_usd=0)
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    main()