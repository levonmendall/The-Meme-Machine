import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from robinhood_research.identity import load
from robinhood_research import ramses_universe


class _LogRpc:
    def __init__(self):
        self.calls = []

    def batch(self, calls, scope="connectivity"):
        self.calls.extend((scope, c) for c in calls)
        return [[] for _ in calls]


class _InventoryRpc:
    def __init__(self, addresses):
        self.addresses=list(addresses)
        self.count_calls=0
        self.indices_by_scope={}

    @staticmethod
    def _word(value):
        return "0x"+f"{int(value):064x}"

    @staticmethod
    def _address_word(address):
        return "0x"+f"{int(address,16):064x}"

    def call(self,method,params,scope="connectivity"):
        if method!="eth_call" or scope!="universe_inventory":
            raise AssertionError((method,params,scope))
        self.count_calls+=1
        return self._word(len(self.addresses))

    def batch(self,calls,scope="connectivity"):
        indices=[]
        out=[]
        for method,params in calls:
            if method!="eth_call":
                raise AssertionError((method,params,scope))
            data=params[0]["data"]
            index=int(data[-64:],16)
            indices.append(index)
            out.append(self._address_word(self.addresses[index]))
        self.indices_by_scope.setdefault(scope,[]).append(indices)
        return out


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
    def setUp(self):
        with ramses_universe._FACTORY_INVENTORY_LOCK:
            ramses_universe._FACTORY_INVENTORY_CACHE.clear()

    def test_all_pool_scanner_is_bounded_and_strategy_only(self):
        self.assertEqual(ramses_universe.LOOKBACK_BLOCKS, 300)
        self.assertEqual(ramses_universe.MAX_RECENT_ACTIVE_POOLS, 32)
        self.assertEqual(ramses_universe.WATCH_COHORT_SIZE, 8)
        self.assertEqual(ramses_universe.PAPER_ACTIVE_LIQUIDITY_BPS, 50)
        self.assertLess(
            ramses_universe.PAPER_ACTIVE_LIQUIDITY_BPS,
            1000,
        )

    def test_factory_inventory_cache_reuses_verified_prefix_and_fetches_only_append(self):
        factory="0x"+"aa"*20
        rpc=_InventoryRpc([
            "0x"+"11"*20,
            "0x"+"22"*20,
            "0x"+"33"*20,
        ])
        first=ramses_universe._enumerate_factory(rpc,factory,100)
        self.assertEqual(len(first),3)
        self.assertEqual(
            rpc.indices_by_scope["universe_inventory"],
            [[0,1,2]],
        )
        self.assertFalse(rpc._roi_factory_inventory_cache_hit)
        self.assertEqual(rpc._roi_factory_inventory_fetched,3)

        second=ramses_universe._enumerate_factory(rpc,factory,101)
        self.assertEqual(second,first)
        self.assertEqual(
            rpc.indices_by_scope["universe_inventory_verify"][-1],
            [0,2],
        )
        self.assertEqual(
            rpc.indices_by_scope["universe_inventory"],
            [[0,1,2]],
        )
        self.assertTrue(rpc._roi_factory_inventory_cache_hit)
        self.assertEqual(rpc._roi_factory_inventory_reused,3)
        self.assertEqual(rpc._roi_factory_inventory_fetched,0)

        rpc.addresses.append("0x"+"44"*20)
        third=ramses_universe._enumerate_factory(rpc,factory,102)
        self.assertEqual(len(third),4)
        self.assertEqual(
            rpc.indices_by_scope["universe_inventory"][-1],
            [3],
        )
        self.assertEqual(rpc._roi_factory_inventory_reused,3)
        self.assertEqual(rpc._roi_factory_inventory_fetched,1)
        self.assertEqual(rpc.count_calls,3)

    def test_factory_inventory_cache_fails_closed_on_registry_change(self):
        factory="0x"+"aa"*20
        rpc=_InventoryRpc([
            "0x"+"11"*20,
            "0x"+"22"*20,
            "0x"+"33"*20,
        ])
        ramses_universe._enumerate_factory(rpc,factory,100)
        rpc.addresses[0]="0x"+"99"*20
        with self.assertRaisesRegex(
            ramses_universe.BoundaryError,
            "ramses_universe_factory_inventory_changed",
        ):
            ramses_universe._enumerate_factory(rpc,factory,101)

    def test_factory_inventory_cache_fails_closed_on_count_or_block_regression(self):
        factory="0x"+"aa"*20
        rpc=_InventoryRpc([
            "0x"+"11"*20,
            "0x"+"22"*20,
            "0x"+"33"*20,
        ])
        ramses_universe._enumerate_factory(rpc,factory,100)
        with self.assertRaisesRegex(
            ramses_universe.BoundaryError,
            "ramses_universe_inventory_block_regression",
        ):
            ramses_universe._enumerate_factory(rpc,factory,99)

        rpc.addresses.pop()
        with self.assertRaisesRegex(
            ramses_universe.BoundaryError,
            "ramses_universe_factory_count_regression",
        ):
            ramses_universe._enumerate_factory(rpc,factory,101)

    def test_durable_all_pool_cache_reuses_verified_prefix_after_process_reset(self):
        factory="0x"+"aa"*20
        runtime="runtime-sha"
        addresses=["0x"+"11"*20,"0x"+"22"*20,"0x"+"33"*20]
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"inventory.json"
            with patch.object(ramses_universe,"FACTORY_CACHE",cache):
                first_rpc=_InventoryRpc(addresses)
                first=ramses_universe._enumerate_factory(
                    first_rpc,factory,100,factory_runtime_sha256=runtime
                )
                self.assertTrue(cache.exists())
                with ramses_universe._FACTORY_INVENTORY_LOCK:
                    ramses_universe._FACTORY_INVENTORY_CACHE.clear()
                second_rpc=_InventoryRpc(addresses)
                second=ramses_universe._enumerate_factory(
                    second_rpc,factory,101,factory_runtime_sha256=runtime
                )
        self.assertEqual(second,first)
        self.assertTrue(second_rpc._roi_factory_inventory_durable_hit)
        self.assertEqual(second_rpc._roi_factory_inventory_reused,3)
        self.assertNotIn("universe_inventory",second_rpc.indices_by_scope)
        self.assertNotIn("universe_inventory_verify",second_rpc.indices_by_scope)
        self.assertEqual(second_rpc.count_calls,1)

    def test_runtime_bound_cache_fetches_only_new_append_without_sentinels(self):
        factory="0x"+"aa"*20
        runtime="runtime-sha"
        addresses=["0x"+"11"*20,"0x"+"22"*20,"0x"+"33"*20]
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"inventory.json"
            with patch.object(ramses_universe,"FACTORY_CACHE",cache):
                first_rpc=_InventoryRpc(addresses)
                first=ramses_universe._enumerate_factory(
                    first_rpc,factory,100,factory_runtime_sha256=runtime
                )
                self.assertEqual(first,addresses)
                with ramses_universe._FACTORY_INVENTORY_LOCK:
                    ramses_universe._FACTORY_INVENTORY_CACHE.clear()
                grown=addresses+["0x"+"44"*20]
                second_rpc=_InventoryRpc(grown)
                second=ramses_universe._enumerate_factory(
                    second_rpc,factory,101,factory_runtime_sha256=runtime
                )
        self.assertEqual(second,grown)
        self.assertEqual(second_rpc.count_calls,1)
        self.assertNotIn("universe_inventory_verify",second_rpc.indices_by_scope)
        self.assertEqual(second_rpc.indices_by_scope["universe_inventory"],[[3]])
        self.assertEqual(second_rpc._roi_factory_inventory_reused,3)
        self.assertEqual(second_rpc._roi_factory_inventory_fetched,1)

    def test_tracked_seed_is_read_only_fallback_and_runtime_cache_is_mutable(self):
        factory="0x"+"aa"*20
        runtime="runtime-sha"
        addresses=["0x"+"11"*20,"0x"+"22"*20]
        seed=dict(
            kind="ramses_all_pool_inventory_cache_v1",chain_id=4663,
            factory=factory,factory_runtime_sha256=runtime,count=2,
            asof_block=99,addresses=addresses,
            addresses_sha256=ramses_universe._inventory_digest(addresses),
        )
        with tempfile.TemporaryDirectory() as td:
            seed_path=Path(td)/"seed.json"
            runtime_path=Path(td)/"runtime.json"
            seed_path.write_text(json.dumps(seed))
            with patch.object(ramses_universe,"FACTORY_SEED",seed_path), patch.object(
                ramses_universe,"FACTORY_CACHE",runtime_path
            ):
                rpc=_InventoryRpc(addresses)
                got=ramses_universe._enumerate_factory(
                    rpc,factory,100,factory_runtime_sha256=runtime
                )
                persisted=json.loads(runtime_path.read_text())
        self.assertEqual(got,addresses)
        self.assertTrue(rpc._roi_factory_inventory_seed_hit)
        self.assertEqual(json.loads(seed_path.read_text()),seed)
        self.assertEqual(persisted["addresses"],addresses)
        self.assertEqual(persisted["asof_block"],100)
        self.assertEqual(rpc.count_calls,1)
        self.assertNotIn("universe_inventory_verify",rpc.indices_by_scope)

    def test_invalid_durable_cache_is_not_trusted_and_is_reauthenticated(self):
        factory="0x"+"aa"*20
        runtime="runtime-sha"
        addresses=["0x"+"11"*20,"0x"+"22"*20]
        bad=dict(
            kind="ramses_all_pool_inventory_cache_v1",chain_id=4663,
            factory=factory,factory_runtime_sha256=runtime,count=2,
            asof_block=99,addresses=addresses,addresses_sha256="bad",
        )
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"inventory.json"
            cache.write_text(json.dumps(bad))
            with patch.object(ramses_universe,"FACTORY_CACHE",cache):
                rpc=_InventoryRpc(addresses)
                got=ramses_universe._enumerate_factory(
                    rpc,factory,100,factory_runtime_sha256=runtime
                )
        self.assertEqual(got,addresses)
        self.assertFalse(rpc._roi_factory_inventory_durable_hit)
        self.assertEqual(rpc.indices_by_scope["universe_inventory"],[[0,1]])

    def test_factory_minus_32000_batch_isolated_to_single_members(self):
        factory="0x"+"aa"*20
        addresses=["0x"+"11"*20,"0x"+"22"*20,"0x"+"33"*20]
        class Rpc(_InventoryRpc):
            def __init__(self,rows):
                super().__init__(rows);self.failed=False;self.isolated=[]
            def batch(self,calls,scope="connectivity"):
                if scope=="universe_inventory" and not self.failed:
                    self.failed=True
                    raise ramses_universe.BoundaryError("provider_rpc_-32000")
                return super().batch(calls,scope=scope)
            def call(self,method,params,scope="connectivity"):
                if scope=="universe_inventory_isolated":
                    index=int(params[0]["data"][-64:],16)
                    self.isolated.append(index)
                    return self._address_word(self.addresses[index])
                return super().call(method,params,scope=scope)
        rpc=Rpc(addresses)
        with tempfile.TemporaryDirectory() as td, patch.object(
            ramses_universe,"FACTORY_CACHE",Path(td)/"inventory.json"
        ):
            got=ramses_universe._enumerate_factory(
                rpc,factory,100,factory_runtime_sha256="runtime-sha"
            )
        self.assertEqual(got,addresses)
        self.assertEqual(rpc.isolated,[0,1,2])
        self.assertEqual(rpc._roi_factory_batch_recoveries,1)

    def test_persistent_factory_member_error_names_exact_index(self):
        factory="0x"+"aa"*20
        addresses=["0x"+"11"*20,"0x"+"22"*20]
        class Rpc(_InventoryRpc):
            def batch(self,calls,scope="connectivity"):
                if scope=="universe_inventory":
                    raise ramses_universe.BoundaryError("provider_rpc_-32000")
                return super().batch(calls,scope=scope)
            def call(self,method,params,scope="connectivity"):
                if scope=="universe_inventory_isolated":
                    index=int(params[0]["data"][-64:],16)
                    if index==1:
                        raise ramses_universe.BoundaryError("provider_rpc_-32000")
                    return self._address_word(self.addresses[index])
                return super().call(method,params,scope=scope)
        with tempfile.TemporaryDirectory() as td, patch.object(
            ramses_universe,"FACTORY_CACHE",Path(td)/"inventory.json"
        ):
            with self.assertRaisesRegex(
                ramses_universe.BoundaryError,
                "ramses_universe_factory_member_1:provider_rpc_-32000",
            ):
                ramses_universe._enumerate_factory(
                    Rpc(addresses),factory,100,
                    factory_runtime_sha256="runtime-sha",
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

    def test_compact_screen_strips_heavy_selector_state_but_keeps_identity(self):
        screen = dict(
            rows=[dict(
                pool="0x" + "11" * 20,
                prestate=dict(active=7, step=5, bins={7: dict(reserves=[1, 2], supply=3)}),
                prehistory=[dict(block=1), dict(block=2)],
                prestate_block=123,
                prestate_block_hash="0x" + "ab" * 32,
                prestate_timestamp=456,
                decision=dict(qualified=False),
            )],
        )
        compact = ramses_universe.compact_screen(screen)
        row = compact["rows"][0]
        self.assertNotIn("prestate", row)
        self.assertNotIn("prehistory", row)
        self.assertTrue(row["prestate_retained_in_memory"])
        self.assertTrue(row["prehistory_retained_in_memory"])
        self.assertEqual(row["prehistory_swap_count"], 2)
        self.assertEqual(row["prestate_block"], 123)
        self.assertEqual(row["prestate_block_hash"], "0x" + "ab" * 32)
        self.assertFalse(compact["heavy_selector_state_in_artifact"])


if __name__ == "__main__":
    unittest.main()
