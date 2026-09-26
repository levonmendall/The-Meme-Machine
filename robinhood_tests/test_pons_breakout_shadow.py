"""Deterministic contracts for Pons post-graduation shadow outcome research."""
import unittest

from robinhood_research.pons_breakout_sample import (
    _after_cost_return_bps, _zero_for_one,
)
from robinhood_research.pons_selective_continuation import ZERO


class _Key:
    def __init__(self,c0,c1):
        self.currency0=c0
        self.currency1=c1


class PonsBreakoutShadowTests(unittest.TestCase):
    def test_native_quote_directions_are_inverse(self):
        token="0x1111111111111111111111111111111111111111"
        for key in (_Key(ZERO,token),_Key(token,ZERO)):
            self.assertNotEqual(
                _zero_for_one(key,"buy"),
                _zero_for_one(key,"sell"),
            )

    def test_buy_direction_uses_native_quote_as_input(self):
        token="0x1111111111111111111111111111111111111111"
        self.assertTrue(_zero_for_one(_Key(ZERO,token),"buy"))
        self.assertFalse(_zero_for_one(_Key(token,ZERO),"buy"))

    def test_after_cost_return_includes_both_gas_legs(self):
        entry=dict(amount_in=100_000,gas_quote=1_000)
        exit_quote=dict(amount_out=111_000,gas_quote=1_000)
        self.assertEqual(
            _after_cost_return_bps(entry,exit_quote),
            (110_000-101_000)*10_000//101_000,
        )


if __name__=="__main__":
    unittest.main()
