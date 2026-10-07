"""Audit a completed shared-provider capture without extrapolating startup stock.

Run after the disposable owner has stopped. Raw provider payloads, HTTP CU,
consumer durability, retained stock, active arrivals and decision readiness are
distinct measurements. This script never grants production readiness.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics
import struct
import zlib
from .certify import CU

LANES = ('pump', 'pumpswap', 'meteora')


def distribution(values):
    values = sorted(v for v in values if isinstance(v, (int, float)))
    if not values:
        return dict(N=0, mean=None, p50=None, p95=None, p99=None, max=None)
    return dict(N=len(values), mean=statistics.fmean(values),
                **{name: values[min(len(values)-1, math.floor((len(values)-1)*p))]
                   for name, p in (('p50', .5), ('p95', .95), ('p99', .99))}, max=values[-1])


def compressed_lines(path):
    decoder = zlib.decompressobj()
    pending = b''
    with path.open('rb') as source:
        while chunk := source.read(65536):
            pending += decoder.decompress(chunk)
            lines = pending.split(b'\n'); pending = lines.pop()
            for line in lines:
                if line: yield json.loads(line)
    pending += decoder.flush()
    for line in pending.splitlines():
        if line: yield json.loads(line)


def frames(path):
    decoder = zlib.decompressobj(); pending = b''
    with path.open('rb') as source:
        while chunk := source.read(65536):
            pending += decoder.decompress(chunk)
            while len(pending) >= 8:
                header, raw = struct.unpack('!II', pending[:8]); end = 8+header+raw
                if len(pending) < end: break
                yield json.loads(pending[8:8+header]), pending[8+header:end]
                pending = pending[end:]
    pending += decoder.flush()
    if pending: raise ValueError('provider_frame_archive_incomplete')


def readonly(path):
    return sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True)


def peak_per_bucket(times, seconds=1):
    return max(Counter(math.floor(t/seconds) for t in times).values(), default=0)


def measure(folder):
    result = json.loads((folder/'result.json').read_text())
    start = result['measurement_started']; end = start+result['window_seconds']
    duration = result['window_seconds']; canonical_path = folder/'state/canonical.sqlite'
    with readonly(canonical_path) as db:
        scopes = [dict(family=f, address=a, first_seen=t, fields=json.loads(v))
                  for f, a, t, v in db.execute('SELECT family,address,first_seen,fields FROM market_observations')]
        outbox = [dict(id=i, family=f, address=a, kind=k, body=json.loads(b), hash=h, created=t, consumed=c)
                  for i, f, a, k, b, h, t, c in db.execute(
                      'SELECT id,family,address,kind,body,hash,created,consumed FROM candidate_history_outbox')]
        bindings = {(f, a): m for f, a, m in db.execute('SELECT family,address,market_address FROM evidence_bindings')}
        acquisitions = [dict(zip(('id','family','address','lo','hi','priority','deadline','status','pages','created','updated','error'), r))
                        for r in db.execute('SELECT id,family,address,lo,hi,priority,deadline,status,pages,created,updated,error FROM acquisition_jobs')]
        observations = [dict(job=j, kind=k, at=t, body=json.loads(b)) for j, k, t, b in db.execute(
            'SELECT job,kind,at,body FROM acquisition_observations')]
        pending_gaps = [dict(scope=s, lo=lo, hi=hi, created=t, reason=r) for s, lo, hi, t, r in db.execute(
            'SELECT scope,lo,hi,created,reason FROM candidate_gaps WHERE repaired IS NULL')]
        checkpoints = [dict(scope=s, slot=t, receipt=r, updated=u) for s,t,r,u in db.execute('SELECT * FROM candidate_checkpoints')]
        delivery = [dict(family=f, transport=t, provider_bytes=b, materialized_bytes=m, canonical_bytes=c,
                         ipc_bytes=i, cu=u, calls=n) for f,t,b,m,c,i,u,n in db.execute(
            'SELECT family,transport,SUM(raw_bytes),SUM(retained_bytes),SUM(canonical_bytes),SUM(ipc_bytes),SUM(rpc_cu),SUM(calls) FROM provider_delivery GROUP BY family,transport')]
        table_counts = {t: db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in
                        ('candidate_content_receipts','candidate_pending_proofs','candidate_outbox','records','shared_history_cache')}
    with readonly(folder/'candidate.sqlite') as db:
        work = [dict(id=i, lane=l, candidate=c, status=s, created=t, deadline=d, estimate=e)
                for i,l,c,s,t,d,e in db.execute('SELECT id,lane,candidate,status,created_at,deadline,estimate_seconds FROM work')]
        source_receipts = {i: json.loads(b) for i,b in db.execute('SELECT id,body FROM source_receipts')}
        event_counts = dict(db.execute('SELECT kind,COUNT(*) FROM events GROUP BY kind'))
    missing_receipts = [r['id'] for r in outbox if r['consumed'] is not None and r['id'] not in source_receipts]
    changed_receipts = [r['id'] for r in outbox if r['consumed'] is not None and r['id'] in source_receipts
                        and source_receipts[r['id']]['source_hash'] != r['body'].get('source_hash', r['hash'])]
    # Keep raw authenticated payloads in the archive, not a second multi-GB
    # in-memory copy when auditing a full bounded capture.
    http = []
    rpc_errors = Counter()
    for row in compressed_lines(folder/'http.ndjson.zlib'):
        row['captured_CU']=row['cu']
        row['cu']=sum(CU[method] for method in row['methods'])
        payload = row.get('response')
        for response in payload if isinstance(payload, list) else [payload]:
            if isinstance(response, dict) and isinstance(response.get('error'), dict):
                rpc_errors[str(response['error'].get('code', 'unknown'))] += 1
        http.append({k:v for k,v in row.items() if k not in ('requests','response')})
    rpc_families = {}
    for family in sorted({r['family'] for r in http}):
        rows = [r for r in http if r['family']==family]
        rpc_families[family] = dict(N=len(rows),calls=sum(r['calls'] for r in rows),cu=sum(r['cu'] for r in rows),
            http_bytes=sum(r['bytes'] for r in rows),transaction_bodies=sum(r.get('transaction_bodies',0) for r in rows),
            scoped_archive_bodies=sum(r.get('scoped_archive_bodies',0) for r in rows),blocks=sum(r.get('blocks',0) for r in rows),
            duration=distribution(r['seconds'] for r in rows),requests_per_second_peak=peak_per_bucket([r['started'] for r in rows]))
    promoted = [r for r in outbox if r['kind']=='promotion']
    terminal = {r['id']:r for r in result['promotions']}
    attempts = defaultdict(list)
    for row in result.get('attempts', []): attempts[row['id']].append(row)
    native_pump = result.get('pump_candidate_work', [])
    lanes = {}
    promotion_audit = []
    for family in LANES:
        discovered = [r for r in scopes if r['family']==family]
        stock = {r['address'] for r in outbox if r['family']==family and r['kind']=='scout'
                 and not r['body'].get('signature') and r['body'].get('fields',{}).get('source')=='paginated_structural_census'}
        active = {r['address'] for r in outbox if r['family']==family and r['kind']=='activity'}
        promos = [r for r in promoted if r['family']==family]
        classifications = Counter(); hydration_units = []; full_required = 0; unknown = 0
        for promo in promos:
            candidate = bindings.get((family,promo['address']),promo['address'])
            work_id = 'provider:'+promo['id']
            if family=='meteora':
                samples = attempts.get(work_id,[]); final = terminal.get(work_id)
            else:
                # Current evaluates native event prospects, not structural scout
                # ranks. Preserve the exact mapping; do not relabel all event
                # evaluations as promotions when no native event was ready.
                samples = [r for r in native_pump if r['candidate']==candidate and r['lane']==family
                           and promo['created']<=r['worker_claim']<=promo['body']['decision_deadline']]
                final = samples[-1] if samples else None
            needed = any(r.get('full_hydration_required') or r.get('full_hydration') for r in samples)
            calls = sum(r.get('calls',0) for r in samples); cu = sum(r.get('cu',0) for r in samples)
            byte_count = sum(r.get('bytes',0) for r in samples)
            observed_kind='OTHER_EXPLICIT_CLASS' if final is None else final['hydration_class']
            reason=None if final is None else final.get('reason',final.get('alignment',{}).get('reason'))
            incomplete_trigger=(family=='meteora' and reason=='fresh_swap_trigger_timeout' and
                any(g['scope']=='candidate:meteora:'+candidate for g in pending_gaps))
            censored=(final is None or observed_kind!='INCOMPATIBLE_STRUCTURAL' and
                (bool(final.get('error')) or observed_kind=='OTHER_EXPLICIT_CLASS' or incomplete_trigger))
            kind='OTHER_EXPLICIT_CLASS' if censored else observed_kind
            unknown+=int(censored)
            classifications[kind]+=1; full_required+=int(needed)
            unit = dict(calls=calls,cu=cu,http_bytes=byte_count,bodies=sum(r.get('bodies',0) for r in samples),
                        blocks=sum(r.get('blocks',0) for r in samples),
                        active_hydration_seconds=sum(r['seconds'] for r in samples if r.get('calls',0)))
            if calls: hydration_units.append(unit)
            finish = None if final is None else final.get('qualification_ready')
            audit = dict(id=work_id, family=family, candidate=candidate, provider_address=promo['address'],
                first_observed=promo['body']['first_seen'], original_decision_deadline=promo['body']['decision_deadline'],
                queue_entry=promo['created'], worker_claim=None if not samples else samples[0]['worker_claim'],
                hydration_start=None if not samples else samples[0].get('hydration_start'),
                hydration_finish=None if not samples else samples[-1].get('hydration_finish',samples[-1].get('qualification_ready')),
                disposition_ready=finish, qualification_vector_ready=finish if final and 'qualification' in final else None,
                remaining_deadline_margin=None if finish is None else promo['body']['decision_deadline']-finish,
                classification=kind, observed_hydration_class=observed_kind,
                disposition_censored=censored,trigger_continuity_unproved=incomplete_trigger,
                full_hydration_required=None if censored else needed, attempts=len(samples), units=unit,
                result=None if final is None else final.get('reason',final.get('alignment',{}).get('reason','native_disposition')))
            promotion_audit.append(audit)
        denominator = len(active)
        lanes[family] = dict(window_seconds=duration, candidate_stock=len(discovered),startup_census_stock=len(stock),
            active_scopes=denominator, reactivations=sum(r['family']==family and r['kind']=='reactivated' for r in outbox),
            promotion_events=len(promos), promotion_unique_scopes=len({r['address'] for r in promos}),
            promotion_percent_of_active_scopes=None if not denominator else 100*len({r['address'] for r in promos})/denominator,
            classification_counts=dict(classifications),full_hydrations_required=full_required,
            full_hydration_incidence_percent=None if not promos else 100*full_required/len(promos),
            full_hydration_incidence_bounds_percent=None if not promos else
                [100*full_required/len(promos),100*(full_required+unknown)/len(promos)],
            unobserved_native_dispositions=unknown,
            hydration_units={k:distribution(u[k] for u in hydration_units) for k in ('calls','cu','http_bytes','bodies','blocks','active_hydration_seconds')},
            event_prospect_evaluations=sum(r['lane']==family for r in native_pump),
            sampled_hydration_operations=sum(r['lane']==family and r.get('calls',0)>0 for r in native_pump) if family!='meteora' else len(hydration_units),
            normalized_active_scopes_per_day=denominator*86400/duration,
            normalized_promotions_per_day=len(promos)*86400/duration,
            max_promotions_per_second=peak_per_bucket([r['created'] for r in promos]),
            production_rate_certified=False,
            note='Startup census is retained stock, not daily births. Normalization describes this bounded window only. Full-hydration count is an observed lower bound; censored dispositions are not zero.')
    positions={}
    for family in LANES:
        rows=[r for r in result['positions'] if r['family']==family]; ready=[r for r in rows if r['ready']]
        first_ready=min((r['requested'] for r in ready),default=end)
        misses=[r for r in rows if not r['ready'] and r['requested']>first_ready]
        dependent=[r for r in ready if not r.get('dependencies',{}).get('ordered_history_ready')]
        meter=rpc_families.get(family+'_position',dict(http_bytes=0,cu=0,calls=0))
        positions[family]=dict(samples=len(rows),mark_ready=len(ready),bootstrap_failures=len(rows)-len(ready)-len(misses),
            observation_failures_after_first_ready=len(misses),history_dependency_unready=len(dependent),
            history_dependency_reasons=dict(Counter(r['dependencies'].get('reason','') for r in dependent)),
            evidence_read_latency=distribution(r['seconds'] for r in ready),
            request_schedule_lateness=distribution(r.get('schedule_lateness_seconds',0) for r in rows),
            measured_HTTP_bytes_per_position_hour=meter['http_bytes']*3600/duration,
            measured_RPC_CU_per_position_hour=meter['cu']*3600/duration,
            measured_RPC_calls_per_position_hour=meter['calls']*3600/duration,
            classification='MEASURED_LIVE',traffic_label='MEASURED_LIVE_POSITION_TRAFFIC',
            occupancy='One nonmonetary equivalent active throughout this bounded run.')
    transport=result['transport']; raw_native=sum(r['bytes'] for r in transport['delivery'] if r['transport']=='yellowstone')
    raw_ws=sum(r['bytes'] for r in transport['delivery'] if r['transport']=='websocket')
    duplicates=sum(r['duplicate_bytes'] for r in transport['delivery'])
    raw_http=sum(r['bytes'] for r in http); cu=sum(r['cu'] for r in http)
    total=raw_native+raw_ws+raw_http
    byte_buckets=Counter();cu_buckets=Counter();call_buckets=Counter()
    for row in http:
        bucket=math.floor(row['finished']);byte_buckets[bucket]+=row['bytes']
        cu_buckets[bucket]+=row['cu'];call_buckets[bucket]+=row['calls']
    for metadata,raw in frames(folder/'provider.frames.zlib'):
        if metadata['kind']=='delivery':byte_buckets[math.floor(metadata['seen'])]+=len(raw)
    diagnostic=cu*.525/1e6+raw_native*75/1e12+raw_ws*.0002*.525/1e6
    monitors=result['monitor']; warming_max=max((m.get('warming',[0])[0] for m in monitors),default=0)
    oldest_pending=max((m['at']-m['warming'][1] for m in monitors if m.get('warming',[0,None])[1] is not None),default=0)
    minimum_slack=min((m['warming'][2]-m['at'] for m in monitors if m.get('warming',[0,None,None])[2] is not None),default=None)
    gov_queues=[q for m in monitors for q in m['provider']['queues']]
    max_governor_depth=max((sum(q['depth'] for q in m['provider']['queues']) for m in monitors),default=0)
    with readonly(folder/'governor.sqlite') as db:
        grants=[dict(priority=p,requested=r,ended=e,wait=w,granted=g,reason=s) for p,r,e,w,g,s in db.execute(
            'SELECT priority,requested,ended,wait,granted,reason FROM grants')]
    contested=[]
    for g in grants:
        if g['priority']==0 and g['granted'] and any(o['priority']>0 and o['requested']<g['ended']<o['ended'] for o in grants):
            contested.append(g['wait'])
    deadline_misses=[r for r in acquisitions if r['status']=='deadline_missed']
    candidate_deadline_misses=[r for r in work if r['status']=='deadline_missed']
    retries=dict(Counter(r['kind'] for r in observations if r['kind'] in
                        ('control_reconnect','scout_reconnect','subscription_retry','archive_decoder_unavailable','join_failure','rpc_retry')))
    with readonly(canonical_path) as db:
        retirement = [dict(at=t, **json.loads(b)) for t,b in db.execute(
            'SELECT at,body FROM scoped_retirement_observations')]
        local_bytes = dict(materialized_body_bytes=db.execute(
            'SELECT COALESCE(SUM(LENGTH(body)),0) FROM canonical_evidence').fetchone()[0],
            candidate_history_file_bytes=(folder/'candidate.sqlite').stat().st_size,
            canonical_database_file_bytes=canonical_path.stat().st_size)
    completeness=dict(consumed_outbox_without_external_receipt=len(missing_receipts),changed_external_receipts=len(changed_receipts),
        pending_outbox=sum(r['consumed'] is None for r in outbox),pending_gaps=len(pending_gaps),
        pending_acquisition=sum(r['status']=='pending' for r in acquisitions),
        failed_acquisition=sum(r['status']=='failed' for r in acquisitions),
        history_job_deadline_misses=len(deadline_misses),candidate_work_deadline_misses=len(candidate_deadline_misses),
        feasible_miss_classification='Do not label all expired history jobs feasible: individual full-history service requirements are not known at enqueue.',
        missing_receipt_ids=missing_receipts,changed_receipt_ids=changed_receipts)
    proof_gaps=[]
    if result['errors']:proof_gaps.append('shared_source_terminated')
    if deadline_misses:proof_gaps.append('required_history_deadlines_expired')
    if candidate_deadline_misses:proof_gaps.append('candidate_deadlines_expired')
    if any(p['history_dependency_unready'] for p in positions.values()):proof_gaps.append('position_continuation_history_not_ready')
    if any(p['observation_failures_after_first_ready'] for p in positions.values()):proof_gaps.append('active_position_evidence_read_failed')
    if any(l['unobserved_native_dispositions'] for l in lanes.values()):proof_gaps.append('promotion_native_disposition_incomplete')
    if not any(r.get('full_hydration') and 'qualification' in r for r in result['promotions']):
        proof_gaps.append('full_meteora_warming_and_qualification_not_observed_under_contention')
    latency={}
    for family,prefix in (('pump','Pump'),('pumpswap','PumpSwap/Survivor'),('meteora','Meteora')):
        promos=[r for r in promoted if r['family']==family]
        latency[prefix+' promotion']=distribution(r['created']-r['body']['observed_at'] for r in promos)
        actual=[r for r in (result['promotions'] if family=='meteora' else native_pump)
                if r.get('lane')==family and 'qualification' in r and r.get('qualification_ready') is not None]
        latency[prefix+' qualification-ready']=distribution(r['qualification_ready']-r.get('evidence_available',r['first_observed']) for r in actual)
        units=[r for r in promotion_audit if r['family']==family and r['hydration_start'] is not None and r['hydration_finish'] is not None]
        latency[prefix+' hydration/disposition including trigger wait']=distribution(r['hydration_finish']-r['hydration_start'] for r in units)
        latency[prefix+' position mark']=positions[family]['evidence_read_latency']
    latency['Pump candidate event to native evaluation']=distribution(r['worker_claim']-r['evidence_available'] for r in native_pump if r.get('lane')=='pump' and 'evidence_available' in r)
    latency['Meteora scout/provider delivery']=result['provider_delivery_latency'].get('discovery_delivery',distribution([]))
    latency['Pump HWM/exit/safety']=positions['pump']['evidence_read_latency']
    latency['Meteora safety/confirmation']=positions['meteora']['evidence_read_latency']
    replay_events=[r for r in observations if r['kind'] in ('control_reconnect','scout_reconnect','subscription_retry')]
    return dict(schema='shared-provider-capacity-audit-v1',started_UTC=result['started_UTC'],window_seconds=duration,
        tested_source_sha256=result['source_sha256'],endpoint_identity=result['endpoint_identity'],
        source_errors=result['errors'],production_capacity_certified=False,remaining_blocker='SIMULTANEOUS_PROVIDER_CAPACITY',
        certification_proof_gaps=proof_gaps,lanes=lanes,promotion_audit=promotion_audit,positions=positions,
        latency_seconds=latency,latency_limitations='Qualification rows require an actual native qualification vector. Negative compatibility/quiet-trigger dispositions are separate. Mark/HWM/exit/safety rows share the same position tick, not independent samples. Scout delivery combines program account scouts. No chain execution latency is measured.',
        replay_incidence=dict(observed_rebuild_or_reconnect_events=len(replay_events),window_hours=duration/3600,
            normalization_per_day=len(replay_events)*86400/duration,classification='DERIVED',
            natural_control_reconnects=sum(r['kind']=='control_reconnect' for r in replay_events),
            note='Scout reconnects and scoped subscription rebuilds are distinct from a whole-provider recovery. Do not apply one replay unit indiscriminately.'),
        traffic=dict(HTTP_response_bytes=raw_http,Yellowstone_delivered_bytes=raw_native,WebSocket_delivered_bytes=raw_ws,
            raw_provider_payload_bytes=total,RPC_CU=cu,RPC_calls=sum(r['calls'] for r in http),
            captured_RPC_CU=sum(r['captured_CU'] for r in http),
            RPC_CU_classification='DERIVED: measured method counts multiplied by verified current official method prices',
            HTTP_JSON_RPC_errors=dict(rpc_errors),transport_and_RPC_error_meter=result['rpc'].get('errors',{}),
            provider_payload_bytes_per_second=total/duration,RPC_CU_per_second=cu/duration,
            RPC_calls_per_second=sum(r['calls'] for r in http)/duration,
            completed_payload_bytes_one_second_peak=max(byte_buckets.values(),default=0),
            completed_RPC_calls_one_second_peak=max(call_buckets.values(),default=0),
            completed_RPC_CU_one_second_peak=max(cu_buckets.values(),default=0),
            framing_and_NIC_bytes='Not measured; reported provider delivery counts are raw application payloads. Five percent is an allowance, not a verified wire-overhead bound.',
            cross_shard_duplicate_provider_bytes=duplicates,
            duplicate_overhead_percent=None if raw_native==duplicates else 100*duplicates/(raw_native-duplicates),
            diagnostic_estimated_USD=diagnostic,diagnostic_network_framing_bound_USD=diagnostic*1.05,
            measured_payload_daily_normalization=total*86400/duration,
            measured_RPC_CU_daily_normalization=cu*86400/duration,
            production_expected=False,provider_delivery_ledger=delivery,HTTP_families=rpc_families),
        governor=dict(sampled_queue_depth_max=max_governor_depth,retained_grant_records=len(grants),
            failed_grants=dict(Counter(g['reason'] for g in grants if not g['granted'])),
            position_grant_latency=distribution(g['wait'] for g in grants if g['priority']==0),
            position_grants_with_lower_priority_work_waiting=distribution(contested),
            oldest_pending_warming_seconds=oldest_pending,minimum_pending_deadline_slack=minimum_slack,
            warming_backlog_max=warming_max,queue_samples=gov_queues),
        subscriptions=dict(peak_native_streams=transport['peak_native_streams'],
            filter_counts=[r['filters'] for r in transport['subscriptions'] if r['kind']=='subscribe'],
            addresses_per_subscription=[len(r['addresses']) for r in transport['subscriptions'] if r['kind']=='subscribe'],
            subscriptions_total=len(transport['subscriptions']),recovery_observations=retries),
        process=dict(CPU_seconds=result['cpu_seconds'],CPU_percent_of_one_core=100*result['cpu_seconds']/duration,
            RSS_peak_KiB=result['rss_peak_kib']),durability=completeness,event_counts=event_counts,
        history_jobs=acquisitions,deadline_misses=deadline_misses,candidate_deadline_misses=candidate_deadline_misses,
        pending_gaps=pending_gaps,checkpoints=checkpoints,compact_and_hot_counts=table_counts,
        local_storage_bytes=local_bytes,scoped_retirement_observations=retirement,
        note='This audit rejects incomplete proof; it does not infer production feasibility or central tendency from an aborted or censored window.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.write_text(json.dumps(measure(args.folder),indent=2)+'\n')
