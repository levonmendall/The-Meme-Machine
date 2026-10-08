"""Finite admission and autonomous native maintenance in the existing service.

This is a lifecycle state machine, not another manager. Economic state belongs
to the unchanged native journals and shared authority. Resource configuration
does not grant operational permission; the owner authorizes the service start.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time

from .bounded_provider import LIMITS
from meme_machine.shared_capital.model import CapitalError, FAMILIES

HOLD_SECONDS=72*60*60
BRIDGE_SECONDS=36*60*60
EXIT_RECOVERY_SECONDS=3600
SHUTDOWN_SECONDS=65
TOTAL_SECONDS=1200+HOLD_SECONDS+EXIT_RECOVERY_SECONDS+SHUTDOWN_SECONDS
PHASES=('BOOTSTRAP','CONTINUATION','RECOVERY','FAULT','FLAT')


def validate_envelope(row):
    """Explicit finite operational allowances, never provider account quotas."""
    if row.get('schema')!='paper-position-continuation-resources-v1':
        raise CapitalError('explicit_continuation_resource_envelope_required')
    if row.get('maximum_seconds')!=TOTAL_SECONDS or row.get('recovery_seconds')!=EXIT_RECOVERY_SECONDS:
        raise CapitalError('original_hold_and_bounded_exit_recovery_required')
    for phase in ('continuation','recovery'):
        limits=row.get(phase,{})
        if set(limits)!=set(LIMITS)|{'http_bytes'} or any(type(v) is not int or v<=0 for v in limits.values()):
            raise CapitalError('complete_finite_continuation_resource_limits_required')
        if (limits['native_stop_bytes']+limits['native_inflight_bytes']>limits['native_bytes']
                or limits['native_inflight_bytes']<6*16*1024**2):
            raise CapitalError('continuation_native_shutdown_reserve_required')
    if (row.get('maximum_queue_depth')!=64 or row.get('maximum_queue_wait_seconds')!=5
            or row.get('maximum_rss_bytes')!=6*1024**3 or row.get('maximum_cpu_cores')!='1.8'
            or row.get('maximum_reconnects')!=32):
        raise CapitalError('continuation_existing_Droplet_and_latency_envelope_required')
    for phase in ('continuation','recovery'):
        from decimal import Decimal
        value=row.get(phase+'_modeled_spend_usd')
        if not isinstance(value,str) or not Decimal(value).is_finite() or Decimal(value)<=0:
            raise CapitalError('explicit_continuation_modeled_spend_required')
    return row


def load_envelope(path=None):
    path=path or os.environ.get('MM_POSITION_CONTINUATION_ENVELOPE')
    if not path:raise CapitalError('separately_authorized_continuation_envelope_missing')
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>16384:
        raise CapitalError('continuation_resource_configuration_bound')
    return validate_envelope(json.loads(path.read_text()))


def position_only(*,path=None,now=None):
    """All existing workers share this durable work fence, also after restart.

    No run ledger means ordinary separately authorized operational behavior.
    An unreadable finite-run ledger can never resume expensive discovery.
    """
    path=path or os.environ.get('MM_BOUNDED_PROVIDER_DB')
    if not path:return False
    try:
        with closing(sqlite3.connect(Path(path).absolute().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            rows=dict(db.execute("SELECT key,value FROM run WHERE key IN ('phase','started_wall','work_mode')"))
        return (rows.get('work_mode')=='POSITION_ONLY' or rows.get('phase','BOOTSTRAP')!='BOOTSTRAP'
            or (time.time() if now is None else now)>=float(rows['started_wall'])+1200)
    except (OSError,sqlite3.Error,KeyError,ValueError):return True


def outstanding(state):
    return (any(p['status']=='OPEN' for p in state['positions'].values())
        or any(state.get(k) for k in ('reservations','commitments','obligations','pending_deliveries',
            'runtime_pending','runtime_inbox')))


def position_lanes(state):
    lanes={FAMILIES[p['regime']] for p in state['positions'].values() if p['status']=='OPEN'}
    for name in ('reservations','commitments','obligations'):
        lanes.update(FAMILIES[p['regime']] for p in state.get(name,{}).values())
    for name in ('pending_deliveries','runtime_pending'):
        values=state.get(name,{})
        lanes.update(p['lane'] for p in (values.values() if isinstance(values,dict) else values))
    # A request can still require native verified-absence cancellation/delivery.
    lanes.update(FAMILIES[p['regime']] for p in state.get('runtime_inbox',{}).values())
    return tuple(lane for lane in ('pump','pons') if lane in lanes)


def readiness(health,portfolio,rss,envelope):
    """Fresh native recovery, execution wiring and evidence, not a heartbeat flag."""
    if rss>=envelope['maximum_rss_bytes']:raise ValueError('continuation_memory_limit')
    resources=health.get('continuation_resources') or {}
    if resources.get('limits_verified') is not True:
        raise ValueError('continuation_existing_service_resource_limits_unavailable')
    if resources.get('cgroup_memory_bytes',envelope['maximum_rss_bytes'])>=envelope['maximum_rss_bytes']:
        raise ValueError('continuation_memory_limit')
    if not portfolio.get('reconciliation',{}).get('checks') or not all(
            value is True for value in portfolio['reconciliation']['checks'].values()):
        raise ValueError('continuation_reconciliation_unavailable')
    for lane in ('pump','pons'):
        row=health['lanes'][lane]
        proof=row.get('native_continuation',{})
        if (not row.get('reconciled') or row.get('exit_code') is not None
                or not all(proof.get(key) is True for key in
                    ('current_restored','survivor_replay_verified','survivor_handoff_ready','exit_path_bound'))):
            raise ValueError(lane+'_native_continuation_not_ready')
    for provider in ('solana','robinhood'):
        row=health['providers'].get(provider,{})
        if (row.get('state')!='CURRENT' or row['queue_depth']>envelope['maximum_queue_depth']
                or row['oldest_wait_seconds']>envelope['maximum_queue_wait_seconds']):
            raise ValueError(provider+'_continuation_provider_not_ready')
    evidence=health['providers']['evidence']
    if evidence.get('startup_released') is not True or evidence.get('phase')!='ACTIVE':
        raise ValueError('continuation_subscription_or_coverage_not_ready')
    return dict(native_managers=True,native_recovery=True,exit_paths=True,
        authenticated_evidence=True,reconciliation=True,provider_governors=True)


def addition_rejection(book,identity,reason,at):
    """A denied add is durable diagnostic state, never an economic event."""
    book.checkpoint_runtime(identity,'continuation-addition-rejection',
        dict(reason=reason,at=int(at),exposure_increased=False),claim=True)


def cancel_unfilled(book,sleeve,history,row,now):
    """Cancel a proved unfilled reservation; an open native lot is untouched."""
    if not position_only():return False
    identity=row['position']
    native=book.db.execute('SELECT body FROM positions WHERE id=?',(identity,)).fetchone()
    position=json.loads(native[0]) if native else None
    if position and position['status']!='reserved':return False
    proof=book.replay()
    if proof.get('verified') is not True:raise ValueError('native_replay_required')
    from meme_machine.runtime.journal import digest
    if position:
        book.transition(identity,'cancelled',max(now,position['last_at']),
            evidence=dict(reason='bootstrap_funding_closed_before_native_fill'))
        position=book._load(identity)
    else:
        native_ids={key for key, in book.db.execute('SELECT id FROM positions')}
        if hasattr(sleeve,'recover_unmaterialized'):
            sleeve.recover_unmaterialized(native_ids,strategy=book.identity['lane'],verified=True)
    held=sleeve.get(identity)
    if held and held['held']:
        if held['status']!='reserved':raise ValueError('unfilled_native_and_sleeve_state_conflict')
        sleeve.release(identity,pnl=0,at=max(now,held['at']),terminal_hash=digest(position or proof),
            native_verified=True,cancelled=True)
    row.update(position=None,state='qualified_but_capital_unavailable')
    row['continuation_rejection']=dict(reason='funding_closed',at=now,exposure_increased=False)
    history.save(row)
    return True


def pons_current_safety(path):
    """Read the existing verified native-observation projection, without RPC."""
    if not position_only():return []
    try:
        with closing(sqlite3.connect(Path(path).absolute().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            rows=[json.loads(raw) for raw, in db.execute("SELECT body FROM capital_positions WHERE json_extract(body,'$.status')!='settled' LIMIT 32")]
        return [dict(identity=row['id'],at=(row.get('native_position') or {}).get('last_at',0),
            evidence_current=0<=time.time()-(row.get('native_position') or {}).get('last_at',0)<=15,
            blocker='pons_current_authenticated_mark_or_exit_not_current') for row in rows]
    except (OSError,sqlite3.Error,ValueError):
        return [dict(at=0,evidence_current=False,blocker='pons_current_native_observation_unavailable')]


def close_bootstrap(supervisor,reason,*,phase='CONTINUATION'):
    budget=supervisor.provider_budget
    budget.bootstrap.change(reason=reason,check=False)
    budget.set_phase(phase,reason)
    state=supervisor.shared_capital.ledger();scope=state['runtime_admission']
    supervisor.shared_capital.command('continuation:'+supervisor.run_id+':'+phase,
        'runtime_admission',dict(scope,mode='CONTINUATION',phase=phase),int(time.time()))
    supervisor.admission='CONTINUATION'


def tick(supervisor):
    """Do not stop native owners because an admission clock or quota expired."""
    budget=supervisor.provider_budget;state=supervisor.shared_capital.ledger()
    budget.reap_orphans()
    scope=state['runtime_admission'];now=int(time.time())
    if (supervisor.admission=='BOOTSTRAP' and
            (now>=scope['stop_at']-SHUTDOWN_SECONDS or budget.bootstrap.snapshot()['reason'])):
        close_bootstrap(supervisor,'bootstrap_completed_or_closed')
        state=supervisor.shared_capital.ledger()
    if position_only(path=budget.path,now=now):
        budget.position_work_only()
        needed=set(position_lanes(state))
        health=getattr(supervisor,'last_native_health',{})
        # A shared terminal event can precede native callback/delivery. Keep
        # that native owner until its actual book/worker proves flat as well.
        for lane in supervisor.processes:
            proof=health.get(lane,{}).get('native_continuation',{})
            if proof.get('flat') is not True:needed.add(lane)
        supervisor.continuation_lanes=tuple(lane for lane in ('pump','pons') if lane in needed)
    # Only a proved flat native/shared state can finish this temporary operation.
    # Parent publication does not manufacture reconciliation or a native exit.
    if supervisor.admission=='CONTINUATION' and not outstanding(state):
        health=getattr(supervisor,'last_native_health',{})
        required=tuple(supervisor.processes)
        if all(health.get(lane,{}).get('reconciled') is True and
                health[lane].get('native_continuation',{}).get('flat') is True for lane in required):
            supervisor.shared_capital.verify_replay()
            budget.set_phase('FLAT','all_positions_exited_and_reconciled')
            supervisor.stop_requested=True
    if outstanding(state):
        # Hard service deadlines are absolute, not renewed per systemd restart.
        # Native 72h/36h clocks still evaluate at their original economic times.
        if now>=scope['started_at']+TOTAL_SECONDS-SHUTDOWN_SECONDS:
            budget.set_phase('FAULT','original_continuation_and_exit_recovery_deadline_exhausted')
        elif now>=scope['funding_until']+HOLD_SECONDS and budget.phase() not in ('RECOVERY','FAULT'):
            budget.set_phase('RECOVERY','original_maximum_hold_expired_exit_or_reconciliation_pending')
        if budget.phase()=='RECOVERY':
            from .bounded_provider import Budget
            recovery=Budget(budget.path,phase='recovery')
            if recovery.expired(recovery.snapshot()):
                budget.set_phase('FAULT','bounded_exit_or_resource_recovery_exhausted')
    phase=budget.phase()
    if phase in ('RECOVERY','FAULT') and supervisor.admission!='CONTINUATION':
        close_bootstrap(supervisor,'provider_resource_or_recovery_fault',phase=phase)
    if phase=='FAULT':
        # Keep a durable, actionable local fault and the independent existing
        # monitor. No paid polling or automatic fresh allowance on restart.
        supervisor.continuation_fault=budget.fault()
        supervisor.stop_requested=True


def provider_failure(supervisor,reason):
    """One incident deadline, durable across restart; healthy recovery clears it.

    Ordinary reconnects retain the same manager and remaining allowances. This
    is not an exit signal and does not mark stale evidence as usable.
    """
    budget=supervisor.provider_budget;now=int(time.time())
    if supervisor.admission=='BOOTSTRAP':close_bootstrap(supervisor,reason)
    with closing(budget.bootstrap.db()) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT value FROM run WHERE key='provider_degraded_at'").fetchone()
        at=int(row[0]) if row else now
        db.execute('INSERT OR IGNORE INTO run VALUES(?,?)',('provider_degraded_at',str(at)))
        detail=dict(phase='DEGRADED',reason=reason,at=at,deadline=at+EXIT_RECOVERY_SECONDS,
            funding_closed=True,protected=False,action='restore_authenticated_market_evidence_and_exit_connectivity')
        db.execute('INSERT INTO run VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            ('provider_fault',json.dumps(detail)))
        db.execute('COMMIT')
    if now>=at+EXIT_RECOVERY_SECONDS:budget.set_phase('FAULT','provider_recovery_deadline_exhausted:'+reason)


def provider_recovered(supervisor):
    with closing(supervisor.provider_budget.bootstrap.db()) as db:
        db.execute("DELETE FROM run WHERE key IN ('provider_degraded_at','provider_fault')")
