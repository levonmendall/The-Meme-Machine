import unittest

from meme_machine import pump
from meme_machine.legacy_raydium import LegacyRaydiumProvenance, read_explicit_pool
from meme_machine.postgrad import GraduationHandoff, OPENBOOK_V3, PostGraduationAdapter, WSOL
from tests.test_postgrad import (
    MINT, CREATOR, account, mint_account, open_orders_account,
    raydium_pool_raw, token_account,
)


class FakeRaydiumRPC:
    def __init__(self, pool_key, pool_account, mint_acc, base_acc, quote_acc, orders_acc):
        self.url = 'https://example.invalid'
        self.transport = object()
        self._http = object()
        self.calls = 0
        self.pool_key = pool_key
        self.accounts = [pool_account, mint_acc, base_acc, quote_acc, orders_acc]
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


def fixture(reverse=True):
    base_mint, quote_mint = (WSOL, MINT) if reverse else (MINT, WSOL)
    raw, keys = raydium_pool_raw(base_mint=base_mint, quote_mint=quote_mint)
    pool_key = pump.b58(bytes([79])*32)
    pool_acc = account(raw, '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8')
    mint_acc = mint_account()
    if reverse:
        base_acc = token_account(WSOL, pump.b58(bytes([91])*32), 50_000_000_000)
        quote_acc = token_account(MINT, pump.b58(bytes([92])*32), 500_000_000_000_000)
    else:
        base_acc = token_account(MINT, pump.b58(bytes([91])*32), 500_000_000_000_000)
        quote_acc = token_account(WSOL, pump.b58(bytes([92])*32), 50_000_000_000)
    # Raydium vault authority is not encoded in the AMM state, so the read path
    # validates token mint/program and OpenBook linkage rather than inventing one.
    base_raw = bytearray(__import__('base64').b64decode(base_acc['data'][0]))
    quote_raw = bytearray(__import__('base64').b64decode(quote_acc['data'][0]))
    base_raw[32:64] = bytes([93])*32
    quote_raw[32:64] = bytes([93])*32
    import base64
    base_acc['data'][0] = base64.b64encode(base_raw).decode()
    quote_acc['data'][0] = base64.b64encode(quote_raw).decode()
    orders = open_orders_account(keys[528], base_total=100, quote_total=200)
    return pool_key, pool_acc, mint_acc, base_acc, quote_acc, orders


class ExplicitLegacyRaydium(unittest.TestCase):
    def test_explicit_pool_is_onchain_validated_and_orientation_normalized(self):
        pool_key, pool_acc, mint_acc, base_acc, quote_acc, orders = fixture(reverse=True)
        rpc = FakeRaydiumRPC(pool_key, pool_acc, mint_acc, base_acc, quote_acc, orders)
        adapter = PostGraduationAdapter(rpc, scan_rpc=object())
        handoff = GraduationHandoff(MINT, CREATOR, 'source', 900, 90, False)
        provenance = LegacyRaydiumProvenance(
            mint=MINT, pool=pool_key,
            current_pair_identity_verified=True,
            direct_pump_withdraw_lineage_verified=False,
            source_label='captured-known-primary',
        )
        snap = read_explicit_pool(adapter, handoff, provenance, 101)
        self.assertEqual(snap['pool'], pool_key)
        self.assertEqual(snap['surface'], 'raydium-v4')
        self.assertEqual(snap['state']['base_reserve'], 500_000_000_000_000 + 200 - 20)
        self.assertEqual(snap['state']['quote_reserve'], 50_000_000_000 + 100 - 10)
        self.assertTrue(snap['source']['current_pair_identity_verified'])
        self.assertFalse(snap['source']['direct_pump_withdraw_lineage_verified'])
        self.assertFalse(snap['source']['allocation_eligible'])
        self.assertFalse(provenance.allocation_eligible)
        self.assertEqual(snap['state']['market_program'], OPENBOOK_V3)

    def test_explicit_provenance_cannot_override_mint_identity(self):
        pool_key, pool_acc, mint_acc, base_acc, quote_acc, orders = fixture(reverse=False)
        rpc = FakeRaydiumRPC(pool_key, pool_acc, mint_acc, base_acc, quote_acc, orders)
        adapter = PostGraduationAdapter(rpc, scan_rpc=object())
        handoff = GraduationHandoff(MINT, CREATOR, 'source', 900, 90, False)
        bad_mint = pump.b58(bytes([110])*32)
        provenance = LegacyRaydiumProvenance(
            mint=bad_mint, pool=pool_key,
            current_pair_identity_verified=True,
            direct_pump_withdraw_lineage_verified=True,
            source_label='forged',
        )
        with self.assertRaisesRegex(ValueError, 'provenance_mint'):
            read_explicit_pool(adapter, handoff, provenance, 101)

    def test_structurally_wrong_explicit_pool_still_fails_closed(self):
        wrong = pump.b58(bytes([111])*32)
        raw, keys = raydium_pool_raw(base_mint=wrong, quote_mint=WSOL)
        pool_key = pump.b58(bytes([79])*32)
        pool_acc = account(raw, '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8')
        dummy = token_account(WSOL, pump.b58(bytes([93])*32), 1)
        rpc = FakeRaydiumRPC(pool_key, pool_acc, mint_account(), dummy, dummy,
                             open_orders_account(keys[528]))
        adapter = PostGraduationAdapter(rpc, scan_rpc=object())
        handoff = GraduationHandoff(MINT, CREATOR, 'source', 900, 90, False)
        provenance = LegacyRaydiumProvenance(
            mint=MINT, pool=pool_key,
            current_pair_identity_verified=True,
            direct_pump_withdraw_lineage_verified=False,
            source_label='wrong-pool',
        )
        with self.assertRaisesRegex(ValueError, 'pair_identity'):
            read_explicit_pool(adapter, handoff, provenance, 101)


if __name__ == '__main__':
    unittest.main()
