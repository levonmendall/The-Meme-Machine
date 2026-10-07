"""Audit the pre-stop mixed census without treating unobserved work as zero."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from .analyze import compressed_lines,frames
from .certify import quantiles
from .final_mixed import position_disposition


def audit(folder):
    r=json.loads((folder/'result.json').read_text());close=r['running_close_at'];start=r['measurement_started']
    live=r.get('running_close') or {};release=live.get('startup',{}).get('consumers_released_at');release=release or r.get('steady_started')
    traffic={k:Counter() for k in ('startup','steady','shutdown')};methods={k:Counter() for k in traffic};rpc_rows=[]
    for row in compressed_lines(folder/'http.ndjson.zlib'):
        rpc_rows.append(row)
        phase='startup' if release is None or row['finished']<=release else 'steady' if row['finished']<=close else 'shutdown'
        t=traffic[phase];t['physical_requests']+=1;t['HTTP_bytes']+=row['bytes'];t['RPC_calls']+=row['calls'];t['RPC_CU']+=row['cu']
        t['transaction_body_calls']+=row['transaction_bodies'];t['scoped_transaction_bodies']+=row.get('scoped_archive_bodies',0)
        t['blocks']+=row['blocks'];methods[phase].update(row['methods'])
        if set(row['methods']) & {'getTransaction','getTransactionsForAddress','getBlock'}:t['history_RPC_calls']+=row['calls'];t['repair_HTTP_bytes']+=row['bytes']
    first_post=None
    for meta,raw in frames(folder/'provider.frames.zlib'):
        if meta['kind']!='delivery':continue
        phase='startup' if release is None or meta['seen']<=release else 'steady' if meta['seen']<=close else 'shutdown'
        t=traffic[phase];t[meta['transport']+'_bytes']+=len(raw);t['delivery_messages']+=1
        if meta.get('cross_shard_duplicate'):t['duplicate_delivery_bytes']+=len(raw)
        if phase=='steady' and meta.get('slot') and first_post is None:first_post=dict(slot=meta['slot'],at=meta['seen'],transport=meta['transport'])
    for t in traffic.values():t['provider_payload_bytes']=t['HTTP_bytes']+t['yellowstone_bytes']+t['websocket_bytes']
    positions={}
    for lane in ('pump','pumpswap','meteora'):
        rows=[p for p in r['positions'] if p['family']==lane and p['requested']<=close]
        dispositions=Counter(position_disposition(p) for p in rows)
        active=[v for k,v in r.get('running_position_pending',{}).items() if k==lane]
        positions[lane]=dict(requested=len(rows)+len(active),completed=dispositions['completed'],incomplete=dispositions['incomplete'],pending=active,
            failed=dispositions['failed'],bootstrap=dispositions['bootstrap_prerequisite'],
            incomplete_identities=[dict(candidate=r.get('pump_position_mint') if lane=='pump' else lane,
                requested=p['requested'],reason=p.get('reason') or p.get('dependencies',{}).get('reason'),slot=p.get('slot'))
                for p in rows if position_disposition(p) in ('failed','incomplete')],
            complete_evidence_latency=quantiles([p['seconds'] for p in rows if position_disposition(p)=='completed']),
            mark_latency=quantiles([p['seconds'] for p in rows if p.get('ready')]))
    repairs=[]
    for job in live.get('acquisitions',[]):
        matching=[q for q in rpc_rows if q['started']<=close and any(c['method']=='getTransactionsForAddress' and c.get('params',[None])[0]==job['address']
            and c['params'][1].get('filters',{}).get('slot')==dict(gte=job['lo'],lte=job['hi']) for c in q['requests'])]
        repairs.append(dict(id=job['id'],cause=job.get('repair_cause'),lane=job['family'],candidate=job['address'],
            required_interval=[job['lo'],job['hi']],requested_interval=[job['lo'],job['hi']],deadline=job['deadline'],
            enqueued=job['created'],slack_at_enqueue=job['deadline']-job['created'],status=job['status'],error=job.get('error'),
            requests=len(matching),RPC_calls=sum(q['calls'] for q in matching),CU=sum(q['cu'] for q in matching),
            bytes=sum(q['bytes'] for q in matching),methods=dict(Counter(m for q in matching for m in q['methods'])),
            scope_reason=job.get('repair_fields'),first_service=None if not matching else min(q['started'] for q in matching),
            feasibility='UNPROVEN' if job['status']!='complete' else 'COMPLETED'))
    path=(folder/'state/canonical.sqlite').resolve()
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        from meme_machine.solana_rolling_history import RollingHistory
        from meme_machine.solana_selective_history import coverage_scope
        rolling=RollingHistory.__new__(RollingHistory);rolling.db=db;rolling.history=SimpleNamespace(db=db,clock=lambda:close)
        phases=[dict(phase=p,at=t,details=json.loads(b)) for p,t,b in db.execute('SELECT phase,at,body FROM prewarm_startup_transitions ORDER BY sequence')]
        metrics=defaultdict(list)
        for f,a,at,b in db.execute('SELECT family,address,at,body FROM promotion_history_metrics'):
            if at<=close:metrics[f,a].append(dict(at=at,**json.loads(b)))
        obligations=[]
        for promo in live.get('promotions',[]):
            f,a=promo['family'],promo['address'];candidates=sorted(metrics[f,a],key=lambda m:m['at']);m=candidates[0] if candidates else None
            detail=dict(id=promo['id'],lane=f,candidate=a,promoted_at=promo['created'],category='D_INCOMPLETE_OR_CENSORED',history_proof=None)
            if m:
                binding=db.execute('SELECT coverage_scope FROM evidence_bindings WHERE family=? AND address=?',(f,a)).fetchone()
                scope=binding[0] if binding else coverage_scope(f,a)
                missing=rolling.missing(f,scope,m['lower_slot'],m['upper_slot'],as_of=promo['created'])
                jobs=[j for j in repairs if j['id'] in m['backfill_jobs']]
                detail.update(required_interval=[m['lower_slot'],m['upper_slot']],missing_at_promotion=missing,deadline=m['decision_deadline'],history_proof=m)
                if not missing and not jobs:detail['category']='A_ROLLING_COMPLETE_NO_BACKFILL'
                elif jobs and all(j['status']=='complete' for j in jobs):
                    detail['category']='C_GENUINE_LATE_DISCOVERY' if any(j['cause']=='LATE_DISCOVERY' for j in jobs) else 'B_TARGETED_SMALL_GAP'
            obligations.append(detail)
    work=live.get('candidate_work',[])
    pending=[dict(id=j['id'],candidate=j['candidate'],lane=j['lane'],status=j['status'],deadline=j['deadline'],ready_at=j['ready_at'],
        enqueue=j['created_at'],estimate=j['estimate_seconds']) for j in work if j['status'] in ('pending','active')]
    expired=[j for j in work if j['status']=='deadline_missed']
    candidate_rows=[*r.get('pump_candidate_work',[]),*r.get('promotions',[])]
    completed_vectors=[j for j in candidate_rows if 'qualification' in j and not j.get('error')]
    unknown_deadlines=[dict(id=j['id'],candidate=j['candidate'],lane=j['lane'],deadline=j['deadline'],enqueue=j['created_at'],
        slack_at_enqueue=j['deadline']-j['created_at'],service_estimate=j['estimate_seconds'],feasibility='UNPROVEN',reason='expired_without_complete_measured_obligation') for j in expired]
    censored=sum(p['category'].startswith('D_') for p in obligations)
    provider=r['monitor'][-1].get('provider',{}) if r.get('monitor') else {}
    faults=list(r['errors'])
    if any(p['incomplete'] or p['failed'] or p['pending'] for p in positions.values()):faults.append(dict(reason='position_prerequisites_incomplete'))
    if pending or unknown_deadlines or censored:faults.append(dict(reason='candidate_work_or_deadline_censored'))
    if not r['owner_observation']['normal_drain']['proven']:faults.append(dict(reason='normal_running_queue_drain_unproven'))
    if any(j['status']=='pending' for j in repairs):faults.append(dict(reason='history_acquisition_pending'))
    return dict(schema='model-b-final-mixed-audit-v1',source_commit=r['source_commit'],source_tree=r['source_tree'],
        classification='NEW_STARTUP_CERTIFIED' if not faults else 'NEW_STARTUP_MEASURED_DEFECT',
        consumer_release=release,start=start,measurement_close=close,steady_seconds=None if release is None else close-release,
        phases=phases,first_post_release_source_event=first_post,traffic={k:dict(v) for k,v in traffic.items()},RPC_methods={k:dict(v) for k,v in methods.items()},
        ordinary_startup_cold_reconstruction_calls=traffic['startup']['history_RPC_calls'],
        candidate_evidence=dict(requested=len(work),completed=sum(j['status']=='complete' for j in work),pending=len(pending),
            expired=len(expired),complete_qualification_vectors=len(completed_vectors),vectors_by_lane=dict(Counter(j['lane'] for j in completed_vectors))),
        promotions=dict(denominator=len(obligations),categories=dict(Counter(p['category'] for p in obligations)),obligations=obligations),
        position_evidence=positions,repairs=repairs,repair_causes=dict(Counter(j['cause'] for j in repairs)),
        feasible_deadline_misses='UNPROVEN' if unknown_deadlines or pending or censored else 0,deadline_audit=unknown_deadlines,
        unexplained_pending_work=pending,pending_acquisitions=[j for j in repairs if j['status']=='pending'],
        rolling_waits={k:live.get(k,[]) for k in ('publication_waits','boundary_waits')},required_gaps=live.get('required_gaps'),
        owner_queue=r['owner_observation'],provider=provider,provider_latency=quantiles(q['seconds'] for q in rpc_rows if q['finished']<=close),
        resources=dict(wall_seconds=close-start,CPU_seconds=r['cpu_seconds'],peak_RSS_KiB=r['rss_peak_kib'],canonical_DB_bytes=live.get('hot_db_bytes'),
            WAL_before_stop_bytes=live.get('wal_bytes'),peak_WAL_bytes=max((s.get('wal_bytes',0) for s in [*r.get('startup_samples',[]),*r.get('monitor',[])]),default=0),
            SQLite_changes=live.get('sqlite_changes')),faults=faults,monthly_Alchemy_cost='NOT_CERTIFIED')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);args=parser.parse_args()
    result=audit(args.folder);(args.folder/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('classification','steady_seconds','candidate_evidence','repair_causes','feasible_deadline_misses')}))
