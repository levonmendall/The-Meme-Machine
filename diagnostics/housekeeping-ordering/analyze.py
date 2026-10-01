"""Captured-evidence analysis and stop record; never executes a workload."""
import argparse, hashlib, importlib.util, json, os
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def read(path):
    return json.loads(path.read_text())

def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')

def sole_blocker(row):
    if row.get('selected')!='retirement' or not row.get('receipt_pending'):
        return False
    if not row.get('ready',{}).get('archive') or not row.get('housekeeping',0):
        return False
    leases=row.get('reservations',{});at=row.get('at')
    if at is None or not leases:return False
    active=[n for n in row.get('needs',[]) if n['side']=='retirement' and n['units']]
    hk=[n for n in active if n['scope']=='__housekeeping__']
    if len(hk)!=1:return False
    def effective(n):
        return min(n['safety_deadline'],n['service_deadline'],
                   n['recovery_deadline'] if n['recovery_deadline'] is not None else float('inf'))
    peer=at+2*leases['execution']+leases['owner']
    return (at+leases['execution']<effective(hk[0])<=peer and
            all(effective(n)>peer for n in active if n['scope']!='__housekeeping__'))

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args()
    out=Path(a.root);out.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('preserved_analysis',
        ROOT/'diagnostics/source-owner-ablation/analyze.py')
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
    arms={};compact={}
    for name in ('control','treatment'):
        folder=out/name
        if not (folder/'summary.json').exists():
            arms[name]=dict(unavailable=True)
            compact[name]=dict(unavailable=True)
            continue
        detail=base.analyze_arm(folder)
        turns=read(folder/'native-turns.json')
        relevant=[t for t in turns if sole_blocker(t)]
        prefixes=[t for t in turns if t.get('prefix_requested')]
        hk=lambda t:t.get('durable_progress',{}).get('__housekeeping__',0)
        violations=[]
        for t in prefixes:
            outcome=t.get('retention_outcome') or {}
            if not sole_blocker(t):violations.append(dict(sequence=t['sequence'],reason='prefix_outside_trigger'))
            if outcome.get('yield_reason') in ('source','urgent') and any(
                outcome.get(k,0) for k in ('retired_records','continuity_rows','floor_updates','examined_scopes')):
                violations.append(dict(sequence=t['sequence'],reason='scope_work_behind_queued_source_or_urgent'))
            if t.get('durable_records',{}).get('__housekeeping__',0):
                violations.append(dict(sequence=t['sequence'],reason='housekeeping_record_credit'))
        trace=dict(recorded_turns=len(turns),eligible_count=len(relevant),
            eligible_turns_with_housekeeping_progress=sum(hk(t)>0 for t in relevant),
            eligible_turns_without_housekeeping_progress=sum(hk(t)==0 for t in relevant),
            prefix_turns=len(prefixes),prefix_committed_housekeeping_units=sum(hk(t) for t in prefixes),
            prefix_empty_or_rolled_back_turns=sum(hk(t)==0 for t in prefixes),
            prefix_source_returns=sum((t.get('retention_outcome') or {}).get('yield_reason')=='source' for t in prefixes),
            prefix_urgent_returns=sum((t.get('retention_outcome') or {}).get('yield_reason') in ('urgent','urgent_sql') for t in prefixes),
            trigger_or_progress_rule_violations=violations,
            eligible_turns=relevant,prefix_turn_evidence=prefixes)
        # Keep both counts and full receipt-local native evidence under distinct keys.
        trace['eligible_count']=len(relevant)
        write(folder/'housekeeping-ordering-evidence.json',trace)
        s=detail['summary'];cycles=detail['archive_cycles']
        first=[o for o in detail['obligations'] if o['latched_frame']*.27<=336]
        report=dict(completed_frames=s['completed_frames'],source_seconds=s['source_seconds'],
            failure=s['failure'],stop_reason=s['stop_reason'],
            prefix_completed=s['failure'] is None and s['completed_frames']==1334
                and s['stop_reason']=='fixed_diagnostic_prefix',
            eligible_turns=len(relevant),eligible_serviced=sum(hk(t)>0 for t in relevant),
            eligible_unserviced=sum(hk(t)==0 for t in relevant),prefix_turns=len(prefixes),
            prefix_housekeeping_units=sum(hk(t) for t in prefixes),
            prefix_source_returns=trace['prefix_source_returns'],
            rule_violations=violations,first_window_episodes=len(first),
            first_window_open_or_late=sum(o['outcome']!='recovered_within_original_deadline' for o in first),
            obligation_groups=detail['obligation_groups'],
            mature_archive_timing=cycles.get('mature',{}),
            all_archive_timing=cycles.get('decomposition',{}),
            incomplete_archive_flights=len(cycles.get('incomplete_flights',[])),
            diagnostic_overhead_fraction=s['diagnostic_overhead_fraction'],
            recorded_timing_drops=s['timing_dropped'],observer_errors=s['observer_errors'],
            native_terminal=s.get('terminal'),integrity=s.get('integrity'),environment_differences=s['environment']['differences'])
        detail['housekeeping_evidence']=trace
        arms[name]=detail;compact[name]=report
        write(out/(name+'-analysis.json'),detail)
        print('HOUSEKEEPING_ARM_RESULT '+json.dumps(dict(arm=name,**report),sort_keys=True),flush=True)
    executions=read(out/'pair-executions.json') if (out/'pair-executions.json').exists() else []
    consumed=4+len(executions)
    control=compact.get('control',{});treatment=compact.get('treatment',{})
    mechanism_observed=(control.get('eligible_unserviced',0)>0 and
        treatment.get('prefix_housekeeping_units',0)>0 and not treatment.get('rule_violations'))
    interpretation=('ordering_service_and_prefix_recovery_observed' if mechanism_observed and
        treatment.get('prefix_completed') and treatment.get('first_window_open_or_late')==0 else
        'ordering_service_observed_without_complete_prefix_recovery' if mechanism_observed else
        'inconclusive_for_paired_binding_housekeeping_effect')
    status='HOUSEKEEPING_ORDERING_PAIR_STOP_FOR_ASTRA' if executions else 'HOUSEKEEPING_ORDERING_TEST_GATE_STOP_NO_MATERIAL_RUN'
    stop=dict(status=status,stop_all_diagnostic_execution=True,executions_consumed=consumed,
        ceiling=6,unused=6-consumed,retry_authorized=False,paper_only=True,
        stage_e='RED',stage_f='NOT_STARTED',production_promotion_approved=False,
        canonical_stage_e_approved=False,successor_freeze_approved=False,
        m1_repair_approved=False,preflight_repair_approved=False,
        historical_gates_preserved=True,scope='Stop for Astra; captured evidence only.')
    write(out/'FOLLOWUP_STOP.json',stop)
    comparison=dict(status=status,interpretation=interpretation,
        mechanism_observed=mechanism_observed,arms=compact,executions=executions,
        budget=dict(consumed=consumed,ceiling=6,unused=6-consumed),
        safety_gate=read(out/'SAFETY_GATE.json') if (out/'SAFETY_GATE.json').exists() else None,
        static_verification=read(out/'STATIC_VERIFICATION.json') if (out/'STATIC_VERIFICATION.json').exists() else None,
        paper_only=True,stage_e='RED',stage_f='NOT_STARTED',
        limitations=['One fixed-order matched pair on one hosted runner; no replication or counterbalance.',
            'Source .165, archive .36/1000, COMMIT .006 and reduced urgent ACK controls are retained in both arms.',
            'Scope/owner/transaction/worker spans overlap; do not sum them as independent occupancy.',
            'Ready marker precedes Future.set_result bookkeeping; complete receipt partitions only.',
            'Timing drops or missing summaries leave evidence incomplete; no reconstruction from aggregate counters.',
            'Native and extra observer cost remain mixed. No strict less-than-1-percent certification is claimed.',
            'M1 and preflight blockers remain historical and unresolved; canonical Stage E/F is not tested.'])
    write(out/'COMPARISON.json',comparison)
    print('HOUSEKEEPING_COMPARISON '+json.dumps(comparison,sort_keys=True),flush=True)
    lines=[status,'','PAPER ONLY. Stage E RED. Stage F NOT STARTED.','',
        '| Arm | frames | eligible / serviced | prefix units | terminal |',
        '| --- | ---: | ---: | ---: | --- |']
    for name,r in compact.items():
        lines.append(f"| {name} | {r.get('completed_frames')} | {r.get('eligible_turns')} / {r.get('eligible_serviced')} | {r.get('prefix_housekeeping_units')} | {r.get('failure') or r.get('stop_reason')} |")
    lines+=['',interpretation+'.','',f'Budget: {consumed}/6 consumed; {6-consumed}/6 unused. Stop for Astra.']
    body='\n'.join(lines)+'\n';(out/'SUMMARY.md').write_text(body)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as stream:stream.write(body)
    hashes={str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest()
        for f in out.rglob('*') if f.is_file() and
        not {'runtime','worktrees'}.intersection(f.relative_to(out).parts) and f.name!='SHA256.json'}
    write(out/'SHA256.json',hashes)
    print('HOUSEKEEPING_EVIDENCE_HASHES '+json.dumps(hashes,sort_keys=True),flush=True)

if __name__=='__main__':main()
