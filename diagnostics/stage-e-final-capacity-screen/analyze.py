"""Apply only the immutable predeclared screen rules to preserved raw evidence."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).parent
WORK=Path('/workspace/stage-e-screen-work/runs/final-capacity-screen-20261001-v1')
PRE=json.loads((HERE/'PREDECLARATION.json').read_bytes())
SCOPES=('program:pump','program:pumpswap','program:meteora')

def read(path,default=None):
    return json.loads(path.read_bytes()) if path.exists() else default

def slope(points):
    if len(points)<2:return None
    x=sum(p[0] for p in points)/len(points);y=sum(p[1] for p in points)/len(points)
    den=sum((a-x)**2 for a,b in points)
    return sum((a-x)*(b-y) for a,b in points)/den if den else None

def unique_turns(rows):
    result={}
    for row in rows:
        result[(row.get('generation'),row.get('sequence'),row.get('at'),row.get('selected'))]=row
    return list(result.values())

def episodes(raw,summary,turns,stop):
    origin=summary.get('wire_start')
    events=read(raw/'episode-events.json',[])
    rows={}
    for event in events:
        key=(event['scope'],event['side'],event['original_source_deadline'],event['wall_started'])
        if event['transition']=='latched':
            rows[key]={'scope':event['scope'],'side':event['side'],
                'original_start_wall':event['wall_started'],
                'original_start_source':event['original_source_start'],
                'original_start_source_offset':event['original_source_start']-origin,
                'original_deadline_source':event['original_source_deadline'],
                'original_deadline_source_offset':event['original_source_deadline']-origin,
                'original_deadline_monotonic':event['projected_deadline'],
                'latched_monotonic':event['at'],'opening_excess':event['opening_excess'],
                'resolution_monotonic':None,'headroom_at_resolution':None}
        elif key in rows:
            rows[key].update(resolution_monotonic=event['at'],
                resolution_source=event['source_now'],headroom_at_resolution=event['headroom'])
    for row in rows.values():
        resolved=row['resolution_monotonic']
        end=resolved if resolved is not None else float('inf')
        row['durable_record_progress']=sum((r.get('durable_records') or {}).get(row['scope'],0)
            for r in turns if r.get('selected')==row['side'] and
            row['latched_monotonic']<=r.get('at',-1)<=end)
        row['required_original_deadline_observation']=row['original_start_source_offset']<=240
        if resolved is not None:
            row['status']='PASS' if resolved<row['original_deadline_monotonic'] else 'FAILED'
        elif stop and stop['wall']>=row['original_deadline_source']-.25:
            row['status']='FAILED'
        else:row['status']='CENSORED'
        if stop:
            s=stop['scopes'].get(row['scope'],{})
            row['ending_excess']=s.get('recovery_excess' if row['side']=='archive' else 'retirement_excess')
    return list(rows.values())

def scope_balances(left,right,samples):
    result={}
    elapsed=right['wall']-left['wall']
    for scope in sorted(set(left['scopes'])|set(right['scopes'])):
        a,b=left['scopes'][scope],right['scopes'][scope]
        arrivals=b['eligible_arrivals_total']-a['eligible_arrivals_total']
        archived=b['archived']-a['archived'];retired=b['retired']-a['retired']
        points=[(r['wall'],r['scopes'][scope]['eligible_hot']) for r in samples if scope in r['scopes']]
        result[scope]={'measured_seconds':elapsed,'eligible_arrivals':arrivals,
            'durable_archived':archived,'durable_retired':retired,
            'archive_arrival_rate':arrivals/elapsed,'archive_rate':archived/elapsed,
            'archive_rate_surplus':(archived-arrivals)/elapsed,
            'starting_hot_debt':a['eligible_hot'],'peak_hot_debt':max(y for x,y in points),
            'ending_hot_debt':b['eligible_hot'],'hot_debt_slope':slope(points),
            'starting_archive_excess':a['recovery_excess'],'ending_archive_excess':b['recovery_excess'],
            'archived_pending_arrivals':archived,'retirement_service_rate':retired/elapsed,
            'starting_archived_pending':a['archived_pending'],
            'peak_archived_pending':max(r['scopes'][scope]['archived_pending'] for r in samples),
            'ending_archived_pending':b['archived_pending'],
            'starting_retirement_excess':a['retirement_excess'],'ending_retirement_excess':b['retirement_excess'],
            'retirement_keeps_pace':retired>=archived,
            'retirement_debt_nonincreasing':b['archived_pending']<=a['archived_pending'],
            'retirement_excess_declines_or_stays_zero':b['retirement_excess']<a['retirement_excess'] or a['retirement_excess']==b['retirement_excess']==0,
            'scope_not_starved':not archived or retired>0,
            'starting_retired_durable':a['retired'],'ending_retired_durable':b['retired'],
            'archive_coupled_residual':arrivals-archived-(b['eligible_hot']-a['eligible_hot']),
            'retirement_coupled_residual':archived-retired-(b['archived_pending']-a['archived_pending'])}
    return result

def debt_transfer_test(balance):
    """Separate correct record accounting from actual maintenance-debt decline."""
    if not balance:return None
    hot_delta=balance['ending_hot_debt']-balance['starting_hot_debt']
    pending_delta=balance['ending_archived_pending']-balance['starting_archived_pending']
    return {
        'starting_combined_maintenance_debt':balance['starting_hot_debt']+balance['starting_archived_pending'],
        'ending_combined_maintenance_debt':balance['ending_hot_debt']+balance['ending_archived_pending'],
        'hot_debt_delta':hot_delta,'archived_pending_delta':pending_delta,
        'combined_maintenance_debt_delta':hot_delta+pending_delta,
        'hot_reduction_not_only_exported':hot_delta<0 and hot_delta+pending_delta<0,
    }

def arm(name):
    root=WORK/name;raw=root/'raw';summary=read(raw/'summary.json',{})
    finished=read(root/'FINISHED.json',{})
    timeline=[json.loads(x) for x in (raw/'timeline.jsonl').read_text().splitlines()] if (raw/'timeline.jsonl').exists() else []
    left=read(raw/'mature-start.json');fixed_end=read(raw/'mature-end.json')
    pre_stop=read(raw/'pre-stop-snapshot.json');final=read(raw/'final-snapshot.json')
    right=fixed_end or pre_stop
    turns=unique_turns(read(raw/'native-turns.json',[]))
    queues=read(raw/'source-queues.json',[]);offers=read(raw/'a2-events.json',[])
    owner=read(raw/'owner-events.json',[]);screen=summary.get('screen',{})
    health=read(raw/'native-health.json',{});ipc=health.get('ipc',{})
    failure=summary.get('failure')
    relevant=failure is not None and any(x in failure for x in
        ('maintenance_cannot_reserve_both_sides','maintenance_service_deadline_exhausted'))
    samples=[r for r in timeline if left and right and left['wall']<=r['wall']<=right['wall']]
    if left and right:samples=[left]+samples+[right]
    balances=scope_balances(left,right,samples) if left and right and right['wall']>left['wall'] else {}
    source_start=(left or {}).get('source_coordinate_at_acquisition')
    source_end=(right or {}).get('source_coordinate_at_acquisition')
    if right and source_end is None and summary.get('wire_start') is not None:source_end=right['wall']-summary['wire_start']
    total={}
    if balances:
        duration=right['wall']-left['wall']
        for k in ('eligible_arrivals','durable_archived','durable_retired','starting_hot_debt','peak_hot_debt','ending_hot_debt','starting_archived_pending','ending_archived_pending'):
            total[k]=sum(v[k] for v in balances.values())
        total.update(measured_seconds=duration,arrival_rate=total['eligible_arrivals']/duration,
            archive_rate=total['durable_archived']/duration,
            rate_surplus=(total['durable_archived']-total['eligible_arrivals'])/duration,
            debt_slope=slope([(r['wall'],sum(s['eligible_hot'] for s in r['scopes'].values())) for r in samples]),
            peak_hot_debt=max(sum(s['eligible_hot'] for s in r['scopes'].values()) for r in samples))
    ledger=episodes(raw,summary,turns,pre_stop or right) if summary else []
    actual_placements=[]
    owner_by_seq={r.get('sequence'):r for r in owner}
    for offer in offers:
        m=owner_by_seq.get(offer.get('maintenance_sequence'),{})
        s=owner_by_seq.get(offer.get('source_sequence'),{})
        placed=bool(offer.get('outcome')=='accepted' and m.get('entry') is not None and
            s.get('entry') is not None and offer['maintenance_sequence']<offer['source_sequence'] and m['entry']<s['entry'])
        if placed:
            progress=offer.get('durable_records') or {}
            native=next((r for r in turns if r.get('at') is not None and m['entry']<=r['at']<=m.get('end',m['entry'])),{})
            row=dict(offer,actual_maintenance_before_source=True,
                maintenance_owner_entry=m['entry'],source_owner_entry=s['entry'],
                useful_durable_records=sum(progress.values()),
                native_deadlines=native.get('deadlines'),native_scope_state=native.get('scope_state'))
            actual_placements.append(row)
    a2c=(screen.get('a2') or {}).get('counters',{})
    births=read(raw/'source-batches.json',[])
    charge_errors=[r for r in births if r['source_floor_wait_requested']!=max(0,.165*r['frames']-r['native_seconds'])]
    peak_hot=max((s['hot_age'] for r in timeline for s in r['scopes'].values()),default=None)
    peak_retained=max((s['retained_age'] for r in timeline for s in r['scopes'].values()),default=None)
    peak_lag=max((r['source_lag'] for r in timeline),default=None)
    cq=[r for r in queues if left and right and left['elapsed']<=r['elapsed']<=right['elapsed'] and 'pending_frames' in r]
    backlog_growth=None if not cq else cq[-1]['pending_frames']-cq[0]['pending_frames']
    due_backlog_growth=None if not cq else (cq[-1]['offered_due_frames']-cq[-1]['committed_frames'])-(cq[0]['offered_due_frames']-cq[0]['committed_frames'])
    pending_slope=slope([(r['elapsed'],r['pending_frames']) for r in cq])
    stream_ack=a2c.get('bypass_head_ack',0)
    admitted=None if 'stream.received_messages' not in ipc else ipc['stream.received_messages']-stream_ack
    source={'planned':1334,'offered':summary.get('wire_sent'),'admitted':admitted,
        'committed':summary.get('completed_frames'),'offered_source_seconds':summary.get('wire_sent',0)*.27,
        'committed_source_seconds':summary.get('source_seconds'),
        'peak_source_lag':peak_lag,'source_lag_contract_seconds':45,
        'native_source_seconds':summary.get('metrics',{}).get('source_owner_native',{}).get('wall'),
        'injected_source_seconds':summary.get('metrics',{}).get('source_owner_injected_wait',{}).get('wall'),
        'charge_formula_errors':len(charge_errors),'peak_pending_frames':max((r.get('pending_frames',0) for r in queues),default=None),
        'peak_pending_bytes':max((r.get('pending_bytes',0) for r in queues),default=None),
        'queue_peaks':{k:max((r.get(k,0) for r in queues),default=None) for k in ('ready','decoded','inbound')},
        'mature_pending_growth':backlog_growth,'mature_due_uncommitted_growth':due_backlog_growth,
        'mature_pending_slope':pending_slope,
        'pre_admission_gate_wait_total_us':a2c.get('wait_total_us',0),
        'pre_admission_gate_wait_peak_us':a2c.get('wait_peak_us',0),'ipc':ipc}
    conservation=[r.get('conservation',{}) for r in timeline]
    conserved=bool(conservation) and all(all(x['total']==x['eligible']==0 for x in r.values()) for r in conservation)
    observers=screen.get('periodic_observer_errors',[])+screen.get('instrumentation_errors',[])
    observation_valid=bool(summary and left and right and cq) and not observers and screen.get('dropped_samples',1)==0 and conserved
    observation_valid=observation_valid and all(abs(x)<=1 for x in screen.get('boundary_acquisition_gaps',{}).values())
    observation_valid=observation_valid and (screen.get('measurement_gap_peak_seconds') or float('inf'))<=10
    if fixed_end is None:observation_valid=observation_valid and name=='control' and relevant and source_end<=349.92
    needs=(summary.get('terminal') or {}).get('needs',[])
    no_feasible=(summary.get('terminal') or {}).get('feasible')==[]
    root_mechanism=relevant and no_feasible and any(n.get('side')=='archive' and n.get('units',0)>0 for n in needs)
    unresolved_original=any(x['required_original_deadline_observation'] and x['status']=='FAILED' and x.get('ending_excess',0)>0 for x in ledger)
    reproduction=bool(total and total['durable_archived']<total['eligible_arrivals'] and
        (total['ending_hot_debt']>total['starting_hot_debt'] or any(v['ending_archive_excess']>0 for v in balances.values())) and
        (root_mechanism or unresolved_original))
    archive_success=bool(fixed_end and total and total['durable_archived']>total['eligible_arrivals'] and
        total['ending_hot_debt']<total['starting_hot_debt'] and total['debt_slope']<0)
    retirement_success=bool(balances) and all(v['retirement_keeps_pace'] and v['retirement_debt_nonincreasing'] and
        v['retirement_excess_declines_or_stays_zero'] and v['scope_not_starved'] for v in balances.values())
    deadline_success=all(r['status']=='PASS' for r in ledger if r['required_original_deadline_observation'] or r['original_start_source_offset']<=349.92)
    source_success=(source['offered']==source['admitted']==source['committed']==1334 and not charge_errors and peak_lag is not None and peak_lag<45 and
        not any(v for k,v in summary.get('counters',{}).items() if k.startswith('disconnect:') or k=='capacity_stops'))
    source_success=source_success and pending_slope is not None and pending_slope<=0 and due_backlog_growth is not None and due_backlog_growth<=0
    integrity_success=(summary.get('integrity')==[['ok']] and screen.get('owner_unresolved_accepted_futures')==0 and
        screen.get('owner_thread_alive') is False and not finished.get('residual_process_group',True) and
        all(x=='exited' for x in screen.get('worker_processes',{}).values()) and
        bool(screen.get('writer_close')) and all(not x['transaction_open'] for x in screen['writer_close']) and
        screen.get('provider_calls')==screen.get('provider_attempts')==0)
    safety_success=(failure is None and not screen.get('owner_fairness_errors') and
        not screen.get('urgent_control_errors') and not screen.get('candidate_read_errors') and
        not (screen.get('a2') or {}).get('failed',False) and a2c.get('overshoots',0)==0 and
        peak_hot is not None and peak_hot<240 and peak_retained is not None and peak_retained<240 and
        any(ipc.get(k,0)>0 for k in ('checkpoint.reclaimed','checkpoint.boundary_reclaimed')) and
        max((r['wal_bytes']+r['db_bytes'] for r in timeline),default=float('inf'))<2*1024**3 and
        ipc.get('stream.commit_batch_messages_peak',9)<=8 and ipc.get('stream.commit_batch_bytes_peak',16777217)<=16777216)
    transfer=debt_transfer_test(total)
    checks={'observation_valid':observation_valid,'control_reproduces':reproduction,
        'archive_positive_surplus_and_debt_reduction':archive_success,'retirement_sustainable_every_scope':retirement_success,
        'original_deadlines_pass':deadline_success,'source_integrity_no_upstream_masking':source_success,
        'conservation_reconciles':conserved,
        'hot_debt_reduction_not_only_exported':bool(transfer and transfer['hot_reduction_not_only_exported']),
        'integrity_resources':integrity_success,'safety_fairness':safety_success}
    full_success=all(v for k,v in checks.items() if k!='control_reproduces')
    costs={k:v for k,v in summary.get('metrics',{}).items() if k in ('periodic_observer_total','serialization','persistence','diagnostic_wrapper','screen_queue_observation','screen_boundary_observation')}
    return {'arm':name,'identity':PRE['arms'][name],'execution':finished,'summary_present':bool(summary),
        'stop_reason':summary.get('stop_reason'),'root_failure':failure,'relevant_capacity_root_failure':root_mechanism,
        'mature_interval_declared':[190.08,349.92],'mature_source_acquisition':[source_start,source_end],
        'mature_suffix_censored':fixed_end is None,'archive':total,'per_scope':balances,'source':source,
        'debt_transfer_test':transfer,
        'whole_arm':{'counters':summary.get('counters',{}),'final_scopes':(final or {}).get('scopes',{}),
            'runtime_elapsed':summary.get('runtime_elapsed'),'planned_source_frames':1334},
        'recovery_episodes':ledger,'a2':{'offers':a2c.get('offers',0),'accepted':a2c.get('accepted',0),
            'timeouts':a2c.get('timeout',0),'bypasses':{k:v for k,v in a2c.items() if k.startswith('bypass_')},
            'affected_frames':sum(r.get('affected_frames',0) for r in offers),
            'actual_placements':len(actual_placements),'useful_placements':sum(r['useful_durable_records']>0 for r in actual_placements),
            'placement_correlations':actual_placements},
        'housekeeping':{'prefix_triggers':sum(bool(r.get('prefix_requested')) for r in turns),
            'prefix_outcomes':[r.get('retention_outcome') for r in turns if r.get('prefix_requested')],
            'durable_units':sum((r.get('durable_progress') or {}).get('__housekeeping__',0) for r in turns),
            'native_demand_peak':max((r.get('housekeeping',0) for r in turns),default=0)},
        'archive_slices':[r.get('durable_records') for r in turns if r.get('selected')=='archive' and r.get('durable_records')],
        'owner':{'admissions':len(owner),'priority_counts':{str(k):sum(r['priority']==k for r in owner) for k in set(r['priority'] for r in owner)},
            'queue_delay_peak':max((r['entry']-r['accepted'] for r in owner if 'entry' in r),default=None),
            'fairness_errors':screen.get('owner_fairness_errors')},
        'ages':{'hot_peak':peak_hot,'retained_peak':peak_retained,'strict_limit_seconds':240},
        'observation':{'costs':costs,'screen':screen,'cost_not_subtracted':True,'formal_benchmark_run':False},
        'resources':summary.get('resources'),'integrity':summary.get('integrity'),
        'checks':checks,'treatment_all_requirements_pass':full_success}

def main():
    control=arm('control');treatment=arm('treatment')
    def interrupted(a):return not a['summary_present'] or a['execution'].get('forced') or a['execution'].get('controller_interrupted')
    if any(interrupted(a) for a in (control,treatment)):classification='EXECUTION_INTERRUPTED'
    elif control['root_failure'] and not control['relevant_capacity_root_failure']:classification='INCONCLUSIVE_INVALID_CONTROL_FAILURE'
    elif not all(a['checks']['observation_valid'] for a in (control,treatment)):classification='INCONCLUSIVE_INSTRUMENTATION'
    elif not control['checks']['control_reproduces']:classification='INCONCLUSIVE_CONTROL_DID_NOT_REPRODUCE'
    elif treatment['treatment_all_requirements_pass']:classification='CONTROL_FAILS_TREATMENT_RECOVERS'
    elif treatment['a2']['useful_placements']>0 and treatment['root_failure'] is None and treatment['checks']['integrity_resources'] and treatment['checks']['safety_fairness']:
        classification='MECHANISM_WORKS_CAPACITY_INSUFFICIENT'
    else:classification='NO_BENEFIT_OR_NEW_FAILURE'
    result={'CAPACITY_SCREEN':classification,'capacity_screen_green':classification=='CONTROL_FAILS_TREATMENT_RECOVERS',
        'paper_only':True,'stage_e':'RED','stage_f':'NOT_STARTED','historical_budget':'6/6 unchanged','capacity_budget':'2/2 consumed',
        'predeclaration_commit':'729d0151568cec6dbcb93b5ff177d996ae9e3584','control':control,'treatment':treatment,
        'stop_for_astra':True,'no_retry_or_additional_execution':True}
    (HERE/'RESULTS.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:result[k] for k in ('CAPACITY_SCREEN','capacity_screen_green','capacity_budget','stop_for_astra')},indent=2))

if __name__=='__main__':main()
