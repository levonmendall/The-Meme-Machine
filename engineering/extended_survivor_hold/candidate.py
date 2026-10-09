"""Inactive Current/Survivor proposal: arithmetic from the already optimized
acquisition model. No additional cache discount, quota, acquisition or P&L.
"""
import json
from decimal import Decimal

from .research import ROOT,HORIZONS,MULTIPLES,SCENARIOS,evidence_inventory,identity,POLICY_PATHS
from engineering.continuation_resources.model import pump,pons,current_v4
from meme_machine.runtime.exceptional_winner import VERSION,RENEWAL_SECONDS,CHECKPOINTS
from meme_machine.lanes.pump.pump_acceleration_strategy import (
    MODE_LATE_CURVE,MODE_POSTGRAD,MODE_SECOND_LEG,mode_max_hold_s)
from meme_machine.lanes.pons.pons_selective_continuation import EXIT_POLICY


def build():
    demand={};daily={};economic=[]
    for family in CHECKPOINTS:
        hours=(36,*HORIZONS) if family.endswith('current') else HORIZONS
        scenarios=SCENARIOS if family=='pons_survivor' else {'quiet_reference':{}}
        if family=='pons_current':
            scenarios=dict(quiet_reference={},ordinary_reference=dict(events_per_turn=1,event_period_turns=10),
                high_activity=dict(events_per_turn=25,missing_sender=True))
        def native_model(h,kw):
            if family=='pons_survivor':return pons(h,**kw)
            if family=='pons_current':return current_v4(h,**kw)
            return pump(h,current=family=='pump_current')
        demand[family]=[];daily[family]={}
        for name,kwargs in scenarios.items():
            first_hours=CHECKPOINTS[family]/3600
            before=native_model(first_hours,kwargs);next_day=native_model(first_hours+24,kwargs)
            delta={key:next_day[key]-before[key] for key in ('rpc_cu','rpc_elements','physical_attempts_without_failures','turns')}
            delta['rpc_only_modeled_usd']=str(Decimal(next_day['rpc_only_modeled_usd'])-Decimal(before['rpc_only_modeled_usd']))
            daily[family][name]=dict(delta,renewal_gate_provider_calls=0,
                complete_additional_day_cost_usd=None,
                missing_costs=['additional eligibility evidence not already fresh and authenticated',
                    'actual provider failures and recovery',
                    'Pump delivered native bytes and selective gap hydration' if family.startswith('pump') else
                    'actual native payload sizes, HTTP tails and account tariff'],
                classification='synthetic scenario arithmetic from optimized native paths; not invoice or full capacity')
            for h in hours:
                usage=native_model(h,kwargs)
                demand[family].append(dict(hours=h,scenario=name,usage=usage,
                    rpc_counter_limits_unchanged=dict(rpc_cu=24000000,rpc_elements=500000,http_attempts=500000),
                    fits_rpc_counters=(usage['rpc_cu']<=24000000 and usage['rpc_elements']<=500000 and
                        usage['physical_attempts_without_failures']<=500000),
                    safe_capacity_demonstrated=False))
        for h in hours:
            for multiple in MULTIPLES:
                economic.append(dict(family=family,hours=h,checkpoint_multiple=multiple,
                    complete_authenticated_market_lifecycles=0,realized_net_portfolio_pnl=None,
                    execution_fees_spread_slippage_gas=None,liquidity_deterioration=None,
                    after_checkpoint_drawdown=None,capital_recycling_opportunity_cost=None,
                    status='INSUFFICIENT_EVIDENCE'))
    return dict(schema=VERSION,activation=False,market_provider_calls=0,
        baseline_optimization_commit='97186a4e33ea6963d82dc1d08fa998d1a6a229eb',
        ordinary_current_seconds=dict(pump={mode:mode_max_hold_s(mode) for mode in
            (MODE_LATE_CURVE,MODE_POSTGRAD,MODE_SECOND_LEG)},pons_total=EXIT_POLICY['max_total_hold_seconds'],
            pons_pregraduation_thesis=EXIT_POLICY['max_pregraduation_thesis_seconds']),
        original_entry_bound_checkpoints=CHECKPOINTS,provisional_renewal_seconds=RENEWAL_SECONDS,
        selected_strategy_absolute_maximum=None,maximum_safely_demonstrated_operating_seconds=None,
        production_source_sha256={path:identity(path) for path in POLICY_PATHS},
        evidence=evidence_inventory(),economic_comparison=economic,
        resource_horizons=demand,incremental_additional_day=daily,
        provider_limits_changed=False,renewal_acquires_history=False,renewal_recreates_rpc=False,
        renewal_restarts_monitoring=False,renewal_replenishes_usage=False,
        measured_gate_provider_calls=0,
        classification='INACTIVE_CANDIDATE_WITH_INSUFFICIENT_ECONOMIC_AND_RESOURCE_EVIDENCE')


if __name__=='__main__':
    print(json.dumps(build(),indent=2,sort_keys=True))
