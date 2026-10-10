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
                accounting.stream(record['stream_type'],int(record['delivered_payload_bytes']),family=family,consumer=consumer,redelivery=record.get('redelivery'))
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
            # Unknown byte measurements contribute no fabricated delivery.
            # The explicit missing-measurement counters above retain uncertainty.
            accounting.started(label,methods,int(signature[1] or 0),retry=int(signature[3]))
            accounting.completed(label,int(signature[2] or 0),failed=bool(signature[4]))
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


def join_native_decisions(purchases,evidence,consumers,*,limit=4096):
    """Join existing records; this function acquires and authenticates no evidence.

    Native validators supply authenticated projections. Missing links stay
    unknown. Joining multiple consumers never creates another provider purchase.
    """
    if any(len(rows)>limit for rows in (purchases,evidence,consumers)):
        raise ValueError('offline_decision_join_bound')
    def indexed(rows,key):
        out={}
        for row in rows:
            identity=row[key]
            if not isinstance(identity,str) or not 1<=len(identity)<=160:
                raise ValueError('offline_decision_join_identity')
            if identity in out and out[identity]!=row:raise ValueError('offline_decision_join_conflict')
            out[identity]=row
        return out
    bought=indexed(purchases,'purchase_id');facts=indexed(evidence,'evidence_id')
    decisions=indexed(consumers,'decision_id');links=[];linked=set();missing=0;late=0
    for row in decisions.values():
        ids=row.get('evidence_ids',[])
        if len(ids)>32:raise ValueError('offline_decision_join_evidence_bound')
        for identity in ids:
            fact=facts.get(identity)
            if not fact or fact.get('authenticated_by_native_validator') is not True:
                missing+=1;continue
            if fact.get('canonical_hash')!=row.get('canonical_hash'):
                raise ValueError('offline_decision_join_canonical_disagreement')
            refs=fact.get('purchase_ids',[])
            if len(refs)>64:raise ValueError('offline_decision_join_purchase_bound')
            for purchase in refs:
                if purchase not in bought:missing+=1;continue
                linked.add(purchase)
                missed=row['decided_at']>row['original_deadline']
                late+=int(missed)
                links.append(dict(purchase_id=purchase,evidence_id=identity,consumer=row['consumer'],
                    decision_id=row['decision_id'],original_deadline=row['original_deadline'],
                    decided_at=row['decided_at'],original_deadline_met=not missed,
                    canonical_hash=row['canonical_hash'],native_decision=row['native_decision']))
                if len(links)>limit*32:raise ValueError('offline_decision_join_link_bound')
    return dict(links=links,unique_physical_purchases=len(bought),linked_physical_purchases=len(linked),
        unlinked_purchases=len(bought)-len(linked),missing_or_unauthenticated_evidence_links=missing,
        late_consumer_links=late,failed_physical_purchases=sum(bool(r.get('failed')) for r in bought.values()),
        charged_failure_purchases=sum(bool(r.get('failed')) and r.get('billed_cu') is not None and
            Decimal(str(r['billed_cu']))>0 for r in bought.values()),
        failure_charge_status='UNKNOWN unless separately billed',
        unresolved_purchase_outcomes=sum(r.get('completed') is not True for r in bought.values()),
        join_authenticates_inputs=False,provider_purchases_added=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture');parser.add_argument('--output',required=True)
    args=parser.parse_args();source=Path(args.fixture)
    if source.stat().st_size>8*1024*1024:raise ValueError('offline_attribution_input_bound')
    value=json.loads(source.read_text());report=attribute(value['records'])
    if value.get('native_evidence') is not None:
        report['native_decision_join']=join_native_decisions(
            [r for r in value['records'] if r.get('kind','purchase')=='purchase'],
            value['native_evidence'],value.get('native_consumers',[]))
    import hashlib
    report['input_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    report['input_classification']=value.get('classification','UNKNOWN')
    report['captured_measurements']=value.get('captured_measurements',[])
    Path(args.output).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')


if __name__=='__main__':main()
