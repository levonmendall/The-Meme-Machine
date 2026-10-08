"""Conditional 24-hour/30-day models; actual usage is kept separate.

Event/candidate rates and Current allowances are assumptions, never live facts.
No model is a complete production quote. Funding safety has no spending cutoff.
"""
import argparse
import json
from math import ceil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
RATE_USD_PER_M_CU=.525
EVM_CU_PER_BYTE=.04
SOLANA_CU_PER_BYTE=.0002


def payloads():
    """Measured historical log sizes plus a synthetic subscription envelope."""
    from meme_machine.lanes.pons.abi import topic
    from meme_machine.lanes.pons.pons_historical import FACTORY,LAUNCH,GRADUATION,MANAGER,ACTIVITY
    curve={topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)'),
           topic('CurveSell(address,address,uint256,uint256,uint256,uint256)')}
    def walk(row):
        if isinstance(row,dict):
            if all(k in row for k in ('topics','blockNumber','data','address')):yield row
            for value in row.values():yield from walk(value)
        elif isinstance(row,list):
            for value in row:yield from walk(value)
    rows={}
    for name in ('protocol_capture_35370277849.json','pons_lineage_35378762520.json'):
        p=ROOT/'tests/lanes/pons/fixtures'/name
        for log in walk(json.loads(p.read_text())):
            rows[json.dumps(log,sort_keys=True)]=log
    sizes={'curve_and_factory':[],'pool_activity':[]}
    # The preserved graduation captures have no complete V4 activity sample.
    # Use the explicitly synthetic complete Swap fixture for that coefficient.
    from engineering.pons_history.fixtures import Tape
    for log in Tape(candidates=1).logs:
        if log['address'].lower()==MANAGER and log['topics'][0] in ACTIVITY:
            rows[json.dumps(log,sort_keys=True)]=log
    for log in rows.values():
        if not log['topics']:continue
        signature=log['topics'][0].lower();address=log['address'].lower()
        kind=('curve_and_factory' if signature in curve or
              address==FACTORY and signature in (LAUNCH,GRADUATION) else
              'pool_activity' if address==MANAGER and signature in ACTIVITY else None)
        if kind:
            event=dict(jsonrpc='2.0',method='eth_subscription',params=dict(
                subscription='0x'+'0'*32,result=log))
            sizes[kind].append(len(json.dumps(event,separators=(',',':')).encode()))
    return {name:dict(samples=len(values),mean_notification_payload_bytes=sum(values)/len(values) if values else None,
        minimum_bytes=min(values) if values else None,maximum_bytes=max(values) if values else None,
        basis=('authentic retained historical raw logs' if name=='curve_and_factory' else
               'synthetic ABI-shaped V4 Swap fixture')+'; synthetic subscription wrapper; not billed delivery bytes')
        for name,values in sizes.items()}


def build():
    source=json.loads((ROOT/'operational/pump-provider-finalization/NEXT_PROOF.json').read_text())
    a,b=source['pons_cold_projection']['block_header_pairs'];rate=(b[0]-a[0])/(b[1]-a[1])
    decisions=json.loads(Path(__file__).with_name('decisions.json').read_text())['cases']
    case=decisions[0];warm=case['position_turn_usage'];qualification=case['points'][0]['optimized_quote_work']
    auth=case['nomination_plus_authentication_usage'];nom=case['nomination_usage']
    weights=json.loads((ROOT/'meme_machine/runtime/alchemy-cu-schedule.json').read_text())['methods']
    auth_methods={m:n-nom['methods'].get(m,0) for m,n in auth['methods'].items() if n!=nom['methods'].get(m,0)}
    auth_cu=sum(weights[m]*n for m,n in auth_methods.items())
    raw=payloads();market_bytes=raw['curve_and_factory']['mean_notification_payload_bytes']
    pool_bytes=raw['pool_activity']['mean_notification_payload_bytes']
    # These replaceable scenarios are workload assumptions. They are not
    # candidate caps, enforced acquisition limits or promises of opportunity.
    scenarios=[dict(name='quiet',cohorts=1,canonical_watch_hours=1,funded_occupancy=.05,
        curve_events_per_hour=8,pool_events_per_hour=4,candidates_per_day=4,qualified_per_day=1,
        current_attempts_per_hour=1,canonical_event_share=.25,gap_blocks=0,gaps_per_day=0),
      dict(name='normal',cohorts=1,canonical_watch_hours=6,funded_occupancy=.25,
        curve_events_per_hour=360,pool_events_per_hour=120,candidates_per_day=48,qualified_per_day=8,
        current_attempts_per_hour=12,canonical_event_share=.25,gap_blocks=0,gaps_per_day=0),
      dict(name='high_activity',cohorts=2,canonical_watch_hours=24,funded_occupancy=1,
        curve_events_per_hour=7200,pool_events_per_hour=2000,candidates_per_day=480,qualified_per_day=80,
        current_attempts_per_hour=120,canonical_event_share=.5,gap_blocks=0,gaps_per_day=0),
      dict(name='recovery',cohorts=1,canonical_watch_hours=6,funded_occupancy=.25,
        curve_events_per_hour=360,pool_events_per_hour=120,candidates_per_day=48,qualified_per_day=8,
        current_attempts_per_hour=12,canonical_event_share=.25,gap_blocks=round(rate*3600),gaps_per_day=1)]
    projections=[]
    for scenario in scenarios:
        for window in (10,40):
            turns=scenario['canonical_watch_hours']*3600/3*scenario['cohorts']
            range_elements=ceil(min(40,rate*3)/window)*turns
            boundary_cu=turns*40
            canonical_events=scenario['pool_events_per_hour']*24*scenario['canonical_event_share']
            # Conservative one receipt + half a unique header per event.
            # Repeated same-block transactions and cache hits reduce this term.
            flow_cu=canonical_events*30
            position_turns=86400/3*scenario['funded_occupancy']
            position_cu=position_turns*warm['diagnostic_cu']['known_estimated_cu']
            auth_daily=auth_cu*scenario['candidates_per_day']
            quote_daily=qualification['diagnostic_cu']['known_estimated_cu']*scenario['qualified_per_day']
            reconstruction=range_elements*60+boundary_cu+flow_cu
            current_range=[4000*scenario['current_attempts_per_hour']*24,
                           12000*scenario['current_attempts_per_hour']*24]
            gap_cu=ceil(scenario['gap_blocks']/window)*60*scenario['gaps_per_day']
            for architecture in ('A','B','C','D'):
                observation_cu=subscription_cu=0.;subscription_bytes=0.
                if architecture=='B':
                    # Exact market + one pool cohort, using existing forty-block
                    # scheduling. Wider pages reduce members, not HTTP rounds.
                    observation_cu=(ceil(40/window)*60*(1+scenario['cohorts'])+40)*rate/40*86400
                elif architecture in ('C','D'):
                    subscription_bytes=24*(scenario['curve_events_per_hour']*market_bytes+
                        scenario['pool_events_per_hour']*pool_bytes)
                    subscription_cu=subscription_bytes*EVM_CU_PER_BYTE+20
                    # Fixed ten-block recovery in C; adaptive compared range in D.
                    gap_cu=ceil(scenario['gap_blocks']/(10 if architecture=='C' else window))*60*scenario['gaps_per_day']
                # Each architecture preserves canonical selected-candidate and
                # funded work. C/D get no speculative economic hydration discount.
                known=reconstruction+position_cu+auth_daily+quote_daily+observation_cu+subscription_cu+gap_cu
                lower,upper=[known+c for c in current_range]
                physical=(2*turns+canonical_events*1.5/50+
                    position_turns*warm['physical_http_attempts']+
                    (auth['physical_http_requests']-nom['physical_http_requests'])*scenario['candidates_per_day']+
                    qualification['physical_http_attempts']*scenario['qualified_per_day']+
                    ceil(scenario['gap_blocks']/(10 if architecture=='C' else window)/4)*scenario['gaps_per_day'])
                if architecture=='B':physical+=3*rate/40*86400
                dollars=lambda cu:cu/1e6*RATE_USD_PER_M_CU
                projections.append(dict(architecture=architecture,scenario=scenario['name'],window_blocks=window,
                    wider_range_status='CURRENT_SAFE_FALLBACK' if window==10 else 'CONDITIONAL_AFTER_AUTHORIZED_COMPARISON',
                    assumptions=scenario,diagnostic_components_cu_24h=dict(canonical_reconstruction=reconstruction,
                        warm_survivor_position_maintenance=position_cu,cold_graduation_authentication=auth_daily,
                        eligible_survivor_quote_ladders=quote_daily,paid_observation_http=observation_cu,
                        subscription_byte_estimate=subscription_cu,gap_log_repair=gap_cu),
                    current_unmeasured_allowance_cu_24h=current_range,
                    modeled_cu_24h_range=[lower,upper],modeled_cu_30d_range=[lower*30,upper*30],
                    modeled_usd_24h_range=[dollars(lower),dollars(upper)],
                    modeled_usd_30d_range=[dollars(lower*30),dollars(upper*30)],
                    subscription_delivery_bytes_24h=subscription_bytes,
                    subscription_delivery_cu_24h=subscription_cu,
                    known_physical_http_attempts_24h=physical,known_physical_rps=physical/86400,
                    physical_demand_excludes_Current_and_retries=True,
                    current_physical_and_deadline_capacity_certified=False,
                    cost_per_coverage_hour_usd_range=[dollars(lower)/24,dollars(upper)/24],
                    blended_cost_per_discovered_candidate_usd_range=[dollars(lower)/scenario['candidates_per_day'],dollars(upper)/scenario['candidates_per_day']],
                    blended_cost_per_fully_qualified_candidate_usd_range=[dollars(lower)/scenario['qualified_per_day'],dollars(upper)/scenario['qualified_per_day']],
                    canonical_reconstruction_cu_per_discovered_opportunity=(reconstruction+auth_daily)/scenario['candidates_per_day'],
                    warm_survivor_position_cu_per_position_hour=3600/3*warm['diagnostic_cu']['known_estimated_cu'],
                    gap_log_repair_cu_per_missing_interval=gap_cu/scenario['gaps_per_day'] if scenario['gaps_per_day'] else None,
                    actual_billed_cu=None,complete_production_forecast=False,
                    unmeasured_additive_terms=['Current funded-position work','conditional entries/scaling/exits',
                        'canonical additional head/state checks','retries/timeouts/reorg churn',
                        'extra non-swap liquidity-event hydration','public fallback duration',
                        'notification retransmission and provider byte-meter basis',
                        'paid-stream periodic HTTP reconciliation, heartbeat and subscription/filter lifecycle work'
                            if architecture in ('C','D') else 'public sequencer transport and retention resource cost']))
    return dict(schema='robinhood-payg-conditional-cost-model-v1',projections=projections,
        observed_account=dict(source='owner connectivity update, 2026-10-08',compute_units_approximately=1730000,
            reported_usage_usd_approximately=.91,implied_rounded_usd_per_million_cu=.91/1.73,
            billing_window='not supplied; cannot normalize to 24 hours',
            pons_app='v5h0vqr0wpp9zscj',pump_app='9bin99s96t7ga5e9',
            per_app_numeric_breakdown='visible to owner; not returned by this running connector session',
            solana_primary_drivers=['address history','WebSocket logs']),
        pricing=dict(published_usd_per_m_cu=RATE_USD_PER_M_CU,exact_account_tariff_independently_verified=False,
            rounded_account_value_consistent_with_published_rate=True,
            evm_subscription_cu_per_byte=EVM_CU_PER_BYTE,solana_subscription_cu_per_byte=SOLANA_CU_PER_BYTE,
            solana_is_not_modeled_with_evm_byte_rate=True,
            sources=['https://www.alchemy.com/pricing','https://www.alchemy.com/docs/reference/compute-unit-costs']),
        payload_samples=raw,retained_block_header_pair=[a,b],block_rate_assumption=rate,
        block_rate_is_a_current_measurement=False,live_activity_density_measured=False,
        coefficients=dict(graduation_authentication_methods=auth_methods,cold_authentication_cu=auth_cu,
            eligible_survivor_execution_quote_cu=qualification['diagnostic_cu']['known_estimated_cu'],
            warm_survivor_position_turn=warm,
            current_cu_per_attempt_allowance_range=[4000,12000],
            current_allowance_basis='UNMEASURED replaceable scenario allowance, not a measured or hard upper bound',
            forty_block_log_subscription_break_even_bytes_per_second=60*rate/40/EVM_CU_PER_BYTE),
        interpretation='Conditional comparable ranges plus named unmeasured additions. Blended ratios are not marginal measured unit costs. Thirty days scales assumed rates, not a five-minute autonomy or billing certification.',
        spending_cutoff=None,ten_million_cu_is_acceptance_gate=False,provider_requests=0)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv);args.output.write_text(json.dumps(build(),indent=2)+'\n');return 0


if __name__=='__main__':raise SystemExit(main())
