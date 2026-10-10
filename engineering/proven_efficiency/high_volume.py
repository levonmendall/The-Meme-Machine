"""Offline native replay and sanitized attribution of an existing provider trace.

Synthetic sensitivities are separate from observed purchases. No provider client
is invoked, no deployed DB is opened, and no blanket workload multiplier is used.
"""
import argparse
from collections import Counter,defaultdict
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import time
from unittest.mock import patch

from operational.tests import network_guard
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.runtime.robinhood.plane import Plane,digest
from meme_machine.runtime.robinhood.pons import durable_cache,shared_evidence_domain
from meme_machine.runtime.cu import estimate
from operational.provider_cost_attribution import attribute
from engineering.solana_capacity.analyze import compressed_lines
from engineering.solana_capacity.offline_attribution import sha256
from engineering.continuation_resources.model import pons,current_v4
from tests.test_pons_dense_v4_receipts import run,fixture,original_v4,optimized,ENDPOINT
from tests.test_pump_known_slot_block_repair import fixture as pump_fixture,PROFILE,NOW
from meme_machine.solana_candidate_join import authenticated_block_logs


def counts(tape):
    schedule=json.loads(Path('meme_machine/runtime/alchemy-cu-schedule.json').read_text())
    weights=dict(schedule['methods'],**schedule['throughput_overrides'])
    return dict(physical_requests=tape.batches,rpc_elements=sum(tape.methods.values()),methods=dict(tape.methods),
        estimated_billed_cu=estimate(tape.methods)['estimated_cu'],
        estimated_throughput_cu=sum(weights[m]*n for m,n in tape.methods.items()),
        delivered_payload_bytes=tape.response_bytes,request_bytes=tape.request_bytes)


def shared_replay(root):
    plane=Plane(root/'shared.sqlite');domain=shared_evidence_domain(ENDPOINT)
    before=Counter();after=Counter();events=0;cpu={};vectors={}
    try:
        # Thirty-two distinct canonical blocks, two independent native consumers.
        for label,module,acc in (('original',original_v4(),before),('optimized',optimized,after)):
            start=time.process_time()
            for seed in range(32):
                reference=None
                for consumer in ('current','survivor'):
                    tape,ctx,options=fixture(seed=seed)
                    if label=='optimized':ctx.cache=durable_cache(plane,domain)
                    with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=tape),patch('time.monotonic',return_value=100):
                        result=module.collect_v4_activity(ENDPOINT,**options)
                    vector={k:v for k,v in result.items() if k!='provider_sessions'}
                    if label=='original':vectors[(seed,consumer)]=digest(vector)
                    else:assert vectors[(seed,consumer)]==digest(vector)
                    if reference is None:reference=vector
                    else:assert reference==vector
                    if label=='original':events+=len(result['swaps'])
                    acc.update({k:v for k,v in counts(tape).items() if isinstance(v,int)})
            cpu[label]=time.process_time()-start
        rows=plane.db.execute('SELECT COUNT(*) FROM evidence WHERE namespace=?',(domain+':receipt',)).fetchone()[0]
        assert rows==3200
        return dict(classification='SYNTHETIC_NATIVE_STRESS; not Pro specimens or observed market incidence',
            distinct_canonical_blocks=32,required_receipts_per_block=100,independent_consumers=2,
            per_consumer_economic_vectors_equal=True,original_economic_event_observations=events,
            original=dict(before),optimized=dict(after),cpu_seconds=cpu,durable_required_receipts=rows,
            memory_cache_record_limit=8192,durable_shared_receipt_byte_limit=64*1024*1024,
            actual_provider_requests=0)
    finally:plane.close()


def retained_capture(directory):
    manifest=json.loads((directory/'manifest.json').read_text());name='http.ndjson.zlib'
    digest=sha256(directory/name)
    if digest!=manifest['files'][name]['sha256']:raise ValueError('capture_manifest_mismatch')
    rows=[];request_hashes=Counter();transactions={};transaction_purchases=Counter();families=Counter();recorded_cu=0;starts=set()
    for index,row in enumerate(compressed_lines(directory/name)):
        if index>=4096:raise ValueError('capture_purchase_bound')
        starts.add(row['started']);recorded_cu+=row['cu'];family=row['family'];families[family]+=1
        operation=('pump_held_protection' if family in ('pump_position','pumpswap_position') else
            'recovery_restart' if family in ('replay_source','rolling_recovery_missing_logs_source') else
            'pump_discovery' if family=='pump_source' else 'unattributed')
        method=row['methods'];requests=row.get('requests') or []
        request_hashes[hashlib.sha256(json.dumps(requests,sort_keys=True).encode()).hexdigest()]+=1
        if method==['getTransaction'] and requests:
            transaction_purchases[requests[0]['params'][0]]+=1
            response=row.get('response',{}).get('result')
            if isinstance(response,dict) and type(response.get('slot')) is int:
                transactions[requests[0]['params'][0]]=response['slot']
        rows.append(dict(purchase_id='captured-http-'+str(index),methods=method,operation=operation,
            family='pump' if operation.startswith('pump_') or family.endswith('missing_logs_source') else 'shared',
            consumer='shared',purpose='held_protection' if operation=='pump_held_protection' else
                'recovery_restart' if operation=='recovery_restart' else 'discovery' if operation=='pump_discovery' else 'unknown',
            request_bytes=sum(len(json.dumps(r).encode()) for r in requests),
            delivered_payload_bytes=row['bytes'],failed='rpc_error' in row,completed=True))
    if len(starts)!=len(rows):raise ValueError('capture_transport_identity_ambiguous')
    report=attribute(rows);report['purchases_without_request_byte_measurement']=len(rows)
    # The capture retained JSON arguments but not exact encoded wire requests.
    for r in report['operations']:r.pop('request_bytes',None)
    report['totals'].pop('request_bytes',None)
    if sha256(directory/'audit.json.gz')!=manifest['files']['audit.json.gz']['sha256']:
        raise ValueError('capture_audit_manifest_mismatch')
    with gzip.open(directory/'audit.json.gz','rt') as source:audit=json.load(source)
    slots=Counter(transactions.values())
    return dict(classification='OBSERVED_RETAINED_COMPLETED_HTTP_TRACE; CU fields are tariff estimates, not invoices',
        source_commit=manifest['source_commit'],input=dict(path=str(directory/name),sha256=digest),
        completed_http_records=len(rows),original_family_counts=dict(families),attribution=report,
        recorded_capture_schedule_cu=recorded_cu,unique_required_missing_pump_bodies=len(transactions),
        observed_getTransaction_purchases=sum(transaction_purchases.values()),
        repeated_getTransaction_purchases=sum(n-1 for n in transaction_purchases.values()),
        actual_retry_count=None,pre_response_http_failure_count=None,
        retry_status='NOT RECOVERABLE from this retained completed-response trace',
        known_missing_body_slots=len(slots),missing_bodies_per_known_slot=dict(Counter(slots.values())),
        potential_repeated_argument_records=sum(n-1 for n in request_hashes.values()),
        repetition_caveat='Includes required fresh heads/quotes; equality of arguments does not prove wasted purchases.',
        stream_delivery_by_phase=audit['traffic'],retained_window=dict(start=audit['start'],end=audit['measurement_close']),
        omitted_failure_caveat='HTTP failures before response read are absent from this tape; no billed failure or retry count is invented.',
        measured_billed_cu=None,monthly_full_market_forecast=None,
        known_eliminable_getTransaction_calls=0,
        savings_caveat='Known slots alone are not authenticated block census, resource proof or unknown interval completeness.')


def build(root,capture):
    comparisons=[]
    for relevant,total in ((1,100),(24,24),(25,40),(100,100),(100,129)):
        a,x,_,_=run(original_v4(),relevant=relevant,total=total)
        b,y,_,_=run(optimized,relevant=relevant,total=total);assert a==b
        comparisons.append(dict(required=relevant,total_block_transactions=total,original=x,optimized=y,economic_vectors_equal=True))
    stress=shared_replay(root)
    join,keys,block=pump_fixture();_,witness=join.block_repair_groups(keys,PROFILE,NOW)[0]
    logs=authenticated_block_logs(block,witness,keys,PROFILE['max_response_bytes']);assert len(logs)==8
    quiet=pons(1);current=current_v4(1,cold_turns=0)
    per_bundle=stress['original']['estimated_billed_cu']//32-stress['optimized']['estimated_billed_cu']//32
    sensitivity=[dict(synthetic_bundles_per_month=n,avoided_cu=n*per_bundle,
        conditional_usd=str(Decimal(n*per_bundle)*Decimal('0.525')/1000000)) for n in (1000,10000,100000)]
    return dict(schema='high-volume-efficiency-handoff-v1',classification='OFFLINE; no paid workload or service start',
        pro_artifacts_inspected=False,pons_density_comparisons=comparisons,shared_native_stress=stress,
        pump_known_slot_repair=dict(required_missing_bodies=8,known_authenticated_slots=1,original_requests=8,
            optimized_requests=1,modeled_billed_cu_avoided=280,modeled_throughput_cu_avoided=280,
            response_bytes=len(json.dumps(block).encode()),native_log_frames_equivalent=True,
            native_interval_completeness_unchanged=True,capability_gate_default='individual repair'),
        retained_provider_capture=retained_capture(capture),
        capacity=dict(unchanged_pons_requests_per_second=2,three_second_start_capacity=6,five_second_start_capacity=10,
            quiet_survivor_wire_minimum_per_three_second_cycle=5,quiet_survivor_model=quiet,
            quiet_current_model=current,two_survivors_wire_minimum=10,
            two_survivors_wire_minimum_rps='10/3 = 3.333333...',two_survivors_feasible_at_two_rps=False,
            dense_receipts_cannot_fix_quiet_deficit=True,
            hybrid_solana_governor_interval_seconds=.05,
            caveat='Existing finite no-failure models; network/service/authentication overhead is additional. The existing hybrid Solana exception was not changed.'),
        monthly_sensitivities=dict(classification='HYPOTHETICAL; no observed dense-block monthly distribution',
            bundle='two consumers, same canonical block, 100 required receipts, measured capability and complete successful responses',
            avoided_cu_per_bundle=per_bundle,rows=sensitivity,no_double_counting='1980 CU from first dense acquisition + 2000 CU from second consumer reuse',
            excluded='Qualification/stream baseline, retries, provider package allowances, CPU dollars and previous PR savings'),
        deprecated_forecasts='Previous busy/extreme blanket RPC multipliers are not production forecasts. Pro matched specimens are unavailable.',
        actual_deployed_provider_savings=0,actual_infrastructure_savings_usd=0)


def main():
    p=argparse.ArgumentParser();p.add_argument('--capture',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();network_guard()
    with Scratch() as scratch:
        result=build(scratch.path,args.capture);scratch.check()
        args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');scratch.success=True
    print(json.dumps(dict(output=str(args.output),observed_http_records=result['retained_provider_capture']['completed_http_records'],actual_provider_requests=0)))


if __name__=='__main__':main()
