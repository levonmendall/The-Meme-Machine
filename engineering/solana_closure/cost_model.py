"""Measured units, gated production forecast. No previous assumed counts.

Run: python -m engineering.solana_closure.cost_model
The final measurement phase requires seven passing gates. Missing production
incidence stays null; a cold-interest burst is not a monthly central tendency.
"""
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
OUTPUT=HERE.parent/'solana_finalization/cost_model.json'
FAMILIES=[
    'Shared control/finality','Replay/recovery','Pump universal discovery',
    'Pump ordered history','Pump promotion/hydration','Pump position management',
    'PumpSwap ordered history','PumpSwap selective bodies','Survivor incremental evidence',
    'Meteora structural scout','Meteora ordered history','Meteora warming/hydration',
    'Meteora position management']
PRICING=dict(checked_at_UTC='2026-10-07 05:00:47 UTC',yellowstone_USD_per_decimal_TB=75.,
    rpc_USD_per_million_CU=.525,solana_websocket_CU_per_byte=.0002,
    getSlot_CU=20,getMultipleAccounts_CU=20,getProgramAccountsV2_CU=20,
    getTransaction_CU=40,getBlock_CU=40,getTransactionsForAddress_CU=100,
    PAYG_included_CU=0,yellowstone_minimum_monthly_USD=0,
    sources=dict(rpc='https://www.alchemy.com/pricing',yellowstone='https://www.alchemy.com/solana-grpc',
        methods_and_websocket='https://www.alchemy.com/docs/reference/compute-unit-costs'),
    note='Solana-specific WebSocket rate applies. Free-plan 30M CU is not a PAYG credit. HTTP bytes are measured; RPC is charged by CU.')


def build():
    m=json.loads((HERE/'measurements.json').read_text());inputs={};table={}
    def add(name,value,unit,source,window,count,kind,**notes):
        assert kind in ('MEASURED_LIVE','MEASURED_REPLAY','DERIVED','MODELED')
        inputs[name]=dict(value=value,unit=unit,source=source,measurement_window=window,
            sample_count=count,classification=kind,**notes)
    for family,r in m['promotion'].items():
        source='engineering/solana_closure/simultaneous_provider.json#/candidate_rates/'+family
        for key,value,unit in (('observed_candidates',r['denominator'],'candidates'),
                ('promotions',r['numerator'],'promotion_events'),('reactivations',r['reactivations'],'reactivations'),
                ('promotion_percentage',r['promotion_percentage'],'percent'),
                ('daily_normalized_stress_promotions',r['rate_day'],'promotion_events/day')):
            add(family+'.'+key,value,unit,source,r['seconds'],r['denominator'],
                'DERIVED' if key.startswith('daily') else 'MEASURED_REPLAY',
                production_central_tendency=False,cohort=r['cohort'])
        for key,unit in (('production_promotions_per_day','promotions/day'),('production_hydrations_per_day','hydrations/day')):
            add(family+'.'+key,None,unit,source,r['seconds'],r['denominator'],'MODELED',
                missing_reason='Final operating incidence is gated by simultaneous provider capacity.')
    for key,d in m['hydration']['distributions'].items():
        add('meteora.hydration.'+key,d['mean'],key+'/hydration',
            'engineering/solana_closure/measurements.json#/hydration',
            m['hydration']['observation_windows'],d['samples'],'MEASURED_LIVE',distribution=d,
            limitation='Four full fresh-trigger warmups of one pool; not hydrations/day.')
    for family in ('pump','pumpswap'):
        for key,value in m['position'][family].items():
            add(family+'.position.'+key,value,key,'engineering/solana_closure/pump_position_measurements.json',15.,3,'DERIVED',
                authority='MEASURED_REPLAY_POSITION_TRAFFIC with live read-only HTTP units',complete_simultaneous_position_path=False)
    met=m['position']['meteora']
    for key in ('provider_bytes_per_position_hour','http_bytes_per_position_hour','native_bytes_per_position_hour',
            'rpc_cu_per_position_hour','rpc_calls_per_position_hour','subscription_messages_per_position_hour',
            'selective_fetches_per_position_hour'):
        add('meteora.position.'+key,met[key],key,'engineering/solana_closure/meteora_position_measurements.json',
            met['window_seconds'],12,'DERIVED',authority='MEASURED_REPLAY_POSITION_TRAFFIC',complete_simultaneous_position_path=False)
    replay=m['replay']
    for key,unit in (('raw_provider_bytes_per_reconnect','bytes/reconnect'),('rpc_cu_per_reconnect','CU/reconnect'),
            ('rpc_calls_per_reconnect','calls/reconnect'),('provider_capture_catchup_seconds','seconds/reconnect'),
            ('expected_reconnects_per_day','reconnects/day'),('expected_replay_provider_bytes_per_day','bytes/day'),
            ('expected_replay_cu_per_day','CU/day')):
        derived=key.startswith('expected')
        add('replay.'+key,replay[key],unit,'engineering/solana_closure/recovery_measurements.json',
            replay['historical_visible_connected_seconds'] if derived else replay['provider_capture_catchup_seconds'],
            replay['historical_reconnects'] if derived else 103,'DERIVED' if derived else 'MEASURED_REPLAY',
            limitation=replay['frequency_limitation'] if derived else 'Representative 103-transaction interval, not every reconnect.')
    add('replay.natural_reconnects',0,'reconnects','engineering/solana_closure/recovery_measurements.json',
        replay['natural_observation_seconds'],len(replay['natural_observation_windows']),'MEASURED_LIVE',production_zero_rate_proven=False)
    for label,s in m['scouting'].items():
        add('scout.'+label+'.bytes_per_day_normalized',s['bytes_per_day_normalized'],'bytes/day',
            'engineering/solana_closure/captures/delivery-20261007T023339Z/scout.frames.zlib',
            s['window_seconds'],s['messages'],'DERIVED',steady_state_monthly_forecast=False)
    route=m['capacity']['routing']
    add('shards.overlap_delivery_bytes',route['duplicate_delivered_bytes'],'bytes/captured_window',
        'engineering/solana_closure/simultaneous_provider.json#/routing',30.10356330004288,1064,'DERIVED',
        billing_included=True,serialization='Complete captured provider status, only routing labels differ.')
    add('shards.limit',50,'filter entries/shard','Established authenticated endpoint probe 2026-10-07','bounded probe',1,'MEASURED_REPLAY')
    for name,value,unit,source in (('yellowstone',75,'USD/decimal_TB',PRICING['sources']['yellowstone']),
            ('rpc',.525,'USD/million_CU',PRICING['sources']['rpc']),
            ('solana_websocket',.0002,'CU/byte',PRICING['sources']['methods_and_websocket'])):
        add('pricing.'+name,value,unit,source,PRICING['checked_at_UTC'],1,'MODELED',verified_current_public_rate=True)
    add('host_storage',73,'USD/month','Established $68 host + $5 50 GiB volume; engineering/solana_finalization/measurements.json',
        'preceding authenticated infrastructure snapshot',1,'MODELED',alchemy_direct_scope=False)
    for name in FAMILIES:
        table[name]=dict(provider_bytes_per_day=None,rpc_CU_per_day=None,LOW_monthly_USD=None,
            EXPECTED_monthly_USD=None,PRODUCTION_HIGH_monthly_USD=None,input_quality='Production incidence uncertified; measured units in inputs.')
    # Known component normalizations never become a purported complete EXPECTED.
    table['Pump universal discovery'].update(provider_bytes_per_day=m['scouting']['p']['bytes_per_day_normalized'],
        rpc_CU_per_day=0,input_quality='DERIVED short scout capture; initial census cost absent.')
    table['Meteora structural scout'].update(provider_bytes_per_day=sum(m['scouting'][k]['bytes_per_day_normalized'] for k in ('m','n')),
        input_quality='DERIVED WSOL scout capture; paginated census/refresh incidence unmeasured.')
    table['Meteora ordered history'].update(provider_bytes_per_day=m['scouting']['a']['bytes_per_day_normalized'],
        input_quality='Cheap bin-locator deliveries only; rich promoted-history incidence unmeasured.')
    table['Replay/recovery'].update(provider_bytes_per_day=replay['expected_replay_provider_bytes_per_day'],
        rpc_CU_per_day=replay['expected_replay_cu_per_day'],input_quality='DERIVED historical frequency × measured replay unit; not new-topology live rate.')
    table['PumpSwap selective bodies'].update(input_quality='0/879 captured events needed bodies. Fallback tested; production incidence unmeasured.')
    stress=m['promotion']['meteora']['rate_day'];mean_cu=m['hydration']['distributions']['rpc_cu']['mean']
    floor=stress*mean_cu*30*.525/1e6
    envelope=dict(partial_monthly_USD_lower_bound=floor,full_system_monthly_USD=None,classification='MODELED',production_high=False,
        assumption='Daily-linear continuation of captured cold/activity-first Meteora promotions, every promoted scope needing measured mean compatible full warmup.',
        exclusions='All Pump/PumpSwap, other Meteora/control/replay/native-byte traffic and position occupancy.',
        current_capacity=m['capacity']['two_worker_deadline_envelope'])
    add('failure_envelope.Meteora_warming_RPC',floor,'USD/month','simultaneous_provider.json + measurements.json#/hydration',
        [m['promotion']['meteora']['seconds'],m['hydration']['observation_windows']],
        [m['promotion']['meteora']['numerator'],m['hydration']['sample_count']],'MODELED',production_high=False)
    return dict(status='ALCHEMY_SOLANA_NOT_READY',measured_cost_model='FAIL',blocker='SIMULTANEOUS_PROVIDER_CAPACITY',
        pricing=PRICING,inputs=inputs,evidence_families=table,
        monthly=dict(ALCHEMY_LOW=None,ALCHEMY_EXPECTED=None,ALCHEMY_PRODUCTION_HIGH=None,
            UNSERVICEABLE_FAILURE_ENVELOPE=envelope,NON_ALCHEMY_HOST_STORAGE=73.,TOTAL_EXPECTED_INFRA=None,
            EXPECTED_SAVINGS_USD=None,EXPECTED_SAVINGS_PERCENT=None),
        previous_broad_monthly_USD=1332.83,previous_conditional_expected_USD=83.87,
        previous_expected_status='WITHDRAWN as a measured production estimate; historical conditional arithmetic only.',
        previous_assumed_daily_promotions_imported=False,previous_assumed_selective_bodies_imported=False,
        production_forecast_certified=False,
        target_classification={str(n):dict(classification='PLAUSIBLE',proven=False,
            note='Selective evidence can reach this reporting band; sustainable measured operating incidence is uncertified. No strategy changed to reach it.') for n in (25,50,100,250)},
        measurement_phase='BLOCKED by capacity gate. Unit/stress evidence is not a completed measured production model.',
        pons_direct_alchemy_monthly_USD=0,ramses_direct_alchemy_monthly_USD=0)


def main():
    model=build();OUTPUT.write_text(json.dumps(model,indent=2)+'\n')
    print(json.dumps(dict(status=model['status'],monthly=model['monthly']),indent=2))


if __name__=='__main__':main()
