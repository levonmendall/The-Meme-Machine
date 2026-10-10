"""Offline integration boundaries only. No operational module imports this file.

These plans do not fetch, publish canonical coverage, authorize a quote, or turn
on a provider capability. The existing native readers remain the fallback.
"""
from copy import deepcopy


def account_union_plan(views,*,max_positions=32,max_accounts=100):
    if not views or len(views)>max_positions:return None
    keys=[];partitions={};context=None
    for consumer,view in views.items():
        current=tuple(view.get(k) for k in ('provider_fingerprint','source_generation','commitment','slot','available_at','deadline'))
        if any(v is None for v in current) or current[2]!='finalized':return None
        if context is not None and current!=context:return None
        context=current;indices=[]
        for key in view['accounts']:
            if key not in keys:keys.append(key)
            indices.append(keys.index(key))
        partitions[consumer]=tuple(indices)
    if len(keys)>max_accounts:return None
    return dict(accounts=tuple(keys),partitions=partitions,context=context)


def partition_snapshot(plan,response,*,now):
    if plan is None:raise ValueError('shared_snapshot_original_fallback')
    fingerprint,generation,commitment,slot,available,deadline=plan['context']
    if (not available<=now<=deadline or response.get('context',{}).get('slot')!=slot
            or not isinstance(response.get('value'),list) or len(response['value'])!=len(plan['accounts'])
            or any(value is None for value in response['value'])):
        raise ValueError('shared_snapshot_original_fallback')
    # Each native validator owns an independent view, including every requested
    # mint/authority/reserve/fee field. Concentration is separate original work.
    return {consumer:dict(context=deepcopy(response['context']),
        value=[deepcopy(response['value'][i]) for i in indices]) for consumer,indices in plan['partitions'].items()}


def ordered_canonical_events(events):
    """Prepublication order guard; native receipt/range membership is still required."""
    keys=[]
    for event in events:
        if event.get('removed'):raise ValueError('shared_canonical_removed_event')
        key=tuple(int(event[k],16) for k in ('blockNumber','transactionIndex','logIndex'))
        if key in keys:raise ValueError('shared_canonical_duplicate_or_conflict')
        keys.append(key)
    if keys!=sorted(keys):raise ValueError('shared_canonical_publication_order')
    return tuple(deepcopy(events))


def adaptive_receipt_plan(relevant_count,total_transactions,*,capability,identity,remaining_seconds):
    from meme_machine.lanes.pons.immutable_rpc import choose_block_receipts
    proven=bool(capability and identity and capability.get('authenticated') is True
        and all(capability.get(k)==identity.get(k) and identity.get(k) is not None
            for k in ('provider_fingerprint','chain_id','source_generation','block_hash'))
        and capability.get('eth_getBlockReceipts') is True)
    return 'block_receipts' if choose_block_receipts(relevant_count,total_transactions,
        supported=proven,remaining_seconds=remaining_seconds) else 'individual_receipts'
