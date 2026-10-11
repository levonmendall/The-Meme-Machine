"""Continuous PAPER and bounded diagnostic maintenance in the existing service.

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
from meme_machine.exact_money import money

HOLD_SECONDS=72*60*60
BRIDGE_SECONDS=36*60*60
EXIT_RECOVERY_SECONDS=3600
SHUTDOWN_SECONDS=65
TOTAL_SECONDS=1200+HOLD_SECONDS+EXIT_RECOVERY_SECONDS+SHUTDOWN_SECONDS
PHASES=('BOOTSTRAP','CONTINUATION','RECOVERY','FAULT','FLAT')


def validate_continuous(row):
    """Physical operating capacity and warning thresholds, never an allowance."""
    keys={'schema','funding_regimes','limits','maximum_queue_depth','maximum_queue_wait_seconds',
        'maximum_rss_bytes','maximum_cpu_cores','failure_window_seconds','failures_before_backoff',
        'reconnect_backoff_seconds','spend_warning_hourly_usd','spend_warning_daily_usd',
        'spend_warning_monthly_usd','usage_increase_factor','physical_http_start_interval_seconds',
        'robinhood_http_start_interval_seconds'}
    if not isinstance(row,dict) or set(row)!=keys or row['schema']!='paper-continuous-provider-v1':
        raise CapitalError('explicit_continuous_provider_profile_required')
    regimes=row['funding_regimes']
    if (not isinstance(regimes,list) or not regimes or len(set(regimes))!=len(regimes)
            or any(r not in ('pump_current','pump_survivor','pons_current','pons_survivor') for r in regimes)):
        raise CapitalError('continuous_selected_regimes_required')
    limits=row['limits']
    if (not isinstance(limits,dict) or set(limits)!={'native_inflight_bytes','http_inflight_bytes'}
            or any(type(v) is not int or not 6*16*1024**2<=v<=512*1024**2 for v in limits.values())):
        raise CapitalError('continuous_inflight_capacity_required')
    if (row['maximum_queue_depth']!=64 or row['maximum_queue_wait_seconds']!=5
            or row['maximum_rss_bytes']!=6*1024**3 or row['maximum_cpu_cores']!='1.8'
            or row['failure_window_seconds']!=60 or row['failures_before_backoff']!=8
            or row['reconnect_backoff_seconds']!=30):
        raise CapitalError('continuous_technical_health_profile_required')
    from decimal import Decimal
    try:
        for key in ('physical_http_start_interval_seconds','robinhood_http_start_interval_seconds'):
            value=row[key]
            if not isinstance(value,str) or not Decimal(value).is_finite() or not Decimal('0.1')<=Decimal(value)<=1:
                raise ValueError()
        for key in ('spend_warning_hourly_usd','spend_warning_daily_usd','spend_warning_monthly_usd','usage_increase_factor'):
            value=row[key]
            if not isinstance(value,str) or not Decimal(value).is_finite() or Decimal(value)<=0:raise ValueError()
        if Decimal(row['usage_increase_factor'])<2:raise ValueError()
    except (ValueError,ArithmeticError):raise CapitalError('continuous_usage_warning_profile_required') from None
    return row


def load_continuous(path=None):
    path=path or os.environ.get('MM_CONTINUOUS_PROVIDER_ENVELOPE')
    if not path:raise CapitalError('continuous_provider_profile_missing')
    file=Path(path)
    if file.is_symlink() or file.stat().st_size>16384:raise CapitalError('continuous_provider_profile_bound')
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise CapitalError('continuous_provider_profile_duplicate')
            result[k]=v
        return result
    return validate_continuous(json.loads(file.read_text(),object_pairs_hook=unique))


def continuous_operation():
    return os.environ.get('MM_PROVIDER_OPERATION_MODE')=='CONTINUOUS'


def provider_interval(provider):
    """Explicit shared pacing; a profile is configuration, not provider proof."""
    if continuous_operation():
        key='robinhood_http_start_interval_seconds' if provider=='robinhood' else 'physical_http_start_interval_seconds'
        return float(load_continuous()[key])
    if os.environ.get('MM_BOUNDED_PROVIDER_DB'):
        from .bounded_provider import Budget
        budget=Budget(os.environ['MM_BOUNDED_PROVIDER_DB'])
        if 'continuation_envelope' in budget.snapshot():
            # Legacy bounded maintenance has its own phase admission. An
            # expired bootstrap must never veto its remaining exit resources.
            return .5
        row=budget.preflight_file()
        return float(row['physical_http_start_intervals'][provider])
    return None


def funding_scope(envelope):
    """Optional first-owner funding limits; native protection stays independent."""
    scope=envelope.get('bootstrap_funding_scope')
    if scope is None:return None
    keys={'regimes','maximum_initial_basis_usd','maximum_addition_basis_usd','maximum_fee_reserve_usd'}
    if not isinstance(scope,dict) or set(scope)!=keys:
        raise CapitalError('complete_bootstrap_funding_scope_required')
    regimes=scope['regimes']
    if (not isinstance(regimes,list) or not 1<=len(regimes)<=2
            or any(r not in ('pump_current','pump_survivor','pons_current','pons_survivor') for r in regimes)
            or len(set(regimes))!=len(regimes) or len({FAMILIES[r] for r in regimes})!=1):
        raise CapitalError('bootstrap_single_family_funding_scope_required')
    try:
        initial=money(scope['maximum_initial_basis_usd'],positive=True)
        addition=money(scope['maximum_addition_basis_usd'],nonnegative=True)
        money(scope['maximum_fee_reserve_usd'],nonnegative=True)
    except (ValueError,TypeError):
        raise CapitalError('explicit_exact_bootstrap_basis_and_fee_limits_required') from None
    if initial>50 or addition>25:
        raise CapitalError('bootstrap_first_owner_basis_limit')
    return scope


def funding_lanes(envelope):
    if envelope.get('schema')=='paper-continuous-provider-v1':
        return tuple(dict.fromkeys(FAMILIES[r] for r in envelope['funding_regimes']))
    scope=funding_scope(envelope)
    return tuple(dict.fromkeys(FAMILIES[r] for r in scope['regimes'])) if scope else ('pump','pons')


def validate_envelope(row):
    """Explicit finite operational allowances, never provider account quotas."""
    if row.get('schema') not in ('paper-position-continuation-resources-v1','paper-position-maintenance-resources-v2'):
        raise CapitalError('explicit_continuation_resource_envelope_required')
    maintenance=row['schema']=='paper-position-maintenance-resources-v2'
    if (row.get('recovery_seconds')!=EXIT_RECOVERY_SECONDS or
            (not maintenance and row.get('maximum_seconds')!=TOTAL_SECONDS) or
            (maintenance and (row.get('maximum_seconds') is not None or
                row.get('holding_time_exit') is not False or row.get('cumulative_usage') is not True))):
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
    funding_scope(row)
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
    path=path or os.environ.get('MM_PROVIDER_USAGE_DB') or os.environ.get('MM_BOUNDED_PROVIDER_DB')
    if not path:return False
    try:
        with closing(sqlite3.connect(Path(path).absolute().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            rows=dict(db.execute("SELECT key,value FROM run WHERE key IN ('phase','started_wall','work_mode','operating_mode')"))
        if rows.get('operating_mode')=='CONTINUOUS':return rows.get('work_mode')=='POSITION_ONLY'
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
    lanes=funding_lanes(envelope)
    for lane in lanes:
        row=health['lanes'][lane]
        proof=row.get('native_continuation',{})
        if (not row.get('reconciled') or row.get('exit_code') is not None
                or not all(proof.get(key) is True for key in
                    ('current_restored','survivor_replay_verified','survivor_handoff_ready','exit_path_bound'))):
            raise ValueError(lane+'_native_continuation_not_ready')
    for provider in ('solana' if lane=='pump' else 'robinhood' for lane in lanes):
        row=health['providers'].get(provider,{})
        if (row.get('state')!='CURRENT' or row['queue_depth']>envelope['maximum_queue_depth']
                or row['oldest_wait_seconds']>envelope['maximum_queue_wait_seconds']):
            raise ValueError(provider+'_continuation_provider_not_ready')
    if 'pump' in lanes:
        evidence=health['providers']['evidence']
        if evidence.get('startup_released') is not True or evidence.get('phase')!='ACTIVE':
            raise ValueError('continuation_subscription_or_coverage_not_ready')
    proof=dict(native_managers=True,native_recovery=True,exit_paths=True,
        authenticated_evidence=True,reconciliation=True,provider_governors=True)
    scope=funding_scope(envelope)
    if scope:proof['funding_regimes']=list(scope['regimes'])
    return proof


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
        # The legacy acceptance wall stays absolute on restart. The separately
        # selected maintenance schema has no position/service age ceiling, but
        # retains every cumulative purchase, byte, spending and incident bound.
        wall=budget.envelope['maximum_seconds']
        if wall is not None and now>=scope['started_at']+wall-SHUTDOWN_SECONDS:
            budget.set_phase('FAULT','original_continuation_and_exit_recovery_deadline_exhausted')
        elif (wall is not None and now>=scope['started_at']+wall-EXIT_RECOVERY_SECONDS-SHUTDOWN_SECONDS
                and budget.phase() not in ('RECOVERY','FAULT')):
            budget.set_phase('RECOVERY','finite_operating_window_exhausted_protection_degraded')
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
    if getattr(budget,'continuous',False):
        budget.publish_readiness(False,supervisor.run_id,reason=reason)
        return
    if supervisor.admission=='BOOTSTRAP':close_bootstrap(supervisor,reason)
    with closing(budget.bootstrap.db()) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT value FROM run WHERE key='provider_degraded_at'").fetchone()
        at=int(row[0]) if row else now
        db.execute('INSERT OR IGNORE INTO run VALUES(?,?)',('provider_degraded_at',str(at)))
        detail=dict(phase='DEGRADED',state='DEGRADED_PROTECTION',reason=reason,at=at,deadline=at+EXIT_RECOVERY_SECONDS,
            funding_closed=True,protected=False,action='restore_authenticated_market_evidence_and_exit_connectivity')
        db.execute('INSERT INTO run VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            ('provider_fault',json.dumps(detail)))
        db.execute('COMMIT')
    if now>=at+EXIT_RECOVERY_SECONDS:budget.set_phase('FAULT','provider_recovery_deadline_exhausted:'+reason)


def provider_recovered(supervisor):
    if getattr(supervisor.provider_budget,'continuous',False):return # normal_tick proves fresh readiness before reopening
    with closing(supervisor.provider_budget.bootstrap.db()) as db:
        db.execute("DELETE FROM run WHERE key IN ('provider_degraded_at','provider_fault')")
