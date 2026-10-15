"""Preserved Survivor prefixes retain real risk replay and review continuity."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.native_snapshot_fixtures import copy_snapshot, native_counts
from meme_machine.runtime.directional_accounting import execution_cost
from meme_machine.runtime.survivor_commit import monitor,restore_risk
from meme_machine.runtime.survivor_paper_book import PaperBook
from tests import test_survivor_commit as fixture
from tests.test_survivor_risk_boundaries import POLICIES

class SurvivorPreservedCheckpointTests(unittest.TestCase):
    def case(self):
        case=fixture.SurvivorCommitTests()
        case.new_book=lambda:PaperBook(case.root/'paper.sqlite',run_id='run',lane='survivor',policy_hash='b',initial=1000)
        case.setUp();self.addCleanup(case.tearDown)
        entry=case.adapter.entry;exit_quote=case.adapter.exit_quote
        case.adapter.entry=lambda n:dict(entry(n),gas=3)
        case.adapter.exit_quote=lambda n:dict(exit_quote(n),gas=4)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        case.preserved=Path(temp.name)
        return case
    def snapshot(self,case,index):
        path=case.preserved/(str(index)+'.sqlite');rows=[]
        copy_snapshot(case.root/'paper.sqlite',path,rows)
        self.assertNotIn('error_type',rows[0])
        return path,dict(schema='preserved-native-prefix-v1',snapshot_sha256=rows[0]['sha256'],
            snapshot_name='pump/pump-survivor/paper.sqlite',state_hash=str(index).zfill(64),
            artifact=None,epoch_id='fixture-campaign',window_index=index)
    def compact(self,case,index):
        state=restore_risk(case.book,'run:one');account=case.book.reconcile();cost=execution_cost(case.book)
        old=native_counts(case.book);proof=case.book.replay()
        path,authority=self.snapshot(case,index)
        self.assertTrue(case.book._compact_preserved(path,authority))
        self.assertFalse(case.book._compact_preserved(path,authority))
        self.assertEqual(case.book.replay(),proof);self.assertEqual(case.book.reconcile(),account)
        self.assertEqual(restore_risk(case.book,'run:one'),state);self.assertEqual(execution_cost(case.book),cost)
        new=native_counts(case.book)
        self.assertEqual(old,new)
        for key in ('natural_entries','natural_settlements','natural_partial_realizations','natural_monitoring','natural_exits','complete_natural_lifecycles'):
            self.assertEqual(old.get(key,0),new.get(key,0),key)
        return old,new
    def test_both_policy_runners_resume_before_and_after_partial_then_settle_once(self):
        for lane in ('pump','pons'):
            with self.subTest(lane=lane):
                case=self.case();case.fill()
                self.compact(case,0);case.reopen()
                case.adapter.at=11;case.adapter.proceeds=32
                observation=dict(id='profit',at=11,after_cost_return_bps=POLICIES[lane]['first_profit_bps'],
                    net_exit_proceeds=125,exit_liquidity_valid=True)
                result=monitor(book=case.book,sleeve=case.sleeve,identity='run:one',
                    observation=observation,policy=POLICIES[lane],adapter=case.adapter)
                self.assertEqual(result['action'],'partial_exit')
                old,new=self.compact(case,1);case.reopen()
                self.assertTrue(restore_risk(case.book,'run:one')['realization_taken'])
                self.assertEqual(execution_cost(case.book),7)
                case.adapter.at=12;case.adapter.proceeds=90
                observation=dict(id='stop',at=12,after_cost_return_bps=POLICIES[lane]['hard_stop_bps'],net_exit_proceeds=66,exit_liquidity_valid=True)
                result=monitor(book=case.book,sleeve=case.sleeve,identity='run:one',observation=observation,policy=POLICIES[lane],adapter=case.adapter)
                self.assertEqual(result['action'],'full_exit')
                self.compact(case,2);case.reopen()
                self.assertEqual(execution_cost(case.book),11)
                before=case.book.reconcile();sleeve=case.sleeve.reconcile()
                self.assertEqual(monitor(book=case.book,sleeve=case.sleeve,identity='run:one',observation=observation,policy=POLICIES[lane],adapter=case.adapter)['action'],'settled')
                self.assertEqual(case.book.reconcile(),before);self.assertEqual(case.sleeve.reconcile(),sleeve)
                self.assertEqual(before['open_positions'],0)
    def test_preserved_prefix_keeps_newer_risk_tail_and_checks_source_hash(self):
        case=self.case();case.fill();source,authority=self.snapshot(case,0)
        case.adapter.at=11;case.adapter.proceeds=32
        monitor(book=case.book,sleeve=case.sleeve,identity='run:one',
            observation=dict(id='profit',at=11,after_cost_return_bps=POLICIES['pump']['first_profit_bps'],
                net_exit_proceeds=125,exit_liquidity_valid=True),policy=POLICIES['pump'],adapter=case.adapter)
        risk=restore_risk(case.book,'run:one');proof=case.book.replay()
        wrong=dict(authority,snapshot_sha256='f'*64)
        with self.assertRaisesRegex(ValueError,'snapshot_identity'):case.book._compact_preserved(source,wrong)
        self.assertEqual(case.book.replay(),proof)
        case.book._compact_preserved(source,authority);case.reopen()
        self.assertGreater(case.book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0],0)
        self.assertEqual(case.book.replay(),proof);self.assertEqual(restore_risk(case.book,'run:one'),risk)
        self.assertTrue(risk['realization_taken']);self.assertEqual(execution_cost(case.book),7)

    def test_prefix_rollback_restores_raw_journal_and_risk(self):
        case=self.case();case.fill();source,authority=self.snapshot(case,0)
        before=case.book.replay();state=restore_risk(case.book,'run:one');calls=[];original=case.book.replay
        def cut():
            calls.append(True)
            if len(calls)==2:raise SystemExit('checkpoint commit cut')
            return original()
        with patch.object(case.book,'replay',side_effect=cut):
            with self.assertRaises(SystemExit):case.book._compact_preserved(source,authority)
        self.assertIsNone(case.book._archive());self.assertEqual(case.book.replay(),before)
        self.assertEqual(restore_risk(case.book,'run:one'),state)
    def test_168_checkpoints_bound_mark_history_without_replacing_raw_artifacts(self):
        # Storage-primitive stress only, not a claim that policy holds seven days.
        case=self.case();case.fill();sizes=[];hashes=[]
        state=restore_risk(case.book,'run:one')
        for window in range(168):
            previous=native_counts(case.book)
            for tick in range(200):
                at=11+window*200+tick
                case.book.transition('run:one','mark',at,amount=100,
                    evidence=dict(risk_state=state,observation={'at':at}))
            source,authority=self.snapshot(case,window);hashes.append(authority['snapshot_sha256'])
            before=case.book.replay();case.book._compact_preserved(source,authority)
            self.assertEqual(case.book.replay(),before)
            now=native_counts(case.book)
            # This prefix seals events later than the prior report; use the
            # exact pre-seal report for continuity, never an older skipped one.
            if window==0:self.assertNotEqual(previous,now)
            self.assertEqual(case.book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0],0)
            case.reopen();sizes.append((case.root/'paper.sqlite').stat().st_size)
        self.assertEqual(len(set(hashes)),168)
        self.assertEqual(case.book.replay()['events'],33602)
        self.assertEqual(execution_cost(case.book),3)
        self.assertEqual(restore_risk(case.book,'run:one'),state)
        self.assertLessEqual(max(sizes[4:])-min(sizes[4:]),65536)
        self.assertEqual(case.book.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        print('168-window Survivor prefix component: marks',33600,'hot bytes',min(sizes[4:]),max(sizes[4:]),'preserved snapshots',len(hashes))
