"""Post-publication no-allocation gates used by the real native runners.

These gates do not provide a complete bootstrap, financial book, held position
or provider capability. Explicit resources verify their owned committed native
evidence before retaining the native funding-denial observation.
"""
import json
from dataclasses import asdict,is_dataclass

from meme_machine.runtime.isolated_native_resources import require_resources
from meme_machine.runtime.journal import canonical


def _native_result(value):
    # Broker.finish persists typed CurveState/Stamp values as dataclasses;
    # fresh hydration and committed replay both return those native types.
    def encode(item):
        if is_dataclass(item):return asdict(item)
        raise TypeError(type(item).__name__)
    return json.loads(json.dumps(value,default=encode))


def unsupported_bootstrap(native_resources):
    """Refuse explicit isolated startup before any native financial creation."""
    if native_resources is not None:
        require_resources(native_resources)
        raise ValueError('isolated_native_full_bootstrap_unsupported')


def _require_qualified_attempt(attempts, candidate, generation, decision):
    wanted = canonical(decision)
    if not any(row['generation'] == generation and row['phase'] == 'qualification'
               and row['category'] == 'QUALIFIED' and canonical(row['decision']) == wanted
               for row in attempts.rows(candidate)):
        raise ValueError('isolated_native_qualified_attempt_required')


def require_survivor_resources(runtime, lane):
    resources = getattr(runtime, 'native_resources', None)
    if resources is None:
        return None
    resources = require_resources(resources)
    if getattr(runtime, 'book', None) is not None:
        raise ValueError('isolated_native_financial_book_present')
    resources.require_survivor_history(runtime.history, lane)
    resources.require_observation_state(runtime.sleeve, lane)
    if lane == 'pons':
        resources.require_pons_plane(runtime.plane)
        if runtime.attempts.plane is not runtime.plane:
            raise ValueError('isolated_native_pons_plane_owner')
    elif getattr(runtime, 'candidate_history', None) is not resources.candidate_history():
        raise ValueError('isolated_native_history_owner')
    return resources


def survivor_allocation_allowed(runtime, row, decision, *, lane, policy):
    resources = require_survivor_resources(runtime, lane)
    if resources is None:
        return True
    if runtime.history.db.in_transaction:
        raise ValueError('isolated_native_uncommitted_qualification')
    saved = runtime.history.get(row['id'])
    if (not saved or canonical(saved) != canonical(row) or row.get('position')
            or canonical(row.get('decision')) != canonical(decision)
            or decision.get('candidate') is not True):
        raise ValueError('isolated_native_survivor_qualification_required')
    shared = resources.candidate_history()
    if lane == 'pump':
        if getattr(runtime, 'candidate_history', None) is not shared:
            raise ValueError('isolated_native_history_owner')
        decision_id = row.get('decision_id')
    else:
        resources.require_pons_plane(runtime.plane)
        if runtime.attempts.plane is not runtime.plane or runtime.plane.db.in_transaction:
            raise ValueError('isolated_native_uncommitted_qualification')
        key = 'pons:survivor:'+row['id']
        native = runtime.plane.get(key)
        if (not native or native['generation'] != row.get('plane_generation')
                or canonical(json.loads(native['payload'])) != canonical(decision)):
            raise ValueError('isolated_native_survivor_plane_qualification_required')
        _require_qualified_attempt(runtime.attempts, row['id'],
            row.get('qualification_attempt',0), decision)
        decision_id = shared.record_decision('pons', row['id'], mode='survivor',
            observed_at=int(native['observed']), qualified=True,
            decision=dict(qualification=decision,policy_hash=policy))
    denial = resources.deny_qualified(shared, decision_id, lane, row['id'],
        mode='survivor', at=int(resources.clock()), qualification=decision)
    if lane == 'pons':
        runtime.attempts.record(row['id'],row.get('generation',0),'funding','OTHER_EXPLICIT_REASON',
            at=denial['at'],reason=denial['reason'],execution=dict(
                entry_authorized=False,qualification_preserved=True,allocation_authority=False))
    row.update(state='qualified_but_allocation_denied', funding_denial=denial)
    runtime.history.save(row)
    runtime.sleeve.opportunity(row['id'], identity=row['id'], regime='survivor',
        status=row['state'], at=denial['at'], decision=dict(decision,
            funding_reason=denial['reason']))
    return False


def current_pons_allocation_allowed(queue, scheduled, evaluation, attempts, *,
                                    native_resources=None):
    if native_resources is None:
        return True
    resources = require_resources(native_resources)
    resources.require_pons_plane(queue.plane)
    if attempts.plane is not queue.plane or queue.plane.db.in_transaction:
        raise ValueError('isolated_native_uncommitted_qualification')
    identity = scheduled['key']
    generation = scheduled['work']['generation']
    if evaluation['vector'].get('current_threshold_pass') is not True:
        raise ValueError('isolated_native_current_qualification')
    # The existing result and qualified transition must both be committed.
    # Serialize this owned connection; native helpers retain their own writer
    # transactions and recheck the generation before the final transition.
    with queue.plane.lock:
        native = queue.plane.get(identity)
        if (not native or native['generation'] != generation or native['state'] != 'qualified'
                or native['completed'] != native['desired'] or not native['result']
                or canonical(json.loads(native['result'])) != canonical(_native_result(evaluation))
                or queue.clock() >= native['deadline']):
            raise ValueError('isolated_native_current_plane_qualification_required')
        matching = [row for row in attempts.rows(identity) if row['generation'] == generation
            and row['phase'] == 'qualification' and row['category'] == 'QUALIFIED']
        if not any(canonical({key:value for key,value in row['decision'].items()
                             if key != 'reentry_explanation'}) == canonical(evaluation['vector'])
                   for row in matching):
            raise ValueError('isolated_native_qualified_attempt_required')
        shared = resources.candidate_history()
        decision_id = shared.record_decision('pons', evaluation['token'], mode='current',
            observed_at=int(evaluation['evaluation_completed_at']), qualified=True,
            decision=dict(vector=evaluation['vector'], stage='full_point_in_time',
                          native_candidate=identity, native_generation=generation))
        denial = resources.deny_qualified(shared, decision_id, 'pons', evaluation['token'],
            mode='current', at=int(resources.clock()), vector=evaluation['vector'],
            stage='full_point_in_time')
        attempts.record(identity, generation, 'funding', 'OTHER_EXPLICIT_REASON',
            at=denial['at'], reason=denial['reason'], execution=dict(
                entry_authorized=False, qualification_preserved=True,
                allocation_authority=False, decision_id=decision_id))
        if not queue.plane.decision(identity, generation, 'funding_denied', denial['reason']):
            raise ValueError('isolated_native_current_generation_changed')
    return False
