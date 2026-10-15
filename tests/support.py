import base64
import struct
from meme_machine import pump

MINT=pump.b58(bytes([7])*32)
SCOUT=pump.b58(bytes([8])*32)
CREATOR=pump.b58(bytes([9])*32)


def account(raw,owner):
    return dict(owner=owner,executable=False,data=[base64.b64encode(raw).decode(),'base64'])


def snapshot(now=100,sol=50_000_000_000,token=1_000_000_000_000_000,mint=MINT,creator=CREATOR,slot=None):
    curve=pump.discriminator('BondingCurve')+struct.pack('<QQQQQ?',token,sol,500_000_000_000_000,20_000_000_000,1_000_000_000_000_000,False)+pump.un58(creator)+bytes(66)
    mint_raw=bytes(36)+struct.pack('<QBB',1_000_000_000_000_000,6,1)+bytes(36)
    fee=pump.discriminator('FeeConfig')+bytes(33)+struct.pack('<QQQ',0,100,0)+struct.pack('<I',1)+bytes(16)+struct.pack('<QQQ',0,100,0)
    return dict(mint=mint,pool=pump.pda([b'bonding-curve',pump.un58(mint)]),slot=slot or now,
                market_time=now,available_time=now,accounts=[account(curve,pump.PROGRAM),account(mint_raw,pump.TOKEN_PROGRAM),account(fee,pump.FEE_PROGRAM)],
                decimals=6,protocol='pump.fun',network='solana-mainnet',kind='synthetic')


def event(now=100,wallet=SCOUT,mint=MINT,id='nomination',buy=True):
    return dict(id=id,mint=mint,wallet=wallet,amount=1_000_000_000,tokens=20_000_000_000_000,buy=buy,
                market_time=now,available_time=now,slot=now)


def evidence(now=100,mint=MINT,creator=CREATOR):
    return dict(snapshot=snapshot(now,mint=mint,creator=creator),covered=True,concentration_bps=1000,
                events=[event(now,wallet=pump.b58(bytes([i])*32),mint=mint,id=f'buyer-{i}') for i in (10,11,12)])
