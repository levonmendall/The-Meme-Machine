from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest
from robinhood_research import BoundaryError
from robinhood_research.ramses_strategy import POLICY_HASH,STRATEGY_DOMAIN,STRATEGY_VERSION
from robinhood_research.ramses_strategy_ledger import RamsesStrategyLedger


def decision(amount):
    return dict(mode='fee_pulse',qualified=True,allocation_authority=False,
        strategy_domain=STRATEGY_DOMAIN,strategy_version=STRATEGY_VERSION,policy_hash=POLICY_HASH,
        freeze=dict(proposal_hash='synthetic-test',proposals=[dict(capital_employed=amount)]))


class RamsesCapitalReplay(unittest.TestCase):
    def test_loss_reduces_next_reservation_and_failure_is_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            ledger=RamsesStrategyLedger(str(Path(td)/'paper.sqlite'),paper_capital=1000,quote_asset='quote')
            try:
                ledger.reserve('one',pool='pool',decision=decision(1000),at=1);ledger.open('one',at=2)
                ledger.settle('one',pnl=dict(strategy_domain=STRATEGY_DOMAIN,net_result_quote=-100,unresolved_inventory=None),at=3)
                before=ledger.reconcile()
                with self.assertRaisesRegex(BoundaryError,'capital_exhausted'):
                    ledger.reserve('two',pool='pool',decision=decision(1000),at=4)
                self.assertEqual(before,ledger.reconcile())
                ledger.reserve('two',pool='pool',decision=decision(900),at=4)
                self.assertEqual(ledger.reconcile()['available'],0)
            finally:ledger.close()

    def test_concurrent_reservations_share_one_available_balance(self):
        with tempfile.TemporaryDirectory() as td:
            path=str(Path(td)/'paper.sqlite')
            RamsesStrategyLedger(path,paper_capital=1000,quote_asset='quote').close()
            def reserve(i):
                ledger=RamsesStrategyLedger(path,paper_capital=1000,quote_asset='quote')
                try:
                    ledger.reserve(str(i),pool='pool',decision=decision(600),at=1);return 'reserved'
                except BoundaryError as exc:return str(exc)
                finally:ledger.close()
            with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(reserve,range(2)))
            self.assertEqual(sorted(results),['ramses_strategy_capital_exhausted','reserved'])

    def test_projection_loss_cannot_erase_a_reservation(self):
        with tempfile.TemporaryDirectory() as td:
            ledger=RamsesStrategyLedger(str(Path(td)/'paper.sqlite'),paper_capital=1000,quote_asset='quote')
            try:
                ledger.reserve_forced_machinery('one',pool='pool',decision=decision(600),at=1)
                with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):
                    ledger.db.execute('DELETE FROM ramses_strategy_journal')
                ledger.db.execute('DELETE FROM ramses_strategy_position')
                with self.assertRaisesRegex(BoundaryError,'projection_mismatch'):ledger.reconcile()
            finally:ledger.close()
