"""Bounded finalized DLMM interval reconstruction.

Snapshots bracket every verified interval. Signature census must reach the starting
slot and every intervening pool transaction must be readable and ordered. Supported
exact-input swaps are replayed in authenticated execution order, including multiple
swaps in one transaction. Pinned host-fee exact-input swaps require authenticated
input-token host-account deltas. Unknown pool mutations, exact-out, truncated logs
and incomplete ordering fail closed. Terminal state only validates forward
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
SWAP_EXACT_OUT2_IX = bytes.fromhex('2bd7f784893cf351')
REMOVE_LIQUIDITY_BY_RANGE2_IX = bytes.fromhex('cc02c391359191cd')
REMOVE_LIQUIDITY_EVT = bytes.fromhex('74f461e8671f983a')
CLAIM_FEE2_EVT = bytes.fromhex('e8abf2613a4d232d')
INITIALIZE_POSITION_IX = bytes.fromhex('dbc0ea47bebf6650')
INITIALIZE_BIN_ARRAY_IX = bytes.fromhex('235613b94ed44bd3')
ADD_LIQUIDITY_BY_STRATEGY2_IX = bytes.fromhex('03dd95da6f8d76d5')
CLAIM_FEE2_IX = bytes.fromhex('70bf65ab1c907fbb')
MEMO_PROGRAM = 'MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr'
SYSTEM_PROGRAM = '11111111111111111111111111111111'
EXACT_IN = {SWAP_IX,SWAP2_IX}
EXACT_SWAP = EXACT_IN | {SWAP_EXACT_OUT2_IX}
EXACT_SWAP_NAME = {SWAP_IX:'swap',SWAP2_IX:'swap2',SWAP_EXACT_OUT2_IX:'swap_exact_out2'}
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
    host=int.from_bytes(raw[129:137],'little')
    observed=dict(start=start,end=end,output=output,fee=fee,protocol_fee=protocol)
    if host:
        observed['host_fee']=host
    return dict(amount=amount,for_y=direction,observed=observed)


def decode_swap2(raw,pool):
    """Decode the companion current-program swap event."""
    if len(raw)!=155 or raw[:8]!=SWAP2 or pump.b58(raw[8:40])!=pool or raw[80] not in (0,1):
        raise ValueError('dlmm_swap2_event_layout_or_identity')
    start,end=struct.unpack_from('<ii',raw,72)
    amount,left,output,mm_fee,protocol,limit_fee,host=struct.unpack_from('<QQQQQQQ',raw,97)
    fees_on_input,fees_on_x=raw[153],raw[154]
    if fees_on_input not in (0,1) or fees_on_x not in (0,1):
        raise ValueError('dlmm_swap2_event_flags')
    if left or limit_fee or not fees_on_input:
        raise Unavailable('dlmm_partial_limit_order_or_output_fee_swap_unsupported')
    direction=bool(raw[80])
    if bool(fees_on_x)!=direction:
        raise Unavailable('dlmm_fee_token_direction_unsupported')
    observed=dict(start=start,end=end,output=output,
                  fee=mm_fee+protocol+host,protocol_fee=protocol)
    if host:
        observed['host_fee']=host
    return dict(amount=amount,for_y=direction,observed=observed)



def decode_remove_liquidity(raw,pool):
    if len(raw)!=124 or raw[:8]!=REMOVE_LIQUIDITY_EVT or pump.b58(raw[8:40])!=pool:
        raise ValueError('dlmm_remove_liquidity_event_layout_or_identity')
    position=pump.b58(raw[72:104])
    amount_x,amount_y=struct.unpack_from('<QQ',raw,104)
    active=struct.unpack_from('<i',raw,120)[0]
    return dict(position=position,amount_x=amount_x,amount_y=amount_y,active=active)


def decode_claim_fee2(raw,pool):
    if len(raw)!=124 or raw[:8]!=CLAIM_FEE2_EVT or pump.b58(raw[8:40])!=pool:
        raise ValueError('dlmm_claim_fee2_event_layout_or_identity')
    position=pump.b58(raw[40:72])
    owner=pump.b58(raw[72:104])
    fee_x,fee_y=struct.unpack_from('<QQ',raw,104)
    active=struct.unpack_from('<i',raw,120)[0]
    return dict(position=position,owner=owner,fee_x=fee_x,fee_y=fee_y,active=active)


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


def _instruction_pool_positions(instruction,keys,pool):
    positions=[]
    for i,account_index in enumerate(instruction.get('accounts') or []):
        if type(account_index) is int and 0<=account_index<len(keys) and keys[account_index]==pool:
            positions.append(i)
    return positions


def _event_pool(raw):
    # EVENT_CPI prefix (8) + event discriminator (8) + first event field: pool (32).
    if len(raw)<48:return None
    return pump.b58(raw[16:48])


def _token_balance(meta,side,account_index):
    rows=[row for row in meta.get(side) or [] if row.get('accountIndex')==account_index]
    if len(rows)!=1:
        raise Unavailable('dlmm_host_fee_token_balance_missing')
    row=rows[0];token=row.get('uiTokenAmount') or {};amount=token.get('amount')
    if not isinstance(row.get('mint'),str) or not isinstance(amount,str) or not amount.isdigit():
        raise Unavailable('dlmm_host_fee_token_balance_shape')
    return row['mint'],int(amount)


def _claim_fee2_effect(raw,instruction,meta,keys,pool,order):
    """Authenticate exact pool-vault effect of one pinned-IDL claim_fee2.

    claim_fee2 updates the external PositionV2 and transfers already-accrued fees
    from the pool reserves to that position owner's token accounts. It does not
    redistribute bin liquidity. We authenticate the transfer using transaction
    pre/post SPL balances; terminal equality independently proves no modeled
    LbPair/bin field changed.
    """
    accounts=instruction.get('accounts') or []
    if len(raw)<16 or len(accounts)<14:
        raise Unavailable('dlmm_claim_fee2_identity')
    if any(type(accounts[i]) is not int or not 0<=accounts[i]<len(keys)
           for i in range(14)):
        raise Unavailable('dlmm_claim_fee2_account_index')
    if keys[accounts[0]]!=pool or keys[accounts[9]]!=pump.TOKEN_PROGRAM \
            or keys[accounts[10]]!=pump.TOKEN_PROGRAM \
            or keys[accounts[11]]!=MEMO_PROGRAM \
            or keys[accounts[13]]!=dlmm.PROGRAM:
        raise Unavailable('dlmm_claim_fee2_identity')
    result=dict(kind='claim_fee2',order=list(order),
                reserve_x=keys[accounts[3]],reserve_y=keys[accounts[4]],
                token_x_mint=keys[accounts[7]],token_y_mint=keys[accounts[8]])
    for side,reserve_pos,user_pos,mint_pos in (
        ('x',3,5,7),('y',4,6,8)):
        reserve_index=accounts[reserve_pos];user_index=accounts[user_pos]
        expected_mint=keys[accounts[mint_pos]]
        pre_mint,pre_reserve=_token_balance(meta,'preTokenBalances',reserve_index)
        post_mint,post_reserve=_token_balance(meta,'postTokenBalances',reserve_index)
        user_pre_mint,pre_user=_token_balance(meta,'preTokenBalances',user_index)
        user_post_mint,post_user=_token_balance(meta,'postTokenBalances',user_index)
        if any(mint!=expected_mint for mint in
               (pre_mint,post_mint,user_pre_mint,user_post_mint)):
            raise Unavailable('dlmm_claim_fee2_wrong_token')
        reserve_delta=post_reserve-pre_reserve
        user_delta=post_user-pre_user
        if reserve_delta>0 or user_delta<0 or user_delta!=-reserve_delta:
            raise Unavailable('dlmm_claim_fee2_balance_delta_mismatch')
        result.update({
            f'pre_reserve_{side}':pre_reserve,
            f'post_reserve_{side}':post_reserve,
            f'claimed_{side}':user_delta,
        })
    return result


def apply_terminal_adjustments(state,adjustments):
    """Apply already-authenticated external claim effects to a virtual pool state."""
    result=deepcopy(state)
    for item in adjustments:
        if item.get('kind')!='claim_fee2':
            raise Unavailable('dlmm_unknown_terminal_adjustment')
        for side in ('x','y'):
            claimed=item.get(f'claimed_{side}')
            if type(claimed) is not int or claimed<0:
                raise Unavailable('dlmm_claim_fee2_adjustment_shape')
            key=f'vault_{side}_amount'
            if claimed>result[key]:
                raise Unavailable('dlmm_claim_fee2_vault_underflow')
            result[key]-=claimed
        if type(item.get('slot')) is int:
            result['slot']=max(result.get('slot',0),item['slot'])
        if type(item.get('time')) is int:
            result['time']=max(result.get('time',0),item['time'])
    return result


def _authenticate_host_fee(record,event,meta,keys):
    host=event['observed'].get('host_fee',0)
    if not host:
        return
    accounts=record.get('accounts') or []
    # Pinned IDL for both exact-input instructions:
    # 0 lb_pair, 1 bitmap, 2/3 reserves, 4/5 user token accounts,
    # 6/7 token mints, 8 oracle, 9 optional host_fee_in.
    if len(accounts)<=9 or any(type(accounts[i]) is not int or not 0<=accounts[i]<len(keys)
                               for i in (2,3,6,7,9)):
        raise Unavailable('dlmm_host_fee_account_identity')
    host_index=accounts[9]
    host_address=keys[host_index]
    if host_address in (dlmm.PROGRAM,SYSTEM_PROGRAM):
        raise Unavailable('dlmm_host_fee_account_identity')
    input_mint=keys[accounts[6 if event['for_y'] else 7]]
    pre_mint,pre_amount=_token_balance(meta,'preTokenBalances',host_index)
    post_mint,post_amount=_token_balance(meta,'postTokenBalances',host_index)
    if pre_mint!=input_mint or post_mint!=input_mint:
        raise Unavailable('dlmm_host_fee_wrong_token')
    if post_amount-pre_amount!=host:
        raise Unavailable('dlmm_host_fee_balance_delta_mismatch')


def _log_swap_fallback(meta,pool):
    events=[];stack=[]
    for line in meta.get('logMessages') or []:
        if 'Log truncated' in line:raise Unavailable('dlmm_truncated_logs')
        if line.startswith('Program ') and ' invoke [' in line:stack.append(line.split()[1])
        elif line.startswith('Program ') and (' success' in line or ' failed:' in line):
            if not stack or stack.pop()!=line.split()[1]:raise ValueError('dlmm_log_stack')
        elif line.startswith('Program data: ') and stack and stack[-1]==dlmm.PROGRAM:
            raw=base64.b64decode(line[14:],validate=True)
            if raw[:8]==SWAP and pump.b58(raw[8:40])==pool:events.append(decode_swap(raw,pool))
    if stack:raise Unavailable('dlmm_incomplete_logs')
    return events


def transaction_swaps(tx,pool,terminal_adjustments=None):
    """Return target-pool exact-input swaps in authenticated execution order.

    A routed transaction may invoke Meteora for multiple pools. The pinned IDL puts
    `lb_pair` at account zero for both `swap` and `swap2`: an exact-input invocation
    whose account zero is another pool and which does not reference the target pool is
    unrelated and is ignored. If the target appears elsewhere in that invocation it
    remains an identity failure. Event CPI records are similarly filtered by their
    embedded pool pubkey.

    Two observed structural instructions are accepted only with their exact pinned-IDL
    identities. `initialize_position` has read-only `lb_pair` at account position 2.
    `initialize_bin_array` has read-only `lb_pair` at position 0 and only creates the
    deterministic empty bin-array PDA for its signed i64 index. Neither changes the
    modeled LbPair/vault/existing-bin economics. Any later liquidity/config mutation
    remains independently fail-closed, and terminal equality still validates that no
    modeled pool state changed.
    """
    if not tx or not tx.get('meta') or tx['meta'].get('err'):
        raise Unavailable('dlmm_missing_or_failed_transaction')
    meta=tx['meta'];message=tx['transaction']['message'];keys=_keys(meta,message)
    if pool not in keys or len(keys)>256:
        raise ValueError('dlmm_transaction_pool_identity')
    if meta.get('innerInstructions') is None:
        raise Unavailable('dlmm_missing_inner_instructions')
    records=[];claims=[];current=None
    for outer,inner,instruction in _ordered_instructions(meta,message):
        if keys[instruction['programIdIndex']]!=dlmm.PROGRAM:continue
        raw=_un58_data(instruction['data'])
        positions=_instruction_pool_positions(instruction,keys,pool)
        if raw[:8] in EXACT_IN:
            accounts=instruction.get('accounts') or []
            name=EXACT_IN_NAME[raw[:8]]
            if len(raw)<24 or not accounts:
                if positions:raise ValueError(f'dlmm_swap_instruction_identity:{name}:pool_positions={positions}:accounts={len(accounts)}')
                current=None;continue
            if keys[accounts[0]]!=pool:
                if positions:
                    pos=','.join(map(str,positions))
                    raise ValueError(f'dlmm_swap_instruction_identity:{name}:pool_positions={pos}:accounts={len(accounts)}')
                current=None;continue
            current=dict(call=raw,legacy=[],v2=[],order=[outer,inner],instruction=name,
                         accounts=list(accounts))
            records.append(current)
        elif raw[:8]==EVENT_CPI and raw[8:16]==SWAP:
            if _event_pool(raw)!=pool:continue
            if current is None:raise Unavailable('dlmm_swap_event_without_ordered_call')
            current['legacy'].append(decode_swap(raw[8:],pool))
        elif raw[:8]==EVENT_CPI and raw[8:16]==SWAP2:
            if _event_pool(raw)!=pool:continue
            if current is None:raise Unavailable('dlmm_swap2_event_without_ordered_call')
            current['v2'].append(decode_swap2(raw[8:],pool))
        elif raw[:8]==INITIALIZE_POSITION_IX:
            if positions:
                accounts=instruction.get('accounts') or []
                if len(accounts)!=8 or positions!=[2]:
                    pos=','.join(map(str,positions))
                    raise ValueError(f'dlmm_initialize_position_identity:pool_positions={pos}:accounts={len(accounts)}')
            # Pinned IDL: payer, position, read-only lb_pair, owner, system, rent,
            # event authority, program. No modeled pool state is mutated.
            continue
        elif raw[:8]==INITIALIZE_BIN_ARRAY_IX:
            if positions:
                accounts=instruction.get('accounts') or []
                pos=','.join(map(str,positions))
                if len(raw)!=16 or len(accounts)!=4 or positions!=[0]:
                    raise ValueError(f'dlmm_initialize_bin_array_identity:pool_positions={pos}:accounts={len(accounts)}:data={len(raw)}')
                if any(type(i) is not int or not 0<=i<len(keys) for i in accounts):
                    raise ValueError('dlmm_initialize_bin_array_account_index')
                index=struct.unpack_from('<q',raw,8)[0]
                expected=pump.pda([b'bin_array',pump.un58(pool),struct.pack('<q',index)],dlmm.PROGRAM)
                if keys[accounts[1]]!=expected or keys[accounts[3]]!=SYSTEM_PROGRAM:
                    raise ValueError('dlmm_initialize_bin_array_pda_or_system')
            # Pinned IDL: read-only lb_pair, newly-created writable bin_array PDA,
            # writable signer funder, system program. Creation introduces only an
            # empty structural array. Any instruction that later changes its bins or
            # pool liquidity is still unsupported and fails closed separately.
            continue
        elif raw[:8]==CLAIM_FEE2_IX:
            if positions:
                if positions!=[0]:
                    raise ValueError(
                        f'dlmm_claim_fee2_identity:pool_positions={positions}')
                claims.append(_claim_fee2_effect(
                    raw,instruction,meta,keys,pool,[outer,inner]))
            continue
        elif raw[:8]==ADD_LIQUIDITY_BY_STRATEGY2_IX:
            if positions:
                accounts=instruction.get('accounts') or []
                pos=','.join(map(str,positions))
                # Pinned IDL main accounts begin: position, lb_pair, optional bitmap,
                # user X/Y, reserves X/Y, mints X/Y, sender, token programs,
                # event authority, program. Remaining bin arrays may follow.
                if positions!=[1] or len(accounts)<14:
                    raise ValueError(
                        f'dlmm_add_liquidity_by_strategy2_identity:pool_positions={pos}:accounts={len(accounts)}')
                if any(type(i) is not int or not 0<=i<len(keys) for i in accounts[:14]):
                    raise ValueError('dlmm_add_liquidity_by_strategy2_account_index')
                slot=tx.get('slot')
                if type(slot) is not int or slot<0:
                    raise Unavailable('dlmm_snapshot_reset_slot_unavailable')
                # AddLiquidity only reports aggregate X/Y and active bin. Strategy2
                # can redistribute those amounts across a bin range, so accepting it
                # as a replayable no-op would corrupt bin inventory/supply. Surface a
                # precise reset boundary instead; warmup may restart from a fresh
                # authenticated snapshot, while outcome replay remains fail-closed.
                raise Unavailable(
                    f'dlmm_snapshot_reset_required:add_liquidity_by_strategy2:{slot}')
            continue
        else:
            if positions:raise Unavailable('dlmm_non_swap_mutation_in_interval:'+raw[:8].hex())
            # An authenticated DLMM instruction for another pool cannot mutate the
            # target lb_pair/bin state; terminal equality still validates this claim.
            continue
    if claims and terminal_adjustments is None:
        raise Unavailable('dlmm_claim_fee2_requires_reconstruction_context')
    if len(claims)>1:
        raise Unavailable('dlmm_claim_fee2_multiple_in_transaction')
    if claims and records:
        raise Unavailable('dlmm_claim_fee2_mixed_with_swap_unsupported')
    if terminal_adjustments is not None:
        terminal_adjustments.extend(claims)
    if not records:return []
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
        _authenticate_host_fee(record,e,meta,keys)
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
    state=deepcopy(start);events=[];adjustments=[];previous=list(cursor)
    for sig in sorted(selected,key=lambda s:(s['slot'],s['transactionIndex'])):
        tx=transactions.get(sig['signature'])
        if not tx or tx['transaction']['signatures'][0]!=sig['signature'] or tx['slot']!=sig['slot']:
            raise Unavailable('dlmm_transaction_missing_or_identity')
        tx_adjustments=[]
        swaps=transaction_swaps(
            tx,start['pool'],terminal_adjustments=tx_adjustments)
        for swap_index,e in enumerate(swaps):
            if not state['time']<=e['time']<=end['time']:
                raise ValueError('dlmm_transaction_time_outside_interval')
            host=e['observed'].get('host_fee',0)
            prehash=digest(state);state,quote=dlmm.swap(
                state,e['amount'],e['for_y'],e['time'],host_fee=host if host else None)
            keys=('start','end','output','fee','protocol_fee')
            if any(e['observed'][k]!=quote[k] for k in keys):
                raise Unavailable('dlmm_observed_swap_cannot_be_reconstructed')
            if host and quote.get('host_fee')!=host:
                raise Unavailable('dlmm_observed_host_fee_cannot_be_reconstructed')
            next_cursor=[e['slot'],sig['transactionIndex'],swap_index];state['slot']=e['slot']
            events.append(dict(kind='real',commitment='finalized',pool=start['pool'],cursor=next_cursor,
                previous_cursor=previous,prestate_hash=prehash,amount=e['amount'],for_y=e['for_y'],
                time=e['time'],available_time=now,observed=e['observed'],signature=sig['signature'],
                instruction=e['instruction'],execution_order=e['execution_order']))
            previous=next_cursor
        if tx_adjustments:
            item=tx_adjustments[0]
            if item['reserve_x']!=state['vault_x'] or item['reserve_y']!=state['vault_y'] \
                    or item['token_x_mint']!=state['x'] or item['token_y_mint']!=state['y']:
                raise Unavailable('dlmm_claim_fee2_pool_identity')
            if item['pre_reserve_x']!=state['vault_x_amount'] \
                    or item['pre_reserve_y']!=state['vault_y_amount']:
                raise Unavailable('dlmm_claim_fee2_prestate_mismatch')
            if tx.get('blockTime') is None:
                raise Unavailable('dlmm_missing_transaction_time')
            item.update(slot=tx['slot'],time=tx['blockTime'],
                        signature=sig['signature'],
                        transaction_index=sig['transactionIndex'])
            state=apply_terminal_adjustments(state,[item])
            adjustments.append(item)
    mismatches=[key for key in set(state)-{'time','slot'} if state[key]!=end[key]]
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