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
            attempt, opportunity, results, selected = pilot._attempt_candidate(
                adapter, candidate, start, 12, 1
            )

        self.assertEqual(observe.call_count, 1)
        self.assertFalse(attempt["completed_window"])
        self.assertEqual(
            attempt["terminal_classification"], "verified_zero_swap"
        )
        self.assertEqual(
            attempt["outcome_skipped"],
            "fixed_selector_requires_nonzero_verified_warmup_activity",
        )
        self.assertIsNone(opportunity)
        self.assertEqual(results, [])
        self.assertEqual(selected, [])

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

    def test_fixed_strategy_selection_is_unchanged(self):
        self.assertEqual(research.SELECTED_STRATEGY, "sdk_bidask")
        self.assertEqual(research.SELECTED_WIDTH, 8)
        self.assertEqual(pilot.MAX_ATTEMPTED_POOLS, 12)
        self.assertEqual(pilot.TARGET_COMPLETED_WINDOWS, 6)
        self.assertEqual(pilot.MAX_ACTIVITY_PAGES, 4)
        self.assertEqual(pilot.ACTIVITY_PAGE_SIZE, 80)


if __name__ == "__main__":
    unittest.main()
