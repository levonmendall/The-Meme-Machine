"""Bounded, read-only candidate reconciliation; raw overlapping history stays intact."""
from collections import Counter
import json
import re
from pathlib import Path
import sqlite3

STATES = ('structural_exclusion','valid_early_rejection','evidence_not_required',
    'evidence_required','evidence_completed','provider_failure','queue_deadline_failure',
    'genuine_reconstruction_incomplete','stale_evidence','capital_occupied',
    'qualified_not_entered','entry_reserved','entry_cancelled','entry_filled',
    'settled','open_continuing','authenticated_trigger_awaiting_evidence',
    'pre_admission_evidence_incomplete','observed')


def transition(state, stage, reason, classification, details):
    state=dict(state)
    reason=str(reason or '')
    if stage in ('evidence_required','evidence_requested','full_evidence_requested','warmup_started'):
        state['required']=True
        state['evidence']='evidence_required'
    if stage in ('evidence_complete','economic_vector','full_evidence_complete'):
        state['required']=True
        state['evidence']='evidence_completed'
    if stage=='evidence_not_required' and not state.get('required'):
        state['evidence']='evidence_not_required'
    direct={'qualified':'qualified_not_entered','entry_reserved':'entry_reserved',
        'entry_cancelled':'entry_cancelled','entry_filled':'entry_filled','settled':'settled',
        'deployed':'open_continuing',
        'trigger_authenticated':'authenticated_trigger_awaiting_evidence',
        'evidence_required':'evidence_required','evidence_complete':'evidence_completed',
        'economic_vector':'evidence_completed','evidence_not_required':'evidence_not_required'}
    status=direct.get(stage)
    if reason=='paper_capital_occupied':status='capital_occupied'
    elif classification=='structural_ineligible':status='structural_exclusion'
    elif classification=='strategy_rejection' and stage not in ('entry_cancelled','settled'):
        status='valid_early_rejection'
    elif classification in ('provider_failed','provider_failure'):status='provider_failure'
    elif classification in ('consumer_deadline','capacity_censored','local_budget_exhausted'):
        status='queue_deadline_failure'
    elif classification and classification.startswith('stale'):status='stale_evidence'
    elif classification=='pre_admission_evidence_incomplete':status=classification
    elif classification=='reconstruction_incomplete':status='genuine_reconstruction_incomplete'
    # Economic lifecycle stages carry stronger evidence than a generic reason mapper.
    if stage in ('entry_reserved','entry_cancelled','entry_filled','settled','deployed'):
        status=direct[stage]
    if stage in ('entry_reserved','entry_cancelled','entry_filled','settled','deployed'):
        state['lifecycle_status']=status
    if stage=='forward_observation' and state.get('lifecycle_status') in ('entry_filled','open_continuing'):
        state['lifecycle_status']='open_continuing'
        status='open_continuing'
    if classification=='reconstruction_incomplete':
        state['evidence']='evidence_required' if state.get('required') else state['evidence']
    if status:state['status']=state.get('lifecycle_status',status)
    state['last_stage']=stage
    state['last_reason']=reason[:200]
    return state


def reconcile(path, *, rows_path=None, native_states=None, max_rows=10000):
    """Stream one candidate at a time using SQLite disk sort; constant Python memory.

    Trigger sub-identities are excluded; their parent candidate's own stages remain.
    Evidence obligation is a separate axis, so capital occupancy cannot imply that
    earlier required evidence was successfully acquired.
    """
    counts=Counter();evidence=Counter();total=0
    native_states=native_states or {}
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-2048')
    output=Path(rows_path).open('w') if rows_path else None
    def emit(candidate,state):
        nonlocal total
        if candidate is None:return
        if candidate in native_states:
            state=dict(state,status=native_states[candidate],native_lifecycle_reconciled=True)
        total+=1;counts[state['status']]+=1;evidence[state['evidence']]+=1
        if output and total<=max_rows:output.write(json.dumps(dict(candidate=candidate,**state),sort_keys=True)+'\n')
    candidate=None;state=None
    try:
        for c,s,r,k,raw in db.execute('SELECT candidate,stage,reason,classification,details FROM progress '
                "WHERE stage NOT IN ('trigger_started','trigger_terminal') ORDER BY candidate,sequence"):
            if c!=candidate:
                emit(candidate,state);candidate=c
                state=dict(status='observed',evidence='not_yet_required',required=False)
            details=json.loads(raw)
            state=transition(state,s,r,k,details)
        emit(candidate,state)
    finally:
        db.close()
        if output:output.close()
    return dict(schema='candidate-causal-summary-v1',candidates=total,
        terminal_counts={key:counts[key] for key in STATES},
        candidate_rows_written=min(total,max_rows) if output else 0,
        candidate_rows_omitted=max(0,total-max_rows) if output else 0,
        evidence_obligation_counts=dict(evidence),
        reconciled=sum(counts.values())==total,
        interpretation='One latest status per native candidate; evidence obligations are a separate axis, not additional losses.',
        historical_records_modified=False)


def native_states(lane, report, pipeline_path):
    """Join actual native lifecycle outcomes, never infer fills from qualification."""
    result={}
    if not isinstance(report,dict):return result
    if lane=='pump':
        for row in report.get('qualifiers',[]):
            status={'cancelled':'entry_cancelled','reserved':'entry_reserved','filled':'entry_filled'}.get(row.get('entry_status'))
            if status:result[row['mint']]=status
    elif lane=='pons':
        qualifiers={row.get('index'):row for row in report.get('qualifiers',[])}
        db=sqlite3.connect(Path(pipeline_path).resolve().as_uri()+'?mode=ro',uri=True)
        try:
            for row in report.get('lifecycles',[]):
                q=qualifiers.get(row.get('index'),{})
                tx=q.get('source_transaction')
                if not tx:
                    tail=str(row.get('lifecycle_id','')).rsplit(':',1)[-1]
                    if re.fullmatch(r'0x[0-9a-fA-F]{64}',tail):tx=tail
                if not tx:continue
                candidates=db.execute("SELECT DISTINCT candidate FROM progress WHERE stage='qualified' AND candidate LIKE ?",(tx+':%',)).fetchall()
                if len(candidates)!=1:continue
                status=('entry_cancelled' if row.get('entry_failure') or row.get('status')=='entry_failed' else
                        'settled' if row.get('status')=='settled' else None)
                if status:result[candidates[0][0]]=status
        finally:db.close()
    elif lane=='ramses':
        for row in report.get('natural_lifecycles',[]):
            if row.get('pool') and row.get('status')=='settled':result[row['pool']]='settled'
    return result
