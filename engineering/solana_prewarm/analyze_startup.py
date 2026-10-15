"""Separate actual Model B boot from the subsequent mixed window.

This is an evidence audit, not a monthly extrapolator or readiness authority.
Shutdown deliberately opens replay gaps; those are separate from the last
running observation. An incomplete native disposition is never counted zero.
"""
import argparse,json,sqlite3
from collections import Counter
from pathlib import Path
from engineering.solana_capacity.analyze import compressed_lines,frames,distribution


def audit(folder):
    result=json.loads((folder/'result.json').read_text())
    canonical=folder/'state/canonical.sqlite'
    with sqlite3.connect(canonical.resolve().as_uri()+'?mode=ro',uri=True) as db:
        row=db.execute("SELECT MIN(at) FROM prewarm_startup_transitions WHERE phase='RELEASE_CANDIDATE_CONSUMERS'").fetchone()
    release=row[0];start=result['measurement_started']
    end=start+result['window_seconds'];cutoff=end if release is None else release
    traffic={phase:Counter() for phase in ('startup','steady')}
    for row in compressed_lines(folder/'http.ndjson.zlib'):
        phase='startup' if row['finished']<=cutoff else 'steady';t=traffic[phase]
        t['HTTP_response_samples']+=1
        t['HTTP_bytes']+=row['bytes'];t['RPC_calls']+=row['calls'];t['RPC_CU']+=row['cu']
        t['selective_transaction_bodies']+=row['transaction_bodies']
        t['scoped_archive_transaction_bodies']+=row.get('scoped_archive_bodies',0)
        t['blocks']+=row['blocks']
        if any(m in ('getTransaction','getTransactionsForAddress','getBlock') for m in row['methods']):
            t['history_or_missing_field_RPC_calls']+=row['calls'];t['recovery_HTTP_bytes']+=row['bytes']
    for meta,raw in frames(folder/'provider.frames.zlib'):
        if meta['kind']!='delivery':continue
        phase='startup' if meta['seen']<=cutoff else 'steady';t=traffic[phase]
        t[meta['transport']+'_delivery_samples']+=1
        t[meta['transport']+'_bytes']+=len(raw)
        t['cross_shard_duplicate_bytes']+=len(raw) if meta.get('cross_shard_duplicate') else 0
    for phase,t in traffic.items():
        t['raw_provider_payload_bytes']=t['HTTP_bytes']+t['yellowstone_bytes']+t['websocket_bytes']
    with sqlite3.connect(canonical.resolve().as_uri()+'?mode=ro',uri=True) as db:
        phases=[dict(session=s,phase=p,at=at,details=json.loads(b)) for s,p,at,b in db.execute(
            'SELECT session,phase,at,body FROM prewarm_startup_transitions ORDER BY sequence')]
        startup=json.loads(db.execute('SELECT body FROM prewarm_startup').fetchone()[0])
        reasons=dict(db.execute('SELECT reason,COUNT(*) FROM backfill_reasons GROUP BY reason'))
        jobs=dict(db.execute('SELECT status,COUNT(*) FROM acquisition_jobs GROUP BY status'))
        boundary_waits=dict(db.execute('SELECT status,COUNT(*) FROM rolling_boundary_waits GROUP BY status'))
        metrics=[dict(family=f,address=a,at=t,**json.loads(b)) for f,a,t,b in db.execute(
            'SELECT family,address,at,body FROM promotion_history_metrics ORDER BY at')]
        owner_row=db.execute("SELECT value FROM service_health WHERE key='owner_scheduler'").fetchone()
        owner={} if owner_row is None else json.loads(owner_row[0])
        cold=db.execute('SELECT COALESCE(SUM(cold_bytes),0) FROM scoped_cold_manifests').fetchone()[0]
        normalized=db.execute('SELECT COUNT(*),COALESCE(SUM(LENGTH(body)),0) FROM rolling_economic_events').fetchone()
        outbox=db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0]
        refs={}
    with sqlite3.connect((folder/'candidate.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
        refs=dict(db.execute('SELECT kind,COUNT(*) FROM canonical_event_refs GROUP BY kind'))
        work=dict(db.execute('SELECT status,COUNT(*) FROM work GROUP BY status'))
    monitors=result['monitor'];running_gaps=monitors[-1]['gaps'] if monitors else None
    intervals={p['phase']:p['at']-start for p in phases if p['phase']!='FAIL_CLOSED'}
    counts=Counter(result['transport'].get('control',{}));requested=counts['membership_requested']
    complete=sum(bool(m['history_already_complete_at_promotion']) for m in metrics)
    missing=[m for m in metrics if not m['history_already_complete_at_promotion']]
    seconds=max(0,end-cutoff)
    return dict(schema='model-b-startup-audit-v1',classification='MEASURED_LIVE',
        source_sha256=result['source_sha256'],endpoint_identity=result['endpoint_identity'],
        process_measurement_seconds=end-start,consumer_released=release is not None,
        startup_seconds=cutoff-start,steady_observed_seconds=seconds,
        planned_post_release_arrival_seconds=result['planned_seconds'],
        phase_transitions=phases,stage_seconds_from_process_start=intervals,
        feeds_connected_seconds=None if startup.get('feeds_connected_at') is None else startup['feeds_connected_at']-start,
        first_rolling_event_seconds=None if startup.get('first_rolling_event_at') is None else startup['first_rolling_event_at']-start,
        traffic={k:dict(v) for k,v in traffic.items()},
        steady_hour_normalization={k:(v*3600/seconds if seconds else None) for k,v in traffic['steady'].items()},
        normalization_note='Bounded startup-stock/position-equivalent mix, not production incidence or a monthly estimate.',
        ordinary_startup_cold_reconstruction_calls=traffic['startup']['history_or_missing_field_RPC_calls'],
        startup_transaction_bodies=traffic['startup']['selective_transaction_bodies']+traffic['startup']['scoped_archive_transaction_bodies'],
        control=dict(counts),membership_suppression_percent=100*counts['membership_suppressed']/requested if requested else None,
        owner_scheduler=owner,producer_wait_seconds=distribution(v['seconds'] for v in result['transport'].get('producer_waits',[])),
        canonical_owner_queue_peak=owner.get('queue_peak'),commands_completed=sum(v for k,v in owner.items() if k.endswith('.completed')),
        queue_depth_at_last_telemetry=owner.get('queued'),queue_normal_drain_proven=False,
        acquisition_jobs=jobs,backfill_reasons=reasons,boundary_waits=boundary_waits,
        history_preparation_observations=len(metrics),history_complete_preparation_observations=complete,
        history_complete_preparation_percent=100*complete/len(metrics) if metrics else None,
        history_preparation_note='Preparations can repeat across exact requested intervals; not all promotions have a completed disposition.',
        preparation_metrics=metrics,canonical_event_reference_counts=refs,work_states=work,
        last_running_required_and_unrequired_gap_count=running_gaps,
        shutdown_outbox_pending=outbox,normalized_records=normalized[0],normalized_hot_logical_bytes=normalized[1],
        canonical_DB_bytes=canonical.stat().st_size,candidate_DB_bytes=(folder/'candidate.sqlite').stat().st_size,cold_archive_bytes=cold,
        SQLite_changes_observed=max((m.get('sqlite_changes',0) for m in [*result.get('startup_samples',[]),*monitors]),default=0),
        WAL_peak_bytes_observed=max((m.get('wal_bytes',0) for m in [*result.get('startup_samples',[]),*monitors]),default=0),
        CPU_seconds=result['cpu_seconds'],CPU_percent_of_one_core=result['cpu_seconds']*100/(end-start),
        RSS_peak_KiB=result['rss_peak_kib'],errors=result['errors'],latency=result['latency'],
        measurement_limits=['Application payload bytes, not Ethernet/TLS framing.',
            'CPU is parent-process CPU, consistent with the preserved baseline; decoder child CPU was not sampled.',
            'SQLite changes/WAL extents are local observations, not complete physical disk-write accounting.',
            'Shutdown gaps do not establish normal-drain completeness.',
            'No production monthly cost is certified by this audit.'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.write_text(json.dumps(audit(args.folder),indent=2)+'\n')
