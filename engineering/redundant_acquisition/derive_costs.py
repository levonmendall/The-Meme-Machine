"""Derive component sensitivities from the retained offline measurements.

No market providers, credentials, funding or operational state are accessed.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from meme_machine.operational.artifact_storage import Scratch


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'operational/redundant-acquisition'
HOURS = (24, 72, 168, 720)
RATE = Decimal('0.525') / 1_000_000


def component(cu, starts, elements, interval, hours, owners=1):
    cycles = hours * 3600 // interval
    return dict(observation_cycles=cycles * owners,
                modeled_cu=cu * cycles * owners,
                physical_http_starts=starts * cycles * owners,
                logical_rpc_elements=elements * cycles * owners,
                public_price_assumption_usd=str(RATE * cu * cycles * owners),
                actual_account_charge_usd=None)


def main():
    with Scratch() as scratch:
        source = OUT / 'OFFLINE_WORKLOADS.json'
        evidence = json.loads(source.read_text())
        result = deepcopy(evidence['cost_model'])
        result['derived_from'] = dict(path=str(source.relative_to(ROOT)),
            sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            measured_implementation_commit=evidence['source_commit'],
            command='PYTHONDONTWRITEBYTECODE=1 /opt/meme-machine/.venv/bin/python -m engineering.redundant_acquisition.derive_costs')
        # Current Pons's original one-event specimen is preserved, not relabeled
        # an independently measured quiet Current workload. Each regime keeps
        # its own interval; no four-Survivor cohort discount is extrapolated.
        shapes = {
            'published_specimen_sum': {
                'pump_current': (120, 6, 6, 5),
                'pump_survivor': (100, 5, 5, 5),
                'pons_current': (232, 4, 9, 5),
                'pons_survivor': (232, 4, 9, 3)},
            'same_evidence_candidate': {
                'pump_current': (120, 6, 6, 5),
                'pump_survivor': (100, 5, 5, 5),
                'pons_current': (232, 4, 9, 5),
                'pons_survivor': (232, 4, 9, 3)},
            'quiet_survivor_model_correction': {
                'pump_current': (120, 6, 6, 5),
                'pump_survivor': (100, 5, 5, 5),
                'pons_current': (232, 4, 9, 5),
                'pons_survivor': (212, 3, 8, 3)},
            'existing_pump_optimized_inactive_with_quiet_survivor': {
                'pump_current': (60, 3, 3, 5),
                'pump_survivor': (40, 2, 2, 5),
                'pons_current': (232, 4, 9, 5),
                'pons_survivor': (212, 3, 8, 3)}}
        portfolio = []
        for name, shapes_by_regime in shapes.items():
            for owners_per_regime in (1, 2):
                for hours in HOURS:
                    parts = {regime: component(*shape, hours, owners_per_regime)
                             for regime, shape in shapes_by_regime.items()}
                    usd = next(r for r in result['pons_usd_source_shaped_sensitivity'] if r['hours'] == hours)
                    fields = ('observation_cycles', 'modeled_cu', 'physical_http_starts', 'logical_rpc_elements')
                    total = {k: sum(p[k] for p in parts.values()) for k in fields}
                    total['public_price_assumption_usd'] = str(RATE * total['modeled_cu'])
                    total['actual_account_charge_usd'] = None
                    portfolio.append(dict(name=name, positions=4 * owners_per_regime,
                        hours=hours, independent_core_components=parts,
                        unshared_core_specimen_sum=total,
                        conditional_shared_pons_usd_once=usd,
                        core_plus_one_usd_component_usd=str(RATE * (total['modeled_cu'] + usd['modeled_cu'])),
                        expected_total_cost_usd=None,
                        basis='continuous synthetic component sum, not observed activity or a worst-case bound',
                        original_path_and_candidate_core_identical=name in ('published_specimen_sum', 'same_evidence_candidate'),
                        discounts_for_shared_history_or_headers=0,
                        additional_original_path_fallback_cost_usd=None))
        result['portfolio_component_sensitivities'] = portfolio
        result['portfolio_assumptions'] = [
            'Pump/Current and Pons/Current have five-second intervals; Pons Survivor has three seconds',
            'Current Pons uses the prior one-event specimen, not an asserted quiet Current measurement',
            'Pons USD is counted once only for an existing compatible shared reader in one process',
            'SOL USD, discovery, streaming, qualifications, execution, recovery, failures and infrastructure remain unknown',
            'eight $25 positions imply $200 total, $100 per family and $50 per regime within original $500 static limits; actual admission remains required',
            'no source rate, capital limit, cache, feature flag, provider plan or service is changed']
        result['bounded_event_costs'] = {
            r['name']: dict(before=r['before'], after=r['after'],
                            same_market_evidence=True,
                            economic_and_protective_parity=r['position_risk_and_execution_equivalence'],
                            monthly_occurrence_rate=None)
            for r in evidence['native_scenarios']}
        result['historical_recovery_costs'] = evidence['history_reuse']
        result['new_scout_saving'] = dict(account_data_bytes_avoided_per_frame=7,
            protobuf_bytes_avoided_in_measured_fixture=7,
            actual_metered_bytes_avoided=None,
            public_usd_avoided_per_million_frames=str(Decimal(7) * 1_000_000 * 75 / Decimal(10)**12),
            frequency_frames_per_month=None, authenticated_billing_savings_usd=None)
        result['replacement_break_even']['evm_setup_cu_per_subscribe'] = 10
        result['replacement_break_even']['evm_teardown_cu_per_unsubscribe'] = 10
        result['replacement_break_even']['evm_rule'] = (
            '0.04*delivered_bytes + 10*subscribe_elements + 10*unsubscribe_elements '
            '+ fallback_CU + reconciliation_CU + infrastructure_CU_equivalent '
            '< 60*eliminated_log_elements')
        assert len(portfolio) == 32
        month = [r for r in portfolio if r['name'] == 'published_specimen_sum'
                 and r['positions'] == 4 and r['hours'] == 720][0]
        assert Decimal(month['unshared_core_specimen_sum']['public_price_assumption_usd']) == Decimal('228.251520')
        for n in evidence['native_scenarios']:
            assert n['position_risk_and_execution_equivalence']
        (OUT / 'COST_MODEL.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        scratch.success = True


if __name__ == '__main__':
    main()
