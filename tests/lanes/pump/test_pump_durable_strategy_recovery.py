from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.lanes.pump.paper_accounting import PaperBook
from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle as Lifecycle
from meme_machine.lanes.pump.pump_acceleration_strategy import policy_hash,STRATEGY_ID
from tests.lanes.pump.test_pump_acceleration_paper import qualification

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'book.sqlite'
        self.book=PaperBook(self.path,run_id='recovery',lane=STRATEGY_ID,policy_hash=policy_hash(),initial=10000)
        self.life=Lifecycle(book=self.book,lifecycle_id='recovery:one',entry_evidence={'slot':5,'fill_context':{'signal':'retained'}})
        self.life.reserve(qualification(),1000,100)
    def tearDown(self):self.book.close();self.temp.cleanup()
    def recover(self):
        before=self.book.replay()
        restored=Lifecycle.restore(self.book,'recovery:one')
        self.assertEqual(self.book.replay(),before)
        return restored
    def test_reservation_and_original_time_preserved(self):
        restored=self.recover()
        self.assertEqual(restored.snapshot(),self.life.snapshot())
        self.assertEqual(restored.entry_evidence,self.life.entry_evidence)
        self.assertEqual(restored.reservation['reserved_at'],100)
    def test_fill_committed_before_memory_update_does_not_duplicate(self):
        self.book.transition('recovery:one','filled',102,amount=900,tokens=100,
                             evidence={'surface':'pump.fun','execution':{'slot':7}})
        restored=self.recover()
        self.assertEqual(restored.position.tokens,100)
        self.assertIsNone(restored.reservation)
        with self.assertRaises(ValueError):restored.fill(100,900,103,'pump.fun')
        self.assertEqual(self.book.reconcile()['open_positions'],1)
    def test_graduation_highwater_partial_and_soft_exit_streak_survive(self):
        self.life.fill(100,900,102,'pump.fun')
        self.life.authenticate_graduation(110,True)
        self.life.mark(1200,111,80,True)
        self.life.harvest(25,300,112)
        self.life.mark(810,113,20,True)
        restored=self.recover()
        self.assertEqual(restored.snapshot(),self.life.snapshot())
        self.assertTrue(restored.position.partial_harvest_taken)
        self.assertTrue(restored.position.graduation_authenticated)
        self.assertEqual(restored.position.demand_deterioration_streak,1)
    def test_close_and_reopen_uses_journal_without_report(self):
        self.life.fill(100,900,102,'pump.fun')
        expected=self.life.snapshot();self.book.close()
        self.book=PaperBook(self.path,run_id='recovery',lane=STRATEGY_ID,policy_hash=policy_hash(),initial=10000)
        self.assertEqual(self.recover().snapshot(),expected)
    def test_settlement_is_not_fabricated_by_recovery(self):
        self.life.fill(100,900,102,'pump.fun')
        self.life.mark(700,105,80)
        restored=self.recover()
        self.assertEqual(self.book.reconcile()['settled'],0)
        self.assertEqual(restored.position.exit_reason,self.life.position.exit_reason)
        restored.settle(700,106)
        again=self.recover()
        self.assertIsNone(again.position)
        self.assertEqual(self.book.reconcile()['settled'],1)
    def test_cancelled_reservation_stays_terminal(self):
        self.life.cancel('entry_fill_timeout',120)
        self.assertEqual(self.recover().snapshot(),self.life.snapshot())
