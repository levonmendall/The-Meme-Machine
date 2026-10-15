"""Whole-machine marginal costs; unmeasured baseline terms remain explicit.

No provider client or activation. Existing fallback/capability requirements and
ceilings are authoritative. Monthly arithmetic never extends a position's hold.
"""
from decimal import Decimal
import json

from .model import PRICE, ROOT, pons, pump, current_v4, short_current_reference


def money(cu):
    return str(Decimal(cu)*PRICE)


def build():
    turns=86400
    components=dict(v4_logs=180,executable_simulation=26,quoter_code=20,
        quoter_manager=26,gas_price=20,quote_canonical_headers=40,history_headers=60)
    breakdown={k:dict(cu_per_turn=v,rpc_cu_72h=v*turns,rpc_only_usd_72h=money(v*turns))
        for k,v in components.items()}
    quiet=pons(72)
    wider=pons(72,log_width=40)
    # The 86,400 intervals do not include a separate deadline observation.
    # Two successful terminal executions (one original partial, one final)
    # each reserve a cold six-element quote plus fresh membership validation.
    # Actual same-evaluation reuse is deliberately not discounted here.
    deadline=pons(3/3600)
    terminal_cu=deadline['rpc_cu']+2*152
    terminal_elements=deadline['rpc_elements']+2*7
    terminal_physical=deadline['physical_attempts_without_failures']+2*3
    daily=[]
    profiles=dict(light=dict(survivor={},current={}),
        moderate=dict(survivor=dict(events_per_turn=1,event_period_turns=10),
            current=dict(events_per_turn=1,event_period_turns=10)),
        heavy=dict(survivor=dict(blocks_per_turn=40,events_per_turn=15,missing_sender=True),
            current=dict(events_per_turn=25,missing_sender=True)))
    for name,kw in profiles.items():
        ps=pons(24,**kw['survivor']);pc=current_v4(24,**kw['current'])
        terms=dict(pump_survivor_rpc=pump(24)['rpc_only_modeled_usd'],
            pump_current_postgrad_rpc=pump(24,current=True)['rpc_only_modeled_usd'],
            pons_survivor_rpc=ps['rpc_only_modeled_usd'],pons_current_v4_rpc=pc['rpc_only_modeled_usd'])
        total=sum(Decimal(v) for v in terms.values())
        daily.append(dict(scenario=name,assumptions=kw,
            occupancy='one position in EACH of four families for 24h; Current requires eligible bridge; hypothetical operations beyond first-position authority',
            rpc_maintenance_usd_24h_by_family=terms,rpc_maintenance_usd_24h=str(total),
            rpc_maintenance_usd_30d=str(total*30),
            month_classification='repeated separately authorized lifecycles at assumed occupancy; no 30-day position or authority',
            pons_unshared_physical_rps=ps['minimum_physical_rps_under_scenario']+pc['minimum_physical_rps_under_scenario'],
            fits_local_two_rps=False,
            complete_total_usd_24h=None,complete_total_usd_30d=None,
            unmeasured_additive_terms=['Pump filtered stream bytes and required gap hydration',
                'shared observation/qualification and conditional entry/exit/addition work',
                'provider outages, canonical replay, shared valuations and actual tariff'],
            production_forecast=False))
    horizons=[]
    for h in (.25,1,6,24,72):
        horizons.append(dict(hours=h,pump_survivor_rpc=pump(h)['rpc_only_modeled_usd'],
            pump_current_postgrad_rpc=pump(h,current=True)['rpc_only_modeled_usd'],
            pump_current_curve_snapshot_rpc=short_current_reference(h,family='pump')['rpc_only_modeled_usd'],
            pons_current_curve_fixture_rpc=short_current_reference(h,family='pons')['rpc_only_modeled_usd'],
            pons_current_v4_rpc=current_v4(h)['rpc_only_modeled_usd'],
            pons_survivor_rpc=pons(h)['rpc_only_modeled_usd'],
            current_authority='original economic maximum including eligible 36h bridge; 72h arithmetic is not allowed holding'))
    # Existing measured qualification scenario, rather than invented per-attempt
    # allowances. It does not bound a novel candidate or forecast arrival rate.
    from engineering.solana_capacity.proof_limits import PUBLISHED
    old=json.loads((ROOT/'engineering/robinhood_payg/decisions.json').read_text())['cases'][0]
    unit={}
    for label,key in (('nomination','nomination_usage'),('nomination_plus_authentication','nomination_plus_authentication_usage')):
        row=old[key];methods=row['methods']
        cu=sum(PUBLISHED['robinhood'][m]*n for m,n in methods.items())
        unit[label]=dict(methods=methods,rpc_cu=cu,usd=money(cu),
            classification='previous deterministic native captured-lineage fixture; not measured provider invoice or worst case')
    return dict(schema='whole-system-alchemy-cost-v1',market_provider_calls=0,
        baseline_pons_72h=quiet,pons_72h_breakdown=breakdown,
        concurrent_pump_provider_evidence=json.loads((ROOT/'operational/continuation-resources/CONCURRENT_PROVIDER_EVIDENCE.json').read_text()),
        deployed_additional_savings_usd='0',
        newly_implemented=dict(exact_block_identity_pair=dict(
            reads='quoter code and poolManager() only, keyed by authenticated credential fingerprint, exact block number/hash and quoter',
            storage='one bounded transient pair on existing RPC session; no additional DB/service',
            numeric_fenced_same_block_two_quotes=dict(before_rpc_elements=12,after_rpc_elements=10,
                before_rpc_cu=264,after_rpc_cu=218,before_physical=4,after_physical=4),
            all_86400_heads_advancing_incremental_savings_cu=0,
            verified_eip1898_existing_reuse_incremental_savings_cu=0,
            cross_block_identity_or_quote_reuse=False,fresh_gas_and_canonical_fences=True,
            provider_response_bytes='fixture measurement separately; real quoter payload size unmeasured')),
        already_implemented=['Pump snapshot sharing/qualification-only omission and compact holder evidence',
            'Pons same-evaluation exact-quantity quote reuse; fresh head and mutable gas guard',
            'Current rolling curve/V4 history; incremental independent Survivor history',
            'hash-bound receipts/senders and proved EIP-1898 immutable state reuse',
            'authenticated adaptive wider logs, neutral pool-union acquisition and bounded overload splitting',
            'scout-first candidate work, exact filters, selective hydration and admission-closed optional-work rejection',
            'native quote/price/journal retention and paused Ramses/Meteora'],
        existing_conditional_wider_logs=dict(status='NOT_ENABLED; exact nonempty filter comparison and actual app capability required',
            expected_ordinary_blocks_per_turn=30,existing_comparison_width=40,
            before_rpc_elements=quiet['rpc_elements'],after_rpc_elements=wider['rpc_elements'],
            before_rpc_cu=quiet['rpc_cu'],after_rpc_cu=wider['rpc_cu'],
            before_physical=quiet['physical_attempts_without_failures'],after_physical=wider['physical_attempts_without_failures'],
            rpc_only_usd_72h=wider['rpc_only_modeled_usd'],
            savings_usd_72h=str(Decimal(quiet['rpc_only_modeled_usd'])-Decimal(wider['rpc_only_modeled_usd'])),
            physical_savings_classification='log batches unchanged; only reduced authentication rotation attempts differ',
            logical_element_limit_still_exceeded=wider['rpc_elements']>500000),
        cost_interpretation=dict(arbitrary_cost_targets_are_acceptance_gates=False,
            retired_targets='The $1 and 80% objectives are retired; adequacy and safety determine acceptance.',
            single_fresh_simulation_alone_usd_72h=money(26*turns),
            fresh_simulation_gas_and_original_two_quote_headers_usd_72h=money(86*turns),
            classification='method-specific floors within unchanged acquisition contract, not universal theoretical minima',
            full_current_quiet_rpc_usd_72h=quiet['rpc_only_modeled_usd'],
            simulation_component_is_not_total_cost=True,
            further_cross_block_identity_work='NOT_PURSUED; no verified immutable deployment/upgrade proof, no production assumption or savings'),
        acquisition_alternatives=[
            dict(name='optimized authenticated incremental polling',status='CURRENT',
                savings='only missing intervals; expensive overlapping Current windows already removed',
                limitation='ten-block fallback still buys empty intervals as chain advances'),
            dict(name='existing wider filtered polling',status='CONDITIONAL_EXISTING_CAPABILITY',
                limitation='nonempty exact comparison, entitlement, payload/tail/recovery bounds; no larger default enabled'),
            dict(name='authenticated event-driven acquisition',status='UNPROVEN_NOT_ENABLED',
                limitation='must prove complete event delivery and sealed empty intervals, canonical ordering, reconnect gap recovery and net byte cost'),
            dict(name='shared local immutable evidence plus fresh state',status='CURRENT',
                limitation='exact credential/block/filter/quantity semantics; no incomplete history or changing gas reuse'),
            dict(name='public scout plus authoritative Alchemy',status='CURRENT',
                limitation='scout prioritizes; quiet public feed cannot certify empty economic history'),
            dict(name='alternative canonical provider',status='UNVERIFIED_NOT_RECOMMENDED',
                limitation='actual coverage, account pricing, reliability and authority equivalence unavailable; no new client/service')],
        evm_stream_break_even=dict(cu_per_delivered_byte='0.04',
            tariff_status='published prior model, actual billing/notification envelope unverified',
            ten_block_log_component_bytes_per_second=1500,
            forty_block_log_component_bytes_per_second=500,
            classification='necessary traffic break-even BEFORE receipt/header/reconnect/HTTP-reconciliation costs; no completeness guarantee'),
        per_position_rpc_costs=horizons,whole_machine_occupancy_scenarios=daily,
        pons_quiet_successful_terminal_reference=dict(
            classification='conditional quiet/no-failure arithmetic, not a capacity or profitability guarantee',
            original_partial_executions=1,final_executions=1,
            quote_plus_execution_membership_cu_each=152,
            quote_plus_execution_membership_elements_each=7,
            additional_deadline_and_terminal_cu=terminal_cu,
            additional_deadline_and_terminal_elements=terminal_elements,
            additional_deadline_and_terminal_physical=terminal_physical,
            rpc_cu_72h_including_terminal=quiet['rpc_cu']+terminal_cu,
            rpc_elements_72h_including_terminal=quiet['rpc_elements']+terminal_elements,
            physical_72h_including_terminal=quiet['physical_attempts_without_failures']+terminal_physical,
            rpc_only_usd_72h_including_terminal=money(quiet['rpc_cu']+terminal_cu),
            incremental_held_pons_native_stream_bytes=0,
            recovery_actual_expected_spend=None,
            original_separate_recovery_spend_ceiling_usd='2',
            holding_reference_plus_recovery_ceiling_usd=str(Decimal(money(quiet['rpc_cu']+terminal_cu))+2),
            budget_attribution='Holding arithmetic starts at original entry; runtime phase ledgers attribute actual use. Bootstrap and recovery maxima are not extra expected bills.',
            repeated_pending_exit_attempts='additional recovery work subject to original finite limits; not included as fabricated successful executions'),
        shared_baseline=dict(complete_cost_usd_24h=None,
            admission_closed_optional_discovery_rpc=0,paused_ramses_meteora_rpc=0,
            before_admission='existing public scout signals and bounded authenticated candidate work; arrivals and Pump delivered bytes unmeasured',
            measured_native_unit_examples=unit,
            no_unmeasured_current_allowance_invented=True),
        recovery=dict(original_maximum_seconds=3600,rpc_cu=2400000,rpc_elements=50000,physical_attempts=50000,
            native_bytes=1073741824,http_bytes=134217728,modeled_spend_usd='2',
            pons_one_hour_quiet_rpc=pons(1),ordinary_actual_recovery_spend=None,
            maximums_are_not_expected_cost=True),
        safety='All original quotes, gas, native exits, history completeness and canonical checks retained. No economic thresholds, holds, allowances or services changed.',
        actual_bill_reduction_proven=False,disposition='BLOCKED_BY_SPECIFIC_PROVIDER_OR_RESOURCE_CONSTRAINT')
