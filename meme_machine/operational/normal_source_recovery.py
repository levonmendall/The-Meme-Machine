"""Private failed-generation inputs, never execution or recovery completion.

The supplied original stopped/read scope authenticates its census, held inodes
and fences. The original full financial replay, source registry EOF, native
handler/gap/control joins and protected prior root record supply the facts.
No writer, provider, legacy selector or continuation branch is invoked here.
"""
from copy import deepcopy
import os
import threading

from .normal_boot_record import canonical,digest,require
from . import normal_source_registry as registry

_ISSUER=object()
MAX_OBLIGATIONS=registry.MAX_ROWS
MAX_BYTES=registry.MAX_INPUT_BYTES


def _snapshot(context):
    from meme_machine.runtime.native_restore_context import require_read_context
    from meme_machine.solana_source_drain import (_health_from_db,SOURCE_DRAIN_BYTES,
        CONTROL_RECOVERY_KEY,control_recovery)
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from .normal_source_boot import KEY,validate_current_generation,_clock_sha256
    from .normal_boot import _source_inputs
    context=require_read_context(context);context.verify_boundary()
    # This first capability intentionally reuses the original FLAT authority
    # view. It cannot turn a held snapshot into an eligible recovery scope.
    ledger=context.ledger()
    plan=registry.derive_failed_generation_plan(context).value()
    with context.database(context.root/'shared/solana-evidence.sqlite') as db:
        current=validate_current_generation(_health_from_db(db,KEY,SOURCE_DRAIN_BYTES))
        identity=current['identity'];launch=identity['launch']
        require(launch['epoch_id']==ledger['epoch_id'] and
            launch['inception_sha256']==ledger['inception_sha256'],'recovery_target_epoch')
        endpoint=AlchemyEndpoint.parse(os.environ.get('MM_SOLANA_READ_RPC_URL','')).identity
        require(endpoint==current['provider_identity'],'recovery_target_endpoint')
        clock=_clock_sha256()
        require(clock==identity['native_clock_sha256'],'recovery_target_clock')
        row=db.execute('SELECT CASE WHEN octet_length(body)<=? THEN body END,'
            'CASE WHEN octet_length(hash)<=64 THEN hash END FROM '+registry.GENERATION_TABLE+
            ' WHERE id=?',(registry.MAX_BODY,identity['generation'])).fetchone()
        require(row is not None,'recovery_target_registry_missing')
        generation=registry._validate_generation(registry._read(*row))
        require(digest(generation)==plan['registry_sha256'] and
            current['identity_sha256']==plan['identity_sha256'],'recovery_target_registry_changed')
        obligations=[];encoded=0
        def add(kind,scope,lower,upper,reference):
            nonlocal encoded
            context.check()
            value=dict(kind=kind,scope=scope,lower_slot=lower,retained_upper_slot=upper,
                reference=reference,fresh_authenticated_upper_required=True)
            encoded+=len(canonical(value))
            require(len(obligations)<MAX_OBLIGATIONS and encoded<=MAX_BYTES,
                'recovery_target_obligation_bound')
            obligations.append(value)
        for session in plan['sessions']:
            kind=('CONTROL_METADATA' if session['plane']=='control' else
                'SCOUT_NOMINATION_HISTORY_UNPROVED' if session['plane']=='scout' else
                'CANONICAL_INTERVAL_DELIVERY_AND_PROOF')
            for scope in session['scopes']:
                add(kind,scope,session['lower_slot'],session['retained_upper_slot'],
                    dict(stream=session['stream'],session=session['session']))
        for handler in plan['handlers']:
            recovery=handler['recovery']
            if recovery is not None and recovery['kind']=='CANDIDATE_GAPS':
                for gap in recovery['gaps']:
                    add('NATIVE_GAP',gap['scope'],gap['lower_slot'],gap['upper_slot'],
                        dict(handler=handler['id'],gap=gap['id']))
            elif recovery is not None and recovery['kind']=='CONTROL_REPLAY':
                from meme_machine.solana_selective_runtime import CONTROL
                add('RETAINED_CONTROL_REPLAY',CONTROL,recovery['lower_slot'],recovery['upper_slot'],
                    dict(handler=handler['id'],coverage_after_id=recovery['coverage_after_id'],
                        current_obligation=deepcopy(recovery['current_obligation'])))
        source_inputs,historical=_source_inputs(db)
        control=control_recovery(_health_from_db(db,CONTROL_RECOVERY_KEY,SOURCE_DRAIN_BYTES))
        require(plan['original_unknown_historical_handlers']==historical['pending_handlers'],
            'recovery_target_historical_changed')
        terminal=plan['terminal_census_retained']
        value=dict(schema='qualified-native-source-recovery-target-v1',
            state='BOUND_FAILED_INPUTS_NOT_RECOVERED',generation=plan['generation'],
            identity_sha256=plan['identity_sha256'],failed_raw_sha256=plan['failed_raw_sha256'],
            registry_sha256=plan['registry_sha256'],plan_sha256=digest(plan),
            prior_launch=deepcopy(launch),source=deepcopy(identity['source']),
            provider_identity=endpoint,native_clock_sha256=clock,
            epoch_id=ledger['epoch_id'],inception_sha256=ledger['inception_sha256'],
            preserved_source_inputs=source_inputs,
            original_unknown_historical_handlers=historical['pending_handlers'],
            registered_sessions=len(plan['sessions']),
            registered_session_eof_verified=True,
            retained_session_closures=sum(row['closure'] is not None for row in plan['sessions']),
            terminal_census_retained=terminal,queue_accounting=plan['queue_accounting'],
            handler_population=plan['handler_population'],handlers=deepcopy(plan['handlers']),
            active_programs=deepcopy(generation['active_programs']),
            issued_outbox_frontiers=deepcopy(generation['economic']),
            outbox_membership_independently_verified=False,
            initial_frontiers=deepcopy(plan['initial_frontiers']),
            retained_frontiers=deepcopy(plan['retained_frontiers']),
            obligations=obligations,obligation_union='ALL_REGISTERED_SCOPES_AND_REAL_HANDLER_REFERENCES',
            current_control_prerequisite=control,
            control_prerequisite_role='CURRENT_NATIVE_OBLIGATION_NOT_RECLASSIFIED_HISTORICAL_HANDLER',
            original_failure_state=plan['original_failure_state'],
            original_unexpected_cancellation=plan['original_unexpected_cancellation'],
            fresh_authenticated_upper_required=True,authenticated_upper=None,
            quiescent_final_frontier_verified=False,original_callback_completion=False,
            recovery_complete=False,protected_execution_request_bound=False,
            native_endpoint_completion_verified=False,historical_handler_disposition_verified=False,
            funding_authority=False,safe_for_normal=False,authoritative_writes=0,provider_requests=0)
        require(len(canonical(value))<=MAX_BYTES,'recovery_target_bound')
    context.verify_boundary()
    return value


class QualifiedSourceRecoveryTarget:
    """Detached metadata whose lifetime remains tethered to the real RO guard.

    A later executor needs a separately reviewed guard handoff before closing
    this context/opening a writer. This object itself never transfers ownership.
    """
    __slots__=('_context','_owner','_value','_sha256')
    def __init__(self,context,value,*,_issuer=None):
        require(_issuer is _ISSUER,'recovery_target_private_issuer')
        object.__setattr__(self,'_context',context)
        object.__setattr__(self,'_owner',(os.getpid(),threading.get_ident()))
        object.__setattr__(self,'_value',deepcopy(value))
        object.__setattr__(self,'_sha256',digest(value))

    def __setattr__(self,*args):raise AttributeError('immutable_qualified_recovery_target')
    def __reduce__(self):raise TypeError('qualified_recovery_target_is_process_private')

    @property
    def identity_sha256(self):
        verify_qualified_recovery_target(self)
        return self._sha256

    def value(self):
        verify_qualified_recovery_target(self)
        value=deepcopy(self._value)
        self._context.verify_boundary()
        return value


def derive_qualified_recovery_target(read_context):
    """Original read scope only; caller dictionaries cannot issue this target."""
    value=_snapshot(read_context)
    target=QualifiedSourceRecoveryTarget(read_context,value,_issuer=_ISSUER)
    read_context.verify_boundary()
    return target


def verify_qualified_recovery_target(target):
    """Rejoin actual registry EOF/closures/handlers/gaps/root/clock before use."""
    require(type(target) is QualifiedSourceRecoveryTarget,'recovery_target_required')
    require(target._owner==(os.getpid(),threading.get_ident()),'recovery_target_owner')
    require(digest(_snapshot(target._context))==target._sha256,'recovery_target_changed')
    target._context.verify_boundary()
    return target
