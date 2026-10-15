"""Conditional package arithmetic; no workload-frequency or bill prediction."""
from decimal import Decimal
import argparse
import json
from pathlib import Path

PRICE=Decimal('0.525')/1_000_000


def pons_rpc_hybrid(*,monthly_rpc_elements,alchemy_cu_per_element,archive_fraction,
                    existing_alchemy_plan_usd=0,existing_alchemy_unused_cu=0,
                    unchanged_solana_and_stream_usd=0,fallback_fraction=0,
                    added_storage_usd=0,added_operations_usd=0):
    n=Decimal(str(monthly_rpc_elements));cu=Decimal(str(alchemy_cu_per_element))
    archive=Decimal(str(archive_fraction));fallback=Decimal(str(fallback_fraction))
    unused=Decimal(str(existing_alchemy_unused_cu))
    costs=[Decimal(str(v)) for v in (existing_alchemy_plan_usd,
        unchanged_solana_and_stream_usd,added_storage_usd,added_operations_usd)]
    if (any(not v.is_finite() or v<0 for v in [n,cu,unused,*costs])
            or not archive.is_finite() or not fallback.is_finite()
            or not 0<=archive<=1 or not 0<=fallback<=1):
        raise ValueError('provider_sensitivity_inputs')
    # Standard RPC RU treatment is a conditional per-member assumption. Exact
    # endpoint batch/failure classification must be verified before a purchase.
    ru=n*(1+archive)
    chainstack=Decimal(49)+max(Decimal(0),ru-20_000_000)*Decimal(15)/1_000_000
    avoided_alchemy=max(Decimal(0),n*cu-unused)*PRICE
    residual=max(Decimal(0),n*cu*fallback-unused)*PRICE
    extras=costs[2]+costs[3]
    constant=costs[0]+costs[1]
    before=constant+avoided_alchemy;after=constant+chainstack+residual+extras
    return dict(classification='CONDITIONAL_MONTHLY_SENSITIVITY; not observed incidence or invoice',
        pons_rpc_elements=str(n),cu_per_element=str(cu),archive_fraction=str(archive),
        chainstack_request_units=str(ru),chainstack_growth_total_usd=str(chainstack),
        alchemy_replaced_variable_usd=str(avoided_alchemy),fallback_alchemy_usd=str(residual),
        existing_alchemy_fixed_and_solana_usd=str(constant),additional_storage_operations_usd=str(extras),
        original_total_usd=str(before),hybrid_total_usd=str(after),conditional_net_saving_usd=str(before-after))


def build():
    sensitivities=[]
    for n in (1_000_000,5_000_000,10_000_000,20_000_000):
        for cu in (20,26,40,60):
            for archive in (0,.5,1):
                sensitivities.append(pons_rpc_hybrid(monthly_rpc_elements=n,alchemy_cu_per_element=cu,archive_fraction=archive))
    return dict(preferred_next_candidate='Pons standard RPC only, after endpoint parity and capacity proof',
        retain='Alchemy Solana streams and enhanced address history',stream_migration=False,
        rpc_only_growth_monthly_usd=49,included_ru=20_000_000,overage_usd_per_million_ru=15,
        documented_developer=dict(monthly_usd=0,included_ru=3_000_000,rps=25,
            archive_access_proved=False,capability_test_authorized=False),
        public_sources=['https://chainstack.com/pricing/','https://docs.chainstack.com/docs/request-units'],
        verification_date='2026-10-09',expected_net_saving_usd=None,
        expected_savings_reason='No authenticated full-month Pons method/archive/failure/fallback distribution or current plan allowance allocation is available.',
        break_even_if_included_ru_suffice_and_no_fallback_or_extra_costs=dict(
            marginal_alchemy_cu=str(Decimal(49)/PRICE),formula='49 / (0.525 / 1,000,000)',
            current_alchemy_plan_and_solana_charges='retained, not counted as avoided'),
        observations_are_not_monthly_forecasts=True,sensitivities=sensitivities,
        architecture_comparison=[
            dict(architecture='optimized current Alchemy',plan_charges='existing actual contract; unchanged',
                 economic_status='no migration charge; actual Pons monthly demand unknown'),
            dict(architecture='Pons RPC-only hybrid',plan_charges='Growth $49 plus measured RU overages; Alchemy retained',
                 economic_status='smallest source-compatible candidate; conditional only'),
            dict(architecture='standard-RPC hybrid including Pump',plan_charges='same existing package only if spare included RU suffice, otherwise additional overage',
                 economic_status='Solana archive and account/concentration/deadline parity still unproved'),
            dict(architecture='streaming alternative',plan_charges='separate stream tier and recovery RPC; no omitted addon fees',
                 economic_status='not needed by the preferred next move; no subscription or migration prepared')],
        assumptions=['30-day illustrative month; counts are supplied hypotheses, not observed frequencies',
            'per-logical-member RU billing must be verified for batches',
            'full/archive method classification and charged failures must be joined to actual history depth',
            'Growth paid in full; no annual discount, promo, free tier credit or cheaper host assumed',
            'fallback adds Alchemy variable charges; actual retry events only, no blanket multiplier',
            'provided unchanged Alchemy plan, Solana, streams, storage and operations costs remain in both totals'],
        operating_forecast=None,actual_spend_reduced_usd=0,provider_purchases=0)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.write_text(json.dumps(build(),indent=2)+'\n')


if __name__=='__main__':main()
