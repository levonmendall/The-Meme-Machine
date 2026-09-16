import base64
import unittest

from meme_machine import pump
from tests.support import snapshot


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


class MayhemMode(unittest.TestCase):
    def test_sol_paired_mayhem_uses_same_reserve_quote_math(self):
        standard = pump.curve(curve_account_with(mayhem=False))
        mayhem = pump.curve(curve_account_with(mayhem=True))
        self.assertEqual(mayhem, standard)
        rates = (95, 30)
        self.assertEqual(pump.buy(mayhem, 10_000_000, rates), pump.buy(standard, 10_000_000, rates))
        tokens = pump.buy(mayhem, 10_000_000, rates)[0]
        self.assertEqual(pump.sell(mayhem, tokens, rates), pump.sell(standard, tokens, rates))

    def test_cashback_remains_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'unsupported cashback'):
            pump.curve(curve_account_with(mayhem=True, cashback=True))

    def test_non_native_quote_asset_remains_fail_closed(self):
        quote = pump.b58(bytes([19]) * 32)
        with self.assertRaisesRegex(ValueError, 'unsupported.*quote asset'):
            pump.curve(curve_account_with(mayhem=True, quote_mint=quote))


if __name__ == '__main__':
    unittest.main()
