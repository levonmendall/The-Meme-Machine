import struct
import unittest

from meme_machine import pump
from meme_machine.pump_alpha_runtime import (
    PumpAlphaPaperBook,
    PumpAlphaProspectiveRuntime,
    curve_points_from_snapshot,
    curve_progress_bps,
    decode_global_curve_params,
    graduation_quote_target,
)
from tests.support import MINT, account, event, snapshot
from tests.test_postgrad import (
    CREATOR as POST_CREATOR,
    MINT as POST_MINT,
    complete_pump_snapshot,
    pumpswap_snapshot,
)


class PumpAlphaRuntimeTests(unittest.TestCase):
    def test_global_decoder_and_curve_progress_are_protocol_state_driven(self):
        raw = bytearray(113)
        raw[:8] = pump.discriminator("Global")
        raw[8] = 1
        struct.pack_into(
            "<QQQQQ", raw, 73,
            1_073_000_000_000_000,
            30_000_000_000,
            793_100_000_000_000,
            1_000_000_000_000_000,
            125,
        )
        params = decode_global_curve_params(account(bytes(raw), pump.PROGRAM))
        self.assertEqual(params["initial_real_token_reserves"], 793_100_000_000_000)
        self.assertEqual(curve_progress_bps(793_100_000_000_000, 793_100_000_000_000), 0)
        self.assertEqual(curve_progress_bps(0, 793_100_000_000_000), 10_000)

    def test_curve_trajectory_reconstructs_from_current_reserve_and_finalized_trades(self):
        snap = snapshot(now=100)
        params = {"initial_real_token_reserves": 560_000_000_000_000}
        rows = [
            event(now=80, wallet=pump.b58(bytes([21])*32), id="e1"),
            event(now=90, wallet=pump.b58(bytes([22])*32), id="e2"),
            event(now=100, wallet=pump.b58(bytes([23])*32), id="e3"),
        ]
        points = curve_points_from_snapshot(snap, rows, params, 100)
        progress = [p["progress_bps"] for p in points]
        self.assertEqual([p["market_time"] for p in points], [80, 90, 100])
        self.assertEqual(progress, sorted(progress))
        self.assertGreater(progress[-1], progress[0])
        self.assertGreater(graduation_quote_target(snap), 0)

    def test_isolated_pump_paper_entry_delayed_fill_exit_and_restart_state(self):
        book = PumpAlphaPaperBook(100_000_000_000)
        decision = {
            "strategy_id": "pump-alpha-v1",
            "policy_hash": "x",
            "entry_mode": "late_curve_acceleration",
            "eligible": True,
            "score_bps": 8000,
            "features": {"current_price": __import__("fractions").Fraction(1, 3)},
        }
        oid = book.reserve_pump(decision, snapshot(now=100, slot=100), 100)
        self.assertTrue(str(oid).startswith("pump-alpha-v1:curve:"))
        self.assertEqual(book.fill_pump(oid, snapshot(now=101, slot=101), 101), "waiting")
        self.assertEqual(book.fill_pump(oid, snapshot(now=102, slot=102), 102), "settled")
        self.assertIn(MINT, book.state["positions"])

        frozen = book.snapshot_state()
        restarted = PumpAlphaPaperBook(100_000_000_000, state=frozen)
        self.assertTrue(restarted.reconcile())

        exit_signal = {"exit": True, "reasons": ["demand_deceleration"]}
        self.assertEqual(
            restarted.monitor_pump(
                MINT, snapshot(now=107, sol=65_000_000_000, slot=107), 107, exit_signal
            ),
            "exit_intended",
        )
        self.assertEqual(
            restarted.monitor_pump(
                MINT, snapshot(now=110, sol=65_000_000_000, slot=110), 110,
                {"exit": False, "reasons": []},
            ),
            "settled",
        )
        self.assertNotIn(MINT, restarted.state["positions"])
        self.assertEqual(restarted.state["reserved"], 0)
        self.assertEqual(restarted.state["rent"], 0)
        self.assertTrue(restarted.reconcile())

    def test_postgrad_entry_has_separate_delayed_paper_path(self):
        book = PumpAlphaPaperBook(100_000_000_000)
        decision = {
            "strategy_id": "pump-alpha-v1",
            "entry_mode": "postgrad_continuation",
            "eligible": True,
            "score_bps": 7000,
        }
        oid = book.reserve_postgrad(decision, pumpswap_snapshot(now=100, slot=100), 100)
        self.assertEqual(
            book.fill_postgrad(oid, pumpswap_snapshot(now=102, slot=102), 102),
            "settled",
        )
        self.assertEqual(book.state["positions"][POST_MINT]["surface"], "pumpswap")
        self.assertEqual(
            book.monitor_postgrad(
                POST_MINT, pumpswap_snapshot(now=107, slot=107, quote=70_000_000_000),
                107, {"exit": True, "reasons": ["trailing_drawdown"]},
            ),
            "exit_intended",
        )
        self.assertEqual(
            book.monitor_postgrad(
                POST_MINT, pumpswap_snapshot(now=110, slot=110, quote=70_000_000_000),
                110, {"exit": False, "reasons": []},
            ),
            "settled",
        )
        self.assertTrue(book.reconcile())

    def test_curve_position_can_cross_only_authenticated_canonical_graduation(self):
        book = PumpAlphaPaperBook(100_000_000_000)
        decision = {
            "strategy_id": "pump-alpha-v1",
            "entry_mode": "late_curve_acceleration",
            "eligible": True,
            "score_bps": 8000,
        }
        entry = snapshot(now=100, slot=100, mint=POST_MINT, creator=POST_CREATOR)
        fill = snapshot(now=102, slot=102, mint=POST_MINT, creator=POST_CREATOR)
        oid = book.reserve_pump(decision, entry, 100)
        self.assertEqual(book.fill_pump(oid, fill, 102), "settled")
        completed = complete_pump_snapshot(now=105)
        post = pumpswap_snapshot(now=108, slot=108)
        carry = {
            "eligible": True,
            "entry_mode": "postgrad_continuation",
            "graduated_at": 105,
        }
        self.assertEqual(
            book.handoff_to_postgrad(POST_MINT, completed, post, carry, 108),
            "carried",
        )
        p = book.state["positions"][POST_MINT]
        self.assertEqual(p["surface"], "pumpswap")
        self.assertEqual(p["graduation_source_slot"], 105)

    def test_failed_postgrad_confirmation_schedules_exit_not_hold(self):
        book = PumpAlphaPaperBook(100_000_000_000)
        decision = {
            "strategy_id": "pump-alpha-v1",
            "entry_mode": "late_curve_acceleration",
            "eligible": True,
        }
        entry = snapshot(now=100, slot=100, mint=POST_MINT, creator=POST_CREATOR)
        fill = snapshot(now=102, slot=102, mint=POST_MINT, creator=POST_CREATOR)
        oid = book.reserve_pump(decision, entry, 100)
        self.assertEqual(book.fill_pump(oid, fill, 102), "settled")
        completed = complete_pump_snapshot(now=105)
        post = pumpswap_snapshot(now=108, slot=108)
        failed = {
            "eligible": False,
            "entry_mode": "postgrad_continuation",
            "graduated_at": 105,
        }
        self.assertEqual(
            book.handoff_to_postgrad(POST_MINT, completed, post, failed, 108),
            "exit_intended",
        )
        self.assertEqual(
            book.monitor_postgrad(
                POST_MINT, pumpswap_snapshot(now=111, slot=111), 111,
                {"exit": False, "reasons": []},
            ),
            "settled",
        )

    def test_runtime_telemetry_is_strategy_local(self):
        runtime = PumpAlphaProspectiveRuntime(
            {"initial_real_token_reserves": 560_000_000_000_000},
            100_000_000_000,
        )
        # Deliberately insufficient event history: the runtime should record the
        # rejection locally rather than borrowing authority from another strategy.
        rows = [
            event(now=90, wallet=pump.b58(bytes([31])*32), id="r1"),
            event(now=100, wallet=pump.b58(bytes([32])*32), id="r2"),
        ]
        decision = runtime.evaluate_curve(
            snapshot=snapshot(now=100, slot=100),
            events=rows,
            concentration_bps=1000,
            now=100,
        )
        self.assertFalse(decision["eligible"])
        status = runtime.status()
        self.assertEqual(status["evaluations"], 1)
        self.assertEqual(status["qualifiers"], 0)
        self.assertTrue(status["independent_from_existing_strategy_authority"])
        self.assertFalse(status["live_money_authority"])


if __name__ == "__main__":
    unittest.main()
