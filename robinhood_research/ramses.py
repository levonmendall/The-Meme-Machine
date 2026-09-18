"""Ramses deployed DLMM arithmetic; no Meteora state assumptions or allocation.

Ported from the pinned verified BinHelper, PriceHelper, Uint128x128Math,
FeeHelper and PairParameterHelper (MIT). LP fees compound in bin reserves.
Raw replay currently supports swaps; other mutations are explicit boundaries.
"""
from copy import deepcopy
from math import isqrt

from . import BoundaryError
from .abi import decode_event, words
from .identity import load, verify_compilation

Q = 1 << 128
MAX = (1 << 256)-1
PRECISION = 10**18
MAX_LIQUIDITY = 65251743116719673010965625540244653191619923014385985379600384103134737


def ceildiv(a,b):
    return (a+b-1)//b


def price(bin_id, step):
    if not 0 <= bin_id < 2**24 or not 0 < step < 2**16:
        raise BoundaryError('invalid_bin_identity')
    exponent = bin_id - (1 << 23)
    if exponent == 0:
        return Q
    if abs(exponent) >= 0x100000:
        raise BoundaryError('price_exponent_underflow')
    base = Q + (step << 128)//10000
    invert = exponent < 0
    squared = base
    if base > Q-1:
        squared = MAX//base
        invert = not invert
    result = Q
    for bit in range(20):
        if abs(exponent) & (1<<bit):
            result = ((result*squared)&MAX) >> 128
        squared = ((squared*squared)&MAX) >> 128
    if result == 0:
        raise BoundaryError('price_underflow')
    return MAX//result if invert else result


def unpack(value):
    n=int(value,16) if isinstance(value,str) else value
    return [n & (Q-1), n >> 128]


def values(raw):
    return [int.from_bytes(w,'big') for w in words(raw)]


def authenticate_pool(code, *, factory_member, expected_implementation=None):
    """Validate the entire CWIA runtime and its appended token/step arguments."""
    verify_compilation(load('ramses_pool_implementation'))
    impl = expected_implementation or load('ramses_pool_implementation')['address'].lower()
    if impl != load('ramses_pool_implementation')['address'].lower() or factory_member is not True:
        raise BoundaryError('unverified_pool_implementation_or_membership')
    raw=bytes.fromhex(code[2:])
    prefix=bytes.fromhex('363d3d373d3d3d3d61002c806035363936013d73'+impl[2:]+'5af43d3d93803e603357fd5bf3')
    if len(raw)!=97 or raw[:53]!=prefix or raw[-2:]!=b'\x00\x2c':
        raise BoundaryError('unrecognized_pool_clone_runtime')
    x,y='0x'+raw[53:73].hex(),'0x'+raw[73:93].hex()
    step=int.from_bytes(raw[93:95],'big')
    if x==y or int(x,16)==0 or int(y,16)==0 or not step:
        raise BoundaryError('invalid_pool_tokens')
    return dict(implementation=impl,token_x=x,token_y=y,bin_step=step,
                factory=load('ramses_factory')['address'].lower(),proxy='immutable_cwia')


def total_fee(static, volatility, step):
    base,_,_,_,control,share,_=static
    fee=base*step*10**10 + ceildiv((volatility*step)**2*control,100)
    if not 0 <= fee <= 10**17 or not 0 <= share <= 10000:
        raise BoundaryError('invalid_fee_parameters')
    return fee


def update_volatility(static, variable, *, previous_active, active, timestamp):
    acc,ref,id_ref,last=variable
    _,filter_period,decay,reduction,_,_,maximum=static
    if timestamp<last or filter_period==0:
        raise BoundaryError('unsupported_variable_fee_clock')
    if timestamp-last>=filter_period:
        id_ref=previous_active
        ref=acc*reduction//10000 if timestamp-last<decay else 0
    acc=min(ref+abs(active-id_ref)*10000,maximum)
    return [acc,ref,id_ref,timestamp]


def swap_bin(reserves, *, bin_id, step, gross_input, for_y, fee_rate, protocol_share):
    if type(for_y) is not bool or gross_input<=0 or gross_input>=Q or any(not 0<=r<Q for r in reserves):
        raise BoundaryError('invalid_swap_amount')
    if not 0<=fee_rate<=10**17 or not 0<=protocol_share<=10000:
        raise BoundaryError('invalid_fee_parameters')
    p=price(bin_id,step)
    available=reserves[1 if for_y else 0]
    net_max=ceildiv(available*Q,p) if for_y else ceildiv(available*p,Q)
    max_fee=ceildiv(net_max*fee_rate,PRECISION-fee_rate)
    if gross_input>=net_max+max_fee:
        used,fee,out=net_max+max_fee,max_fee,available
    else:
        used=gross_input
        fee=ceildiv(used*fee_rate,PRECISION)
        out=min(available, (used-fee)*p//Q if for_y else (used-fee)*Q//p)
    protocol=fee*protocol_share//10000
    incoming=[used-protocol,0] if for_y else [0,used-protocol]
    outgoing=[0,out] if for_y else [out,0]
    after=[r+i-o for r,i,o in zip(reserves,incoming,outgoing)]
    if any(not 0<=r<Q for r in after) or after[0]*p+after[1]*Q>MAX_LIQUIDITY:
        raise BoundaryError('bin_liquidity_capacity')
    return dict(gross_input=used,output=out,total_fee=fee,protocol_fee=protocol,
                lp_fee=fee-protocol,after=after,incoming=incoming,outgoing=outgoing)


def mint_shares(reserves, supply, amounts, *, bin_id, step, active_id):
    """Exact BinHelper effective amounts; active-bin composition fees gated."""
    if bin_id==active_id:
        raise BoundaryError('active_bin_composition_fee_not_supported')
    if (bin_id<active_id and amounts[0]) or (bin_id>active_id and amounts[1]):
        raise BoundaryError('wrong_side_liquidity')
    if any(not 0<=x<Q for x in reserves+amounts) or supply<0:
        raise BoundaryError('invalid_liquidity_amounts')
    p=price(bin_id,step)
    liquidity=reserves[0]*p+reserves[1]*Q
    user=amounts[0]*p+amounts[1]*Q
    if user==0:
        return 0,[0,0]
    if max(user,liquidity)>MAX:
        raise BoundaryError('liquidity_overflow')
    if liquidity==0 or supply==0:
        return isqrt(user),list(amounts)
    shares=user*supply//liquidity
    effective=ceildiv(shares*liquidity,supply)
    x,y=amounts
    delta=user-effective
    if delta>=Q:
        dy=min(delta//Q,y);y-=dy;delta-=dy*Q
    if delta>=p:
        x-=min(delta//p,x)
    if (reserves[0]+x)*p+(reserves[1]+y)*Q>MAX_LIQUIDITY:
        raise BoundaryError('bin_liquidity_capacity')
    return shares,[x,y]


def burn_amounts(reserves,supply,shares):
    if not 0<shares<=supply:
        raise BoundaryError('invalid_burn_shares')
    out=[r*shares//supply for r in reserves]
    if not any(out):
        raise BoundaryError('zero_burn_output')
    return out


def state(raw):
    v=raw['values']
    if int(v['getLBHooksParameters()'],16):
        raise BoundaryError('unsupported_pool_hooks')
    return dict(active=values(v['getActiveId()'])[0],step=values(v['getBinStep()'])[0],
                reserves=values(v['getReserves()']),protocol=values(v['getProtocolFees()']),
                static=values(v['getStaticFeeParameters()']),variable=values(v['getVariableFeeParameters()']),
                bins={int(b):dict(reserves=values(s['getBin(uint24)']),supply=values(s['totalSupply(uint256)'])[0])
                      for b,s in raw['bins'].items()})


def replay(capture):
    if capture.get('boundary'):
        raise BoundaryError('incomplete_capture')
    pool=capture['pool']
    auth=authenticate_pool(capture['pool_code'],factory_member=int(capture['factory_checks'][pool],16)==1)
    heights=sorted(map(int,capture['states']))
    if len(heights)!=2:
        raise BoundaryError('missing_terminal_state')
    initial,terminal=(state(capture['states'][str(h)]) for h in heights)
    s=deepcopy(initial)
    if s['step']!=auth['bin_step'] or terminal['step']!=auth['bin_step']:
        raise BoundaryError('pool_step_disagreement')
    for h in heights:
        v=capture['states'][str(h)]['values']
        for sig,key in [('getTokenX()','token_x'),('getTokenY()','token_y'),('getFactory()','factory'),('implementation()','implementation')]:
            if '0x'+v[sig][-40:]!=auth[key]:
                raise BoundaryError('pool_wiring_disagreement')
    receipts={r['transactionHash']:r for r in capture['receipts']}
    seen={};events=[]
    for event in capture['logs']:
        identity=(event['blockHash'],event['logIndex'])
        if identity in seen:
            if seen[identity]!=event:
                raise BoundaryError('conflicting_logs')
            continue
        seen[identity]=event;events.append(event)
    expected={ (e['blockHash'],e['logIndex']):e for r in receipts.values() for e in r['logs']
              if e['address'].lower()==pool.lower()}
    if seen!=expected:
        raise BoundaryError('missing_receipt_events')
    fee_by_bin={};txs=set()
    for event in sorted(events,key=lambda e:(int(e['blockNumber'],16),int(e['transactionIndex'],16),int(e['logIndex'],16))):
        h=int(event['blockNumber'],16)
        if not heights[0]<h<=heights[1]:
            raise BoundaryError('event_outside_capture')
        from .pons import raw_event
        authenticated=raw_event(load('ramses_pool_implementation')['abi'],event,address=pool,
            receipt=receipts[event['transactionHash']],header=capture['headers'][str(h)],
            observed_at=capture['ended_at'],confirmation='finalized')
        decoded=authenticated['decoded']
        if decoded['name']!='Swap':
            raise BoundaryError('unsupported_ramses_mutation:'+decoded['name'])
        a=decoded['args'];bid=a['id']
        if bid not in s['bins']:
            raise BoundaryError('missing_bin_prestate')
        incoming,outgoing,fees,protocol=(unpack(a[k]) for k in ('amountsIn','amountsOut','totalFees','protocolFees'))
        for_y=bool(incoming[0])
        inp=0 if for_y else 1;out=1-inp
        if incoming[out] or outgoing[inp] or fees[out] or protocol[out]:
            raise BoundaryError('invalid_swap_direction')
        # A cross-bin move must consume the preceding output bin completely.
        if bid!=s['active']:
            prior=s['bins'].get(s['active'])
            if prior is None or prior['reserves'][out]!=0 or (bid<s['active'])!=for_y:
                raise BoundaryError('unproven_swap_traversal')
        s['variable']=update_volatility(s['static'],s['variable'],previous_active=s['active'],active=bid,
            timestamp=authenticated['event_at'])
        if s['variable'][0]!=a['volatilityAccumulator']:
            raise BoundaryError('volatility_disagreement')
        rate=total_fee(s['static'],s['variable'][0],s['step'])
        result=swap_bin(s['bins'][bid]['reserves'],bin_id=bid,step=s['step'],
            gross_input=incoming[inp]+protocol[inp],for_y=for_y,fee_rate=rate,protocol_share=s['static'][5])
        if (result['incoming']!=incoming or result['outgoing']!=outgoing
            or result['total_fee']!=fees[inp] or result['protocol_fee']!=protocol[inp]):
            raise BoundaryError('swap_arithmetic_disagreement')
        s['bins'][bid]['reserves']=result['after']
        s['reserves']=[r+i-o for r,i,o in zip(s['reserves'],incoming,outgoing)]
        s['protocol']=[r+p for r,p in zip(s['protocol'],protocol)]
        s['active']=bid
        f=fee_by_bin.setdefault(bid,[0,0]);f[inp]+=result['lp_fee']
        txs.add(event['transactionHash'])
    if s!=terminal:
        raise BoundaryError('terminal_state_disagreement')
    # Prices are independently read from the deployed contract at both endpoints.
    for h in heights:
        for b,raw in capture['states'][str(h)]['bins'].items():
            if price(int(b),s['step'])!=int(raw['getPriceFromId(uint24)'],16):
                raise BoundaryError('bin_price_disagreement')
    return dict(pool=pool,implementation=auth['implementation'],events=len(events),transactions=len(txs),
                start=heights[0],end=heights[1],seconds=int(capture['headers'][str(heights[1])]['timestamp'],16)-int(capture['headers'][str(heights[0])]['timestamp'],16),
                terminal_equality=True,lp_fees_by_bin=fee_by_bin,
                modeled_components=['bin_reserves','bin_total_supply','pool_reserves','protocol_fees','active_id','static_fee_parameters','variable_fee_parameters','bin_prices','token_order','implementation','factory','no_hooks'],
                excluded_components=['oracle_ring_storage','individual_LP_owner_balances','non_swap_mutations'],
                prospective_range=False,after_cost_return=None)
