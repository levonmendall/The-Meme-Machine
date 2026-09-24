"""Post-block breadth, conformance and position audits; no provider calls or DB writes.

Unknown denominators remain null. Candidate stages/classes overlap and are never
added as if disjoint losses. Admission uses the frozen censoring policy, with no
new profitability or numerical breadth threshold.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

LANES=('pump','pons','meteora','ramses')
SCOPE={
 'pump':dict(authority='sources.json:lanes.pump.prospect_admission; pump_acceleration_strategy.POLICY',
     universe='Native-SOL Pump curves in the frozen 60-85% late-curve strategy domain, plus its authenticated PumpSwap graduation/continuation modes; existing positions retain their lifecycle scope.',
     dimensions=['surface','phase','quote_asset'],denominator='Source stream completeness; absolute chain opportunity census unavailable.'),
 'pons':dict(authority='pons_selective_cohort.operational_configuration; pons_selective_continuation.POLICY',
     universe='Native-quote Pons curves in the frozen 50-85% progress, 120-600s age and 20-90s graduation-ETA domain, plus its authenticated graduation/re-entry modes; existing positions retain their lifecycle scope.',
     dimensions=['curve','graduation_state','event_at'],denominator='Canonical discovery cursor/log windows; independent all-event denominator unavailable.'),
 'meteora':dict(authority='SOLANA_DLMM_INDEPENDENT_V1.json; solana_dlmm_independent_v1 discovery loop',
     universe='Nonblacklisted Solana Meteora DLMM pools with exactly one WSOL leg, as defined by the frozen strategy; no minimum TVL or absolute volume.',
     dimensions=['quote_asset','public_sort','pool'],denominator='Full target-pair inventory is unknown. The bounded ranking-page union measures source acquisition only and does not redefine the target market.'),
 'ramses':dict(authority='ramses_universe.scan; ramses_strategy.POLICY',
     universe='Recently active Ramses USDG pools with one or two prior 30-minute swaps, as frozen in sources.json; existing positions retain their lifecycle scope.',
     dimensions=['quote_asset','swap_count','bin_depth'],denominator='Authenticated USDG subset of the complete quiet-entry pool cohort; the broad factory inventory is acquisition overhead.'),
}

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def ro(path):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    db.execute('PRAGMA query_only=ON');return db
def ratio(a,b):return a/b if isinstance(a,int) and isinstance(b,int) and b>0 else None
def percentile(values,q):
    values=sorted(values)
    return values[min(len(values)-1,int((len(values)-1)*q))] if values else None

def economic_marks(lane,proof):
    a=proof.get('accounting') or {}
    if lane=='ramses':
        return dict(by_quote_asset={asset:dict(realized=r.get('realized'),unrealized=None,
            unrealized_status='not_marked_by_native_ledger') for asset,r in a.get('by_quote_asset',{}).items()},
            unlike_quote_units_summed=False)
    suffix='_pnl_lamports' if lane=='meteora' else ''
    return dict(realized=a.get('realized'+suffix),unrealized=a.get('unrealized'+suffix),
        units='lamports' if lane in ('pump','meteora') else 'native_quote_raw',
        unrealized_status='available' if a.get('unrealized'+suffix) is not None else 'not_marked_by_native_ledger')

def pipeline(root):
    paths=sorted(set(Path(root).rglob('*.pipeline.sqlite')) | set(Path(root).rglob('opportunity-pipeline.sqlite')))
    if len(paths)!=1:return dict(available=False,reason='pipeline_missing_or_ambiguous')
    with ro(paths[0]) as db:
        stages={k:n for k,n in db.execute('SELECT stage,COUNT(DISTINCT candidate) FROM progress GROUP BY stage')}
        classes={k:n for k,n in db.execute('SELECT classification,COUNT(DISTINCT candidate) FROM progress WHERE classification IS NOT NULL GROUP BY classification')}
        reasons={k:n for k,n in db.execute('SELECT reason,COUNT(DISTINCT candidate) FROM progress WHERE reason IS NOT NULL GROUP BY reason')}
        last=db.execute('SELECT stage,at FROM progress ORDER BY sequence DESC LIMIT 1').fetchone()
        stage_times={stage:at for stage,at in db.execute('SELECT stage,MAX(at) FROM progress GROUP BY stage')}
        gaps=Counter();latencies={};by_candidate={};discovery_frontiers=set();missing_discovery_frontier=False
        for candidate,stage,at,details,classification in db.execute('SELECT candidate,stage,at,details,classification FROM progress ORDER BY sequence'):
            by_candidate.setdefault(candidate,{}).setdefault(stage,at)
            d=json.loads(details)
            if stage=='discovered':
                frontier=d.get('frontier')
                if (isinstance(frontier,list) and len(frontier)==2
                        and type(frontier[0]) is int and isinstance(frontier[1],str) and frontier[1]):
                    discovery_frontiers.add(tuple(frontier))
                else:missing_discovery_frontier=True
            if classification in ('provider_failed','capacity_censored','consumer_deadline','reconstruction_incomplete','local_budget_exhausted'):
                segment={k:d[k] for k in ('surface','phase','quote_asset','graduated','mode') if k in d}
                gaps[canonical(segment or {'segment':'not_preserved'})]+=1
        for start,end in [('discovered','screened'),('screened','evidence_requested'),
                          ('evidence_requested','evidence_complete'),('evidence_complete','qualified')]:
            vals=[d[end]-d[start] for d in by_candidate.values() if start in d and end in d and d[end]>=d[start]]
            latencies[start+'__'+end]=dict(count=len(vals),p50=percentile(vals,.5),p95=percentile(vals,.95),max=max(vals) if vals else None)
    return dict(available=True,stages=stages,classes=classes,reasons=reasons,
        last_stage=last[0] if last else None,last_at=last[1] if last else None,
        last_at_by_stage=stage_times,latency_seconds=latencies,
        discovery_frontiers=[dict(block=block,hash=block_hash) for block,block_hash in sorted(discovery_frontiers)],
        discovery_frontier_membership_complete=not missing_discovery_frontier,
        gaps_by_segment=[dict(segment=json.loads(k),transition_records=n) for k,n in gaps.items()],
        identity_scope='native candidate IDs within this block; stage and class counts overlap')

def meteora_source_coverage(runtime,native,source):
    """Reconstruct the frozen public page union from evidence already acquired."""
    constants={}
    for node in ast.parse((Path(source)/'tests/solana_dlmm_independent_v1.py').read_text()).body:
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id in ('DISCOVERY_SORTS','DISCOVERY_PAGES_PER_SORT','DISCOVERY_PAGE_SIZE'):
                    constants[target.id]=ast.literal_eval(node.value)
    expected={(sort,page) for sort in constants['DISCOVERY_SORTS'] for page in range(1,constants['DISCOVERY_PAGES_PER_SORT']+1)}
    path=Path(native)/'solana-dlmm-independent-v1-live.pipeline.sqlite'
    with ro(path) as db:
        discovered={r[0] for r in db.execute("SELECT DISTINCT candidate FROM progress WHERE stage='discovered'")}
        screened={r[0] for r in db.execute("SELECT DISTINCT candidate FROM progress WHERE stage='screened'")}
    all_raw=set();eligible=set();pages={};errors=[];exhausted=set()
    with ro(Path(runtime)/'meteora/telemetry.sqlite') as db:
        for at_ns,raw in db.execute("SELECT at_ns,body FROM events WHERE kind='public_http_evidence' ORDER BY seq"):
            event=json.loads(raw)
            if event.get('path')!='/pools':continue
            params=event.get('parameters') or {};sort=params.get('sort_by');page=params.get('page');key=(sort,page)
            response=event.get('response') or {};rows=response.get('data')
            if key not in expected:errors.append('unexpected_discovery_source_page');continue
            if event.get('error_type') or not isinstance(rows,list):errors.append(f'failed_page:{sort}:{page}');continue
            ids={r.get('address') for r in rows if isinstance(r,dict) and r.get('address')}
            sol={r.get('address') for r in rows if isinstance(r,dict) and r.get('address') and
                 (((r.get('token_x') or {}).get('address')=='So11111111111111111111111111111111111111112') ^
                  ((r.get('token_y') or {}).get('address')=='So11111111111111111111111111111111111111112'))}
            all_raw.update(ids);eligible.update(sol)
            if len(rows)<constants['DISCOVERY_PAGE_SIZE']:
                exhausted.update((sort,p) for p in range(page+1,constants['DISCOVERY_PAGES_PER_SORT']+1))
            pages[key]=dict(sort=sort,page=page,observed_at=at_ns/1e9,raw_rows=len(rows),
                one_wsol_pair_count=len(sol),discovered_in_page=len(sol & discovered),
                preflight_evaluated_in_page=len(sol & screened),
                not_discovered_from_acquired_page=len(sol-discovered),
                global_api_total=response.get('total'),global_total_is_strategy_denominator=False)
    missing=sorted(expected-set(pages)-exhausted)
    complete=not missing and not errors
    return dict(authority='Exact frozen DISCOVERY_SORTS, DISCOVERY_PAGES_PER_SORT and DISCOVERY_PAGE_SIZE',
        census_complete=complete,planned_source_pages=len(expected),acquired_source_pages=len(pages),
        unobserved_source_pages=[dict(sort=s,page=p) for s,p in missing],
        raw_acquired_source_union_count=len(all_raw),structurally_eligible_acquired_union_count=len(eligible),
        target_structural_union_count=len(eligible) if complete else None,
        union_scope='acquired ranking pages only; not the full strategy target universe',
        full_strategy_target_universe_count=None,
        out_of_target_source_rows=len(all_raw-eligible),
        discovered_in_acquired_structural_union=len(eligible & discovered),
        undiscovered_in_acquired_structural_union=len(eligible-discovered),
        acquired_union_discovery_coverage=ratio(len(eligible & discovered),len(eligible)),
        segments=list(pages.values()),errors=errors,
        gap_classification='ordered_discovery_and_evidence_share_the_bounded_observation_window' if missing else None,
        inferred_never_observed_outside_acquired_pages=False,provider_calls_added=0)

def native_positions(root,lane):
    """Project native append-only events and retain their digest chain for transfers."""
    positions={};violations=[];journal=[];by_id={};cohort=[]
    for path in sorted(Path(root).rglob('*.sqlite*')):
        if not path.is_file() or path.name.endswith(('-wal','-shm')):continue
        with ro(path) as db:
            tables={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if lane=='pons' and 'pons_selective_paper' in tables:
                rows=[json.loads(x[0]) for x in db.execute('SELECT body FROM pons_selective_paper')]
                for row in rows:positions[row['id']]=row
                events=[json.loads(x[0]) for x in db.execute("SELECT body FROM records WHERE category='pons_selective_paper_journal'")]
                events.sort(key=lambda e:((e.get('position') or {}).get('id',''),(e.get('position') or {}).get('version',-1)))
                for event in events:
                    identity=event['position']['id'];by_id.setdefault(identity,[]).append(event)
            elif lane=='pons' and 'capital_positions' in tables:
                cohort.extend(json.loads(raw) for raw, in db.execute('SELECT body FROM capital_positions'))
            elif lane=='ramses' and 'ramses_strategy_journal' in tables:
                for identity,action,raw in db.execute('SELECT id,action,body FROM ramses_strategy_journal ORDER BY seq'):
                    row=json.loads(raw);positions[identity]=row
                    by_id.setdefault(identity,[]).append(dict(action=action,position=row))
            elif lane=='meteora' and 'events' in tables and 'accounting' in path.name:
                for raw, in db.execute('SELECT body FROM events ORDER BY seq'):
                    event=json.loads(raw);identity=event.get('identity')
                    if identity:by_id.setdefault(identity,[]).append(event)
                for identity,events in by_id.items():
                    last=events[-1];terminal=last['action'] in ('cancel','settle','writeoff')
                    entered=any(e['action']=='entry' for e in events)
                    positions[identity]=dict(id=identity,status='settled' if terminal else 'open' if entered else 'reserved',
                        version=len(events)-1,at=last.get('at'),last_action=last['action'])
            elif lane=='pump' and 'journal' in tables and 'positions' in tables:
                for raw, in db.execute('SELECT body FROM positions'):
                    position=json.loads(raw);positions[position['id']]=position
                for raw, in db.execute('SELECT body FROM journal ORDER BY seq'):
                    event=json.loads(raw);identity=event['position']['id']
                    by_id.setdefault(identity,[]).append(event)
            # No speculative table reads: an unsupported schema stays unknown.
    entries=settlements=monitoring=partials=exits=complete=0
    entry_times={};monitor_times={}
    for identity,events in by_id.items():
        actions=[e.get('action') for e in events]
        entered=any(x in ('entry','open','fill','filled') for x in actions)
        terminal=any(x in ('settle','settlement','settled') for x in actions)
        if lane=='pons' and positions.get(identity,{}).get('status')=='settled' and 'exit' in actions:
            terminal=True
        for event in events:
            position=event.get('position') or {}
            at=event.get('at',position.get('last_at',position.get('at')))
            if event.get('action') in ('entry','open','fill','filled') and isinstance(at,(int,float)):
                entry_times.setdefault(identity,at)
            if event.get('action') in ('mark','monitor') and isinstance(at,(int,float)):
                monitor_times[identity]=at
        entries+=entered;settlements+=bool(entered and terminal)
        monitoring+=bool(entered and any(x in ('mark','monitor') for x in actions))
        partials+=sum(x in ('partial_exit','partial','partial_realization','partial_harvest') for x in actions)
        exits+=sum(x in ('exit','exit_intent','segment_close','settled') for x in actions)
        complete+=bool(entered and terminal and any(x in ('mark','monitor') for x in actions)
                       and any(x in ('exit','exit_intent','segment_close','settle','settled') for x in actions))
        if actions.count('entry')+actions.count('open')>1:violations.append(dict(id=identity,reason='duplicate_entry'))
        if actions.count('settle')>1:violations.append(dict(id=identity,reason='duplicate_realization'))
        previous_version=None
        for event in events:
            p=event.get('position') or {};version=p.get('version')
            if previous_version is not None and version is not None and version!=previous_version+1:
                violations.append(dict(id=identity,reason='lifecycle_version_discontinuity'))
            if version is not None:previous_version=version
        row=positions.get(identity,{})
        if row.get('status')=='settled' and any(row.get(k,0)!=0 for k in ('tokens','reserved','remaining_cost')):
            violations.append(dict(id=identity,reason='terminal_residual_exposure'))
        journal.append(dict(id=identity,events=len(events),event_hashes=[digest(e) for e in events]))
    for row in cohort:
        native=positions.get(row['id'])
        if native is None:violations.append(dict(id=row['id'],reason='missing_native_position'))
        elif native!=row.get('native_position'):violations.append(dict(id=row['id'],reason='cross_ledger_position_mismatch'))
        elif native.get('status')=='settled' and row.get('reserved')!=0:
            violations.append(dict(id=row['id'],reason='cancelled_native_position_retains_cohort_reserve'))
    return dict(positions=positions,journals=journal,violations=violations,
        entry_times=entry_times,last_monitor_times=monitor_times,
        natural_entries=entries,natural_settlements=settlements,natural_monitoring=monitoring,
        natural_partial_realizations=partials,natural_exits=exits,complete_natural_lifecycles=complete,
        natural_counts_source='native append-only action records; cancellations are not entries or settlements')

def continuity(previous,current):
    failures=[];spanning=0
    prior_j={r['id']:r for r in previous.get('journals',[])}
    next_j={r['id']:r for r in current.get('journals',[])}
    for identity,row in previous.get('positions',{}).items():
        if row.get('status') in ('settled','cancelled','written_off'):continue
        if identity not in current.get('positions',{}):
            failures.append(dict(id=identity,reason='open_position_lost_across_block'));continue
        spanning+=1;old=prior_j.get(identity,{}).get('event_hashes',[])
        new=next_j.get(identity,{}).get('event_hashes',[])
        if not old or new[:len(old)]!=old:
            failures.append(dict(id=identity,reason='unexplained_cross_block_state_mutation'))
        elif len(old)==len(new) and row!=current['positions'][identity]:
            failures.append(dict(id=identity,reason='projection_changed_without_event'))
    return dict(status='fail' if failures else 'pass',positions_spanning_blocks=spanning,failures=failures)

def lane_report(lane,row,native,conformance,pipe,proof,ended_at,previous=None):
    stages=pipe.get('stages') or (row.get('opportunity_coverage') or {}).get('stages') or {}
    classes=pipe.get('classes') or {};scan=row.get('scan_progress') or {}
    observed=stages.get('discovered');target=None;structural=None;discovered=observed
    gaps=[]
    upstream=dict(native_candidate_discovered_count=observed,native_funnel_stages=stages,
        broader_source_rows_are_strategy_observations=False)
    preflight=stages.get('screened',stages.get('evaluated'))
    if lane in ('pump','pons'):
        # These native discovery rows precede strategy-domain screening. They
        # cannot establish how many target opportunities were observed. Keep
        # acquisition progress visible without relabelling it as target breadth.
        discovered=None;preflight=None
    if lane=='ramses':
        # Factory census rows include out-of-scope assets. Never count these as
        # observed strategy targets, nor use profitability gates as a denominator.
        census_complete=(scan.get('state')=='complete' and scan.get('log_pages_completed')==scan.get('log_pages_total'))
        scope_complete=(census_complete and scan.get('quiet_activity_deferred')==0
                        and scan.get('identity_preflight_failures')==0)
        latest_frontier=dict(block=scan.get('frontier_block'),hash=scan.get('frontier_hash'))
        # Distinct discovery IDs span the whole block. A latest-scan census is
        # a denominator only when every discovered row belongs to that frontier.
        # Multiple completed scans can contain different, overlapping target sets.
        census_window_matches=(pipe.get('discovery_frontier_membership_complete') is True
            and type(latest_frontier['block']) is int and bool(latest_frontier['hash'])
            and pipe.get('discovery_frontiers')==[latest_frontier])
        target=scan.get('strategy_identity_candidates') if scope_complete and census_window_matches else None
        structural=target
        if not census_complete:
            gaps.append('factory_census_incomplete_or_unmeasured')
        if scan.get('quiet_activity_deferred',0)>0:gaps.append('target_scope_preflight_capacity_deferred')
        if scan.get('identity_preflight_failures',0)>0:gaps.append('target_scope_identity_unavailable')
        upstream.update(factory_inventory_count=scan.get('pools_total'),
            quiet_activity_candidates=scan.get('quiet_activity_candidates'),
            known_target_candidates=scan.get('strategy_identity_candidates'),
            known_target_candidates_scope='latest_scan_only',
            latest_scan_frontier=latest_frontier,
            latest_scan_scope_census_complete=scope_complete,
            observation_window_matches_latest_census=census_window_matches,
            scope_exclusions=scan.get('target_scope_exclusions'))
    elif lane=='meteora':
        target=None  # Seen union is a lower bound when pagination completion is not preserved.
        structural=(stages.get('screened',0)-classes['structural_ineligible']
                    if 'structural_ineligible' in classes else None)
    for key in ('provider_failed','capacity_censored','consumer_deadline','local_budget_exhausted','reconstruction_incomplete'):
        if classes.get(key,0)>0:gaps.append(key)
    if not pipe.get('available'):gaps.append('pipeline_unavailable')
    stream=row.get('stream_state') or {}
    if any(stream.get(k,0)>0 for k in ('gaps','parse_failures','capacity_losses','creation_capacity_losses')):
        gaps.append('stream_coverage_loss')
    coverage='coverage_degraded' if gaps else 'coverage_unknown' if target is None else 'coverage_healthy'
    violations=list(native['violations'])
    transfer=continuity(previous,native) if previous else dict(status='not_applicable',positions_spanning_blocks=0,failures=[])
    violations.extend(transfer['failures'])
    if violations:coverage='coverage_invalid'
    attempts=stages.get('evidence_requested');completed=stages.get('evidence_complete')
    if lane=='ramses' and completed==0:completed=None  # Screening is not authenticated full entry evidence.
    open_rows=[r for r in native['positions'].values() if r.get('status') not in ('settled','cancelled','written_off')]
    times=[native['entry_times'].get(r['id']) for r in open_rows]
    times=[x for x in times if isinstance(x,(int,float))]
    failures=[]
    if conformance.get('status')=='fail':failures.append('strategy_conformance_failure')
    if conformance.get('status')=='unknown':failures.append('decision_conformance_unestablished')
    if row.get('unexpected_exit') or row.get('exit_code') not in (0,None):failures.append('process_failed')
    if proof.get('verified') is not True:failures.append('accounting_unestablished')
    if violations:failures.append('position_invariant_failure')
    progress=pipe.get('last_at_by_stage') or {}
    upstream['discovery_progress_at']=progress.get('discovered')
    behavior=dict(process_alive=row.get('health')=='responsive',provider_alive=bool(row.get('provider_requests')),
        target_market_discovery_progressing=progress.get('discovered') if discovered is not None else None,
        discovery_breadth_healthy=coverage,
        evidence_progressing=progress.get('evidence_complete'),qualification_progressing=progress.get('evaluated'),
        position_monitoring_progressing=max(native['last_monitor_times'].values(),default=progress.get('monitor')),
        settlement_progressing=progress.get('settled'),
        strategy_progressing=pipe.get('last_at'),classification=(row.get('pipeline_health') or {}).get('state'))
    return dict(strategy_conformance=conformance.get('status'),current_strategy_phase='position_open' if open_rows else pipe.get('last_stage'),
        last_strategy_progress_at=pipe.get('last_at'),target_market_scope=SCOPE[lane],
        target_market_universe_count=target,structurally_eligible_count=structural,
        upstream_acquisition=upstream,
        discovered_count=discovered,discovery_coverage=ratio(discovered,target),
        observed_market_count_scope='strategy_target_only',
        observed_market_count_status='unknown_scope_membership' if discovered is None else 'target_candidates_observed',
        preflight_evaluated_count=preflight,
        preflight_coverage=ratio(preflight,discovered),
        full_evidence_attempted=attempts,full_evidence_completed=completed,
        evidence_completion_coverage=ratio(completed,attempts),evidence_attempt_coverage=None,
        candidates_requiring_full_evidence=None,qualified_count=stages.get('qualified'),
        authorized_count=native['natural_entries'],
        discovered_too_late=classes.get('stale_before_evidence'),never_discovered=None,
        queue_saturation=dict(classified_candidates={k:classes.get(k,0) for k in ('capacity_censored','consumer_deadline','local_budget_exhausted')},
            queue_time_at_capacity_seconds=None,maximum_concurrent_evaluations=None),
        coverage_health=coverage,coverage_gaps=gaps,coverage_gaps_by_segment=pipe.get('gaps_by_segment',[]),
        acquisition_latency_seconds=pipe.get('latency_seconds'),behavioral_liveness=behavior,
        current_open_positions=sum(r.get('status') in ('open','exit_pending','unresolved') for r in open_rows),
        native_unsettled_records=proof.get('open_positions'),native_position_records_open=len(open_rows),
        oldest_open_position_age=max(0,ended_at-min(times)) if times else None,
        positions_spanning_blocks=transfer['positions_spanning_blocks'],
        **{k:native[k] for k in ('natural_entries','natural_settlements','complete_natural_lifecycles')},
        natural_lifecycle=dict(machinery_certified='separate_exact_sha_certificate',
            target_market_coverage_observed=coverage,natural_entry_observed=native['natural_entries']>0,
            natural_monitoring_observed=native['natural_monitoring']>0,
            natural_partial_realization_observed_if_strategy_triggers_it=native['natural_partial_realizations']>0,
            natural_exit_observed=native['natural_exits']>0,natural_settlement_observed=native['natural_settlements']>0,
            complete_natural_lifecycle_observed=native['complete_natural_lifecycles']>0),
        decision_replay_checked=conformance.get('checked',0),decision_replay_failures=conformance.get('failures',[]),
        conformance_unavailable=conformance.get('unavailable',[]),accounting_reconciliation=proof,
        position_watchdog=dict(status='fail' if violations else 'pass',violations=violations),
        provider_health=dict(errors=row.get('errors'),requests=row.get('provider_requests'),
            rpc_latency_seconds=row.get('rpc_latency_seconds')),
        infrastructure_censoring=dict(classifications=classes,overlapping_counts=True,
            frozen_policy='profitability_protocol.json; prospective_acceptance._infra_fraction'),
        economic_admission='invalid' if failures else 'eligible_subject_to_frozen_block_gate',
        admission_failures=failures,last_valid_block=None,snapshot=native)

def audit(artifact,worktrees,output,previous=None):
    started=time.perf_counter();artifact=Path(artifact);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    result_paths=list(artifact.glob('certification-*/result.json'))
    if len(result_paths)!=1:raise ValueError('assurance_result_ambiguous')
    result=read(result_paths[0]);phase=result['phase'];runtime=result_paths[0].parent
    manifest=read(runtime/'manifest.json');native_root=artifact/'certification-native'/phase
    prev=read(previous) if previous else {};reports={};identity_failures=[]
    if manifest.get('integration_sha')!=result.get('integration_sha'):identity_failures.append('runtime_identity_mismatch')
    expected=read(Path(__file__).with_name('sources.json'))
    for lane in LANES:
        frozen=manifest['lanes'][lane]
        for key in ('policy_hash','strategy_version','source_sha'):
            if frozen.get(key)!=expected['lanes'][lane].get(key):identity_failures.append(lane+':'+key)
        source=Path(worktrees)/lane;native=native_root/lane
        cmd=[sys.executable,'-m','certification.decision_conformance','--lane',lane,
            '--source-root',str(source),'--trace',str(runtime/lane/'decision-trace.jsonl'),
            '--policy-hash',frozen['policy_hash'],'--runtime-sha',result['integration_sha'],
            '--output',str(output/(lane+'-conformance.json'))]
        replay=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
        conformance=read(output/(lane+'-conformance.json')) if (output/(lane+'-conformance.json')).exists() else dict(status='fail',failures=[dict(reason='replay_process_failed')])
        cmd=[sys.executable,str(Path(__file__).with_name('terminal_reconciliation.py')),
            '--lane',lane,'--root',str(native),'--source-root',str(source)]
        proof_result=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
        try:proof=json.loads(proof_result.stdout)
        except ValueError:proof=dict(verified=False,error='native_replay_unavailable')
        snapshot=native_positions(native,lane)
        reports[lane]=lane_report(lane,result['lanes'][lane],snapshot,conformance,
            pipeline(native),proof,result['ended_at'],((prev.get('lanes') or {}).get(lane) or {}).get('snapshot'))
        if lane=='meteora':
            breadth=meteora_source_coverage(runtime,native,source)
            detail=reports[lane];detail['source_coverage']=breadth
            detail['structurally_eligible_count']=None
            detail['observed_source_pair_count']=breadth['structurally_eligible_acquired_union_count']
            detail['raw_acquired_source_count']=breadth['raw_acquired_source_union_count']
            if not breadth['census_complete']:
                detail['coverage_gaps'].append('frozen_source_union_not_fully_observed')
                if detail['coverage_health']!='coverage_invalid':detail['coverage_health']='coverage_degraded'
            detail['coverage_gaps_by_segment'].extend(breadth['segments'])
    failures=identity_failures+[lane+':'+reason for lane,row in reports.items() for reason in row['admission_failures']]
    row=dict(schema='four-lane-market-assurance-v1',runtime_sha=result['integration_sha'],
        run_id=result.get('run_id'),phase=phase,started_at=result['started_at'],ended_at=result['ended_at'],
        operational_validity='invalid' if failures else 'valid',admission_failures=failures,lanes=reports,
        market_observation_validity={lane:r['coverage_health'] for lane,r in reports.items()},
        economic_performance=dict(eligible=not failures and phase=='hourly',
            reason='smoke_excluded' if phase!='hourly' else 'validity_gate',
            realized_and_unrealized_by_lane={lane:economic_marks(lane,r['accounting_reconciliation']) for lane,r in reports.items()},
            unrealized_aggregate=None,unlike_quote_units_summed=False),
        overhead=dict(elapsed_seconds=time.perf_counter()-started,provider_calls_added=0,
            execution='post_block_separate_process',native_databases_read_only=True),
        admission_policy='Existing frozen profitability gates plus evidence-integrity checks; no numerical breadth threshold added.')
    (output/'market-assurance.json').write_text(json.dumps(row,indent=2,sort_keys=True)+'\n')
    return row

def main():
    p=argparse.ArgumentParser();p.add_argument('--artifact',required=True);p.add_argument('--worktrees',required=True)
    p.add_argument('--output',required=True);p.add_argument('--previous');a=p.parse_args()
    row=audit(a.artifact,a.worktrees,a.output,a.previous)
    print(canonical(dict(operational_validity=row['operational_validity'],failures=row['admission_failures'],
        market_observation_validity=row['market_observation_validity'])))
    raise SystemExit(0 if row['operational_validity']=='valid' else 1)

if __name__=='__main__':main()
