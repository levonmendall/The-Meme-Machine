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
MAYHEM_EXTRA_WHOLE_TOKENS = 1_000_000_000


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


def _curve_mode_raw(raw):
    if len(raw) < 83:
        raise ValueError('unsupported short curve')
    quote_raw = raw[83:115] if len(raw) >= 115 else bytes(32)
    return dict(
        mayhem=bool(raw[81]),
        cashback=bool(raw[82]),
        quote_mint=None if not any(quote_raw) else b58(quote_raw),
    )


def curve_mode(account):
    return _curve_mode_raw(raw_account(account, PROGRAM, 'BondingCurve'))


def curve(account):
    raw = raw_account(account, PROGRAM, 'BondingCurve')
    mode = _curve_mode_raw(raw)
    values = struct.unpack_from('<QQQQQ?', raw, 8)
    # Mayhem is still a SOL-paired Pump bonding curve: the external Mayhem agent
    # changes market participation, not the reserve invariant used to quote our own
    # buy/sell. Keep cashback and non-native quote assets fail-closed because their
    # cash-flow/accounting semantics are outside pump-sol-cp-v1.
    if mode['cashback'] or mode['quote_mint'] is not None:
        raise ValueError('unsupported cashback or quote asset')
    if min(values[:2]) <= 0 or values[4] <= 0:
        raise ValueError('invalid reserves')
    return Curve(*values, b58(raw[49:81]))


def validate_mint_supply(curve_account, c, mint_supply, decimals):
    """Validate issuance bounds, not immutable equality with creation-time supply.

    BondingCurve.token_total_supply is the curve's creation-time supply parameter.
    Current SPL mint supply is live state and can legitimately decrease when holders
    burn tokens. Therefore equality is not an integrity invariant.

    What must remain true for a supported active Pump mint is:
    - Pump tokens use 6 decimals;
    - live supply cannot be smaller than tokens the bonding curve still claims as
      real inventory; and
    - live supply cannot exceed the protocol's issuance ceiling: the curve's
      creation-time supply for standard coins, or that supply plus Pump's documented
      extra one billion Mayhem tokens.

    Mint/freeze authority and Token-2022 extension safety are validated separately
    by mint_info(). Fee tiers continue to use the actual live mint supply.
    """
    mode = curve_mode(curve_account)
    if decimals != 6:
        raise ValueError('unsupported pump decimals')

    upper = c.supply
    if mode['mayhem']:
        upper += MAYHEM_EXTRA_WHOLE_TOKENS * (10 ** decimals)

    if not c.real_token <= mint_supply <= upper:
        raise ValueError('supply_mismatch')
    return mode


def fees(account, c, mint_supply=None):
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
    effective_supply = c.supply if mint_supply is None else mint_supply
    if effective_supply <= 0:
        raise ValueError('invalid mint supply')
    # Pump fee tiers are selected from market cap using the actual mint supply.
    cap = c.sol*effective_supply//c.token
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



def create_events(tx):
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
        elif line.startswith('Program data: ') and stack and stack[-1] == PROGRAM:
            raw=base64.b64decode(line[14:],validate=True)
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
                mint=b58(raw[offset:offset+32]);offset+=32
                bonding_curve=b58(raw[offset:offset+32]);offset+=32
                user=b58(raw[offset:offset+32]);offset+=32
                creator=b58(raw[offset:offset+32]);offset+=32
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
                            virtual_quote_reserves=struct.unpack_from('<Q',raw,97)[0],
                            virtual_token_reserves=struct.unpack_from('<Q',raw,105)[0],
                            real_quote_reserves=struct.unpack_from('<Q',raw,113)[0],
                            real_token_reserves=struct.unpack_from('<Q',raw,121)[0],
                            creator=b58(raw[177:209]),
                            fees_lamports=struct.unpack_from('<Q',raw,169)[0]+struct.unpack_from('<Q',raw,217)[0]))
    return out
