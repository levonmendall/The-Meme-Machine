"""Counterfactual arithmetic and evidence inventory, with no activation or I/O client.

No market outcomes can be inferred from synthetic safety/retention fixtures.
Resource ceilings and production policies are read, never modified.
"""
import argparse
from decimal import Decimal
import hashlib
import json
from math import ceil
from pathlib import Path

from engineering.continuation_resources.model import GIB, PRICE, pons, pump
from meme_machine.lanes.pump.pumpswap_survivor import POLICY as PUMP, POLICY_HASH as PUMP_HASH
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY as PONS, POLICY_HASH as PONS_HASH, risk_policy
from meme_machine.operational.position_continuation import TOTAL_SECONDS, SHUTDOWN_SECONDS
from meme_machine.runtime.directional_continuation import BRIDGE_SECONDS

ROOT = Path(__file__).resolve().parents[2]
PRIMARY_COMMIT = '5370a633101620ab87c302546a87212334c400ec'
HORIZONS = (72, 96, 120, 168, 240, 336)
MULTIPLES = (2, 5, 10, 25, 50)
SCENARIOS = {
    'quiet': {},
    'ordinary_reference': dict(events_per_turn=1, event_period_turns=10),
    'high_volatility': dict(events_per_turn=3),
    'high_activity': dict(blocks_per_turn=40, events_per_turn=15, missing_sender=True),
}
POLICY_PATHS = (
    'meme_machine/lanes/pump/pumpswap_survivor.py',
    'meme_machine/lanes/pons/pons_postgrad_survivor.py',
    'meme_machine/runtime/survivor_risk.py',
    'meme_machine/runtime/directional_continuation.py',
    'meme_machine/operational/position_continuation.py',
    'operational/position-continuation/RESOURCE_ENVELOPE.example.json',
    'deployment/meme-machine-paper.service',
)


def read(relative):
    return json.loads((ROOT / relative).read_text())


def identity(relative):
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def policies():
    return dict(pump=dict(PUMP['exits']), pons=risk_policy())


def tail_floor(multiple):
    """Existing 60% of peak *gain*, not 60% of gross price; execution unproved."""
    high = (multiple - 1) * 10000
    floor_gain = high * 6000 // 10000
    return dict(peak_multiple=multiple, high_water_return_bps=high,
        existing_full_exit_at_or_below_return_bps=floor_gain,
        reference_multiple_at_signal=str(Decimal(10000 + floor_gain) / 10000),
        peak_to_signal_drawdown_bps=(high - floor_gain) * 10000 // (10000 + high),
        execution_price_guaranteed=False)


def evidence_inventory():
    audit_path = 'operational/pons-historical-bootstrap/SOURCES.json'
    capture_path = 'operational/pump-provider-finalization/BYTE_LATENCY.json'
    audit = read(audit_path)
    captured = read(capture_path)
    # Refer to previously verified coherent sources; do not recopy or open live DBs.
    selected = []
    for source in audit['sources']:
        if source['path'].endswith('/pons/history.sqlite') or '/meme-machine-paper-v1/shared/' in source['path']:
            selected.append({key: source.get(key) for key in
                ('path', 'bytes', 'wal_bytes', 'sha256', 'counts', 'header_count',
                 'header_bounds', 'reusable_complete_ranges')})
    return dict(prior_audit=dict(path=audit_path, sha256=identity(audit_path),
            screened_databases=audit['screened_databases'], audited_sources=audit['audited_sources'],
            distinct_verified_copies=audit['isolated_distinct_copies'],
            sources_with_reusable_complete_ranges=sum(bool(s.get('reusable_complete_ranges')) for s in audit['sources'])),
        selected_existing_sources=selected,
        pump_capture=dict(path=capture_path, sha256=identity(capture_path),
            active_delivery_seconds=captured['throughput']['active_captured_delivery_seconds'],
            post_release_delivery_seconds=captured['throughput']['post_release_captured_delivery_seconds']),
        accepted_economic_lifecycles=dict(pump=0, pons=0),
        missing=['continuous token-specific economic coverage through 72h and proposed horizon',
            'authenticated remaining-quantity executable exits, liquidity, gas, spread and slippage at boundaries',
            'entry/partial-realization accounting and concurrent portfolio opportunity set',
            'an ex ante population including reversals, failures and delistings; duplicate backups are not samples'],
        isolated_headers_do_not_prove_intervening_history=True,
        seven_day_startup_census_required=False,
        new_market_provider_calls=0, new_database_copies=0,
        conclusion='INSUFFICIENT_EVIDENCE')


def checks(row, proposal):
    limits = proposal['continuation']
    observed = dict(rpc_cu=row['rpc_cu'], rpc_elements=row['rpc_elements'],
        http_attempts=row['physical_attempts_without_failures'])
    result = {key: dict(demand=value, unchanged_limit=limits[key], fits=value <= limits[key])
        for key, value in observed.items()}
    result['rpc_spend_only'] = dict(demand_usd=row['rpc_only_modeled_usd'],
        unchanged_limit_usd=proposal['continuation_modeled_spend_usd'],
        fits=Decimal(row['rpc_only_modeled_usd']) <= Decimal(proposal['continuation_modeled_spend_usd']))
    result['all_modeled_rpc_components_fit'] = all(result[k]['fits'] for k in result)
    return result


def maximum_rpc_component_seconds(function, proposal):
    """Whole-second feasibility of RPC components only; never a holding permit."""
    low, high = 1, 60 * 24 * 3600
    while low < high:
        middle = (low + high + 1) // 2
        if checks(function(middle / 3600), proposal)['all_modeled_rpc_components_fit']:
            low = middle
        else:
            high = middle - 1
    row = function(low / 3600)
    return dict(seconds=low, hours=low / 3600, binding=checks(function((low + 1) / 3600), proposal),
        demand_at_last_fitting_second=row, classification='RPC_COMPONENT_BOUND_ONLY',
        streaming_bytes_latency_memory_queue_recovery_and_approval_proven=False)


def resource_horizons(proposal):
    rows = []
    baseline_pump = pump(72)
    baseline_pons = {name: pons(72, **kw) for name, kw in SCENARIOS.items()}
    for hours in HORIZONS:
        pump_row = pump(hours)
        pump_row.update(incremental_rpc_usd_over_72=str(Decimal(pump_row['rpc_only_modeled_usd'])
            - Decimal(baseline_pump['rpc_only_modeled_usd'])), ceiling_checks=checks(pump_row, proposal),
            native_stream_and_gap_reconstruction='UNMEASURED; mandatory additional work, not included',
            scenarios='snapshot RPC count identical across quiet/volatile/busy prices; total stream/hydration work is not')
        pons_rows = {}
        for name, kw in SCENARIOS.items():
            after, before = pons(hours, **kw), pons(hours, before=True, **kw)
            after.update(incremental_rpc_usd_over_72=str(Decimal(after['rpc_only_modeled_usd'])
                - Decimal(baseline_pons[name]['rpc_only_modeled_usd'])), ceiling_checks=checks(after, proposal),
                before_optimization_physical_attempts=before['physical_attempts_without_failures'],
                physical_attempts_removed=before['physical_attempts_without_failures']-after['physical_attempts_without_failures'],
                local_two_rps_cadence_fits=after['minimum_physical_rps_under_scenario'] <= 2,
                guaranteed_exit_latency=False, http_bytes='UNMEASURED; contract code and event payloads vary')
            pons_rows[name] = after
        degraded = dict(pons_rows['high_volatility'])
        failures = ceil(degraded['physical_attempts_without_failures'] / 10)
        degraded.update(extra_failed_physical_attempts=failures,
            extra_logical_elements_upper=50 * failures,
            extra_modeled_cu_upper=50 * 60 * failures,
            extra_rpc_cost_upper_usd=str(PRICE * 50 * 60 * failures),
            assumption='10% extra failed attempts; each reserves at most a 50-element 60-CU batch; no internal retries',
            allocation='additional demand, not a grant; must fit unchanged separate recovery resources and deadlines',
            protected_guaranteed=False)
        attempted_upper=dict(rpc_cu=degraded['rpc_cu']+50*60*failures,
            rpc_elements=degraded['rpc_elements']+50*failures,
            physical_attempts_without_failures=degraded['physical_attempts_without_failures']+failures,
            rpc_only_modeled_usd=str(Decimal(degraded['rpc_only_modeled_usd'])+PRICE*50*60*failures))
        degraded['combined_reservation_upper']=attempted_upper
        degraded['combined_reservation_upper_checks']=checks(attempted_upper,proposal)
        pons_rows['degraded_provider'] = degraded
        rows.append(dict(hours=hours, extension_hours_over_baseline=hours-72,
            pump=pump_row, pons=pons_rows,
            original_policy_allows=hours == 72,
            ordinary_holding_after_service_start_deadline_seconds=TOTAL_SECONDS-3600-SHUTDOWN_SECONDS,
            existing_operational_envelope_allows_extension=False,
            native_32_gib_average_allowance_bytes_per_second=32*GIB/(hours*3600),
            native_stop_average_allowance_bytes_per_second=proposal['continuation']['native_stop_bytes']/(hours*3600),
            http_1_gib_average_allowance_bytes_per_pons_turn=GIB/(hours*1200),
            capital_hours_gross_25_usd_upper=25*hours,
            incremental_capital_hours_upper=25*(hours-72),
            capital_classification='upper occupancy arithmetic, not actual residual basis or opportunity cost',
            safe_duration_proven=False))
    return rows


def economic_cells():
    metrics = ('realized_net_pnl', 'profit_captured_fraction', 'gains_sacrificed_at_72h',
        'gains_lost_by_later_exit', 'maximum_drawdown_after_72h', 'liquidity_deterioration',
        'execution_fees_spread_slippage_gas', 'portfolio_return', 'portfolio_downside_risk',
        'capital_recycling_opportunity_cost')
    return [dict(family=family, hours=hours, boundary_appreciation_multiple=multiple,
        independently_qualified_market_lifecycles=0, status='INSUFFICIENT_EVIDENCE',
        **{key: None for key in metrics})
        for family in ('pump', 'pons') for hours in HORIZONS for multiple in MULTIPLES]


def build():
    proposal = read('operational/position-continuation/RESOURCE_ENVELOPE.example.json')
    primary = read('operational/continuation-resources/MODEL.json')
    measured=read('operational/continuation-resources/MEASUREMENTS.json')
    history_cpu=next(t['value']['cpu_seconds'] for t in measured['traces']
        if t['value'].get('survivor_monitor_turns')==86401)
    return dict(schema='extended-survivor-hold-research-v1', primary_engineering_commit=PRIMARY_COMMIT,
        disposition='INSUFFICIENT_EVIDENCE', production_extension_recommended=False,
        production_state_mutations=0, market_provider_calls=0, research_is_not_authorization=True,
        baseline=dict(policies=policies(), hashes=dict(pump=PUMP_HASH, pons=PONS_HASH),
            original_entry_clock_required=True, current_bridge_seconds=BRIDGE_SECONDS,
            operational_maximum_seconds=TOTAL_SECONDS, recovery_seconds=3600,
            shutdown_seconds=SHUTDOWN_SECONDS, provider_limits=proposal,
            recovery_is_not_speculative_hold_time=True),
        policy_and_service_source_sha256={path: identity(path) for path in POLICY_PATHS},
        evidence=evidence_inventory(), economic_comparison=economic_cells(),
        exceptional_strata=[tail_floor(m) for m in MULTIPLES],
        resource_horizons=resource_horizons(proposal),
        component_only_maxima=dict(pump_snapshot=maximum_rpc_component_seconds(pump, proposal),
            **{'pons_'+name: maximum_rpc_component_seconds(lambda h, kw=kw: pons(h, **kw), proposal)
                for name, kw in SCENARIOS.items()}),
        simultaneous_positions=dict(first_bootstrap_maximum=1,
            pons_independent_quiet_two_position_minimum_rps=pons(72)['minimum_physical_rps_under_scenario']*2,
            local_pons_rps_limit=2,
            shared_acquisition_savings='UNVERIFIED for different positions; no aggregate cache discount assumed',
            queue_maximum=64, queue_wait_maximum_seconds=5,
            cpu_cores='1.8', rss_readiness_bytes=6*GIB, systemd_memory_max_bytes=7*GIB),
        storage_reference=primary['storage'],
        cpu_projections=dict(survivor_history_72h_cpu_seconds=str(history_cpu),
            classification='offline 2-events-per-3s fixture; linear work arithmetic is not wall-time or live benchmark',
            horizon_seconds={str(h): str(Decimal(str(history_cpu))*Decimal(h)/72) for h in HORIZONS},
            marginal_hardware_dollar_cost='no new service/instance proposed; existing fixed cost, spare capacity unproved'),
        recommended_policy='Retain approved 72h maximum; no economically justified longer horizon established',
        conditional_research_parameters=dict(renewal_hours_candidates=[1,3,6], absolute_hours_candidates=list(HORIZONS[1:]),
            selected_renewal_hours=None, selected_absolute_hours=None,
            threshold_selection='No economic data sufficient to choose minimum winner multiple or tighter price-to-high gate',
            any_native_exit_pending_disqualifies=True,
            stale_incomplete_or_unverified_history_disqualifies=True,
            original_entry_timers_and_existing_risk_rules_immutable=True),
        next_resource_validation='operational/continuation-resources/OBSERVATION_PLAN.json; NOT AUTHORIZED',
        next_economic_validation='prospective ex ante token-specific exit/liquidity tapes through proposed horizons; NOT AUTHORIZED',
        limitation='No market P&L, continuous economic coverage, paid-provider throughput or 336h service capacity is proved by synthetic tests.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(build(), indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.write_text(result)
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
