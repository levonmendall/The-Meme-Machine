import unittest
from types import SimpleNamespace

from meme_machine.continuation_economics import (
    choose_economic_shadow,
    continuation_economic_features,
    economic_priority_key,
)


class FakeTape:
    def __init__(self, rows):
        self.rows = rows

    def window(self, mint, now):
        return [row for row in self.rows if row["mint"] == mint and row["market_time"] <= now]


def trade(mint, wallet, when, amount, buy=True, tokens=1_000_000):
    return dict(
        mint=mint,
        wallet=wallet,
        market_time=when,
        slot=when,
        index=0,
        amount=amount,
        tokens=tokens,
        buy=buy,
    )


class ContinuationEconomicShadowTests(unittest.TestCase):
    def test_features_use_only_point_in_time_non_anchor_flow(self):
        candidate = dict(
            mint="M1",
            nomination=dict(id="n1", wallet="anchor", market_time=100),
        )
        tape = FakeTape([
            trade("M1", "anchor", 98, 9_000_000_000, True),
            trade("M1", "buyer1", 92, 1_000_000_000, True),
            trade("M1", "buyer2", 96, 2_000_000_000, True),
            trade("M1", "seller", 97, 500_000_000, False),
            trade("M1", "future", 101, 99_000_000_000, True),
        ])
        features = continuation_economic_features(candidate, tape, 100)
        self.assertEqual(features["window_10s"]["gross_buy_lamports"], 3_000_000_000)
        self.assertEqual(features["window_10s"]["gross_sell_lamports"], 500_000_000)
        self.assertEqual(features["window_10s"]["unique_buyers"], 2)
        self.assertFalse(features["future_outcomes_used"])
        self.assertFalse(features["order_authority"])

    def test_shadow_prefers_stronger_recent_net_flow_without_authority(self):
        a = dict(mint="A", nomination=dict(id="a", wallet="anchor-a", market_time=100))
        b = dict(mint="B", nomination=dict(id="b", wallet="anchor-b", market_time=100))
        tape = FakeTape([
            trade("A", "a1", 96, 1_000_000_000, True),
            trade("A", "a2", 97, 1_000_000_000, True),
            trade("B", "b1", 96, 3_000_000_000, True),
            trade("B", "b2", 97, 3_000_000_000, True),
            trade("B", "b3", 98, 1_000_000_000, False),
        ])
        metric = SimpleNamespace(possible=True)
        chosen = choose_economic_shadow([(a, metric), (b, metric)], tape, 100)
        self.assertEqual(chosen[0]["mint"], "B")
        self.assertFalse(chosen[2]["order_authority"])

    def test_priority_key_is_deterministic(self):
        candidate = dict(mint="M", nomination=dict(id="n", wallet="anchor", market_time=100))
        tape = FakeTape([trade("M", "b1", 99, 1_000_000_000, True)])
        features = continuation_economic_features(candidate, tape, 100)
        self.assertEqual(economic_priority_key(features), economic_priority_key(features))


if __name__ == "__main__":
    unittest.main()
