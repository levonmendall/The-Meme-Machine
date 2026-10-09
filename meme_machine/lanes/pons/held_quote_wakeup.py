"""Fail-closed Pons held-position event/quote scheduler, offline candidate.

No provider, subscription, admission, funding or execution work. Only an
authenticated canonical manager+hook+token adapter may supply a WindowProof.
Absent that adapter (current production), QUOTE_NOW is always returned.
QUIET_HOLD_ONLY is never permission to mark, sell, extend or requalify using
an expired quote. The original 3s/5s protective tick remains authoritative.
"""
from dataclasses import dataclass
from functools import lru_cache
import math

from .abi import signature, topic
from .identity import load

_MANAGER = 'uniswap_v4_manager'
_HOOK = 'pons_v2_hook'
_MANAGER_POOL = frozenset(('Swap', 'ModifyLiquidity', 'Donate',
                          'Initialize', 'ProtocolFeeUpdated'))
_HOOK_POOL = frozenset(('HookFeeCollected', 'BuybackEnabledUpdated',
                       'CreatorFeeRecipientUpdated', 'PoolBuybackSkipped',
                       'PoolConversionSkipped', 'PoolFeesRescued',
                       'PoolFeesSwept', 'PoolRegistered'))
_MAX_QUOTE_AGE_SECONDS = 60
_MAX_PROOF_AGE_SECONDS = 5
_MIN_RISK_DISTANCE_BPS = 1000


@lru_cache(maxsize=2)
def _events(role):
    pin = load(role)
    topics = {}
    for event in pin['abi']:
        if event.get('type') == 'event':
            topics[topic(signature(event)).lower()] = (
                event['name'], bool(event.get('inputs')) and
                event['inputs'][0].get('indexed') is True)
    return pin['address'].lower(), topics


def classify_native_log(log, pool_id):
    """Pool-specific WAKE, OTHER_POOL, OTHER_CONTRACT, or UNKNOWN.

    Unknown or global manager/hook logs always wake. A notification is not a
    complete canonical interval, even if it is categorized successfully.
    """
    if not isinstance(log, dict):
        return 'UNKNOWN'
    address = str(log.get('address', '')).lower()
    manager, manager_topics = _events(_MANAGER)
    hook, hook_topics = _events(_HOOK)
    if address not in (manager, hook):
        return 'OTHER_CONTRACT'
    topics = log.get('topics')
    if not isinstance(topics, list) or not topics or not isinstance(topics[0], str):
        return 'UNKNOWN'
    event = (manager_topics if address == manager else hook_topics).get(topics[0].lower())
    if event is None:
        return 'UNKNOWN'
    name, indexed_pool = event
    pool_events = _MANAGER_POOL if address == manager else _HOOK_POOL
    if name not in pool_events:
        return 'WAKE'
    if not indexed_pool or len(topics) < 2 or not isinstance(topics[1], str):
        return 'UNKNOWN'
    requested = str(pool_id).lower()
    if not requested.startswith('0x') or len(requested) != 66:
        return 'UNKNOWN'
    return 'WAKE' if topics[1].lower() == requested else 'OTHER_POOL'


@dataclass(frozen=True)
class WindowProof:
    """An authenticated, sealed full-mutation interval, not a WS hint.

    Completeness must include manager Swap/ModifyLiquidity/Donate/fee events,
    hook pool/global fee and control events, and token state semantics.
    No code in this module manufactures any of these claims.
    """
    pool_id: str
    quote_block: int
    quote_block_hash: str
    through_block: int
    through_hash: str
    observed_monotonic: float
    source: str
    canonical_contiguous: bool
    exact_manager_scope_complete: bool
    exact_hook_scope_complete: bool
    token_behavior_proven: bool
    gas_and_fee_bound_valid: bool
    mutation_count: int
    unknown_count: int


@dataclass(frozen=True)
class QuotePlan:
    decision: str
    reason: str
    may_publish_new_mark: bool = False
    may_execute_with_previous_quote: bool = False

    @property
    def request_fresh_quote(self):
        return self.decision == 'QUOTE_NOW'


def _quote(reason):
    return QuotePlan('QUOTE_NOW', reason)


def plan_held_quote(*, pool_id, quantity, quote, proof, current_head,
                    now_monotonic, risk_distance_bps, pending_exit=False,
                    pending_partial=False, scale_or_requalification=False,
                    renewal_due=False, cadence_seconds=3,
                    maximum_quote_age_seconds=60):
    """Return safe scheduling decision, never an economic mark or fill.

    The caller must preserve native protective evaluation at original cadence.
    A quiet interval can skip a QUOTE request only with all original price
    protection proven distant from its threshold. Missing information buys a
    fresh quote, not a fictional last-price mark or a time-limit extension.
    """
    if cadence_seconds not in (3, 5):
        return _quote('original_safety_cadence_required')
    if (type(maximum_quote_age_seconds) is not int or
            not 5 <= maximum_quote_age_seconds <= _MAX_QUOTE_AGE_SECONDS):
        return _quote('quote_heartbeat_bounds_invalid')
    if pending_exit or pending_partial:
        return _quote('pending_execution_is_fresh')
    if scale_or_requalification or renewal_due:
        return _quote('fresh_strategy_or_renewal_evidence_required')
    if not isinstance(quote, dict) or not isinstance(proof, WindowProof):
        return _quote('authenticated_quote_and_window_missing')
    if type(quantity) is not int or quantity <= 0 or quote.get('quantity') != quantity:
        return _quote('exact_remaining_quantity_required')
    if (quote.get('pool_id') != pool_id or quote.get('block') != proof.quote_block
            or quote.get('block_hash') != proof.quote_block_hash):
        return _quote('quote_identity_disagreement')
    try:
        quote_age = float(now_monotonic) - float(quote['acquired'])
        proof_age = float(now_monotonic) - float(proof.observed_monotonic)
    except (TypeError, ValueError, KeyError, OverflowError):
        return _quote('age_incomplete')
    if (not math.isfinite(quote_age) or not 0 <= quote_age < maximum_quote_age_seconds
            or not math.isfinite(proof_age) or
            not 0 <= proof_age <= _MAX_PROOF_AGE_SECONDS):
        return _quote('heartbeat_or_event_evidence_stale')
    if (type(risk_distance_bps) is not int or
            risk_distance_bps <= _MIN_RISK_DISTANCE_BPS):
        return _quote('near_protective_exit')
    if (proof.source != 'authenticated_canonical_manager_hook_and_token' or
            proof.pool_id != pool_id):
        return _quote('authoritative_scope_missing')
    if (not isinstance(current_head, dict) or
            type(current_head.get('number')) is not int or
            not isinstance(current_head.get('hash'), str)):
        return _quote('fresh_canonical_head_missing')
    if (type(proof.quote_block) is not int or proof.quote_block < 0
            or type(proof.through_block) is not int
            or proof.through_block < proof.quote_block
            or proof.through_block != current_head['number']
            or proof.through_hash != current_head['hash']
            or not proof.quote_block_hash):
        return _quote('canonical_frontier_invalid')
    if not all((proof.canonical_contiguous, proof.exact_manager_scope_complete,
                proof.exact_hook_scope_complete, proof.token_behavior_proven,
                proof.gas_and_fee_bound_valid)):
        return _quote('complete_mutation_or_cost_evidence_missing')
    if (type(proof.mutation_count) is not int or
            type(proof.unknown_count) is not int or
            proof.mutation_count < 0 or proof.unknown_count < 0):
        return _quote('mutation_accounting_invalid')
    if proof.mutation_count or proof.unknown_count:
        return _quote('pool_or_fee_mutation_requires_quote')
    return QuotePlan('QUIET_HOLD_ONLY',
                     'complete_unchanged_interval_no_mark_or_execution')


def modeled_quote_elements(*, hours, every_seconds, elements_per_quote=6):
    """Offline arithmetic, no claim about actual billed CU or provider limits."""
    if hours < 0 or every_seconds <= 0 or elements_per_quote <= 0:
        raise ValueError('invalid_held_cost_model')
    turns = math.ceil(hours * 3600 / every_seconds)
    return dict(turns=turns, quote_elements=turns * elements_per_quote)
