"""Synthetic Meteora tape fixtures extracted from pinned historical regressions."""
import base64,copy,struct
from copy import deepcopy
from meme_machine.lanes.meteora import dlmm,pump
from meme_machine.lanes.meteora.dlmm_tape import SWAP,SWAP2,EXACT_IN,EVENT_CPI

MINT=pump.b58(bytes([7])*32)

def account(raw,owner):
    return dict(owner=owner,executable=False,data=[base64.b64encode(raw).decode(),'base64'])

POOL=pump.b58(bytes([40])*32)

VAULT_X=pump.b58(bytes([41])*32)

VAULT_Y=pump.b58(bytes([42])*32)

def snapshot(now=100,slot=100,sol_x=False):
    x,y=(dlmm.WSOL,MINT) if sol_x else (MINT,dlmm.WSOL)
    raw=bytearray(904);raw[:8]=pump.discriminator('LbPair')
    struct.pack_into('<HHHHIIiiHBBB',raw,8,10000,30,600,5000,1000,350000,-1000,1000,2000,0,0,0)
    struct.pack_into('<IIi',raw,40,0,0,0);struct.pack_into('<q',raw,56,now)
    struct.pack_into('<iH',raw,76,0,10)
    for offset,key in [(88,x),(120,y),(152,VAULT_X),(184,VAULT_Y)]:raw[offset:offset+32]=pump.un58(key)
    accounts={POOL:account(raw,dlmm.PROGRAM)}
    for mint in [x,y]:
        m=bytearray(82);struct.pack_into('<QBB',m,36,10**15,9 if mint==dlmm.WSOL else 6,1)
        accounts[mint]=account(m,pump.TOKEN_PROGRAM)
    for key,mint in [(VAULT_X,x),(VAULT_Y,y)]:
        v=bytearray(165);v[:32]=pump.un58(mint);v[32:64]=pump.un58(POOL)
        struct.pack_into('<Q',v,64,10**15);v[108]=1
        accounts[key]=account(v,pump.TOKEN_PROGRAM)
    for index in [-1,0]:
        a=bytearray(10136);a[:8]=pump.discriminator('BinArray')
        struct.pack_into('<q',a,8,index);a[16]=2;a[24:56]=pump.un58(POOL)
        for i in range(70):
            bid=index*70+i;off=56+i*144;px=dlmm.price(bid,10)
            bx=200_000_000 if bid>=0 else 0;by=200_000_000 if bid<=0 else 0
            struct.pack_into('<QQ',a,off,bx,by)
            a[off+16:off+32]=px.to_bytes(16,'little')
            a[off+32:off+48]=(bx*px+by*dlmm.Q).to_bytes(16,'little')
        accounts[dlmm.array_address(POOL,index)]=account(a,dlmm.PROGRAM)
    return dict(pool=POOL,accounts=accounts,array_indices=[-1,0],slot=slot,market_time=now,
        available_time=now,network='solana-mainnet',commitment='finalized',kind='synthetic')

def change_account(s,key,offset,data):
    import base64
    s=deepcopy(s);raw=bytearray(base64.b64decode(s['accounts'][key]['data'][0]))
    raw[offset:offset+len(data)]=data
    s['accounts'][key]['data'][0]=base64.b64encode(raw).decode()
    return s

def encode_state(s,p,slot,now):
    s=copy.deepcopy(s);s.update(slot=slot,market_time=now,available_time=now,kind='real')
    s=change_account(s,POOL,40,struct.pack('<IIi',p['volatility_accumulator'],p['volatility_reference'],p['index_reference']))
    s=change_account(s,POOL,56,struct.pack('<q',p['last_update']))
    s=change_account(s,POOL,76,struct.pack('<i',p['active']))
    s=change_account(s,POOL,216,struct.pack('<QQ',p['protocol_fee_x'],p['protocol_fee_y']))
    for key,field in [('vault_x','vault_x_amount'),('vault_y','vault_y_amount')]:
        s=change_account(s,p[key],64,struct.pack('<Q',p[field]))
    for index in s['array_indices']:
        key=dlmm.array_address(POOL,index);raw=bytearray(base64.b64decode(s['accounts'][key]['data'][0]))
        for i in range(70):
            b=p['bins'][str(index*70+i)];off=56+i*144
            struct.pack_into('<QQ',raw,off,b['x'],b['y'])
            for offset,field in [(16,'price'),(32,'supply'),(80,'fee_x'),(96,'fee_y')]:raw[off+offset:off+offset+16]=b[field].to_bytes(16,'little')
        s['accounts'][key]['data'][0]=base64.b64encode(raw).decode()
    return s

def transaction(p,amount,slot,now,signature='synthetic-signature',swap2=False):
    post,q=dlmm.swap(p,amount,True,now)
    event=(SWAP+pump.un58(POOL)+bytes(32)+struct.pack('<iiQQ?QQ',q['start'],q['end'],amount,q['output'],True,q['fee'],q['protocol_fee'])+bytes(24))
    raw=sorted(EXACT_IN)[0]+struct.pack('<QQ',amount,1)
    events=[dict(programIdIndex=1,accounts=[],data=pump.b58(EVENT_CPI+event))]
    if swap2:
        event2=(SWAP2+pump.un58(POOL)+bytes(32)+struct.pack('<ii?',q['start'],q['end'],True)+
                bytes(16)+struct.pack('<QQQQQQQ??',amount,0,q['output'],q['fee']-q['protocol_fee'],
                q['protocol_fee'],0,0,True,True))
        events.append(dict(programIdIndex=1,accounts=[],data=pump.b58(EVENT_CPI+event2)))
    tx=dict(slot=slot,blockTime=now,transaction=dict(signatures=[signature],message=dict(accountKeys=[POOL,dlmm.PROGRAM],
        instructions=[dict(programIdIndex=1,accounts=[0],data=pump.b58(raw))])),
        meta=dict(err=None,innerInstructions=[dict(index=0,instructions=events)],logMessages=[]))
    return post,tx

