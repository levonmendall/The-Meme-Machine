import base64
import struct
import tempfile
import unittest
from pathlib import Path

from meme_machine import pump
from meme_machine.postgrad import (
    OPENBOOK_V3, PUMPSWAP_PROGRAM, RAYDIUM_AMM_V4, WSOL,
    GraduationHandoff, PostGraduationAdapter, PostGraduationPaperEngine,
    POSTGRAD_ALLOCATION_DISABLED, _decode_open_orders, _decode_pumpswap_pool,
    _decode_raydium_pool, _pda_with_bump, _pumpswap_fee_rates,
    buy_quote, graduation_handoff, pumpswap_pool, pumpswap_pool_creator,
    sell_quote,
)
from meme_machine.store import Store


MINT = pump.b58(bytes([71])*32)
CREATOR = pump.b58(bytes([72])*32)


def account(raw, owner):
    return dict(owner=owner, executable=False,
                data=[base64.b64encode(raw).decode(), 'base64'])


def mint_account(supply=1_000_000_000_000_000, decimals=6, owner=pump.TOKEN_PROGRAM):
    raw = bytes(36)+struct.pack('<QBB', supply, decimals, 1)+bytes(36)
    return account(raw, owner)


def token_account(mint, authority, amount, owner=pump.TOKEN_PROGRAM):
    raw = bytearray(165)
    raw[0:32] = pump.un58(mint)
    raw[32:64] = pump.un58(authority)
    raw[64:72] = int(amount).to_bytes(8, 'little')
    raw[108] = 1
    return account(bytes(raw), owner)


def fee_config(lp=20, protocol=5, creator=50):
    raw = bytearray(109)
    raw[:8] = pump.discriminator('FeeConfig')
    raw[65:69] = struct.pack('<I', 1)
    raw[69:85] = (0).to_bytes(16, 'little')
    raw[85:109] = struct.pack('<QQQ', lp, protocol, creator)
    return account(bytes(raw), pump.FEE_PROGRAM)


def complete_pump_snapshot(now=100, mint=MINT, creator=CREATOR, mayhem=False,
                           retired=False, legacy_layout=False):
    token = 0 if retired else 500_000_000_000_000
    sol = 0 if retired else 80_000_000_000
    real_token = 0
    real_sol = 0 if retired else 30_000_000_000
    curve_supply = 1_000_000_000_000_000
    curve = bytearray(
        pump.discriminator('BondingCurve') +
        struct.pack('<QQQQQ?', token, sol, real_token, real_sol, curve_supply, True) +
        pump.un58(creator) + bytes(66)
    )
    curve[81] = 1 if mayhem else 0
    if legacy_layout:
        if mayhem:
            raise ValueError('legacy layout predates mayhem')
        curve = curve[:81]
    actual_supply = curve_supply + (1_000_000_000*1_000_000 if mayhem else 0)
    mint_acc = mint_account(actual_supply)
    return dict(
        mint=mint, pool=pump.pda([b'bonding-curve', pump.un58(mint)]),
        slot=now, market_time=now, available_time=now,
        accounts=[account(bytes(curve), pump.PROGRAM), mint_acc],
        protocol='pump.fun', network='solana-mainnet',
        kind='synthetic', mint_supply=actual_supply,
    )


def pumpswap_pool_account(mint=MINT, coin_creator=CREATOR, mayhem=False,
                          cashback=False, virtual_quote=0):
    creator = pumpswap_pool_creator(mint)
    pool_key = pumpswap_pool(mint)
    _, bump = _pda_with_bump([
        b'pool', struct.pack('<H', 0), pump.un58(creator),
        pump.un58(mint), pump.un58(WSOL),
    ], PUMPSWAP_PROGRAM)
    lp = pump.b58(bytes([73])*32)
    base_vault = pump.b58(bytes([74])*32)
    quote_vault = pump.b58(bytes([75])*32)
    raw = bytearray()
    raw += pump.discriminator('Pool')
    raw += bytes([bump])
    raw += struct.pack('<H', 0)
    for key in (creator, mint, WSOL, lp, base_vault, quote_vault):
        raw += pump.un58(key)
    raw += struct.pack('<Q', 1_000_000)
    raw += pump.un58(coin_creator)
    raw += bytes([1 if mayhem else 0, 1 if cashback else 0])
    raw += int(virtual_quote).to_bytes(16, 'little', signed=True)
    raw += struct.pack('<Q', 0)
    raw += b'\x00'
    raw += b'\x00'
    return pool_key, account(bytes(raw), PUMPSWAP_PROGRAM), base_vault, quote_vault


def pumpswap_snapshot(kind='synthetic', now=100, slot=100, quote=50_000_000_000,
                      base=500_000_000_000_000):
    return dict(
        mint=MINT, pool=pumpswap_pool(MINT), creator=CREATOR, surface='pumpswap',
        protocol='pump.swap', network='solana-mainnet', model='pumpswap-sol-cp-v1',
        kind=kind, slot=slot, market_time=now, available_time=now,
        state=dict(
            surface='pumpswap', pool=pumpswap_pool(MINT),
            base_reserve=base, quote_reserve=quote, raw_quote_reserve=quote,
            virtual_quote_reserves=0, fee_parts_bps=[20, 5, 50],
            mint_supply=1_000_000_000_000_000, decimals=6,
            coin_creator=CREATOR, mayhem_mode=False, holder_rewards=False,
            base_vault=pump.b58(bytes([74])*32),
            quote_vault=pump.b58(bytes([75])*32),
        ),
        source={},
    )


def raydium_pool_raw(base_mint=MINT, quote_mint=WSOL):
    raw = bytearray(752)
    def put_u64(offset, value):
        raw[offset:offset+8] = struct.pack('<Q', value)
    put_u64(0, 6)
    put_u64(8, 254)
    put_u64(32, 6)
    put_u64(40, 9)
    put_u64(176, 25)
    put_u64(184, 10_000)
    put_u64(192, 10)
    put_u64(200, 20)
    keys = {
        336:pump.b58(bytes([80])*32),
        368:pump.b58(bytes([81])*32),
        400:base_mint,
        432:quote_mint,
        464:pump.b58(bytes([82])*32),
        496:pump.b58(bytes([83])*32),
        528:pump.b58(bytes([84])*32),
        560:OPENBOOK_V3,
        592:pump.b58(bytes([85])*32),
        624:pump.b58(bytes([86])*32),
        656:pump.b58(bytes([87])*32),
        688:pump.b58(bytes([88])*32),
    }
    for offset, key in keys.items():
        raw[offset:offset+32] = pump.un58(key)
    put_u64(720, 123)
    return bytes(raw), keys


def open_orders_account(market, base_total=100, quote_total=200):
    raw = bytearray(3228)
    raw[:5] = b'serum'
    raw[-7:] = b'padding'
    raw[5:13] = struct.pack('<Q', 5)
    raw[13:45] = pump.un58(market)
    raw[45:77] = bytes([90])*32
    raw[85:93] = struct.pack('<Q', base_total)
    raw[101:109] = struct.pack('<Q', quote_total)
    return account(bytes(raw), OPENBOOK_V3)


class FakeRPC:
    def __init__(self, pool_key, pool_acc, mint_acc, base_acc, quote_acc, fee_acc):
        self.url = 'https://example.invalid'
        self.transport = object()
        self._http = object()
        self.calls = 0
        self.pool_key = pool_key
        self.accounts = [pool_acc, mint_acc, base_acc, quote_acc, fee_acc]
    def clock(self):
        return 101
    def call(self, method, params=None, priority=False):
        self.calls += 1
        if method == 'getGenesisHash':
            return pump.MAINNET
        if method == 'getBlockTime':
            return 100
        if method == 'getMultipleAccounts':
            addresses = params[0]
            if addresses == [self.pool_key]:
                return {'context':{'slot':1000}, 'value':[self.accounts[0]]}
            return {'context':{'slot':1001}, 'value':list(self.accounts)}
        raise AssertionError(method)


class PostGraduation(unittest.TestCase):
    def test_completed_curve_handoff_is_required(self):
        snap = complete_pump_snapshot()
        handoff = graduation_handoff(snap, 100)
        self.assertEqual(handoff.mint, MINT)
        self.assertEqual(handoff.creator, CREATOR)
        self.assertFalse(handoff.mayhem_mode)
        bad = complete_pump_snapshot()
        raw = bytearray(base64.b64decode(bad['accounts'][0]['data'][0]))
        raw[48] = 0
        bad['accounts'][0]['data'][0] = base64.b64encode(raw).decode()
        with self.assertRaisesRegex(ValueError, 'not_complete'):
            graduation_handoff(bad, 100)

    def test_retired_and_legacy_completed_curve_handoff_does_not_require_quote_reserves(self):
        retired = complete_pump_snapshot(retired=True)
        handoff = graduation_handoff(retired, 100)
        self.assertEqual(handoff.mint, MINT)
        self.assertEqual(handoff.creator, CREATOR)
        self.assertFalse(handoff.mayhem_mode)
        legacy = complete_pump_snapshot(retired=True, legacy_layout=True)
        legacy_handoff = graduation_handoff(legacy, 100)
        self.assertEqual(legacy_handoff.mint, MINT)
        self.assertFalse(legacy_handoff.mayhem_mode)

    def test_canonical_pumpswap_identity_and_quote_math(self):
        pool_key, pool_acc, _, _ = pumpswap_pool_account()
        parsed = _decode_pumpswap_pool(pool_key, pool_acc, MINT)
        self.assertEqual(parsed['index'], 0)
        self.assertEqual(parsed['creator'], pumpswap_pool_creator(MINT))
        self.assertEqual(parsed['quote_mint'], WSOL)
        rates = _pumpswap_fee_rates(fee_config(), 100_000_000_000, CREATOR)
        self.assertEqual(rates, (20, 5, 50))
        snap = pumpswap_snapshot()
        buy = buy_quote(snap, 250_000_000)
        self.assertEqual(buy.surface, 'pumpswap')
        self.assertLessEqual(buy.input_amount, 250_000_000)
        self.assertGreater(buy.output_amount, 0)
        self.assertGreater(buy.fee_amount, 0)
        sell = sell_quote(snap, buy.output_amount)
        self.assertGreater(sell.output_amount, 0)
        self.assertLess(sell.output_amount, buy.input_amount)

    def test_pumpswap_spoof_and_cashback_fail_closed(self):
        pool_key, pool_acc, _, _ = pumpswap_pool_account(cashback=True)
        with self.assertRaisesRegex(ValueError, 'cashback'):
            _decode_pumpswap_pool(pool_key, pool_acc, MINT)
        good_key, good_acc, _, _ = pumpswap_pool_account()
        with self.assertRaisesRegex(ValueError, 'noncanonical'):
            _decode_pumpswap_pool(pump.b58(bytes([99])*32), good_acc, MINT)
        self.assertEqual(good_key, pumpswap_pool(MINT))

    def test_live_shape_adapter_reads_canonical_pumpswap_only(self):
        handoff = GraduationHandoff(MINT, CREATOR, 'source', 900, 90, False)
        pool_key, pool_acc, base_vault, quote_vault = pumpswap_pool_account()
        mint_acc = mint_account()
        base_acc = token_account(MINT, pool_key, 500_000_000_000_000)
        quote_acc = token_account(WSOL, pool_key, 50_000_000_000)
        rpc = FakeRPC(pool_key, pool_acc, mint_acc, base_acc, quote_acc, fee_config())
        adapter = PostGraduationAdapter(rpc, scan_rpc=object())
        snap = adapter.pumpswap_snapshot(handoff, 101)
        self.assertEqual(snap['surface'], 'pumpswap')
        self.assertEqual(snap['pool'], pool_key)
        self.assertEqual(snap['state']['base_vault'], base_vault)
        self.assertEqual(snap['state']['quote_vault'], quote_vault)
        self.assertEqual(snap['state']['quote_reserve'], 50_000_000_000)
        self.assertEqual(snap['source']['account_slot'], 1001)

    def test_raydium_v4_layout_open_orders_and_state_fee_quote(self):
        raw, keys = raydium_pool_raw()
        pool_key = pump.b58(bytes([79])*32)
        decoded = _decode_raydium_pool(pool_key, account(raw, RAYDIUM_AMM_V4), MINT)
        self.assertEqual(decoded['base_mint'], MINT)
        self.assertEqual(decoded['quote_mint'], WSOL)
        self.assertEqual(decoded['swap_fee_numerator'], 25)
        orders = _decode_open_orders(open_orders_account(keys[528], 100, 200), keys[528])
        self.assertEqual(orders['base_total'], 100)
        self.assertEqual(orders['quote_total'], 200)
        snap = dict(
            mint=MINT, pool=pool_key, creator=CREATOR, surface='raydium-v4',
            protocol='raydium-amm-v4', network='solana-mainnet',
            model='raydium-v4-sol-cp-v1', kind='synthetic',
            slot=100, market_time=100, available_time=100,
            state=dict(surface='raydium-v4', pool=pool_key,
                       base_reserve=500_000_000_000_000,
                       quote_reserve=50_000_000_000,
                       fee_numerator=25, fee_denominator=10_000),
        )
        q = buy_quote(snap, 250_000_000)
        self.assertEqual(q.fee_amount, 625_000)
        self.assertGreater(q.output_amount, 0)
        out = sell_quote(snap, q.output_amount)
        self.assertGreater(out.output_amount, 0)

    def test_prospective_allocation_is_hard_disabled_even_when_shared_capital_allows(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(str(Path(td)/'state.db'), 'prospective', 100_000_000, 'test')
            engine = PostGraduationPaperEngine(store)
            handoff = GraduationHandoff(MINT, CREATOR, 'source', 1, 1, False)
            snap = pumpswap_snapshot(kind='real', now=100)
            self.assertEqual(engine.allocation_reason(handoff, snap, 100),
                             POSTGRAD_ALLOCATION_DISABLED)
            with self.assertRaisesRegex(ValueError, 'allocation_not_proven'):
                PostGraduationPaperEngine(store, test_allocation=True)
            store.close()

    def test_synthetic_paper_lifecycle_uses_same_store_and_shared_bankroll(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(str(Path(td)/'state.db'), 'synthetic', 100_000_000, 'test')
            engine = PostGraduationPaperEngine(store, test_allocation=True)
            handoff = GraduationHandoff(MINT, CREATOR, 'source', 1, 1, False)
            initial_cash = store.state['cash']
            entry = pumpswap_snapshot(now=100, slot=100)
            oid = engine.reserve_for_test(handoff, entry, 100, oid='postgrad-test')
            self.assertEqual(oid, 'postgrad-test')
            self.assertGreater(store.state['reserved'], 0)
            self.assertLess(store.state['cash'], initial_cash)
            fill = pumpswap_snapshot(now=102, slot=102)
            self.assertEqual(engine.fill_for_test(oid, fill, 102), 'settled')
            self.assertIn(MINT, store.state['positions'])
            store.reconcile()
            mark = pumpswap_snapshot(now=107, slot=107, quote=70_000_000_000)
            self.assertEqual(engine.monitor_for_test(MINT, mark, 107), 'exit_intended')
            close = pumpswap_snapshot(now=112, slot=112, quote=70_000_000_000)
            self.assertEqual(engine.monitor_for_test(MINT, close, 112), 'settled')
            self.assertNotIn(MINT, store.state['positions'])
            self.assertEqual(store.state['reserved'], 0)
            self.assertEqual(store.state['rent'], 0)
            self.assertTrue(store.reconcile())
            self.assertIn('exit', store.state['orders'][oid])
            store.close()


if __name__ == '__main__':
    unittest.main()
