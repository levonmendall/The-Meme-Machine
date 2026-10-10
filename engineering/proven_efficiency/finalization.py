"""Reproduce PR 129's native purchase/deadline specimens without market I/O.

The predecessor methods come from the owner's published source. Injected RTT
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
REPAIR_BASE='ed7b3c6616c59bfce21e96097d175ed3212214c2'


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


def repair_survivor(count,action,rate,latency=.1,sender_fallback=False):
    f=ProtectiveCapacityTests();factor={'hold':1.,'full_exit':.6,'partial_exit':2.2}[action]
    def missing_sender(runtime,rpc):
        value=rpc.value
        def response(method,params):
            result=value(method,params)
            if method=='eth_getTransactionReceipt':result.pop('from')
            return result
        rpc.value=response
    extra=dict(before_step=missing_sender) if sender_fallback else {}
    try:
        a,ra,old,_=replay(f,count,predecessor=REPAIR_BASE,price_factor=factor,latency=0,paced=False,**extra)
        b,rb,warm,_=replay(f,count,price_factor=factor,latency=0,paced=False,**extra)
        assert a==b and ra==rb
        positions,risks,rpc,result=replay(f,count,price_factor=factor,latency=latency,rps=rate,**extra)
        before=measurements([old]);after=measurements([warm]);timed=measurements([rpc])
        elapsed=rpc.clock-100+rpc.local_wall_seconds
        return dict(family='pons_survivor',positions=count,action=action,rps=rate,
            sender_fallback=sender_fallback,modeled_http_rtt_seconds=latency,
            predecessor=before,optimized=after,actual_admission_with_injected_rtt=timed,
            eliminated_mock_starts=before['physical_mock_starts']-after['physical_mock_starts'],
            avoided_modeled_cu=before['estimated_billed_cu']-after['estimated_billed_cu'],
            identical_evidence_position_and_risk_parity=True,
            timed_economic_parity=f.economic(a,ra)==f.economic(positions,risks),
            native_accounting_verified=result['accounting']['reconciled'],
            native_actions=[r['last_action']['action'] for r in risks],
            position_statuses=[p['status'] for p in positions],
            virtual_decision_seconds=rpc.clock-100,measured_local_wall_seconds=rpc.local_wall_seconds,
            measured_local_cpu_seconds=rpc.local_cpu_seconds,conservative_combined_envelope_seconds=elapsed,
            within_three_second_complete_turn=elapsed<3,
            minimum_paced_rate_from_this_trace=(len(rpc.starts)-1)/(3-latency-rpc.local_wall_seconds)
                if len(rpc.starts)>1 and latency+rpc.local_wall_seconds<3 else None)
    finally:f.doCleanups()


def repair_current(count,action,rate,*,stagger=False,survivor_count=0):
    f=CurrentSharedOwnerTests();factor={'hold':1.,'full_exit':.6,'partial_exit':2.2}[action]
    try:
        before=None;after=None
        if not stagger and not survivor_count:
            # Keep the predecessor's completed held-owner sharing. Only the
            # original private delayed-exit acquisition is compared here.
            old,a,_=f.run_owners(count,sharing=True,price_factor=factor,exit_sharing=False)
            new,b,_=f.run_owners(count,sharing=True,price_factor=factor)
            assert all(x['final_position']==y['final_position'] and x['reconciliation']==y['reconciliation']
                for x,y in zip(old,new))
            before=measurements(a);after=measurements(b)
        results,rpcs,t=f.run_owners(count,sharing=True,stagger=stagger,paced=True,latency=.1,
            price_factor=factor,rps=rate,survivor_count=survivor_count)
        decisions=[]
        for i in range(1,count+1):
            identity='current:owner:'+str(i);due=105+i*.1 if stagger else 105
            marks=[e for e in t['native_events'] if e['identity']==identity and e['action']=='mark']
            completed=max(e['completed_monotonic'] for e in marks)
            decisions.append(dict(identity=identity,original_due=due,completed_native_risk_at=completed,
                virtual_risk_latency_seconds=completed-due,within_original_five_seconds=completed-due<5))
        mixed=t.get('mixed_survivor')
        if mixed is not None:
            mixed['conservative_complete_turn_seconds']=mixed['completed_at']-105+t['native_local_wall_seconds']
            mixed['within_three_second_complete_turn']=mixed['conservative_complete_turn_seconds']<3
        return dict(family='pons_current',positions=count,action=action,rps=rate,staggered=stagger,
            survivor_positions=survivor_count,predecessor_exit_acquisition=before,optimized=after,
            eliminated_mock_starts=before['physical_mock_starts']-after['physical_mock_starts'] if before else None,
            avoided_modeled_cu=before['estimated_billed_cu']-after['estimated_billed_cu'] if before else None,
            actual_admission_with_injected_rtt=measurements(rpcs),modeled_http_rtt_seconds=.1,
            native_accounting_verified=all(r['reconciliation']['cash_basis_conservation'] for r in results),
            decisions=decisions,virtual_risk_deadline_misses=sum(not d['within_original_five_seconds'] for d in decisions),
            worker=t,original_paper_exit_delay_seconds=2,
            settlement_is_separate_from_original_risk_observation=True)
    finally:f.doCleanups()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--capacity-repair',action='store_true',help='Incremental ed7 comparison and inactive resource profiles')
    args=parser.parse_args();network_guard()
    with Scratch() as scratch:
        if args.capacity_repair:
            actions=('hold','full_exit','partial_exit');counts=(1,2,4,8,12,20)
            survivors=[repair_survivor(n,a,rate) for rate in (2,3,4) for n in counts for a in actions]
            survivors.extend(repair_survivor(n,'partial_exit',rate,latency=rtt,sender_fallback=sender)
                for n in (1,20) for rate in (2,3,4) for rtt,sender in ((.1,True),(.3,False),(.6,False)))
            currents=[repair_current(n,a,rate) for rate in (2,3,4) for n in counts for a in actions]
            staggered=[repair_current(n,a,rate,stagger=True) for n in (2,8,20) for a in actions for rate in (4,8,12)]
            mixed=[repair_current(n,a,rate,survivor_count=n) for n in (2,10) for a in actions for rate in (3,4,8,12)]
            report=dict(schema='pr129-native-capacity-repair-v1',predecessor=REPAIR_BASE,
                code_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                actual_market_provider_calls=0,actual_provider_bill_savings_usd=0,production_physical_rps=2,
                alternative_resource_profiles_enabled=False,source_tariff_estimate=estimate({}),
                survivor_specimens=survivors,current_specimens=currents,staggered_current_specimens=staggered,
                mixed_specimens=mixed,process_high_water_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                limits=['All responses and RTT are injected offline; no authenticated endpoint P95/P99 or capacity proof.',
                    'Conservative envelopes add whole-turn local wall time to admission/response time; risk events retain original clocks.',
                    'Current settlement includes the original two-second delay, separate from its five-second risk observation.',
                    'Same comparison appears at multiple rates: do not sum its modeled savings across specimens.',
                    'Current comparisons preserve existing held sharing; no PR 124-128 or earlier PR 129 savings are counted again.',
                    'Mixed fixtures share transport admission with independently reconciled synthetic books; this is not $500 funding authority.',
                    'JSON fixture bytes exclude HTTP framing, IDs and compression. Whole-harness RSS is not server sizing.',
                    'Monthly action frequencies and actual marginal account tariffs remain unknown.'])
            args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');scratch.success=True
            return
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
