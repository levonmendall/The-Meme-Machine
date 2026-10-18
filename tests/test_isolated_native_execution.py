"""Implicit legacy constructors cannot regain authority in isolated scopes."""
from concurrent.futures import ProcessPoolExecutor,ThreadPoolExecutor
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from meme_machine.runtime.isolated_native_execution import (
    IsolatedFinancialWriteDenied,financial_writes_denied,
    install_isolated_native_execution,isolated_native_execution,
    reject_financial_construction,
)
from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
from tests.test_isolated_native_resources import authenticated,receipt


def implicit_pump_book(path):
    from meme_machine.lanes.pump.paper_accounting import PaperBook
    try:
        book=PaperBook(path,run_id='offline',lane='pump',policy_hash='offline',initial=1000)
    except IsolatedFinancialWriteDenied:
        return 'DENIED'
    else:
        book.close()
        return 'UNEXPECTED_FINANCIAL_CREATION'


class IsolatedNativeExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.resources=IsolatedNativeResources(self.root/'owned',
            sizing_facts=authenticated(receipt()),clock=lambda:1000)

    def tearDown(self):
        self.resources.close();self.tmp.cleanup()

    def test_nested_implicit_financial_constructors_refuse_before_any_state(self):
        from meme_machine.lanes.pump.paper_accounting import PaperBook as PumpBook
        from meme_machine.runtime.survivor_paper_book import PaperBook as SurvivorBook
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.shared_capital.native_sleeve import SharedSleeve
        from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper
        from meme_machine.runtime.native_boundary import attach
        from meme_machine.runtime.portfolio import NativePortfolio
        from meme_machine.shared_capital.runtime import SharedNativePortfolio
        from meme_machine.shared_capital.authority import CapitalAuthority
        from meme_machine.portfolio_accounting import PortfolioAccounting
        from meme_machine.operational.lane import run_native
        path=self.root/'must-not-exist'/'money.sqlite';store=Mock()
        kwargs=dict(run_id='r',lane='pump',policy_hash='p',initial=1000)
        calls=(lambda:PumpBook(path,**kwargs),lambda:SurvivorBook(path,**kwargs),
            lambda:SleeveReservations(path,lane='pump',capital=1000,policies={},cohort='c'),
            lambda:SharedSleeve(path,lane='pump',capital=1000,policies={},cohort='c'),
            lambda:CohortCapital(path,1000),lambda:SelectivePaper(store,'ignored',1000),
            lambda:attach(object(),'pump'),lambda:NativePortfolio(path,'pump'),
            lambda:SharedNativePortfolio(path,'pump'),lambda:CapitalAuthority(path),
            lambda:PortfolioAccounting(path),lambda:run_native(path.parent,'pump'))
        def nested_legacy_call(call):return call()
        self.assertFalse(financial_writes_denied())
        self.assertIsNone(reject_financial_construction())
        with patch('sqlite3.connect',side_effect=AssertionError('financial SQLite opened')):
            with isolated_native_execution(self.resources):
                with isolated_native_execution(self.resources):
                    for call in calls:
                        with self.subTest(call=call),self.assertRaises(IsolatedFinancialWriteDenied):
                            nested_legacy_call(call)
                self.assertTrue(financial_writes_denied())
        self.assertFalse(financial_writes_denied())
        self.assertIsNone(reject_financial_construction())
        self.assertFalse(path.parent.exists());self.assertEqual(store.mock_calls,[])

    def test_native_owner_thread_initializer_installs_denial_without_main_thread_leak(self):
        path=self.root/'thread-money.sqlite'
        with ThreadPoolExecutor(max_workers=1,initializer=install_isolated_native_execution,
                initargs=(self.resources,)) as pool:
            self.assertTrue(pool.submit(financial_writes_denied).result(timeout=5))
            self.assertEqual(pool.submit(implicit_pump_book,str(path)).result(timeout=5),'DENIED')
        self.assertFalse(financial_writes_denied());self.assertFalse(path.exists())

    def test_real_spawn_initializer_denies_implicit_book_without_copying_resources(self):
        path=self.root/'spawn-money.sqlite'
        with ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'),
                initializer=install_isolated_native_execution) as pool:
            self.assertTrue(pool.submit(financial_writes_denied).result(timeout=10))
            self.assertEqual(pool.submit(implicit_pump_book,str(path)).result(timeout=10),'DENIED')
        self.assertFalse(financial_writes_denied());self.assertFalse(path.exists())
