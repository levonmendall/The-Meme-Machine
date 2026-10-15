"""Interrupt every money boundary and reconstruct durable authority after restart."""
import multiprocessing
import os
import sqlite3
import tempfile
import unittest

from meme_machine.shared_capital import CapitalAuthority, CapitalError
from meme_machine.shared_capital.model import money
from tests.shared_capital_support import Harness


class Interrupted(RuntimeError):
    pass


def _crash_allocate(path, stage):
    authority = CapitalAuthority(path)
    authority.fault = lambda point: os._exit(88) if point == stage else None
    authority.allocate(round_id="process-crash", at=0)
    authority.close()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.h = Harness(self.temp.name); self.addCleanup(lambda: self.h.close())

    def interrupted(self, stage, action, *, committed=False):
        before = self.h.authority.snapshot()
        def fail(point):
            if point == stage: raise Interrupted(point)
        self.h.authority.fault = fail
        with self.assertRaises(Interrupted): action()
        self.h.authority.fault = None
        self.h.restart()
        if not committed: self.assertEqual(before, self.h.authority.snapshot())
        self.h.check(); self.h.authority.verify_replay()

    def sealed(self, round_id="crash"):
        q = self.h.prepare("pump_current", round_id=round_id)
        self.h.authority.open_round(operation_id="open:" + round_id, round_id=round_id, at=0, cutoff=0)
        self.h.authority.submit(q, at=0); self.h.finish_round(round_id, [q])
        return q

    def test_before_reservation_and_during_decision_leave_no_partial_grants(self):
        self.sealed()
        for stage in ("before_apply", "during_allocation", "before_commit"):
            self.interrupted(stage, lambda: self.h.authority.allocate(round_id="crash", at=0))
        result = self.h.authority.allocate(round_id="crash", at=0)
        self.assertEqual(sum(d["status"] == "RESERVED" for d in result["decisions"].values()), 1)

    def test_after_reservation_commit_retry_returns_original_grant(self):
        q = self.sealed()
        self.interrupted("after_commit", lambda: self.h.authority.allocate(round_id="crash", at=0), committed=True)
        self.assertEqual(money(self.h.check()["capital"]["active_reservations"]), money("6.25"))
        result = self.h.authority.allocate(round_id="crash", at=0)
        self.assertEqual(result["decisions"][q.request_id]["status"], "RESERVED")

    def test_before_and_during_position_creation_preserve_commitment_and_single_basis(self):
        requests, _ = self.h.allocate([("pump_current", {})]); q = requests[0]
        self.h.authority.commit(operation_id="intent", request_id=q.request_id,
            commitment_id="position-intent", at=0, intent_sha256="a" * 64, lifecycle_id="life:" + q.request_id)
        native = self.h.native(q.regime, "life:" + q.request_id)
        def fill():
            return self.h.authority.consume(operation_id="consume:" + q.request_id, request_id=q.request_id,
                lifecycle_id="life:" + q.request_id, basis="6.25", cost="0", at=0,
                native=native, valuation=self.h.valuation(), native_basis_units=625000000000000000000000000000)
        for stage in ("before_apply", "during_position_creation", "before_commit"):
            self.interrupted(stage, fill)
        self.interrupted("after_commit", fill, committed=True)
        fill()  # Same delivery is idempotent after a lost reply.
        s = self.h.check()
        self.assertEqual(money(s["capital"]["deployed_basis"]), money("6.25"))
        self.assertEqual(len(s["ledger"]["positions"]), 1)
        self.assertEqual(money(s["capital"]["pending_authoritative_commitments"]), 0)

    def test_cancellation_interruption_cannot_strand_or_double_release_capital(self):
        requests, _ = self.h.allocate([("pump_current", {})]); q = requests[0]
        def cancel():
            return self.h.authority.cancel(operation_id="cancel", request_id=q.request_id, at=0,
                proof_sha256="a" * 64, proof_kind="DEFINITIVELY_CANCELLED")
        self.interrupted("before_commit", cancel)
        self.interrupted("after_commit", cancel, committed=True)
        cancel()
        self.assertEqual(money(self.h.check()["capital"]["free_cash"]), 500)

    def test_partial_and_terminal_settlement_restart_never_duplicate_pnl(self):
        requests, _ = self.h.allocate([("pons_current", {})]); q = requests[0]
        life, _ = self.h.fill(q); self.h.at = 10
        native = self.h.native(q.regime, life)
        def partial():
            return self.h.authority.realize(operation_id="partial", lifecycle_id=life, basis_released="1.25",
                gross_proceeds="2", cost="0", at=10, native=native, valuation=self.h.valuation(), terminal=False)
        self.interrupted("during_partial_realization", partial)
        self.interrupted("after_commit", partial, committed=True); partial()
        self.h.at = 20; native = self.h.native(q.regime, life)
        def terminal():
            return self.h.authority.realize(operation_id="terminal", lifecycle_id=life, basis_released="5",
                gross_proceeds="7", cost="0", at=20, native=native, valuation=self.h.valuation(), terminal=True)
        self.interrupted("during_settlement", terminal)
        self.interrupted("after_commit", terminal, committed=True); terminal()
        self.assertEqual(money(self.h.check()["capital"]["realized_equity"]), money("502.75"))

    def test_process_death_before_and_after_full_synchronous_commit(self):
        self.sealed("process-crash")
        context = multiprocessing.get_context("spawn")
        for stage, expected in (("during_allocation", "0"), ("before_commit", "0"), ("after_commit", "6.25")):
            with self.subTest(stage=stage):
                process = context.Process(target=_crash_allocate, args=(self.h.path, stage))
                process.start(); process.join(timeout=30)
                self.assertEqual(process.exitcode, 88)
                self.h.restart()
                self.assertEqual(money(self.h.check()["capital"]["active_reservations"]), money(expected))

    def test_conflicting_native_delivery_and_projection_corruption_fail_closed(self):
        requests, _ = self.h.allocate([("pump_current", {})]); q = requests[0]
        life, _ = self.h.fill(q)
        native = self.h.native(q.regime, life); native["sequence"] -= 1
        with self.assertRaisesRegex(CapitalError, "sequence_gap_or_replay"):
            self.h.authority.mark(operation_id="bad-native", lifecycle_id=life, net_value="6.25",
                at=0, native=native, valuation=self.h.valuation())
        self.h.authority.db.execute("UPDATE shared_capital_projection SET hash=?", ("0" * 64,))
        with self.assertRaisesRegex(CapitalError, "projection_mismatch"):
            self.h.authority.snapshot()

    def test_journal_is_append_only_and_missing_capital_cannot_be_reinitialized(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.h.authority.db.execute("DELETE FROM shared_capital_events")
        with self.assertRaisesRegex(CapitalError, "already_installed"):
            self.h.authority.install_migration(self.h.plan, operation_id="another-inception")
        self.h.authority.install_migration(self.h.plan)
        self.assertEqual(money(self.h.check()["capital"]["realized_equity"]), 500)

    def test_commitment_and_native_ack_cannot_fork_the_request_lifecycle(self):
        requests, _ = self.h.allocate([("pump_current", {})]); q = requests[0]
        with self.assertRaisesRegex(CapitalError, "lifecycle_identity_required"):
            self.h.authority.commit(operation_id="unbound-intent", request_id=q.request_id,
                commitment_id="unbound", at=0, intent_sha256="a" * 64)
        self.h.authority.acknowledge_native(operation_id="reserve-ack", request_id=q.request_id, lifecycle_id="life:bound",
            at=0, native=self.h.native(q.regime, "life:bound"))
        self.h.restart()
        with self.assertRaisesRegex(CapitalError, "lifecycle_identity_conflict"):
            self.h.authority.commit(operation_id="forked-intent", request_id=q.request_id,
                commitment_id="forked", at=0, intent_sha256="a" * 64, lifecycle_id="life:other")
        self.h.authority.commit(operation_id="bound-intent", request_id=q.request_id,
            commitment_id="bound", at=0, intent_sha256="a" * 64, lifecycle_id="life:bound")
        with self.assertRaisesRegex(CapitalError, "native_ack_identity_mismatch"):
            self.h.authority.acknowledge_native(operation_id="forked-ack", request_id=q.request_id, lifecycle_id="life:other",
                at=0, native=self.h.native(q.regime, "life:other"))
        self.assertEqual(money(self.h.check()["capital"]["pending_authoritative_commitments"]), money("6.25"))
