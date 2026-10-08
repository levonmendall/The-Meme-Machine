"""Reproducible diagnostic 30-day projections; no claim of observed billing.

Dense synthetic profiles are normalized at the independently retained chain
header rate. A separate empty-market floor makes low activity assessable without
pretending dense fixtures are representative of live Robinhood market traffic.
Current final/position work is unchanged and unmeasured; it is an explicit
unknown additive term, never silently counted as zero.
"""
import json
from math import ceil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SECONDS=30*86400


def main():
    retained=json.loads((ROOT/'operational/pump-provider-finalization/NEXT_PROOF.json').read_text())
    pair=retained['pons_cold_projection']['block_header_pairs'];a,b=pair
    rate=(b[0]-a[0])/(b[1]-a[1]);blocks=rate*SECONDS
    traces=json.loads((Path(__file__).with_name('collector-comparison.json')).read_text())['scenarios']
    decisions=json.loads((Path(__file__).with_name('decision-comparison.json')).read_text())['cases']
    quote=decisions[0]['position_quote_usage'];position=decisions[0]['position_turn_usage'];floor=[];dense=[]
    schedule=json.loads((ROOT/'meme_machine/runtime/alchemy-cu-schedule.json').read_text())
    weights=schedule['methods'];throughput={**weights,**schedule['throughput_overrides']}
    auth=decisions[0]['nomination_plus_authentication_usage'];nom=decisions[0]['nomination_usage']
    auth_methods={k:n-nom['methods'].get(k,0) for k,n in auth['methods'].items()
                  if n!=nom['methods'].get(k,0)}
    auth_cu=sum(throughput[k]*n for k,n in auth_methods.items())
    factory=blocks/10
    for trace,cohorts,occupancy in zip(traces,(1,1,2),(.05,.25,1)):
        factor=blocks/trace['blocks']
        row=dict(scenario=trace['scenario'],classification='SYNTHETIC_SUSTAINED_TRACE_NORMALIZATION',
            block_rate=rate,trace_cycles_30d=factor,candidates_in_transport_cohort=trace['candidates'],
            economic_event_rate=trace['optimized']['methods']['eth_getTransactionReceipt']/trace['blocks']*rate,
            prospective_candidate_recall=trace['candidate_recall'],current_additive_cost='UNMEASURED',
            final_qualification_and_position_additive_cost='not included in collector normalization',
            verified_billed_cu=None,representative_live_workload=False)
        for key in ('baseline','optimized'):
            work=trace[key]
            row[key]=dict(diagnostic_estimated_cu=work['diagnostic_cu']['known_estimated_cu']*factor+
                (factory*60 if key=='baseline' else 0),
                physical_http_attempts=work['physical_http_attempts']*factor+
                    (factory/4 if key=='baseline' else 0),
                response_bytes=work['response_bytes']*factor,
                provider_requests_per_second=work['physical_http_attempts']/trace['blocks']*rate+
                    (rate/40 if key=='baseline' else 0),
                logical_rpc_elements_per_second=work['logical_rpc_elements']/trace['blocks']*rate+
                    (rate/10 if key=='baseline' else 0),
                diagnostic_throughput_cu_per_second=sum(throughput[k]*n for k,n in work['methods'].items())/
                    trace['blocks']*rate+(rate/10*throughput['eth_getLogs'] if key=='baseline' else 0),
                collector_cpu_core_equivalent=work['cpu_seconds']/trace['blocks']*rate,
                measured_offline_peak_rss_bytes=work['maximum_rss_bytes'])
        row['response_bytes_exclude_factory_and_all_other_work']=True
        row['within_existing_2rps_alchemy_ceiling']=row['optimized']['provider_requests_per_second']<=2
        row['smallest_integer_collector_physical_ceiling_rps']=ceil(row['optimized']['provider_requests_per_second'])
        row['minimum_collector_throughput_cu_per_second']=row['optimized']['diagnostic_throughput_cu_per_second']
        row['within_documented_free_300_cups']=row['minimum_collector_throughput_cu_per_second']<=300
        row['complete_system_capacity_certified']=False
        row['required_complete_system_rps']='collector demand + Current + funded maintenance + authentication + qualification + recovery; deadline/burst headroom also unmeasured'
        row['under_aspirational_10m']=row['optimized']['diagnostic_estimated_cu']<10_000_000
        dense.append(row)
        # These lower bounds include only the mandatory canonical ten-block
        # range stream for continuously hydrated cohorts, plus authentic funded
        # turns at the adopted forward worker's three-second cadence. All omitted
        # authentication, flow receipts, entries, Current and recovery add cost.
        exit_count=SECONDS/3*occupancy
        floor.append(dict(scenario=trace['scenario'],classification='MODELED_REQUIRED_WORK_LOWER_BOUND',
            simultaneously_continuously_hydrated_cohorts=cohorts,mean_survivor_funded_positions=occupancy,
            optimized_canonical_range_cu=cohorts*factory*60,
            optimized_position_exit_quote_cu=exit_count*quote['diagnostic_cu']['known_estimated_cu'],
            optimized_position_warm_turn_cu=exit_count*position['diagnostic_cu']['known_estimated_cu'],
            baseline_factory_discovery_cu=factory*60,
            baseline_known_subtotal_cu=(cohorts+1)*factory*60+exit_count*position['diagnostic_cu']['known_estimated_cu'],
            optimized_known_subtotal_cu=cohorts*factory*60+exit_count*position['diagnostic_cu']['known_estimated_cu'],
            comparison_cadence='same three-second funded workload for both architectures; b1 reference Worker originally ran at five seconds, the approved forward work adopts three',
            optimized_known_physical_http_attempts=cohorts*factory/4+exit_count*position['physical_http_attempts'],
            optimized_known_physical_rps=cohorts*rate/40+occupancy*position['physical_http_attempts']/3,
            optimized_known_logical_rpc_elements=cohorts*factory+exit_count*sum(position['methods'].values()),
            optimized_known_response_bytes=exit_count*position['response_bytes'],
            response_bytes_exclude_canonical_ranges_and_missing_terms=True,
            missing_terms=['Current qualification/positions','launch/graduation authentication',
                'swap receipts/headers','candidate state/qualification/entry quotes',
                'position flow/state checks','gaps/retries','canonical head probes'],
            verified_minimum_billed_cu=None,verified_billed_cu=None,
            complete_system_forecast=False,under_aspirational_10m=False))
    result=dict(schema='robinhood-scout-cost-projection-v2',days=30,
        diagnostic_schedule='meme_machine/runtime/alchemy-cu-schedule.json',
        header_rate_source='operational/pump-provider-finalization/NEXT_PROOF.json',
        header_pairs=pair,block_rate=rate,blocks_30d=blocks,
        public_observation=dict(market_getLogs_elements_30d=factory,
            pool_getLogs_elements_per_continuous_cohort_30d=factory,
            market_plus_one_pool_cohort_physical_http_attempts_30d=blocks/40*3,
            physical_requests_per_second=rate/40*3,
            provider='Robinhood public RPC; not Alchemy',
            public_response_bytes='UNMEASURED at representative live activity',
            subscription_bytes='UNMEASURED; existing sequencer telemetry counts decoded deliveries, not wire framing',
            scope='one header batch, one market filter batch, one exact-Pons pool batch per forty blocks',
            public_provider_sustainability='UNVERIFIED',direct_alchemy_rpc_elements=0,verified_billed_alchemy_cu=None),
        routine_alchemy_broad_discovery_cu=dict(baseline=factory*60,optimized=0),
        startup_global_seven_day_factory_scan_cu=dict(baseline=rate*7*86400/10*60,
            optimized=0,classification='one-time method-weight estimate, not repeated monthly'),
        floors=floor,sustained_trace_projections=dense,
        aspirational_target_cu_30d=10_000_000,target_is_acceptance_gate=False,
        hard_production_cu_budget=None,
        acceptance_objective='Complete strategy behavior, candidate preservation, original deadlines and position safety at sustainable measured throughput; minimize avoidable consumption afterward',
        cost_target_observation='Modeled continuous-history subtotals exceed the aspiration; this does not fail strategy acceptance',
        measured_cost_coefficients=dict(
            canonical_continuous_ten_block_range_stream_cu_30d=factory*weights['eth_getLogs'],
            canonical_range_physical_rps_per_forty_block_batch=rate/40,
            graduation_cold_authentication=dict(methods=auth_methods,
                diagnostic_estimated_cu=sum(weights[k]*n for k,n in auth_methods.items()),
                diagnostic_throughput_cu=auth_cu,
                physical_http_attempts=auth['physical_http_requests']-nom['physical_http_requests'],
                logical_rpc_elements=auth['logical_requests']-nom['logical_requests'],
                response_bytes=auth['response_bytes']-nom['response_bytes']),
            survivor_exit_quote=quote,
            survivor_funded_warm_turn=position,
            survivor_eligible_quote_ladder=decisions[0]['points'][0]['optimized_quote_work'],
            survivor_weak_quote_ladder_cu=0,
            current_full_qualification_and_position_units='UNMEASURED; must be added, never zero-filled'),
        capacity_investigation=dict(existing_application_physical_ceiling_rps=2,
            physical_ceiling_is_not_alchemy_account_cups=True,
            documented_free_account_throughput_cups=300,
            documented_payg_account_throughput_cups=10000,
            account_specific_throughput_verified=False,
            documentation_checked_at='2026-10-08',
            sources=['https://www.alchemy.com/docs/reference/throughput',
                     'https://www.alchemy.com/docs/reference/pricing-plans',
                     'https://www.alchemy.com/docs/reference/compute-unit-costs'],
            current_two_rps_complete_workload_status='NOT_CERTIFIED; insufficient even for all three sustained dense collector traces',
            smallest_justified_increase='At least 3 / 6 / 7 physical RPS for the measured dense collector alone, plus all other work and deadline headroom. No complete-system limit or purchase is justified before genuine combined measurements.',
            proposed_capacity_change=None,
            narrow_architectural_option=dict(status='INVESTIGATED_NOT_IMPLEMENTED_OR_VALIDATED',
                option='Supported authenticated exact-Pons filtered logs subscription with existing journal, receipt authentication, canonical boundaries and bounded ten-block recovery',
                purpose='May avoid empty canonical range polling without weakening authority or transaction evidence',
                subscription_delivery_diagnostic_cu_per_byte=.04,
                one_range_stream_subscription_delivery_break_even_bytes_per_second=rate/10*60/.04,
                excluded_costs='subscription establishment, receipts/headers, reorgs, outage replay, quotes and all Current work',
                required_evidence='Robinhood filter support, complete ordering, measured delivered bytes, reconnect/gap recovery and exact economic equivalence; requires separate bounded provider authorization',
                dense_receipt_driver_remains=True)),
        actual_billing_evidence='billing-availability.json: app/method breakdown denied; allowed account-level window returned no usage rows; neither is zero billed CU',
        canonical_role_changed=False,provider_limits_changed=False,
        billing_measurement='UNMEASURED',verified_minimum_requirement='UNMEASURED without separately authorized provider measurements',
        lowest_realistic_complete_monthly_requirement=dict(normal=None,busy_market=None,stress=None,
            status='NOT_ESTABLISHED: genuine promotion, swap, Current, funded-position and recovery rates are not available. Conditional lower bounds and dense profiles are reported separately, not relabeled as complete representative forecasts.'),
        interpretation='The trace rates are synthetic capacity scenarios; use the lower bounds and measured coefficients to substitute genuine prospective rates. Consumption is subordinate to complete operation. No scenario licenses candidate loss, weaker evidence or spending authorization.')
    Path(__file__).with_name('cost-projection.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
