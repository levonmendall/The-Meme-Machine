"""All-four stopped native restore dependencies, never market/funding readiness.

Only a protected caller may supply the original source/census/fence premises.
Every result remains nonauthoritative and preserves unresolved historical work.
"""
from copy import deepcopy
import json
from pathlib import Path
import re

from .journal import canonical, digest
from .native_restore_context import (NativeDependencyUnavailable, MAX_ROWS,
                                     _require, require_read_context)


COHORT = 'pons/pons-selective-continuation-v1-cohort'
PAPERS = {
    'pump_current': 'pump/pump-acceleration-natural-prospective.accounting.sqlite3',
    'pump_survivor': 'pump/pump-survivor/paper.sqlite',
    'pons_survivor': COHORT + '/pons-survivor/paper.sqlite',
}
HISTORIES = {'pump': 'pump/pump-survivor/history.sqlite',
             'pons': COHORT + '/pons-survivor/history.sqlite'}
PLANE = 'shared/robinhood-evidence.candidates.sqlite'
CANDIDATES = 'shared/solana-candidate-history.sqlite'

# These are roles in the original startup, not substitute admission flags.
# A protected funding-closed boot may let original actors repair nominations;
# spending still needs the original live financial/protection/quote guards.
DEPENDENCY_ROLES = {
    'native_financial_replay': 'STOPPED_FINANCIAL_AND_CURRENT_AUTHORITY_INPUT',
    'controller_reentry_cycle_memory': 'DECISION_CRITICAL_RETAINED_INPUT',
    'scout_watch_cursor_pipeline': 'ORIGINAL_FUNDING_CLOSED_STARTUP_REPAIR_INPUT',
    'frozen_wallet_documents': 'AUTHENTICATED_SOURCE_QUALIFICATION_INPUT',
    'provider_membership_usd_and_protection': 'FRESH_RUNNING_ACTOR_ATTESTATION_REQUIRED',
    'historical_handler_disposition': 'PRESERVED_SEPARATE_UNRESOLVED_HISTORY',
}

UNIMPLEMENTED_INPUT_DEPENDENCIES = (
    'FULL_DISCOVERY_WATCH_GENERATION_AND_CHECKPOINT_SEMANTICS',
    'SOURCE_ROUTED_SCOUT_AND_GRADUATION_POPULATION_JOINS',
    'QUALIFICATION_AUDIT_AND_PIPELINE_RETAINED_MEMBERSHIP',
    'FROZEN_AND_LOCAL_WALLET_QUALIFICATION_DOCUMENTS',
    'FRESH_PROVIDER_MEMBERSHIP_NATIVE_USD_AND_POSITION_PROTECTION',
)


def _rows(db, table):
    return [json.loads(raw) for raw, in db.execute('SELECT body FROM ' + table)]


def _archive(archive):
    if not archive:
        return
    # Interrupted retirement has real join work; observation never finishes it.
    _require(not archive.get('retirement_pending'), 'native_restore_retirement_pending')
    authority = archive.get('authority')
    if authority is not None:
        _require(type(authority) is dict and isinstance(authority.get('state_hash'), str),
                 'native_restore_prefix_authority')


def _policy_memory(book):
    from .policy_compatibility import (SELECTION_NAMESPACE, SELECTION_KEY,
                                      LEGACY_SELECTION_KEY, validate_prior_selection)
    for key in (SELECTION_KEY, LEGACY_SELECTION_KEY):
        saved = book.runtime_state(SELECTION_NAMESPACE, key)
        if saved is not None:
            validate_prior_selection(saved, book.identity)


def _terminal_join(context, book, sleeve, position, *, lane):
    from .policy_compatibility import require_flat_rows
    require_flat_rows([position], kind='pump')
    held = sleeve.get(position['id'])
    _require(held is not None and held['strategy'] == book.identity['lane']
             and held['status'] == 'settled' and held['held'] == 0
             and held['pnl'] == position['realized']
             and held['terminal_hash'] == digest(position)
             and held.get('cancelled') is (position['status'] == 'cancelled')
             and (held.get('scale_reservation') or {}).get('status') != 'reserved',
             'native_restore_native_sleeve_terminal_join')
    # The original global validator retains its exact receipt/cursor/request
    # checks. A native terminal with no actual global ACK stays unavailable.
    if position['status'] == 'cancelled':
        # A never-filled release has no fabricated global SETTLED position.
        # Reuse the original release-delivery ACK against the actual retained
        # native terminal event. Missing compacted detail stays unavailable.
        from meme_machine.lanes.pons.pons_reentry import _portfolio_ack
        terminal = None
        for raw, checksum in book.db.execute('SELECT body,hash FROM journal ORDER BY seq'):
            event = json.loads(raw)
            if event['position']['id'] == position['id']:
                terminal = (event, checksum)
        _require(terminal is not None and terminal[0]['position'] == position
                 and terminal[0]['action'] == 'cancelled'
                 and _portfolio_ack(position, terminal[1], lane=lane,
                                    cancelled=True, read_context=context),
                 'native_restore_global_cancel_ack')
    else:
        _require(sleeve.reentry_verified(position['id']) is not None,
                 'native_restore_global_terminal_ack')


def _survivor(context, lane, book, sleeve, history):
    from fractions import Fraction
    from .survivor_commit import handoff_ready, restore_risk
    from .policy_compatibility import known_hash
    rows = history.rows(include_retired=True)
    _require(len(rows) <= MAX_ROWS and handoff_ready(book, rows),
             'native_restore_survivor_handoff')
    candidates = {row['id']: row for row in rows}
    _require(len(candidates) == len(rows), 'native_restore_survivor_candidate_population')
    _require(set(candidates) == {identity for identity, in history.db.execute('SELECT id FROM candidates')},
             'native_restore_survivor_candidate_identity')
    for candidate, identity, at, raw, checksum in history.db.execute(
            'SELECT candidate,id,at,body,hash FROM events'):
        event = json.loads(raw)
        row = candidates.get(candidate)
        _require(row is not None and row.get('state') != 'retired'
                 and event.get('id') == identity and event.get('at') == at
                 and digest(event) == checksum and event.get('authenticated') is True
                 and type(at) is int and at <= row['through'],
                 'native_restore_survivor_event_join')
    for candidate, at, raw, checksum in history.db.execute('SELECT candidate,at,price,hash FROM points'):
        point = json.loads(raw)
        row = candidates.get(candidate)
        _require(row is not None and row.get('state') != 'retired'
                 and type(at) is int and at <= row['through']
                 and digest([candidate, at, raw]) == checksum
                 and 0 < Fraction(point['low']) <= Fraction(point['price']) <= Fraction(point['high']),
                 'native_restore_survivor_point_join')
    positions = {row['id']: row for row in _rows(book.db, 'positions')}
    for row in rows:
        context.check()
        graduation = row['graduation']
        _require(type(graduation) is dict and type(graduation.get('at')) is int,
                 'native_restore_survivor_graduation')
        if row['state'] == 'retired':
            # Original retirement intentionally retains this smaller tombstone
            # and deletes its acquired points/events. It has no pending owner.
            _require(row.get('position') is None and type(row['last_checked']) is int,
                     'native_restore_survivor_retired_controller')
            continue
        _require(type(row.get('through')) is int and row['through'] >= graduation['at']
                 and type(row.get('complete')) is bool,
                 'native_restore_survivor_watermark')
        identity = row.get('position')
        if identity is not None:
            _require(identity in positions and positions[identity].get('candidate') == row['id'],
                     'native_restore_survivor_position_join')
        # Use the actual verifier for every event and point, including retired
        # candidates. Do not use the hot-set rows() default or discard gaps.
        points, events = history.facts(row['id'], row['through'])
        prefix = history.prefix(row['id'])
        if lane == 'pump':
            from meme_machine.lanes.pump.pumpswap_survivor import reduce_reset_history, POLICY, policy_hash
            from meme_machine.paper_policy_revision import predecessor_policies, previous_policies
            policy = POLICY
            selected = history.get_meta('policy')
            if selected != policy_hash(POLICY):
                sources = (predecessor_policies(), previous_policies())
                matches = [source['pump_survivor']['policy'] for source in sources
                           if source['pump_survivor']['policy_hash'] == selected]
                _require(len(matches) == 1, 'native_restore_reset_policy')
                policy = matches[0]
            additions = points if prefix is None else [p for p in points if p['at'] > prefix['through']]
            reduce_reset_history(additions, prefix, policy=policy)
            saved = history.get_meta('calculation_prefix:' + row['id'])
            if saved is not None:
                _require(saved.get('policy') == selected
                         and saved.get('source') == digest([selected, graduation,
                             history.get_meta('archive_prefix:' + row['id'])]),
                         'native_restore_calculation_prefix_source')
                before = history.prefix(row['id'])
                expected = reduce_reset_history((p for p in points
                    if (before is None or p['at'] > before['through']) and p['at'] <= saved['through']),
                    before, policy=policy)
                _require(expected == saved.get('state'), 'native_restore_calculation_prefix_state')
                inputs = digest(history.get_meta('archive_prefix:' + row['id']))
                records = 0
                for at, raw, checksum in history.db.execute('SELECT at,price,hash FROM points '
                        'WHERE candidate=? AND at<=? ORDER BY at', (row['id'], saved['through'])):
                    if before is not None and at <= before['through']:
                        continue
                    inputs = digest([inputs, row['id'], at, checksum])
                    records += 1
                _require(saved.get('inputs_hash') == inputs and saved.get('records') == records,
                         'native_restore_calculation_prefix_inputs')
        else:
            window = history.get_meta('pons_price_window:' + row['id'])
            if window:
                _require(window.get('authority') == 'canonical_observations_folded_after_strategy_window'
                         and type(window.get('before')) is int
                         and window['before'] <= row['through'], 'native_restore_pons_price_window')
                retained = {point['at']: point for point in points}
                _require(all(retained.get(window[name]['at']) == window[name]
                             for name in ('original_anchor', 'boundary')),
                         'native_restore_pons_price_window_anchor')
        decision = row.get('decision')
        if decision:
            _require(known_hash(lane + '_survivor', decision.get('policy_hash')),
                     'native_restore_survivor_decision_policy')
    for identity, position in positions.items():
        _terminal_join(context, book, sleeve, position, lane=lane)
        if position.get('status') == 'settled':
            restore_risk(book, identity)
        candidate = position.get('candidate')
        _require(candidate in candidates or (history.get_meta('graduation_floor') is not None
                 and history.get_meta('retired_archive') is not None
                 and (book._archive() or {}).get('archived_entry_scope') is not None),
                 'native_restore_survivor_candidate_missing')
    return dict(candidates=len(rows), positions=len(positions),
                state_sha256=digest(rows), position_sha256=digest(positions))


def _pump_current(context, book, sleeve):
    from types import SimpleNamespace
    from meme_machine.lanes.pump import runner
    from meme_machine.lanes.pump.pump_attempt_reference import release_acknowledged, FRONTIERS
    def no_interest(*args, **kwargs):
        raise NativeDependencyUnavailable('native_restore_nonflat_interest')
    # restore_runtime only merges these two retained creator projections. This
    # is deliberately not a ConfirmationBook with an invented empty cohort;
    # source-authenticated frozen wallet inputs belong to actual qualification.
    creator_memory = SimpleNamespace(creator_launches={}, mint_creator={})
    restored = runner.restore_runtime(book, SimpleNamespace(interest=no_interest),
        creator_memory, bind_allocation=False, read_context=context)
    qualifiers = restored[-1]
    positions = _rows(book.db, 'positions')
    _require({q['lifecycle_id'] for q in qualifiers} == {p['id'] for p in positions}
             and not restored[2] and not restored[3], 'native_restore_pump_controller_population')
    for qualifier in qualifiers:
        _require(qualifier.get('verified_terminal_attempt') is not None,
                 'native_restore_current_attempt_unresolved')
    for position in positions:
        _terminal_join(context, book, sleeve, position, lane='pump')
    for proof in (book._archive() or {}).get(FRONTIERS, {}).values():
        _require(release_acknowledged(book, proof, read_context=context),
                 'native_restore_retained_attempt_unresolved')
    return dict(positions=len(positions), qualifiers=len(qualifiers),
                qualifier_sha256=digest(qualifiers),
                restored_creator_memory_sha256=digest(vars(creator_memory)),
                frozen_wallet_qualification_inputs_verified=False)


def _pons_current(context, capital, plane_path):
    from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
    from meme_machine.lanes.pons.pons_selective_ledger import (SelectivePaper, STRATEGY_NAMESPACE,
        GENESIS_CATEGORY, DECISION_CATEGORY, JOURNAL_CATEGORY)
    from meme_machine.lanes.pons.pons_selective_recovery import LifecycleState, _pending_recoveries, BASE, GROUPS
    from .policy_compatibility import known_hash
    from meme_machine.lanes.pons.pons_reentry import recover_references
    from .robinhood.pons import recover_cohort
    from .pons_terminal_archive import anchor
    root = Path(capital.path).parent
    result = recover_cohort(plane_path, POLICY_HASH, capital_path=capital.path, read_context=context)
    qualifiers = result.get('qualifiers', [])
    _require(len(qualifiers) <= MAX_ROWS and len({q['index'] for q in qualifiers}) == len(qualifiers),
             'native_restore_pons_qualifier_population')
    by_index = {q['index']: q for q in qualifiers}
    pending, _, _ = _pending_recoveries(root, qualifiers, result.get('lifecycles', []),read_context=context)
    _require(not pending, 'native_restore_pons_controller_continuation_required')
    with context.database(capital.path) as db:
        rows = _rows(db, 'capital_positions')
        archive = anchor(db)
        _archive(archive)
    expected = set()
    for row in rows:
        path = context.trial_identity(row['trial_path'], root=root)
        match = re.fullmatch(r'trial-(\d+)\.sqlite', path.name)
        _require(match is not None and path not in expected, 'native_restore_trial_identity')
        expected.add(path)
        index = int(match[1])
        _require(index in by_index, 'native_restore_trial_qualifier_missing')
        store = context.store(path)
        paper = object.__new__(SelectivePaper)
        paper.store = store
        paper.experiment = STRATEGY_NAMESPACE
        paper._readonly_shared_authority = context
        native_positions = paper.positions()
        _require(len(native_positions) == 1 and native_positions[0]['id'] == row['id']
                 and len(list(store.db.execute('SELECT id FROM pons_selective_paper'))) == 1,
                 'native_restore_trial_position_population')
        genesis = store.get(GENESIS_CATEGORY, STRATEGY_NAMESPACE)
        _require(genesis['strategy_namespace'] == STRATEGY_NAMESPACE
                 and genesis['authority'] == 'pons_selective_continuation_only'
                 and genesis['shared_allocator'] is False
                 and genesis['position_table'] == 'pons_selective_paper'
                 and type(genesis['delay']) is int and genesis['delay'] >= 1
                 and known_hash('pons_current', genesis['natural_policy_hash'])
                 and genesis['capital'] == capital.capital,
                 'native_restore_trial_genesis')
        for category, identity in store.db.execute('SELECT category,id FROM records'):
            if category in (BASE, DECISION_CATEGORY):
                _require(identity == row['id'], 'native_restore_trial_record_population')
            elif category == GENESIS_CATEGORY:
                _require(identity == STRATEGY_NAMESPACE, 'native_restore_trial_record_population')
        tables = {name for name, in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if GROUPS in tables:
            context.bound_bodies(store.db, (GROUPS,))
            _require(all(identity == row['id'] and kind in ('preholders','seen_v4_buyers')
                         for identity,kind in store.db.execute('SELECT DISTINCT identity,kind FROM '+GROUPS)),
                     'native_restore_trial_group_population')
        paper.reconcile()
        position = paper._get(row['id'])
        _require(position.get('status') == 'settled' and position['tokens'] == 0,
                 'native_restore_pons_trial_nonflat')
        if position.get('entry_tokens', 0) > 0:
            LifecycleState.restore(paper, row['id'])
        _require(row.get('native_position') == position
                 and row.get('native_settlement_hash') == digest(position),
                 'native_restore_trial_capital_terminal_join')
    physical = {path for path in context.database_identities
                if path.parent == root and re.fullmatch(r'trial-\d+\.sqlite', path.name)}
    _require(physical == expected, 'native_restore_physical_trial_population')
    references = recover_references(root, result, read_context=context)
    _require(not any(state.get('unresolved_lifecycles') for state in references.values()),
             'native_restore_pons_reentry_unresolved')
    for qualifier in qualifiers:
        reference = references.get(qualifier['curve']) or {}
        attempt = reference.get('last_attempt') or {}
        _require(attempt.get('terminal_ready') is True, 'native_restore_pons_attempt_unresolved')
    sleeve = context.sleeve('pons')
    for reference in references.values():
        for key in ('last_attempt', 'last_filled_trade'):
            attempt = reference.get(key)
            if not attempt:
                continue
            _require(attempt.get('terminal_ready') is True
                     and sleeve.reentry_verified(attempt['lifecycle_id']) is not None,
                     'native_restore_retired_pons_reference_ack')
            if key == 'last_filled_trade':
                _require(attempt.get('vector_id') == digest(attempt['vector'])
                         and attempt['vector'].get('asof') == attempt.get('original_at'),
                         'native_restore_retired_pons_reference_vector')
    # Completed retirement intentionally retains aggregates, not deleted trial
    # details. Authenticate the exact representation current restart consumes.
    controller = result.get('archived_trials') or {}
    folded = (archive or {}).get('folded') or {}
    _require(controller.get('qualifiers', 0) == folded.get('positions', 0),
             'native_restore_pons_retirement_population')
    return dict(trials=len(rows), qualifiers=len(qualifiers),
                controller_sha256=digest(result), reentry_sha256=digest(references))


def _rallies(context, sleeve, histories, native_positions):
    from .policy_compatibility import regime_for, known_hash
    from .rally_cycle import validate_cycle
    rows = _rows(sleeve.db, 'sleeve_rallies')
    for row in rows:
        strategy = row['strategy']
        _require(strategy in sleeve.identity['policies'], 'native_restore_rally_strategy')
        regime = regime_for(strategy)
        cycle = validate_cycle(row['cycle'], candidate=row['candidate'], observation_at=row['last_observed_at'])
        _require(known_hash(regime, cycle['policy_hash']), 'native_restore_rally_policy')
        history = histories.get(regime)
        _require(history is not None, 'native_restore_rally_history_dependency')
        candidate = history.get(row['candidate'])
        _require(candidate is not None, 'native_restore_rally_graduation_missing')
        expected = digest(dict(candidate=str(row['candidate']), chain=cycle['chain'], venue=cycle['venue'],
                               pool=cycle['pool'], graduation=candidate['graduation']))
        _require(cycle['lineage'] == expected, 'native_restore_rally_lineage')
        for outcome in [row.get('last_traded'), *row.get('completed', [])]:
            if not outcome:
                continue
            validate_cycle(outcome['cycle'], candidate=row['candidate'])
            identity = outcome['identity']
            position = native_positions.get((sleeve.identity['lane'], identity))
            _require(position is not None and outcome.get('status') == 'settled'
                     and outcome.get('terminal_hash') == digest(position)
                     and sleeve.reentry_verified(identity) is not None,
                     'native_restore_rally_terminal_join')
    return digest(rows)


def _bidirectional_financial_memory(context, papers, capital, sleeves, histories):
    from .lifecycle_identity import parsed
    from .policy_compatibility import regime_for
    from .pons_terminal_archive import anchor
    native = {}
    scopes = {}
    strategies = {}
    for regime, book in papers.items():
        lane = regime.split('_')[0]
        strategies[regime] = book.identity['lane']
        scopes[regime] = (book._archive() or {}).get('archived_entry_scope')
        for row in _rows(book.db, 'positions'):
            key = (lane, row['id'])
            _require(key not in native, 'native_restore_duplicate_lifecycle')
            native[key] = (regime, row)
    with context.database(capital.path) as db:
        prefix = anchor(db) or {}
        scopes['pons_current'] = prefix.get('archived_entry_scope')
        from meme_machine.lanes.pons.pons_selective_ledger import STRATEGY_NAMESPACE
        strategies['pons_current'] = STRATEGY_NAMESPACE
        for row in _rows(db, 'capital_positions'):
            key = ('pons', row['id'])
            _require(key not in native, 'native_restore_duplicate_lifecycle')
            native[key] = ('pons_current', row['native_position'])
    state = context.ledger()
    for lane, sleeve in sleeves.items():
        for held in _rows(sleeve.db, 'sleeve_positions'):
            key = (lane, held['id'])
            _require(key in native and strategies[native[key][0]] == held['strategy'],
                     'native_restore_orphan_sleeve_position')
        for candidate in _rows(sleeve.db, 'sleeve_candidates'):
            regime = regime_for(candidate['strategy'])
            _require(strategies.get(regime) == candidate['strategy'],
                     'native_restore_sleeve_candidate_strategy')
            if regime.endswith('_survivor'):
                _require(histories[lane].get(candidate['id']) is not None,
                         'native_restore_orphan_survivor_memory')
    for key, lifecycle in state['native_aliases'].items():
        lane, identity = key.split(':', 1)
        position = state['positions'].get(lifecycle)
        request = state['requests'].get(state.get('runtime_native_requests', {}).get(key)) or {}
        regime = position['regime'] if position is not None else (request.get('value') or {}).get('regime')
        if position is None:
            _require(request.get('status') in ('CANCELLED','SUPERSEDED','QUALIFIED_BUT_CAPITAL_UNAVAILABLE'),
                     'native_restore_alias_position_missing')
            if (lane, identity) in native:
                _require(native[(lane, identity)][1].get('status') in ('cancelled','settled'),
                         'native_restore_alias_nonterminal_release')
        if regime not in strategies:
            # Paused/legacy financial inputs retain their separately required
            # original guard; this capability covers the four active regimes.
            continue
        if (lane, identity) in native:
            _require(native[(lane, identity)][0] == regime,
                     'native_restore_alias_regime_join')
            continue
        scope = scopes.get(regime)
        issued = parsed(identity)
        sleeve_scope = (sleeves[lane]._archive() or {}).get('archived_entry_scopes', {}).get(strategies[regime])
        _require(issued is not None and scope is not None and sleeve_scope == scope
                 and issued['epoch'] == scope['epoch'] and issued['index'] <= scope['through'],
                 'native_restore_alias_retirement_scope_missing')
    for (lane, identity), (regime, position) in native.items():
        alias = state['native_aliases'].get(lane+':'+identity)
        financial = state['positions'].get(alias)
        request = state['requests'].get(state.get('runtime_native_requests', {}).get(lane+':'+identity)) or {}
        actual_regime = financial.get('regime') if financial else (request.get('value') or {}).get('regime')
        _require(alias is not None and actual_regime == regime,
                 'native_restore_native_global_alias_missing')


def _classify_native_population(context):
    expected_papers = {context.root/path for path in PAPERS.values()}
    expected_histories = {context.root/path for path in HISTORIES.values()}
    expected_sleeves = {context.sleeve_path(lane) for lane in ('pump','pons')}
    capital = context.root/COHORT/'pons-selective-cohort-capital.sqlite'
    cohort = capital.parent
    for path in context.database_identities:
        with context.database(path) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 257")}
            _require(len(tables) <= 256, 'native_restore_schema_bound')
            if {'genesis','positions','journal'} <= tables:
                _require(path in expected_papers, 'native_restore_unmapped_paper_store')
            if {'sleeve_genesis','sleeve_positions','sleeve_journal'} <= tables:
                _require(path in expected_sleeves, 'native_restore_unmapped_sleeve_store')
            if {'meta','candidates','events','points'} <= tables:
                _require(path in expected_histories, 'native_restore_unmapped_history_store')
            if {'capital_genesis','capital_positions','capital_journal'} <= tables:
                _require(path == capital, 'native_restore_unmapped_capital_store')
            if {'records','pons_selective_paper'} <= tables:
                _require(path.parent == cohort and re.fullmatch(r'trial-\d+\.sqlite',path.name),
                         'native_restore_unmapped_trial_store')


def _native_memory_facts(read_context):
    """Internal original replay graph; never a boot/admission certificate."""
    context = require_read_context(read_context)
    context.verify_boundary()
    _classify_native_population(context)
    authority = context.authenticate_authority()
    sleeves = {lane: context.sleeve(lane) for lane in ('pump', 'pons')}
    papers = {regime: context.paper(context.root/path, regime) for regime, path in PAPERS.items()}
    for book in papers.values():
        _policy_memory(book)
        _archive(book._archive())
    for sleeve in sleeves.values():
        _archive(sleeve._archive())
    histories = {lane: context.history(context.root/path, lane) for lane, path in HISTORIES.items()}
    facts = {'pump_current': _pump_current(context, papers['pump_current'], sleeves['pump'])}
    for lane in ('pump', 'pons'):
        regime = lane + '_survivor'
        facts[regime] = _survivor(context, lane, papers[regime], sleeves[lane], histories[lane])
    capital, proof = context.capital(context.root/COHORT/'pons-selective-cohort-capital.sqlite')
    facts['pons_current'] = _pons_current(context, capital, context.root/PLANE)
    _bidirectional_financial_memory(context,papers,capital,sleeves,histories)
    history_by_regime = {lane+'_survivor': history for lane, history in histories.items()}
    native = {(regime.split('_')[0], row['id']):row
              for regime, book in papers.items() for row in _rows(book.db, 'positions')}
    rally_hashes = {lane: _rallies(context, sleeve, history_by_regime, native)
                    for lane, sleeve in sleeves.items()}
    context.verify_boundary()
    return dict(facts=facts, authority=authority, capital=proof, rallies=rally_hashes)


def validate_stopped_restore_closure(read_context):
    """Complete finite native-restart input graph, conditional on caller fences.

    No admission object is created and historical callbacks remain unresolved.
    An exception means UNKNOWN; a caller must discard every provisional fact.
    This strict capability is not a prerequisite invented for funding-closed
    boot: original actors can validate/repair nonauthoritative inputs there.
    """
    context = require_read_context(read_context)
    _native_memory_facts(context)
    # Do not certify a subset while source/discovery/qualification inputs are
    # still unmapped. This final closure phase must cover them before publishing.
    raise NativeDependencyUnavailable('native_restore_discovery_semantics_unimplemented')


def inspect_stopped_restore_memory(read_context):
    """Bounded public projection of the completed original-reducer ports.

    This result never certifies complete restore-input closure or boot/admission.
    Protected acquisition premises are supplied and rechecked by the caller;
    this application-only component cannot attest the source/census/fences.
    """
    facts = _native_memory_facts(read_context)
    return dict(schema='stopped-four-regime-native-memory-inputs-v1',
        state='VERIFIED_REDUCER_PORTS_WITH_UNIMPLEMENTED_INPUT_DEPENDENCIES',
        scope='CONDITIONAL_STOPPED_NATIVE_TERMINAL_CONTROLLER_REENTRY_AND_CYCLE_INPUTS',
        four_regimes=list(sorted(facts['facts'])),
        native_memory_reducer_ports_verified=True, native_input_closure_complete=False,
        unimplemented_input_dependencies=list(UNIMPLEMENTED_INPUT_DEPENDENCIES),
        state_sha256=digest(facts), dependency_roles=dict(DEPENDENCY_ROLES),
        acquisition_premise='ORIGINAL_CALLER_SOURCE_CENSUS_AND_STOPPED_FENCE_REQUIRED',
        current_native_resumability_verified=False,current_economic_authority_verified=False,
        qualification_authority=False,funding_authority=False,boot_authority=False,
        historical_handler_disposition_verified=False,historical_drain_reclassified=False,
        safe_for_normal=False,provider_requests=0,authoritative_writes=0,raw_content_exported=False)
