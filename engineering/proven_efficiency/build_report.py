"""Build a sanitized report from existing captured usage and offline benchmarks.

No provider access or rate refresh. The checked-in COST_INPUT can be replayed
without the original captures; their hashes retain provenance.
"""
import argparse
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from operational.provider_cost_attribution import attribute
from operational.tests import network_guard


def captured(path):
    if path.stat().st_size>8*1024*1024:raise ValueError('captured_usage_size')
    return json.loads(path.read_text())['data'],dict(file=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def usage_measurements(directory):
    summary,source=captured(directory/'alchemy-usage-summary.json')
    monthly=summary['totals']['monthToDate']
    measurements=[dict(classification='PREVIOUSLY_CAPTURED_PROVIDER_REPORTED_AGGREGATE',
        source=source,billing_period=summary['billingPeriod'],freshness=summary['freshness'],
        month_to_date=monthly,operation='unattributed',physical_requests=None,
        note='One month-to-date total only. Last-7/30-day windows overlap and are not added.')]
    for filename in ('alchemy-usage-by-app.json','alchemy-yellowstone-usage.json'):
        data,source=captured(directory/filename);groups=defaultdict(lambda:Decimal(0))
        for row in data['data']:
            key=tuple(row.get('dimensions',{}).get(k,'unknown') for k in ('network','requestType'))+(row['unit'],)
            groups[key]+=Decimal(row['amount'])
        groups=[dict(network=k[0],request_type=k[1],unit=k[2],amount=str(v)) for k,v in
            sorted(groups.items(),key=lambda item:item[1],reverse=True)]
        measurements.append(dict(classification='PREVIOUSLY_CAPTURED_SELECTED_WINDOW_ROWS',source=source,
            query={k:data['query'][k] for k in ('startTime','endTime','granularity','products')},
            freshness=data['freshness'],returned_rows=len(data['data']),
            partial_rows=sum(row.get('isPartial') is True for row in data['data']),groups=groups,
            operation='unattributed',physical_requests=None,
            note='Account/app identifiers omitted. Returned windows are not a frequency model or additive to month-to-date. TB is kept in the reported unit, not converted into CU.'))
    return measurements


def build(directory,output):
    benchmark=json.loads((output/'BENCHMARK.json').read_text())
    fixture=dict(schema_version=1,classification='OFFLINE MOCKED TRANSPORT RECORDS; NOT PROVIDER BILLINGS',
        provenance=dict(benchmark='BENCHMARK.json',method='native Pons fresh_state with original/optimized frozen scaling comparison',
            description='One add rejected by the original exposure ceiling. Original attempted two mocked HTTP transports; optimized attempted none.'),
        records=benchmark['native_pons_precheck']['original']['purchase_records'],
        captured_measurements=usage_measurements(directory))
    data=json.dumps(fixture,indent=2,sort_keys=True)+'\n';(output/'COST_INPUT.json').write_text(data)
    report=attribute(fixture['records']);report.update(input_classification=fixture['classification'],
        input_sha256=hashlib.sha256(data.encode()).hexdigest(),captured_measurements=fixture['captured_measurements'])
    (output/'COST_ATTRIBUTION.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    cu=report['totals']['known_estimated_cu'];rate=Decimal('0.525');count=1000
    model=dict(classification='CONDITIONAL SENSITIVITY; NOT OBSERVED MONTHLY SAVINGS',
        frozen_rate_usd_per_million_cu=str(rate),rate_source='engineering/solana_closure/cost_model.py:PRICING',
        frozen_schedule='meme_machine/runtime/alchemy-cu-schedule.json',cu_per_denied_add=cu,
        formula='avoided CU = N * 46; avoided USD = N * 46 * 0.525 / 1000000',
        explicitly_assumed_denied_adds_per_month=count,
        conditional_monthly_cu=count*cu,conditional_monthly_usd=str(Decimal(count*cu)*rate/Decimal(1000000)),
        assumptions=['N is a hypothetical sensitivity input, not an inferred production frequency.',
            'Both original methods reach the provider as cache misses; otherwise these physical savings are smaller or zero.',
            'Only the first fresh-state header and eth_call are priced; subsequent research and quotes are unspecified.',
            'The frozen repository rate applies; no current invoice, allowance or account discount is assumed.',
            'No overlap with PR #126 held snapshots or existing Pons reuse is added.'],
        actual_deployed_provider_savings='0; this branch is not deployed',
        actual_infrastructure_savings='0; infrastructure unchanged',
        cpu_savings_are_dollars=False)
    (output/'COST_MODEL.json').write_text(json.dumps(model,indent=2,sort_keys=True)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captured-directory',type=Path,required=True)
    parser.add_argument('--output-directory',type=Path,default=Path('operational/proven-efficiency-phase1'))
    args=parser.parse_args();network_guard();build(args.captured_directory,args.output_directory)


if __name__=='__main__':main()
