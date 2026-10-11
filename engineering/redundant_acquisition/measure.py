"""Offline same-evidence acquisition and cost measurements, never a provider probe."""
import argparse
from collections import Counter
from dataclasses import asdict
import json
import math
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from operational.tests import network_guard
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.runtime.cu import DEFAULT,estimate
from meme_machine.runtime.robinhood.plane import Plane
from meme_machine.runtime.usd_valuation import NativeValueReader
from tests.test_redundant_acquisition import BASE,history_replay,original_v4
from tests import test_pons_protective_capacity as capacity
from tests.test_robinhood_usd_valuation import ReadRPC,NOW
from tests.lanes.pump.test_postgrad_read_efficiency import MeteredRPC
from meme_machine.lanes.pump.postgrad import PostGraduationAdapter,graduation_handoff,sell_quote

RATE=.525/1_000_000


def counts(methods,physical,**extra):
    schedule=json.loads(DEFAULT.read_text())
    weights=dict(schedule['methods'],**schedule['throughput_overrides'])
    return dict(methods=dict(methods),logical_rpc_elements=sum(methods.values()),
        physical_http_starts=physical,modeled_billed_cu=estimate(methods)['estimated_cu'],
        modeled_throughput_cu=sum(weights[k]*v for k,v in methods.items()),**extra)


def sender_reuse(n):
    with tempfile.TemporaryDirectory() as td:
        old=Plane(Path(td)/'old.sqlite');new=Plane(Path(td)/'new.sqlite')
        try:
            a,ar,_=history_replay(old,module=original_v4(),count=n)
            b,br,_=history_replay(new,count=n)
            assert a==b
            cold=(counts(ar.methods,ar.batches),counts(br.methods,br.batches))
            old.close();new.close()
            old=Plane(Path(td)/'old.sqlite');new=Plane(Path(td)/'new.sqlite')
            a,ar,ac=history_replay(old,module=original_v4(),count=n)
            b,br,bc=history_replay(new,count=n)
            assert a==b
            before=counts(ar.methods,ar.batches);after=counts(br.methods,br.batches)
            return dict(name='warm_history_recovery_missing_receipt_sender',transactions=n,
                source='synthetic identical canonical transactions, fresh independent consumers',
                cold_before=cold[0],cold_after=cold[1],before=before,after=after,
                economic_and_canonical_event_parity=True,cache=bc.cache.telemetry(),
                cu_avoided=before['modeled_billed_cu']-after['modeled_billed_cu'],
                physical_starts_avoided=before['physical_http_starts']-after['physical_http_starts'],
                modeled_usd_avoided=(before['modeled_billed_cu']-after['modeled_billed_cu'])*RATE,
                repeated_receipts_before=ar.methods['eth_getTransactionReceipt'],
                repeated_receipts_after=br.methods['eth_getTransactionReceipt'])
        finally:old.close();new.close()


def native_case(name,*,quiet=False,blocks=1,factor=1.,owners=1,sender=False,gas=1,paced=False):
    def run(original):
        test=capacity.ProtectiveCapacityTests()
        try:
            def prepare(runtime,rpc):
                rpc.top=100+blocks;rpc.gas=gas
                if quiet:rpc.events=[]
                if sender:
                    read=rpc.value
                    def missing(method,params):
                        value=read(method,params)
                        if method=='eth_getTransactionReceipt':value.pop('from',None)
                        return value
                    rpc.value=missing
            p,r,rpc,result=capacity.replay(test,owners,predecessor=BASE if original else False,
                price_factor=factor,latency=.1 if paced else 0,paced=paced,before_step=prepare)
            m=rpc.methods
            measured=counts(m,len(rpc.starts),observation_cycles=1,native_quotes=m['eth_call']-1,
                block_headers=m['eth_getBlockByNumber'],canonical_numeric_checks=m['eth_getBlockByNumber']-1,
                historical_receipts=m['eth_getTransactionReceipt'],transaction_sender_acquisitions=m['eth_getTransactionByHash'],
                financial_valuation_acquisitions=0,streaming_bytes=0,
                queue_wait_seconds=sum(rpc.waits),virtual_native_protective_seconds=rpc.clock-100,
                local_wall_seconds=rpc.local_wall_seconds,local_cpu_seconds=rpc.local_cpu_seconds,
                conservative_core_latency_seconds=rpc.clock-100+rpc.local_wall_seconds,
                fixture_json_response_bytes=rpc.bytes,fixture_json_request_bytes=rpc.request_bytes,
                actions=[x['last_action']['action'] for x in r],
                native_cash_basis_conservation=result['accounting']['reconciled'],
                cache_hits=None,cache_invalidations=None,fallback_requests=m['eth_getTransactionByHash'])
            return p,r,measured
        finally:test.doCleanups()
    a,ra,before=run(True);b,rb,after=run(False)
    assert a==b and ra==rb
    return dict(name=name,source='synthetic native runtime; same evidence and original PR129 economic state',
        owners=owners,blocks_advanced=blocks,price_factor=factor,injected_rtt_seconds=.1 if paced else 0,
        modeled_physical_rps=2 if paced else None,before=before,after=after,
        position_risk_and_execution_equivalence=True,
        complete_protective_capacity_proven=False,
        exclusions=['mandatory USD market acquisitions injected by the native fixture',
            'discovery, qualification, provider rotations, streaming, failures and restart costs',
            'fixture bytes are not authenticated or compressed billable wire bytes'])


class USDMeter(ReadRPC):
    def __init__(self):
        super().__init__();self.depth=0;self.starts=0;self.base=0x4bdc170
    def batch(self,calls,*,scope):
        self.starts+=1;self.depth+=1
        try:return super().batch(calls,scope=scope)
        finally:self.depth-=1
    def call(self,method,params,*,scope=None):
        if not self.depth:self.starts+=1
        if method=='eth_getBlockByNumber':
            self.calls.append((method,params,scope))
            n=self.base+(self.now-NOW)*10 if params[0]=='latest' else int(params[0],16)
            return dict(number=hex(n),hash='0x'+f'{n:064x}',timestamp=hex(NOW+(n-self.base)//10))
        return super().call(method,params,scope=scope)


def usd_cases():
    rpc=USDMeter();reader=NativeValueReader('pons',rpc=rpc);rows=[]
    # This explicit clock trace demonstrates freshness branches, not a measured
    # distribution of block or oracle activity. Every numeric header is stable.
    with patch('meme_machine.runtime.usd_valuation.time.time',side_effect=lambda:rpc.now):
        for offset in (0,3,6,12,66):
            rpc.now=NOW+offset;first=len(rpc.calls);starts=rpc.starts
            value=reader(rpc.now)
            methods=Counter(m for m,p,s in rpc.calls[first:])
            rows.append(dict(elapsed_seconds=offset,assumed_blocks_per_second=10,
                source='synthetic source-shaped USD oracle plus one eligible route',
                **counts(methods,rpc.starts-starts),usd_per_eth=str(value.usd_per_unit),
                quote_valid_until=value.valid_until,oracle_checked_at=reader.oracle_checked_at,
                shared_valuation_cache_hit=not methods))
    return rows


def pump_cases():
    results=[];rpc=MeteredRPC();adapter=PostGraduationAdapter(rpc,scan_rpc=object());quotes=[]
    for label in ('baseline','existing_optimized_cold','existing_optimized_warm','existing_optimized_exact_local_time'):
        first=len(rpc.requests)
        if label=='baseline':
            raw=adapter.graduation_snapshot(''+__import__('tests.lanes.pump.test_postgrad',fromlist=['MINT']).MINT,101)
            q=adapter.pumpswap_snapshot(graduation_handoff(raw,101),101)
        else:
            if label.endswith('local_time'):adapter.finalized_market_time=lambda slot:100
            from tests.lanes.pump.test_postgrad import MINT
            q=adapter.pumpswap_snapshot(MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        methods=Counter(m for m,p in rpc.requests[first:])
        quotes.append([sell_quote(q,qty) for qty in (10**6,10**9,10**11)])
        results.append(dict(name=label,source='existing PR126 path; unchanged in this branch',
            **counts(methods,len(rpc.requests)-first),exact_sell_outputs=quotes[-1],
            excludes=['holders, discovery, streaming, USD, genesis rotation, recovery']))
    assert all(q==quotes[0] for q in quotes)
    return results


def projection(cu,physical,elements,interval,hours):
    cycles=math.ceil(hours*3600/interval)
    return dict(hours=hours,observation_cycles=cycles,modeled_cu=cu*cycles,
        physical_http_starts=physical*cycles,logical_rpc_elements=elements*cycles,
        public_price_assumption_usd=round(cu*cycles*RATE,8),actual_account_charge_usd=None)


def model():
    components={
        'pons_survivor_old_one_event_specimen':(232,4,9,3),
        'pons_survivor_quiet_one_new_block':(212,3,8,3),
        'pons_survivor_quiet_30_new_blocks_default_10_window':(332,3,10,3),
        'pons_survivor_quiet_40_new_blocks_default_10_window':(392,3,11,3),
        'pons_survivor_30_new_blocks_validated_40_window_inactive':(212,3,8,3),
        'pons_survivor_one_block_immutable_getter_candidate_inactive':(186,3,7,3),
        'pump_survivor_baseline_warm_quote':(100,5,5,5),
        'pump_survivor_existing_optimized_warm_quote_inactive':(40,2,2,5),
        'pump_survivor_existing_optimized_exact_local_time_inactive':(20,1,1,5),
        'pump_current_baseline_with_holder_element':(120,6,6,5),
        'pump_current_existing_optimized_with_holder_element_inactive':(60,3,3,5),
    }
    projections={name:[projection(*params,h) for h in (24,72,168,720)] for name,params in components.items()}
    usd=[]
    for h in (24,72,168,720):
        route=math.ceil(h*3600/6);oracle=math.ceil(route/11)
        cu=420+(route-oracle)*158+(oracle-1)*354
        usd.append(dict(hours=h,route_refreshes=route,oracle_refreshes=oracle,modeled_cu=cu,
            physical_http_starts=10+(route-oracle)*6+(oracle-1)*8,
            logical_rpc_elements=19+(route-oracle)*8+(oracle-1)*16,
            public_price_assumption_usd=round(cu*RATE,8),actual_account_charge_usd=None))
    logs=[]
    for delta in (30,40,100,160,500,8192):
        for width in (10,20,40,100,160,500):
            q=math.ceil(delta/width)
            logs.append(dict(blocks=delta,width=width,log_elements=q,log_cu=q*60,
                standalone_log_batch_starts=math.ceil(q/4),
                supported_by_existing_inactive_capability_schema=width<=160,
                applicable_to_one_held_turn=delta<=160,
                status='arithmetic only; exact filter and endpoint proof required',
                excludes='headers, receipts, sender bodies, splits, state and deadlines'))
    return dict(schema='meme-machine-acquisition-cost-v2',reference=BASE,
        pricing=dict(public_cu_usd_per_million=.525,authenticated_marginal_price=None,
            evm_subscription_cu_per_delivered_byte=.04,solana_websocket_cu_per_delivered_byte=.0002,
            solana_grpc_usd_per_decimal_tb=75,account_included_allowance=None),
        continuous_hold_component_sensitivities=projections,
        pons_usd_source_shaped_sensitivity=usd,
        pons_usd_assumptions=['original five-second route validity and three-second tick',
            'oracle check valid through sixty seconds; next due route refresh at sixty-six seconds',
            'one eligible route, distinct current and retained oracle blocks',
            'no degradation, provider fees beyond CU, processing delay, route cardinality change or restarts'],
        window_arithmetic=logs,
        market_workload=dict(observed_ordinary_event_rate=None,observed_high_event_rate=None,
            expected_monthly_total=None,quiet_cycle_formula_cu='152 + 60*ceil(new_blocks/window) + 20*extra_event_canonical_headers; no new block:132 with deduplicated target/checkpoint',
            activity_formula_cu='quiet_core + 20*new_receipts + 20*missing_senders + 20*extra_event_headers',
            note='three base headers include target fence and previous checkpoint; no block advance deduplicates'),
        replacement_break_even=dict(evm_stream_bytes_per_avoided_log_element=1500,
            evm_rule='0.04*delivered_bytes + fallback_CU + reconciliation_CU + infrastructure_CU_equivalent < 60*eliminated_log_elements',
            solana_grpc_bytes_per_avoided_http_transaction=280000,
            solana_grpc_rule='75*bytes/1e12 + residual_RPC_USD + overhead_USD < eliminated_RPC_USD',
            solana_grpc_to_websocket_byte_ratio_limit=1.4,
            enterprise_rule='fixed_monthly_fee + discounted_CU_rate*CU/1e6 + delivery + recovery < PAYG_total',
            dedicated_rule='fixed_node_price + uncovered_products + maintenance < eliminated_PAYG_work'),
        portfolio=dict(one_owner='component tables; whole protection cost unknown',
            four_regimes='Pump Current + Pump Survivor + Pons Current + Pons Survivor at their own five/three-second deadlines',
            larger='eight $25 original-$500 positions, two per regime; $200 aggregate basis, hypothetical admissions still require all actual governors',
            scaling='sum independent components as an unshared ceiling; count shared discovery/USD/history once; exact-quantity quotes remain per owner',
            approved_capital_changed=False),
        unknown_components=['fixed infrastructure already paid without a position','baseline discovery and sustained market bytes',
            'candidate qualification frequency','entry/settlement rates','failures and restart distribution',
            'mandatory combined protective latency and sustained reserves','actual account tariff and credits'],
        realized_provider_billing_savings_usd=None,market_provider_calls=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();network_guard()
    with Scratch() as scratch:
        cases=[native_case('quiet_one_block',quiet=True),native_case('quiet_30_blocks',quiet=True,blocks=30),
            native_case('quiet_40_blocks',quiet=True,blocks=40),native_case('one_new_transaction'),
            native_case('sharp_decline',quiet=True,factor=.6),native_case('partial_realization',factor=2.2),
            native_case('full_exit',factor=.6),native_case('gas_change_without_swaps',quiet=True,gas=10**10),
            native_case('missing_sender',sender=True),native_case('four_compatible_owners',owners=4),
            native_case('one_owner_two_rps',paced=True)]
        cases += [native_case('winner_'+str(n)+'x',factor=n) for n in (2,5,10,25,50,100,1000)]
        report=dict(schema='meme-machine-redundant-acquisition-offline-v1',
            source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            baseline=BASE,market_provider_calls=0,realized_billing_savings_usd=None,
            native_scenarios=cases,history_reuse=[sender_reuse(n) for n in (1,100)],
            pons_usd=usd_cases(),pump_existing= pump_cases(),cost_model=model(),
            failures_and_reorganizations='focused original native regression receipts; no successful decision or monthly rate invented',
            interpretation='Synthetic branch and boundary measurements; authenticated account totals are a separate artifact.')
        args.output.write_text(json.dumps(report,indent=2,sort_keys=True,default=asdict)+'\n');scratch.success=True


if __name__=='__main__':main()
