"""Shared Solana program event decoders used by the evidence service.

This module contains protocol parsing only. It has no strategy thresholds, scoring,
qualification, accounting, or execution authority.
"""
from __future__ import annotations

import base64
import struct

from . import pump
from .postgrad import PUMPSWAP_PROGRAM

PUMPSWAP_BUY_EVENT=bytes([103,244,82,31,44,245,119,119])
PUMPSWAP_SELL_EVENT=bytes([62,47,55,10,165,3,220,42])


def pump_events(tx):
    return (
        [dict(e,event_type='trade') for e in pump.trade_events(tx)]
        +[dict(e,event_type='create') for e in pump.create_events(tx)]
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
