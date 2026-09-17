"""One bounded fallback page for DLMM signature start-boundary proof.

This module changes only signature-census acquisition for the research replay. The
core verifier, finalized commitment, MAX_TRANSACTIONS=16, transaction bodies, strategy,
costs and allocation authority are unchanged. A second page is requested only when
the first page contains at most 16 successful post-start transactions but does not
reach a signature at or before the authenticated starting snapshot slot.
"""
from __future__ import annotations

import time

from meme_machine.dlmm_tape import MAX_TRANSACTIONS, reconstruct
from meme_machine.provider import Unavailable
from meme_machine.store import encode

PAGE_LIMIT = 64


def _key(sig):
    if not isinstance(sig, dict):
        raise Unavailable('dlmm_signature_census_shape')
    signature = sig.get('signature')
    slot = sig.get('slot')
    transaction_index = sig.get('transactionIndex')
    if not isinstance(signature, str) or not signature:
        raise Unavailable('dlmm_signature_census_shape')
    if type(slot) is not int or slot < 0:
        raise Unavailable('dlmm_signature_census_shape')
    if type(transaction_index) is not int or transaction_index < 0:
        raise Unavailable('dlmm_transaction_index_unavailable')
    if sig.get('confirmationStatus') != 'finalized':
        raise Unavailable('dlmm_signature_not_finalized')
    return slot, transaction_index


def _validate_page(page):
    if not isinstance(page, list) or len(page) > PAGE_LIMIT:
        raise Unavailable('dlmm_signature_census_shape')
    signatures = []
    keys = []
    for sig in page:
        keys.append(_key(sig))
        signatures.append(sig['signature'])
    if len(set(signatures)) != len(signatures):
        raise Unavailable('dlmm_signature_census_duplicates')
    if keys != sorted(keys, reverse=True):
        raise Unavailable('dlmm_signature_order')
    return page


def _successful_interval(signatures, start_slot, end_slot):
    return [sig for sig in signatures
            if start_slot < sig['slot'] <= end_slot and not sig.get('err')]


def complete_signature_census(rpc, pool, start_slot, end_slot):
    """Return complete successful interval signatures plus one start-boundary anchor.

    The fallback page is boundary-only acquisition. It cannot increase the accepted
    transaction count: if pagination reveals more than MAX_TRANSACTIONS successful
    post-start transactions, the interval still fails closed before any transaction
    bodies are fetched.
    """
    first = _validate_page(rpc.call(
        'getSignaturesForAddress',
        [pool, dict(limit=PAGE_LIMIT, commitment='finalized')],
        True,
    ))
    combined = list(first)
    selected = _successful_interval(combined, start_slot, end_slot)
    if len(selected) > MAX_TRANSACTIONS:
        raise Unavailable('dlmm_transaction_bound')

    if not any(sig['slot'] <= start_slot for sig in combined):
        if not combined:
            raise Unavailable('dlmm_signature_census_missing_start_boundary')
        oldest = combined[-1]['signature']
        second = _validate_page(rpc.call(
            'getSignaturesForAddress',
            [pool, dict(limit=PAGE_LIMIT, before=oldest, commitment='finalized')],
            True,
        ))
        first_ids = {sig['signature'] for sig in combined}
        if any(sig['signature'] in first_ids for sig in second):
            raise Unavailable('dlmm_signature_census_pagination_duplicate')
        combined.extend(second)
        keys = [_key(sig) for sig in combined]
        if keys != sorted(keys, reverse=True):
            raise Unavailable('dlmm_signature_census_pagination_order')
        selected = _successful_interval(combined, start_slot, end_slot)
        if len(selected) > MAX_TRANSACTIONS:
            raise Unavailable('dlmm_transaction_bound')
        if not any(sig['slot'] <= start_slot for sig in combined):
            raise Unavailable('dlmm_signature_census_missing_start_boundary')

    if len({sig['signature'] for sig in selected}) != len(selected):
        raise Unavailable('dlmm_transaction_bound_or_duplicates')
    boundary = max((sig for sig in combined if sig['slot'] <= start_slot), key=_key)
    proof = sorted(selected + [boundary], key=_key, reverse=True)
    return proof


def capture_chunk(adapter, start, cursor):
    """Capture one terminal-verified chunk with bounded start-boundary pagination."""
    rpc = adapter.rpc
    end_snapshot = adapter.snapshot(start['pool'], int(time.time()), True, fresh=True)
    signatures = complete_signature_census(
        rpc, start['pool'], start['slot'], end_snapshot['slot'])
    relevant = [sig for sig in signatures
                if start['slot'] < sig['slot'] <= end_snapshot['slot'] and not sig.get('err')]
    if len(relevant) > MAX_TRANSACTIONS:
        raise Unavailable('dlmm_transaction_bound')
    params = [[sig['signature'], dict(encoding='json', commitment='finalized',
                                      maxSupportedTransactionVersion=0)]
              for sig in relevant]
    values = rpc.call_many('getTransaction', params, True, batch_size=4)
    transactions = {sig['signature']: tx for sig, tx in zip(relevant, values)}
    if len(encode(transactions)) > 2_000_000:
        raise Unavailable('dlmm_interval_evidence_bound')
    now = int(time.time())
    tape = reconstruct(start, end_snapshot, signatures, transactions, now, cursor)
    next_cursor = list(tape.events[-1]['cursor']) if tape.events else list(cursor)
    return tape, next_cursor, len(relevant)
