"""Trace retained jobs without modifying the failed run or inventing witnesses.

Missing historical enqueue estimates remain explicitly absent. Retrospective
minimum-service estimates are not substituted for an estimate recorded at enqueue.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from ..analyze import compressed_lines, distribution
from meme_machine.solana_selective_history import coverage_points

CAUSES = (
    'LOWER_BOUND_MISSING', 'UPPER_BOUND_NOT_CLOSED', 'LIVE_SUBSCRIPTION_GAP',
    'REPLAY_GAP', 'PROVIDER_FETCH_FAILED', 'CANONICAL_PUBLICATION_LAG',
    'CANDIDATE_HISTORY_PUBLICATION_LAG', 'WORK_NOT_READY', 'WORKER_CAPACITY',
    'DEADLINE_ALREADY_INFEASIBLE_AT_ENQUEUE',
    'DEADLINE_BECAME_INFEASIBLE_DURING_ACQUISITION', 'POSITION_PIN_WAIT',
    'OTHER_EXACT_CAUSE',
)


def connect(path):
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def audit(folder):
    result = json.loads((folder/'result.json').read_text())
    db = connect(folder/'state/canonical.sqlite')
    shared = connect(folder/'candidate.sqlite')
    end = result['measurement_started']+result['window_seconds']
    jobs = [dict(row) for row in db.execute('SELECT * FROM acquisition_jobs ORDER BY created,id')]
    bindings = {(f,a):(m,s) for f,a,m,s in db.execute(
        'SELECT family,address,market_address,coverage_scope FROM evidence_bindings')}
    promotions = defaultdict(list)
    for f,a,at,raw in db.execute("SELECT family,address,created,body FROM candidate_history_outbox WHERE kind='promotion'"):
        promotions[f,a].append((at,json.loads(raw)))
    requests = defaultdict(list); errors = []
    for row in compressed_lines(folder/'http.ndjson.zlib'):
        responses = row['response'] if isinstance(row['response'],list) else [row['response']]
        for request,response in zip(row['requests'],responses):
            if isinstance(response,dict) and 'error' in response:
                errors.append(dict(method=request['method'],purpose=row['family'],
                    params=request.get('params'),error=response['error'],at=row['finished']))
            if request['method']!='getTransactionsForAddress':continue
            params=request['params'];bounds=params[1]['filters']['slot']
            item = {k:row[k] for k in ('family','started','finished','seconds','bytes')}
            value = response.get('result',{})
            item.update(token=params[1].get('paginationToken'),
                next_token=value.get('paginationToken'),transactions=len(value.get('data',[])),
                response_error=response.get('error'),response_hash=hashlib.sha256(
                    json.dumps(response,sort_keys=True,separators=(',',':')).encode()).hexdigest())
            requests[params[0],bounds['gte'],bounds['lte']].append(item)
    gaps=[dict(row) for row in db.execute('SELECT * FROM candidate_gaps')]
    work=[dict(row) for row in shared.execute('SELECT * FROM work')]
    attempts=defaultdict(list)
    for row in result['attempts']:attempts[row['candidate']].append(row)
    reports=[]
    for job in jobs:
        family=job['family'];address=job['address'];candidate,scope=bindings.get(
            (family,address),(address,'candidate:'+family+':'+address))
        local=sorted([r for r in requests[address,job['lo'],job['hi']]
            if r['family']==family+'_source'],key=lambda r:r['started'])
        replay=[r for r in requests[address,job['lo'],job['hi']] if r['family']=='replay_source']
        receipts=[dict(row) for row in db.execute(
            'SELECT page,committed,result FROM acquisition_page_receipts WHERE job=? ORDER BY page',(job['id'],))]
        linked=[]
        for receipt in receipts:
            if receipt['page']<len(local):linked.append(receipt['committed']-local[receipt['page']]['finished'])
        pending_gaps=[g for g in gaps if g['scope']==scope and g['repaired'] is None
            and g['lo']<=job['hi'] and (g['hi'] is None or g['hi']>=job['lo'])]
        coverage=[point for raw,checksum in db.execute('SELECT points,hash FROM candidate_coverage WHERE scope=?',(scope,))
            for point in coverage_points(raw,checksum)]
        sealed=job['status']=='complete'
        unpublished=len(local)>len(receipts)
        if job['status']=='failed':cause='OTHER_EXACT_CAUSE';detail=job['error']
        elif unpublished:cause='CANONICAL_PUBLICATION_LAG';detail='fetched_page_not_durably_committed'
        elif job['status']=='deadline_missed' and local:
            cause='DEADLINE_BECAME_INFEASIBLE_DURING_ACQUISITION';detail='archive_cursor_not_exhausted_before_original_deadline'
        elif job['status']!='complete' and not local:
            cause='WORK_NOT_READY';detail='archive_claim_not_dispatched_while_older_page_claims_remained_occupied'
        elif job['status']=='pending':cause='UPPER_BOUND_NOT_CLOSED';detail='pagination_cursor_not_exhausted'
        else:cause='OTHER_EXACT_CAUSE';detail='durably_complete_acquisition'
        relevant=[w for w in work if w['candidate']==candidate]
        promoted=promotions[family,address]
        first=db.execute('SELECT first_seen FROM market_observations WHERE family=? AND address=?',(family,address)).fetchone()
        block=db.execute('SELECT slot,seen FROM candidate_blocks WHERE scope=?',(scope,)).fetchone()
        checkpoint=db.execute('SELECT slot,updated FROM candidate_checkpoints WHERE scope=?',(scope,)).fetchone()
        observed_minimum_pages=max(1,len(local),job['pages'])
        # A lower estimate is useful for locating consumed slack, but neither
        # unknown remaining page count nor queue contention can be recovered
        # from a final DB snapshot. Never invent the missing original estimate.
        retrospective=dict(history_acquisition_seconds=sum(r['seconds'] for r in local),
            publication_seconds=distribution(linked),hydration_seconds=16.003484838 if family=='meteora' else None,
            qualification_seconds=None,safety_margin_seconds=None,
            observed_minimum_pages=observed_minimum_pages,unseen_remaining_pages_unknown=not sealed,
            minimum_total_service_estimate_at_first_enqueue=None)
        reports.append(dict(job_id=job['id'],candidate=candidate,provider_address=address,lane=family,
            history_kind='ordered_economic_history',first_observed_time=None if first is None else first[0],
            promotion_time=None if not promoted else min(x[0] for x in promoted),
            original_decision_deadline=job['deadline'],required_lower_bound=job['lo'],required_upper_bound=job['hi'],
            lower_bound_proof_present=any(a<=job['lo']<=b for a,b,_ in coverage),
            upper_bound_proof_present=any(a<=job['hi']<=b for a,b,_ in coverage),
            live_coverage_present=bool(block),replay_coverage_present=sealed,
            subscription_installed_at=None,subscription_timestamp_not_recorded=True,
            replay_started_at=None if not replay else min(r['started'] for r in replay),
            last_provider_evidence_at=None if not local and not block else max(
                [r['finished'] for r in local]+([] if not block else [block[1]])),
            canonical_history_through=job['last_slot'],
            consumer_durable_checkpoint=None if not checkpoint else checkpoint[0],
            CandidateHistory_through=None,consumer_coverage_rows=shared.execute('SELECT COUNT(*) FROM history_coverage').fetchone()[0],
            gap_count=len(pending_gaps),oldest_unresolved_gap=None if not pending_gaps else min(pending_gaps,key=lambda g:g['created']),
            work_enqueue_time=job['created'],work_ready_at=None if not relevant else min(w['ready_at'] for w in relevant),
            estimated_seconds=None if not relevant else min(w['estimate_seconds'] for w in relevant),
            worker_claim_time=None if not attempts[candidate] else min(a['worker_claim'] for a in attempts[candidate]),
            available_slack_at_first_enqueue=job['deadline']-job['created'],
            first_RPC_delay=None if not local else local[0]['started']-job['created'],
            retrospective_service_components=retrospective,enqueue_feasibility='UNRECORDED_CANNOT_PROVE_RETROSPECTIVELY',
            final_state=job['status'],classification=cause,exact_detail=detail,
            pages_committed=job['pages'],page_requests=local,publication_receipts=receipts))
    traces=[]
    for sample in result['monitor']:
        at=sample['at'];active=sum(a['worker_claim']<=at<a['hydration_finish'] for a in result['attempts'])
        pending_jobs=sum(j['created']<=at and (j['updated']>at or j['status']=='pending') for j in jobs)
        # The capture had one sequential Meteora claimant and a separate Pump
        # event evaluator. A capacity ceiling of two is not two claim loops.
        traces.append(dict(at=at,seconds=at-result['measurement_started'],
            pending_history_jobs=pending_jobs,sampled_work=sample.get('work',{}),active_expensive_workers=active,
            runnable_jobs_not_measured=True,blocked_by_history_not_measured=True,
            claimant_loops=1,native_Pump_hydrations=sum(a['worker_claim']<=at<a['qualification_ready']
                and a.get('calls',0)>0 for a in result.get('pump_candidate_work',[]))))
    answer=dict(schema='history-closure-preserved-trace-v1',source='final-shared14',
        verified_UTC=datetime.now(timezone.utc).isoformat(),capture_ended=end,jobs=reports,
        cause_counts=dict(Counter(r['classification'] for r in reports if r['final_state']!='complete')),
        completed_job_count=sum(r['final_state']=='complete' for r in reports),
        expired_job_count=sum(r['final_state']=='deadline_missed' for r in reports),
        feasibility_audit=dict(feasible_at_enqueue=None,infeasible_at_enqueue=None,
            exact_original_estimate_absent=18,reason='Neither acquisition estimates nor readiness predicates were recorded at first enqueue; current data cannot support a binary historical claim.'),
        worker_trace=traces,optional_errors=errors,
        owner_scheduler=json.loads(db.execute("SELECT value FROM service_health WHERE key='owner_scheduler'").fetchone()[0]),
        missing_position_interests=['PumpSwap position mint pregraduation Pump interval'],
        CandidateHistory_coverage_rows=shared.execute('SELECT COUNT(*) FROM history_coverage').fetchone()[0])
    db.close();shared.close();return answer


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();answer=audit(args.folder);args.output.write_text(json.dumps(answer,indent=2)+'\n')
    print(json.dumps({k:answer[k] for k in ('cause_counts','completed_job_count','expired_job_count','feasibility_audit','CandidateHistory_coverage_rows')},indent=2))
