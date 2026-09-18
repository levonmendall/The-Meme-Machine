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


def _maybe_token_balance(meta,side,account_index):
    rows=[row for row in meta.get(side) or [] if row.get('accountIndex')==account_index]
    if not rows:
        return None
    if len(rows)!=1:
        raise Unavailable('dlmm_host_fee_token_balance_ambiguous')
    row=rows[0];token=row.get('uiTokenAmount') or {};amount=token.get('amount')
    if not isinstance(row.get('mint'),str) or not isinstance(amount,str) or not amount.isdigit():
        raise Unavailable('dlmm_host_fee_token_balance_shape')
    return row['mint'],int(amount)


def _spl_transfer(instruction,keys):
    """Decode the bounded classic SPL Transfer/TransferChecked subset."""
    program_index=instruction.get('programIdIndex')
    if type(program_index) is not int or not 0<=program_index<len(keys)             or keys[program_index]!=pump.TOKEN_PROGRAM:
        return None
    accounts=instruction.get('accounts') or []
    raw=_un58_data(instruction.get('data') or '')
    if len(raw)==9 and raw[:1]==b'\x03' and len(accounts)>=2:
        source,destination=accounts[:2]
        if any(type(i) is not int or not 0<=i<len(keys)
               for i in (source,destination)):
            raise Unavailable('dlmm_host_fee_transfer_account_index')
        return dict(
            kind='transfer',amount=int.from_bytes(raw[1:9],'little'),
            source=source,destination=destination,mint=None)
    if len(raw)==10 and raw[:1]==b'\x0c' and len(accounts)>=3:
        source,mint,destination=accounts[:3]
        if any(type(i) is not int or not 0<=i<len(keys)
               for i in (source,mint,destination)):
            raise Unavailable('dlmm_host_fee_transfer_account_index')
        return dict(
            kind='transfer_checked',amount=int.from_bytes(raw[1:9],'little'),
            source=source,destination=destination,mint=keys[mint])
    return None


def _claim_fee2_record(raw,instruction,keys,pool,order):
    accounts=instruction.get('accounts') or []
    if len(raw)<16 or len(accounts)<14:
        raise Unavailable('dlmm_claim_fee2_identity')
    if any(type(accounts[i]) is not int or not 0<=accounts[i]<len(keys)
           for i in range(14)):
        raise Unavailable('dlmm_claim_fee2_account_index')
    if (keys[accounts[0]]!=pool or keys[accounts[9]]!=pump.TOKEN_PROGRAM
            or keys[accounts[10]]!=pump.TOKEN_PROGRAM
            or keys[accounts[11]]!=MEMO_PROGRAM
            or keys[accounts[13]]!=dlmm.PROGRAM):
        raise Unavailable('dlmm_claim_fee2_identity')
    min_bin,max_bin=struct.unpack_from('<ii',raw,8)
    if min_bin>max_bin:
        raise Unavailable('dlmm_claim_fee2_range')
    return dict(
        kind='claim_fee2',order=list(order),events=[],
        position=keys[accounts[1]],owner=keys[accounts[2]],
        min_bin=min_bin,max_bin=max_bin,
        reserve_x=keys[accounts[3]],reserve_y=keys[accounts[4]],
        token_x_mint=keys[accounts[7]],token_y_mint=keys[accounts[8]],
        reserve_x_index=accounts[3],reserve_y_index=accounts[4],
        user_x_index=accounts[5],user_y_index=accounts[6],
        mint_x_index=accounts[7],mint_y_index=accounts[8],
    )


def _remove_liquidity_record(raw,instruction,keys,pool,order):
    accounts=instruction.get('accounts') or []
    if len(raw)<18 or len(accounts)<15:
        raise Unavailable('dlmm_remove_liquidity_by_range2_identity')
    if any(type(accounts[i]) is not int or not 0<=accounts[i]<len(keys)
           for i in range(15)):
        raise Unavailable('dlmm_remove_liquidity_by_range2_account_index')
    if (keys[accounts[1]]!=pool or keys[accounts[10]]!=pump.TOKEN_PROGRAM
            or keys[accounts[11]]!=pump.TOKEN_PROGRAM
            or keys[accounts[12]]!=MEMO_PROGRAM
            or keys[accounts[14]]!=dlmm.PROGRAM):
        raise Unavailable('dlmm_remove_liquidity_by_range2_identity')
    lower,upper,bps=struct.unpack_from('<iiH',raw,8)
    if lower>upper or not 1<=bps<=10000:
        raise Unavailable('dlmm_remove_liquidity_by_range2_range_or_bps')
    return dict(
        kind='remove_liquidity_by_range2',order=list(order),events=[],
        position=keys[accounts[0]],lower=lower,upper=upper,bps=bps,
        reserve_x=keys[accounts[5]],reserve_y=keys[accounts[6]],
        token_x_mint=keys[accounts[7]],token_y_mint=keys[accounts[8]],
        reserve_x_index=accounts[5],reserve_y_index=accounts[6],
        user_x_index=accounts[3],user_y_index=accounts[4],
        mint_x_index=accounts[7],mint_y_index=accounts[8],
    )


def _attach_effect_event(effects,kind,event,order):
    """Bind an EventCpi record to its preceding effect without adjacency assumptions.

    Anchor programs may execute other inner DLMM instructions between the effect call
    and its event-authority CPI. Bind only inside the same top-level instruction, by
    exact effect kind and PositionV2 identity, and require one unmatched predecessor.
    """
    candidates=[
        effect for effect in effects
        if effect.get('kind')==kind
        and effect.get('position')==event.get('position')
        and not effect.get('events')
        and len(effect.get('order') or ())==2
        and effect['order'][0]==order[0]
        and tuple(effect['order'])<tuple(order)
    ]
    if not candidates:
        raise Unavailable(f'dlmm_{kind}_event_without_ordered_call')
    latest=max(tuple(effect['order']) for effect in candidates)
    matches=[effect for effect in candidates if tuple(effect['order'])==latest]
    if len(matches)!=1:
        raise Unavailable(f'dlmm_{kind}_event_ambiguous_order')
    matches[0]['events'].append(event)


def _resolve_effect_event(effect,pool):
    if len(effect.get('events') or [])!=1:
        raise Unavailable('dlmm_missing_or_ambiguous_liquidity_event')
    event=effect['events'][0]
    if effect['kind']=='claim_fee2':
        if event['position']!=effect['position']:
            raise Unavailable('dlmm_claim_fee2_event_identity')
        effect.update(
            amount_x=event['fee_x'],amount_y=event['fee_y'],
            active=event['active'],event_owner=event['owner'])
    elif effect['kind']=='remove_liquidity_by_range2':
        if event['position']!=effect['position']:
            raise Unavailable('dlmm_remove_liquidity_event_identity')
        effect.update(
            amount_x=event['amount_x'],amount_y=event['amount_y'],
            active=event['active'])
    else:
        raise Unavailable('dlmm_unknown_external_effect')
    if min(effect['amount_x'],effect['amount_y'])<0:
        raise Unavailable('dlmm_external_effect_amount')
    return effect


def _authenticate_effect_transfers(effects,meta,keys):
    """Authenticate aggregate reserve-to-user transfers for claim/removal effects."""
    expected={}
    for effect in effects:
        for side in ('x','y'):
            amount=int(effect[f'amount_{side}'])
            mint=effect[f'token_{side}_mint']
            reserve_index=effect[f'reserve_{side}_index']
            user_index=effect[f'user_{side}_index']
            for index,delta in ((reserve_index,-amount),(user_index,amount)):
                prior=expected.get(index)
                if prior is None:
                    expected[index]=[mint,delta]
                elif prior[0]!=mint:
                    raise Unavailable('dlmm_external_effect_token_alias')
                else:
                    prior[1]+=delta
    for index,(mint,delta) in expected.items():
        pre_mint,pre_amount=_token_balance(meta,'preTokenBalances',index)
        post_mint,post_amount=_token_balance(meta,'postTokenBalances',index)
        if pre_mint!=mint or post_mint!=mint:
            raise Unavailable('dlmm_external_effect_wrong_token')
        if post_amount-pre_amount!=delta:
            raise Unavailable('dlmm_external_effect_balance_delta_mismatch')


def _host_binding(record,event,keys):
    host=event['observed'].get('host_fee',0)
    if not host:
        return None
    accounts=record.get('accounts') or []
    required=(2,3,4,6,7,9)
    if len(accounts)<=9 or any(type(accounts[i]) is not int or not 0<=accounts[i]<len(keys)
                               for i in required):
        raise Unavailable('dlmm_host_fee_account_identity')
    host_index=accounts[9]
    host_address=keys[host_index]
    if host_address in (dlmm.PROGRAM,SYSTEM_PROGRAM):
        raise Unavailable('dlmm_host_fee_account_identity')
    for_y=event['for_y']
    input_mint=keys[accounts[6 if for_y else 7]]
    reserve_input=accounts[2 if for_y else 3]
    user_input=accounts[4]
    return dict(
        host_index=host_index,input_mint=input_mint,host=int(host),
        reserve_input=reserve_input,user_input=user_input,
        order=tuple(record['order']),target=bool(record.get('target')))


def _host_transfer_amount(binding,ordered,keys,next_swap_order):
    """Sum only attributable SPL transfers in this swap's execution slice."""
    outer,inner=binding['order'];host_index=binding['host_index']
    sources={binding['user_input'],binding['reserve_input']}
    total=0;found=False
    for order,instruction in ordered:
        if order[0]!=outer or tuple(order)<=binding['order']:
            continue
        if next_swap_order is not None and tuple(order)>=next_swap_order:
            continue
        transfer=_spl_transfer(instruction,keys)
        if transfer is None or transfer['destination']!=host_index:
            continue
        # A transfer into the declared host account from another source is not
        # attributable to this swap and makes transaction-net balance unsuitable,
        # but it does not invalidate an exact swap-owned transfer.
        if transfer['source'] not in sources:
            continue
        if transfer['mint'] is not None and transfer['mint']!=binding['input_mint']:
            raise Unavailable('dlmm_host_fee_transfer_wrong_token')
        found=True;total+=transfer['amount']
    return found,total


def _authenticate_host_fees(resolved_records,meta,keys,ordered):
    hosted=[]
    for record,event in resolved_records:
        binding=_host_binding(record,event,keys)
        if binding is not None:
            hosted.append((record,event,binding))

    # Only target-pool hosted swaps can invalidate target reconstruction. Routed
    # swaps for other pools are retained only when they share the same host account
    # and mint, because their fee can legitimately contribute to one transaction-
    # level host-account balance delta.
    target_bindings=[binding for _record,_event,binding in hosted if binding['target']]
    if not target_bindings:
        return

    grouped={}
    for _record,_event,binding in hosted:
        key=(binding['host_index'],binding['input_mint'])
        grouped.setdefault(key,[]).append(binding)

    hosted_orders=sorted(
        (tuple(binding['order']),binding)
        for _record,_event,binding in hosted)

    transfer_proven={}
    for _record,_event,binding in hosted:
        if not binding['target']:
            continue
        next_order=None
        for order,_other in hosted_orders:
            if order[0]==binding['order'][0] and order>binding['order']:
                next_order=order;break
        found,amount=_host_transfer_amount(binding,ordered,keys,next_order)
        if found:
            if amount!=binding['host']:
                raise Unavailable('dlmm_host_fee_transfer_amount_mismatch')
            key=(binding['host_index'],binding['input_mint'])
            transfer_proven[key]=transfer_proven.get(key,0)+amount

    target_groups={}
    for binding in target_bindings:
        key=(binding['host_index'],binding['input_mint'])
        target_groups.setdefault(key,0)
        target_groups[key]+=binding['host']

    for (index,mint),target_expected in target_groups.items():
        if transfer_proven.get((index,mint))==target_expected:
            pre=_maybe_token_balance(meta,'preTokenBalances',index)
            post=_maybe_token_balance(meta,'postTokenBalances',index)
            if pre is not None and pre[0]!=mint:
                raise Unavailable('dlmm_host_fee_wrong_token')
            if post is not None and post[0]!=mint:
                raise Unavailable('dlmm_host_fee_wrong_token')
            continue

        pre=_maybe_token_balance(meta,'preTokenBalances',index)
        post=_maybe_token_balance(meta,'postTokenBalances',index)
        if pre is None or post is None:
            raise Unavailable('dlmm_host_fee_token_balance_missing')
        pre_mint,pre_amount=pre;post_mint,post_amount=post
        if pre_mint!=mint or post_mint!=mint:
            raise Unavailable('dlmm_host_fee_wrong_token')
        delta=post_amount-pre_amount
        if delta==target_expected:
            continue

        # Routed DLMM swaps can share one host token account. In that case the
        # transaction-level delta is the aggregate for every DLMM swap using that
        # exact host account + input mint, even though only one pool is being
        # reconstructed here.
        aggregate=sum(binding['host'] for binding in grouped[(index,mint)])
        if delta!=aggregate:
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


def _resolve_swap_record(record,meta,block_time):
    legacy=record['legacy'];v2=record['v2']
    if len(legacy)>1 or len(v2)>1 or (not legacy and not v2):
        raise Unavailable('dlmm_missing_or_ambiguous_swap_event')
    if record['instruction']=='swap_exact_out2' and len(v2)!=1:
        raise Unavailable('dlmm_exact_out_requires_swap2_event')
    event=v2[0] if v2 else legacy[0]
    if legacy and v2 and legacy[0]!=v2[0]:
        raise ValueError('dlmm_swap_event_versions_disagree')
    if record['instruction']=='swap_exact_out2':
        max_input,requested_output=struct.unpack_from('<QQ',record['call'],8)
        if event['amount']>max_input or event['observed']['output']!=requested_output:
            raise ValueError('dlmm_exact_out_instruction_event_mismatch')
        swap_mode='exact_out'
    else:
        amount,minimum=struct.unpack_from('<QQ',record['call'],8)
        if event['amount']!=amount or event['observed']['output']<minimum:
            raise ValueError('dlmm_instruction_event_mismatch')
        swap_mode='exact_in'
    if block_time is None:
        raise Unavailable('dlmm_missing_transaction_time')
    return dict(
        **event,time=block_time,instruction=record['instruction'],
        execution_order=record['order'],swap_mode=swap_mode)


def transaction_swaps(tx,pool,terminal_adjustments=None):
    """Return authenticated target-pool swaps and external effects in execution order."""
    if not tx or not tx.get('meta') or tx['meta'].get('err'):
        raise Unavailable('dlmm_missing_or_failed_transaction')
    meta=tx['meta'];message=tx['transaction']['message'];keys=_keys(meta,message)
    if pool not in keys or len(keys)>256:
        raise ValueError('dlmm_transaction_pool_identity')
    if meta.get('innerInstructions') is None:
        raise Unavailable('dlmm_missing_inner_instructions')
    ordered=[
        ((outer,inner),instruction)
        for outer,inner,instruction in _ordered_instructions(meta,message)
    ]
    records=[];effects=[];current=None
    for (outer,inner),instruction in ordered:
        if keys[instruction['programIdIndex']]!=dlmm.PROGRAM:
            continue
        raw=_un58_data(instruction['data'])
        positions=_instruction_pool_positions(instruction,keys,pool)
        if raw[:8] in EXACT_SWAP:
            accounts=instruction.get('accounts') or []
            name=EXACT_SWAP_NAME[raw[:8]]
            if len(raw)<24 or not accounts or type(accounts[0]) is not int \
                    or not 0<=accounts[0]<len(keys):
                if positions:
                    raise ValueError(
                        f'dlmm_swap_instruction_identity:{name}:pool_positions={positions}:accounts={len(accounts)}')
                current=None;continue
            call_pool=keys[accounts[0]]
            if call_pool!=pool and positions:
                pos=','.join(map(str,positions))
                raise ValueError(
                    f'dlmm_swap_instruction_identity:{name}:pool_positions={pos}:accounts={len(accounts)}')
            current=dict(kind='swap',pool=call_pool,target=call_pool==pool,call=raw,
                         legacy=[],v2=[],order=[outer,inner],instruction=name,
                         accounts=list(accounts))
            records.append(current)
        elif raw[:8]==EVENT_CPI and raw[8:16] in (SWAP,SWAP2):
            event_pool=_event_pool(raw)
            if current is None or current.get('kind')!='swap' or current['pool']!=event_pool:
                if event_pool==pool:
                    raise Unavailable('dlmm_swap_event_without_ordered_call')
                continue
            if raw[8:16]==SWAP:
                current['legacy'].append(decode_swap(raw[8:],event_pool))
            else:
                current['v2'].append(decode_swap2(raw[8:],event_pool))
        elif raw[:8]==EVENT_CPI and raw[8:16]==REMOVE_LIQUIDITY_EVT:
            event_pool=_event_pool(raw)
            if event_pool!=pool:
                continue
            event=decode_remove_liquidity(raw[8:],pool)
            _attach_effect_event(
                effects,'remove_liquidity_by_range2',event,[outer,inner])
        elif raw[:8]==EVENT_CPI and raw[8:16]==CLAIM_FEE2_EVT:
            event_pool=_event_pool(raw)
            if event_pool!=pool:
                continue
            event=decode_claim_fee2(raw[8:],pool)
            _attach_effect_event(effects,'claim_fee2',event,[outer,inner])
        elif raw[:8]==INITIALIZE_POSITION_IX:
            if positions:
                accounts=instruction.get('accounts') or []
                if len(accounts)!=8 or positions!=[2]:
                    pos=','.join(map(str,positions))
                    raise ValueError(
                        f'dlmm_initialize_position_identity:pool_positions={pos}:accounts={len(accounts)}')
            current=None;continue
        elif raw[:8]==INITIALIZE_BIN_ARRAY_IX:
            if positions:
                accounts=instruction.get('accounts') or []
                pos=','.join(map(str,positions))
                if len(raw)!=16 or len(accounts)!=4 or positions!=[0]:
                    raise ValueError(
                        f'dlmm_initialize_bin_array_identity:pool_positions={pos}:accounts={len(accounts)}:data={len(raw)}')
                if any(type(i) is not int or not 0<=i<len(keys) for i in accounts):
                    raise ValueError('dlmm_initialize_bin_array_account_index')
                index=struct.unpack_from('<q',raw,8)[0]
                expected=pump.pda(
                    [b'bin_array',pump.un58(pool),struct.pack('<q',index)],
                    dlmm.PROGRAM)
                if keys[accounts[1]]!=expected or keys[accounts[3]]!=SYSTEM_PROGRAM:
                    raise ValueError('dlmm_initialize_bin_array_pda_or_system')
            current=None;continue
        elif raw[:8]==CLAIM_FEE2_IX:
            if positions:
                if positions!=[0]:
                    raise ValueError(
                        f'dlmm_claim_fee2_identity:pool_positions={positions}')
                effect=_claim_fee2_record(
                    raw,instruction,keys,pool,[outer,inner])
                effects.append(effect);current=dict(kind='effect',effect=effect)
            else:
                current=None
            continue
        elif raw[:8]==REMOVE_LIQUIDITY_BY_RANGE2_IX:
            if positions:
                if positions!=[1]:
                    raise ValueError(
                        f'dlmm_remove_liquidity_by_range2_identity:pool_positions={positions}')
                effect=_remove_liquidity_record(
                    raw,instruction,keys,pool,[outer,inner])
                effects.append(effect);current=dict(kind='effect',effect=effect)
            else:
                current=None
            continue
        elif raw[:8]==ADD_LIQUIDITY_BY_STRATEGY2_IX:
            if positions:
                accounts=instruction.get('accounts') or []
                pos=','.join(map(str,positions))
                if positions!=[1] or len(accounts)<14:
                    raise ValueError(
                        f'dlmm_add_liquidity_by_strategy2_identity:pool_positions={pos}:accounts={len(accounts)}')
                if any(type(i) is not int or not 0<=i<len(keys) for i in accounts[:14]):
                    raise ValueError('dlmm_add_liquidity_by_strategy2_account_index')
                slot=tx.get('slot')
                if type(slot) is not int or slot<0:
                    raise Unavailable('dlmm_snapshot_reset_slot_unavailable')
                raise Unavailable(
                    f'dlmm_snapshot_reset_required:add_liquidity_by_strategy2:{slot}')
            current=None;continue
        else:
            if positions:
                raise Unavailable(
                    'dlmm_non_swap_mutation_in_interval:'+raw[:8].hex())
            current=None;continue

    resolved=[]
    for record in records:
        if record['target'] and record['instruction']!='swap_exact_out2' \
                and not record['legacy'] and not record['v2'] and len(records)==1:
            record['legacy']=_log_swap_fallback(meta,record['pool'])
        event=_resolve_swap_record(record,meta,tx.get('blockTime'))
        resolved.append((record,event))
    _authenticate_host_fees(resolved,meta,keys,ordered)

    resolved_effects=[_resolve_effect_event(effect,pool) for effect in effects]
    if resolved_effects:
        if any(record['target'] for record,_event in resolved):
            raise Unavailable('dlmm_swap_mixed_with_external_liquidity_effect')
        _authenticate_effect_transfers(resolved_effects,meta,keys)
        if terminal_adjustments is None:
            raise Unavailable('dlmm_external_effect_requires_reconstruction_context')
        terminal_adjustments.extend(resolved_effects)

    return [
        dict(**event,slot=tx['slot'])
        for record,event in resolved if record['target']
    ]


def _materialize_removal_effects(start,end,effects):
    removals=[item for item in effects
              if item.get('kind')=='remove_liquidity_by_range2']
    if len(removals)>1:
        raise Unavailable('dlmm_multiple_liquidity_removals_in_interval')
    if not removals:
        # No supported liquidity mutation means supply must remain invariant.
        for bid,b in start['bins'].items():
            if bid not in end['bins'] or end['bins'][bid]['supply']!=b['supply']:
                raise Unavailable('dlmm_unmodeled_liquidity_supply_change')
        return
    item=removals[0]
    lower,upper=item['lower'],item['upper']
    if upper-lower+1>len(start['bins']):
        raise Unavailable('dlmm_remove_liquidity_range_not_fully_observed')
    for bid in range(lower,upper+1):
        if str(bid) not in start['bins'] or str(bid) not in end['bins']:
            raise Unavailable('dlmm_remove_liquidity_range_not_fully_observed')
    removed={}
    for bid,b in start['bins'].items():
        if bid not in end['bins']:
            raise Unavailable('dlmm_remove_liquidity_terminal_bin_set')
        delta=b['supply']-end['bins'][bid]['supply']
        if delta<0:
            raise Unavailable('dlmm_liquidity_supply_increase_in_interval')
        numeric=int(bid)
        if not lower<=numeric<=upper and delta:
            raise Unavailable('dlmm_liquidity_supply_change_outside_remove_range')
        if delta:
            removed[bid]=delta
    if not removed and (item['amount_x'] or item['amount_y']):
        raise Unavailable('dlmm_remove_liquidity_missing_supply_delta')
    item['removed_shares']=removed


def apply_external_adjustment(state,item,counterfactual=False):
    """Apply one authenticated external LP action to a real or hypothetical pool."""
    result=deepcopy(state)
    kind=item.get('kind')
    active=item.get('active')
    if type(active) is not int or active!=result['active']:
        raise Unavailable('dlmm_external_adjustment_active_bin_mismatch')
    if kind=='claim_fee2':
        # Claiming another position's accrued fee does not alter bin inventory,
        # supply, or fee growth. In the real pool the authenticated fee transfer
        # leaves reserve vaults. Under the hypothetical LP state the other
        # position's counterfactual claim amount is not assumed from real history,
        # and it is irrelevant to our bin-level entitlement, so only clock/order
        # advance is applied.
        if not counterfactual:
            for side in ('x','y'):
                amount=item.get(f'amount_{side}')
                if type(amount) is not int or amount<0:
                    raise Unavailable('dlmm_claim_fee2_adjustment_shape')
                key=f'vault_{side}_amount'
                if amount>result[key]:
                    raise Unavailable('dlmm_claim_fee2_vault_underflow')
                result[key]-=amount
    elif kind=='remove_liquidity_by_range2':
        shares=item.get('removed_shares')
        if not isinstance(shares,dict):
            raise Unavailable('dlmm_remove_liquidity_share_evidence_missing')
        totals={'x':0,'y':0}
        for bid in sorted(shares,key=int):
            share=shares[bid]
            b=result['bins'].get(str(bid))
            if b is None or type(share) is not int or share<=0 or share>b['supply']:
                raise Unavailable('dlmm_remove_liquidity_share_evidence_invalid')
            x=dlmm.withdraw_amount(share,b['x'],b['supply'])
            y=dlmm.withdraw_amount(share,b['y'],b['supply'])
            b['x']-=x;b['y']-=y;b['supply']-=share
            result['vault_x_amount']-=x;result['vault_y_amount']-=y
            totals['x']+=x;totals['y']+=y
        if not counterfactual and (
                totals['x']!=item.get('amount_x')
                or totals['y']!=item.get('amount_y')):
            raise Unavailable('dlmm_remove_liquidity_event_amount_mismatch')
    else:
        raise Unavailable('dlmm_unknown_terminal_adjustment')
    if type(item.get('time')) is int:
        result['time']=max(result.get('time',0),item['time'])
    if type(item.get('slot')) is int:
        result['slot']=max(result.get('slot',0),item['slot'])
    return result


def apply_terminal_adjustments(state,adjustments,counterfactual=False):
    result=deepcopy(state)
    for item in adjustments:
        result=apply_external_adjustment(
            result,item,counterfactual=counterfactual)
    return result


def replay_swap_event(state,event):
    host=event['observed'].get('host_fee',0)
    if event.get('swap_mode')=='exact_out':
        return dlmm.swap_exact_out(
            state,event['observed']['output'],event['for_y'],event['time'],
            host_fee=host if host else None)
    return dlmm.swap(
        state,event['amount'],event['for_y'],event['time'],
        host_fee=host if host else None)


def ordered_tape_actions(tape):
    if not isinstance(tape,VerifiedTape):
        raise TypeError('dlmm_verified_tape_required')
    actions=[]
    for event in tape.events:
        actions.append(('swap',event))
    for item in tape.terminal_adjustments:
        actions.append(('adjustment',item))
    def key(pair):
        item=pair[1]
        cursor=item.get('cursor') or [item.get('slot',0),
                                     item.get('transaction_index',0),0]
        order=item.get('execution_order') or item.get('order') or [0,0]
        return (cursor[0],cursor[1],order[0],order[1],cursor[2])
    return tuple(sorted(actions,key=key))


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
    if len({(s['slot'],s['transactionIndex']) for s in selected})!=len(selected):
        raise Unavailable('dlmm_transaction_order_ambiguous')

    parsed={};all_effects=[]
    for sig in sorted(selected,key=lambda s:(s['slot'],s['transactionIndex'])):
        tx=transactions.get(sig['signature'])
        if not tx or tx['transaction']['signatures'][0]!=sig['signature'] or tx['slot']!=sig['slot']:
            raise Unavailable('dlmm_transaction_missing_or_identity')
        tx_effects=[]
        swaps=transaction_swaps(
            tx,start['pool'],terminal_adjustments=tx_effects)
        if tx.get('blockTime') is None:
            raise Unavailable('dlmm_missing_transaction_time')
        for item in tx_effects:
            item.update(
                slot=tx['slot'],time=tx['blockTime'],signature=sig['signature'],
                transaction_index=sig['transactionIndex'])
            item.pop('events',None)
        parsed[sig['signature']]=(swaps,tx_effects)
        all_effects.extend(tx_effects)

    _materialize_removal_effects(start,end,all_effects)

    state=deepcopy(start);events=[];adjustments=[];previous=list(cursor)
    for sig in sorted(selected,key=lambda s:(s['slot'],s['transactionIndex'])):
        swaps,tx_effects=parsed[sig['signature']]
        actions=[('swap',event,event['execution_order']) for event in swaps]
        actions.extend(
            ('adjustment',item,item['order']) for item in tx_effects)
        actions.sort(key=lambda row:(row[2][0],row[2][1]))
        for action_index,(kind,item,_order) in enumerate(actions):
            prehash=digest(state)
            next_cursor=[sig['slot'],sig['transactionIndex'],action_index]
            if kind=='swap':
                event=item
                if not state['time']<=event['time']<=end['time']:
                    raise ValueError('dlmm_transaction_time_outside_interval')
                state,quote=replay_swap_event(state,event)
                keys=('start','end','output','fee','protocol_fee')
                if any(event['observed'][k]!=quote[k] for k in keys):
                    raise Unavailable('dlmm_observed_swap_cannot_be_reconstructed')
                if event.get('swap_mode')=='exact_out' and event['amount']!=quote['input']:
                    raise Unavailable('dlmm_observed_exact_out_input_cannot_be_reconstructed')
                host=event['observed'].get('host_fee',0)
                if host and quote.get('host_fee')!=host:
                    raise Unavailable('dlmm_observed_host_fee_cannot_be_reconstructed')
                state['slot']=sig['slot']
                enriched=dict(
                    **event,kind='real',commitment='finalized',pool=start['pool'],
                    cursor=next_cursor,previous_cursor=previous,
                    prestate_hash=prehash,available_time=now,
                    signature=sig['signature'])
                events.append(enriched)
            else:
                item.update(
                    commitment='finalized',pool=start['pool'],
                    cursor=next_cursor,previous_cursor=previous,
                    prestate_hash=prehash,available_time=now,
                    execution_order=list(item['order']))
                state=apply_external_adjustment(
                    state,item,counterfactual=False)
                adjustments.append(deepcopy(item))
            previous=next_cursor

    mismatches=[key for key in set(state)-{'time','slot'} if state[key]!=end[key]]
    if mismatches:
        key=mismatches[0];detail=''
        if key=='last_update' and events:
            detail=f':sim={state[key]}:chain={end[key]}:last_instruction={events[-1]["instruction"]}'
        raise Unavailable(
            'dlmm_terminal_state_disagrees_with_forward_reconstruction:'+key+detail)
    return VerifiedTape(
        digest(start),digest(end),tuple(events),end,
        digest(dict(start=start,end=end_snapshot,signatures=signatures,
                    transactions=transactions)),
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