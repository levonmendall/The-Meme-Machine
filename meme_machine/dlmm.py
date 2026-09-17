"""Meteora DLMM read-only, integer mechanics. No allocation authority.

Semantic reference: MeteoraAg/dlmm-sdk 576919e3e4368e542c402f000b4264724f7f23ec,
@meteora-ag/dlmm 1.9.14. Supported subset: SPL tokens, input fees, no limit orders
or farming. Prices are Q64.64; tokens and SOL are integer base units.
"""
from copy import deepcopy
import struct

from . import pump
from .postgrad import WSOL, _token_account
from .provider import Unavailable
from .store import digest

PROGRAM = 'LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo'
Q = 1 << 64
U128 = (1 << 128) - 1
FEE_PRECISION = 1_000_000_000
MAX_BINS = 210
MAX_AGE = 20
DLMM_ALLOCATION_ENABLED = False


def price(bin_id, step):
    """Reference u64x64_math::pow, including its inversion/rounding behavior."""
    if not 0 < step <= 10000 or abs(bin_id) >= 0x80000:
        raise ValueError('dlmm_price_domain')
    if bin_id == 0:
        return Q
    base = Q + step * Q // 10000
    invert = bin_id < 0
    if base >= Q:
        base = U128 // base
        invert = not invert
    result = Q
    exponent = abs(bin_id)
    for i in range(19):
        if exponent & (1 << i):
            result = result * base >> 64
        base = base * base >> 64
    if result == 0:
        raise ValueError('dlmm_price_underflow')
    return U128 // result if invert else result


def pool(account):
    raw = pump.raw_account(account, PROGRAM, 'LbPair')
    if len(raw) != 904:
        raise ValueError('dlmm_pool_layout')
    names = ('base_factor','filter_period','decay_period','reduction_factor',
             'variable_fee_control','max_volatility_accumulator','min_bin_id',
             'max_bin_id','protocol_share','base_fee_power_factor','function_type','collect_fee_mode')
    static = dict(zip(names, struct.unpack_from('<HHHHIIiiHBBB', raw, 8)))
    vol, ref, index = struct.unpack_from('<IIi', raw, 40)
    result = dict(parameters=static, volatility_accumulator=vol,
                  volatility_reference=ref,index_reference=index,
                  last_update=struct.unpack_from('<q',raw,56)[0],
                  active=struct.unpack_from('<i',raw,76)[0],
                  step=struct.unpack_from('<H',raw,80)[0],
                  pair_type=raw[75],activation_type=raw[86],
                  activation_point=struct.unpack_from('<Q',raw,816)[0],
                  x=pump.b58(raw[88:120]),y=pump.b58(raw[120:152]),
                  vault_x=pump.b58(raw[152:184]),vault_y=pump.b58(raw[184:216]))
    if raw[82] != 0 or raw[75] not in (0,2,3) or raw[86] not in (0,1):
        raise ValueError('dlmm_disabled_or_permissioned_pool')
    if raw[880:882] != bytes(2) or raw[882] > 1:
        raise ValueError('dlmm_unsupported_token_program_or_version')
    if static['collect_fee_mode'] != 0 or static['function_type'] not in (0,1,2):
        raise ValueError('dlmm_unsupported_fee_mode')
    # RewardInfo starts with mint. No farming rewards are modeled or claimed.
    if any(raw[264:296]) or any(raw[408:440]):
        raise ValueError('dlmm_farming_unsupported')
    if static['protocol_share'] > 2500 or static['base_fee_power_factor'] > 9:
        raise ValueError('dlmm_invalid_fee_parameters')
    if static['reduction_factor'] > 10000 or static['filter_period'] > static['decay_period']:
        raise ValueError('dlmm_invalid_decay_parameters')
    if not static['min_bin_id'] <= result['active'] <= static['max_bin_id']:
        raise ValueError('dlmm_bin_bounds')
    if (result['x'] == WSOL) == (result['y'] == WSOL):
        raise ValueError('dlmm_requires_one_sol_leg')
    price(result['active'], result['step'])
    return result


def array_address(address, index):
    return pump.pda([b'bin_array',pump.un58(address),struct.pack('<q',index)],PROGRAM)


def bin_array(account, address, index, step):
    raw = pump.raw_account(account, PROGRAM, 'BinArray')
    if len(raw) != 10136 or struct.unpack_from('<q',raw,8)[0] != index or raw[16] not in (1,2,3):
        raise ValueError('dlmm_array_layout_or_index')
    if pump.b58(raw[24:56]) != address:
        raise ValueError('dlmm_array_pool_mismatch')
    result = {}
    for i in range(70):
        offset = 56 + i*144
        x,y = struct.unpack_from('<QQ',raw,offset)
        p = int.from_bytes(raw[offset+16:offset+32],'little')
        supply = int.from_bytes(raw[offset+32:offset+48],'little')
        bid = index*70+i
        # Version 3 reuses the old cumulative swap counters for limit orders.
        # The pinned SDK's pre-limit-order fixtures use version 1 and nonzero
        # counters here. Those counters are not available order liquidity.
        if raw[16]>=3 and any(raw[offset+112:offset+136]):
            raise ValueError('dlmm_limit_orders_unsupported')
        if bool(supply) != bool(x or y):
            raise ValueError('dlmm_bin_supply_inventory_mismatch')
        if p and p != price(bid,step):
            raise ValueError('dlmm_bin_price_mismatch')
        result[str(bid)] = dict(x=x,y=y,price=p or price(bid,step),supply=supply,
            fee_x=int.from_bytes(raw[offset+80:offset+96],'little'),
            fee_y=int.from_bytes(raw[offset+96:offset+112],'little'))
    return result


def validate(snapshot, now, kind=None):
    if snapshot.get('network') != 'solana-mainnet' or snapshot.get('commitment') != 'finalized':
        raise ValueError('dlmm_finalized_mainnet_required')
    if kind is not None and snapshot.get('kind') != kind:
        raise ValueError('dlmm_experiment_contamination')
    if not snapshot['market_time'] <= snapshot['available_time'] <= now or now-snapshot['market_time'] > MAX_AGE:
        raise ValueError('dlmm_stale_or_future_evidence')
    if snapshot['slot'] <= 0:
        raise ValueError('dlmm_invalid_slot')
    address = snapshot['pool']; pump.un58(address)
    accounts = snapshot['accounts']
    p = pool(accounts[address])
    activation_now=snapshot['slot'] if p['activation_type']==0 else snapshot['market_time']
    if p['pair_type']!=0 and activation_now<p['activation_point']:
        raise ValueError('dlmm_pool_not_activated')
    for mint in (p['x'],p['y']):
        if accounts[mint]['owner'] != pump.TOKEN_PROGRAM:
            raise ValueError('dlmm_unsupported_token_program')
        _,decimals = pump.mint_info(accounts[mint])
        if mint == WSOL and decimals != 9:
            raise ValueError('dlmm_native_decimals')
    vx = _token_account(accounts[p['vault_x']],p['x'],address,pump.TOKEN_PROGRAM)
    vy = _token_account(accounts[p['vault_y']],p['y'],address,pump.TOKEN_PROGRAM)
    for key in ('vault_x','vault_y'):
        raw=pump.raw_account(accounts[p[key]],pump.TOKEN_PROGRAM)
        if len(raw)!=165 or any(raw[72:76]) or any(raw[129:133]):
            raise ValueError('dlmm_unsupported_vault_delegate_or_layout')
    indices = snapshot['array_indices']
    if not 1 <= len(indices) <= 3 or sorted(set(indices)) != indices:
        raise ValueError('dlmm_array_bound')
    bins = {}
    for index in indices:
        bins.update(bin_array(accounts[array_address(address,index)],address,index,p['step']))
    if str(p['active']) not in bins or not any(b['x'] or b['y'] for b in bins.values()):
        raise ValueError('dlmm_missing_active_or_liquidity')
    if sum(b['x'] for b in bins.values()) > vx or sum(b['y'] for b in bins.values()) > vy:
        raise ValueError('dlmm_vault_inventory_mismatch')
    return dict(pool=address,**p,bins=bins,slot=snapshot['slot'],time=snapshot['market_time'])


def total_fee(p):
    s=p['parameters']
    base=s['base_factor']*p['step']*10*10**s['base_fee_power_factor']
    variable=pump.ceildiv(s['variable_fee_control']*(p['volatility_accumulator']*p['step'])**2,100_000_000_000)
    return min(base+variable,100_000_000)


def swap(state, amount, for_y, timestamp):
    """Exact-input counterfactual traversal. Returns new state; never mutates input.

    Every traversed bin must be present. No extrapolation across missing arrays.
    Fee growth uses integer LP supply, as PositionV2's claim calculation does.
    """
    if type(amount) is not int or not 0 < amount < 1<<64 or type(for_y) is not bool:
        raise ValueError('dlmm_invalid_swap')
    p=deepcopy(state); s=p['parameters']
    if timestamp < max(p['last_update'],p['time']):
        raise ValueError('dlmm_time_regression')
    elapsed=timestamp-p['last_update']
    if elapsed >= s['filter_period']:
        p['index_reference']=p['active']
        p['volatility_reference']=(p['volatility_accumulator']*s['reduction_factor']//10000
                                   if elapsed < s['decay_period'] else 0)
    left=amount; output=fees=protocol=0; traversed=[]
    start=p['active']
    while left:
        bid=p['active']; b=p['bins'].get(str(bid))
        if b is None or len(traversed) >= MAX_BINS:
            raise Unavailable('dlmm_missing_traversal_bins')
        p['volatility_accumulator']=min(s['max_volatility_accumulator'],
            p['volatility_reference']+abs(p['index_reference']-bid)*10000)
        rate=total_fee(p)
        out_reserve=b['y' if for_y else 'x']; px=b['price']
        if out_reserve:
            max_net=(pump.ceildiv(out_reserve*Q,px) if for_y else pump.ceildiv(out_reserve*px,Q))
            max_fee=pump.ceildiv(max_net*rate,FEE_PRECISION-rate)
            used=min(left,max_net+max_fee)
            fee=pump.ceildiv(used*rate,FEE_PRECISION)
            net=used-fee
            out=min(out_reserve,net*px//Q if for_y else net*Q//px)
            if net==0 or out==0:
                raise Unavailable('dlmm_dust_swap_unsupported')
            pf=fee*s['protocol_share']//10000
            in_key,out_key=('x','y') if for_y else ('y','x')
            b[in_key]+=net; b[out_key]-=out
            if b[in_key] >= 1<<64 or b['supply']>>64 == 0:
                raise ValueError('dlmm_bin_overflow_or_zero_fee_supply')
            b['fee_'+in_key]+=((fee-pf)<<64)//(b['supply']>>64)
            left-=used; output+=out; fees+=fee; protocol+=pf
            traversed.append(dict(bin=bid,input=used,output=out,fee=fee,protocol_fee=pf))
        else:
            traversed.append(dict(bin=bid,input=0,output=0,fee=0,protocol_fee=0))
        if left:
            p['active']+=-1 if for_y else 1
            if not s['min_bin_id'] <= p['active'] <= s['max_bin_id']:
                raise Unavailable('dlmm_pool_bin_limit')
    p['last_update']=timestamp; p['time']=timestamp
    return p,dict(input=amount,output=output,fee=fees,protocol_fee=protocol,
                  start=start,end=p['active'],traversed=traversed)


def scout(snapshot, now, api_identity=None):
    """Structural evidence only. This function has no Store or allocator."""
    p=validate(snapshot,now)
    if api_identity is not None and any(api_identity.get(k)!=p[k] for k in ('pool','x','y')):
        raise ValueError('dlmm_api_chain_identity_mismatch')
    return dict(pool=p['pool'],x=p['x'],y=p['y'],active_bin=p['active'],bin_step=p['step'],
                liquidity=[dict(bin=int(k),x=v['x'],y=v['y']) for k,v in p['bins'].items() if v['supply']],
                slot=p['slot'],evidence_hash=digest(snapshot),allocation_eligible=False,
                research=dict(pool_age=None,tvl=None,volume=None,realized_fees=None,
                    fee_tvl=None,volatility=None,token_concentration=None,recent_swaps=None))


class Adapter:
    """Explicit pool registry is a bounded discovery source when Data API is absent.

    All final evidence comes from one finalized getMultipleAccounts response; the
    earlier address-discovery read is discarded. Reuses the caller's RPC budget.
    """
    def __init__(self,rpc):
        self.rpc=rpc
        if rpc.call('getGenesisHash',priority=True)!=pump.MAINNET:
            raise Unavailable('unsupported_network')

    def snapshot(self,address,now,priority=False):
        initial=self.rpc.call('getMultipleAccounts',[[address],
            dict(encoding='base64',commitment='finalized')],priority)
        p=pool(initial['value'][0]); center=p['active']//70
        indices=[center-1,center,center+1]
        keys=[address,p['x'],p['y'],p['vault_x'],p['vault_y']]+[array_address(address,i) for i in indices]
        response=self.rpc.call('getMultipleAccounts',[keys,dict(encoding='base64',commitment='finalized',
            minContextSlot=initial['context']['slot'])],priority)
        slot=response['context']['slot']
        market_time=self.rpc.call('getBlockTime',[slot],priority)
        if market_time is None:
            raise Unavailable('dlmm_missing_block_time')
        # Missing adjacent arrays are not invented. Keep available arrays only;
        # quotes fail closed if traversal subsequently needs any absent bin.
        accounts=dict(zip(keys,response['value']))
        indices=[i for i in indices if accounts[array_address(address,i)] is not None]
        snap=dict(pool=address,accounts=accounts,array_indices=indices,slot=slot,
                  market_time=market_time,available_time=int(self.rpc.clock()),
                  network='solana-mainnet',commitment='finalized',kind='real')
        validate(snap,max(now,snap['available_time']),'real')
        return snap

    def discover(self,addresses,now):
        if len(addresses)>4:
            raise ValueError('dlmm_discovery_bound')
        candidates=[]; rejections=[]
        for address in addresses:
            try:
                candidates.append(scout(self.snapshot(address,now),int(self.rpc.clock())))
            except (ValueError,Unavailable,KeyError,TypeError) as exc:
                rejections.append(dict(pool=address,reason=str(exc)[:100]))
        return dict(candidates=candidates,rejections=rejections,allocation_enabled=False)

    def pool_addresses(self,step,now,sol_is_y=True):
        """Bounded public RPC index fallback; requires existing PoolScanRPC.

        Bin step is a discovery partition, not a strategy threshold. Favor fresh
        evidence (at most four addresses), without TVL/APR/profitability ranking.
        The shared transport enforces its existing 2 MB response ceiling.
        """
        if type(step) is not int or not 1<=step<=10000:
            raise ValueError('dlmm_discovery_step')
        rows=self.rpc.call('getProgramAccounts',[PROGRAM,dict(encoding='base64',commitment='finalized',
            dataSlice=dict(offset=56,length=32),filters=[dict(dataSize=904),
                dict(memcmp=dict(offset=120 if sol_is_y else 88,bytes=WSOL)),
                dict(memcmp=dict(offset=80,bytes=pump.b58(struct.pack('<H',step)+b'\0')))])])
        if len(rows)>4000:
            raise Unavailable('dlmm_discovery_response_bound')
        addresses=[]
        for row in rows:
            raw=pump.raw_account(row['account'],PROGRAM)
            if len(raw)!=32:raise ValueError('dlmm_discovery_slice')
            updated=struct.unpack_from('<q',raw)[0]
            if updated<=now:addresses.append((updated,row['pubkey']))
        return [address for _,address in sorted(addresses,reverse=True)[:4]]

    def swap_history(self,start,cursor,end_snapshot=None,now=None,priority=True):
        if not isinstance(start,dict) or end_snapshot is None or now is None:
            raise Unavailable('dlmm_requires_complete_ordered_prestate_and_pool_mutation_history')
        from .dlmm_tape import capture
        return capture(self,start,end_snapshot,now,cursor)
