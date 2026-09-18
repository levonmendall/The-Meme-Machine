"""Regression coverage for density-screened DLMM profitability acquisition."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine.dlmm_tape import MAX_TRANSACTIONS
from meme_machine.provider import Unavailable
from tests import dlmm_profitability_pilot as pilot
from tests import dlmm_strategy_high_activity as research


class _RPC:
    def __init__(self, rows=None, error=None):
        self.rows = rows if rows is not None else []
        self.error = error
        self.calls = 0
        self.http_requests = 0
        self.failures = 0
        self.retries = 0
        self.sleeps = []
        self.methods = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def call(self, method, params=None, priority=False, fresh=False):
        self.calls += 1
        self.http_requests += 1
        self.methods.append((method, params, priority, fresh))
        if self.error is not None:
            if str(self.error) == "provider_request_failed":
                self.failures += 1
            raise self.error
        return list(self.rows)


def _rows(count, start_slot=100):
    return [
        dict(
            signature=f"s{i}",
            slot=start_slot + i + 1,
            err=None,
            confirmationStatus="finalized",
        )
        for i in range(count)
    ]


class ProfitabilityDensityPreflight(unittest.TestCase):
    def test_over_capacity_is_explicit_and_never_reconstructs(self):
        rpc = _RPC(_rows(MAX_TRANSACTIONS + 1))
        adapter = SimpleNamespace(rpc=rpc)
        start = dict(pool="pool", slot=100)

        with patch.object(pilot.dense, "pressure_advance") as advance:
            phase, tape, terminal, effective_start = pilot._observe_phase(
                adapter, "pool", start, 12, allow_snapshot_reset=True
            )

        self.assertFalse(phase["verified"])
        self.assertEqual(
            phase["terminal_classification"], "over_verification_capacity"
        )
        self.assertEqual(
            phase["preflight"]["successful_post_start"], MAX_TRANSACTIONS + 1
        )
        self.assertIsNone(tape)
        self.assertIsNone(terminal)
        self.assertIs(effective_start, start)
        advance.assert_not_called()
        self.assertEqual([m[0] for m in rpc.methods], ["getSignaturesForAddress"])
        self.assertTrue(rpc.methods[0][3])

    def test_provider_failure_is_not_zero_opportunity(self):
        rpc = _RPC(error=Unavailable("provider_request_failed"))
        adapter = SimpleNamespace(rpc=rpc)
        start = dict(pool="pool", slot=100)

        with patch.object(pilot.dense, "pressure_advance") as advance:
            phase, _, _, _ = pilot._observe_phase(
                adapter, "pool", start, 12, allow_snapshot_reset=False
            )

        self.assertFalse(phase["verified"])
        self.assertEqual(phase["terminal_classification"], "provider_failure")
        self.assertEqual(
            phase["preflight"]["classification"], "provider_failure"
        )
        advance.assert_not_called()

    def test_passing_preflight_gates_verified_acquisition_and_keeps_window_total(self):
        rpc = _RPC(_rows(2))
        adapter = SimpleNamespace(rpc=rpc)
        start = dict(pool="pool", slot=100)
        terminal = dict(slot=110)
        tape = SimpleNamespace(events=[], lineage="lineage")

        with patch.object(
            pilot.dense,
            "pressure_advance",
            return_value=({"pool": terminal}, {"pool": tape}, []),
        ) as advance:
            phase, actual_tape, actual_terminal, _ = pilot._observe_phase(
                adapter, "pool", start, 12, allow_snapshot_reset=False
            )

        self.assertTrue(phase["verified"])
        self.assertEqual(phase["preflight"]["classification"], "certifiable")
        self.assertEqual(phase["terminal_classification"], "verified_zero_swap")
        self.assertIs(actual_tape, tape)
        self.assertIs(actual_terminal, terminal)
        args, kwargs = advance.call_args
        self.assertEqual(args[0], adapter)
        self.assertAlmostEqual(args[2], 12 - pilot.PREFLIGHT_SECONDS)
        self.assertFalse(kwargs["allow_snapshot_reset"])

    def test_error_classification_keeps_censoring_reasons_distinct(self):
        self.assertEqual(
            pilot._classify_reason("dlmm_transaction_bound"),
            "over_verification_capacity",
        )
        self.assertEqual(
            pilot._classify_reason("provider_request_failed"),
            "provider_failure",
        )
        self.assertEqual(
            pilot._classify_reason("provider_budget_exhausted"),
            "provider_budget_exhausted",
        )
        self.assertEqual(
            pilot._classify_reason("dlmm_signature_census_missing_start_boundary"),
            "verification_failure",
        )

    def test_zero_swap_warmup_skips_outcome_and_keeps_scanning(self):
        rpc = _RPC()
        adapter = SimpleNamespace(rpc=rpc)
        start = dict(pool="pool", slot=100)
        terminal = dict(slot=110)
        zero = SimpleNamespace(events=[], lineage="warm-lineage")
        phase = dict(
            verified=True,
            terminal_classification="verified_zero_swap",
            errors=[],
        )
        candidate = dict(address="pool", name="QUIET-SOL", rank=1, source="test")

        with patch.object(
            pilot,
            "_observe_phase",
            return_value=(phase, zero, terminal, start),
        ) as observe:
            (
                attempt,
                opportunity,
                results,
                selected,
                normalized,
                legacy,
            ) = pilot._attempt_candidate(
                adapter,
                candidate,
                start,
                12,
                60,
                "development",
                1,
            )

        self.assertEqual(observe.call_count, 1)
        self.assertFalse(attempt["completed_window"])
        self.assertEqual(
            attempt["terminal_classification"], "verified_zero_swap"
        )
        self.assertEqual(
            attempt["outcome_skipped"],
            "no_pre_entry_economic_case_without_verified_flow",
        )
        self.assertIsNone(opportunity)
        self.assertEqual(results, [])
        self.assertEqual(selected, [])
        self.assertEqual(normalized, [])
        self.assertEqual(legacy, [])

    def test_sixty_second_outcome_is_chained_from_five_verified_segments(self):
        rpc = _RPC()
        adapter = SimpleNamespace(rpc=rpc)
        start = dict(pool="pool", slot=100)
        phases = []
        tapes = []
        states = [start]
        for index in range(5):
            terminal = dict(pool="pool", slot=101 + index)
            states.append(terminal)
            phase = dict(
                verified=True,
                terminal_classification="certifiable",
                errors=[],
                swap_count=1,
            )
            tape = SimpleNamespace(events=[dict(i=index)], lineage=f"l{index}")
            phases.append((phase, tape, terminal, states[index]))
        calls = iter(phases)
        combined = SimpleNamespace(
            events=[dict(i=i) for i in range(5)],
            lineage="combined",
        )
        with patch.object(
            pilot,
            "_observe_phase",
            side_effect=lambda *args, **kwargs: next(calls),
        ) as observe, patch.object(
            pilot, "chain_verified_tapes", return_value=combined
        ) as chain:
            phase, tape, terminal = pilot._observe_horizon(
                adapter, "pool", start, total_seconds=60, segment_seconds=12
            )

        self.assertTrue(phase["verified"])
        self.assertEqual(phase["verified_holding_seconds"], 60)
        self.assertEqual(phase["segment_count"], 5)
        self.assertEqual(observe.call_count, 5)
        self.assertIs(tape, combined)
        self.assertEqual(terminal["slot"], 105)
        chain.assert_called_once()

    def test_non_sixty_second_horizon_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError, "holding_horizon_must_match_mechanical"
        ):
            pilot._observe_horizon(
                SimpleNamespace(rpc=_RPC()),
                "pool",
                dict(pool="pool", slot=100),
                total_seconds=12,
            )

    def test_fresh_supported_start_is_taken_at_attempt_time(self):
        snap = dict(pool="pool", available_time=123)
        adapter = SimpleNamespace(
            snapshot=lambda address, now, priority, fresh=False: snap
        )
        candidate = dict(
            address="pool",
            token_x=pilot.dlmm.WSOL,
            token_y="token",
        )
        state = dict(pool="pool", slot=222)
        with patch.object(pilot.dlmm, "validate", return_value=state) as validate, \
             patch.object(pilot.dlmm, "scout") as scout, \
             patch.object(pilot.time, "time", return_value=123):
            actual = pilot._fresh_supported_start(adapter, candidate)

        self.assertIs(actual, state)
        validate.assert_called_once_with(snap, 123, "real")
        scout.assert_called_once()

    def test_per_candidate_budget_exhaustion_does_not_stop_batch(self):
        class BudgetRPC:
            def __init__(self):
                self.limit = pilot.PER_POOL_RPC_LIMIT
                self.calls = 0
                self.http_requests = 0
                self.failures = 0
                self.retries = 0
                self.batch_fallbacks = 0
                self.batch_fallback_items = 0
                self.null_retries = 0
                self.cache_hits = 0
                self.failure_kinds = {}
                self.failure_methods = {}

        class Pacer:
            def telemetry(self):
                return dict(
                    minimum_interval_seconds=1.0,
                    paced_requests=0,
                    throttle_sleep_seconds=0.0,
                )

        rpcs = [BudgetRPC(), BudgetRPC(), BudgetRPC()]
        candidates = [
            dict(address="pool-1", name="ONE-SOL", rank=1, source="test"),
            dict(address="pool-2", name="TWO-SOL", rank=2, source="test"),
        ]
        starts = {
            "pool-1": dict(pool="pool-1", slot=100),
            "pool-2": dict(pool="pool-2", slot=200),
        }

        def attempt(adapter, candidate, start, *args, **kwargs):
            rpc = adapter.rpc
            if candidate["address"] == "pool-1":
                rpc.calls = rpc.http_requests = pilot.PER_POOL_RPC_LIMIT
                return (
                    dict(
                        terminal_classification="provider_budget_exhausted",
                        completed_window=False,
                        rpc=dict(
                            calls=pilot.PER_POOL_RPC_LIMIT,
                            http_requests=pilot.PER_POOL_RPC_LIMIT,
                            failures=0,
                            retries=0,
                        ),
                    ),
                    None,
                    [],
                    [],
                    [],
                    [],
                )
            rpc.calls = rpc.http_requests = 10
            opportunity = dict(
                pool="pool-2",
                features=dict(warmup_swaps=1),
                outcome_swaps=1,
                warmup_host_fee_swaps=0,
                outcome_host_fee_swaps=0,
            )
            return (
                dict(
                    terminal_classification="certifiable",
                    completed_window=True,
                    strategy_selected=False,
                    rpc=dict(
                        calls=10,
                        http_requests=10,
                        failures=0,
                        retries=0,
                    ),
                ),
                opportunity,
                [],
                [],
                [],
                [],
            )

        report_sink = SimpleNamespace(write_text=lambda _text: None)
        with patch.object(
            pilot.alchemy_provider, "AlchemyPacer", return_value=Pacer()
        ), patch.object(
            pilot.alchemy_provider, "new_rpc", side_effect=rpcs
        ) as new_rpc, patch.object(
            pilot.dlmm,
            "Adapter",
            side_effect=lambda rpc: SimpleNamespace(rpc=rpc),
        ), patch.object(
            pilot,
            "_discover_for_scan",
            return_value=(candidates, [], []),
        ), patch.object(
            pilot,
            "_fresh_supported_start",
            side_effect=lambda _adapter, candidate: starts[candidate["address"]],
        ), patch.object(
            pilot, "_attempt_candidate", side_effect=attempt
        ) as attempt_call, patch.object(
            pilot.research, "_summary", return_value=([], None)
        ), patch.object(
            pilot.research, "REPORT", report_sink
        ), patch.object(
            pilot.run, "historical_last_update_reference", return_value={}
        ):
            report = pilot.run_live(
                target_completed=1,
                max_attempted_pools=2,
                warmup_seconds=12,
                holding_seconds=60,
                study_phase="development",
            )

        self.assertEqual(new_rpc.call_count, 3)  # discovery + two candidates
        self.assertEqual(attempt_call.call_count, 2)
        self.assertEqual(report["completed_window_count"], 1)
        self.assertEqual(report["provider_budget_instance_count"], 2)
        self.assertEqual(report["per_candidate_budget_exhaustion_count"], 1)
        self.assertEqual(report["attempted_pool_count"], 2)
        self.assertGreater(report["rpc_calls"], pilot.PER_POOL_RPC_LIMIT)

    def test_hurdle_progress_tracks_best_candidate_gap(self):
        rows=[
            dict(target_distance_bps=100,width=2,actual_distance_bps=99.0,
                 features=dict(
                     projected_60s_range_fee_capture_lamports=5_000.0,
                     projected_60s_range_fee_surplus_lamports=-345_000.0)),
            dict(target_distance_bps=200,width=4,actual_distance_bps=198.0,
                 features=dict(
                     projected_60s_range_fee_capture_lamports=20_000.0,
                     projected_60s_range_fee_surplus_lamports=-330_000.0)),
        ]
        result=pilot._hurdle_progress(rows)
        self.assertEqual(result["best_target_distance_bps"],200)
        self.assertEqual(result["best_width"],4)
        self.assertEqual(result["best_projected_fee_capture_lamports"],20_000.0)
        self.assertEqual(result["hurdle_gap_lamports"],330_000.0)
        self.assertAlmostEqual(result["hurdle_gap_bps"],33.0)
        self.assertAlmostEqual(
            result["fee_hurdle_coverage_ratio"],20_000/350_000)

    def test_development_ledger_is_deduped_and_targets_thirty(self):
        prior=pilot._load_development_ledger()
        self.assertEqual(pilot.DEVELOPMENT_LEDGER_TARGET,30)
        self.assertEqual(len(prior),7)
        duplicate=dict(prior[0])
        new=dict(
            run_id=None,pool="new-pool",entry_slot=1,end_slot=2,
            selected=False,best_target_distance_bps=100,best_width=2,
            best_actual_distance_bps=99.0,
            best_projected_fee_capture_lamports=10_000.0,
            best_projected_surplus_lamports=-340_000.0,
            hurdle_gap_lamports=340_000.0,hurdle_gap_bps=34.0,
            fee_hurdle_coverage_ratio=10_000/350_000,
            fixed_cost_lamports=350_000.0,
        )
        merged=pilot._merge_development_observations(prior,[duplicate,new])
        self.assertEqual(len(merged),8)

    def test_width8_is_retained_as_legacy_comparator(self):
        self.assertEqual(research.SELECTED_STRATEGY, "sdk_bidask")
        self.assertEqual(research.SELECTED_WIDTH, 8)
        self.assertEqual(pilot.economics.HOLD_SECONDS, 60)
        self.assertEqual(
            pilot.economics.NORMALIZED_TARGET_BPS, (100, 200, 400, 800)
        )
        self.assertEqual(pilot.MAX_ATTEMPTED_POOLS, 24)
        self.assertEqual(pilot.TARGET_COMPLETED_WINDOWS, 6)
        self.assertEqual(pilot.MAX_ACTIVITY_PAGES, 4)
        self.assertEqual(pilot.ACTIVITY_PAGE_SIZE, 80)
        self.assertEqual(pilot.DISCOVERY_RPC_LIMIT, 120)
        self.assertEqual(pilot.PER_POOL_RPC_LIMIT, 240)


if __name__ == "__main__":
    unittest.main()
