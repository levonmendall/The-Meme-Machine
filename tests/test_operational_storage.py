"""Economic state remains exact when retained telemetry/journal prefixes shrink."""
from contextlib import closing
from decimal import Decimal
import json,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

from meme_machine.runtime.storage import compact_pons,audit_ring,compact_pump
from meme_machine.runtime.lifecycle_identity import issue
from meme_machine.runtime.pons_terminal_archive import checkpoint_capital
from meme_machine.portfolio_accounting import PortfolioAccounting,LANES,inception_receipt


class StorageBounds(unittest.TestCase):
    def test_decision_evidence_retention_preserves_waiting_consumers_without_double_archive(self):
        from meme_machine.lanes.pump.solana_evidence_broker import EvidenceBroker
        from meme_machine.runtime.storage import solana_cache_retention
        clock=[1]
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'MM_PAPER_EPOCH':'offline-cache'}):
            broker=EvidenceBroker(Path(td)/'cache.sqlite',clock=lambda:clock[0])
            try:
                broker.put_transaction('expired',{'slot':1,'blockTime':1})
                broker.put_transaction('needed',{'slot':2,'blockTime':1})
                broker.consumers.register('open-position',['needed'],'position_monitor',200000)
                self.assertEqual(broker.db.execute('SELECT COUNT(*) FROM tx_cache').fetchone()[0],0)
                clock[0]=90000
                with broker.lock,broker.db:solana_cache_retention(broker.db,clock[0])
                self.assertIsNone(broker.get_transaction('expired'))
                self.assertEqual(broker.get_transaction('needed')['slot'],2)
                with self.assertRaises(sqlite3.IntegrityError):broker.db.execute("DELETE FROM immutable_transactions WHERE signature='needed'")
            finally:broker.close()

    def test_active_pons_prefix_retains_flow_integral_and_next_commit(self):
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE,JOURNAL_CATEGORY
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        from meme_machine.lanes.pons.evidence import Store
        fixture=PartialAccountingTests()
        with tempfile.TemporaryDirectory() as td:
            with closing(Store(Path(td)/'native.sqlite')) as store:
                clock=iter(range(1,1000))
                book=SelectivePaper(store,STRATEGY_NAMESPACE,10000,natural_policy_hash=POLICY_HASH,clock_ns=lambda:next(clock)*10**9)
                book.reserve('x',market='m',amount=100,gas_budget=2,now=100,features=fixture.features(100))
                book.advance('x',now=102,action='entry',quote=fixture.quote(102,'buy',100,1000))
                for at in range(103,113):book.advance('x',now=at,action='mark',quote=fixture.quote(at,'sell',1000,130))
                before=book.reconcile();self.assertTrue(compact_pons(book,limit=4))
                self.assertEqual(book.reconcile(),before)
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM records WHERE category=?',(JOURNAL_CATEGORY,)).fetchone()[0],1)
                book.advance('x',now=113,action='mark',quote=fixture.quote(113,'sell',1000,132))
                self.assertGreater(book.accounting('x')['capital_at_risk_unit_nanoseconds'],before['accounting']['x']['capital_at_risk_unit_nanoseconds'])
                book.advance('x',now=114,action='exit_intent',exit_tokens=250)
                book.advance('x',now=116,action='exit',quote=fixture.quote(116,'sell',250,40))
                self.assertEqual(book._get('x')['tokens'],750)
                self.assertTrue(book.reconcile()['cash_basis_conservation'])

    def test_native_pump_checkpoint_restores_exact_controller_state(self):
        from meme_machine.lanes.pump.paper_accounting import PaperBook
        from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
        from meme_machine.lanes.pump.pump_acceleration_strategy import STRATEGY_ID,policy_hash
        from tests.lanes.pump.test_pump_acceleration_paper import qualification
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'MM_PAPER_EPOCH':'offline-prefix'}):
            with closing(PaperBook(Path(td)/'native.sqlite',run_id='offline-prefix',lane=STRATEGY_ID,policy_hash=policy_hash(),initial=100000)) as book:
                native=issue('offline-prefix:winner');life=PumpAccelerationPaperLifecycle(book=book,lifecycle_id=native)
                life.reserve(qualification(),5000,100);life.fill(1000,5000,102,'pump.fun')
                for at in range(103,650):life.mark(5500,at,80)
                before=life.snapshot();restored=PumpAccelerationPaperLifecycle.restore(book,native)
                self.assertEqual(restored.snapshot()['position'],before['position'])
                self.assertEqual(restored.entry_evidence,life.entry_evidence)
                self.assertLess(book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0],512)
                self.assertLess(len(book._archive()['controller_snapshots'][native]['state']['history']),67)
                self.assertTrue(book.replay()['verified'])

    def test_audit_retention_preserves_scheduling_state_and_monotone_sequence(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript("CREATE TABLE audit(seq INTEGER PRIMARY KEY,body TEXT);CREATE TABLE capital(amount INTEGER);INSERT INTO capital VALUES(500);CREATE TRIGGER audit_guard BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'append_only');END;")
            db.executemany('INSERT INTO audit(body) VALUES(?)',[(str(i),) for i in range(100)])
            audit_ring(db,'audit','audit_guard',limit=8)
            db.execute("INSERT INTO audit(body) VALUES('next')")
            self.assertEqual(db.execute('SELECT MAX(seq) FROM audit').fetchone()[0],101)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],9)
            self.assertEqual(db.execute('SELECT amount FROM capital').fetchone()[0],500)
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM audit')

    def test_many_local_closed_aliases_fold_without_losing_money_or_reopening(self):
        from meme_machine.runtime.portfolio import NativePortfolio
        from meme_machine.portfolio_lane_integration import usd_evidence
        from meme_machine.portfolio_accounting import PortfolioIntegrityError
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'MM_PAPER_EPOCH':'offline-bounds'}):
            path=Path(td)/'portfolio.sqlite';at='2026-10-03T00:00:00Z';ids=dict(source_sha='a'*40,policy_hash='b'*64,config_hash='c'*64)
            with closing(PortfolioAccounting(path)) as account:
                account.establish_inception(inception_receipt('offline-bounds',at,'fixture'),portfolio_identities=ids,lane_identities={lane:ids for lane in LANES});account.configure_family_sleeves()
            client=NativePortfolio(path,'pump');old=None
            for i in range(20):
                native=issue('offline-bounds:'+str(i));old=old or native
                for kind,data in [('reserve',{'amount':'6.25'}),('enter',{'asset':'fixture','basis':'6.25','fee':'0','strategy_id':'pump'}),('settle',{'gross_proceeds':'7.25','fee':'0','exit_reason':'fixture'})]:
                    client.deliver(native,event_key=kind,journal_hash='f'*64,kind=kind,at=at,data=data,value_evidence=usd_evidence('fixture-value','e'*64,at,'2026-10-03T00:02:00Z') if kind!='reserve' else None)
            with closing(PortfolioAccounting(path)) as account:
                before=account._reconcile(account.snapshot());account.compact(keep_closed=2)
                self.assertEqual(before,account._reconcile(account.snapshot()))
                self.assertEqual(account.snapshot()['available'],Decimal('520'))
                self.assertEqual(account.db.execute('SELECT COUNT(*) FROM portfolio_native_ids').fetchone()[0],2)
                self.assertLessEqual(len(account.snapshot()['native_cursors']),2)
            with self.assertRaisesRegex(PortfolioIntegrityError,'retired_native'):
                client.prepare(old,event_key='replay',journal_hash='f'*64,kind='reserve',at=at,data={'amount':'6.25'})
