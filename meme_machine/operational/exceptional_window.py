"""Inactive candidate deadlines in the SAME usage DB and service supervisor.

No new economic maximum or default activation. Initial finite configuration can
extend the operating wall only; allowances, consumption, run/funding clocks,
incident clocks and economic state remain unchanged. Restarts read the same row.
"""
from contextlib import closing
import json
import time

from . import position_continuation as native

KEY='exceptional_operational_window'


def systemd_dropin(window):
    """Reviewable candidate text for the EXISTING unit; never writes or reloads it."""
    duration=window['recovery_until']-window['started_at']
    if type(duration) is not int or duration<=0:raise ValueError('finite_exceptional_service_wall_required')
    return '[Service]\nRuntimeMaxSec='+str(duration)+'\nTimeoutStopSec=65\n'


def read(budget):
    raw=budget.bootstrap.snapshot().get(KEY)
    return json.loads(raw) if raw else None


def prepare(budget,*,maintenance_until):
    """Proposal preparation API; used only in disposable offline fixtures here.

    Future owner-approved configuration supplies a finite absolute wall bound.
    It is an operating resource bound, not a replacement strategy forced sale.
    Repeating the identical preparation is idempotent; changing it is rejected.
    """
    if type(maintenance_until) is not int:raise ValueError('finite_exceptional_wall_required')
    with closing(budget.bootstrap.db()) as db:
        db.execute('BEGIN IMMEDIATE');root=dict(db.execute('SELECT key,value FROM run'))
        start=int(float(root['started_wall']))
        if maintenance_until<=start:raise ValueError('finite_exceptional_wall_required')
        value=dict(version='exceptional-window-candidate-v1',started_at=start,
            maintenance_until=maintenance_until,recovery_until=maintenance_until+3600,
            service_until=maintenance_until+3600+65)
        old=root.get(KEY)
        if old and json.loads(old)!=value:raise ValueError('original_exceptional_window_immutable')
        if not old:
            if root['phase']!='BOOTSTRAP':raise ValueError('initial_exceptional_configuration_required')
            db.execute('INSERT INTO run VALUES(?,?)',(KEY,json.dumps(value,sort_keys=True)))
            for phase in ('continuation','recovery'):
                phase_start=int(float(root[phase+'.started_wall']))
                db.execute('UPDATE run SET value=? WHERE key=?',
                    (str(value['service_until']-phase_start),phase+'.wall_seconds'))
        db.execute('COMMIT')
    adopt(budget,value)
    return value


def adopt(budget,window=None):
    window=window or read(budget)
    if window is None:return False
    root=budget.bootstrap.snapshot();start=int(float(root['started_wall']))
    if (window['version']!='exceptional-window-candidate-v1' or window['started_at']!=start
            or window['recovery_until']!=window['maintenance_until']+3600
            or window['service_until']!=window['recovery_until']+65):
        raise ValueError('exceptional_original_operating_window_identity')
    budget.envelope=dict(budget.envelope,maximum_seconds=window['service_until']-start)
    budget.time=dict(total_wall_seconds=budget.envelope['maximum_seconds'])
    return True


def tick(supervisor):
    """Candidate revision of deadline handling, reusing all native work owners."""
    budget=supervisor.provider_budget;window=read(budget)
    if window is None:return native.tick(supervisor)
    adopt(budget,window);state=supervisor.shared_capital.ledger();now=int(time.time())
    budget.reap_orphans();scope=state['runtime_admission']
    if (supervisor.admission=='BOOTSTRAP' and
            (now>=scope['stop_at']-native.SHUTDOWN_SECONDS or budget.bootstrap.snapshot()['reason'])):
        native.close_bootstrap(supervisor,'bootstrap_completed_or_closed')
        state=supervisor.shared_capital.ledger()
    if native.position_only(path=budget.path,now=now):
        budget.position_work_only();needed=set(native.position_lanes(state))
        health=getattr(supervisor,'last_native_health',{})
        for lane in supervisor.processes:
            if health.get(lane,{}).get('native_continuation',{}).get('flat') is not True:needed.add(lane)
        supervisor.continuation_lanes=tuple(lane for lane in ('pump','pons') if lane in needed)
    if supervisor.admission=='CONTINUATION' and not native.outstanding(state):
        health=getattr(supervisor,'last_native_health',{})
        if all(health.get(lane,{}).get('reconciled') is True and
                health[lane].get('native_continuation',{}).get('flat') is True for lane in supervisor.processes):
            supervisor.shared_capital.verify_replay();budget.set_phase('FLAT','all_positions_exited_and_reconciled')
            supervisor.stop_requested=True
    if native.outstanding(state):
        # Reserve the existing two-second supervisor tick before the 65-second
        # shutdown allowance. An ordinary restart retains these absolute walls.
        if now>=window['recovery_until']-2:budget.set_phase('FAULT','finite_exceptional_exit_recovery_exhausted')
        elif now>=window['maintenance_until'] and budget.phase() not in ('RECOVERY','FAULT'):
            budget.set_phase('RECOVERY','finite_exceptional_maintenance_window_exhausted')
        if budget.phase()=='RECOVERY':
            from .bounded_provider import Budget
            recovery=Budget(budget.path,phase='recovery')
            if recovery.expired(recovery.snapshot()):budget.set_phase('FAULT','bounded_exit_or_resource_recovery_exhausted')
    phase=budget.phase()
    if phase in ('RECOVERY','FAULT') and supervisor.admission!='CONTINUATION':
        native.close_bootstrap(supervisor,'provider_resource_or_recovery_fault',phase=phase)
    if phase=='FAULT':supervisor.continuation_fault=budget.fault();supervisor.stop_requested=True
