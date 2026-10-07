import unittest
from unittest.mock import patch

from robinhood_research import ramses_costs


def _words(*values):
    return "0x" + "".join(f"{int(v):064x}" for v in values)


class _CostRpc:
    def __init__(self, gas_by_tx=None, gas_price=10, quote_out=0):
        self.gas_by_tx = gas_by_tx or {}
        self.gas_price = gas_price
        self.quote_out = quote_out
        self.receipt_calls = 0
        self.calls = []

    def receipts(self, identities, scope="connectivity"):
        self.receipt_calls += 1
        out = []
        for tx, block_hash in identities:
            out.append(dict(
                transactionHash=tx,
                blockHash=block_hash,
                gasUsed=hex(self.gas_by_tx[tx]),
                status="0x1",
                logs=[],
            ))
        return out

    def call(self, method, params, scope="connectivity"):
        self.calls.append((method, params, scope))
        if method == "eth_gasPrice":
            return hex(self.gas_price)
        if method == "eth_call":
            return _words(0, self.quote_out, 7)
        raise AssertionError((method, params, scope))


class RamsesAutomaticCostTests(unittest.TestCase):
    def test_receipts_build_complete_observed_native_cycle(self):
        rpc = _CostRpc(
            gas_by_tx={"a":100, "b":200, "c":300},
            gas_price=10,
        )
        events = [
            dict(category="add_liquidity", transaction_hash="a", block_hash="ha"),
            dict(category="remove_liquidity", transaction_hash="b", block_hash="hb"),
            dict(category="unwind", transaction_hash="c", block_hash="hc"),
        ]
        state = {}
        ramses_costs.observe_receipt_gas(rpc, events, state)
        native, meta = ramses_costs.current_native_cycle(rpc, state)
        self.assertEqual(
            native,
            dict(
                add_liquidity=1000,
                remove_liquidity=2000,
                unwind=3000,
                entry_overhead=3000,
            ),
        )
        self.assertEqual(meta["proxy_categories"], [])
        self.assertEqual(
            meta["sample_counts"],
            dict(add_liquidity=1, remove_liquidity=1, unwind=1),
        )
        self.assertEqual(meta["native_cycle_cost_raw"], 9000)

    def test_missing_operations_use_two_x_worst_observed_proxy(self):
        rpc = _CostRpc(gas_by_tx={"s":300}, gas_price=2)
        state = {}
        ramses_costs.observe_receipt_gas(
            rpc,
            [dict(category="unwind", transaction_hash="s", block_hash="hs")],
            state,
        )
        native, meta = ramses_costs.current_native_cycle(rpc, state)
        self.assertEqual(native["unwind"], 600)
        self.assertEqual(native["add_liquidity"], 1200)
        self.assertEqual(native["remove_liquidity"], 1200)
        self.assertEqual(native["entry_overhead"], 600)
        self.assertEqual(
            set(meta["proxy_categories"]),
            {"add_liquidity", "remove_liquidity"},
        )

    def test_candidate_wnative_pool_converts_total_cost_executably(self):
        wnative = "0x" + "11"*20
        quote = "0x" + "22"*20
        pool = "0x" + "33"*20
        native = dict(
            add_liquidity=100,
            remove_liquidity=200,
            unwind=300,
            entry_overhead=400,
        )
        rpc = _CostRpc(quote_out=2500)
        row = dict(pool=pool, token_x=wnative, token_y=quote)
        with patch.object(ramses_costs, "_wnative", return_value=wnative):
            costs, meta = ramses_costs.quote_native_cycle(
                rpc,
                "0x"+"44"*20,
                row,
                123,
                native,
                {},
            )
        self.assertEqual(sum(costs.values()), 2500)
        self.assertTrue(meta["conversion_is_executable_get_swap_out"])
        self.assertEqual(
            meta["conversion"]["route_kind"],
            "candidate_wnative_quote_pool",
        )
        call = next(x for x in rpc.calls if x[0] == "eth_call")
        self.assertEqual(call[2], "universe_cost_conversion")

    def test_factory_pair_array_decoder_is_strict(self):
        pair = int("0x" + "ab"*20, 16)
        raw = _words(32, 1, 25, pair, 1, 0)
        got = ramses_costs._decode_pairs(raw)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["bin_step"], 25)
        self.assertEqual(got[0]["pool"], "0x" + "ab"*20)
        self.assertTrue(got[0]["created_by_owner"])
        self.assertFalse(got[0]["ignored_for_routing"])


if __name__ == "__main__":
    unittest.main()
