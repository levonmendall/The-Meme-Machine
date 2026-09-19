import unittest

from robinhood_research.identity import load
from robinhood_research import ramses_universe


class _LogRpc:
    def __init__(self):
        self.calls = []

    def batch(self, calls, scope="connectivity"):
        self.calls.extend((scope, c) for c in calls)
        return [[] for _ in calls]


class _StateRpc:
    def __init__(self, code, active):
        self.code = code
        self.active = active
        self.batch_count = 0

    @staticmethod
    def _words(values):
        return "0x" + "".join(f"{v:064x}" for v in values)

    def batch(self, calls, scope="connectivity"):
        self.batch_count += 1
        if self.batch_count == 1:
            return [
                "0x" + f"{1:064x}",
                self.code,
                "0x" + f"{0:064x}",
                "0x" + f"{self.active:064x}",
                self._words([10**18, 2 * 10**18]),
                self._words([0, 0]),
                self._words([40000, 30, 600, 5000, 40000, 500, 350000]),
                self._words([0, 0, self.active, 1000]),
            ]
        out = []
        for i in range(7):
            out.extend([
                self._words([10**18, 10**18]),
                "0x" + f"{10**18:064x}",
            ])
        return out


class RamsesAllPoolUniverseTests(unittest.TestCase):
    def test_all_pool_scanner_is_bounded_and_strategy_only(self):
        self.assertEqual(ramses_universe.LOOKBACK_BLOCKS, 300)
        self.assertEqual(ramses_universe.MAX_RECENT_ACTIVE_POOLS, 32)
        self.assertEqual(ramses_universe.WATCH_COHORT_SIZE, 8)
        self.assertEqual(ramses_universe.PAPER_ACTIVE_LIQUIDITY_BPS, 100)
        self.assertLess(
            ramses_universe.PAPER_ACTIVE_LIQUIDITY_BPS,
            1000,
        )

    def test_log_queries_cover_all_addresses_in_bounded_block_chunks(self):
        rpc = _LogRpc()
        addresses = ["0x" + "11" * 20, "0x" + "22" * 20]
        got = ramses_universe._batched_logs(rpc, 100, 125, addresses)
        self.assertEqual(got, [])
        self.assertEqual(len(rpc.calls), 3)
        for scope, call in rpc.calls:
            self.assertEqual(scope, "universe_logs")
            self.assertEqual(call[0], "eth_getLogs")
            query = call[1][0]
            self.assertEqual(query["address"], addresses)
            self.assertLessEqual(
                int(query["toBlock"], 16) - int(query["fromBlock"], 16) + 1,
                10,
            )

    def test_prestate_accepts_non_native_authenticated_pool(self):
        impl = load("ramses_pool_implementation")["address"].lower()
        token_x = "0x" + "31" * 20
        token_y = "0x" + "42" * 20
        step = 25
        prefix = bytes.fromhex(
            "363d3d373d3d3d3d61002c806035363936013d73"
            + impl[2:]
            + "5af43d3d93803e603357fd5bf3"
        )
        code = "0x" + (
            prefix
            + bytes.fromhex(token_x[2:])
            + bytes.fromhex(token_y[2:])
            + step.to_bytes(2, "big")
            + b"\x00\x2c"
        ).hex()
        active = 1 << 23
        rpc = _StateRpc(code, active)
        auth, state = ramses_universe._prestate(
            rpc,
            load("ramses_factory")["address"],
            "0x" + "55" * 20,
            123,
        )
        self.assertEqual(auth["token_x"], token_x)
        self.assertEqual(auth["token_y"], token_y)
        self.assertEqual(auth["bin_step"], step)
        self.assertEqual(state["active"], active)
        self.assertEqual(len(state["bins"]), 7)

    def test_watch_ranking_prioritizes_turnover_then_fee_then_chop(self):
        base = dict(
            pool="0x" + "11" * 20,
            latest_swap_block=10,
            features=dict(
                turnover_percentile_bps=9000,
                fee_percentile_bps=7000,
                chop_ratio_milli=3000,
                volume_acceleration_milli=2000,
                flow_imbalance_bps=3000,
            ),
        )
        fee_richer = dict(
            pool="0x" + "22" * 20,
            latest_swap_block=11,
            features=dict(
                turnover_percentile_bps=9000,
                fee_percentile_bps=8000,
                chop_ratio_milli=3000,
                volume_acceleration_milli=2000,
                flow_imbalance_bps=3000,
            ),
        )
        turnover_richer = dict(
            pool="0x" + "33" * 20,
            latest_swap_block=9,
            features=dict(
                turnover_percentile_bps=10000,
                fee_percentile_bps=6000,
                chop_ratio_milli=3000,
                volume_acceleration_milli=2000,
                flow_imbalance_bps=3000,
            ),
        )
        ranked = sorted(
            [base, fee_richer, turnover_richer],
            key=ramses_universe._selection_key,
            reverse=True,
        )
        self.assertEqual(
            [r["pool"] for r in ranked],
            [turnover_richer["pool"], fee_richer["pool"], base["pool"]],
        )


if __name__ == "__main__":
    unittest.main()
