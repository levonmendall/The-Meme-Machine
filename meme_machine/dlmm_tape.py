"""Bounded finalized swap-only interval reconstruction.

Snapshots bracket the interval. Signature census must reach the starting slot;
every intervening pool transaction must be readable. Reject LP mutations, unknown
instructions, exact-out, host fees, truncated logs and ambiguous same-slot order.
The terminal snapshot only validates the forward calculation; it never supplies
earlier inventory or fees. Any discrepancy rejects the entire interval.
"""
import base64
from copy import deepcopy
from dataclasses import dataclass
import struct

from . import dlmm,pump
from .provider import Unavailable
from .store import digest,encode

SWAP = bytes([81,108,227,190,205,208,10,196])
EXACT_IN = {bytes([248,198,158,145,225,117,135,200]),bytes([65,75,63,76,235,91,91,136])}
EVENT_CPI = bytes.fromhex('e445a52e51cb9a1d')
MAX_TRANSACTIONS = 16


def _un58_data(s):
    # Instruction data is variable length; pump.un58 is public-key-only.
    n=0
    for ch in s:n=n*58+pump.ALPHABET.index(ch)
    return bytes(len(s)-len(s.lstrip('1')))+(n.to_bytes((n.bit_length()+7)//8,'big') if n else b'')


def decode_swap(raw,pool):
    if len(raw)!=137 or raw[:8]!=SWAP or pump.b58(raw[8:40])!=pool or raw[96] not in (0,1):
        raise ValueError('dlmm_swap_event_layout_or_identity')
    start,end,amount,output,direction,fee,protocol=struct.unpack_from('<iiQQ?QQ',raw,72)
    if int.from_bytes(raw[129:137],'little'):
        raise Unavailable('dlmm_host_fee_unsupported')
    return dict(amount=amount,for_y=direction,
                observed=dict(start=start,end=end,output=output,fee=fee,protocol_fee=protocol))


def transaction_swap(tx,pool):
    if not tx or not tx.get('meta') or tx['meta'].get('err'):
        raise Unavailable('dlmm_missing_or_failed_transaction')
    meta=tx['meta'];message=tx['transaction']['message']
    keys=message['accountKeys']+meta.get('loadedAddresses',{}).get('writable',[])+meta.get('loadedAddresses',{}).get('readonly',[])
    if pool not in keys or len(keys)>256:
        raise ValueError('dlmm_transaction_pool_identity')
    instructions=list(message['instructions'])
    if meta.get('innerInstructions') is None:
        raise Unavailable('dlmm_missing_inner_instructions')
    for group in meta['innerInstructions']:instructions.extend(group['instructions'])
    calls=[];events=[]
    for instruction in instructions:
        if keys[instruction['programIdIndex']]!=dlmm.PROGRAM:continue
        raw=_un58_data(instruction['data'])
        if raw[:8] in EXACT_IN:
            if len(raw)<24 or keys[instruction['accounts'][0]]!=pool:
                raise ValueError('dlmm_swap_instruction_identity')
            calls.append(raw)
        elif raw[:8]==EVENT_CPI:
            events.append(decode_swap(raw[8:],pool))
        else:
            raise Unavailable('dlmm_non_swap_mutation_in_interval')
    if len(calls)!=1:
        raise Unavailable('dlmm_requires_one_exact_input_swap_per_transaction')
    if not events:
        stack=[]
        for line in meta.get('logMessages') or []:
            if 'Log truncated' in line:raise Unavailable('dlmm_truncated_logs')
            if line.startswith('Program ') and ' invoke [' in line:stack.append(line.split()[1])
            elif line.startswith('Program ') and (' success' in line or ' failed:' in line):
                if not stack or stack.pop()!=line.split()[1]:raise ValueError('dlmm_log_stack')
            elif line.startswith('Program data: ') and stack and stack[-1]==dlmm.PROGRAM:
                raw=base64.b64decode(line[14:],validate=True)
                if raw[:8]==SWAP:events.append(decode_swap(raw,pool))
        if stack:raise Unavailable('dlmm_incomplete_logs')
    if len(events)!=1:raise Unavailable('dlmm_missing_or_ambiguous_swap_event')
    e=events[0]
    amount,minimum=struct.unpack_from('<QQ',calls[0],8)
    # Direction is emitted by the verified DLMM invocation, not a swap argument.
    if e['amount']!=amount or e['observed']['output']<minimum:
        raise ValueError('dlmm_instruction_event_mismatch')
    if tx.get('blockTime') is None:raise Unavailable('dlmm_missing_transaction_time')
    return dict(**e,time=tx['blockTime'],slot=tx['slot'])


@dataclass(frozen=True)
class VerifiedTape:
    start_hash: str
    end_hash: str
    events: tuple
    terminal: dict
    lineage: str


def reconstruct(start,end_snapshot,signatures,transactions,now,cursor):
    if len(signatures)>64 or len(transactions)>MAX_TRANSACTIONS or len(encode(transactions))>2_000_000:
        raise Unavailable('dlmm_interval_evidence_bound')
    if any(s.get('confirmationStatus')!='finalized' for s in signatures):
        raise Unavailable('dlmm_signature_not_finalized')
    if [s['slot'] for s in signatures]!=sorted((s['slot'] for s in signatures),reverse=True):
        raise Unavailable('dlmm_signature_order')
    # History may arrive after the current-quote TTL. Validate that the endpoint
    # was fresh when captured, never treat it as executable evidence at `now`.
    # Replay.mark independently applies the unchanged 20-second current-state TTL.
    if end_snapshot['available_time']>now:
        raise ValueError('dlmm_future_endpoint')
    end=dlmm.validate(end_snapshot,end_snapshot['available_time'],'real')
    if end['pool']!=start['pool'] or end['slot']<=start['slot'] or end['time']-start['time']>60:
        raise Unavailable('dlmm_interval_identity_or_age')
    if not any(sig['slot']<=start['slot'] for sig in signatures):
        raise Unavailable('dlmm_signature_census_missing_start_boundary')
    selected=[s for s in signatures if start['slot']<s['slot']<=end['slot'] and not s.get('err')]
    if len(selected)>MAX_TRANSACTIONS or len({s['signature'] for s in selected})!=len(selected):
        raise Unavailable('dlmm_transaction_bound_or_duplicates')
    if len({s['slot'] for s in selected})!=len(selected):
        raise Unavailable('dlmm_same_slot_transaction_order_unavailable')
    state=deepcopy(start);events=[];previous=list(cursor)
    for sig in sorted(selected,key=lambda s:s['slot']):
        tx=transactions.get(sig['signature'])
        if not tx or tx['transaction']['signatures'][0]!=sig['signature'] or tx['slot']!=sig['slot']:
            raise Unavailable('dlmm_transaction_missing_or_identity')
        e=transaction_swap(tx,start['pool'])
        if not state['time']<=e['time']<=end['time']:
            raise ValueError('dlmm_transaction_time_outside_interval')
        prehash=digest(state);state,quote=dlmm.swap(state,e['amount'],e['for_y'],e['time'])
        if any(e['observed'][k]!=quote[k] for k in ('start','end','output','fee','protocol_fee')):
            raise Unavailable('dlmm_observed_swap_cannot_be_reconstructed')
        next_cursor=[e['slot'],0,0];state['slot']=e['slot']
        events.append(dict(kind='real',commitment='finalized',pool=start['pool'],
            cursor=next_cursor,previous_cursor=previous,prestate_hash=prehash,
            amount=e['amount'],for_y=e['for_y'],time=e['time'],available_time=now,
            observed=e['observed'],signature=sig['signature']))
        previous=next_cursor
    # Same array footprint is required: no invisible liquidity enters the model.
    for key in set(state)-{'time','slot'}:
        if state[key]!=end[key]:
            raise Unavailable('dlmm_terminal_state_disagrees_with_forward_reconstruction:'+key)
    return VerifiedTape(digest(start),digest(end),tuple(events),end,
                        digest(dict(start=start,end=end_snapshot,signatures=signatures,transactions=transactions)))


def capture(adapter,start,end_snapshot,now,cursor):
    rpc=adapter.rpc
    signatures=rpc.call('getSignaturesForAddress',[start['pool'],dict(limit=64,commitment='finalized')],True)
    relevant=[s for s in signatures if start['slot']<s['slot']<=end_snapshot['slot'] and not s.get('err')]
    if len(relevant)>MAX_TRANSACTIONS:raise Unavailable('dlmm_transaction_bound')
    transactions={}
    for sig in relevant:
        transactions[sig['signature']]=rpc.call('getTransaction',[sig['signature'],
            dict(encoding='json',commitment='finalized',maxSupportedTransactionVersion=0)],True)
        if len(encode(transactions))>2_000_000:
            raise Unavailable('dlmm_interval_evidence_bound')
    return reconstruct(start,end_snapshot,signatures,transactions,now,cursor)
