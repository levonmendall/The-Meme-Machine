import base64
import struct
import tempfile
import unittest
from pathlib import Path

from meme_machine import pump
from meme_machine.engine import Engine, MAYHEM_AGENT_WALLET
from meme_machine.store import Store
from tests.support import SCOUT, evidence, event, snapshot


def curve_account_with(**changes):
    account = snapshot()['accounts'][0]
    raw = bytearray(base64.b64decode(account['data'][0]))
    if 'mayhem' in changes:
        raw[81] = int(bool(changes['mayhem']))
    if 'cashback' in changes:
        raw[82] = int(bool(changes['cashback']))
    if 'quote_mint' in changes:
        raw[83:115] = pump.un58(changes['quote_mint']) if changes['quote_mint'] else bytes(32)
    account['data'][0] = base64.b64encode(raw).decode()
    return account


def set_mint_supply(account, supply):
    raw = bytearray(base64.b64decode(account['data'][0]))
    struct.pack_into('<Q', raw, 36, supply)
    account['data'][0] = base64.b64encode(raw).decode()
    return account


def enable_mayhem(snap):
    raw = bytearray(base64.b64decode(snap['accounts'][0]['data'][0]))
    raw[81] = 1
    snap['accounts'][0]['data'][0] = base64.b64encode(raw).decode()
    return snap


class MayhemMode(unittest.TestCase):
    def test_sol_paired_mayhem_uses_same_reserve_quote_math(self):
        standard = pump.curve(curve_account_with(mayhem=False))
        mayhem = pump.curve(curve_account_with(mayhem=True))
        self.assertEqual(mayhem, standard)
        rates = (95, 30)
        self.assertEqual(pump.buy(mayhem, 10_000_000, rates), pump.buy(standard, 10_000_000, rates))
        tokens = pump.buy(mayhem, 10_000_000, rates)[0]
        self.assertEqual(pump.sell(mayhem, tokens, rates), pump.sell(standard, tokens, rates))

    def test_mayhem_supply_accepts_documented_extra_billion_and_burns(self):
        account = curve_account_with(mayhem=True)
        c = pump.curve(account)
        extra = pump.MAYHEM_EXTRA_WHOLE_TOKENS * 10**6
        self.assertTrue(pump.validate_mint_supply(account, c, c.supply + extra, 6)['mayhem'])
        self.assertTrue(pump.validate_mint_supply(account, c, c.supply + extra - 1, 6)['mayhem'])
        self.assertTrue(pump.validate_mint_supply(account, c, c.supply, 6)['mayhem'])
        self.assertTrue(pump.validate_mint_supply(account, c, c.supply - 1, 6)['mayhem'])
        self.assertTrue(pump.validate_mint_supply(account, c, c.real_token, 6)['mayhem'])
        with self.assertRaisesRegex(ValueError, 'supply_mismatch'):
            pump.validate_mint_supply(account, c, c.real_token - 1, 6)
        with self.assertRaisesRegex(ValueError, 'supply_mismatch'):
            pump.validate_mint_supply(account, c, c.supply + extra + 1, 6)
        with self.assertRaisesRegex(ValueError, 'unsupported pump decimals'):
            pump.validate_mint_supply(account, c, c.supply + extra, 9)

    def test_standard_supply_validation_proves_bounds_not_creation_time_equality(self):
        account = curve_account_with(mayhem=False)
        c = pump.curve(account)
        # Exact class of state proven by the live smoke: valid holder burns reduce
        # current mint supply while BondingCurve.token_total_supply stays unchanged.
        burned_supply = c.supply - 19_345_511_376
        self.assertGreaterEqual(burned_supply, c.real_token)
        self.assertFalse(pump.validate_mint_supply(account, c, burned_supply, 6)['mayhem'])
        self.assertFalse(pump.validate_mint_supply(account, c, c.real_token, 6)['mayhem'])
        with self.assertRaisesRegex(ValueError, 'supply_mismatch'):
            pump.validate_mint_supply(account, c, c.real_token - 1, 6)
        with self.assertRaisesRegex(ValueError, 'supply_mismatch'):
            pump.validate_mint_supply(account, c, c.supply + 1, 6)
        with self.assertRaisesRegex(ValueError, 'unsupported pump decimals'):
            pump.validate_mint_supply(account, c, c.supply, 9)

    def test_fee_tier_uses_actual_mint_supply(self):
        snap = snapshot()
        c = pump.curve(snap['accounts'][0])
        fee_account = snap['accounts'][2]
        raw = bytearray(base64.b64decode(fee_account['data'][0]))
        struct.pack_into('<I', raw, 65, 2)
        threshold = 75_000_000_000
        raw += threshold.to_bytes(16, 'little') + struct.pack('<QQQ', 0, 200, 0)
        fee_account['data'][0] = base64.b64encode(raw).decode()
        self.assertEqual(pump.fees(fee_account, c, c.supply), (100, 0))
        self.assertEqual(pump.fees(fee_account, c, c.supply * 2), (200, 0))

    def test_engine_accepts_mayhem_supply_without_policy_change(self):
        snap = enable_mayhem(snapshot())
        c = pump.curve(snap['accounts'][0])
        set_mint_supply(snap['accounts'][1], c.supply * 2)
        with tempfile.TemporaryDirectory() as td:
            store = Store(str(Path(td)/'state.db'), 'synthetic', 100_000_000, 'test')
            try:
                engine = Engine(store, [SCOUT])
                validated, rates = engine.validate_snapshot(snap, 100)
                self.assertEqual(validated, c)
                self.assertEqual(rates, pump.fees(snap['accounts'][2], c, c.supply * 2))
            finally:
                store.close()

    def test_disclosed_mayhem_agent_cannot_be_scout(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(str(Path(td)/'state.db'), 'synthetic', 100_000_000, 'test')
            try:
                with self.assertRaisesRegex(ValueError, 'system_wallet_cannot_scout'):
                    Engine(store, [MAYHEM_AGENT_WALLET])
            finally:
                store.close()

    def test_mayhem_agent_does_not_count_as_independent_demand(self):
        ev = evidence()
        enable_mayhem(ev['snapshot'])
        ev['events'][0]['wallet'] = MAYHEM_AGENT_WALLET
        with tempfile.TemporaryDirectory() as td:
            store = Store(str(Path(td)/'state.db'), 'synthetic', 100_000_000, 'test')
            try:
                engine = Engine(store, [SCOUT])
                self.assertEqual(engine.qualify(event(), ev, 100), 'independent_demand')
            finally:
                store.close()

    def test_cashback_remains_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'unsupported cashback'):
            pump.curve(curve_account_with(mayhem=True, cashback=True))

    def test_non_native_quote_asset_remains_fail_closed(self):
        quote = pump.b58(bytes([19]) * 32)
        with self.assertRaisesRegex(ValueError, 'unsupported.*quote asset'):
            pump.curve(curve_account_with(mayhem=True, quote_mint=quote))


if __name__ == '__main__':
    unittest.main()
