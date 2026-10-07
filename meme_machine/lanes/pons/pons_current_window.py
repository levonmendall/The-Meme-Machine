"""Canonical coverage of exactly the frozen Current demand window.

Public observations are hints, not a proof that no trade was omitted. Query only
the selected curve, then let the existing receipt/header decoder authenticate
every member. Missing ranges and provider pressure are evidence failures.
"""
from . import BoundaryError
from .abi import topic


def canonical_window(context, candidate, *, seconds=60):
    from .pons_selective_acquisition import _header_search
    block = int(candidate['block'])
    at = int(candidate['stamp'].event_at)
    header = candidate['header']
    if int(header['number'], 16) != block or int(header['timestamp'], 16) != at:
        raise BoundaryError('pons_current_window_anchor_identity')
    cache = dict(context.cache.headers_by_number)
    cache[block] = header
    # Include every block at the inclusive lower timestamp, even when several
    # blocks share that timestamp. Searching the last block <= the boundary
    # itself would omit earlier trades in the same second.
    lower = max(0, at-seconds)
    first = 0 if lower == 0 else int(_header_search(context, block, at, lower-1, cache)['number'], 16)+1
    for witness in cache.values():
        context.cache.remember_header(witness)
    signatures = [
        topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)'),
        topic('CurveSell(address,address,uint256,uint256,uint256,uint256)'),
    ]
    calls = [('eth_getLogs', [dict(address=candidate['curve'].lower(),
        fromBlock=hex(start), toBlock=hex(min(block, start+9)), topics=[signatures])])
        for start in range(first, block+1, 10)]
    pages = context.batch(calls, 'pons_selective_window_coverage')
    if not isinstance(pages, list) or len(pages) != len(calls):
        raise BoundaryError('pons_current_window_range_incomplete')
    unique = {}
    for (_, params), page in zip(calls, pages):
        if not isinstance(page, list):
            raise BoundaryError('pons_current_window_range_incomplete')
        query = params[0]
        for event in page:
            if (event.get('removed') or event.get('address', '').lower() != candidate['curve'].lower()
                    or not int(query['fromBlock'], 16) <= int(event['blockNumber'], 16) <= int(query['toBlock'], 16)
                    or not event.get('topics') or event['topics'][0].lower() not in signatures):
                raise BoundaryError('pons_current_window_log_identity')
            identity = (event['transactionHash'], event['logIndex'])
            if identity in unique and unique[identity] != event:
                raise BoundaryError('pons_current_window_log_conflict')
            unique[identity] = event
    raw = sorted(unique.values(), key=lambda e: (int(e['blockNumber'], 16),
        int(e['transactionIndex'], 16), int(e['logIndex'], 16)))
    # A complete canonical range, including empty blocks, supplies absence proof.
    context.window_coverage = dict(complete=True, authority='canonical_alchemy_getLogs',
        from_block=first, through_block=block, through_hash=header['hash'],
        from_time=lower, through_time=at, events=len(raw))
    return raw
