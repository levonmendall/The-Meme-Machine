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
MAX_CENSUS_PAGES = 16
MAX_CENSUS_ROWS = PAGE_LIMIT * MAX_CENSUS_PAGES
CENSUS_PAGE_DELAY_SECONDS = 1.0
DENSE_TRANSACTION_SERIAL_THRESHOLD = 8
DENSE_TRANSACTION_PACE_SECONDS = 1.0
ENDPOINT_DIAGNOSTICS = []


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


def _page_telemetry(prefix, page, start_slot, end_slot, target):
    target[prefix+'_count'] = len(page)
    target[prefix+'_newest_slot'] = None if not page else page[0]['slot']
    target[prefix+'_oldest_slot'] = None if not page else page[-1]['slot']
    target[prefix+'_successful_post_start'] = len(_successful_interval(page,start_slot,end_slot))
    target[prefix+'_has_start_boundary'] = any(sig['slot'] <= start_slot for sig in page)


def complete_signature_census(rpc, pool, start_slot, end_slot, telemetry=None):
    """Prove finalized signature coverage from end_slot back through start_slot.

    Pages newer than the authenticated endpoint are scheduling noise: they are scanned
    only to reach the endpoint and are never admitted to the verified interval. The
    census is bounded to MAX_CENSUS_PAGES/MAX_CENSUS_ROWS. Once it reaches the
    authenticated interval, every successful transaction in (start_slot, end_slot] is
    retained and MAX_TRANSACTIONS=16 remains unchanged. One finalized signature at or
    before start_slot proves the lower boundary.
    """
    if telemetry is None:
        telemetry = {}
    telemetry.update(
        census_page_limit=PAGE_LIMIT,
        census_page_cap=MAX_CENSUS_PAGES,
        census_row_cap=MAX_CENSUS_ROWS,
        census_page_delay_seconds=CENSUS_PAGE_DELAY_SECONDS,
        census_pages=[],
        post_endpoint_rows_skipped=0,
        fallback_attempted=False,
    )
    selected=[]
    boundary_sig=None
    seen=set()
    previous_oldest_key=None
    before=None
    rows_scanned=0

    for page_index in range(MAX_CENSUS_PAGES):
        if page_index:
            sleeper=getattr(rpc,'sleep',None)
            if callable(sleeper):
                sleeper(CENSUS_PAGE_DELAY_SECONDS)
        config=dict(limit=PAGE_LIMIT,commitment='finalized')
        if before is not None:
            config['before']=before
            telemetry['fallback_attempted']=True
        page=_validate_page(rpc.call(
            'getSignaturesForAddress',[pool,config],True))
        rows_scanned += len(page)
        if rows_scanned > MAX_CENSUS_ROWS:
            raise Unavailable('dlmm_signature_census_row_bound')

        if page:
            page_ids={sig['signature'] for sig in page}
            if len(page_ids)!=len(page) or seen.intersection(page_ids):
                raise Unavailable('dlmm_signature_census_pagination_duplicate')
            newest_key=_key(page[0]);oldest_key=_key(page[-1])
            if previous_oldest_key is not None and not newest_key < previous_oldest_key:
                raise Unavailable('dlmm_signature_census_pagination_order')
            previous_oldest_key=oldest_key
            seen.update(page_ids)

        item=dict(
            page=page_index+1,
            count=len(page),
            newest_slot=None if not page else page[0]['slot'],
            oldest_slot=None if not page else page[-1]['slot'],
            post_endpoint=sum(1 for sig in page if sig['slot']>end_slot),
            interval_successful=len(_successful_interval(page,start_slot,end_slot)),
            has_start_boundary=any(sig['slot']<=start_slot for sig in page),
        )
        telemetry['census_pages'].append(item)
        telemetry['post_endpoint_rows_skipped'] += item['post_endpoint']
        if page_index==0:
            _page_telemetry('first_page',page,start_slot,end_slot,telemetry)
        elif page_index==1:
            _page_telemetry('fallback_page',page,start_slot,end_slot,telemetry)

        selected.extend(_successful_interval(page,start_slot,end_slot))
        if len(selected)>MAX_TRANSACTIONS:
            raise Unavailable('dlmm_transaction_bound')

        candidates=[sig for sig in page if sig['slot']<=start_slot]
        if candidates:
            boundary_sig=max(candidates,key=_key)
            break
        if not page or len(page)<PAGE_LIMIT:
            break
        before=page[-1]['signature']

    telemetry['census_pages_used']=len(telemetry['census_pages'])
    telemetry['census_rows_scanned']=rows_scanned
    telemetry['combined_successful_post_start']=len(selected)
    telemetry['combined_has_start_boundary']=boundary_sig is not None
    if boundary_sig is None:
        telemetry['census_completed']=False
        if len(telemetry['census_pages'])>=MAX_CENSUS_PAGES and telemetry['census_pages'][-1]['count']==PAGE_LIMIT:
            raise Unavailable('dlmm_signature_census_page_bound')
        raise Unavailable('dlmm_signature_census_missing_start_boundary')
    if len({sig['signature'] for sig in selected})!=len(selected):
        raise Unavailable('dlmm_transaction_bound_or_duplicates')
    telemetry['boundary_slot']=boundary_sig['slot']
    telemetry['census_completed']=True
    proof=sorted(selected+[boundary_sig],key=_key,reverse=True)
    return proof


def _fetch_transaction_bodies(rpc, relevant, telemetry=None):
    """Fetch immutable finalized transaction bodies without dense batch bursts.

    Small intervals keep the existing <=4-item batching efficiency. Dense intervals
    (8..16 successful transactions) are serialized as ordinary single JSON-RPC
    requests with one-second spacing. Logical request count/evidence scope is
    unchanged; this only changes transport concurrency and avoids batch-item
    throughput collisions.
    """
    params=[[sig['signature'],dict(encoding='json',commitment='finalized',
                                  maxSupportedTransactionVersion=0)]
            for sig in relevant]
    if telemetry is None:
        telemetry={}
    if len(params) >= DENSE_TRANSACTION_SERIAL_THRESHOLD:
        telemetry['transaction_retrieval_mode']='serialized_single_getTransaction'
        telemetry['transaction_retrieval_pace_seconds']=DENSE_TRANSACTION_PACE_SECONDS
        values=[]
        for index,param in enumerate(params):
            if index:
                sleeper=getattr(rpc,'sleep',None)
                if callable(sleeper):
                    sleeper(DENSE_TRANSACTION_PACE_SECONDS)
            values.append(rpc.call('getTransaction',param,True))
        return values
    telemetry['transaction_retrieval_mode']='bounded_call_many_batch_size_4'
    telemetry['transaction_retrieval_pace_seconds']=None
    return rpc.call_many('getTransaction',params,True,batch_size=4)


def capture_chunk(adapter, start, cursor):
    """Capture one terminal-verified chunk with bounded start-boundary pagination."""
    rpc = adapter.rpc
    end_snapshot = adapter.snapshot(start['pool'], int(time.time()), True, fresh=True)
    telemetry = dict(
        pool=start['pool'],
        fresh_endpoint=True,
        start_slot=start['slot'],
        end_slot=end_snapshot['slot'],
        slot_advanced=end_snapshot['slot'] > start['slot'],
        start_time=start.get('time'),
        end_market_time=end_snapshot.get('market_time'),
        end_available_time=end_snapshot.get('available_time'),
    )
    # Append before signature-census processing so even a census failure retains the
    # exact authenticated endpoint slots that define the attempted interval.
    ENDPOINT_DIAGNOSTICS.append(telemetry)
    try:
        signatures = complete_signature_census(
            rpc, start['pool'], start['slot'], end_snapshot['slot'], telemetry=telemetry)
        relevant = [sig for sig in signatures
                    if start['slot'] < sig['slot'] <= end_snapshot['slot'] and not sig.get('err')]
        telemetry['transaction_count'] = len(relevant)
        if len(relevant) > MAX_TRANSACTIONS:
            raise Unavailable('dlmm_transaction_bound')
        values = _fetch_transaction_bodies(rpc,relevant,telemetry)
        transactions = {sig['signature']: tx for sig, tx in zip(relevant, values)}
        if len(encode(transactions)) > 2_000_000:
            raise Unavailable('dlmm_interval_evidence_bound')
        now = int(time.time())
        tape = reconstruct(start, end_snapshot, signatures, transactions, now, cursor)
        next_cursor = list(tape.events[-1]['cursor']) if tape.events else list(cursor)
        telemetry['capture_completed'] = True
        return tape, next_cursor, len(relevant)
    except (Unavailable, ValueError, KeyError, TypeError) as exc:
        telemetry.setdefault('census_completed', False)
        telemetry['capture_completed'] = False
        telemetry['capture_error'] = str(exc)
        raise
