"""Shared Solana program event decoders used by the evidence service.

This module contains protocol parsing only. It has no strategy thresholds, scoring,
qualification, accounting, or execution authority.
"""
from __future__ import annotations

import base64
import hashlib
import struct

from . import pump
from .postgrad import PUMPSWAP_PROGRAM,WSOL,pumpswap_pool

PUMPSWAP_BUY_EVENT=bytes([103,244,82,31,44,245,119,119])
PUMPSWAP_SELL_EVENT=bytes([62,47,55,10,165,3,220,42])


MIGRATION_DISC=hashlib.sha256(b'event:CompletePumpAmmMigrationEvent').digest()[:8]

def _program_data(line,index,decoded):
    if decoded is None:return base64.b64decode(line[14:],validate=True)
    if index not in decoded:decoded[index]=base64.b64decode(line[14:],validate=True)
    return decoded[index]

def migration_events(tx,*,_decoded=None):
    if not tx or not tx.get('meta') or tx['meta'].get('err'):return []
    stack=[];out=[]
    for index,line in enumerate(tx['meta'].get('logMessages') or []):
        if line.startswith('Program ') and ' invoke [' in line:stack.append(line.split()[1])
        elif line.startswith('Program ') and (' success' in line or ' failed:' in line):
            if stack:stack.pop()
        elif line.startswith('Program data: ') and stack and stack[-1]==pump.PROGRAM:
            raw=_program_data(line,index,_decoded)
            if raw[:8]!=MIGRATION_DISC:continue
            if len(raw) not in (168,200):raise ValueError('migration_event_layout')
            mint=pump.b58(raw[40:72]);quantity,quote,fee=struct.unpack_from('<QQQ',raw,72)
            curve=pump.b58(raw[96:128]);at=struct.unpack_from('<q',raw,128)[0]
            pool=pump.b58(raw[136:168])
            quote_mint=pump.b58(raw[168:200]) if len(raw)==200 else '11111111111111111111111111111111'
            if quote_mint not in (WSOL,'11111111111111111111111111111111'):continue
            if (quantity<=0 or quote<=0 or at<=0 or pool!=pumpswap_pool(mint)
                    or curve!=pump.pda([b'bonding-curve',pump.un58(mint)])):
                raise ValueError('migration_lineage')
            out.append(dict(event_type='migration',mint=mint,pool=pool,bonding_curve=curve,
                market_time=at,index=index,slot=int(tx['slot']),mint_amount=quantity,
                quote_amount=quote,migration_fee=fee,quote_mint=quote_mint,
                quote_asset='SOL' if quote_mint in (WSOL,'11111111111111111111111111111111') else 'OTHER'))
    return out

def pump_events(tx):
    decoded={}
    return (
        [dict(e,event_type='trade') for e in _pump_trade_events(tx,_decoded=decoded)]
        +[dict(e,event_type='create') for e in _pump_create_events(tx,_decoded=decoded)]
        +migration_events(tx,_decoded=decoded)
    )


def _decode_pumpswap_event(raw):
    if len(raw)<184:
        raise ValueError('short_pumpswap_event')
    disc=raw[:8]
    if disc not in (PUMPSWAP_BUY_EVENT,PUMPSWAP_SELL_EVENT):
        return None
    buy=disc==PUMPSWAP_BUY_EVENT
    offset=8
    timestamp=struct.unpack_from('<q',raw,offset)[0];offset+=8
    base_amount=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    _limit_quote=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    _user_base=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    _user_quote=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    pool_base=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    pool_quote=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    quote_amount=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    _lp_bps=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    _lp_fee=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    _protocol_bps=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    _protocol_fee=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    _quote_with_fee=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    user_quote=struct.unpack_from('<Q',raw,offset)[0];offset+=8
    pool=pump.b58(raw[offset:offset+32]);offset+=32
    user=pump.b58(raw[offset:offset+32]);offset+=32
    if min(base_amount,quote_amount,pool_base,pool_quote)<=0:
        raise ValueError('invalid_pumpswap_event')
    return dict(
        pool=pool,wallet=user,amount=int(quote_amount),tokens=int(base_amount),buy=buy,
        market_time=int(timestamp),pool_base_reserve=int(pool_base),
        pool_quote_reserve=int(pool_quote),user_quote_amount=int(user_quote),
    )


def pumpswap_trade_events(tx):
    if not tx or not tx.get('meta') or tx['meta'].get('err'):
        return []
    stack=[];out=[]
    for index,line in enumerate(tx['meta'].get('logMessages') or []):
        if line.startswith('Program ') and ' invoke [' in line:
            stack.append(line.split()[1])
        elif line.startswith('Program ') and (' success' in line or ' failed:' in line):
            if stack:
                stack.pop()
        elif line.startswith('Program data: ') and stack and stack[-1]==PUMPSWAP_PROGRAM:
            try:
                raw=base64.b64decode(line[14:],validate=True)
                event=_decode_pumpswap_event(raw)
            except (ValueError,struct.error):
                continue
            if event is not None:
                event.update(index=index,slot=int(tx.get('slot',0)))
                out.append(event)
    return out


# Protocol-only copies of the certified Pump event codecs. Keeping these in the
# shared plane avoids dependence on a lane-specific legacy decoder revision.
def _pump_create_events(tx,*,_decoded=None):
    """Decode prospectively observed Pump CreateEvent launch parameters."""
    if not tx or not tx.get('meta') or tx['meta']['err']:
        return []
    stack,out=[],[]
    for index,line in enumerate(tx['meta'].get('logMessages') or []):
        if line.startswith('Program ') and ' invoke [' in line:
            stack.append(line.split()[1])
        elif line.startswith('Program ') and (' success' in line or ' failed:' in line):
            if stack:
                stack.pop()
        elif line.startswith('Program data: ') and stack and stack[-1] == pump.PROGRAM:
            raw=_program_data(line,index,_decoded)
            if raw[:8] != bytes([27,114,169,77,222,235,99,118]):
                continue
            offset=8
            try:
                for _ in range(3):
                    if offset+4>len(raw):
                        raise ValueError('truncated create event')
                    size=struct.unpack_from('<I',raw,offset)[0]
                    offset+=4
                    if size>4096 or offset+size>len(raw):
                        raise ValueError('truncated create event')
                    offset+=size
                if offset+168>len(raw):
                    raise ValueError('truncated create event')
                mint=pump.b58(raw[offset:offset+32]);offset+=32
                bonding_curve=pump.b58(raw[offset:offset+32]);offset+=32
                user=pump.b58(raw[offset:offset+32]);offset+=32
                creator=pump.b58(raw[offset:offset+32]);offset+=32
                timestamp=struct.unpack_from('<q',raw,offset)[0];offset+=8
                virtual_token=struct.unpack_from('<Q',raw,offset)[0];offset+=8
                virtual_quote=struct.unpack_from('<Q',raw,offset)[0];offset+=8
                real_token=struct.unpack_from('<Q',raw,offset)[0];offset+=8
                supply=struct.unpack_from('<Q',raw,offset)[0]
            except (struct.error,IndexError):
                raise ValueError('truncated create event') from None
            if min(virtual_token,virtual_quote,real_token,supply)<=0:
                raise ValueError('invalid create reserves')
            out.append(dict(
                mint=mint,bonding_curve=bonding_curve,wallet=user,creator=creator,
                market_time=int(timestamp),index=index,slot=int(tx['slot']),
                initial_virtual_token_reserves=int(virtual_token),
                initial_virtual_quote_reserves=int(virtual_quote),
                initial_real_token_reserves=int(real_token),
                token_total_supply=int(supply),
            ))
    return out


def _pump_trade_events(tx,*,_decoded=None):
    """Only successful finalized RPC transactions; verify actual invocation stack."""
    if not tx or not tx.get('meta') or tx['meta']['err']:
        return []
    stack, out = [], []
    for index, line in enumerate(tx['meta'].get('logMessages') or []):
        if line.startswith('Program ') and ' invoke [' in line:
            stack.append(line.split()[1])
        elif line.startswith('Program ') and (' success' in line or ' failed:' in line):
            if stack:
                stack.pop()
        elif line.startswith('Program data: ') and stack and stack[-1] == pump.PROGRAM:
            raw = _program_data(line,index,_decoded)
            if raw[:8] != bytes([189,219,127,211,78,230,97,238]):
                continue
            if len(raw) < 225:
                raise ValueError('truncated trade event')
            mint = pump.b58(raw[8:40])
            amount, tokens, is_buy = struct.unpack_from('<QQ?', raw, 40)
            user = pump.b58(raw[57:89])
            timestamp = struct.unpack_from('<q', raw, 89)[0]
            out.append(dict(mint=mint, wallet=user, amount=amount, tokens=tokens,
                            buy=is_buy, market_time=timestamp, index=index, slot=tx['slot'],
                            virtual_quote_reserves=struct.unpack_from('<Q',raw,97)[0],
                            virtual_token_reserves=struct.unpack_from('<Q',raw,105)[0],
                            real_quote_reserves=struct.unpack_from('<Q',raw,113)[0],
                            real_token_reserves=struct.unpack_from('<Q',raw,121)[0],
                            creator=pump.b58(raw[177:209]),
                            fees_lamports=struct.unpack_from('<Q',raw,169)[0]+struct.unpack_from('<Q',raw,217)[0]))
    return out
