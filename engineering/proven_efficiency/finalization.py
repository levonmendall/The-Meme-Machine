"""Reproduce PR 129's native purchase/deadline specimens without market I/O.

The predecessor methods come from the owner's published e1070404. Injected RTT
and virtual admission time are separate from measured local wall/CPU time.
Neither prices nor monthly workload frequencies are measured operating bills.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import resource
import subprocess

from operational.tests import network_guard
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.runtime.cu import estimate,DEFAULT
from tests.test_pons_protective_capacity import ProtectiveCapacityTests,replay
from tests.test_pons_current_shared_owners import CurrentSharedOwnerTests

BASE='e1070404849dfa86eb3e47d57cf24263b2fefc25'


def percentile(values,fraction):
    return sorted(values)[max(0,math.ceil(len(values)*fraction)-1)] if values else None


def measurements(sessions):
    methods=Counter();transports=[];waits=[]
    for rpc in sessions:
        methods.update(rpc.methods);transports.extend(rpc.transports);waits.extend(rpc.waits)
    tariff=json.loads(DEFAULT.read_text());weights=dict(tariff['methods'],**tariff['throughput_overrides'])
    return dict(physical_mock_starts=sum(len(r.starts) for r in sessions),
        logical_rpc_elements=sum(methods.values()),logical_consumer_requests=None,methods=dict(methods),
        estimated_billed_cu=estimate(methods)['estimated_cu'],
        estimated_throughput_cu=sum(weights[m]*n for m,n in methods.items()),
        mock_json_request_bytes=sum(r.request_bytes for r in sessions),
        mock_json_delivered_bytes=sum(r.bytes for r in sessions),
        max_batch_elements=max((len(rows) for kind,rows in transports),default=0),
        queue_wait_seconds=sum(waits),p95_wait_seconds=percentile(waits,.95),p99_wait_seconds=percentile(waits,.99),
        physical_traces=transports,starts=[s for r in sessions for s in r.starts],
        responses=[s for r in sessions for s in r.responses])


def survivor(count,action):
    f=ProtectiveCapacityTests();factor={'hold':1.,'full_exit':.6,'partial_exit':2.2}[action]
    try:
        a,ra,old,_=replay(f,count,predecessor=True,price_factor=factor,latency=0,paced=False)
        b,rb,warm,_=replay(f,count,price_factor=factor,latency=0,paced=False)
        assert a==b and ra==rb
        positions,risks,paced,result=replay(f,count,price_factor=factor,latency=.1)
        assert f.economic(a,ra)==f.economic(positions,risks)
        before=measurements([old]);after=measurements([warm]);timed=measurements([paced])
        complete=paced.clock-100+paced.local_wall_seconds
        return dict(family='pons_survivor',positions=count,action=action,deadline_seconds=3,
            predecessor=before,optimized=after,actual_admission_with_injected_rtt=timed,
            eliminated_mock_starts=before['physical_mock_starts']-after['physical_mock_starts'],
            avoided_modeled_cu=before['estimated_billed_cu']-after['estimated_billed_cu'],
            native_position_and_risk_parity=True,native_accounting_verified=True,
            modeled_http_rtt_seconds=.1,virtual_decision_seconds=paced.clock-100,
            measured_local_wall_seconds=paced.local_wall_seconds,measured_local_cpu_seconds=paced.local_cpu_seconds,
            conservative_combined_envelope_seconds=complete,within_original_deadline=complete<3,
            native_actions=[r['last_action']['action'] for r in risks],
            open_positions=result['accounting']['open_positions'])
    finally:f.doCleanups()


def current(count,stagger=False):
    f=CurrentSharedOwnerTests()
    try:
        old,a,_=f.run_owners(count,sharing=False,stagger=stagger)
        new,b,owner=f.run_owners(count,sharing=True,stagger=stagger)
        assert all(x['final_position']==y['final_position'] and x['reconciliation']==y['reconciliation']
            and x['monitor'][0]['action']==y['monitor'][0]['action'] for x,y in zip(old,new))
        result=dict(family='pons_current',positions=count,staggered=stagger,deadline_seconds=5,
            predecessor_private=measurements(a),optimized=measurements(b),native_ledger_and_action_parity=True,
            native_worker_telemetry=owner)
        if not stagger:
            _,rpcs,t=f.run_owners(count,sharing=True,paced=True,latency=.1)
            result.update(actual_admission_with_injected_rtt=measurements(rpcs),
                modeled_http_rtt_seconds=.1,virtual_decision_seconds=t['complete_modeled_seconds'],
                measured_local_wall_seconds=t['native_local_wall_seconds'],measured_local_cpu_seconds=t['native_cpu_seconds'],
                conservative_combined_envelope_seconds=t['complete_modeled_with_local_seconds'],
                within_original_deadline=t['complete_modeled_with_local_seconds']<5,
                native_worker_telemetry=t)
        return result
    finally:f.doCleanups()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();network_guard()
    with Scratch() as scratch:
        specimens=[survivor(n,a) for n in (1,2,4,8,20) for a in ('hold','full_exit','partial_exit')]
        currents=[current(n) for n in (2,4,8,20)]+[current(4,stagger=True)]
        report=dict(schema='pr129-native-finalization-v1',predecessor=BASE,
            code_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            actual_market_provider_calls=0,actual_provider_bill_savings_usd=0,
            surviving_two_rps_limit=True,source_tariff_estimate=estimate({}),
            survivor_specimens=specimens,current_specimens=currents,
            process_high_water_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            memory_caveat='Whole offline harness high-water RSS; not per-turn memory or a server-sizing proof.',
            limits=['Synthetic canonical markets; endpoint latency and capability are not measured.',
                'JSON fixture bytes exclude HTTP framing, JSON-RPC IDs and compressed wire delivery.',
                'Native local time includes validation, monetary replay, disk commits and the mock admission implementation.',
                'The virtual clock does not advance for local work; combined envelopes conservatively add measured local wall time.',
                'No monthly frequency, actual billed CU, retry multiplier or infrastructure savings are inferred.',
                'Current private comparisons include existing durable receipt reuse; its savings are not counted again.'])
        args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');scratch.success=True


if __name__=='__main__':main()
