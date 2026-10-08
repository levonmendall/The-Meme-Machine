"""Explicit read-only legacy Raydium pool verification.

Historical Pump graduations used an off-chain withdraw/migrator flow and do not have a
current deterministic pool PDA.  A mint can also have several Raydium-v4 WSOL pools.
Therefore this module never discovers or ranks a pool.  It accepts an explicitly
provenanced pool key, validates the complete on-chain Raydium/OpenBook/vault identity,
and returns a read-only snapshot.  This is evidence plumbing only; prospective
post-graduation allocation remains disabled elsewhere.
"""
from dataclasses import dataclass

from . import pump
from .postgrad import (
    OPENBOOK_V3, RAYDIUM_AMM_V4, RAYDIUM_MODEL, WSOL,
    _decode_open_orders, _decode_raydium_pool, _token_account,
)
from .provider import Unavailable


@dataclass(frozen=True)
class LegacyRaydiumProvenance:
    mint: str
    pool: str
    current_pair_identity_verified: bool
    direct_pump_withdraw_lineage_verified: bool
    source_label: str

    @property
    def allocation_eligible(self):
        # This milestone never turns provenance into allocation authority.  Even a
        # future direct lineage proof must still pass a separately authorized gate.
        return False


def read_explicit_pool(adapter, handoff, provenance, now, priority=True):
    """Validate and quote-state an explicit Raydium-v4 pool without selecting it.

    `provenance.pool` is data, not authority.  Every executable identity component is
    revalidated from finalized accounts at read time.  The returned snapshot carries
    both the current-pair and direct-migration lineage flags so callers cannot blur
    those two claims.
    """
    if not isinstance(provenance, LegacyRaydiumProvenance):
        raise TypeError('legacy_raydium_provenance_required')
    if provenance.mint != handoff.mint:
        raise ValueError('legacy_raydium_provenance_mint')
    pump.un58(provenance.pool)

    first = adapter.rpc.call(
        'getMultipleAccounts',
        [[provenance.pool], {'encoding':'base64', 'commitment':'finalized'}],
        priority,
    )
    if not first.get('value') or first['value'][0] is None:
        raise Unavailable('explicit_raydium_pool_missing')
    metadata = _decode_raydium_pool(provenance.pool, first['value'][0], handoff.mint)

    addresses = [
        provenance.pool,
        handoff.mint,
        metadata['base_vault'],
        metadata['quote_vault'],
        metadata['open_orders'],
    ]
    result = adapter.rpc.call(
        'getMultipleAccounts',
        [addresses, {'encoding':'base64', 'commitment':'finalized'}],
        priority,
    )
    if len(result.get('value') or []) != len(addresses) or any(x is None for x in result['value']):
        raise Unavailable('explicit_raydium_accounts_missing')
    pool_account, mint_account, base_vault, quote_vault, open_orders_account = result['value']
    metadata = _decode_raydium_pool(provenance.pool, pool_account, handoff.mint)

    supply, decimals = pump.mint_info(mint_account)
    if supply <= 0 or decimals <= 0:
        raise ValueError('invalid_postgrad_mint')
    base_token_program = mint_account['owner'] if metadata['base_mint'] == handoff.mint else pump.TOKEN_PROGRAM
    quote_token_program = mint_account['owner'] if metadata['quote_mint'] == handoff.mint else pump.TOKEN_PROGRAM
    base_vault_amount = _token_account(
        base_vault, metadata['base_mint'], token_program=base_token_program)
    quote_vault_amount = _token_account(
        quote_vault, metadata['quote_mint'], token_program=quote_token_program)
    orders = _decode_open_orders(open_orders_account, metadata['market_id'])

    effective_base = (
        int(base_vault_amount) + int(orders['base_total']) - int(metadata['base_need_take_pnl']))
    effective_quote = (
        int(quote_vault_amount) + int(orders['quote_total']) - int(metadata['quote_need_take_pnl']))
    if effective_base <= 0 or effective_quote <= 0:
        raise ValueError('invalid_raydium_reserves')
    if metadata['base_mint'] == handoff.mint:
        token_reserve, sol_reserve = effective_base, effective_quote
    elif metadata['quote_mint'] == handoff.mint:
        token_reserve, sol_reserve = effective_quote, effective_base
    else:
        raise ValueError('raydium_pair_identity')

    slot = int(result['context']['slot'])
    market_time = adapter._market_time(slot, priority)
    available_time = int(adapter.rpc.clock())
    # The RPC call itself can advance past the caller's pre-request `now`, so judge
    # freshness at receipt rather than comparing to a stale pre-request clock. This
    # avoids the canary's earlier false future-quote boundary while still failing
    # closed on future or >20-second-old finalized marks.
    if market_time > available_time or available_time-market_time > 20:
        raise ValueError('stale_or_future_raydium_snapshot')

    return dict(
        mint=handoff.mint,
        pool=provenance.pool,
        creator=handoff.creator,
        surface='raydium-v4',
        protocol='raydium-amm-v4',
        network='solana-mainnet',
        model=RAYDIUM_MODEL,
        kind='real',
        slot=slot,
        market_time=market_time,
        available_time=available_time,
        state=dict(
            surface='raydium-v4', pool=provenance.pool,
            base_reserve=token_reserve, quote_reserve=sol_reserve,
            fee_numerator=int(metadata['swap_fee_numerator']),
            fee_denominator=int(metadata['swap_fee_denominator']),
            mint_supply=supply, decimals=decimals,
            base_vault=metadata['base_vault'], quote_vault=metadata['quote_vault'],
            open_orders=metadata['open_orders'], market_id=metadata['market_id'],
            market_program=metadata['market_program'],
            open_orders_base_total=int(orders['base_total']),
            open_orders_quote_total=int(orders['quote_total']),
        ),
        source=dict(
            graduation_slot=handoff.source_slot,
            pool_probe_slot=int(first['context']['slot']),
            account_slot=slot,
            identity_source='explicit_provenance_plus_onchain_validation',
            provenance_label=provenance.source_label,
            current_pair_identity_verified=bool(provenance.current_pair_identity_verified),
            direct_pump_withdraw_lineage_verified=bool(
                provenance.direct_pump_withdraw_lineage_verified),
            allocation_eligible=False,
        ),
        accounts=dict(
            pool=pool_account, mint=mint_account, base_vault=base_vault,
            quote_vault=quote_vault, open_orders=open_orders_account,
        ),
    )
