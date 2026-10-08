"""Bounded offline measurements using the existing fixtures and controlled tapes."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
import json
import os
from pathlib import Path
import resource
import statistics
import time


def quantiles(values):
    rows=sorted(values)
    if not rows:return None
    return dict(median_ms=statistics.median(rows)*1000,p95_ms=rows[min(len(rows)-1,int(len(rows)*.95))]*1000,
        p99_ms=rows[min(len(rows)-1,int(len(rows)*.99))]*1000,samples=len(rows))


def io():
    return {k:int(v) for k,v in (line.split(':') for line in Path('/proc/self/io').read_text().splitlines())}


def measure(policy):
    from operational.tests import network_guard
    network_guard()
    from experiments.shared_capital import Opportunity,run_tape
    from meme_machine.shared_capital.runtime import RuntimeCapital,SharedNativePortfolio
    from meme_machine.runtime.usd_valuation import utc
    from meme_machine.shared_capital.model import digest
    from tests.test_pump_pons_capital_preparation import RuntimeIntegrationTests
    from meme_machine.shared_capital.operational_candidate import ACTIVE_REGIMES
    case=RuntimeIntegrationTests();root,a,_,_=case.fixture(policy=policy)
    try:
        clients=[RuntimeCapital(root/'shared-capital.sqlite') for _ in ACTIVE_REGIMES]
        starts={};waits=[];errors=Counter();latency=[];denials=Counter();counts=Counter();missed=Counter()
        for client in clients:
            original=client._transaction
            @contextmanager
            def measured(*,write,_original=original):
                start=time.monotonic()
                with _original(write=write):
                    if write:waits.append(time.monotonic()-start)
                    yield
            client._transaction=measured
        initial_io=io();cpu=time.process_time();wall=time.monotonic();transactions=0
        with ThreadPoolExecutor(max_workers=4) as pool:
            for batch in range(16):
                def submit(index):
                    r=ACTIVE_REGIMES[index];identity=f'perf:{batch}:{r}';now=int(time.time())
                    starts[identity]=time.monotonic()
                    try:return case.queue(clients[index],r,identity,now)
                    except Exception as error:errors[type(error).__name__]+=1;raise
                requests=list(pool.map(submit,range(4)));transactions+=4
                result=a.drain(at=int(time.time()));transactions+=1;end=time.monotonic()
                for q in requests:
                    decision=result['decisions'][q.request_id]
                    elapsed=end-starts[q.request_id];latency.append(elapsed)
                    if elapsed>5:missed[q.regime]+=1
                    if decision['status']!='RESERVED':
                        denials[(q.regime,decision['reason'])]+=1;continue
                    counts[q.regime]+=1
                    native=SharedNativePortfolio(root/'portfolio.sqlite',q.regime.split('_')[0]);now=int(time.time())
                    valuation=dict(evidence_id='perf-value',evidence_sha256='e'*64,currency='USD',as_of=utc(now-1),valid_until=utc(now+3600))
                    for kind,data in [('reserve',dict(amount='6.25')),('enter',dict(basis='6.25',fee='0')),
                                      ('mark',dict(state='CURRENT',net_liquidation_value='6.25'))]:
                        h=digest([q.request_id,kind])
                        native.deliver(q.request_id,event_key='perf:'+h,journal_hash=h,kind=kind,at=utc(now),
                            data=data,value_evidence=valuation if kind!='reserve' else None,metadata=dict(native_basis_units=6250))
                        transactions+=2
        seconds=time.monotonic()-wall;cpu_seconds=time.process_time()-cpu;final_io=io()
        snap=a.snapshot();sizes={p.name:p.stat().st_size for p in root.glob('shared-capital.sqlite*')}
        replay_start=time.monotonic();proof=a.verify_replay();replay_seconds=time.monotonic()-replay_start
        measured_result=dict(classification='OFFLINE_SYNTHETIC_MEASURED_ON_EXISTING_DROPLET',vcpus=os.cpu_count(),
            rounds=16,requests=64,independent_authority_connections=4,granted_by_regime=dict(counts),
            qualified_but_unfunded=[dict(regime=r,constraint=c,count=n) for (r,c),n in sorted(denials.items())],
            grant_latency=quantiles(latency),latency_includes='concurrent durable queue admission and fixed allocation round; excludes native quote/provider time',
            missed_funding_ceiling_5s=dict(missed),wall_seconds=seconds,cpu_seconds=cpu_seconds,
            mean_cpu_percent_of_two_vcpu=cpu_seconds/seconds/2*100,peak_process_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
            durable_transactions=transactions,transactions_per_second=transactions/seconds,concurrent_requests_per_second=64/seconds,
            sqlite_begin_wait=quantiles(waits),begin_wait_over_1ms=sum(t>.001 for t in waits),application_retries=0,errors=dict(errors),
            process_io_delta={k:final_io[k]-v for k,v in initial_io.items()},database_files_bytes=sizes,
            journal_events=proof['events'],replay_seconds=replay_seconds,conservation=proof['conservation'],
            capital=snap['capital'],risk=snap['risk'],stranded_cash_by_historical_partition='0',
            idle_reason='owner-approved fixed aggregate risk cap; deployment remains gated on genuine cutover prerequisites')
        for client in clients:client.close()
        tape=[Opportunity('21:'+str(i),0,'pump_current','asset:'+str(i),1000 if i%3 else -800,1) for i in range(21)]
        comparison={model:run_tape(tape,model,policy=policy) for model in ('A_HARD_SLEEVES','B_SHARED_FIXED')}
        return dict(schema='shared-capital-offline-performance-v1',market_provider_calls=0,
            proposal_policy_sha256=digest(policy.value()),native_21_position_case=dict(position_size='6.25',deployed_basis='131.25',actual_cash='368.75',
                evidence_test='RuntimeIntegrationTests.test_native_pump_shared_funding_exceeds_125_with_original_625_targets'),
            performance=measured_result,controlled_identical_tape=comparison,
            returns_are_scripted=True,profits_are_not_predictions=True)
    finally:case.doCleanups()


def main():
    from meme_machine.shared_capital import RiskPolicy
    parser=argparse.ArgumentParser();parser.add_argument('--policy',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();policy=RiskPolicy(**json.loads(Path(args.policy).read_text()))
    result=measure(policy);Path(args.output).write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')


if __name__=='__main__':main()
