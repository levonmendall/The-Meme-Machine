"""Reproducible offline CPU/allocation and acquisition-stage comparisons."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import sqlite3
import time
import tracemalloc
from unittest.mock import patch

from operational.tests import network_guard
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.runtime.source_artifacts import REGISTRY,invalidate_sources
from meme_machine.lanes.pons.pons import TEMPLATE,curve_abi
from meme_machine.lanes.pons.abi import decode_event
from meme_machine.runtime.survivor_paper_book import PaperBook
from meme_machine.runtime.survivor_commit import restore_risk,scale,_fold_risk
from tests.proven_efficiency_baseline import original_restore_risk,original_scale
from tests.test_scaling_necessary_conditions import ScalingNecessaryTests


def timed(fn,count):
    started=time.process_time();wall=time.perf_counter()
    last=None
    for _ in range(count):last=fn()
    return last,dict(cpu_seconds=time.process_time()-started,wall_seconds=time.perf_counter()-wall,iterations=count)


def peak(fn,count=25):
    tracemalloc.start()
    for _ in range(count):fn()
    current,maximum=tracemalloc.get_traced_memory();tracemalloc.stop()
    return dict(retained_python_bytes=current,peak_python_bytes=maximum,iterations=count)


def artifacts():
    capture_path=Path('tests/lanes/pons/fixtures/protocol_capture_35370277849.json')
    capture=json.loads(capture_path.read_text());selected={c['address'] for c in capture['lanes']['pons']['curves']}
    events=[e for e in capture['lanes']['pons']['unverified_curve_activity'] if e['address'] in selected]
    event=events[0]
    def old():return decode_event(json.loads(TEMPLATE.read_text())['abi'],event)
    def new():return decode_event(curve_abi(),event)
    original,old_time=timed(old,1000);old_peak=peak(old)
    invalidate_sources();before=REGISTRY.stats().get('parses',0)
    started=time.process_time();candidate=new();cold=time.process_time()-started
    optimized,new_time=timed(new,1000);new_peak=peak(new)
    assert original==candidate==optimized
    return dict(classification='captured event decoding; repetition count is an explicit benchmark workload',
        source_path=str(TEMPLATE.relative_to(Path.cwd())),source_bytes=TEMPLATE.stat().st_size,
        capture_path=str(capture_path),capture_sha256=hashlib.sha256(capture_path.read_bytes()).hexdigest(),
        eligible_captured_events=len(events),old=old_time,new=new_time,cold_validation_cpu_seconds=cold,
        old_template_parses=1000,new_source_parses_including_compiler_dependency=REGISTRY.stats()['parses']-before,
        new_registry=REGISTRY.stats(),old_allocations=old_peak,new_allocations=new_peak,
        identical_decoding=True,provider_calls=0)


def risks(root):
    book=PaperBook(root/'bench-book',run_id='b',lane='survivor',policy_hash='p',initial=1000000)
    try:
        book.reserve('b:p',100,1,{});book.transition('b:p','filled',2,amount=100,tokens=400)
        state=original_restore_risk(book,'b:p')
        for at in range(3,259):
            state=dict(state,high_water_bps=at,high_at=at)
            book.transition('b:p','mark',at,evidence=dict(risk_state=state))
        before_proof=book.replay()
        old,old_time=timed(lambda:original_restore_risk(book,'b:p'),100)
        book._risk_replay_cache=None
        with patch('meme_machine.runtime.survivor_commit._fold_risk',wraps=_fold_risk) as folds,patch.object(book,'replay',wraps=book.replay) as verifications:
            new,new_time=timed(lambda:restore_risk(book,'b:p'),100)
            fold_count=folds.call_count;verify_count=verifications.call_count
        assert old==new and book.replay()==before_proof
        return dict(classification='100 reads of one unchanged 258-event journal; no observed production frequency inferred',
            old=old_time,new=new_time,old_risk_folds=100,new_risk_folds=fold_count,
            monetary_verifications_retained=verify_count,identical_risk_state=True,identical_monetary_proof=True,provider_calls=0)
    finally:book.close()


def scaling(root):
    tests=ScalingNecessaryTests();rows=[]
    scenarios=[('equity_ceiling',dict(original=80000),9000),('gross_high_distance',{},6999),('high_threshold',dict(high=9999),9000),('valid_add',{},9000)]
    for name,fixture,price in scenarios:
        results=[]
        for label,path in [('original',original_scale),('optimized',scale)]:
            folder=root/(name+'-'+label);folder.mkdir();book,sleeve,adapter=tests.fixture(folder,**fixture)
            try:
                adapter.current_return=price;started=time.process_time()
                result=tests.run_path(path,book,sleeve,adapter)
                results.append(dict(path=label,cpu_seconds=time.process_time()-started,stages=dict(Counter(adapter.calls)),
                    native_result=result,proof=book.replay(),position=book._load('r:p'),capital=sleeve.reconcile()))
            finally:book.close();sleeve.close()
        assert all(results[0][k]==results[1][k] for k in ('native_result','proof','position','capital'))
        rows.append(dict(scenario=name,original=results[0],optimized=results[1],identical_decision_and_accounting=True))
    return dict(classification='offline native integer-book replay; stage counts are not measured provider billings',scenarios=rows,provider_calls=0)


def native_pons_precheck(root):
    from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
    from meme_machine.lanes.pons.pons import factory_record
    from meme_machine.lanes.pons.provider import Rpc
    from meme_machine.runtime.provider_purchases import ledger,provider_work
    from types import SimpleNamespace
    tests=ScalingNecessaryTests();counts=[]
    capture=json.loads(Path('tests/lanes/pons/fixtures/pons_lineage_35378762520.json').read_text())['v2']
    record=factory_record(capture['factory_record_raw']);token=record['token']
    key=dict(currency0='0x'+'00'*20,currency1=token,fee=3000,tick_spacing=60,hook='0x'+'11'*20)
    for label,path in [('original',original_scale),('optimized',scale)]:
        folder=root/('pons-precheck-'+label);folder.mkdir();book,sleeve,adapter=tests.fixture(folder,original=80000)
        methods=[];purchases=[]
        def transport(request,*args,**kwargs):
            body=json.loads(request.data);method=body['method']
            methods.append(method)
            if method=='eth_getBlockByNumber':value=dict(number='0x1',hash='fixture',timestamp='0x7d0')
            elif method=='eth_call':value='0x'+f'{1<<96:064x}'
            else:raise AssertionError(method)
            response=json.dumps(dict(jsonrpc='2.0',id=body['id'],result=value)).encode()
            purchases.append(dict(purchase_id='native-pons-precheck-'+str(len(purchases)),methods=[method],
                request_bytes=len(request.data),delivered_payload_bytes=len(response),
                operation='scaling_requalification',family='pons',consumer='survivor',purpose='scaling_requalification'))
            return BytesIO(response)
        adapter._provider=lambda:None;adapter.rpc=Rpc('https://offline.invalid/no-key',retries=0)
        adapter.history=SimpleNamespace(get=lambda candidate:dict(block=1,
            decision=dict(features=dict(independent_buyers=20)),
            graduation=dict(key=key,transition=dict(market=capture['expected']['pool_id']))))
        adapter.fresh_state=lambda candidate:Runtime.fresh_state(adapter,candidate)
        try:
            with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=transport),provider_work(
                    'scaling_requalification',family='pons',consumer='survivor'):
                tests.run_path(path,book,sleeve,adapter)
            counts.append(dict(path=label,fixture_acquisitions=dict(Counter(methods)),
                mocked_transport_attempts=len(purchases),purchase_records=purchases,
                purchase_accounting=ledger(adapter.rpc).snapshot(),native=book.replay()))
        finally:book.close();sleeve.close()
    assert counts[0]['native']==counts[1]['native']
    assert (counts[0]['mocked_transport_attempts'],counts[1]['mocked_transport_attempts'])==(2,0)
    return dict(classification='existing Pons Runtime.fresh_state and native RPC with mocked HTTP; zero paid provider requests',
        original=counts[0],optimized=counts[1],avoided_fixture_rpc_elements=2,
        avoided_mocked_physical_transport_attempts=2,
        avoided_uncached_method_bundle={'eth_getBlockByNumber':1,'eth_call':1},
        caveat='46 CU only if both original methods would be physical cache misses at the frozen schedule; deeper savings unspecified')


def attribution_cost(root):
    from meme_machine.runtime.provider_purchases import ProviderPurchases,provider_work
    accounting=ProviderPurchases()
    label=dict(operation='scaling_requalification',family='pons',consumer='survivor',purpose='scaling_requalification')
    def record():
        accounting.started(label,['eth_call','eth_getBlockByNumber'],120)
        accounting.completed(label,1000)
    _,cost=timed(record,50000)
    from meme_machine.runtime.robinhood.provider_usage import record as durable
    from tests.proven_efficiency_baseline import original_provider_usage_record
    timings=[]
    for label,fn in [('original',original_provider_usage_record),('optimized',durable)]:
        db=sqlite3.connect(root/('purchase-'+label+'.sqlite'))
        try:
            db.execute('CREATE TABLE provider_usage(endpoint TEXT,lane TEXT,metric TEXT,value REAL,PRIMARY KEY(endpoint,lane,metric))')
            row=dict(endpoint_fingerprint='offline',lane='pons',methods=['eth_call','eth_getBlockByNumber'],
                physical_requests=1,request_bytes=120,response_bytes=1000,purchase_work=dict(
                    operation='scaling_requalification',family='pons',consumer='survivor',purpose='scaling_requalification'))
            def transaction():
                fn(db,row);fn(db,row,wire=False);db.commit()
            _,measurement=timed(transaction,500)
            timings.append(dict(path=label,**measurement,retained_counter_rows=db.execute('SELECT COUNT(*) FROM provider_usage').fetchone()[0]))
        finally:db.close()
    return dict(classification='synthetic instrumentation; zero provider work; durable comparison retains original transaction count',
        **cost,cpu_microseconds_per_attempt=cost['cpu_seconds']*1000000/50000,
        durable_transaction_comparison=timings,retained_label_rows=len(accounting.rows),provider_calls=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);args=parser.parse_args()
    network_guard()
    with Scratch() as scratch:
        result=dict(schema_version=1,python=sys.version.split()[0],classification='OFFLINE; measurements are this host and explicit fixtures',
            artifacts=artifacts(),risk_replay=risks(scratch.path),scaling=scaling(scratch.path),
            native_pons_precheck=native_pons_precheck(scratch.path),attribution_overhead=attribution_cost(scratch.path),
            actual_provider_requests_dispatched=0,actual_infrastructure_spending_reduction='0; no infrastructure changed')
        scratch.check();Path(args.output).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');scratch.success=True
    print(json.dumps({k:result[k] for k in ('python','actual_provider_requests_dispatched','actual_infrastructure_spending_reduction')}))


if __name__=='__main__':main()
