"""Recover the digest-pinned failed smoke on a copy, preserving its original bytes.

No new entries, portfolio reset, fabricated exit, or prospective economic credit.
The full new-SHA certificate is required before market monitoring resumes.
"""
from __future__ import annotations
import argparse
from contextlib import chdir
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from certification.position_continuation import _atomic

AUTHORITY=Path(__file__).with_name('recovery_predecessor.json')

def _ro(path):return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
def hashes(path,table,columns):
    with _ro(path) as db:
        return [hashlib.sha256(json.dumps(row,separators=(',',':')).encode()).hexdigest()
                for row in db.execute('SELECT '+columns+' FROM '+table+' ORDER BY rowid')]

def acknowledge_pons(root,source):
    """Finish an already committed native cancel, never issue a new exit."""
    sys.path.insert(0,str(Path(source).resolve()))
    from robinhood_research.pons_selective_capital import CohortCapital
    from robinhood_research.pons_selective_paper import STRATEGY_CAPITAL_QUOTE,STRATEGY_NAMESPACE
    from robinhood_research.pons_selective_continuation import POLICY_HASH,EXIT_POLICY
    from robinhood_research.pons_selective_ledger import SelectivePaper
    from robinhood_research.evidence import Store
    root=Path(root).resolve();cohort=root/'pons-selective-continuation-v1-cohort'
    path=cohort/'pons-selective-cohort-capital.sqlite'
    before=hashes(path,'capital_journal','seq,id,action,body,hash');receipts=[]
    with chdir(root):
        guard=CohortCapital(path,STRATEGY_CAPITAL_QUOTE)
        with _ro(path) as db:rows=[json.loads(x[0]) for x in db.execute('SELECT body FROM capital_positions')]
        for row in rows:
            trial=cohort/Path(row['trial_path']).name
            native_before=hashes(trial,'records','category,id,body,hash')
            store=Store(trial,max_records=8192)
            try:
                paper=SelectivePaper(store,STRATEGY_NAMESPACE,STRATEGY_CAPITAL_QUOTE,
                    delay=EXIT_POLICY['entry_delay_seconds'],natural_policy_hash=POLICY_HASH)
                paper.positions();position=paper._get(row['id'])
                if (position['status']!='settled' or any(position.get(k)!=0 for k in
                    ('tokens','entry_tokens','cost','remaining_cost','reserved','realized_proceeds','pnl'))
                    or not paper.accounting(row['id'])['replay_verified']):
                    raise RuntimeError('recovery_requires_proven_unfilled_native_cancel')
                if row['status']=='reserved':
                    guard.observe(paper,position)
                    guard.settle(row['id'],position,at=position['last_at'])
                    receipts.append(dict(id=row['id'],action='acknowledge_existing_native_cancel',
                        effective_at=position['last_at'],recovered_at=time.time(),natural_entry=False))
                elif row['status']!='settled':raise RuntimeError('recovery_unknown_cohort_state')
            finally:store.close()
            if hashes(trial,'records','category,id,body,hash')!=native_before:
                raise RuntimeError('recovery_mutated_native_trial')
        rec=guard.reconcile()
    after=hashes(path,'capital_journal','seq,id,action,body,hash')
    if after[:len(before)]!=before:raise RuntimeError('recovery_mutated_cohort_history')
    if rec['reserved'] or rec['unsettled']:raise RuntimeError('recovery_pons_not_flat')
    return dict(verified=True,append_only=True,original_native_journals_unchanged=True,
        receipts=receipts,accounting=rec,natural_entries=0,natural_settlements=0)

def seed_ramses(root):
    """Only the pinned two-event reserve/open case permits reconstruction here."""
    root=Path(root);state_path=root/'robinhood-ramses-continuation.json'
    state=json.loads(state_path.read_text())
    if state.get('lifecycle_id'):return state
    campaign=root/'robinhood-ramses-extended-market.sqlite.campaign'
    paths=list(campaign.glob('0x*.sqlite'))
    if len(paths)!=1:raise RuntimeError('recovery_ramses_book_ambiguous')
    path=paths[0]
    with _ro(path) as db:
        genesis=json.loads(db.execute("SELECT body FROM ramses_strategy_meta WHERE id='genesis'").fetchone()[0])
        rows=[json.loads(x[0]) for x in db.execute('SELECT body FROM ramses_strategy_position')]
        events=[(action,json.loads(raw)) for action,raw in db.execute('SELECT action,body FROM ramses_strategy_journal ORDER BY seq')]
    if len(rows)!=1 or [x[0] for x in events]!=['reserve','open'] or rows[0]['status']!='open':
        raise RuntimeError('recovery_ramses_state_requires_explicit_review')
    position=rows[0]
    screen=json.loads(gzip.open(campaign/'initial-screen.json.gz','rt').read())
    selected=next(r for r in screen['rows'] if r['pool']==position['pool'])
    decision=selected['decision']
    if (decision['policy_hash']!=genesis['policy_hash'] or not decision['qualified'] or
            decision['freeze']['proposal_hash']!=position['proposal_hash'] or
            position['at']!=screen['finalized_timestamp'] or
            position['reserved']!=decision['freeze']['proposals'][0]['capital_employed']):
        raise RuntimeError('recovery_ramses_frozen_geometry_mismatch')
    state.update(active=True,lifecycle_id=position['id'],ledger_path=str(path),
        paper_capital=genesis['paper_capital'],quote_asset=genesis['quote_asset'],
        pool=position['pool'],decision=deepcopy(decision),costs=deepcopy(selected['gas_costs']),
        entry_at=position['at'],entry_block=screen['finalized_block'],segment_start=screen['finalized_block'],
        current_capital=position['reserved'],position_phase='deployed',segments=[],rebalances=0,
        recovery=dict(original_journal_events=2,original_proposal_hash=position['proposal_hash'],
            original_run_id=35921058163,no_new_entry=True,economic_sample_eligible=False))
    _atomic(state_path,state);return state

def prepare(api,state_dir,worktrees,certificate_run_id,state_run_id=None):
    from certification.prospective_program import certificate
    from certification.run import git
    state_dir=Path(state_dir);source=json.loads(AUTHORITY.read_text());sha=git('rev-parse','HEAD')
    cert=certificate(api,certificate_run_id,sha,worktrees)
    state_run_id=int(state_run_id or source['run_id'])
    checkpoint=source.get('reviewed_recovery_checkpoint') or {}
    reviewed_checkpoint=state_run_id==checkpoint.get('run_id')
    if state_run_id==source['run_id']:
        # A superseded candidate may finish certification while its replacement
        # is being prepared. Never fork an already-started recovery from genesis.
        for previous in source.get('superseded_candidate_runs',[]):
            jobs=api.pages(f'actions/runs/{previous}/jobs','jobs')
            if any(j['name'].startswith('recover-preserved-position') and
                   j['status']!='queued' and j.get('conclusion') not in ('skipped','cancelled')
                   for j in jobs):
                raise RuntimeError('predecessor_recovery_already_started_preserve_existing_chain')
        archive,item=api.artifact(source['run_id'],source['artifact_name'])
        if item['id']!=source['artifact_id'] or item['digest']!=source['artifact_digest']:
            raise RuntimeError('recovery_predecessor_artifact_identity')
    elif reviewed_checkpoint:
        prior=api.request('GET',f'actions/runs/{state_run_id}')
        if (prior.get('head_sha')!=checkpoint['integration_sha'] or
                prior.get('status')!='completed' or prior.get('conclusion')!=checkpoint['conclusion']):
            raise RuntimeError('recovery_reviewed_checkpoint_not_stopped')
        archive,item=api.artifact(state_run_id,checkpoint['artifact_name'])
        if item['id']!=checkpoint['artifact_id'] or item['digest']!=checkpoint['artifact_digest']:
            raise RuntimeError('recovery_reviewed_checkpoint_artifact_identity')
    else:
        prior=api.request('GET',f'actions/runs/{state_run_id}')
        if prior['head_sha']!=sha:raise RuntimeError('recovery_chain_runtime_mismatch')
        archive,item=api.artifact(state_run_id,f'position-continuation-ramses-{state_run_id}-{prior["run_attempt"]}')
    if state_dir.exists() and any(state_dir.iterdir()):raise RuntimeError('recovery_destination_not_empty')
    state_dir.mkdir(parents=True,exist_ok=True)
    for member in archive.infolist():
        p=Path(member.filename)
        if p.is_absolute() or '..' in p.parts:raise RuntimeError('recovery_unsafe_archive')
    archive.extractall(state_dir)
    # Immutable receipt of the digest verified before any copied book changes.
    bridge_path=state_dir/'engineering-recovery-authorization.json'
    if state_run_id==source['run_id'] or reviewed_checkpoint:
        if reviewed_checkpoint:
            previous=json.loads(bridge_path.read_text())
            if (any(previous.get(k)!=source.get(k) for k in
                    ('run_id','integration_sha','implementation_hash','artifact_id','artifact_digest'))
                    or previous.get('recovery_sha')!=checkpoint['integration_sha']
                    or previous.get('certificate_run_id')!=checkpoint['certificate_run_id']):
                raise RuntimeError('recovery_reviewed_checkpoint_authority_mismatch')
            history=state_dir/'engineering-recovery-history';history.mkdir(exist_ok=True)
            _atomic(history/(str(state_run_id)+'-authorization.json'),previous)
        bridge=dict(source,certificate_run_id=int(certificate_run_id),recovery_sha=sha,
            full_exact_sha_certificate=cert,prepared_at=time.time())
        _atomic(bridge_path,bridge)
    else:
        bridge=json.loads(bridge_path.read_text())
        if bridge['recovery_sha']!=sha or bridge['certificate_run_id']!=int(certificate_run_id):
            raise RuntimeError('recovery_chain_authority_mismatch')
    with (state_dir/'recovery-artifact-chain.jsonl').open('a') as f:
        f.write(json.dumps(dict(run_id=state_run_id,artifact_id=item['id'],digest=item['digest'],restored_at=time.time()),sort_keys=True)+'\n')
    return bridge

def run(state_dir,worktrees,slice_seconds):
    root=Path(state_dir).resolve();native=root/'certification-native/smoke'
    bridge=json.loads((root/'engineering-recovery-authorization.json').read_text())
    pons_receipt=root/'pons-reserve-recovery.json'
    if not pons_receipt.exists():
        child=subprocess.run([sys.executable,'-m','certification.preserved_position_recovery','pons',
            '--state-dir',str(root),'--worktrees',str(worktrees)],capture_output=True,text=True,check=True)
    seed_ramses(native/'ramses')
    os.environ['MM_CONTINUATION_LANE_ROOT']=str(Path(worktrees).resolve()/'ramses')
    trace_root=root/'recovery-decisions'/str(time.time_ns());trace_root.mkdir(parents=True)
    # The subprocess installs the same trace hooks and preserves before/after
    # native prefixes. Only this existing position may advance.
    subprocess.run([sys.executable,'-m','certification.position_continuation',
        '--lane','ramses','--state-dir',str(root),'--slice-seconds',str(slice_seconds),
        '--output',str(root/'position-continuation-result.json'),
        '--audit-output',str(trace_root)],check=True)
    result=json.loads((root/'position-continuation-result.json').read_text())
    outcome=dict(schema='preserved-position-recovery-v1',economic_sample_eligible=False,
        predecessor=bridge,pons=json.loads(pons_receipt.read_text()),ramses=result,
        handoff_required=result.get('handoff_required') is True,
        verified_flat=result.get('terminal_replay_verified') is True and result.get('handoff_required') is False)
    proofs={}
    for lane in ('pump','pons','meteora','ramses'):
        command=[sys.executable,str(Path(__file__).with_name('terminal_reconciliation.py')),
            '--lane',lane,'--root',str(native/lane),'--source-root',str(Path(worktrees).resolve()/lane)]
        check=subprocess.run(command,capture_output=True,text=True,timeout=120)
        proofs[lane]=json.loads(check.stdout)
    outcome['native_proofs']=proofs
    outcome['verified_flat']=outcome['verified_flat'] and all(p.get('verified') is True and p.get('open_positions')==0 for p in proofs.values())
    _atomic(root/'preserved-position-recovery.json',outcome)
    return outcome

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('prepare','run','pons'))
    p.add_argument('--state-dir',required=True);p.add_argument('--worktrees',required=True)
    p.add_argument('--certificate-run-id');p.add_argument('--state-run-id');p.add_argument('--slice-seconds',type=int,default=3000);a=p.parse_args()
    if a.command=='prepare':
        from certification.prospective_program import GitHub
        row=prepare(GitHub(),a.state_dir,a.worktrees,a.certificate_run_id,a.state_run_id)
    elif a.command=='pons':
        row=acknowledge_pons(Path(a.state_dir)/'certification-native/smoke/pons',Path(a.worktrees)/'pons')
        _atomic(Path(a.state_dir)/'pons-reserve-recovery.json',row)
    else:row=run(a.state_dir,a.worktrees,a.slice_seconds)
    print(json.dumps({k:row.get(k) for k in ('verified','verified_flat','handoff_required','economic_sample_eligible')},sort_keys=True))

if __name__=='__main__':main()
