"""Offline provider-delivery workload envelope, not a certified production forecast.

Run: python engineering/solana_finalization/cost_model.py
Every rate is exposed. LOW/EXPECTED/HIGH are conditional workload scenarios,
not statistical percentiles. No capital/entry/exit policy is changed by this model.
"""
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
PRICES=dict(yellowstone_per_TB=75.,rpc_per_million_CU=.525,websocket_CU_per_byte=.0002,
    bytes_per_TB=10**12,PAYG_included_CU=0,monthly_minimum=0)
SCENARIOS={
 'LOW':dict(traffic=.5,creations=23400,pump_promotions=500,pump_events_per_promotion=40,
    graduations=1800,swap_promotions=100,swap_archive_bodies_per_promotion=100,
    swap_watch_events=100000,swap_activity_transactions=1500000,met_promotions=20,
    pump_open_hours=1,survivor_open_hours=1,met_open_hours=1,replay=.01),
 'EXPECTED':dict(traffic=1.,creations=46800,pump_promotions=6000,pump_events_per_promotion=120,
    graduations=3600,swap_promotions=500,swap_archive_bodies_per_promotion=1000,
    swap_watch_events=1000000,swap_activity_transactions=3053785,met_promotions=200,
    pump_open_hours=4,survivor_open_hours=4,met_open_hours=4,replay=.05),
 'HIGH':dict(traffic=2.,creations=93600,pump_promotions=93600,pump_events_per_promotion=500,
    graduations=7200,swap_promotions=7200,swap_archive_bodies_per_promotion=10000,
    swap_watch_events=52761600,swap_activity_transactions=52761600,met_promotions=119330,
    pump_open_hours=24,survivor_open_hours=24,met_open_hours=24,replay=.25),
}
FAMILIES=[
 'Shared Solana control/finality/replay','Pump universal discovery',
 'Pump ordered candidate history','Pump qualification hydration','Pump position management',
 'PumpSwap ordered history','PumpSwap selective body hydration','Pump Survivor incremental evidence',
 'Meteora structural scout','Meteora ordered candidate history','Meteora warming/hydration',
 'Meteora position management']

def row(y=0,w=0,http=0,cu=0,bodies=0,calls=0,canonical=0,ipc=0):
    y,w,http,cu,bodies,calls,canonical,ipc=map(lambda n:int(round(n)),(y,w,http,cu,bodies,calls,canonical,ipc))
    price=30*y/PRICES['bytes_per_TB']*PRICES['yellowstone_per_TB']+30*(cu+w*PRICES['websocket_CU_per_byte'])/1e6*PRICES['rpc_per_million_CU']
    return dict(provider_bytes_per_day=y+w+http,yellowstone_bytes_per_day=y,
        websocket_bytes_per_day=w,http_response_bytes_per_day=http,rpc_CU_per_day=cu,
        billed_websocket_CU_per_day=w*PRICES['websocket_CU_per_byte'],
        rpc_calls_per_day=calls,transaction_bodies_delivered_per_day=bodies,
        canonical_bytes_per_day=canonical,local_IPC_bytes_per_day=ipc,monthly_USD=price)

def calculate(a,m):
    traffic=a['traffic'];p=a['pump_promotions'];g=a['graduations'];s=a['swap_promotions'];h=a['met_promotions']
    # A cold Pump history page uses full API results: 100 CU, not 100 separate
    # getTransaction calls. Its rich bytes are still provider-delivered bytes.
    pump_archive_bodies=p*(103 if p<93600 else 500)
    pump_pages=p*(3 if p<93600 else 6)
    pump_events=p*a['pump_events_per_promotion']
    swap_archive_bodies=s*a['swap_archive_bodies_per_promotion']
    swap_pages=s*(1+a['swap_archive_bodies_per_promotion']//100)
    # Observed ambiguous filter fanout averages 1.11372; HIGH doubles request
    # work. It is acquisition pressure, never authority to reject candidates.
    fanout=2. if traffic==2. else m['activity_mean_fanout']
    positions_p=a['pump_open_hours']*3600;positions_s=a['survivor_open_hours']*3600
    positions_m=a['met_open_hours']*3600
    r={}
    r[FAMILIES[0]]=row(y=m['control_bytes_per_second']*86400*traffic,cu=20*1440+10,
        http=1440*50,calls=1441,
        ipc=200*(p*4+s*4+h*30)+200*(positions_p+positions_s+positions_m)/5)
    r[FAMILIES[1]]=row(y=m['pump_scout_bytes_per_day']*traffic)
    r[FAMILIES[2]]=row(y=pump_events*120,w=pump_events*2500,
        http=pump_archive_bodies*m['archive_bytes_per_transaction'],
        cu=pump_pages*100+p*20,bodies=pump_archive_bodies,calls=pump_pages+p,
        canonical=pump_events*m['canonical_pump_event_bytes'])
    r[FAMILIES[3]]=row(http=p*10000,cu=p*50,calls=p*3)
    r[FAMILIES[4]]=row(y=positions_p*1000,w=positions_p*20000,
        http=positions_p/5*2000,cu=positions_p/5*20,calls=positions_p/5,
        canonical=positions_p*2000)
    r[FAMILIES[5]]=row(y=a['swap_activity_transactions']*m['activity_bytes_per_status'],
        w=a['swap_watch_events']*2200,http=swap_archive_bodies*m['archive_bytes_per_transaction']*fanout,
        cu=swap_pages*100*fanout+s*20,calls=swap_pages*fanout+s,
        bodies=swap_archive_bodies*fanout,canonical=a['swap_watch_events']*m['canonical_swap_event_bytes'])
    # Preserved 879/879 logged events need no body. Reserve 0.5% exceptions in
    # EXPECTED, 5% in HIGH for absent/truncated logs or a missing identity field.
    exceptions=a['swap_watch_events']*(.05 if traffic==2. else (.005 if traffic==1. else 0))
    r[FAMILIES[6]]=row(http=exceptions*m['archive_bytes_per_transaction'],
        cu=exceptions*40,calls=exceptions,bodies=exceptions)
    # Independent Survivor state does not reacquire Current/Survivor shared
    # economic events. This is new exact state plus disjoint open-position work.
    r[FAMILIES[7]]=row(y=positions_s*1500,w=positions_s*40000,
        http=g*8000+positions_s/5*2000,cu=g*40+positions_s/5*20,
        calls=g*2+positions_s/5,canonical=positions_s*2500)
    r[FAMILIES[8]]=row(y=m['met_pool_scout_bytes_per_day']*traffic)
    # Bin headers locate development/reactivation only. They do not become
    # swaps or completeness proofs; their delivered bytes nevertheless count.
    r[FAMILIES[9]]=row(y=m['met_bin_scout_bytes_per_day']*traffic+h*20000,
        canonical=h*100000)
    r[FAMILIES[10]]=row(y=h*(150000 if traffic<2 else 1201295),
        http=h*m['met_warming_http_bytes'],cu=h*m['met_warming_CU'],
        calls=h*m['met_warming_calls'],bodies=h*(1 if traffic<2 else 108),
        canonical=h*12000)
    r[FAMILIES[11]]=row(y=positions_m*(60000 if traffic<2 else 1142000),
        http=positions_m/(5 if traffic<2 else 1)*30000,
        cu=positions_m/(5 if traffic<2 else 1)*60,
        calls=positions_m/(5 if traffic<2 else 1)*3,
        canonical=positions_m*10000)
    # Replay charged once across all transport families, with repair RPC counted
    # conservatively at the same proportional workload. Allocate at system level.
    base_y=sum(v['yellowstone_bytes_per_day'] for v in r.values())
    base_w=sum(v['websocket_bytes_per_day'] for v in r.values())
    base_http=sum(v['http_response_bytes_per_day'] for v in r.values())
    base_cu=sum(v['rpc_CU_per_day'] for v in r.values())
    extra=row(y=base_y*a['replay'],w=base_w*a['replay'],http=base_http*a['replay'],cu=base_cu*a['replay'])
    control=r[FAMILIES[0]]
    for k in ('provider_bytes_per_day','yellowstone_bytes_per_day','websocket_bytes_per_day',
              'http_response_bytes_per_day','rpc_CU_per_day','billed_websocket_CU_per_day','monthly_USD'):
        control[k]+=extra[k]
    total=sum(v['monthly_USD'] for v in r.values())
    return dict(families=r,total_monthly_USD=total,
        provider_bytes_per_day=sum(v['provider_bytes_per_day'] for v in r.values()),
        canonical_bytes_per_day=sum(v['canonical_bytes_per_day'] for v in r.values()),
        # Retained after local projection includes canonical bytes plus short
        # ephemeral normalized objects. This is a model, not a raw-wire discount.
        retained_bytes_per_day=sum(v['canonical_bytes_per_day'] for v in r.values())*1.25,
        local_IPC_bytes_per_day=sum(v['local_IPC_bytes_per_day'] for v in r.values()),
        rpc_CU_per_day=sum(v['rpc_CU_per_day'] for v in r.values()),
        transaction_bodies_delivered_per_day=sum(v['transaction_bodies_delivered_per_day'] for v in r.values()),
        explicit_getTransaction_per_day=round(exceptions),
        hydration_promotions_per_day=p+s+h)

def allocations(result):
    r=result['families'];lanes={n:dict(discovery=0,history_watch=0,hydration=0,position_management=0,recovery=0,marginal=0,fully_loaded=0) for n in ('Pump Current','Pump Survivor','Meteora')}
    # Every source family is acquired once. Shared Pump/PumpSwap history is
    # allocated 50/50 for accounting, never duplicated in the system total.
    mapping={0:('recovery',{'Pump Current':1/3,'Pump Survivor':1/3,'Meteora':1/3}),
     1:('discovery',{'Pump Current':.5,'Pump Survivor':.5}),
     2:('history_watch',{'Pump Current':.5,'Pump Survivor':.5}),
     3:('hydration',{'Pump Current':1}),4:('position_management',{'Pump Current':1}),
     5:('history_watch',{'Pump Current':.5,'Pump Survivor':.5}),
     6:('hydration',{'Pump Current':.5,'Pump Survivor':.5}),
     7:('position_management',{'Pump Survivor':1}),8:('discovery',{'Meteora':1}),
     9:('history_watch',{'Meteora':1}),10:('hydration',{'Meteora':1}),11:('position_management',{'Meteora':1})}
    for index,(category,weights) in mapping.items():
        for lane,weight in weights.items():lanes[lane][category]+=r[FAMILIES[index]]['monthly_USD']*weight
    # Marginal = lane-exclusive acquisition with other lanes still present.
    lanes['Pump Current']['marginal']=sum(r[FAMILIES[i]]['monthly_USD'] for i in (3,4))
    lanes['Pump Survivor']['marginal']=r[FAMILIES[7]]['monthly_USD']
    lanes['Meteora']['marginal']=sum(r[FAMILIES[i]]['monthly_USD'] for i in (8,9,10,11))
    for v in lanes.values():v['fully_loaded']=sum(v[k] for k in ('discovery','history_watch','hydration','position_management','recovery'))
    assert abs(sum(v['fully_loaded'] for v in lanes.values())-result['total_monthly_USD'])<1e-6
    return lanes

def main():
    measured=json.loads((HERE/'measurements.json').read_text())
    results={s:calculate(a,measured) for s,a in SCENARIOS.items()}
    for r in results.values():r['lanes']=allocations(r)
    expected=results['EXPECTED']['total_monthly_USD']
    model=dict(pricing=PRICES,pricing_timestamp_UTC='2026-10-07 02:40 UTC',
        status='CONDITIONAL_WORKLOAD_ENVELOPE_NOT_CERTIFIED_PRODUCTION_BILL',
        production_forecast_certified=False,
        scenario_note='Promotion incidence, simultaneous open-position traffic and replay frequency are explicit engineering scenarios; short captures cannot establish a monthly expectation. HIGH covers double measured creation/graduation/activity rates and one warming per structural Meteora pool/day. It is not an unconditional physical bound on all future markets.',
        assumptions=SCENARIOS,measurements=measured,results=results,
        non_alchemy_host_monthly_USD=73,expected_infra_scenario_monthly_USD=expected+73,
        previous_broad_monthly_USD=1332.83,modeled_savings_monthly_USD=1332.83-expected,
        modeled_savings_percent=(1332.83-expected)/1332.83*100,
        realized_savings_certified=False,
        target_classification={'50':'PLAUSIBLE_BUT_UNPROVEN','100':'PLAUSIBLE_BUT_UNPROVEN','250':'PLAUSIBLE_BUT_UNPROVEN'},
        pons_direct_alchemy_monthly_USD=0,ramses_direct_alchemy_monthly_USD=0)
    (HERE/'cost_model.json').write_text(json.dumps(model,indent=2)+'\n')
    print(json.dumps({s:dict(monthly_USD=round(r['total_monthly_USD'],2),provider_GB_day=round(r['provider_bytes_per_day']/1e9,3),rpc_CU_day=r['rpc_CU_per_day']) for s,r in results.items()},indent=2))
if __name__=='__main__':main()
