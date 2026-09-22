"""Synthetic mechanics only: these tests never claim natural qualification."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from meme_machine import dlmm
from meme_machine.dlmm_independent_accounting import PaperBook
from meme_machine.dlmm_tape import VerifiedTape
from meme_machine.store import digest
from tests.dlmm_support import snapshot
from tests import solana_dlmm_independent_v1 as strategy


class DurableIndependentAccounting(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.policy=strategy.load_policy();self.entry=dlmm.validate(snapshot(),100)
        self.features=dict(half_width_bins=4,lower=-4,upper=4,volume_rate_sol_lamports_per_second=1,fee_density=1)
        self.path=Path(self.tmp.name)/'paper.sqlite'
        self.book=self.reopen()

    def reopen(self):return PaperBook(self.path,run_id='test',policy_hash=digest(self.policy),capital=1_000_000_000)

    def observe(self,adapter,address,current,duration,*args):
        end=deepcopy(current);end.update(time=current['time']+duration,slot=current['slot']+1)
        tape=VerifiedTape(digest(current),digest(end),(),end,digest(dict(synthetic=True,start=current['slot'],end=end['slot'])))
        return dict(verified=True),tape,end,current,adapter

    def run_lifecycle(self):
        with patch.object(strategy,'_rotate',side_effect=lambda a,*args:a),patch.object(strategy,'_observe_window',side_effect=self.observe):
            return strategy._lifecycle(None,self.entry['pool'],self.entry,self.features,self.policy,None,[],book=self.book)[0]

    def test_full_lifecycle_reopens_replays_and_recycles_only_actual_cash(self):
        first=self.run_lifecycle();self.assertTrue(first['complete'])
        final=first['final'];rec=self.reopen().reconcile()
        self.assertEqual(rec['cash'],1_000_000_000+final['pnl_lamports'])
        self.assertEqual((rec['settled'],rec['unsettled']),(1,0))
        self.assertGreater(rec['capital_unit_nanoseconds'],0)
        self.assertEqual(final['pnl_lamports'],final['inventory_mark_pnl_lamports']+final['fee_income_mark_lamports']-final['unwind_cost_lamports']-final['network_cost_lamports'])
        replay=self.reopen().replay_economics(strategy._build_position,strategy._advance_position,strategy._mark)
        self.assertTrue(replay['verified']);self.assertGreaterEqual(replay['checked_economic_events'],3)
        self.book=self.reopen();second=self.run_lifecycle();rec=self.book.reconcile()
        self.assertNotEqual(first['lifecycle_id'],second['lifecycle_id'])
        self.assertEqual(rec['cash'],1_000_000_000+first['final']['pnl_lamports']+second['final']['pnl_lamports'])
        with self.assertRaisesRegex(ValueError,'position_not_open'):
            self.book.append(first['lifecycle_id'],'settle',dict(mark=first['final']))
        self.assertEqual(rec,self.book.reconcile())

    def test_failed_monitor_keeps_position_and_cost_reserve(self):
        def fail(*args):return dict(verified=False,reason='synthetic_evidence_missing'),None,None,None,None
        with patch.object(strategy,'_rotate',side_effect=lambda a,*args:a),patch.object(strategy,'_observe_window',side_effect=fail):
            result=strategy._lifecycle(None,self.entry['pool'],self.entry,self.features,self.policy,None,[],book=self.book)[0]
        self.assertFalse(result['complete']);r=self.reopen().reconcile()
        self.assertEqual((r['open_positions'],r['stale_marks'],r['reserved']),(1,1,strategy.EXIT_NETWORK_COST))
        self.assertEqual(r['cash'],1_000_000_000-strategy.CAPITAL-strategy.ENTRY_NETWORK_COST)
        self.assertEqual(r['settled'],0)

    def test_structural_unreplayable_monitor_writes_off_without_stranding(self):
        structural='dlmm_add_liquidity_by_strategy2_mixed_with_swap_interval'
        def fail(*args):return dict(verified=False,reason=structural),None,None,None,None
        with patch.object(strategy,'_rotate',side_effect=lambda a,*args:a),patch.object(strategy,'_observe_window',side_effect=fail):
            result=strategy._lifecycle(None,self.entry['pool'],self.entry,self.features,self.policy,None,[],book=self.book)[0]
        self.assertFalse(result['complete']);self.assertTrue(result['terminal_writeoff'])
        r=self.reopen().reconcile()
        self.assertEqual((r['open_positions'],r['stale_marks'],r['reserved'],r['writeoffs']),(0,0,0,1))
        self.assertEqual(r['realized_pnl_lamports'],-strategy.CAPITAL-strategy.ENTRY_NETWORK_COST)

    def test_failed_build_cancels_without_minting_capital_and_namespace_is_fixed(self):
        with patch.object(strategy,'_build_position',side_effect=ValueError('synthetic_bad_entry')):
            with self.assertRaisesRegex(ValueError,'synthetic_bad_entry'):
                strategy._lifecycle(None,'pool',self.entry,self.features,self.policy,None,[],book=self.book)
        r=self.reopen().reconcile();self.assertEqual((r['cash'],r['unsettled']),(1_000_000_000,0))
        with self.assertRaisesRegex(ValueError,'foreign_lifecycle'):
            self.book.append('pons:foreign','reserve',dict(amount=1))
        with self.assertRaisesRegex(ValueError,'capital_exhausted'):
            self.book.append(self.book.identity(),'reserve',dict(amount=1_000_000_001))
        with sqlite3.connect(self.path) as db:
            with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):db.execute('DELETE FROM events')

    def test_replay_rejects_different_economic_result(self):
        self.run_lifecycle()
        def wrong(position):return dict(strategy._mark(position),ending_sol_lamports=1)
        with self.assertRaisesRegex(ValueError,'entry_replay'):self.book.replay_economics(strategy._build_position,strategy._advance_position,wrong)