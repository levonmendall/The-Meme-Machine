"""Equivalent grouping restricted to the compiled Pons curve's read-only getters.

These getters read storage/immutables and block.timestamp, without writes, calls,
msg.sender, or gasleft. The unchanged caller must authenticate the exact compiled
curve before accepting any result. One bundle, one contract, one end-of-block
state; never combine different blocks, arbitrary calls, or state overrides.
"""
from collections import defaultdict
from .abi import calldata
from . import BoundaryError

GETTERS=('token()','getReserves()','realQuoteReserve()','reservedTokens()',
         'graduated()','currentSnipeTaxBps(address)','launchedAt()')
SELECTORS={calldata(x,*(['0x'+'11'*20] if 'address' in x else []))[:10] for x in GETTERS}

def grouped(calls):
    groups=defaultdict(list)
    for i,(method,p) in enumerate(calls):
        if method!='eth_call' or len(p)!=2 or not isinstance(p[0],dict):continue
        c,block=p
        if set(c)!={'to','data'} or c['data'][:10] not in SELECTORS:continue
        if not isinstance(block,str) or not block.startswith('0x'):continue
        groups[(c['to'],block)].append(i)
    # One candidate/curve only. Other calls remain independent.
    return [indices for indices in groups.values() if len(indices)>=2]

def batch(rpc,calls,scope,state):
    if not state.get('supported'):return rpc.batch(calls,scope=scope)
    groups=grouped(calls)
    if not groups:return rpc.batch(calls,scope=scope)
    members={i for g in groups for i in g};wire=[];labels=[]
    for i,c in enumerate(calls):
        if i not in members:wire.append(c);labels.append(('single',i))
    for g in groups:
        block=calls[g[0]][1][1]
        txs=[dict(to=calls[i][1][0]['to'],input=calls[i][1][0]['data']) for i in g]
        wire.append(('eth_callMany',[[{'transactions':txs}],{'blockNumber':block,'transactionIndex':-1},{},1000]))
        labels.append(('group',g))
    verifying=not state.get('parity_verified')
    if verifying:
        for i in sorted(members):wire.append(calls[i]);labels.append(('verify',i))
    if len(wire)>50:return rpc.batch(calls,scope=scope)
    try:values=rpc.batch(wire,scope=scope)
    except BoundaryError as exc:
        if str(exc) not in ('provider_rpc_-32601','provider_rpc_-32602'):raise
        state.update(supported=False,fallback_reason=str(exc))
        return rpc.batch(calls,scope=scope)
    out=[None]*len(calls);reference={}
    for label,value in zip(labels,values):
        kind,indices=label
        if kind=='single':out[indices]=value
        elif kind=='verify':reference[indices]=value
        else:
            if not isinstance(value,list) or len(value)!=1 or not isinstance(value[0],list) or len(value[0])!=len(indices):
                raise BoundaryError('callmany_shape_disagreement')
            for i,v in zip(indices,value[0]):
                if not isinstance(v,dict) or 'error' in v or not isinstance(v.get('value'),str):raise BoundaryError('callmany_member_failure')
                out[i]=v['value']
    if verifying:
        if any(out[i]!=v for i,v in reference.items()):
            state.update(supported=False,fallback_reason='callmany_independent_call_disagreement')
            for i,v in reference.items():out[i]=v
        else:state['parity_verified']=True
    state['grouped_members']=state.get('grouped_members',0)+len(members)
    state['groups']=state.get('groups',0)+len(groups)
    return out
