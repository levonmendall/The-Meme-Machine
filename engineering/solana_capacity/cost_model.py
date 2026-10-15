"""Rebuild the gated model from one actual shared-provider audit.

The captured startup/failed workload has a cost equivalent, not a certified
production central tendency. LOW/EXPECTED/serviceable HIGH remain null until
the shared evidence path and complete native incidence are certified.
"""
import argparse
import json
from pathlib import Path

FAMILIES = (
    'Shared control/finality','Replay/recovery','Pump universal discovery',
    'Pump ordered history','Pump promotion/hydration','Pump position management',
    'PumpSwap ordered history','PumpSwap selective bodies','Survivor incremental evidence',
    'Meteora structural scout','Meteora ordered history','Meteora warming/hydration',
    'Meteora position management',
)


def build(audit, source, pricing):
    window = audit['window_seconds']; traffic = audit['traffic']; inputs = {}
    def record(key, value, unit, samples, classification='MEASURED_LIVE', note=None):
        inputs[key] = dict(value=value,unit=unit,source=source,window_seconds=window,
                           sample_count=samples,classification=classification)
        if note: inputs[key]['note']=note
    for family, values in audit['lanes'].items():
        for key in ('candidate_stock','startup_census_stock','active_scopes','promotion_events','reactivations',
                    'full_hydrations_required','full_hydration_incidence_percent','unobserved_native_dispositions'):
            record(family+'.'+key,values[key],'percent' if key.endswith('percent') else 'count',values['promotion_events'])
        record(family+'.normalized_promotions_per_day',values['normalized_promotions_per_day'],'events/day',
               values['promotion_events'],'DERIVED','Bounded-window normalization; production central tendency is not certified.')
        record(family+'.normalized_active_scopes_per_day',values['normalized_active_scopes_per_day'],'scopes/day',
               values['active_scopes'],'DERIVED','Unique active scopes in this window, not daily creations or steady-state arrivals.')
        record(family+'.observed_full_hydration_incidence_bounds',values['full_hydration_incidence_bounds_percent'],'percent',
               values['promotion_events'],'DERIVED','Censored native dispositions may require hydration. Zero observed full warmups does not mean zero production incidence.')
        record(family+'.promotion_percent_of_active_scopes',values['promotion_percent_of_active_scopes'],'percent',
               values['active_scopes'],'DERIVED','Unique promoted scopes divided by unique active scopes; repeat promotion events are counted separately.')
        record(family+'.sampled_hydration_operations',values['sampled_hydration_operations'],'operations',
               values['sampled_hydration_operations'],note='Observed account/compatibility operations only; required-history RPC and native bodies are separately billed.')
        record(family+'.production_promotions_per_day',None,'events/day',values['promotion_events'],'MODELED_BOUND',
               'Unresolved shared-provider readiness prevents certification; missing is not zero.')
        record(family+'.production_full_hydrations_per_day',None,'hydrations/day',values['promotion_events'],'MODELED_BOUND',
               'Do not substitute every promotion for full hydration or zero for censored work.')
        for metric, distribution in values['hydration_units'].items():
            record(family+'.'+metric+'_per_sampled_promotion',distribution['mean'],metric+'/promotion',distribution['N'],
                   'DERIVED' if metric=='cu' else 'MEASURED_LIVE','All observed attempts are aggregated by original promotion identity. CU uses verified current method prices.')
        for metric in ('measured_HTTP_bytes_per_position_hour','measured_RPC_CU_per_position_hour','measured_RPC_calls_per_position_hour'):
            record(family+'.'+metric,audit['positions'][family][metric],metric.replace('measured_',''),
                   audit['positions'][family]['mark_ready'],'DERIVED','Measured simultaneous read-only position-equivalent HTTP unit; native delivery is billed separately.')
    for metric,unit in (('Yellowstone_delivered_bytes','bytes'),('WebSocket_delivered_bytes','bytes'),
                        ('HTTP_response_bytes','bytes'),('RPC_CU','CU'),('RPC_calls','calls'),
                        ('cross_shard_duplicate_provider_bytes','bytes')):
        record('provider.'+metric,traffic[metric],unit,traffic['RPC_calls'],'DERIVED' if metric=='RPC_CU' else 'MEASURED_LIVE')
    record('provider.payload_daily_normalization',traffic['measured_payload_daily_normalization'],'bytes/day',
           traffic['RPC_calls'],'DERIVED','Includes actual duplicates and startup/replay; this is not a production forecast.')
    record('provider.CU_daily_normalization',traffic['measured_RPC_CU_daily_normalization'],'CU/day',
           traffic['RPC_calls'],'DERIVED','Includes observed startup/cold-history work.')
    scoped_bodies=sum(v['scoped_archive_bodies'] for v in traffic['HTTP_families'].values())
    selective_bodies=sum(v['transaction_bodies'] for v in traffic['HTTP_families'].values())
    record('provider.scoped_archive_transaction_bodies',scoped_bodies,'bodies',scoped_bodies,
           note='Scoped getTransactionsForAddress history bodies. These are real delivered bodies, not getTransaction calls; startup/replay incidence is not steady state.')
    record('provider.selective_getTransaction_calls',selective_bodies,'calls',traffic['RPC_calls'])
    record('provider.selective_getTransaction_daily_normalization',selective_bodies*86400/window,'calls/day',
           traffic['RPC_calls'],'DERIVED','Observed zero in this window only; censored qualification work prevents certification of production incidence.')
    record('diagnostics.estimated_cost',traffic['diagnostic_estimated_USD'],'USD',traffic['RPC_calls'],'DERIVED')
    record('replay.bytes_per_reconnect',869874,'bytes/reconnect',1,'MEASURED_REPLAY','Established authenticated 103-transaction/three-page overlap unit.')
    record('replay.CU_per_reconnect',400,'CU/reconnect',4,'MEASURED_REPLAY')
    record('replay.calls_per_reconnect',4,'calls/reconnect',4,'MEASURED_REPLAY')
    for key in ('replay.bytes_per_reconnect','replay.CU_per_reconnect','replay.calls_per_reconnect'):
        inputs[key].update(source='engineering/solana_closure/recovery_measurements.json',
                           window_seconds=.3307769339880906,sample_count=103)
    record('replay.historical_reconnects_per_day',6/3971.216834*86400,'reconnects/day',6,'DERIVED',
           'Six preserved reconnects over 3971.216834 visible connected seconds; topology-specific frequency remains uncertain.')
    inputs['replay.historical_reconnects_per_day']['source']='engineering/solana_closure/captures/historical-reconnects.json'
    inputs['replay.historical_reconnects_per_day']['window_seconds']=3971.216834
    record('replay.historical_unit_bytes_daily',869874*6/3971.216834*86400,'bytes/day',6,'DERIVED',
           'Established replay unit multiplied by historical frequency. Scoped scout rebuilds are not whole-provider reconnects.')
    record('replay.historical_unit_CU_daily',400*6/3971.216834*86400,'CU/day',6,'DERIVED')
    record('replay.natural_control_reconnects_in_window',audit['replay_incidence']['natural_control_reconnects'],'reconnects',
           audit['replay_incidence']['natural_control_reconnects'],note='Zero in a short bounded window does not imply zero production reconnect cost.')
    record('replay.observed_HTTP_response_bytes',traffic['HTTP_families'].get('replay_source',{}).get('http_bytes',0),'bytes',
           traffic['HTTP_families'].get('replay_source',{}).get('calls',0),note='Actual startup/overlap traffic; separate from the historical per-reconnect unit.')
    record('host_storage',73,'USD/month',1,'MODELED_BOUND','Established infrastructure; excluded from direct Alchemy billing.')
    inputs['host_storage'].update(source='Owner-established host/storage operating budget, 2026-10-07',window_seconds=None)
    by_family = {name:dict(provider_bytes_per_day=None,RPC_CU_per_day=None,LOW_monthly_USD=None,
                         EXPECTED_monthly_USD=None,PRODUCTION_HIGH_monthly_USD=None,
                         input_quality='Production incidence remains uncertified; measured shared-path units are retained in inputs.')
                 for name in FAMILIES}
    # Cost equivalent of repeating the *actual failed/cold capture*. This replaces
    # the earlier all-compatible 43/61 counterfactual; it is never ordinary HIGH.
    equivalent = traffic['diagnostic_estimated_USD']*86400/window*30
    monthly = dict(ALCHEMY_LOW=None,ALCHEMY_EXPECTED=None,ALCHEMY_PRODUCTION_HIGH=None,
                   UNSERVICEABLE_FAILURE_ENVELOPE=dict(monthly_USD=equivalent,
                       classification='DERIVED',production_high=False,
                       definition='Thirty-day cost equivalent of repeating this observed, uncertified cold/failed workload at its measured provider payload/CU rates.',
                       limitations='Startup stock is not recurring births; position occupancy is three nonmonetary equivalents. This is an arithmetic pressure envelope, not a stationary production forecast.'),
                   NON_ALCHEMY_HOST_STORAGE=73,TOTAL_EXPECTED_INFRA=None,
                   EXPECTED_SAVINGS_USD=None,EXPECTED_SAVINGS_PERCENT=None)
    return dict(status='ALCHEMY_SOLANA_NOT_READY',measured_cost_model='FAIL',
                blocker='SIMULTANEOUS_PROVIDER_CAPACITY',pricing=pricing,inputs=inputs,
                evidence_families=by_family,monthly=monthly,previous_broad_monthly_USD=1332.83,
                previous_conditional_expected_USD=83.87,previous_expected_status='Retired; not a measured production estimate.',
                previous_assumed_daily_promotions_imported=False,previous_assumed_selective_bodies_imported=False,
                previous_43_of_61_counterfactual_used_as_production_failure_rate=False,
                production_forecast_certified=False,
                target_classification={str(band):dict(classification='PLAUSIBLE',proven=False,
                    note='No band is proven while sustainable complete observation and operating incidence remain uncertified.') for band in (25,50,100,250)},
                measurement_phase='Actual shared-provider measurements obtained; production forecast is gated by the remaining capacity proof.',
                pons_direct_alchemy_monthly_USD=0,ramses_direct_alchemy_monthly_USD=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('audit',type=Path);parser.add_argument('--pricing',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.write_text(json.dumps(build(json.loads(args.audit.read_text()),str(args.audit),json.loads(args.pricing.read_text())),indent=2)+'\n')
