"""Read-only Pump.fun SOL bonding-curve decoder and integer quote model.

Layout provenance: pump-fun/pump-public-docs idl/pump.json and pump_fees.json,
read 2026-09-16. No predecessor code or transaction-building SDK.
"""
import base64
import hashlib
import struct
from dataclasses import dataclass

PROGRAM = '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
FEE_PROGRAM = 'pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ'
TOKEN_2022 = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
TOKEN_PROGRAM = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
MAINNET = '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d'
ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
MODEL = 'pump-sol-cp-v1'


def b58(raw):
    n = int.from_bytes(raw, 'big')
    out = ''
    while n:
        n, r = divmod(n, 58)
        out = ALPHABET[r] + out
    return '1' * (len(raw) - len(raw.lstrip(b'\0'))) + out


def un58(s):
    n = 0
    for c in s:
        n = n * 58 + ALPHABET.index(c)
    raw = b'\0' * (len(s) - len(s.lstrip('1'))) + (n.to_bytes((n.bit_length()+7)//8, 'big') if n else b'')
    if len(raw) != 32:
        raise ValueError('invalid public key')
    return raw


def on_curve(raw):
    p = 2**255 - 19
    y = int.from_bytes(raw, 'little') & (2**255-1)
    if y >= p:
        return False
    d = -121665 * pow(121666, p-2, p) % p
    denominator = (d*y*y+1) % p
    if denominator == 0:
        return False
    x2 = (y*y-1) * pow(denominator, p-2, p) % p
    return x2 == 0 or pow(x2, (p-1)//2, p) == 1


def pda(seeds, program=PROGRAM):
    for bump in range(255, -1, -1):
        h = hashlib.sha256(b''.join(seeds)+bytes([bump])+un58(program)+b'ProgramDerivedAddress').digest()
        if not on_curve(h):
            return b58(h)
    raise ValueError('no PDA')


def discriminator(name):
    return hashlib.sha256(('account:'+name).encode()).digest()[:8]


def raw_account(account, owner, name=None):
    if not account or account['owner'] != owner or account.get('executable'):
        raise ValueError('unsupported account owner')
    raw = base64.b64decode(account['data'][0], validate=True)
    if name and raw[:8] != discriminator(name):
        raise ValueError('invalid discriminator')
    return raw


@dataclass(frozen=True)
class Curve:
    token: int
    sol: int
    real_token: int
    real_sol: int
    supply: int
    complete: bool
    creator: str


def curve(account):
    raw = raw_account(account, PROGRAM, 'BondingCurve')
    if len(raw) < 83:
        raise ValueError('unsupported short curve')
    values = struct.unpack_from('<QQQQQ?', raw, 8)
    # Mayhem is still a SOL-paired Pump bonding curve: the external Mayhem agent
    # changes market participation, not the reserve invariant used to quote our own
    # buy/sell. Keep cashback and non-native quote assets fail-closed because their
    # cash-flow/accounting semantics are outside pump-sol-cp-v1.
    if raw[82] or (len(raw) >= 115 and any(raw[83:115])):
        raise ValueError('unsupported cashback or quote asset')
    if min(values[:2]) <= 0 or values[4] <= 0:
        raise ValueError('invalid reserves')
    return Curve(*values, b58(raw[49:81]))


def fees(account, c):
    raw = raw_account(account, FEE_PROGRAM, 'FeeConfig')
    count = struct.unpack_from('<I', raw, 65)[0]
    if not 0 < count <= 64 or len(raw) < 69 + count*40:
        raise ValueError('invalid fee tiers')
    tiers = []
    for i in range(count):
        offset = 69+i*40
        threshold = int.from_bytes(raw[offset:offset+16], 'little')
        lp, protocol, creator = struct.unpack_from('<QQQ', raw, offset+16)
        if lp or protocol+creator >= 1000:
            raise ValueError('unsupported fee schedule')
        tiers.append((threshold, protocol, creator))
    if [x[0] for x in tiers] != sorted(set(x[0] for x in tiers)):
        raise ValueError('unordered fee tiers')
    cap = c.sol*c.supply//c.token
    selected = tiers[0]
    for t in tiers:
        if cap >= t[0]:
            selected = t
    return selected[1:]


def mint_info(account):
    owner = account['owner'] if account else None
    if owner not in (TOKEN_PROGRAM,TOKEN_2022):
        raise ValueError('unsupported token program')
    raw = raw_account(account, owner)
    if len(raw) < 82 or not raw[45] or int.from_bytes(raw[:4], 'little') or int.from_bytes(raw[46:50], 'little'):
        raise ValueError('unsupported mint authority or freeze')
    if owner == TOKEN_PROGRAM and len(raw) != 82:
        raise ValueError('unexpected SPL mint size')
    if owner == TOKEN_2022 and len(raw)>82:
        if len(raw)<166 or raw[165]!=1 or any(raw[82:165]):
            raise ValueError('invalid extended mint')
        offset,seen=166,set()
        while offset<len(raw):
            if not any(raw[offset:]):
                break
            if offset+4>len(raw):
                raise ValueError('truncated extension')
            kind,size=struct.unpack_from('<HH',raw,offset)
            offset+=4
            # Only metadata changes are supported. Reject transfer fees, hooks,
            # delegates, non-transferability, pausing and every unknown extension.
            if kind not in (18,19) or kind in seen or offset+size>len(raw):
                raise ValueError('unsupported transfer behavior or extension')
            if kind==18 and size!=64:
                raise ValueError('invalid metadata pointer')
            seen.add(kind);offset+=size
    return struct.unpack_from('<Q', raw, 36)[0], raw[44]


def ceildiv(a, b):
    return (a+b-1)//b


def fee(amount, rates):
    return sum(ceildiv(amount*r, 10000) for r in rates)


def buy(c, budget, rates):
    if c.complete or budget <= 0:
        raise ValueError('unavailable entry')
    lo, hi = 0, min(c.real_token, c.token-1)
    while lo < hi:
        tokens = (lo+hi+1)//2
        gross = c.sol*tokens//(c.token-tokens)+1
        if gross+fee(gross, rates) <= budget:
            lo = tokens
        else:
            hi = tokens-1
    if not lo or lo >= c.real_token:
        raise ValueError('zero fill or graduation boundary')
    gross = c.sol*lo//(c.token-lo)+1
    return lo, gross+fee(gross, rates), fee(gross, rates)


def sell(c, tokens, rates):
    if c.complete or tokens <= 0:
        raise ValueError('unavailable exit')
    gross = tokens*c.sol//(c.token+tokens)
    if gross > c.real_sol:
        raise ValueError('insufficient real exit liquidity')
    return gross-fee(gross, rates), fee(gross, rates)


def trade_events(tx):
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
        elif line.startswith('Program data: ') and stack and stack[-1] == PROGRAM:
            raw = base64.b64decode(line[14:], validate=True)
            if raw[:8] != bytes([189,219,127,211,78,230,97,238]):
                continue
            if len(raw) < 225:
                raise ValueError('truncated trade event')
            mint = b58(raw[8:40])
            amount, tokens, is_buy = struct.unpack_from('<QQ?', raw, 40)
            user = b58(raw[57:89])
            timestamp = struct.unpack_from('<q', raw, 89)[0]
            out.append(dict(mint=mint, wallet=user, amount=amount, tokens=tokens,
                            buy=is_buy, market_time=timestamp, index=index, slot=tx['slot'],
                            fees_lamports=struct.unpack_from('<Q',raw,169)[0]+struct.unpack_from('<Q',raw,217)[0]))
    return out
