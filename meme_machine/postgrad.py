"""Read-only post-graduation PumpSwap/Raydium-v4 adapters and disabled paper plumbing.

Policy boundary:
- `continuation-v1` remains owned by Engine.qualify and is not changed here.
- Prospective post-graduation allocation is hard-disabled.
- This module may exercise paper mechanics only in synthetic/captured experiments.
- No transaction building, signing or submission exists here.

Layout provenance:
- pump-fun/pump-public-docs PumpSwap docs + pump_amm IDL.
- raydium-io/raydium-sdk-V2 liquidity v4 layout.
- openbook-dex/program OpenOrders packed layout.
"""
import base64
import hashlib
import struct
from dataclasses import dataclass

from . import pump
from .engine import Allocator, DELAY, GAS, RENT
from .provider import RPC, Unavailable

PUMPSWAP_PROGRAM = 'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA'
PUMPSWAP_GLOBAL_CONFIG = 'ADyA8hdefvWN2dbGGWFotbzWxrAvLW83WG6QCVXvJKqw'
WSOL = 'So11111111111111111111111111111111111111112'
RAYDIUM_AMM_V4 = '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8'
OPENBOOK_V3 = 'srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX'
ZERO_PUBKEY = '11111111111111111111111111111111'
PUMPSWAP_MODEL = 'pumpswap-sol-cp-v1'
RAYDIUM_MODEL = 'raydium-v4-sol-cp-v1'
POSTGRAD_ALLOCATION_DISABLED = 'post_graduation_allocation_disabled'
RAYDIUM_LAYOUT_SIZE = 752
OPEN_ORDERS_SIZE = 3228


class PoolScanRPC(RPC):
    """RPC client with one additional read-only discovery method."""
    ALLOWED = RPC.ALLOWED | {'getProgramAccounts'}


@dataclass(frozen=True)
class GraduationHandoff:
    mint: str
    creator: str
    source_pool: str
    source_slot: int
    source_market_time: int
    mayhem_mode: bool


@dataclass(frozen=True)
class Quote:
    surface: str
    side: str
    input_amount: int
    output_amount: int
    fee_amount: int
    fee_asset: str
    gross_output: int


def _pda_with_bump(seeds, program):
    for bump in range(255, -1, -1):
        raw = hashlib.sha256(
            b''.join(seeds) + bytes([bump]) + pump.un58(program) + b'ProgramDerivedAddress'
        ).digest()
        if not pump.on_curve(raw):
            return pump.b58(raw), bump
    raise ValueError('no PDA')


def pumpswap_pool_creator(base_mint):
    return pump.pda([b'pool-authority', pump.un58(base_mint)], pump.PROGRAM)


def pumpswap_pool(base_mint):
    creator = pumpswap_pool_creator(base_mint)
    return pump.pda([
        b'pool',
        struct.pack('<H', 0),
        pump.un58(creator),
        pump.un58(base_mint),
        pump.un58(WSOL),
    ], PUMPSWAP_PROGRAM)


def pumpswap_fee_address():
    return pump.pda([b'fee_config', pump.un58(PUMPSWAP_PROGRAM)], pump.FEE_PROGRAM)


def graduation_handoff(snapshot, now):
    """Verify that a Pump snapshot represents a completed curve before handoff."""
    if snapshot.get('network') != 'solana-mainnet' or snapshot.get('protocol') != 'pump.fun':
        raise ValueError('unsupported_graduation_scope')
    if not snapshot.get('market_time', now+1) <= snapshot.get('available_time', now+1) <= now:
        raise ValueError('future_graduation_evidence')
    mint = snapshot['mint']
    expected_pool = pump.pda([b'bonding-curve', pump.un58(mint)])
    if snapshot.get('pool') != expected_pool:
        raise ValueError('graduation_pool_identity')
    accounts = snapshot.get('accounts') or []
    if len(accounts) < 2:
        raise ValueError('missing_graduation_accounts')
    c = pump.curve(accounts[0])
    supply, decimals = pump.mint_info(accounts[1])
    mode = pump.validate_mint_supply(accounts[0], c, supply, decimals)
    if not c.complete or c.real_token != 0:
        raise ValueError('bonding_curve_not_complete')
    return GraduationHandoff(
        mint=mint,
        creator=c.creator,
        source_pool=expected_pool,
        source_slot=int(snapshot['slot']),
        source_market_time=int(snapshot['market_time']),
        mayhem_mode=bool(mode['mayhem']),
    )


def _raw(account, owners, exact=None, minimum=None):
    if not account or account.get('executable'):
        raise ValueError('missing_or_executable_account')
    allowed = (owners,) if isinstance(owners, str) else tuple(owners)
    if account.get('owner') not in allowed:
        raise ValueError('unsupported_account_owner')
    data = account.get('data')
    if not isinstance(data, list) or len(data) < 2 or data[1] != 'base64':
        raise ValueError('unsupported_account_encoding')
    raw = base64.b64decode(data[0], validate=True)
    if exact is not None and len(raw) != exact:
        raise ValueError('unexpected_account_size')
    if minimum is not None and len(raw) < minimum:
        raise ValueError('short_account')
    return raw


def _token_account(account, mint, authority=None, token_program=None):
    owner_program = account.get('owner') if account else None
    if token_program is not None and owner_program != token_program:
        raise ValueError('token_program_mismatch')
    raw = _raw(account, (pump.TOKEN_PROGRAM, pump.TOKEN_2022), minimum=165)
    if pump.b58(raw[0:32]) != mint:
        raise ValueError('token_account_mint')
    if authority is not None and pump.b58(raw[32:64]) != authority:
        raise ValueError('token_account_authority')
    if raw[108] != 1:
        raise ValueError('token_account_not_initialized')
    return int.from_bytes(raw[64:72], 'little')


def _decode_pumpswap_pool(pool_key, account, expected_mint):
    raw = _raw(account, PUMPSWAP_PROGRAM, minimum=211)
    if raw[:8] != pump.discriminator('Pool'):
        raise ValueError('pumpswap_pool_discriminator')
    bump = raw[8]
    index = struct.unpack_from('<H', raw, 9)[0]
    offset = 11

    def pub():
        nonlocal offset
        value = pump.b58(raw[offset:offset+32])
        offset += 32
        return value

    creator = pub()
    base_mint = pub()
    quote_mint = pub()
    lp_mint = pub()
    base_vault = pub()
    quote_vault = pub()
    lp_supply = struct.unpack_from('<Q', raw, offset)[0]
    offset += 8
    coin_creator = ZERO_PUBKEY if len(raw) < offset+32 else pump.b58(raw[offset:offset+32])
    offset += 32
    mayhem = False if len(raw) <= offset else bool(raw[offset])
    offset += 1
    cashback = False if len(raw) <= offset else bool(raw[offset])
    offset += 1
    virtual_quote = 0
    if len(raw) >= offset+16:
        virtual_quote = int.from_bytes(raw[offset:offset+16], 'little', signed=True)
    offset += 16
    creator_fee_bps = 0
    if len(raw) >= offset+8:
        creator_fee_bps = struct.unpack_from('<Q', raw, offset)[0]
    offset += 8
    can_edit_creator_fee = False if len(raw) <= offset else bool(raw[offset])
    offset += 1
    holder_rewards = False if len(raw) <= offset else bool(raw[offset])

    expected_creator = pumpswap_pool_creator(expected_mint)
    expected_pool, expected_bump = _pda_with_bump([
        b'pool',
        struct.pack('<H', 0),
        pump.un58(expected_creator),
        pump.un58(expected_mint),
        pump.un58(WSOL),
    ], PUMPSWAP_PROGRAM)
    if pool_key != expected_pool or bump != expected_bump or index != 0:
        raise ValueError('noncanonical_pumpswap_pool')
    if creator != expected_creator or base_mint != expected_mint or quote_mint != WSOL:
        raise ValueError('pumpswap_pool_identity')
    if cashback:
        raise ValueError('pumpswap_cashback_unsupported')
    if creator_fee_bps or can_edit_creator_fee:
        raise ValueError('unsupported_custom_pair_fee')
    if lp_supply <= 0:
        raise ValueError('invalid_pumpswap_lp_supply')
    return dict(
        bump=bump, index=index, creator=creator, base_mint=base_mint,
        quote_mint=quote_mint, lp_mint=lp_mint, base_vault=base_vault,
        quote_vault=quote_vault, lp_supply=lp_supply, coin_creator=coin_creator,
        mayhem_mode=mayhem, cashback=cashback, virtual_quote_reserves=virtual_quote,
        creator_fee_bps=creator_fee_bps, can_edit_creator_fee=can_edit_creator_fee,
        holder_rewards=holder_rewards,
    )


def _pumpswap_fee_rates(account, market_cap, coin_creator):
    raw = _raw(account, pump.FEE_PROGRAM, minimum=69)
    if raw[:8] != pump.discriminator('FeeConfig'):
        raise ValueError('fee_config_discriminator')
    count = struct.unpack_from('<I', raw, 65)[0]
    if not 0 < count <= 64 or len(raw) < 69 + count*40:
        raise ValueError('invalid_fee_tiers')
    tiers = []
    for i in range(count):
        offset = 69+i*40
        threshold = int.from_bytes(raw[offset:offset+16], 'little')
        lp, protocol, creator = struct.unpack_from('<QQQ', raw, offset+16)
        if lp + protocol + creator >= 1000:
            raise ValueError('unsupported_fee_schedule')
        tiers.append((threshold, lp, protocol, creator))
    if [x[0] for x in tiers] != sorted(set(x[0] for x in tiers)):
        raise ValueError('unordered_fee_tiers')
    selected = tiers[0]
    for tier in tiers:
        if market_cap >= tier[0]:
            selected = tier
    _, lp, protocol, creator = selected
    if coin_creator == ZERO_PUBKEY:
        creator = 0
    return int(lp), int(protocol), int(creator)


def _quote_buy_pumpswap(state, budget):
    if budget <= 0:
        raise ValueError('invalid_budget')
    base = int(state['base_reserve'])
    quote = int(state['quote_reserve'])
    rates = tuple(int(x) for x in state['fee_parts_bps'])

    def cost(tokens):
        gross = pump.ceildiv(quote*tokens, base-tokens)
        fees = sum(pump.ceildiv(gross*r, 10_000) for r in rates)
        return gross + fees, gross, fees

    lo, hi = 0, base-1
    while lo < hi:
        tokens = (lo+hi+1)//2
        total, _, _ = cost(tokens)
        if total <= budget:
            lo = tokens
        else:
            hi = tokens-1
    if lo <= 0:
        raise ValueError('zero_fill')
    total, gross, fees = cost(lo)
    return Quote('pumpswap', 'buy', total, lo, fees, 'quote', lo)


def _quote_sell_pumpswap(state, tokens):
    if tokens <= 0:
        raise ValueError('invalid_tokens')
    base = int(state['base_reserve'])
    quote = int(state['quote_reserve'])
    gross = tokens*quote//(base+tokens)
    rates = tuple(int(x) for x in state['fee_parts_bps'])
    fees = sum(pump.ceildiv(gross*r, 10_000) for r in rates)
    net = gross-fees
    if net <= 0:
        raise ValueError('zero_exit')
    return Quote('pumpswap', 'sell', tokens, net, fees, 'quote', gross)


def _quote_raydium(state, side, amount):
    if amount <= 0:
        raise ValueError('invalid_amount')
    num, den = int(state['fee_numerator']), int(state['fee_denominator'])
    if den <= 0 or not 0 <= num < den:
        raise ValueError('invalid_raydium_fee')
    if side == 'buy':
        reserve_in, reserve_out = int(state['quote_reserve']), int(state['base_reserve'])
    elif side == 'sell':
        reserve_in, reserve_out = int(state['base_reserve']), int(state['quote_reserve'])
    else:
        raise ValueError('invalid_side')
    effective = amount*(den-num)//den
    fee = amount-effective
    out = reserve_out*effective//(reserve_in+effective)
    if effective <= 0 or out <= 0 or out >= reserve_out:
        raise ValueError('zero_or_exhaustive_quote')
    return Quote(
        'raydium-v4', side, amount, out, fee,
        'quote' if side == 'buy' else 'base', out,
    )


def buy_quote(snapshot, budget):
    state = snapshot['state']
    if state['surface'] == 'pumpswap':
        return _quote_buy_pumpswap(state, budget)
    if state['surface'] == 'raydium-v4':
        return _quote_raydium(state, 'buy', budget)
    raise ValueError('unsupported_postgrad_surface')


def sell_quote(snapshot, tokens):
    state = snapshot['state']
    if state['surface'] == 'pumpswap':
        return _quote_sell_pumpswap(state, tokens)
    if state['surface'] == 'raydium-v4':
        return _quote_raydium(state, 'sell', tokens)
    raise ValueError('unsupported_postgrad_surface')


def _decode_raydium_pool(pool_key, account, mint):
    raw = _raw(account, RAYDIUM_AMM_V4, exact=RAYDIUM_LAYOUT_SIZE)
    u64 = lambda offset: struct.unpack_from('<Q', raw, offset)[0]
    state = dict(
        status=u64(0), nonce=u64(8), base_decimals=u64(32), quote_decimals=u64(40),
        swap_fee_numerator=u64(176), swap_fee_denominator=u64(184),
        base_need_take_pnl=u64(192), quote_need_take_pnl=u64(200),
        base_vault=pump.b58(raw[336:368]), quote_vault=pump.b58(raw[368:400]),
        base_mint=pump.b58(raw[400:432]), quote_mint=pump.b58(raw[432:464]),
        lp_mint=pump.b58(raw[464:496]), open_orders=pump.b58(raw[496:528]),
        market_id=pump.b58(raw[528:560]), market_program=pump.b58(raw[560:592]),
    )
    if state['status'] == 0:
        raise ValueError('raydium_pool_uninitialized')
    if state['market_program'] != OPENBOOK_V3:
        raise ValueError('unsupported_raydium_market_program')
    if {state['base_mint'], state['quote_mint']} != {mint, WSOL}:
        raise ValueError('raydium_pair_identity')
    if not state['swap_fee_denominator'] or state['swap_fee_numerator'] >= state['swap_fee_denominator']:
        raise ValueError('invalid_raydium_fee')
    state['pool'] = pool_key
    return state


def _decode_open_orders(account, expected_market):
    raw = _raw(account, OPENBOOK_V3, exact=OPEN_ORDERS_SIZE)
    if raw[:5] != b'serum' or raw[-7:] != b'padding':
        raise ValueError('open_orders_padding')
    flags = struct.unpack_from('<Q', raw, 5)[0]
    if flags != 5:
        raise ValueError('open_orders_flags')
    market = pump.b58(raw[13:45])
    if market != expected_market:
        raise ValueError('open_orders_market')
    return dict(
        market=market,
        owner=pump.b58(raw[45:77]),
        base_total=struct.unpack_from('<Q', raw, 85)[0],
        quote_total=struct.unpack_from('<Q', raw, 101)[0],
    )


class PostGraduationAdapter:
    """Resolve verified post-graduation surfaces using only finalized read-only RPC."""
    def __init__(self, rpc, scan_rpc=None, scan_limit=40):
        self.rpc = rpc
        if rpc.call('getGenesisHash', priority=True) != pump.MAINNET:
            raise Unavailable('unsupported_network')
        self.fee_address = pumpswap_fee_address()
        self.scan_rpc = scan_rpc
        if (self.scan_rpc is None and hasattr(rpc, 'url') and
                getattr(rpc, 'transport', None) == getattr(rpc, '_http', None)):
            self.scan_rpc = PoolScanRPC(rpc.url, limit=scan_limit)
        self.scan_verified = False

    def _market_time(self, slot, priority):
        value = self.rpc.call('getBlockTime', [slot], priority)
        if value is None:
            raise Unavailable('missing_block_time')
        return int(value)

    def pumpswap_snapshot(self, handoff, now, priority=True):
        pool_key = pumpswap_pool(handoff.mint)
        probe = self.rpc.call(
            'getMultipleAccounts',
            [[pool_key], {'encoding':'base64', 'commitment':'finalized'}],
            priority,
        )
        pool_account = probe['value'][0]
        if pool_account is None:
            raise Unavailable('pumpswap_pool_missing')
        metadata = _decode_pumpswap_pool(pool_key, pool_account, handoff.mint)
        addresses = [
            pool_key, handoff.mint, metadata['base_vault'], metadata['quote_vault'],
            self.fee_address,
        ]
        result = self.rpc.call(
            'getMultipleAccounts',
            [addresses, {'encoding':'base64', 'commitment':'finalized'}],
            priority,
        )
        if len(result.get('value') or []) != len(addresses) or any(x is None for x in result['value']):
            raise Unavailable('pumpswap_accounts_missing')
        pool_account, mint_account, base_vault, quote_vault, fee_account = result['value']
        metadata = _decode_pumpswap_pool(pool_key, pool_account, handoff.mint)
        supply, decimals = pump.mint_info(mint_account)
        if decimals <= 0 or supply <= 0:
            raise ValueError('invalid_postgrad_mint')
        if metadata['mayhem_mode'] != handoff.mayhem_mode:
            raise ValueError('graduation_mode_mismatch')
        base_reserve = _token_account(
            base_vault, handoff.mint, authority=pool_key, token_program=mint_account['owner'])
        raw_quote = _token_account(
            quote_vault, WSOL, authority=pool_key, token_program=pump.TOKEN_PROGRAM)
        effective_quote = raw_quote + int(metadata['virtual_quote_reserves'])
        if base_reserve <= 0 or effective_quote <= 0:
            raise ValueError('invalid_pumpswap_reserves')
        market_cap = effective_quote*supply//base_reserve
        rates = _pumpswap_fee_rates(fee_account, market_cap, metadata['coin_creator'])
        slot = int(result['context']['slot'])
        market_time = self._market_time(slot, priority)
        return dict(
            mint=handoff.mint, pool=pool_key, creator=handoff.creator,
            surface='pumpswap', protocol='pump.swap', network='solana-mainnet',
            model=PUMPSWAP_MODEL, kind='real', slot=slot, market_time=market_time,
            available_time=int(self.rpc.clock()),
            state=dict(
                surface='pumpswap', pool=pool_key, base_reserve=base_reserve,
                quote_reserve=effective_quote, raw_quote_reserve=raw_quote,
                virtual_quote_reserves=int(metadata['virtual_quote_reserves']),
                fee_parts_bps=list(rates), mint_supply=supply, decimals=decimals,
                coin_creator=metadata['coin_creator'], mayhem_mode=metadata['mayhem_mode'],
                holder_rewards=metadata['holder_rewards'],
                base_vault=metadata['base_vault'], quote_vault=metadata['quote_vault'],
            ),
            source=dict(
                graduation_slot=handoff.source_slot,
                pool_probe_slot=int(probe['context']['slot']),
                account_slot=slot,
                fee_address=self.fee_address,
            ),
        )

    def _verify_scan(self):
        if self.scan_rpc is None:
            raise Unavailable('raydium_scan_unavailable')
        if not self.scan_verified:
            if self.scan_rpc.call('getGenesisHash', priority=True) != pump.MAINNET:
                raise Unavailable('raydium_scan_wrong_network')
            self.scan_verified = True

    def _raydium_candidates(self, mint, priority):
        self._verify_scan()
        candidates = {}
        max_slot = 0
        for offset in (400, 432):
            result = self.scan_rpc.call(
                'getProgramAccounts',
                [RAYDIUM_AMM_V4, {
                    'commitment':'finalized', 'withContext':True, 'encoding':'base64',
                    'filters':[
                        {'dataSize':RAYDIUM_LAYOUT_SIZE},
                        {'memcmp':{'offset':offset, 'bytes':mint}},
                    ],
                }],
                priority,
            )
            if not isinstance(result, dict) or 'context' not in result or 'value' not in result:
                raise Unavailable('invalid_raydium_scan')
            max_slot = max(max_slot, int(result['context'].get('slot', 0)))
            for row in result['value']:
                try:
                    key = row['pubkey']
                    state = _decode_raydium_pool(key, row['account'], mint)
                except (ValueError, KeyError, TypeError):
                    continue
                candidates[key] = state
        if not candidates:
            raise Unavailable('legacy_raydium_pool_missing')
        if len(candidates) != 1:
            raise Unavailable('ambiguous_legacy_raydium_pools')
        key = next(iter(candidates))
        return key, max_slot

    def raydium_snapshot(self, handoff, now, priority=True):
        pool_key, discovery_slot = self._raydium_candidates(handoff.mint, priority)
        first = self.rpc.call(
            'getMultipleAccounts',
            [[pool_key], {'encoding':'base64', 'commitment':'finalized'}],
            priority,
        )
        if not first.get('value') or first['value'][0] is None:
            raise Unavailable('raydium_pool_disappeared')
        metadata = _decode_raydium_pool(pool_key, first['value'][0], handoff.mint)
        addresses = [
            pool_key, handoff.mint, metadata['base_vault'], metadata['quote_vault'],
            metadata['open_orders'],
        ]
        result = self.rpc.call(
            'getMultipleAccounts',
            [addresses, {'encoding':'base64', 'commitment':'finalized'}],
            priority,
        )
        if len(result.get('value') or []) != len(addresses) or any(x is None for x in result['value']):
            raise Unavailable('raydium_accounts_missing')
        pool_account, mint_account, base_vault, quote_vault, open_orders_account = result['value']
        metadata = _decode_raydium_pool(pool_key, pool_account, handoff.mint)
        supply, decimals = pump.mint_info(mint_account)
        if supply <= 0 or decimals <= 0:
            raise ValueError('invalid_postgrad_mint')
        base_vault_amount = _token_account(
            base_vault, metadata['base_mint'], token_program=(
                mint_account['owner'] if metadata['base_mint'] == handoff.mint else pump.TOKEN_PROGRAM))
        quote_vault_amount = _token_account(
            quote_vault, metadata['quote_mint'], token_program=(
                mint_account['owner'] if metadata['quote_mint'] == handoff.mint else pump.TOKEN_PROGRAM))
        orders = _decode_open_orders(open_orders_account, metadata['market_id'])
        effective_base = (
            base_vault_amount + int(orders['base_total']) - int(metadata['base_need_take_pnl']))
        effective_quote = (
            quote_vault_amount + int(orders['quote_total']) - int(metadata['quote_need_take_pnl']))
        if effective_base <= 0 or effective_quote <= 0:
            raise ValueError('invalid_raydium_reserves')
        if metadata['base_mint'] == handoff.mint:
            token_reserve, sol_reserve = effective_base, effective_quote
        else:
            token_reserve, sol_reserve = effective_quote, effective_base
        slot = int(result['context']['slot'])
        market_time = self._market_time(slot, priority)
        return dict(
            mint=handoff.mint, pool=pool_key, creator=handoff.creator,
            surface='raydium-v4', protocol='raydium-amm-v4', network='solana-mainnet',
            model=RAYDIUM_MODEL, kind='real', slot=slot, market_time=market_time,
            available_time=int(self.rpc.clock()),
            state=dict(
                surface='raydium-v4', pool=pool_key, base_reserve=token_reserve,
                quote_reserve=sol_reserve,
                fee_numerator=int(metadata['swap_fee_numerator']),
                fee_denominator=int(metadata['swap_fee_denominator']),
                mint_supply=supply, decimals=decimals,
                base_vault=metadata['base_vault'], quote_vault=metadata['quote_vault'],
                open_orders=metadata['open_orders'], market_id=metadata['market_id'],
                open_orders_base_total=int(orders['base_total']),
                open_orders_quote_total=int(orders['quote_total']),
            ),
            source=dict(
                graduation_slot=handoff.source_slot, discovery_slot=discovery_slot,
                pool_probe_slot=int(first['context']['slot']), account_slot=slot,
            ),
        )

    def resolve(self, handoff, now, priority=True):
        try:
            return self.pumpswap_snapshot(handoff, now, priority)
        except Unavailable as exc:
            if str(exc) != 'pumpswap_pool_missing':
                raise
        return self.raydium_snapshot(handoff, now, priority)


def validate_postgrad_snapshot(snapshot, now, mode):
    expected_kind = 'real' if mode == 'prospective' else mode
    if snapshot.get('kind') != expected_kind:
        raise ValueError('experiment_contamination')
    if snapshot.get('network') != 'solana-mainnet':
        raise ValueError('unsupported_scope')
    if snapshot.get('surface') not in ('pumpswap', 'raydium-v4'):
        raise ValueError('unsupported_postgrad_surface')
    if not snapshot['market_time'] <= snapshot['available_time'] <= now:
        raise ValueError('future_quote')
    if now - snapshot['market_time'] > 20:
        raise ValueError('stale_quote')
    state = snapshot['state']
    if state.get('surface') != snapshot['surface'] or state.get('pool') != snapshot['pool']:
        raise ValueError('snapshot_identity')
    if int(state.get('base_reserve', 0)) <= 0 or int(state.get('quote_reserve', 0)) <= 0:
        raise ValueError('invalid_reserves')
    return state


class PostGraduationPaperEngine:
    """Shared-capital paper mechanics; prospective allocation is intentionally disabled."""
    def __init__(self, store, test_allocation=False):
        self.store = store
        self.allocator = Allocator(store)
        self.test_allocation = bool(test_allocation)
        if self.test_allocation and store.state['mode'] == 'prospective':
            raise ValueError('post_graduation_allocation_not_proven')

    def allocation_reason(self, handoff, snapshot, now):
        validate_postgrad_snapshot(snapshot, now, self.store.state['mode'])
        if snapshot['mint'] != handoff.mint or snapshot['creator'] != handoff.creator:
            return 'handoff_identity'
        amount = self.store.state['initial']//20
        blocked = self.allocator.allowed('spot', amount, handoff.mint, handoff.creator, now)
        return blocked or POSTGRAD_ALLOCATION_DISABLED

    def reserve_for_test(self, handoff, snapshot, now, oid=None):
        if not self.test_allocation or self.store.state['mode'] == 'prospective':
            return POSTGRAD_ALLOCATION_DISABLED
        validate_postgrad_snapshot(snapshot, now, self.store.state['mode'])
        if snapshot['mint'] != handoff.mint or snapshot['creator'] != handoff.creator:
            return 'handoff_identity'
        amount = self.store.state['initial']//20
        blocked = self.allocator.allowed('spot', amount, handoff.mint, handoff.creator, now)
        if blocked:
            return blocked
        quote = buy_quote(snapshot, amount)
        oid = oid or f'postgrad:{handoff.mint}:{now}'
        reservation = amount + GAS + RENT
        with self.store.transaction('postgrad_test_reservation'):
            s = self.store.state
            s['cash'] -= reservation
            s['reserved'] += reservation
            s['orders'][oid] = dict(
                status='reserved', mint=handoff.mint, related=handoff.creator,
                reservation=reservation, budget=amount,
                min_tokens=quote.output_amount*9900//10000,
                created=now, due=now+DELAY, slot=snapshot['slot'],
                surface=snapshot['surface'], model=snapshot['model'],
                handoff=dict(handoff.__dict__), evidence_snapshot=snapshot,
                test_only=True,
            )
        return oid

    def fill_for_test(self, oid, snapshot, now, failed=False):
        order = self.store.state['orders'][oid]
        if order['status'] != 'reserved':
            return order['status']
        if now < order['due']:
            return 'waiting'
        error = None
        quote = None
        try:
            validate_postgrad_snapshot(snapshot, now, self.store.state['mode'])
            if snapshot['mint'] != order['mint'] or snapshot['surface'] != order['surface']:
                raise ValueError('fill_identity')
            if snapshot['market_time'] < order['due'] or snapshot['slot'] <= order['slot']:
                if now-order['created'] <= 60:
                    return 'waiting'
                raise ValueError('no_post_delay_quote')
            quote = buy_quote(snapshot, order['budget'])
            if quote.output_amount < order['min_tokens'] or failed:
                raise ValueError('simulated_attempt_failed')
        except (ValueError, KeyError, TypeError) as exc:
            error = str(exc)
        with self.store.transaction('postgrad_test_entry'):
            s = self.store.state
            s['reserved'] -= order['reservation']
            if error:
                charge = GAS if failed else 0
                s['cash'] += order['reservation']-charge
                s['fees'] += charge
                s['realized'] -= charge
                order.update(status='cancelled', reason=error)
                return 'cancelled'
            cost = quote.input_amount
            s['cash'] += order['reservation']-cost-GAS-RENT
            s['rent'] += RENT
            s['fees'] += GAS
            s['positions'][order['mint']] = dict(
                kind='spot', chain='solana-mainnet', surface=order['surface'],
                tokens=quote.output_amount, basis=cost+GAS, rent=RENT, opened=now,
                related=order['related'], entry_slot=snapshot['slot'], next_monitor=now+5,
                mark=None, mark_time=None, unresolved=False, exit_due=None,
                exit_reason=None, test_only=True,
            )
            s['entry_count'] += 1
            s['funnel']['entries'] += 1
            order.update(status='settled', fill=dict(
                tokens=quote.output_amount, cost=cost, gas=GAS,
                slot=snapshot['slot'], market_time=snapshot['market_time'], time=now,
            ), fill_snapshot=snapshot)
        return 'settled'

    def monitor_for_test(self, mint, snapshot, now, failed=False):
        position = self.store.state['positions'].get(mint)
        if position is None:
            return 'closed'
        if now < position['next_monitor']:
            return 'not_due'
        error = None
        quote = None
        try:
            validate_postgrad_snapshot(snapshot, now, self.store.state['mode'])
            if snapshot['mint'] != mint or snapshot['surface'] != position['surface']:
                raise ValueError('position_quote_identity')
            if snapshot['slot'] < position['entry_slot']:
                raise ValueError('position_quote_slot')
            quote = sell_quote(snapshot, position['tokens'])
        except (ValueError, KeyError, TypeError) as exc:
            error = str(exc)
        with self.store.transaction('postgrad_test_monitor'):
            s = self.store.state
            p = s['positions'][mint]
            p['next_monitor'] = now+5
            if error:
                p.update(mark=None, mark_time=None, unresolved=True)
                return 'unresolved'
            proceeds = quote.output_amount
            p.update(mark=max(0, proceeds-GAS), mark_time=now, unresolved=False)
            reason = (
                'risk' if proceeds-GAS <= p['basis']*9000//10000 else
                'take_profit' if proceeds-GAS >= p['basis']*11500//10000 else
                'timeout' if now-p['opened'] >= 900 else
                'liquidity_invalidation' if snapshot['state']['quote_reserve'] < 5_000_000_000
                else None
            )
            if p['exit_due'] is None and reason:
                p.update(exit_due=now+DELAY, exit_reason=reason, exit_slot=snapshot['slot'])
                return 'exit_intended'
            if (p['exit_due'] is None or now < p['exit_due'] or
                    snapshot['market_time'] < p['exit_due'] or
                    snapshot['slot'] <= p['exit_slot']):
                return 'holding'
            if failed:
                if s['cash'] < GAS:
                    p['unresolved'] = True
                    return 'gas_exhausted'
                s['cash'] -= GAS
                s['realized'] -= GAS
                s['fees'] += GAS
                p['unresolved'] = True
                return 'exit_failed'
            s['cash'] += proceeds-GAS+p['rent']
            s['rent'] -= p['rent']
            s['realized'] += proceeds-GAS-p['basis']
            s['fees'] += GAS
            for order in s['orders'].values():
                if order['mint'] == mint and order['status'] == 'settled' and 'exit' not in order:
                    order['exit'] = dict(
                        reason=p['exit_reason'], proceeds=proceeds, gas=GAS,
                        realized=proceeds-GAS-p['basis'], time=now, snapshot=snapshot,
                    )
            del s['positions'][mint]
            s['funnel']['settled_exits'] += 1
            return 'settled'
