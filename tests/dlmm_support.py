"""Explicit synthetic protocol bytes and external order tape. Not mainnet trades."""
import struct
from copy import deepcopy
from meme_machine import dlmm,pump
from meme_machine.store import digest
from tests.support import account,MINT

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


def event(position,amount=250_000_000,for_y=True,now=None):
    p=deepcopy(position);now=now or p['last_time']+1
    _,observed=dlmm.swap(p['real'],amount,for_y,now)
    return dict(kind='synthetic',commitment='finalized',pool=p['pool'],
        cursor=[p['cursor'][0]+1,0,0],previous_cursor=p['cursor'],prestate_hash=digest(p['real']),
        amount=amount,for_y=for_y,time=now,available_time=now,observed=observed)


def change_account(s,key,offset,data):
    import base64
    s=deepcopy(s);raw=bytearray(base64.b64decode(s['accounts'][key]['data'][0]))
    raw[offset:offset+len(data)]=data
    s['accounts'][key]['data'][0]=base64.b64encode(raw).decode()
    return s
