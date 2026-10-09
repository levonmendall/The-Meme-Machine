"""Offline, bounded attribution of captured physical purchase and consumer records.

Run: python -m operational.provider_cost_attribution fixture.json --output report.json
Input records contain no endpoints, arguments, secrets or response bodies.
Repeated purchase IDs describe shared consumption and are charged only once.
"""
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

from meme_machine.runtime.provider_purchases import ProviderPurchases,provider_work,OPERATIONS


def attribute(records,*,max_purchases=4096,max_records=50000):
    accounting=ProviderPurchases();seen={};shared=0;known_billed=Decimal(0);unbilled=0;duplicates=0
    missing_request_bytes=0;missing_response_bytes=0
    for index,record in enumerate(records):
        if index>=max_records:raise ValueError('offline_attribution_record_bound')
        kind=record.get('kind','purchase');methods=record.get('methods',[])
        operation=record.get('operation','unattributed')
        family=record.get('family','unknown');consumer=record.get('consumer','unknown')
        with provider_work(operation,family=family,consumer=consumer,purpose=record.get('purpose','unknown')):
            from meme_machine.runtime.provider_purchases import work_label
            label=work_label()
            if kind=='consumer':
                accounting.consumer(methods,cache_hit=record.get('cache_hit'))
                continue
            if kind=='stream':
                accounting.stream(record['stream_type'],int(record['delivered_payload_bytes']),family=family,consumer=consumer)
                if record.get('billed_cu') is None:unbilled+=1
                else:known_billed+=Decimal(str(record['billed_cu']))
                continue
            if kind!='purchase':raise ValueError('offline_attribution_record_kind')
            purchase=record['purchase_id']
            signature=(tuple(methods),record.get('request_bytes',0),record.get('delivered_payload_bytes',0),
                record.get('retry',0),record.get('failed',False),record.get('billed_cu'))
            accounting.consumer(methods,cache_hit=record.get('cache_hit'))
            if purchase in seen:
                if seen[purchase]!=signature:raise ValueError('shared_purchase_evidence_conflict')
                shared+=1;duplicates+=1;continue
            if len(seen)>=max_purchases:raise ValueError('offline_attribution_purchase_bound')
            seen[purchase]=signature
            missing_request_bytes+=int(record.get('request_bytes') is None)
            missing_response_bytes+=int(record.get('delivered_payload_bytes') is None)
            accounting.started(label,methods,int(signature[1]),retry=int(signature[3]))
            accounting.completed(label,int(signature[2]),failed=bool(signature[4]))
            if signature[5] is None:unbilled+=1
            else:known_billed+=Decimal(str(signature[5]))
    report=accounting.snapshot()
    report.update(classification='OFFLINE_CAPTURE_OR_MODEL; not a newly measured provider bill',
        unique_physical_purchases=len(seen),shared_logical_consumers=shared,
        repeated_purchase_records=duplicates,known_measured_billed_cu=str(known_billed),
        total_measured_billed_cu=None if unbilled else str(known_billed),
        purchases_without_billing_measurement=unbilled,
        purchases_without_request_byte_measurement=missing_request_bytes,
        purchases_without_payload_byte_measurement=missing_response_bytes,
        operation_categories=list(OPERATIONS),
        largest_modeled_drivers=sorted(report['operations'],key=lambda r:r['known_estimated_cu'],reverse=True)[:12])
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture');parser.add_argument('--output',required=True)
    args=parser.parse_args();source=Path(args.fixture)
    if source.stat().st_size>8*1024*1024:raise ValueError('offline_attribution_input_bound')
    value=json.loads(source.read_text());report=attribute(value['records'])
    import hashlib
    report['input_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    report['input_classification']=value.get('classification','UNKNOWN')
    report['captured_measurements']=value.get('captured_measurements',[])
    Path(args.output).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')


if __name__=='__main__':main()
