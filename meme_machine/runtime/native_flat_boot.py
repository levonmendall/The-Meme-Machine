"""Narrow stopped flat native inputs; no live, funding or history authority.

Only the original protected collector may authenticate the read context's
source, physical census, inode map, stopped locks and configuration. This module
earns the native result by running original reducers, never an inspection digest
or supplied success flags. The later administrative producer must join its own
original full financial/native census to this exact fenced scope.
"""
import os
import threading

from .journal import digest
from .native_restore_context import _require, require_read_context
from .native_restore_closure import _native_memory_facts

_ISSUER = object()
REGIMES = ('pons_current', 'pons_survivor', 'pump_current', 'pump_survivor')


def configured_flat_boot_dependencies(root):
    """Mandatory original four-regime stores; not a physical census substitute.

    Trials/cold references are derived by the original retained native reducers
    from actual capital/controller state. Unknown or missing physical inputs
    must still fail the protected collector/reducer; they are never skipped.
    """
    from pathlib import Path
    from .native_restore_closure import PAPERS, HISTORIES, PLANE, COHORT
    root = Path(root)
    _require(root.is_absolute() and '..' not in root.parts, 'flat_boot_native_root')
    names = (*PAPERS.values(), *HISTORIES.values(), PLANE,
        COHORT+'/pons-selective-cohort-capital.sqlite',
        'pump/directional-sleeve.sqlite', 'pons/directional-sleeve.sqlite',
        'portfolio.sqlite', 'shared-capital.sqlite')
    return frozenset(root/name for name in names)


def _generation(context):
    context.verify_boundary()
    rows = []
    for path in sorted(context.database_identities):
        with context.database(path) as db:
            rows.append([str(path), id(db), db.total_changes,
                db.execute('PRAGMA data_version').fetchone()[0],
                db.execute('PRAGMA schema_version').fetchone()[0]])
    return digest(rows)


class FlatNativeBootInputs:
    """One retained read scope's derived inputs, explicitly not a boot permit."""
    __slots__ = ('_context', '_generation', '_owner', '_value', '_cancelled')

    def __init__(self, context, generation, value, *, cancelled=lambda: False, _issuer=None):
        _require(_issuer is _ISSUER, 'flat_boot_native_issuer')
        object.__setattr__(self, '_context', context)
        object.__setattr__(self, '_generation', generation)
        object.__setattr__(self, '_owner', (os.getpid(), threading.get_ident()))
        object.__setattr__(self, '_value', value)
        object.__setattr__(self, '_cancelled', cancelled)

    def __setattr__(self, *args):
        raise AttributeError('immutable_flat_native_inputs')

    def value(self):
        _require(self._owner == (os.getpid(), threading.get_ident()), 'flat_boot_native_owner')
        _require(self._cancelled() is False, 'flat_boot_native_cancelled')
        _require(_generation(self._context) == self._generation, 'flat_boot_native_generation_changed')
        from copy import deepcopy
        return deepcopy(self._value)


def validate_stopped_flat_boot_inputs(read_context, *, cancelled=lambda: False):
    """Replay financial, terminal and retained decision-memory inputs only.

    Discovery/watch/audit closure is not claimed. Every original current native
    financial effect and actual terminal/controller/reentry/rally join exercised
    by the four original reducers must pass. The protected caller's source,
    census, all-nine financial counts and stopped ownership remain independent
    required premises; no dictionary can supply a positive native result.
    """
    context = require_read_context(read_context)
    _require(callable(cancelled), 'flat_boot_native_cancel_callback')
    _require(configured_flat_boot_dependencies(context.root) <= context.database_identities,
        'flat_boot_native_configured_dependency_missing')
    previous = context._check_owner_deadline
    had_shadow = '_check_owner_deadline' in context.__dict__
    shadow = context.__dict__.get('_check_owner_deadline')

    def check():
        previous()
        _require(cancelled() is False, 'flat_boot_native_cancelled')

    # The existing cold-replay per-event hook calls this exact local context
    # method. Compose cancellation for this one owner/scope and restore it even
    # on original decoder/replay failure; never replace an SQL progress handler.
    context._check_owner_deadline = check
    try:
        before = _generation(context)
        facts = _native_memory_facts(context)
        _require(tuple(sorted(facts['facts'])) == REGIMES, 'flat_boot_native_regime_population')
        state = context.ledger()
        proof = facts['authority']
        _require(proof.get('conservation') is True and type(proof.get('events')) is int
            and proof['events'] > 0, 'flat_boot_native_financial_replay')
        after = _generation(context)
        _require(before == after, 'flat_boot_native_generation_changed')
        value = dict(schema='stopped-flat-native-inputs-v1',
            state='VERIFIED_FLAT_NATIVE_TERMINAL_AND_DECISION_MEMORY_INPUTS',
            four_regimes=list(REGIMES), epoch_id=state['epoch_id'],
            inception_sha256=state['inception_sha256'], policy_sha256=digest(state['policy']),
            journal_sequence=proof['events'], journal_hash=proof['journal_hash'],
            projection_hash=proof['state_sha256'],
            combined_sequence=state['migration_source']['sequence'] + proof['events'],
            native_input_sha256=digest(facts), read_generation_sha256=after,
            native_flat_inputs_verified=True, protected_acquisition_authenticated_here=False,
            complete_discovery_closure=False, current_native_protection_verified=False,
            boot_authority=False, funding_authority=False, safe_for_normal=False,
            historical_handler_disposition_verified=False, historical_drain_reclassified=False,
            authoritative_writes=0, provider_requests=0)
        return FlatNativeBootInputs(context, after, value, cancelled=cancelled, _issuer=_ISSUER)
    finally:
        if had_shadow:context._check_owner_deadline = shadow
        else:del context._check_owner_deadline
