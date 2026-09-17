"""Bounded finalized DLMM interval reconstruction.

Snapshots bracket every verified interval. Signature census must reach the starting
slot and every intervening pool transaction must be readable and ordered. Supported
exact-input swaps are replayed in authenticated execution order, including multiple
swaps in one transaction. Unknown pool mutations, exact-out, host fees, truncated
logs and incomplete ordering fail closed. Terminal state only validates forward
reconstruction; it never supplies earlier inventory or fees.
"""
import base64
from copy import deepcopy
from dataclasses import dataclass
import struct

from . import dlmm,pump
from .provider import Unavailable
from .store import digest,encode

SWAP = bytes([81,108,227,190,205,208,10,196])
SWAP2 = bytes.fromhex('2e7452d7941b544d')
SWAP_IX = bytes([248,198,158,145,225,117,135,200])
SWAP2_IX = bytes([65,75,63,76,235,91,91,136])
EXACT_IN = {SWAP_IX,SWAP2_IX}
EXACT_IN_NAME = {SWAP_IX:'swap',SWAP2_IX:'swap2'}
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


def decode_swap2(raw,pool):
    """Decode the companion current-program swap event."""
    if len(raw)!=155 or raw[:8]!=SWAP2 or pump.b58(raw[8:40])!=pool or raw[80] not in (0,1):
        raise ValueError('dlmm_swap2_event_layout_or_identity')
    start,end=struct.unpack_from('<ii',raw,72)
    amount,left,output,mm_fee,protocol,limit_fee,host=struct.unpack_from('<QQQQQQQ',raw,97)
    fees_on_input,fees_on_x=raw[153],raw[154]
    if fees_on_input not in (0,1) or fees_on_x not in (0,1):
        raise ValueError('dlmm_swap2_event_flags')
    if left or limit_fee or host or not fees_on_input:
        raise Unavailable('dlmm_partial_limit_order_host_or_output_fee_swap_unsupported')
    direction=bool(raw[80])
    if bool(fees_on_x)!=direction:
        raise Unavailable('dlmm_fee_token_direction_unsupported')
    return dict(amount=amount,for_y=direction,
                observed=dict(start=start,end=end,output=output,
                              fee=mm_fee+protocol,protocol_fee=protocol))


def _keys(meta,message):
    return (message['accountKeys']+meta.get('loadedAddresses',{}).get('writable',[])
            +meta.get('loadedAddresses',{}).get('readonly',[]))


def _ordered_instructions(meta,message):
    """Yield top-level instruction then its recorded inner execution order."""
    groups={}
    for group in meta.get('innerInstructions') or []:
        index=group.get('index')
        if type(index) is not int or index<0 or index>=len(message['instructions']) or index in groups:
            raise Unavailable('dlmm_inner_instruction_order_ambiguous')
        groups[index]=group.get('instructions') or []
    for index,instruction in enumerate(message['instructions']):
        yield (index,0,instruction)
        for inner_index,inner in enumerate(groups.get(index,()),1):
            yield (index,inner_index,inner)


def _log_swap_fallback(meta,pool):
    events=[];stack=[]
    for line in meta.get('logMessages') or []:
        if 'Log truncated' in line:raise Unavailable('dlmm_truncated_logs')
        if line.startswith('Program ') and ' invoke [' in line:stack.append(line.split()[1])
        elif line.startswith('Program ') and (' success' in line or ' failed:' in line):
            if not stack or stack.pop()!=line.split()[1]:raise ValueError('dlmm_log_stack')
        elif line.startswith('Program data: ') and stack and stack[-1]==dlmm.PROGRAM:
            raw=base64.b64decode(line[14:],validate=True)
            if raw[:8]==SWAP:events.append(decode_swap(raw,pool))
    if stack:raise Unavailable('dlmm_incomplete_logs')
    return events


def transaction_swaps(tx,pool):
    """Return all authenticated exact-input swaps in execution order.

    The Solana `innerInstructions` list is already execution ordered within each
    top-level instruction. A new exact-input invocation opens one record and its
    subsequent Swap/Swap2Evt CPI events close that record before the next invocation.
    Any other DLMM instruction touching the interval remains fail-closed and exposes
    only its 8-byte discriminator for diagnosis.
    """
    if not tx or not tx.get('meta') or tx['meta'].get('err'):
        raise Unavailable('dlmm_missing_or_failed_transaction')
    meta=tx['meta'];message=tx['transaction']['message'];keys=_keys(meta,message)
    if pool not in keys or len(keys)>256:
        raise ValueError('dlmm_transaction_pool_identity')
    if meta.get('innerInstructions') is None:
        raise Unavailable('dlmm_missing_inner_instructions')
    records=[];current=None;dlmm_seen=False
    for outer,inner,instruction in _ordered_instructions(meta,message):
        if keys[instruction['programIdIndex']]!=dlmm.PROGRAM:continue
        dlmm_seen=True
        raw=_un58_data(instruction['data'])
        if raw[:8] in EXACT_IN:
            if len(raw)<24 or not instruction.get('accounts') or keys[instruction['accounts'][0]]!=pool:
                raise ValueError('dlmm_swap_instruction_identity')
            current=dict(call=raw,legacy=[],v2=[],order=[outer,inner],instruction=EXACT_IN_NAME[raw[:8]])
            records.append(current)
        elif raw[:8]==EVENT_CPI and raw[8:16]==SWAP:
            if current is None:raise Unavailable('dlmm_swap_event_without_ordered_call')
            current['legacy'].append(decode_swap(raw[8:],pool))
        elif raw[:8]==EVENT_CPI and raw[8:16]==SWAP2:
            if current is None:raise Unavailable('dlmm_swap2_event_without_ordered_call')
            current['v2'].append(decode_swap2(raw[8:],pool))
        else:
            raise Unavailable('dlmm_non_swap_mutation_in_interval:'+raw[:8].hex())
    if not records:
        # Referencing the pool account without invoking its owning program cannot
        # mutate pool data. Terminal equality still catches unrelated vault changes.
        if not dlmm_seen:return []
        raise Unavailable('dlmm_missing_swap_call')
    if len(records)==1 and not records[0]['legacy']:
        records[0]['legacy']=_log_swap_fallback(meta,pool)
    result=[]
    for record in records:
        if len(record['legacy'])!=1 or len(record['v2'])>1:
            raise Unavailable('dlmm_missing_or_ambiguous_swap_event')
        e=record['legacy'][0]
        if record['v2'] and record['v2'][0]!=e:
            raise ValueError('dlmm_swap_event_versions_disagree')
        amount,minimum=struct.unpack_from('<QQ',record['call'],8)
        if e['amount']!=amount or e['observed']['output']<minimum:
            raise ValueError('dlmm_instruction_event_mismatch')
        if tx.get('blockTime') is None:raise Unavailable('dlmm_missing_transaction_time')
        result.append(dict(**e,time=tx['blockTime'],slot=tx['slot'],
                           instruction=record['instruction'],execution_order=record['order']))
    return result


def transaction_swap(tx,pool):
    """Backward-compatible single-swap helper used by existing tests/callers."""
    swaps=transaction_swaps(tx,pool)
    if len(swaps)!=1:raise Unavailable('dlmm_requires_one_exact_input_swap_per_transaction')
    return swaps[0]


@dataclass(frozen=True)
class VerifiedTape:
    start_hash: str
    end_hash: str
    events: tuple
    terminal: dict
    lineage: str
    terminal_adjustments: tuple=()


def chain_verified_tapes(start,tapes):
    """Combine already-terminal-verified chunks without weakening per-chunk bounds."""
    tapes=tuple(tapes)
    if not tapes:raise ValueError('dlmm_empty_verified_tape_chain')
    expected=digest(start);events=[];adjustments=[];lineages=[]
    for tape in tapes:
        if not isinstance(tape,VerifiedTape) or tape.start_hash!=expected:
            raise Unavailable('dlmm_verified_chunk_chain_gap')
        expected=tape.end_hash
        events.extend(tape.events);adjustments.extend(tape.terminal_adjustments);lineages.append(tape.lineage)
    last=tapes[-1]
    return VerifiedTape(tapes[0].start_hash,last.end_hash,tuple(events),deepcopy(last.terminal),
                        digest(dict(chunks=lineages,start=tapes[0].start_hash,end=last.end_hash)),
                        tuple(adjustments))


def _carry_terminal_clock(start,state,end,events):
    """Use authentic post-swap Clock state only after economic equality is proven.

    Solana RPC blockTime is not the program's Clock::unix_timestamp. The replay uses
    blockTime to reproduce swaps; if every output/fee/protocol amount and every other
    terminal field already matches chain state, a sole `last_update` mismatch cannot
    alter past economics. Carry the authenticated chain value forward only when it is
    monotonic from the prestate and no later than the terminal snapshot time.
    """
    if not events:return None
    chain_value=end['last_update']
    if chain_value<start['last_update'] or chain_value>end['time']:
        return None
    final=events[-1]
    adjustment=dict(kind='authenticated_terminal_swap_clock',chain_last_update=chain_value,
        modeled_last_update=state['last_update'],delta_from_rpc_block_time_seconds=chain_value-final['time'],
        signature=final['signature'],instruction=final['instruction'])
    state['last_update']=chain_value
    return adjustment


def reconstruct(start,end_snapshot,signatures,transactions,now,cursor):
    if len(signatures)>64 or len(transactions)>MAX_TRANSACTIONS or len(encode(transactions))>2_000_000:
        raise Unavailable('dlmm_interval_evidence_bound')
    if any(s.get('confirmationStatus')!='finalized' for s in signatures):
        raise Unavailable('dlmm_signature_not_finalized')
    if any(type(s.get('transactionIndex')) is not int or s['transactionIndex']<0 for s in signatures):
        raise Unavailable('dlmm_transaction_index_unavailable')
    if [(s['slot'],s['transactionIndex']) for s in signatures]!=sorted(
            ((s['slot'],s['transactionIndex']) for s in signatures),reverse=True):
        raise Unavailable('dlmm_signature_order')
    if end_snapshot['available_time']>now:raise ValueError('dlmm_future_endpoint')
    end=dlmm.validate(end_snapshot,end_snapshot['available_time'],'real')
    if end['pool']!=start['pool'] or end['slot']<=start['slot'] or end['time']-start['time']>60:
        raise Unavailable('dlmm_interval_identity_or_age')
    if not any(sig['slot']<=start['slot'] for sig in signatures):
        raise Unavailable('dlmm_signature_census_missing_start_boundary')
    selected=[s for s in signatures if start['slot']<s['slot']<=end['slot'] and not s.get('err')]
    if len(selected)>MAX_TRANSACTIONS or len({s['signature'] for s in selected})!=len(selected):
        raise Unavailable('dlmm_transaction_bound_or_duplicates')
    if len({(s['slot'],s['transactionIndex']) for s in selected})!=len(selected):
        raise Unavailable('dlmm_transaction_order_ambiguous')
    state=deepcopy(start);events=[];previous=list(cursor)
    for sig in sorted(selected,key=lambda s:(s['slot'],s['transactionIndex'])):
        tx=transactions.get(sig['signature'])
        if not tx or tx['transaction']['signatures'][0]!=sig['signature'] or tx['slot']!=sig['slot']:
            raise Unavailable('dlmm_transaction_missing_or_identity')
        swaps=transaction_swaps(tx,start['pool'])
        for swap_index,e in enumerate(swaps):
            if not state['time']<=e['time']<=end['time']:
                raise ValueError('dlmm_transaction_time_outside_interval')
            prehash=digest(state);state,quote=dlmm.swap(state,e['amount'],e['for_y'],e['time'])
            if any(e['observed'][k]!=quote[k] for k in ('start','end','output','fee','protocol_fee')):
                raise Unavailable('dlmm_observed_swap_cannot_be_reconstructed')
            next_cursor=[e['slot'],sig['transactionIndex'],swap_index];state['slot']=e['slot']
            events.append(dict(kind='real',commitment='finalized',pool=start['pool'],cursor=next_cursor,
                previous_cursor=previous,prestate_hash=prehash,amount=e['amount'],for_y=e['for_y'],
                time=e['time'],available_time=now,observed=e['observed'],signature=sig['signature'],
                instruction=e['instruction'],execution_order=e['execution_order']))
            previous=next_cursor
    mismatches=[key for key in set(state)-{'time','slot'} if state[key]!=end[key]]
    adjustments=[]
    if mismatches==['last_update']:
        adjustment=_carry_terminal_clock(start,state,end,events)
        if adjustment is not None:
            adjustments.append(adjustment);mismatches=[]
    if mismatches:
        key=mismatches[0];detail=''
        if key=='last_update' and events:
            detail=f':sim={state[key]}:chain={end[key]}:last_instruction={events[-1]["instruction"]}'
        raise Unavailable('dlmm_terminal_state_disagrees_with_forward_reconstruction:'+key+detail)
    return VerifiedTape(digest(start),digest(end),tuple(events),end,
                        digest(dict(start=start,end=end_snapshot,signatures=signatures,transactions=transactions)),
                        tuple(adjustments))


def capture(adapter,start,end_snapshot,now,cursor):
    rpc=adapter.rpc
    signatures=rpc.call('getSignaturesForAddress',[start['pool'],dict(limit=64,commitment='finalized')],True)
    relevant=[s for s in signatures if start['slot']<s['slot']<=end_snapshot['slot'] and not s.get('err')]
    if len(relevant)>MAX_TRANSACTIONS:raise Unavailable('dlmm_transaction_bound')
    transactions={}
    for sig in relevant:
        transactions[sig['signature']]=rpc.call('getTransaction',[sig['signature'],
            dict(encoding='json',commitment='finalized',maxSupportedTransactionVersion=0)],True)
        if len(encode(transactions))>2_000_000:raise Unavailable('dlmm_interval_evidence_bound')
    return reconstruct(start,end_snapshot,signatures,transactions,now,cursor)
