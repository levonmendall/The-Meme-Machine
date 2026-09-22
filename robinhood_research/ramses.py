"""Ramses deployed DLMM arithmetic; no Meteora state assumptions or allocation.

Ported from the pinned verified BinHelper, PriceHelper, Uint128x128Math,
FeeHelper and PairParameterHelper (MIT). LP fees compound in bin reserves.
Replay covers authenticated swap, liquidity, share, fee and parameter mutations.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from math import isqrt

from . import BoundaryError
from .abi import decode_event, scalar, signature, topic, words
from .identity import load, verify_compilation

Q = 1 << 128
MAX_EVENT_DATA_BYTES = 65536
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


def pack(amounts):
    if len(amounts)!=2 or any(type(x) is not int or not 0<=x<Q for x in amounts):
        raise BoundaryError('invalid_packed_amounts')
    return amounts[0] | (amounts[1]<<128)


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



ZERO='0x'+'00'*20
HURDLE_BPS=35


def _add2(a,b):
    return [a[0]+b[0],a[1]+b[1]]


def _sub2(a,b):
    if b[0]>a[0] or b[1]>a[1]:
        raise BoundaryError('state_underflow')
    return [a[0]-b[0],a[1]-b[1]]


def _liquidity(amounts,p):
    value=amounts[0]*p+amounts[1]*Q
    if value>MAX:
        raise BoundaryError('liquidity_overflow')
    return value


def composition_fees(reserves,amounts,supply,shares,*,fee_rate):
    """Verified BinHelper.getCompositionFees port."""
    if not shares:
        return [0,0]
    post=_add2(reserves,amounts);denom=supply+shares
    received=[post[0]*shares//denom,post[1]*shares//denom]
    fees=[0,0]
    if received[0]>amounts[0]:
        basis=amounts[1]-received[1]
        if basis<0: raise BoundaryError('composition_fee_disagreement')
        fees[1]=basis*fee_rate*(fee_rate+PRECISION)//(PRECISION*PRECISION)
    elif received[1]>amounts[1]:
        basis=amounts[0]-received[0]
        if basis<0: raise BoundaryError('composition_fee_disagreement')
        fees[0]=basis*fee_rate*(fee_rate+PRECISION)//(PRECISION*PRECISION)
    return fees


def mint_effect(reserves,supply,amounts,*,bin_id,step,active_id,static,variable,timestamp):
    """Exact Ramses per-bin mint including active-bin composition fees."""
    if (bin_id<active_id and amounts[0]) or (bin_id>active_id and amounts[1]):
        raise BoundaryError('wrong_side_liquidity')
    if any(not 0<=x<Q for x in reserves+amounts) or supply<0:
        raise BoundaryError('invalid_liquidity_amounts')
    p=price(bin_id,step);bin_liq=_liquidity(reserves,p);user=_liquidity(amounts,p)
    if not user: raise BoundaryError('zero_mint_shares')
    if not bin_liq or not supply:
        shares0=isqrt(user);effective=list(amounts)
    else:
        shares0=user*supply//bin_liq
        target=ceildiv(shares0*bin_liq,supply)
        x,y=amounts;delta=user-target
        if delta>=Q:
            dy=min(delta//Q,y);y-=dy;delta-=dy*Q
        if delta>=p: x-=min(delta//p,x)
        effective=[x,y]
    if not shares0: raise BoundaryError('zero_mint_shares')
    shares=shares0;fees=[0,0];protocol=[0,0];variable_after=list(variable)
    if bin_id==active_id:
        candidate=update_volatility(static,variable,previous_active=active_id,active=active_id,timestamp=timestamp)
        fees=composition_fees(reserves,effective,supply,shares0,fee_rate=total_fee(static,candidate[0],step))
        if any(fees):
            if not bin_liq: raise BoundaryError('composition_fee_empty_bin')
            shares=_liquidity(_sub2(effective,fees),p)*supply//bin_liq
            protocol=[f*static[5]//10000 for f in fees]
            variable_after=candidate
    deposited=_sub2(effective,protocol)
    if not shares or not any(deposited): raise BoundaryError('zero_mint_shares')
    if _liquidity(_add2(reserves,deposited),p)>MAX_LIQUIDITY:
        raise BoundaryError('bin_liquidity_capacity')
    return dict(shares=shares,amounts_in=effective,deposited=deposited,
                composition_fees=fees,protocol_fees=protocol,variable_after=variable_after)


def forced_decay(static,variable,active):
    return [variable[0],variable[0]*static[3]//10000,active,variable[3]]


def _dynamic_value(typ,raw,offset):
    if len(raw)>MAX_EVENT_DATA_BYTES:
        raise BoundaryError('event_data_length')
    if offset%32 or offset<0 or offset+32>len(raw):
        raise BoundaryError('event_dynamic_offset')
    n=int.from_bytes(raw[offset:offset+32],'big')
    # Factory-wide liquidity logs can legitimately span more than 64 bins.
    # Bound work by the already-bounded complete payload, before allocation.
    if n>(len(raw)-offset-32)//32:
        raise BoundaryError('event_dynamic_capacity')
    base=typ[:-2]
    return [scalar(base,raw[offset+32*(i+1):offset+32*(i+2)]) for i in range(n)]


def decode_ramses_event(abi,event):
    """Strict event decoder including Ramses' bounded dynamic-array events."""
    matches=[a for a in abi if a['type']=='event' and not a.get('anonymous')
             and event.get('topics') and topic(signature(a))==event['topics'][0].lower()]
    if len(matches)!=1: raise BoundaryError('unsupported_event_signature')
    spec=matches[0];indexed=[i for i in spec['inputs'] if i['indexed']]
    plain=[i for i in spec['inputs'] if not i['indexed']]
    if len(event['topics'])!=len(indexed)+1: raise BoundaryError('event_topic_count')
    try: raw=bytes.fromhex(event['data'][2:])
    except (ValueError,TypeError): raise BoundaryError('malformed_abi_words') from None
    if len(raw)%32 or len(raw)<32*len(plain) or len(raw)>MAX_EVENT_DATA_BYTES:
        raise BoundaryError('event_data_length')
    out={}
    for spec_i,value in zip(indexed,event['topics'][1:]):
        ws=words(value)
        if len(ws)!=1: raise BoundaryError('event_topic_length')
        out[spec_i['name']]=scalar(spec_i['type'],ws[0])
    for pos,spec_i in enumerate(plain):
        w=raw[32*pos:32*(pos+1)];typ=spec_i['type']
        if typ.endswith('[]'):
            offset=int.from_bytes(w,'big')
            if offset<32*len(plain):
                raise BoundaryError('event_dynamic_offset')
            out[spec_i['name']]=_dynamic_value(typ,raw,offset)
        elif typ in ('bytes','string') or typ.startswith('tuple'): raise BoundaryError('unsupported_dynamic_event')
        else: out[spec_i['name']]=scalar(typ,w)
    return dict(name=spec['name'],signature=signature(spec),args=out)


def _raw_ramses_event(abi,event,*,address,receipt,header,observed_at):
    if event.get('removed'): raise BoundaryError('removed_log_reorg')
    if (event['address'].lower()!=address.lower() or event['blockHash']!=header['hash']
        or event['blockNumber']!=header['number'] or receipt['blockHash']!=header['hash']
        or receipt['transactionHash']!=event['transactionHash']
        or receipt['transactionIndex']!=event['transactionIndex']
        or int(receipt['status'],16)!=1 or event not in receipt['logs']):
        raise BoundaryError('raw_event_identity_disagreement')
    if int(header['timestamp'],16)>observed_at: raise BoundaryError('future_event')
    return dict(decoded=decode_ramses_event(abi,event),event_at=int(header['timestamp'],16))


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
    """Replay every economically relevant Ramses mutation and require terminal equality."""
    if capture.get('boundary'): raise BoundaryError('incomplete_capture')
    pool=capture['pool'];auth=authenticate_pool(capture['pool_code'],factory_member=int(capture['factory_checks'][pool],16)==1)
    heights=sorted(map(int,capture['states']))
    if len(heights)!=2: raise BoundaryError('missing_terminal_state')
    initial,terminal=(state(capture['states'][str(h)]) for h in heights);s=deepcopy(initial)
    if s['step']!=auth['bin_step'] or terminal['step']!=auth['bin_step']: raise BoundaryError('pool_step_disagreement')
    for h in heights:
        v=capture['states'][str(h)]['values']
        for sig,key in [('getTokenX()','token_x'),('getTokenY()','token_y'),('getFactory()','factory'),('implementation()','implementation')]:
            if sig in v and '0x'+v[sig][-40:]!=auth[key]: raise BoundaryError('pool_wiring_disagreement')
    receipts={r['transactionHash']:r for r in capture['receipts']};seen={};events=[]
    for event in capture['logs']:
        ident=(event['blockHash'],event['logIndex'])
        if ident in seen:
            if seen[ident]!=event: raise BoundaryError('conflicting_logs')
            continue
        seen[ident]=event;events.append(event)
    expected={(e['blockHash'],e['logIndex']):e for r in receipts.values() for e in r['logs'] if e['address'].lower()==pool.lower()}
    if seen!=expected: raise BoundaryError('missing_receipt_events')
    abi=load('ramses_pool_implementation')['abi'];fee_by_bin={};composition_by_bin={};fee_events=[]
    txs=set();counts=Counter();contexts={};share_transfers=0
    for event in sorted(events,key=lambda e:(int(e['blockNumber'],16),int(e['transactionIndex'],16),int(e['logIndex'],16))):
        h=int(event['blockNumber'],16)
        if not heights[0]<h<=heights[1]: raise BoundaryError('event_outside_capture')
        authenticated=_raw_ramses_event(abi,event,address=pool,receipt=receipts[event['transactionHash']],
            header=capture['headers'][str(h)],observed_at=capture['ended_at'])
        d=authenticated['decoded'];name=d['name'];a=d['args'];tx=event['transactionHash'];txs.add(tx);counts[name]+=1
        ctx=contexts.setdefault(tx,dict(compositions=[],mint=None,burn=None))
        if name=='Swap':
            bid=a['id']
            if bid not in s['bins']: raise BoundaryError('missing_bin_prestate')
            incoming,outgoing,fees,protocol=(unpack(a[k]) for k in ('amountsIn','amountsOut','totalFees','protocolFees'))
            for_y=bool(incoming[0]);inp=0 if for_y else 1;out=1-inp
            if incoming[out] or outgoing[inp] or fees[out] or protocol[out]: raise BoundaryError('invalid_swap_direction')
            if bid!=s['active']:
                prior=s['bins'].get(s['active'])
                if prior is None or prior['reserves'][out]!=0 or (bid<s['active'])!=for_y: raise BoundaryError('unproven_swap_traversal')
            s['variable']=update_volatility(s['static'],s['variable'],previous_active=s['active'],active=bid,timestamp=authenticated['event_at'])
            if s['variable'][0]!=a['volatilityAccumulator']: raise BoundaryError('volatility_disagreement')
            result=swap_bin(s['bins'][bid]['reserves'],bin_id=bid,step=s['step'],gross_input=incoming[inp]+protocol[inp],
                for_y=for_y,fee_rate=total_fee(s['static'],s['variable'][0],s['step']),protocol_share=s['static'][5])
            if result['incoming']!=incoming or result['outgoing']!=outgoing or result['total_fee']!=fees[inp] or result['protocol_fee']!=protocol[inp]:
                raise BoundaryError('swap_arithmetic_disagreement')
            s['bins'][bid]['reserves']=result['after'];s['reserves']=[r+i-o for r,i,o in zip(s['reserves'],incoming,outgoing)]
            s['protocol']=_add2(s['protocol'],protocol);s['active']=bid
            row=fee_by_bin.setdefault(bid,[0,0]);row[inp]+=result['lp_fee']
            fee_vec=[0,0];fee_vec[inp]=result['lp_fee'];fee_events.append(dict(kind='swap',bin_id=bid,lp_fee=fee_vec,supply_before=s['bins'][bid]['supply'],event_at=authenticated['event_at']))
        elif name=='CompositionFees':
            ctx['compositions'].append(dict(args=a,event_at=authenticated['event_at']))
        elif name=='TransferBatch':
            ids,amounts=a['ids'],a['amounts'];from_,to=a['from'].lower(),a['to'].lower()
            if len(ids)!=len(amounts) or not ids or any(i>=2**24 for i in ids) or any(x<=0 for x in amounts): raise BoundaryError('share_transfer_shape')
            if from_==ZERO and to!=ZERO:
                if ctx['mint'] is not None: raise BoundaryError('duplicate_mint_batch')
                ctx['mint']=dict(ids=ids,shares=amounts,to=to)
            elif to==ZERO and from_!=ZERO:
                if ctx['burn'] is not None: raise BoundaryError('duplicate_burn_batch')
                expected_out=[]
                for bid,amount in zip(ids,amounts):
                    if bid not in s['bins']: raise BoundaryError('missing_bin_prestate')
                    b=s['bins'][bid];outv=burn_amounts(b['reserves'],b['supply'],amount);expected_out.append(outv)
                    b['reserves']=_sub2(b['reserves'],outv);b['supply']-=amount;s['reserves']=_sub2(s['reserves'],outv)
                ctx['burn']=dict(ids=ids,expected=expected_out)
            elif from_!=ZERO and to!=ZERO: share_transfers+=1
            else: raise BoundaryError('invalid_share_transfer')
        elif name=='DepositedToBins':
            pending=ctx['mint']
            if pending is None or pending['ids']!=a['ids'] or pending['to']!=a['to'].lower() or len(a['amounts'])!=len(a['ids']):
                raise BoundaryError('mint_event_pairing')
            comps=list(ctx['compositions']);ci=0
            for bid,share,raw_amount in zip(a['ids'],pending['shares'],a['amounts']):
                if bid not in s['bins']: raise BoundaryError('missing_bin_prestate')
                b=s['bins'][bid];deposited=unpack(raw_amount);candidate=comps[ci] if ci<len(comps) and comps[ci]['args']['id']==bid else None
                protocol=unpack(candidate['args']['protocolFees']) if candidate else [0,0]
                effect=mint_effect(b['reserves'],b['supply'],_add2(deposited,protocol),bin_id=bid,step=s['step'],
                    active_id=s['active'],static=s['static'],variable=s['variable'],timestamp=authenticated['event_at'])
                if effect['shares']!=share or effect['deposited']!=deposited: raise BoundaryError('mint_arithmetic_disagreement')
                if any(effect['composition_fees']):
                    if candidate is None or effect['composition_fees']!=unpack(candidate['args']['totalFees']) or effect['protocol_fees']!=protocol:
                        raise BoundaryError('composition_fee_disagreement')
                    s['variable']=effect['variable_after'];s['protocol']=_add2(s['protocol'],protocol)
                    lp=_sub2(effect['composition_fees'],protocol);row=composition_by_bin.setdefault(bid,[0,0]);row[0]+=lp[0];row[1]+=lp[1]
                    fee_events.append(dict(kind='composition',bin_id=bid,lp_fee=lp,supply_before=b['supply'],event_at=authenticated['event_at']));ci+=1
                elif candidate is not None: raise BoundaryError('unexpected_composition_fee_event')
                b['reserves']=_add2(b['reserves'],deposited);b['supply']+=share;s['reserves']=_add2(s['reserves'],deposited)
            if ci!=len(comps): raise BoundaryError('unpaired_composition_fee_event')
            ctx['compositions']=[];ctx['mint']=None
        elif name=='WithdrawnFromBins':
            pending=ctx['burn'];got=[unpack(x) for x in a['amounts']]
            if pending is None or pending['ids']!=a['ids'] or pending['expected']!=got: raise BoundaryError('burn_arithmetic_disagreement')
            ctx['burn']=None
        elif name=='FlashLoan':
            total,protocol=unpack(a['totalFees']),unpack(a['protocolFees'])
            if a['activeId']!=s['active'] or total!=protocol: raise BoundaryError('flash_loan_fee_disagreement')
            s['protocol']=_add2(s['protocol'],protocol)
        elif name=='CollectedProtocolFees':
            collected=unpack(a['protocolFees']);expected_collected=[p-1 if p else 0 for p in s['protocol']]
            if collected!=expected_collected: raise BoundaryError('protocol_collection_disagreement')
            s['protocol']=[1 if p else 0 for p in s['protocol']]
        elif name=='StaticFeeParametersSet':
            s['static']=[a[k] for k in ('baseFactor','filterPeriod','decayPeriod','reductionFactor','variableFeeControl','protocolShare','maxVolatilityAccumulator')]
            total_fee(s['static'],s['static'][6],s['step'])
        elif name=='ForcedDecay':
            if a['idReference']!=s['variable'][2] or a['volatilityReference']!=s['variable'][1]: raise BoundaryError('forced_decay_disagreement')
            s['variable']=forced_decay(s['static'],s['variable'],s['active'])
        elif name=='HooksParametersSet':
            if int(a['hooksParameters'],16): raise BoundaryError('unsupported_ramses_mutation:HooksParametersSet')
        elif name in ('OracleLengthIncreased','ApprovalForAll'):
            pass
        else:
            raise BoundaryError('unsupported_ramses_mutation:'+name)
    if any(ctx['compositions'] or ctx['mint'] is not None or ctx['burn'] is not None for ctx in contexts.values()):
        raise BoundaryError('unpaired_ramses_mutation')
    if s!=terminal: raise BoundaryError('terminal_state_disagreement')
    for h in heights:
        for b,raw in capture['states'][str(h)]['bins'].items():
            if 'getPriceFromId(uint24)' in raw and price(int(b),s['step'])!=int(raw['getPriceFromId(uint24)'],16): raise BoundaryError('bin_price_disagreement')
    return dict(pool=pool,implementation=auth['implementation'],events=len(events),transactions=len(txs),start=heights[0],end=heights[1],
        seconds=int(capture['headers'][str(heights[1])]['timestamp'],16)-int(capture['headers'][str(heights[0])]['timestamp'],16),
        terminal_equality=True,lp_fees_by_bin=fee_by_bin,composition_lp_fees_by_bin=composition_by_bin,fee_events=fee_events,
        mutation_counts=dict(counts),share_transfers=share_transfers,
        modeled_components=['bin_reserves','bin_total_supply','pool_reserves','protocol_fees','active_id','static_fee_parameters',
            'variable_fee_parameters','bin_prices','token_order','implementation','factory','no_hooks','mint','burn','flash_loan',
            'protocol_fee_collection','share_supply'],
        excluded_components=['oracle_ring_storage','individual_LP_owner_balances'],
        prospective_range=bool(capture.get('range_freeze')),after_cost_return=None,initial_state=initial,terminal_state=terminal)


def quote_value(amounts,p,quote_side):
    if quote_side=='y': return amounts[0]*p//Q+amounts[1]
    if quote_side=='x': return amounts[0]+amounts[1]*Q//p
    raise BoundaryError('invalid_quote_side')


def hurdle_comparison(return_bps,hurdle_bps=HURDLE_BPS):
    if return_bps is None: return 'unresolved'
    return 'above' if return_bps>hurdle_bps else ('equal' if return_bps==hurdle_bps else 'below')


def _range_amount(budget,bid,active,p,quote_side,reserves):
    if bid<active: return [0,budget if quote_side=='y' else budget*p//Q]
    if bid>active: return [budget*Q//p if quote_side=='y' else budget,0]
    liq=_liquidity(reserves,p);target=budget*Q if quote_side=='y' else budget*p
    if not liq: return [0,budget] if quote_side=='y' else [budget,0]
    x=reserves[0]*target//liq;y=reserves[1]*target//liq
    return [x,y] if x or y else ([0,budget] if quote_side=='y' else [budget,0])


def _recent_metrics(prehistory,ids,allocations,step,quote_side):
    lo,hi=min(ids),max(ids);within=near=fee_capture=0;path=[];owned={a['bin_id']:a for a in allocations}
    for row in prehistory or []:
        a=row.get('args',row)
        if 'id' not in a or 'amountsIn' not in a: continue
        bid=a['id'];path.append(bid);p=price(bid,step);gross=_add2(unpack(a['amountsIn']),unpack(a.get('protocolFees',0)))
        volume=quote_value(gross,p,quote_side)
        if lo<=bid<=hi: within+=volume
        if lo-1<=bid<=hi+1: near+=volume
        if bid in owned and 'totalFees' in a:
            lp=_sub2(unpack(a['totalFees']),unpack(a.get('protocolFees',0)));alloc=owned[bid];denom=alloc['pre_supply']+alloc['shares']
            if denom: fee_capture+=quote_value([v*alloc['shares']//denom for v in lp],p,quote_side)
    return dict(recent_within_range_volume=within,near_range_volume=near,
        recent_active_bin_movement=(path[-1]-path[0] if len(path)>1 else 0),estimated_fee_capture=fee_capture)


def freeze_proposals(prestate,capital,*,quote_side,entry_timestamp=None,prehistory=None,gas_costs=None,widths=(1,2,3)):
    """Freeze deterministic narrow/medium/wide proposals before seeing the outcome."""
    if type(capital) is not int or capital<=0 or capital>=Q or quote_side not in ('x','y'): raise BoundaryError('invalid_range_capital')
    active,step=prestate['active'],prestate['step'];entry_timestamp=prestate['variable'][3] if entry_timestamp is None else entry_timestamp
    if entry_timestamp<prestate['variable'][3]: raise BoundaryError('invalid_entry_timestamp')
    proposals=[];current_rate=total_fee(prestate['static'],prestate['variable'][0],step)
    for width in widths:
        ids=list(range(active-width,active+width+1))
        if any(b not in prestate['bins'] for b in ids): raise BoundaryError('missing_range_prestate')
        budgets=[capital//len(ids)]*len(ids);budgets[0]+=capital-sum(budgets);allocations=[];variable=list(prestate['variable'])
        req=[0,0];deposit=[0,0];comp=[0,0];protocol=[0,0]
        for bid,budget in zip(ids,budgets):
            b=prestate['bins'][bid];p=price(bid,step);requested=_range_amount(budget,bid,active,p,quote_side,b['reserves'])
            effect=mint_effect(b['reserves'],b['supply'],requested,bin_id=bid,step=step,active_id=active,static=prestate['static'],
                variable=variable,timestamp=entry_timestamp);variable=effect['variable_after']
            allocations.append(dict(bin_id=bid,pre_reserves=list(b['reserves']),pre_supply=b['supply'],requested=requested,
                amounts_in=effect['amounts_in'],deposited=effect['deposited'],shares=effect['shares'],
                composition_fees=effect['composition_fees'],protocol_fees=effect['protocol_fees'],bin_price=p))
            req=_add2(req,effect['amounts_in']);deposit=_add2(deposit,effect['deposited']);comp=_add2(comp,effect['composition_fees']);protocol=_add2(protocol,effect['protocol_fees'])
        spot=price(active,step);employed=quote_value(req,spot,quote_side);metrics=_recent_metrics(prehistory,ids,allocations,step,quote_side)
        risk_bps=abs(metrics['recent_active_bin_movement'])*step;risk=employed*risk_bps//10000
        projected_before=metrics['estimated_fee_capture']-quote_value(protocol,spot,quote_side)-risk
        required=('entry_gas','add_liquidity_gas','remove_liquidity_gas','unwind_gas')
        gas_ok=isinstance(gas_costs,dict) and all(type(gas_costs.get(k)) is int and gas_costs[k]>=0 for k in required)
        gas_total=sum(gas_costs.get(k,0) for k in required+('claim_gas',)) if gas_ok else None
        after=projected_before-gas_total if gas_total is not None else None;bps=after*10000//employed if after is not None and employed else None
        proposals.append(dict(name={1:'narrow',2:'medium',3:'wide'}.get(width,f'width_{width}'),width=width,bins=ids,active_bin=active,
            quote_side=quote_side,capital_requested=capital,capital_employed=employed,token_requirements=req,pool_deposit=deposit,
            composition_fees=comp,protocol_entry_fees=protocol,initial_inventory_mix=req,initial_spot_value=employed,
            range_reserves={str(a['bin_id']):a['pre_reserves'] for a in allocations},total_shares_by_bin={str(a['bin_id']):a['pre_supply'] for a in allocations},
            allocations=allocations,base_fee=prestate['static'][0]*step*10**10,dynamic_fee=current_rate-prestate['static'][0]*step*10**10,
            protocol_share_bps=prestate['static'][5],lp_share_bps=10000-prestate['static'][5],modeled_inventory_risk_reserve=risk,
            movement_risk_bps=risk_bps,projected_before_gas=projected_before,projected_after_cost_result=after,projected_return_bps=bps,
            hurdle_bps=HURDLE_BPS,hurdle_comparison=hurdle_comparison(bps),exceeds_hurdle=(bps is not None and bps>HURDLE_BPS),
            gas_costs=(dict(gas_costs) if gas_ok else None),**metrics))
    digest=hashlib.sha256(json.dumps(proposals,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return dict(frozen=True,allocation_authority=False,hurdle_bps=HURDLE_BPS,proposal_hash=digest,proposals=proposals)


def verify_proposal_hash(freeze):
    digest=hashlib.sha256(json.dumps(freeze['proposals'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if digest!=freeze['proposal_hash']: raise BoundaryError('frozen_range_modified')
    return True


def paper_position(freeze,proposal_index=0):
    verify_proposal_hash(freeze)
    try: p=deepcopy(freeze['proposals'][proposal_index])
    except (IndexError,TypeError): raise BoundaryError('invalid_range_proposal') from None
    return dict(model='non_impact_exogenous_replay',allocation_authority=False,proposal_hash=freeze['proposal_hash'],
        proposal_index=proposal_index,quote_side=p['quote_side'],initial_cost_basis=p['capital_employed'],initial_token_inventory=p['token_requirements'],
        frozen_range=p['bins'],owned_shares={str(a['bin_id']):a['shares'] for a in p['allocations']},
        deposits={str(a['bin_id']):a['deposited'] for a in p['allocations']},proposal=p)


def paper_removal(position,terminal):
    total=[0,0];by_bin={}
    for a in position['proposal']['allocations']:
        bid=a['bin_id']
        if bid not in terminal['bins']: raise BoundaryError('missing_terminal_range_bin')
        b=terminal['bins'][bid];out=burn_amounts(_add2(b['reserves'],a['deposited']),b['supply']+a['shares'],a['shares'])
        by_bin[str(bid)]=out;total=_add2(total,out)
    return dict(by_bin=by_bin,amounts=total)


def paper_fee_capture(position,replay_result):
    """Exact paper share of replayed LP fees under the frozen non-impact overlay."""
    owned={a['bin_id']:a['shares'] for a in position['proposal']['allocations']}
    totals=[0,0];by_bin={}
    for event in replay_result.get('fee_events',[]):
        shares=owned.get(event['bin_id'],0)
        if not shares: continue
        denom=event['supply_before']+shares
        captured=[v*shares//denom for v in event['lp_fee']]
        totals=_add2(totals,captured);row=by_bin.setdefault(str(event['bin_id']),[0,0]);row[0]+=captured[0];row[1]+=captured[1]
    return dict(amounts=totals,by_bin=by_bin,quote_value=quote_value(totals,price(replay_result['terminal_state']['active'],replay_result['terminal_state']['step']),position['quote_side']))


def paper_outcome(position,terminal,*,unwind=None,costs=None,lp_fees_captured=None):
    removal=paper_removal(position,terminal);quote_side=position['quote_side'];nonquote=0 if quote_side=='y' else 1;quote=1-nonquote
    amounts=removal['amounts'];liquidation=amounts[quote];unresolved=None
    if amounts[nonquote]:
        expected_side='x' if nonquote==0 else 'y'
        if not isinstance(unwind,dict) or unwind.get('input_side')!=expected_side or unwind.get('amount_in')!=amounts[nonquote] or unwind.get('amount_in_left')!=0:
            unresolved='unwind_liquidity_unavailable'
        else: liquidation+=unwind['amount_out']
    cost_ok=isinstance(costs,dict) and all(type(v) is int and v>=0 for v in costs.values());gross=liquidation-position['initial_cost_basis'] if unresolved is None else None
    total_costs=sum(costs.values()) if cost_ok else None;after=gross-total_costs if gross is not None and total_costs is not None else None
    bps=after*10000//position['initial_cost_basis'] if after is not None and position['initial_cost_basis'] else None
    inventory=quote_value(amounts,price(terminal['active'],terminal['step']),quote_side)
    return dict(removal_amounts=amounts,removal_by_bin=removal['by_bin'],inventory_value=inventory,
        inventory_effect=inventory-position['proposal']['initial_spot_value'],lp_fees_captured=lp_fees_captured,unwind=unwind,
        executable_slippage=(unwind.get('slippage') if isinstance(unwind,dict) else None),unresolved_inventory=unresolved,gross_result=gross,
        costs=(dict(costs) if cost_ok else None),total_costs=total_costs,after_cost_result=after,after_cost_return_bps=bps,
        hurdle_bps=HURDLE_BPS,hurdle_comparison=hurdle_comparison(bps),exceeds_hurdle=(bps is not None and bps>HURDLE_BPS))
