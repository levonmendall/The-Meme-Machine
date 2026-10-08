"""PAPER run scope. Qualification and safety do not depend on funding scope.

The first real lifecycle has a finite, durable allowance, not a certification
flag. Normal admission retains the existing provider-latency guard. Operational
review of authentic evidence is still required; bootstrap never promotes itself.
"""
import os
import sqlite3
import time

from meme_machine.exact_money import amount, money
from meme_machine.shared_capital.model import CapitalError

MODES=('OBSERVATION','BOOTSTRAP','CONTINUATION','NORMAL','AUTONOMY')
BOOTSTRAP_SECONDS=1800
FUNDING_SECONDS=1200
CAPITAL_LIMIT='25'
CONTINUATION_PROOFS=('native_managers','native_recovery','exit_paths','authenticated_evidence',
    'reconciliation','provider_governors')

def verified_continuation(proof):
    return isinstance(proof,dict) and all(proof.get(key) is True for key in CONTINUATION_PROOFS)


def require_normal():
    from meme_machine.solana_selective_source import require_certified
    require_certified()


def require_autonomy(root):
    require_normal()
    # Reuse the normal durable acceptance sequence and exact candidate identity.
    from pathlib import Path
    from .durable_acceptance import OUTPUT,source_identity,read_json
    identity=source_identity(Path(__file__).resolve().parents[2])
    from meme_machine.shared_capital.runtime import selected,connection
    shared=selected(Path(root)/'portfolio.sqlite')
    if shared is None:raise CapitalError('shared_authority_required')
    epoch=connection(shared).ledger()['epoch_id']
    for phase in ('CAPACITY','RECOVERY'):
        row=read_json(OUTPUT/('latest-'+phase+'.json'))
        if row.get('status')!='PASS' or row.get('identity')!=identity or row.get('epoch_id')!=epoch:
            raise CapitalError('same_candidate_preceding_phase_required:'+phase)


def legacy_funding_guard(sleeve):
    """Production must never fall back to four independent legacy budgets."""
    if os.environ.get('MM_PORTFOLIO_ACCOUNTING_DB') and not hasattr(sleeve,'authority'):
        from meme_machine.shared_capital.native_sleeve import FundingDenied
        raise FundingDenied('observation_only_shared_authority_not_selected')


def available(state,at,*,live=False):
    scope=state.get('runtime_admission')
    if scope is None:
        # Historical replay stays independent. An operational client must never
        # acquire capital by omitting the new scope on an older selected ledger.
        from meme_machine.runtime.operating_families import operational
        return 'operational_funding_scope_required' if live and operational() else None
    mode=scope['mode']
    if mode in ('OBSERVATION','CONTINUATION'):return 'observation_only_funding_closed'
    if mode in ('NORMAL','AUTONOMY'):
        if live:
            try:require_normal()
            except Exception:return 'combined_position_and_candidate_provider_latency_not_certified'
        return None
    if at>=scope['funding_until']:return 'bootstrap_funding_deadline'
    if not verified_continuation(scope.get('continuation_ready')):return 'native_continuation_not_ready'
    if not scope.get('continuation_envelope'):return 'separately_authorized_continuation_envelope_missing'
    if not live:return None
    from .bounded_provider import Budget
    try:
        budget=Budget(scope['provider_db'])
        if budget.snapshot()['reason'] or time.monotonic()-budget.started>=1800:
            return 'bootstrap_provider_exposure_closed'
        if budget.snapshot().get('phase','BOOTSTRAP')!='BOOTSTRAP':return 'bootstrap_provider_exposure_closed'
    except (OSError,KeyError,sqlite3.Error):return 'bootstrap_provider_exposure_unavailable'
    # A dead supervisor cannot leave a spendable bootstrap after a crash.
    from meme_machine.shared_capital.runtime import process_identity
    try:alive=process_identity(scope['pid'])==scope['process_start']
    except (OSError,CapitalError):alive=False
    return None if alive else 'bootstrap_supervisor_not_running'


def decision(state,request,result,at):
    reason=available(state,at)
    scope=state.get('runtime_admission')
    if not reason and scope and scope['mode']=='BOOTSTRAP' and result['status']=='RESERVED':
        key=next((key for key,req in state['runtime_native_requests'].items()
                  if req==request['request_id']),None)
        life=state['native_aliases'].get(key.removesuffix(':scale')) if key else None
        if not life:raise CapitalError('bootstrap_native_identity_missing')
        if scope['lifecycle_id'] not in (None,life):reason='bootstrap_one_lifecycle_limit'
        elif money(scope['gross_reserved'])+money(result['total'])>money(CAPITAL_LIMIT):
            reason='bootstrap_gross_capital_limit'
        else:
            # No replenishment after cancellation, exit, retry or restart.
            scope['lifecycle_id']=life
            scope['gross_reserved']=amount(money(scope['gross_reserved'])+money(result['total']))
    if reason:return dict(status='QUALIFIED_BUT_CAPITAL_UNAVAILABLE',reason=reason,basis='0',total='0')
    return result


def configure(state,data,at):
    mode=data['mode']
    if mode not in MODES:raise CapitalError('PAPER_admission_mode')
    previous=state.get('runtime_admission')
    if mode=='BOOTSTRAP':
        # The run is created with funding closed and armed only after readiness.
        if (not previous or previous['mode']!='OBSERVATION' or previous.get('run_id')!=data['run_id']
                or previous.get('bootstrap_used')):
            raise CapitalError('bootstrap_requires_unused_observation_run')
        started=previous['started_at']
        from .position_continuation import validate_envelope
        validate_envelope(previous.get('continuation_envelope',{}))
        if not verified_continuation(data.get('continuation_ready')):
            raise CapitalError('native_continuation_not_ready')
        if at>=started+FUNDING_SECONDS:raise CapitalError('bootstrap_readiness_deadline')
        if state['positions'] or state['reservations'] or state['commitments'] or state.get('runtime_pending'):
            raise CapitalError('first_bootstrap_requires_empty_preserved_epoch')
        state['runtime_admission']=dict(previous,mode=mode,bootstrap_used=True,
            funding_until=started+FUNDING_SECONDS,stop_at=started+BOOTSTRAP_SECONDS,
            lifecycle_id=None,gross_reserved='0',continuation_ready=data['continuation_ready'])
    else:
        # Observation/recovery may restart after a claim; its funding stays
        # closed. Preserve the used claim so a restart cannot replenish it.
        same=previous and previous.get('run_id')==data['run_id']
        started=previous['started_at'] if same else at
        state['runtime_admission']=dict(previous or {},mode=mode,run_id=data['run_id'],started_at=started,
            pid=data['pid'],process_start=data['process_start'],
            bootstrap_used=bool(previous and previous.get('bootstrap_used')))
        if data.get('provider_db'):state['runtime_admission']['provider_db']=data['provider_db']
        if data.get('continuation_envelope'):
            if same and previous.get('continuation_envelope')!=data['continuation_envelope']:
                raise CapitalError('continuation_allowance_cannot_expand_on_restart')
            state['runtime_admission']['continuation_envelope']=data['continuation_envelope']
        if data.get('phase'):state['runtime_admission']['phase']=data['phase']
        state['runtime_admission'].setdefault('funding_until',started+FUNDING_SECONDS)
        state['runtime_admission'].setdefault('stop_at',started+BOOTSTRAP_SECONDS)
    return dict(mode=mode)
