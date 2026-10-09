"""Offline Pump RPC elimination proofs: never use market endpoints or positions."""
import base64
import unittest
from unittest.mock import patch

from meme_machine.lanes.pump import pump
from meme_machine.lanes.pump.postgrad import (
    PostGraduationAdapter, graduation_handoff, buy_quote, sell_quote,
    PUMPSWAP_PROGRAM,
)
from meme_machine.lanes.pump.provider import PumpAdapter, Unavailable
from tests.lanes.pump.test_postgrad import (
    MINT, CREATOR, WSOL, account, complete_pump_snapshot, fee_config,
    mint_account, token_account, pumpswap_pool_account,
)


class MeteredRPC:
    """One authenticated fake, with physical-method accounting."""
    def __init__(self):
        self.time = 101
        self.requests = []
        self.graduation = complete_pump_snapshot()
        self.curve = self.graduation['accounts'][0]
        self.mint = self.graduation['accounts'][1]
        self.pool, pool_acc, base_key, quote_key = pumpswap_pool_account()
        self.base_key, self.quote_key = base_key, quote_key
        self.pool_acc = pool_acc
        self.base_acc = token_account(MINT, self.pool, 500_000_000_000_000)
        self.quote_acc = token_account(WSOL, self.pool, 50_000_000_000)
        self.fee_acc = fee_config()
        self.url = 'https://offline.invalid'
        self.transport = object()
        self._http = object()

    def clock(self):
        return self.time

    def counts(self, method=None):
        return len([name for name, _ in self.requests if method is None or name == method])

    def call(self, method, params=None, priority=False):
        self.requests.append((method, params))
        if method == 'getGenesisHash':
            return pump.MAINNET
        if method == 'getBlockTime':
            return min(self.time - 1, 100)
        if method != 'getMultipleAccounts':
            raise AssertionError('unexpected provider work: ' + str(method))
        addresses = params[0]
        if addresses == [self.pool]:
            return dict(context=dict(slot=1000), value=[self.pool_acc])
        if addresses == [self.graduation['pool'], MINT]:
            return dict(context=dict(slot=1000), value=[self.curve, self.mint])
        if addresses == [self.pool, MINT, self.base_key, self.quote_key,
                         pump.pda([b'fee_config', pump.un58(PUMPSWAP_PROGRAM)], pump.FEE_PROGRAM)]:
            return dict(context=dict(slot=1001),
                        value=[self.pool_acc, self.mint, self.base_acc,
                               self.quote_acc, self.fee_acc])
        raise AssertionError('unexpected address scope: ' + repr(addresses))


class PumpHeldReadEfficiency(unittest.TestCase):
    def setUp(self):
        self.rpc = MeteredRPC()
        self.adapter = PostGraduationAdapter(self.rpc, scan_rpc=object())

    def test_handoff_refresh_is_bounded_and_no_entry_call_is_cached(self):
        first = self.adapter.held_graduation_handoff(MINT, 101)
        initial = self.rpc.counts()
        self.assertEqual(initial, 3)  # genesis, completed curve/mint, block time
        self.assertEqual(first.mint, MINT)
        self.assertEqual(first.creator, CREATOR)
        self.rpc.time = 130
        self.assertEqual(self.adapter.held_graduation_handoff(MINT, 130), first)
        self.assertEqual(self.rpc.counts(), initial)
        self.assertEqual(self.adapter.held_handoff_reuses, 1)
        self.rpc.time = 161
        self.adapter.held_graduation_handoff(MINT, 161)
        self.assertEqual(self.rpc.counts(), initial + 2)
        # Qualification retains the independent full authentication path.
        self.adapter.graduation_snapshot(MINT, 161)
        self.assertEqual(self.rpc.counts(), initial + 4)

    def test_price_fee_liquidity_fresh_and_probe_reused_only_after_proof(self):
        handoff = self.adapter.held_graduation_handoff(MINT, 101)
        before = self.rpc.counts('getMultipleAccounts')
        first = self.adapter.pumpswap_snapshot(handoff, 101, reuse_verified_pool=True)
        self.assertEqual(self.rpc.counts('getMultipleAccounts')-before, 2)
        # A new price and fee tier still require the fresh pool/mint/vault/fee batch.
        self.rpc.quote_acc = token_account(WSOL, self.rpc.pool, 80_000_000_000)
        self.rpc.fee_acc = fee_config(lp=30, protocol=10, creator=20)
        before = self.rpc.counts('getMultipleAccounts')
        second = self.adapter.pumpswap_snapshot(handoff, 101, reuse_verified_pool=True)
        self.assertEqual(self.rpc.counts('getMultipleAccounts')-before, 1)
        self.assertEqual(second['state']['quote_reserve'], 80_000_000_000)
        self.assertEqual(second['state']['fee_parts_bps'], [30, 10, 20])
        self.assertNotEqual(sell_quote(first, 10**9).output_amount,
                            sell_quote(second, 10**9).output_amount)
        self.assertEqual(self.adapter.held_pumpswap_probe_reuses, 1)
        before = self.rpc.counts('getMultipleAccounts')
        entry = self.adapter.pumpswap_snapshot(handoff, 101)
        self.assertEqual(self.rpc.counts('getMultipleAccounts')-before, 2)
        self.assertEqual(entry['state'], second['state'])

    def test_vault_drift_and_incomplete_price_fail_closed_then_cold_restart(self):
        handoff = self.adapter.held_graduation_handoff(MINT, 101)
        self.adapter.pumpswap_snapshot(handoff, 101, reuse_verified_pool=True)
        old = self.rpc.pool_acc
        raw = bytearray(base64.b64decode(old['data'][0]))
        raw[139:171] = bytes([79]) * 32
        self.rpc.pool_acc = account(bytes(raw), PUMPSWAP_PROGRAM)
        with self.assertRaisesRegex(ValueError, 'pumpswap_verified_vault_drift'):
            self.adapter.pumpswap_snapshot(handoff, 101, reuse_verified_pool=True)
        self.assertNotIn(MINT, self.adapter._held_pumpswap_vaults)
        self.assertNotIn(MINT, self.adapter._held_graduation)
        self.rpc.pool_acc = old
        self.rpc.fee_acc = None
        with self.assertRaisesRegex(Unavailable, 'pumpswap_accounts_missing'):
            self.adapter.pumpswap_snapshot(handoff, 101, reuse_verified_pool=True)
        self.rpc.fee_acc = fee_config()
        before = self.rpc.counts('getMultipleAccounts')
        self.adapter.pumpswap_snapshot(handoff, 101, reuse_verified_pool=True)
        self.assertEqual(self.rpc.counts('getMultipleAccounts')-before, 2)
        restarted = PostGraduationAdapter(self.rpc, scan_rpc=object())
        before = self.rpc.counts('getMultipleAccounts')
        restarted.pumpswap_snapshot(handoff, 101, reuse_verified_pool=True)
        self.assertEqual(self.rpc.counts('getMultipleAccounts')-before, 2)

    def test_graduation_identity_change_requires_new_proof(self):
        prior = self.adapter.held_graduation_handoff(MINT, 101)
        self.adapter.pumpswap_snapshot(prior, 101, reuse_verified_pool=True)
        self.rpc.time = 162
        changed = complete_pump_snapshot(creator=pump.b58(bytes([76])*32))
        self.rpc.curve = changed['accounts'][0]
        with self.assertRaisesRegex(ValueError, 'held_graduation_identity_changed'):
            self.adapter.held_graduation_handoff(MINT, 162)
        self.assertNotIn(MINT, self.adapter._held_graduation)
        self.assertNotIn(MINT, self.adapter._held_pumpswap_vaults)

    def test_finalized_slot_time_authority_or_original_rpc_fallback(self):
        handoff = self.adapter.held_graduation_handoff(MINT, 101)
        self.rpc.time = 120
        slots = []
        self.adapter.finalized_market_time = lambda slot: slots.append(slot) or 100
        before = self.rpc.counts('getBlockTime')
        state = self.adapter.pumpswap_snapshot(handoff, 120, reuse_verified_pool=True)
        self.assertEqual(self.rpc.counts('getBlockTime'), before)
        self.assertEqual(slots, [1001])
        self.assertEqual(state['market_time'], 100)
        self.assertEqual(self.adapter.held_finalized_time_reuses, 1)
        for invalid in (None, True, -2, 121, '100'):
            self.adapter.finalized_market_time = lambda slot, value=invalid: value
            before = self.rpc.counts('getBlockTime')
            state = self.adapter.pumpswap_snapshot(handoff, 120, reuse_verified_pool=True)
            self.assertEqual(self.rpc.counts('getBlockTime'), before + 1)
            self.assertEqual(state['market_time'], 100)
        def unavailable(slot):
            raise Unavailable('finalized_local_proof_not_ready')
        self.adapter.finalized_market_time = unavailable
        before = self.rpc.counts('getBlockTime')
        self.adapter.pumpswap_snapshot(handoff, 120, reuse_verified_pool=True)
        self.assertEqual(self.rpc.counts('getBlockTime'), before + 1)

    def test_original_buy_and_sell_economics_unchanged(self):
        handoff = self.adapter.held_graduation_handoff(MINT, 101)
        entry_snapshot = self.adapter.pumpswap_snapshot(handoff, 101)
        cached_snapshot = self.adapter.pumpswap_snapshot(
            handoff, 101, reuse_verified_pool=True)
        # First held quote only enrolls hints; its economics are unchanged.
        self.assertEqual(entry_snapshot['state'], cached_snapshot['state'])
        for qty in (1_000_000, 10**9, 10**11):
            self.assertEqual(sell_quote(entry_snapshot, qty),
                             sell_quote(cached_snapshot, qty))
        self.assertEqual(buy_quote(entry_snapshot, 100_000_000),
                         buy_quote(cached_snapshot, 100_000_000))


if __name__ == '__main__':
    unittest.main()
