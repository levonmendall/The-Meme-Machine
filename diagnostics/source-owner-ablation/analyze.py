"""Analyze captured evidence only. No workloads, repair, or qualification."""
import argparse,hashlib,json,os,statistics
from collections import Counter
from pathlib import Path
def read(path):return json.loads(path.read_text())
def write(path,row):path.write_text(json.dumps(row,indent=2)+'\n')
def metric(row,key):return row.get('metrics',{}).get(key,{}).get('wall',0.)
def point(row):
    return dict(elapsed=row['elapsed'],frames=row['frames'],source_seconds=row['source_seconds'],
        source_lag=row['source_lag'],pins=row['pins'],gaps=row['gaps'],
        arrival_inference_valid=row['arrival_inference_valid'],
        scopes=row['scopes'],scheduling=row.get('scheduling'),owner=row.get('owner'),
        owner_observation_at=(row.get('owner_observation') or {}).get('monotonic'))
def stats(values):
    if not values:return dict(count=0,total=None,mean=None,median=None,peak=None)
    return dict(count=len(values),total=sum(values),mean=statistics.mean(values),
        median=statistics.median(values),peak=max(values))
def archive_cycles(cycles):
    rows=[];missing=[]
    for c in cycles:
        stages=c.get('commit_stages',[])
        required=('child_start','native_end','child_end','parent_callback_enter','mapped_ready_mark',
            'receipt_consumed_at','successor_submit_begin')
        if not stages or any(k not in c for k in required):
            missing.append(dict(sequence=c['sequence'],available_keys=sorted(c),commit_stages=len(stages)))
            continue
        first,last=stages[0],stages[-1]
        parts=dict(dispatch=c['child_start']-c['submit_begin'],
            preparation_native=c['native_end']-c['child_start'],
            archive_floor_wait_actual=c['child_end']-c['native_end'],
            return_transport=c['parent_callback_enter']-c['child_end'],
            callback_to_ready_mark=c['mapped_ready_mark']-c['parent_callback_enter'],
            ready_receipt_to_first_commit=first['start']-c['mapped_ready_mark'],
            commit_slice_service=sum(s['end']-s['start'] for s in stages),
            inter_slice_gaps=sum(b['start']-a['end'] for a,b in zip(stages,stages[1:])),
            final_commit_to_receipt_consumed=c['receipt_consumed_at']-last['end'],
            receipt_consumed_to_successor_submit=c['successor_submit_begin']-c['receipt_consumed_at'])
        duration=c['successor_submit_begin']-c['submit_begin']
        rows.append(dict(sequence=c['sequence'],frame=c['committed_frame'],records=c.get('records'),
            commit_attempts=len(stages),commit_errors=sum(bool(s['error']) for s in stages),
            parts=parts,cycle_duration=duration,partition_residual=duration-sum(parts.values()),
            ready_to_owner_entry=None if 'receipt_owner_entry' not in c else c['receipt_owner_entry']-c['mapped_ready_mark'],
            successor_snapshot_stage=c.get('snapshot_stage')))
    return dict(total_flights=len(cycles),complete_partitions=len(rows),incomplete_flights=missing,
        owner_admission_delay=stats([t['entry']-t['request_submitted'] for c in cycles for t in c.get('turns',[])]),
        ready_to_owner_entry=stats([r['ready_to_owner_entry'] for r in rows if r['ready_to_owner_entry'] is not None]),
        decomposition={k:stats([r['parts'][k] for r in rows]) for k in rows[0]['parts']} if rows else {},
        cycle_duration=stats([r['cycle_duration'] for r in rows]),
        max_partition_residual=max((abs(r['partition_residual']) for r in rows),default=None),
        negative_partitions=[r['sequence'] for r in rows if any(v < -1e-6 for v in r['parts'].values())],
        mature= {k:stats([r['parts'][k] for r in rows if 775<=r['frame']<=1112])
            for k in rows[0]['parts']} if rows else {},
        per_flight=rows,
        limitation='Complete timestamp partitions only. Commit attempts include cooperative retries; stage span is not independent of owner/transaction time. Ready mark precedes Future.set_result by callback bookkeeping. Child clocks are common-host monotonic. Final commit-to-consumed includes native successor snapshot and arbiter completion. Incomplete flights are excluded rather than reconstructed from counters.')

def analyze_arm(folder):
    summary=read(folder/'summary.json')
    timeline=[json.loads(line) for line in (folder/'timeline.jsonl').read_text().splitlines()]
    batches=read(folder/'source-batches.json');cycles=read(folder/'archive-cycles.json')
    events=read(folder/'episode-events.json')
    valid=[r for r in timeline if r['arrival_inference_valid'] and r['pins']==r['gaps']==0]
    checkpoints=[point(min(timeline,key=lambda r:abs(r['elapsed']-x))) for x in (180,210,240,270,300,330,355)
        if timeline and timeline[-1]['elapsed']>=x-5]
    intervals=[]
    for start,end in ((210,240),(240,270),(270,300),(300,330),(330,355),(210,300)):
        if not valid or valid[-1]['elapsed']<end-2:continue
        a=min(valid,key=lambda r:abs(r['elapsed']-start));b=min(valid,key=lambda r:abs(r['elapsed']-end))
        dt=b['elapsed']-a['elapsed']
        inside=[r for r in timeline if a['elapsed']<=r['elapsed']<=b['elapsed']]
        validity=all(r['arrival_inference_valid'] and r['pins']==r['gaps']==0 for r in inside)
        scopes={}
        for scope,bv in b['scopes'].items():
            av=a['scopes'][scope];drain=bv['archived']-av['archived'];net=bv['eligible_hot']-av['eligible_hot']
            scopes[scope]=dict(eligible_start=av['eligible_hot'],eligible_end=bv['eligible_hot'],
                excess_start=av['recovery_excess'],excess_end=bv['recovery_excess'],
                arrivals=net+drain,archive_drain=drain,net_debt=net,
                arrivals_per_second=(net+drain)/dt,drain_per_second=drain/dt,
                retirement_progress=bv['retired']-av['retired'])
        intervals.append(dict(start=a['elapsed'],end=b['elapsed'],seconds=dt,
            frames_start=a['frames'],frames_end=b['frames'],valid=validity,scopes=scopes,
            total_arrivals=sum(v['arrivals'] for v in scopes.values()),
            total_archive_drain=sum(v['archive_drain'] for v in scopes.values()),
            source_native_wall=metric(b,'source_owner_native')-metric(a,'source_owner_native'),
            source_floor_wait_requested=metric(b,'source_owner_injected_wait')-metric(a,'source_owner_injected_wait'),
            archive_native_wall=metric(b,'archive_worker.native')-metric(a,'archive_worker.native'),
            archive_floor_wait_requested=metric(b,'archive_worker.injected_wait')-metric(a,'archive_worker.injected_wait')))
    obligations=[]
    for e in events:
        if e['transition']!='latched':continue
        resolution=next((r for r in events if r['transition']=='resolved' and
            (r['scope'],r['side'],r['original_source_deadline'],r['wall_started'])==
            (e['scope'],e['side'],e['original_source_deadline'],e['wall_started'])),None)
        obligations.append(dict(scope=e['scope'],side=e['side'],
            latched_frame=e['committed_frame'],latched_elapsed=e['elapsed'],latched_debt=e['debt'],
            source_deadline=e['original_source_deadline'],projected_deadline=e['projected_deadline'],
            initial_headroom=e['headroom'],resolved_frame=None if resolution is None else resolution['committed_frame'],
            resolved_debt=None if resolution is None else resolution['debt'],
            resolution_headroom=None if resolution is None else resolution['headroom'],
            outcome='open_at_stop' if resolution is None else 'recovered_within_original_deadline'
                if resolution['headroom']>=0 and resolution['debt']<=e['envelope'] else 'late_or_invalid_resolution'))
    groups={}
    for side in ('archive','retirement'):
        for scope in ('program:meteora','program:pump','program:pumpswap'):
            own=[o for o in obligations if o['side']==side and o['scope']==scope]
            groups[side+':'+scope]=dict(latched=len(own),
                recovered=sum(o['outcome']=='recovered_within_original_deadline' for o in own),
                open=sum(o['outcome']=='open_at_stop' for o in own),
                late=sum(o['outcome']=='late_or_invalid_resolution' for o in own),
                interpretation='no_episode_formed; prevention_of_excess_debt_observed' if not own else 'native_latched_obligations_recorded')
    native=metric(summary,'source_owner_native');floor=metric(summary,'source_owner_injected_wait')
    owners=dict(native_stage_wall=native,source_floor_wait_requested=floor,
        source_floor_wait_actual=sum(b['source_floor_wait_actual'] for b in batches),
        retained_commit_floor_wait_in_native_stage=sum(b['commit_floor_wait'] for b in batches),
        native_stage_less_commit_floor_wait=native-sum(b['commit_floor_wait'] for b in batches),
        combined_native_plus_source_floor=native+floor,
        combined_fraction=(native+floor)/summary['runtime_elapsed'],
        frames=sum(b['frames'] for b in batches),batches=len(batches),
        batch_sizes=dict(Counter(str(b['frames']) for b in batches)),
        native_wall_per_frame=native/sum(b['frames'] for b in batches),
        native_cost_per_batch=stats([b['native_seconds'] for b in batches]),
        native_cost_per_frame_by_batch=stats([b['native_seconds_per_frame'] for b in batches]),
        limitation='Native-stage wall includes the identical COMMIT floor and embedded wrappers; commit floor is also recorded separately. Source-floor actual wait includes scheduler oversleep. Source stages/outer transactions/owner service must not be added as independent occupancy.')
    arc=archive_cycles(cycles);write(folder/'archive-cycle-decomposition.json',arc)
    return dict(summary=summary,interaction=read(folder/'interaction.json'),sampled_points=checkpoints,valid_arrival_intervals=intervals,
        observer_samples=len(timeline),valid_samples=len(valid),
        invalid_samples=[dict(elapsed=r['elapsed'],frames=r['frames'],pins=r['pins'],gaps=r['gaps']) for r in timeline if not r['arrival_inference_valid']],
        owner_time=owners,obligations=obligations,obligation_groups=groups,
        episode_events=events,archive_cycles={k:v for k,v in arc.items() if k!='per_flight'})

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();root=Path(a.root)
    arms={}
    for name in ('control','treatment'):
        folder=root/name
        if (folder/'summary.json').exists():
            arms[name]=analyze_arm(folder)
            write(root/(name+'-analysis.json'),arms[name])
        else:arms[name]=dict(unavailable=True,reason='No completed harness summary; retain partial timeline/logs.')
    c,t=arms.get('control',{}),arms.get('treatment',{})
    cs,ts=c.get('summary',{}),t.get('summary',{})
    ct=cs.get('terminal') or {}
    chain=(cs.get('failure')=='EvidenceUnavailable:maintenance_cannot_reserve_both_sides'
        and ct.get('ready')==dict(archive=False,retirement=True) and ct.get('feasible')==[]
        and any(n['side']=='archive' and n['binding']=='recovery' and n['recovery_excess']>0 for n in ct.get('needs',[])))
    success=(ts.get('failure') is None and ts.get('completed_frames')==1334 and ts.get('stop_reason')=='fixed_diagnostic_prefix')
    early=[o for o in t.get('obligations',[]) if o['latched_frame']*.27<=336]
    recovered=all(o['outcome']=='recovered_within_original_deadline' for o in early)
    interpretation=('inconclusive_control_did_not_reproduce' if not chain else
        'owner_pressure_sensitivity_with_native_debt_recovery_or_prevention' if success and recovered else
        'inconclusive_treatment_did_not_complete_or_original_obligations_remain')
    report=dict(status='ASTRA_REVIEW_READY: SOURCE_OWNER_ABLATION_COMPLETE',
        production_sha='dc08f9064cf5e37b63f383f52aa709d0afc1723f',
        reviewed_package_sha='2cc7a7c42e8f98acd57c2b606d132867d2393def',
        diagnostic_identity=read(root/'identity.json'),executions=read(root/'pair-executions.json'),
        control_chain_reproduced=chain,treatment_prefix_completed=success,
        treatment_first_window_obligations_recovered=recovered,
        interpretation=interpretation,arms=arms,budget=dict(consumed=4,ceiling=6,unused=2),
        stage_e='RED',stage_f='NOT_STARTED',paper_only=True,
        establishes='Effect of removing injected owner waiting, conditional on control reproduction and actual native obligation resolution/prevention.',
        does_not_establish=['native_source_processing_alone_caused_historical_failure',
            'archive_preparation_overlap_is_minimum_or_sufficient_repair','canonical_source_floor_removal_authority',
            'full_Stage_E_or_Stage_F_certificate','urgent_ACK_candidate_acceptability'],
        timing_variability='One fixed-order pair on the same runner. Scheduler/CPU/filesystem/checkpoint timing, cache warming and workload-dependent batch formation remain variable. No order counterbalance or replication.',
        best_remaining_discriminator='If attribution is still required, a separately authorized diagnostic that overlaps only successor archive preparation while retaining the .165 source floor and all native admission, reservation and generation semantics. Require original debt deadlines and compare per-flight ready/commit/launch gaps. No execution or repair authorized here.',
        limits='Owner/native observer and SQLite snapshots have distinct timestamps. Exact episode transitions preserve original deadlines. Archive partitions cover completed timestamped flights only; never infer missing flight timings from aggregate counters.')
    write(root/'COMPARISON.json',report)
    # Small reusable durable projections; raw full files remain in the artifact.
    print('COMPARISON_RESULT '+json.dumps({k:v for k,v in report.items() if k!='arms'},sort_keys=True),flush=True)
    for name,arm in arms.items():
        print('ARM_ANALYSIS '+json.dumps(dict(arm=name,analysis=arm),sort_keys=True),flush=True)
    lines=['ASTRA_REVIEW_READY: SOURCE_OWNER_ABLATION_COMPLETE','',
        'PAPER ONLY. Stage E RED. Stage F NOT STARTED. '+interpretation+'.','',
        '| Arm | committed frames | source seconds | stop |',
        '| --- | ---: | ---: | --- |']
    for name,arm in arms.items():
        s=arm.get('summary',{});lines.append(f"| {name} | {s.get('completed_frames')} | {s.get('source_seconds')} | {s.get('failure') or s.get('stop_reason')} |")
    lines+=['','Budget: 4/6 consumed; 2/6 unused. Stop for Astra.']
    body='\n'.join(lines)+'\n';(root/'SUMMARY.md').write_text(body)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as stream:stream.write(body)
    hashes={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest()
        for f in root.rglob('*') if f.is_file() and 'runtime' not in f.relative_to(root).parts and f.name!='SHA256.json'}
    write(root/'SHA256.json',hashes)
    print('EVIDENCE_HASHES '+json.dumps(hashes,sort_keys=True),flush=True)

if __name__=='__main__':main()
