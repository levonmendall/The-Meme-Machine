"""Durable structural trigger waits; waiting does not occupy a warming worker.

Only observation scheduling lives here. Native compatibility, the 120-second
trigger window, the exact warmup and strategy qualification remain authoritative.
"""
from contextlib import closing
import json,time
from .candidate_history import CandidateHistory
from .journal import canonical,digest

class WarmingDeferred(RuntimeError):
    pass

def install(module):
    """Attach observation scheduling without editing native strategy functions."""
    if getattr(module,'_structural_warming_attached',False):return
    original_fresh=getattr(module,'_fresh_supported_start',None)
    if original_fresh is None:return
    module._structural_warming_attached=True
    install_checkpoints(module.dlmm.Adapter)
    original_rotate=module._rotate
    original_trigger=module._await_fresh_swap_trigger
    def fresh(adapter,candidate):
        if candidate.get('provider_structural'):
            import os
            from meme_machine.solana_prewarm_startup import candidate_release
            if not candidate_release(os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB')):
                raise module.Unavailable('rolling_publication_pending')
        if candidate.get('decision_deadline') is not None:
            adapter.rpc.evidence_deadline=float(candidate['decision_deadline'])
            adapter.rpc.evidence_priority=4
        if not candidate.get('provider_structural'):return original_fresh(adapter,candidate)
        now=int(module.time.time());checkpoint=None
        import os
        if os.environ.get('MM_SOLANA_CANDIDATE_HISTORY_DB'):
            with closing(CandidateHistory()) as shared:
                checkpoint=shared.latest_checkpoint('program:meteora',candidate['address'],as_of=now,
                    maximum_age=module.dlmm.MAX_AGE)
        if checkpoint:
            # Current exact state still comes from a NEW finalized account
            # context. Only immutable address discovery is reused.
            try:snap=adapter.snapshot_from_state(checkpoint['state'],now,True,fresh=True)
            except (ValueError,module.Unavailable):snap=adapter.snapshot(candidate['address'],now,True,fresh=True)
        else:snap=adapter.snapshot(candidate['address'],now,True,fresh=True)
        state=module.dlmm.validate(snap,snap['available_time'],'real')
        if (state['x']==module.dlmm.WSOL)==(state['y']==module.dlmm.WSOL):
            raise ValueError('dlmm_structural_wsol_pair_scope')
        candidate.update(token_x=state['x'],token_y=state['y'],volume_acceleration=0.,fee_acceleration=0.)
        module.dlmm.scout(snap,snap['available_time'],dict(pool=candidate['address'],x=state['x'],y=state['y']))
        return state
    def rotate(adapter,pacer,rpcs):
        result=original_rotate(adapter,pacer,rpcs)
        source_rpc=getattr(adapter,'rpc',None);result_rpc=getattr(result,'rpc',None)
        for key in ('evidence_deadline','evidence_priority'):
            if result_rpc is not None and hasattr(source_rpc,key):setattr(result_rpc,key,getattr(source_rpc,key))
        return result
    def await_trigger(adapter,candidate,baseline,policy,pacer,rpcs,deadline=None,broker=None):
        if candidate.get('provider_structural') and candidate.get('_candidate_work_id'):
            return trigger(module,adapter,candidate,baseline,policy,pacer,rpcs,deadline)
        return original_trigger(adapter,candidate,baseline,policy,pacer,rpcs,deadline,broker)
    module._fresh_supported_start=fresh
    module._rotate=rotate
    module._await_fresh_swap_trigger=await_trigger

def install_checkpoints(adapter_class):
    """Use existing authoritative endpoint reads; add zero provider calls.

    Boundaries are the existing fresh compatibility/one-second interval reads,
    not an arbitrary timer. Full state is validated before durable publication.
    It can anchor later deltas but can never prove a missing delta interval.
    """
    if getattr(adapter_class,'_rolling_checkpoints_attached',False):return
    adapter_class._rolling_checkpoints_attached=True
    def attach(method):
        def capture(self,*args,**kwargs):
            snapshot=method(self,*args,**kwargs)
            import os
            if os.environ.get('MM_SOLANA_CANDIDATE_HISTORY_DB'):
                with closing(CandidateHistory()) as history:
                    frontier=0
                    from pathlib import Path
                    import sqlite3
                    path=os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB')
                    if path and Path(path).exists():
                        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
                            if db.execute("SELECT 1 FROM sqlite_master WHERE name='candidate_checkpoints'").fetchone():
                                scopes=['candidate:meteora:'+snapshot['pool']]
                                if db.execute("SELECT 1 FROM sqlite_master WHERE name='rolling_group_members'").fetchone():
                                    scopes.extend(s for s, in db.execute("SELECT scope FROM rolling_group_members WHERE family='meteora' AND address=?",(snapshot['pool'],)))
                                row=db.execute('SELECT MAX(slot) FROM candidate_checkpoints WHERE scope IN ('+','.join('?' for _ in scopes)+') AND slot<=? AND updated<=?',(*scopes,snapshot['slot'],snapshot['available_time'])).fetchone()
                                frontier=0 if not row or row[0] is None else row[0]
                    history.checkpoint('program:meteora',snapshot['pool'],snapshot,
                        proof=digest(snapshot),frontier=frontier)
            return snapshot
        return capture
    adapter_class.snapshot=attach(adapter_class.snapshot)
    adapter_class.snapshot_from_state=attach(adapter_class.snapshot_from_state)

def _store(history):
    history.db.execute('''CREATE TABLE IF NOT EXISTS evidence_progress(
        work_id TEXT PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL)''')

def load(work_id):
    with closing(CandidateHistory()) as history:
        _store(history);row=history.db.execute('SELECT body,hash FROM evidence_progress WHERE work_id=?',(work_id,)).fetchone()
        if row is None:return None
        result=json.loads(row[0])
        if digest(result)!=row[1]:raise ValueError('candidate_evidence_progress_corrupt')
        return result

def save(work_id,value):
    with closing(CandidateHistory()) as history:
        _store(history)
        with history.transaction():
            if history.db.execute('SELECT 1 FROM work WHERE id=?',(work_id,)).fetchone() is None:
                raise ValueError('candidate_evidence_work_unknown')
            history.db.execute('INSERT OR REPLACE INTO evidence_progress VALUES(?,?,?)',(work_id,canonical(value),digest(value)))

def defer(work_id,*,scope=None,lower=None,upper=None,retry_at=None):
    with closing(CandidateHistory()) as history:
        if scope is not None and lower is not None and upper is not None and lower<=upper:
            history.wait_for_history(work_id,scope,lower,upper,retry_at=retry_at,
                reason='authenticated_trigger_history_unsealed')
        else:
            history.complete(work_id,status='deferred',details=dict(reason='authenticated_trigger_pending',delay_seconds=.25,deadline_reset=False))
    raise WarmingDeferred('candidate_trigger_wait')

def compatibility(module,adapter,candidate):
    work_id=candidate.get('_candidate_work_id')
    if not (candidate.get('provider_structural') and work_id):
        return module._fresh_supported_start(adapter,candidate)
    progress=load(work_id)
    if progress is not None:
        state=progress['baseline'];candidate.update(token_x=state['x'],token_y=state['y'],volume_acceleration=0.,fee_acceleration=0.)
        adapter.rpc.evidence_deadline=float(candidate['decision_deadline']);adapter.rpc.evidence_priority=4
        return state
    state=module._fresh_supported_start(adapter,candidate)
    save(work_id,dict(baseline=state,started=time.time(),cursor=state['slot']))
    return state

def trigger(module,adapter,candidate,baseline,policy,pacer,rpcs,deadline):
    work_id=candidate['_candidate_work_id'];progress=load(work_id)
    if progress is None:
        progress=dict(baseline=baseline,started=time.time(),cursor=baseline['slot']);save(work_id,progress)
    elapsed=max(0.,time.time()-progress['started'])
    def terminal(reason):
        return dict(triggered=False,reason=reason,waited_seconds=elapsed,baseline_slot=baseline['slot']),None,adapter,dict(candidate)
    if module._runtime_expired(deadline):return terminal('experiment_runtime_deadline')
    if elapsed>=module.FRESH_SWAP_TRIGGER_MAX_SECONDS:return terminal('fresh_swap_trigger_timeout')
    try:swaps,metadata=module._new_finalized_swaps(adapter.rpc,candidate['address'],progress['cursor'])
    except Exception as exc:
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        if isinstance(exc,EvidenceUnavailable) and str(exc) in ('unresolved_evidence_gap','evidence_cold_start','evidence_finalized_stale','evidence_discontinuous','candidate_binding_required'):
            plane=module._evidence_plane() if hasattr(module,'_evidence_plane') else None
            try:head=None if plane is None else plane.frontier('program:meteora')
            except EvidenceUnavailable:head=None
            defer(work_id,scope=None if head is None else 'candidate:meteora:'+candidate['address'],
                lower=progress['cursor']+1,upper=head,retry_at=progress['started']+module.FRESH_SWAP_TRIGGER_MAX_SECONDS)
        raise
    if not swaps:
        progress['cursor']=max(progress['cursor'],int(metadata.get('head_slot') or progress['cursor']))
        save(work_id,progress);defer(work_id)
    observed=swaps[0]
    post,adapter=module._retry_rate_limited_operation(lambda active:module._fresh_supported_start(active,candidate),adapter,pacer,rpcs,deadline)
    if post['slot']<observed['slot']:defer(work_id)
    observed.update(triggered=True,reason='authenticated_fresh_swap',waited_seconds=elapsed,
        baseline_slot=baseline['slot'],post_trigger_slot=post['slot'])
    return observed,post,adapter,dict(candidate)
