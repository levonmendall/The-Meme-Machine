from decimal import Decimal
import json
import tempfile
from pathlib import Path
import unittest

from meme_machine.portfolio_accounting import PortfolioAccounting, PortfolioIntegrityError, LANES, digest, inception_receipt
from meme_machine.portfolio_lane_integration import PortfolioLaneProducer, usd_evidence
from meme_machine.runtime.portfolio import NativePortfolio
from meme_machine.runtime.usd_valuation import USDValue, robinhood_usd, ValuationUnavailable, USDG_BLOCKER


class SharedOperationalPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "fixture.sqlite"
        self.at = "2026-10-03T00:00:00Z"
        self.ids = dict(source_sha="a"*40, policy_hash="b"*64, config_hash="c"*64)
        with self.account() as account:
            account.establish_inception(inception_receipt("offline-test-only", self.at, "fixture-inception"), portfolio_identities=self.ids, lane_identities={lane:self.ids for lane in LANES})
            account.configure_family_sleeves()

    def account(self):
        from contextlib import contextmanager
        @contextmanager
        def opened():
            account = PortfolioAccounting(self.path)
            try: yield account
            finally: account.close()
        return opened()

    def tearDown(self): self.tmp.cleanup()

    def fact(self, kind, data, key):
        return dict(event_key=key, journal_hash=digest([key, data]), kind=kind, at=self.at, data=data,
                    value_evidence=usd_evidence("offline-value", "d"*64, self.at, "2026-10-03T00:02:00Z") if kind not in ("reserve", "release", "rebalance_reserve") else None)

    def opened(self, lane, native):
        client = NativePortfolio(self.path, lane)
        client.deliver(native, **self.fact("reserve", {"amount":"6.25"}, "reserve"))
        client.deliver(native, **self.fact("enter", {"asset":"fixture-asset", "basis":"6.25", "fee":"0", "strategy_id":lane}, "entry"))
        return client

    def test_four_lane_partial_runner_scale_same_lifecycle_reconcile(self):
        for lane in LANES:
            native = lane + ":" + "long-native-identity-"*12
            client = self.opened(lane, native)
            client.deliver(native, **self.fact("harvest", {"basis_released":"1.5625", "gross_proceeds":"3.125", "fee":"0"}, "partial"))
            client.deliver(native, **self.fact("rebalance_reserve", {"amount":"3.125", "native_reservation_id":"add"}, "scale-reserve"))
            client.deliver(native, **self.fact("rebalance", {"basis_released":"0", "gross_proceeds":"0", "basis_added":"3.125", "fee":"0", "native_reservation_id":"add"}, "scale"))
            client.deliver(native, **self.fact("settle", {"gross_proceeds":"10", "fee":"0.25", "exit_reason":"fixture-close"}, "settle"))
        with self.account() as account:
            state = account.snapshot()
            self.assertEqual(len(state["positions"]), 4)
            self.assertEqual(account._reconcile(state)["realized"], Decimal("14.00"))
            self.assertEqual(state["available"], Decimal("514.00"))
            self.assertEqual(len(list(account.db.execute("SELECT native FROM portfolio_native_ids"))), 4)

    def test_no_cross_sleeve_borrow_or_unrealized_sizing(self):
        client = self.opened("pump", "native")
        client.deliver("native", **self.fact("mark", {"state":"CURRENT", "net_liquidation_value":"1000000"}, "mark"))
        self.assertEqual(client.equity(), Decimal("125"))
        with self.assertRaisesRegex(PortfolioIntegrityError,"family_sleeve"):
            client.deliver("other", **self.fact("reserve", {"amount":"119"}, "oversize"))
        self.assertFalse(client.pending())

    def test_ambiguous_delivery_requires_native_proof_and_recovers_exactly(self):
        client = NativePortfolio(self.path, "pons")
        reservation = client.prepare("native", **self.fact("reserve", {"amount":"6.25"}, "reserve"))
        self.assertEqual(len(client.pending()), 1)
        with self.assertRaisesRegex(PortfolioIntegrityError,"does_not_match"):
            client.committed("native", event_key="reserve", journal_hash="f"*64)
        NativePortfolio(self.path,"pons").committed("native", event_key="reserve", journal_hash=reservation.native_journal_hash)
        with self.account() as account:
            self.assertEqual(account._reconcile(account.snapshot())["reserved"], Decimal("6.25"))
        self.assertFalse(client.pending())

    def test_checkpoint_replay_keeps_all_money_and_active_native_cursors(self):
        client = self.opened("pump", "active")
        closed = self.opened("pons", "closed")
        closed.deliver("closed", **self.fact("settle", {"gross_proceeds":"7", "fee":"0", "exit_reason":"close"}, "settle"))
        with self.account() as account:
            before = account._reconcile(account.snapshot())
            account.compact(keep_closed=0)
            self.assertEqual(before, account._reconcile(account.snapshot()))
            self.assertEqual(len(account.snapshot()["positions"]), 1)
            self.assertEqual(account.db.execute("SELECT count(*) FROM portfolio_events").fetchone()[0], 0)
        client.deliver("active", **self.fact("mark", {"state":"CURRENT", "net_liquidation_value":"8"}, "next-mark"))
        with self.account() as account:
            self.assertEqual(account.snapshot()["positions"]["pump:n1"]["mark"]["net_liquidation_value"], "8")
            self.assertEqual(account.sleeve_equity("pons"), Decimal("125.75"))

    def test_missing_anchor_and_stale_rate_never_create_usd_authority(self):
        with self.assertRaisesRegex(ValuationUnavailable,"USDG/USD"):
            robinhood_usd()
        value = USDValue("SOL",9,Decimal("97.840001"),100,220,"fixture-value","e"*64)
        self.assertEqual(value.amount(123456789,100), Decimal("12.079012359216789"))
        with self.assertRaises(ValuationUnavailable): value.amount(1,221)
