"""Offline native scaling/history and held-position purchase measurements.

Uses the regression fixtures and original-reader AST already used for parity.
No provider endpoints are contacted; quotation freshness remains separately
covered by native quote and execution tests. These are workload specimens,
not observed operating frequencies or provider bills.
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import time

from operational.tests import network_guard
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.runtime.cu import estimate
from meme_machine.lanes.pons.pons_selective_continuation import ongoing_scale_requalification
from tests.test_pons_current_scaling_history import CurrentScalingHistoryTests, original_reader
from tests.test_pons_shared_native_acquisition import SharedNativeAcquisitionTests


def measured(tape,fn):
    before=Counter(tape.methods);wire=tape.batches
    request=tape.request_bytes;response=tape.response_bytes
    cpu=time.process_time();wall=time.perf_counter()
    result=fn()
    elapsed=dict(cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall)
    methods=Counter(tape.methods)-before
    spec=json.loads(Path('meme_machine/runtime/alchemy-cu-schedule.json').read_text())
    weights=dict(spec['methods'],**spec['throughput_overrides'])
    return result,dict(physical_mock_transports=tape.batches-wire,logical_rpc_elements=sum(methods.values()),
        methods=dict(methods),estimated_billed_cu=estimate(methods)['estimated_cu'],
        estimated_throughput_cu=sum(weights[m]*n for m,n in methods.items()),
        request_bytes=tape.request_bytes-request,delivered_bytes=tape.response_bytes-response,
        local_processing=elapsed)


def scaling():
    f=CurrentScalingHistoryTests();f.setUp()
    try:
        original=original_reader()
        old,a=measured(f.tape,lambda:f.reads(original,history=False))
        repeated,b=measured(f.tape,lambda:f.reads(original,history=False))
        _,preparation=measured(f.tape,f.prepare)
        new,c=measured(f.tape,f.reads)
        final,d=measured(f.tape,f.reads)
        assert old[0]==repeated[0]==new[0]==final[0]
        decisions=[ongoing_scale_requalification(position=r[1],controller=vars(f.native.state),
            evidence=r[0],now=2000) for r in (old,repeated,new,final)]
        assert all(q==decisions[0] and q['scale_qualified'] for q in decisions)
        deltas=[]
        for at in (2001,2002):
            f.top+=1;f.tape.request_log=[]
            result,counts=measured(f.tape,lambda:f.reads(at=at))
            ranges=[params[0] for method,params in f.tape.request_log if method=='eth_getLogs']
            assert len(ranges)==1 and int(ranges[0]['fromBlock'],16)==int(ranges[0]['toBlock'],16)==f.top
            assert not counts['methods'].get('eth_getTransactionReceipt')
            assert ongoing_scale_requalification(position=result[1],controller=vars(f.native.state),evidence=result[0],now=at)['scale_qualified']
            deltas.append(dict(execution_sensitive_started_at=at,canonical_block=f.top,log_ranges=ranges,counts=counts))
        assert f.native.paper._get(f.native.identity)==f.native.before
        return dict(classification='OFFLINE_NATIVE_HISTORY_REPLAY; executable exit quote mocked identically',
            original_reader_commit='cd1c16c4e867b8121e6ff8a8b02b6759ca46bef2',
            window_seconds=900,canonical_event_count=25,occupied_event_blocks=1,
            original_first_pass=a,original_second_pass=b,historical_preparation=preparation,
            retained_first_pass=c,retained_final_pass=d,qualification=decisions[0],
            fresh_block_delta_passes=deltas,
            unchanged_native_qualification=True,unchanged_native_position=True,
            native_accounting_verified=f.native.paper.accounting(f.native.identity)['replay_verified'],
            caveat='Preparation is required once and is not free. Quote RPCs, sizing and final fill fences are excluded. '
                'Local replay time is not provider latency. No historical provider frequency or deadline saving is inferred.')
    finally:f.doCleanups()


def positions():
    f=SharedNativeAcquisitionTests()
    try:
        original,a,old,_=f.run_positions(2,proved=False)
        optimized,b,new,_=f.run_positions(2,proved=True)
        assert original==optimized and a==b
        _,risk,twenty,result=f.run_positions(20,proved=True)
        assert len(twenty.transports)==5 and len(risk)==20
        assert result['accounting']['open_positions']==20
        def counts(rpc):
            spec=json.loads(Path('meme_machine/runtime/alchemy-cu-schedule.json').read_text())
            weights=dict(spec['methods'],**spec['throughput_overrides'])
            return dict(physical_mock_transports=len(rpc.transports),logical_rpc_elements=sum(rpc.methods.values()),
                methods=dict(rpc.methods),estimated_billed_cu=estimate(rpc.methods)['estimated_cu'],
                estimated_throughput_cu=sum(weights[m]*n for m,n in rpc.methods.items()),
                traces=deepcopy(rpc.transports),mock_transport_elapsed_seconds=rpc.clock-100)
        return dict(classification='OFFLINE_NATIVE_SURVIVOR_RUNTIME_STEP; quiet mock markets, independent native books',
            original_two=counts(old),shared_two=counts(new),shared_twenty=counts(twenty),
            identical_two_position_money_and_protective_state=True,
            independent_exact_quantity_simulations_preserved=True,
            shared_two_deployment_enabled=False,
            caveat='Endpoint method/resource proof is mocked. Full-loop two-RPS timing is not certified by this trace. '
                'Pending exits retain the original path; adversarial timing and paced quote components are in CROSS_POSITIONS.json.')
    finally:f.doCleanups()


def active_positions(count):
    from unittest.mock import patch
    from engineering.pons_history.fixtures import encoded_event,checksum
    from tests import test_pons_shared_native_acquisition as fixture
    from tests.lanes.pons import test_pons_finalization as native
    class Active(fixture.TraceRPC):
        def __init__(self,**kwargs):
            super().__init__(**kwargs);self.transaction=checksum(('active-union',count))
            self.events=[encoded_event('uniswap_v4_manager','Swap',dict(
                id=native.graduation(i)['transition']['market'],sender=native.address(990),
                amount0=10000,amount1=-10000,sqrtPriceX96=1<<96,liquidity=1000000,tick=0,fee=0),
                block=101,block_hash=native.block_header(101)['hash'],tx=self.transaction,
                tx_index=0,index=i-1) for i in range(1,count+1)]
        def value(self,method,params):
            if method=='eth_getLogs':
                query=params[0];topics=query['topics'][1]
                if isinstance(topics,str):topics=[topics]
                return deepcopy([e for e in self.events if e['topics'][1] in topics
                    and int(query['fromBlock'],16)<=101<=int(query['toBlock'],16)])
            if method=='eth_getTransactionReceipt':
                return dict(transactionHash=self.transaction,blockHash=native.block_header(101)['hash'],
                    blockNumber='0x65',transactionIndex='0x0',status='0x1',logs=deepcopy(self.events),
                    **{'from':native.address(990)})
            return super().value(method,params)
    test=SharedNativeAcquisitionTests()
    try:
        with patch.object(fixture,'TraceRPC',Active):
            a,risk_a,old,_=test.run_positions(count,proved=False)
            b,risk_b,new,_=test.run_positions(count,proved=True)
        assert a==b and risk_a==risk_b
        assert new.methods['eth_getTransactionReceipt']==1
        def counts(rpc):
            spec=json.loads(Path('meme_machine/runtime/alchemy-cu-schedule.json').read_text())
            weights=dict(spec['methods'],**spec['throughput_overrides'])
            physical=len(rpc.transports)
            return dict(physical_mock_transports=physical,methods=dict(rpc.methods),
                logical_rpc_elements=sum(rpc.methods.values()),estimated_billed_cu=estimate(rpc.methods)['estimated_cu'],
                estimated_throughput_cu=sum(weights[m]*n for m,n in rpc.methods.items()),
                minimum_physical_start_span_at_two_rps=(physical-1)*.5,
                delivered_bytes=None,request_bytes=None,traces=deepcopy(rpc.transports))
        return dict(classification='OFFLINE_NATIVE_SURVIVOR_ACTIVE_STEP; synthetic shared transaction in one canonical block',
            held_positions=count,original=counts(old),shared=counts(new),
            identical_native_positions_and_risk=True,unique_required_receipts=1,occupied_blocks=1,
            native_event_count=count,actual_provider_requests=0,
            caveat='Transport latency is injected, whole-loop pacing is not certified, and bytes were not measured. '
                'These events prove parity and sharing, not deployment/source capability or market frequency.')
    finally:test.doCleanups()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();network_guard()
    with Scratch() as scratch:
        report=dict(schema='system-wide-native-measurements-v1',
            source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            actual_provider_requests=0,actual_provider_bill_savings=None,
            scaling=scaling(),held_positions=positions(),active_held_positions=[active_positions(2),active_positions(20)])
        args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');scratch.success=True


if __name__=='__main__':main()
