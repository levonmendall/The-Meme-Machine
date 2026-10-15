"""Reproducible finite demand model, deliberately separate from activation.

Counts describe explicit scenarios, not unlimited outage/activity guarantees.
Method weights are the existing frozen conservative operational contract.
"""
from collections import Counter
from decimal import Decimal
import argparse
import json
from math import ceil
from pathlib import Path

from engineering.solana_capacity.proof_limits import PUBLISHED

HOLD=259200
PRICE=Decimal('0.525')/1000000
GIB=1024**3
ROOT=Path(__file__).resolve().parents[2]


def demand(family,methods,turns,physical):
    methods={m:int(n) for m,n in methods.items() if n}
    cu=sum(PUBLISHED[family][m]*n for m,n in methods.items())
    return dict(turns=turns,methods=methods,rpc_elements=sum(methods.values()),rpc_cu=cu,
        physical_attempts_without_failures=physical,rpc_only_modeled_usd=str(Decimal(cu)*PRICE))


def pump(hours,*,current=False,before=False,fallbacks=0):
    turns=ceil(hours*3600/5)
    if current:
        methods=Counter(getMultipleAccounts=3*turns,getBlockTime=2*turns)
        methods['getTokenLargestAccounts' if before else 'getProgramAccounts']=turns
        # A failed compact scan consumes its own priced request BEFORE fallback.
        if not before:methods['getTokenLargestAccounts']+=fallbacks
    elif before:methods=Counter(getMultipleAccounts=6*turns,getBlockTime=4*turns,getTokenLargestAccounts=turns)
    else:methods=Counter(getMultipleAccounts=3*turns,getBlockTime=2*turns)
    # Session verification is additional; bounded upper allowance, not cache hits.
    auth=ceil(sum(methods.values())/130)+1
    methods['getGenesisHash']=auth
    return demand('solana',methods,turns,sum(methods.values()))


def pons(hours,*,before=False,blocks_per_turn=30,events_per_turn=0,
         missing_sender=False,log_width=10,event_period_turns=1):
    turns=ceil(hours*3600/3);logs=ceil(blocks_per_turn/log_width)
    # Six quote reads, independent current flow head, both history boundaries.
    active_turns=ceil(turns/event_period_turns) if events_per_turn else 0
    blocks=min(blocks_per_turn,events_per_turn);transactions=events_per_turn
    fallback=transactions if missing_sender else 0
    methods=Counter(eth_getBlockByNumber=5*turns+blocks*active_turns,eth_getCode=turns,
        eth_call=2*turns,eth_gasPrice=turns,eth_getLogs=logs*turns,
        eth_getTransactionReceipt=transactions*active_turns,eth_getTransactionByHash=fallback*active_turns)
    evidence=logs*turns+(blocks+transactions+fallback)*active_turns
    # Evidence rotation's 180-read limit with up to 50 per batch guarantees at
    # least 130 consumed elements between local rotations. Primary rotates >150.
    auth=(turns*max(1,ceil((logs+blocks+transactions+fallback)/130))
        if before else ceil(evidence/130))+ceil(9*turns/150)+2
    methods['eth_chainId']=auth
    witnesses=ceil(blocks/50)+ceil(transactions/50)
    physical=turns*(2+1+(2 if before else 1)+ceil(logs/4))+(witnesses+ceil(fallback/50))*active_turns+auth
    result=demand('robinhood',methods,turns,physical)
    result['minimum_physical_rps_under_scenario']=physical/(hours*3600)
    result['assumptions']=dict(blocks_per_three_seconds=blocks_per_turn,
        relevant_transactions_per_three_seconds=transactions,distinct_event_blocks=blocks,
        active_every_n_turns=event_period_turns,
        receipt_sender_missing=missing_sender,verified_log_width=log_width,
        cross_turn_quote_hits=0,retries=0)
    return result


def current_v4(hours,*,before=False,events_per_turn=0,event_period_turns=1,missing_sender=False,cold_turns=1):
    turns=ceil(hours*3600/5)
    # Safe upper for original exponential+binary search within 8192 blocks.
    # No unmeasured numeric-header cache-hit rate is subtracted from the bound.
    # Warm complete history needs at most one exact event-successor boundary,
    # not a search. No cache hits are assumed for quotes or receipt witnesses.
    search=25 if before else 1;logs=16 if before else 5;membership=0 if before else 3
    active=ceil(turns/event_period_turns) if events_per_turn else 0
    events=events_per_turn*(3 if before else 1)  # original overlapping 15s
    event_blocks=min(150 if before else 50,events)
    fallback=events if missing_sender else 0
    cold_extra=0 if before else min(turns,cold_turns)*24
    methods=Counter(eth_getBlockByNumber=(3+search+membership)*turns+cold_extra+event_blocks*active,
        eth_getCode=turns,eth_call=2*turns,eth_gasPrice=turns,eth_getLogs=logs*turns)
    if not before:methods['eth_getLogs']+=11*min(turns,cold_turns)
    methods.update(eth_getTransactionReceipt=events*active,eth_getTransactionByHash=fallback*active)
    evidence=methods['eth_getLogs']+(event_blocks+events+fallback)*active
    primary=(7 if before else 11)*turns+cold_extra
    auth=(turns if before else ceil(evidence/130))+ceil(primary/130)+2
    methods['eth_chainId']=auth
    witnesses=ceil(event_blocks/50)+ceil(events/50)
    # Primary old/new membership is one batch. Current groups five ten-block
    # log elements; this changes HTTP attempts, never the priced element count.
    physical=turns*((3+search+ceil(logs/4)) if before else 7)+cold_extra+auth
    physical+=(witnesses+ceil(fallback/50))*active
    if not before:physical+=3*min(turns,cold_turns)  # cold 150-block vs warm 50-block batch
    result=demand('robinhood',methods,turns,physical)
    result['classification']='finite 10-block/s scenario; warm successor upper plus explicit cold overhead; no cache-hit assumptions'
    result['minimum_physical_rps_under_scenario']=physical/(hours*3600)
    result['assumptions']=dict(relevant_transactions_per_five_seconds=events_per_turn,
        active_every_n_turns=event_period_turns,receipt_sender_missing=missing_sender,cold_turns=cold_turns)
    result['holding_authority']='Current ordinary policy or original 36-hour tail bridge; longer arithmetic is counterfactual'
    return result


def short_current_reference(hours,*,family):
    turns=ceil(hours*3600/5)
    if family=='pump':
        # Native curve/mint/fees snapshot and its finalized slot timestamp.
        result=demand('solana',Counter(getMultipleAccounts=turns,getBlockTime=turns,
            getGenesisHash=ceil(2*turns/130)+1),turns,2*turns+ceil(2*turns/130)+1)
        result['classification']='curve maintenance snapshot only; native event transport/gap hydration separately required'
        return result
    # The SAME measured 21-turn native trajectory, with a quiet 50-block curve
    # delta, native seven-element sell quote and outer fresh head. This is a
    # scenario extrapolation, not a worst-case bound on indexed-header misses.
    cu=Decimal(17224)/21+164+20+320
    return dict(turns=turns,rpc_cu_scenario=str(cu*turns),rpc_only_modeled_usd=str(cu*turns*PRICE),
        classification='measured 21-turn trajectory extrapolation plus exact quiet quote/flow; cache behavior unverified outside fixture',
        deterministic_trajectory_search_guard_blocks=8192,
        pons_curve_quote_methods=dict(eth_getBlockByNumber=2,eth_call=4,eth_gasPrice=1),
        legitimate_holding_authority='original Current policy including eligible 36-hour bridge; 72h is arithmetic only')


def build():
    proposal=json.loads((ROOT/'operational/position-continuation/RESOURCE_ENVELOPE.example.json').read_text())
    scenarios={}
    for name,kw in dict(long_quiet=dict(events_per_turn=0),
        ordinary_reference=dict(events_per_turn=1,event_period_turns=10),
        high_volatility=dict(events_per_turn=3),
        high_activity=dict(blocks_per_turn=40,events_per_turn=15,missing_sender=True)).items():
        scenarios[name]=dict(before=pons(72,before=True,**kw),after=pons(72,**kw))
    degraded=pons(72,events_per_turn=3)
    degraded['bounded_fault_assumption']='10% failed physical attempts before successful fresh acquisition; zero internal retries; faults must fit original recovery deadlines'
    degraded['extra_failed_attempts']=ceil(degraded['physical_attempts_without_failures']/10)
    # Reservation counts attempted methods even when a provider never returns.
    degraded['additional_cu_upper']=degraded['extra_failed_attempts']*50*60
    degraded['protection_guaranteed']=False
    scenarios['degraded_provider']=degraded
    native_cost=Decimal(proposal['continuation']['native_bytes'])*Decimal('0.0002')*PRICE
    rpc_floor=pons(72)
    verification={
        'rpc_cu':dict(proposed=24000000,quiet_minimum=rpc_floor['rpc_cu'],adequate=False),
        'rpc_elements':dict(proposed=500000,quote_only=86400*6,quiet_model=rpc_floor['rpc_elements'],adequate=False),
        'physical_attempts':dict(proposed=500000,quiet_model=rpc_floor['physical_attempts_without_failures'],
            high_activity_model=scenarios['high_activity']['after']['physical_attempts_without_failures'],adequate='quiet only; stress exceeds'),
        'native_bytes':dict(proposed=32*GIB,average_bytes_per_second=32*GIB/HOLD,
            stopping_bytes_per_second=proposal['continuation']['native_stop_bytes']/HOLD,
            adequacy='UNVERIFIED for one held Pump filter; zero Pons native stream after scout stops'),
        'http_bytes':dict(proposed=GIB,average_delivered_bytes_per_second=GIB/HOLD,
            bytes_per_pons_quiet_turn=GIB/86400,adequacy='UNVERIFIED; no complete held-path traffic capture'),
        'modeled_spend_usd':dict(proposed='20',rpc_quiet_minimum=rpc_floor['rpc_only_modeled_usd'],
            charged_native_ceiling_usd=str(native_cost),combined=str(Decimal(rpc_floor['rpc_only_modeled_usd'])+native_cost),
            adequacy='quiet simultaneous ceiling exceeds $20; actual first lifecycle has one family'),
        'recovery':dict(limits=proposal['recovery'],maximum_seconds=3600,reconnects=32,
            pons_quote_and_quiet_flow=pons(1),adequacy='finite resource accounting proven, sustained protective throughput unverified'),
    }
    costs=[]
    for hours in (0.25,1,6,24,72):
        costs.append(dict(hours=hours,
            pump_survivor_rpc_usd=pump(hours)['rpc_only_modeled_usd'],
            pump_current_curve_snapshot_rpc_usd=short_current_reference(hours,family='pump')['rpc_only_modeled_usd'],
            pump_current_postgrad_compact_rpc_usd=pump(hours,current=True)['rpc_only_modeled_usd'],
            pons_survivor_quiet_rpc_usd=pons(hours)['rpc_only_modeled_usd'],
            pons_current_curve_reference_rpc_usd=short_current_reference(hours,family='pons')['rpc_only_modeled_usd'],
            pons_current_v4_quiet_upper_rpc_usd=current_v4(hours)['rpc_only_modeled_usd']))
    return dict(schema='continuation-resource-demand-v2',base_commit='20f8398abb738c85160aa36c9a8c36c1feedb287',
        live_provider_calls=0,arithmetic_not_authorization=True,
        method_weights=PUBLISHED,price_usd_per_million_rpc_cu='0.525',
        price_reference='https://www.alchemy.com/pricing',
        method_reference='https://www.alchemy.com/docs/reference/compute-unit-costs',
        weights_classification='existing conservative application contract; not verified account billing; no free tier or bulk discounts assumed',
        bootstrap=dict(seconds=1800,funding_seconds=1200,maximum_gross_usd='25',
            lifecycle_count=1,rpc_cu=720000,rpc_elements=10000,physical_attempts=10000,native_bytes=4*GIB,modeled_spend_usd='3'),
        scenarios=scenarios,pump_72_hours=dict(before=pump(72,before=True),after=pump(72),
            current_before=pump(72,current=True,before=True),current_after=pump(72,current=True),
            compact_failure_every_turn=pump(72,current=True,fallbacks=51840)),
        pons_current_v4=dict(legitimate_36_hour_quiet=dict(before=current_v4(36,before=True),after=current_v4(36)),
            counterfactual_72_hour_quiet=dict(before=current_v4(72,before=True),after=current_v4(72)),
            high_volatility_36_hours=current_v4(36,events_per_turn=5),
            high_activity_36_hours=current_v4(36,events_per_turn=25,missing_sender=True),
            repeated_restart_36_hours=current_v4(36,cold_turns=32)),
        current_curve_reference_36_hours=short_current_reference(36,family='pons'),
        costs_rpc_only=costs,proposal_verification=verification,
        conditional_wider_logs=dict(before_activation_requires='existing exact-filter nonempty canonical comparison AND account entitlement verification',
            quiet_40_block_ranges=pons(72,log_width=40),one_event_per_turn=pons(72,log_width=40,events_per_turn=1)),
        recommended_funded_envelope=None,
        service_envelope=dict(cpu_cores='1.8',rss_readiness_bytes=6*GIB,systemd_memory_max_bytes=7*GIB,
            queue_depth=64,queue_wait_seconds=5,pons_local_rps=2,
            quote_freshness_seconds=5,pons_survivor_scheduling_seconds=3,pump_and_current_scheduling_seconds=5,
            cpu_memory_latency_adequacy='offline CPU measurements only; native transport and provider tails unverified'),
        storage=dict(current=dict(record_limit=8192,sqlite_page_limit=16384,sqlite_page_bytes=4096,
                quote_retention_seconds=120,maintenance_seconds=60,native_journal_segment_records=64,
                expired_snapshot_dependencies_retained=True,diagnostic_records_per_category=512,
                baseline_exhausted_turn=8191,baseline_sqlite_bytes=3821568,
                measured_36_hour_turns=25920,measured_maximum_records=101,measured_sqlite_bytes=360448,
                classification='actual native journal/quote/restart fixture; variable controller bodies still obey 32768-byte record and 64-MiB page caps'),
            survivor=dict(old_quote_limit=10000,new_persistent_quote_records_per_turn=0,
                snapshot_ledger='one bounded native in-memory Store per quote; economic book and authenticated history remain durable',
                measured_72_hour_turns=86401,measured_retained_points=28803,measured_retained_events=2402,
                measured_sqlite_bytes=9293824,measured_wal_bytes=9405992,
                point_limit=100000,point_hot_seconds=86400,event_hot_seconds=3600,
                classification='actual two-events-per-turn native history fixture; busy event bytes and shared plane footprints remain scenario dependent'),
            v4_history=dict(current_hot_seconds=900,required_original_boundary_events_retained=True,
                range_event_limit=16384,range_physical_attempt_limit=64,
                cache_bytes_per_map=16*1024**2,cache_map_count=5,
                memory_classification='80-MiB serialized cache ceiling plus Python/index overhead; whole process bound enforced separately',
                page_pressure_exhausted_records=2012,page_pressure_pending_exit_preserved=True)),
        limitation='No offline fixture proves provider tail latency, account entitlement, delivered stream volume or arbitrary outage safety. Funding remains closed.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    args=parser.parse_args();raw=json.dumps(build(),sort_keys=True,indent=2)+'\n'
    if args.output:args.output.write_text(raw)
    else:print(raw,end='')


if __name__=='__main__':main()
