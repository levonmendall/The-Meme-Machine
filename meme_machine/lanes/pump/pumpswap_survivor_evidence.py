"""Authenticated wire formats needed by Survivor; no network or alpha here.

Pump public IDL: pump-fun/pump-public-docs@81091419e4457566469d4e2a27f64ed84d42419c.
Pyth PriceUpdateV2 uses the fully verified Solana sponsored SOL/USD feed.
The existing authenticated Solana provider reads the account; no Hermes client.
"""
import base64
from fractions import Fraction
import hashlib
import struct
from . import pump
from .postgrad import WSOL,pumpswap_pool

SOL_USD_ACCOUNT='7UVimffxr9ow1uXYxsr4LHAcV58mLzhmwaeKvJ1pjLiE'
PYTH_RECEIVER='rec5EKMGg6MxZYaMdyBfgwp4d5rB9T1VQH5pJv5LtFJ'
SOL_USD_FEED=bytes.fromhex('ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d')
from .solana_program_decoders import MIGRATION_DISC,migration_events

def sol_usd_lower_micros(account,*,now,slot,maximum_age=120):
    if not account or account.get('owner')!=PYTH_RECEIVER or account.get('executable'):
        raise ValueError('sol_usd_oracle_owner')
    raw=base64.b64decode(account['data'][0],validate=True)
    if (len(raw)<133 or raw[:8]!=hashlib.sha256(b'account:PriceUpdateV2').digest()[:8]
            or raw[40]!=1 or raw[41:73]!=SOL_USD_FEED):
        raise ValueError('sol_usd_oracle_identity_or_verification')
    price,confidence,exponent,published,previous,ema,ema_conf,posted=struct.unpack_from('<qQiqqqQQ',raw,73)
    if not -18<=exponent<=0 or not 0<=now-published<=maximum_age or posted>slot or price<=confidence:
        raise ValueError('sol_usd_oracle_freshness_or_value')
    return int(Fraction(price-confidence)*Fraction(10)**exponent*1_000_000)
