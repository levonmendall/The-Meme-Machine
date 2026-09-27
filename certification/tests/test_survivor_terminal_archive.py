"""Changing retired economic IDs plateau without forgetting entry authority."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from certification.archive_native import copy_snapshot
from certification.journal import digest
from certification.lifecycle_identity import issue
from certification.survivor_history import History
from certification.survivor_paper_book import PaperBook
from certification.sleeve_reservations import SleeveReservations
from certification import survivor_terminal_archive as archive
from certification.market_assurance import native_positions
from certification.directional_accounting import execution_cost


class SurvivorTerminalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.hot=self.root/'hot';self.hot.mkdir()
        self.book=PaperBook(self.hot/'paper.sqlite',run_id='run',lane='survivor',policy_hash='b',initial=1000)
        self.sleeve=SleeveReservations(self.hot/'sleeve.sqlite',lane='pump',capital=1000,
            policies={'survivor':'b','current':'a'},cohort='fixture')
        self.history=History(self.hot/'history.sqlite',policy='b')
        self.addCleanup(lambda:self.book.close());self.addCleanup(lambda:self.sleeve.close());self.addCleanup(lambda:self.history.close())

    def window(self,index):return dict(campaign_id='terminal-fixture',authorization_hash='a'*64,index=index)

    def populate(self,index,count=8):
        identities=[]
        with patch('certification.campaign_state.active_window',return_value=self.window(index)):
            for n in range(count):
                at=index*3600+n*10;candidate='candidate:'+str(index)+':'+str(n)
                row=self.history.graduate(candidate,dict(at=at))
                observed=self.sleeve.observe(candidate,strategy='survivor',at=at,state='qualified',evidence={},regime={})
                identity=issue('run:'+candidate);identities.append(identity)
                self.sleeve.reserve(identity,strategy='survivor',amount=100,at=at,candidate=candidate,generation=observed['generation'],regime={})
                self.book.reserve(identity,100,at,{'candidate':candidate})
                with self.sleeve.commit_fence(identity):pass
                self.book.transition(identity,'filled',at+1,amount=100,tokens=100,evidence={'execution':{'gas':1}})
                self.book.transition(identity,'partial_harvest',at+2,amount=25,tokens=25,evidence={'execution':{'gas':1}})
                self.book.transition(identity,'settled',at+3,amount=75,evidence={'execution':{'gas':1}})
                p=self.book._load(identity)
                self.sleeve.release(identity,pnl=p['realized'],at=at+3,terminal_hash=digest(p),native_verified=True)
                self.history.retire(row,expired_before=at+1)
        return identities

    def preserve(self,index):
        folder=self.root/str(index);folder.mkdir();self.history.close();records=[]
        for name in ('paper.sqlite','sleeve.sqlite','history.sqlite'):
            copy_snapshot(self.hot/name,folder/name,records)
        self.assertFalse(any(r.get('error_type') for r in records))
        authority=dict(schema='preserved-native-prefix-v1',state_hash=str(index).zfill(64),
            artifact={'digest':'sha256:'+'b'*64},campaign_id='terminal-fixture',
            authorization_hash='a'*64,window_index=index)
        for owner,name in ((self.book,'paper.sqlite'),(self.sleeve,'sleeve.sqlite')):
            owner._compact_preserved(folder/name,dict(authority,snapshot_name=name,
                snapshot_sha256=hashlib.sha256((folder/name).read_bytes()).hexdigest()))
        shutil.copyfile(folder/'history.sqlite',self.hot/'history.sqlite')
        with patch.dict(os.environ,MM_AUTONOMOUS_STATE_RECEIPT='verified-fixture'):
            self.history=History(self.hot/'history.sqlite',policy='b')
        self.history.compact_archived(dict(authority,history_sha256=hashlib.sha256((folder/'history.sqlite').read_bytes()).hexdigest()))
        return folder

    def test_changing_settled_ids_and_candidates_plateau_with_exact_totals(self):
        sizes=[]
        for index in range(12):
            ids=self.populate(index);self.preserve(index)
            before=self.book.reconcile();shared=self.sleeve.reconcile();counts=native_positions(self.hot,'pump')
            costs=execution_cost(self.book)
            self.assertTrue(archive.compact(self.book,self.sleeve,self.history))
            self.assertEqual(self.book.reconcile(),before);self.assertEqual(self.sleeve.reconcile(),shared)
            self.assertEqual(execution_cost(self.book),costs)
            now=native_positions(self.hot,'pump')
            for key in ('natural_entries','natural_settlements','natural_partial_realizations','natural_exits'):
                self.assertEqual(now[key],counts[key])
            self.assertEqual(self.book.db.execute('SELECT COUNT(*) FROM positions').fetchone()[0],0)
            self.assertEqual(self.sleeve.db.execute('SELECT COUNT(*) FROM sleeve_positions').fetchone()[0],0)
            self.assertEqual(self.sleeve.db.execute('SELECT COUNT(*) FROM sleeve_candidates').fetchone()[0],0)
            with patch('certification.campaign_state.active_window',return_value=self.window(index+1)):
                for identity in ids:
                    with self.assertRaises(ValueError):self.book.reserve(identity,100,999999,{})
                    with self.assertRaises(ValueError):self.sleeve.reserve(identity,strategy='survivor',amount=100,at=999999)
            for owner in (self.book,self.sleeve):owner.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            sizes.append(sum(p.stat().st_size for p in self.hot.glob('*.sqlite')))
        self.assertEqual(self.book.reconcile()['settled'],96)
        self.assertLessEqual(max(sizes[3:])-min(sizes[3:]),65536,sizes)
        print('Survivor economic churn: 12 windows, 96 settlements; hot bytes',sizes)

    def test_candidate_only_windows_and_delayed_retirement_refresh_empty_prefix(self):
        for index in range(6):
            for n in range(8):
                candidate=f'rejected:{index}:{n}';at=index*3600+n
                row=self.history.graduate(candidate,dict(at=at))
                self.sleeve.observe(candidate,strategy='survivor',at=at,state='rejected',evidence={},regime={})
                self.history.retire(row,expired_before=at+1)
            self.preserve(index)
            self.assertTrue(archive.compact(self.book,self.sleeve,self.history))
            self.assertEqual(self.sleeve.db.execute('SELECT COUNT(*) FROM sleeve_candidates').fetchone()[0],0)
            self.assertEqual(self.book.replay()['events'],0)
            self.assertEqual(self.book.reconcile()['cash'],1000)
        # No new ledger event: an already-recorded candidate ages out in History.
        row=self.history.graduate('later',dict(at=30000))
        self.sleeve.observe('later',strategy='survivor',at=30000,state='watching',evidence={},regime={})
        self.preserve(6)
        self.assertFalse(archive.compact(self.book,self.sleeve,self.history))
        self.history.retire(self.history.get('later'),expired_before=30001)
        self.preserve(7)
        self.assertTrue(archive.compact(self.book,self.sleeve,self.history))
        self.assertIsNone(self.sleeve.candidate('later'))

    def test_crash_between_native_and_sleeve_fold_recovers_once(self):
        ids=self.populate(0,count=2);self.preserve(0);before=self.book.reconcile();shared=self.sleeve.reconcile()
        with patch.object(archive,'_sleeve_commit',side_effect=SystemExit('between databases')),self.assertRaises(SystemExit):
            archive.compact(self.book,self.sleeve,self.history)
        self.assertEqual(self.book.reconcile(),before);self.assertEqual(self.sleeve.reconcile(),shared)
        self.book.close();self.book=PaperBook(self.hot/'paper.sqlite',run_id='run',lane='survivor',policy_hash='b',initial=1000)
        self.assertTrue(archive.compact(self.book,self.sleeve,self.history))
        self.assertFalse(archive.compact(self.book,self.sleeve,self.history))
        self.assertEqual(self.book.reconcile(),before);self.assertEqual(self.sleeve.reconcile(),shared)
        self.assertNotIn('retirement_pending',self.book._archive())

    def test_current_strategy_startup_tail_is_kept_during_survivor_retirement(self):
        self.populate(0,count=2);self.preserve(0)
        self.sleeve.reserve('current:new',strategy='current',amount=50,at=3600)
        before=self.sleeve.reconcile()
        self.assertTrue(archive.compact(self.book,self.sleeve,self.history))
        self.assertEqual(self.sleeve.reconcile(),before)
        self.assertEqual(self.sleeve.get('current:new')['held'],50)
        self.assertEqual(self.sleeve.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone()[0],1)

    def test_corrupted_pending_cross_book_receipt_fails_closed(self):
        self.populate(0,count=2);self.preserve(0)
        with patch.object(archive,'_book_commit',side_effect=SystemExit('plan committed')),self.assertRaises(SystemExit):
            archive.compact(self.book,self.sleeve,self.history)
        anchor=self.book._archive();anchor['retirement_pending']['scope']['through']+=1
        archive._save(self.book,anchor)
        before=self.book.reconcile();shared=self.sleeve.reconcile()
        with self.assertRaisesRegex(ValueError,'pending_corruption'):
            archive.compact(self.book,self.sleeve,self.history)
        self.assertEqual(self.book.reconcile(),before);self.assertEqual(self.sleeve.reconcile(),shared)

    def test_post_sleeve_commit_retry_and_native_rollback_keep_exact_totals(self):
        self.populate(0,count=2);self.preserve(0);before=self.book.reconcile();shared=self.sleeve.reconcile()
        save=archive._save
        def cut(owner,anchor):
            save(owner,anchor)
            if owner is self.book and anchor.get('retirement_receipt'):
                raise SystemExit('native fold before commit')
        with patch.object(archive,'_save',side_effect=cut),self.assertRaises(SystemExit):
            archive.compact(self.book,self.sleeve,self.history)
        self.assertEqual(self.book.db.execute('SELECT COUNT(*) FROM positions').fetchone()[0],2)
        self.assertEqual(self.book.reconcile(),before)
        original=archive._sleeve_commit
        def committed(*args):original(*args);raise SystemExit('sleeve committed before ack')
        with patch.object(archive,'_sleeve_commit',side_effect=committed),self.assertRaises(SystemExit):
            archive.compact(self.book,self.sleeve,self.history)
        self.assertTrue(archive.compact(self.book,self.sleeve,self.history))
        self.assertEqual(self.book.reconcile(),before);self.assertEqual(self.sleeve.reconcile(),shared)

    def test_active_partial_runner_retains_high_water_and_shared_reservation(self):
        from certification.survivor_commit import restore_risk
        self.populate(0,count=2)
        with patch('certification.campaign_state.active_window',return_value=self.window(0)):
            identity=issue('run:held');row=self.history.graduate('held',dict(at=100))
            self.sleeve.observe('held',strategy='survivor',at=100,state='qualified',evidence={},regime={})
            self.sleeve.reserve(identity,strategy='survivor',amount=100,at=100,candidate='held',generation=1,regime={})
            self.book.reserve(identity,100,100,{'candidate':'held'})
            with self.sleeve.commit_fence(identity):pass
            self.book.transition(identity,'filled',101,amount=100,tokens=100,evidence={'execution':{'gas':1}})
            self.book.transition(identity,'partial_harvest',102,amount=40,tokens=25,evidence={'execution':{'gas':1}})
            risk=restore_risk(self.book,identity);risk.update(high_water_bps=4000,high_at=102,tightened=True)
            self.book.transition(identity,'mark',103,amount=110,evidence={'risk_state':risk})
            row['position']=identity;row['state']='runner';self.history.save(row)
        self.preserve(0);before=self.book.reconcile();held=self.sleeve.get(identity)
        self.assertTrue(archive.compact(self.book,self.sleeve,self.history))
        self.assertEqual(restore_risk(self.book,identity),risk)
        self.assertEqual(self.book.reconcile(),before);self.assertEqual(self.sleeve.get(identity),held)
        self.assertEqual(self.history.get('held')['position'],identity)

    def test_current_candidate_and_unacknowledged_terminal_cannot_be_forgotten(self):
        ids=self.populate(0,count=2)
        row=self.history.graduate('still-relevant',dict(at=100));identity='legacy:keep'
        self.sleeve.observe(row['id'],strategy='survivor',at=100,state='watching',evidence={},regime={})
        self.preserve(0)
        self.assertTrue(archive.compact(self.book,self.sleeve,self.history))
        self.assertIsNotNone(self.sleeve.candidate('still-relevant'))
        self.populate(1,count=1);self.preserve(1)
        with self.sleeve.transaction():
            anchor=self.sleeve._archive();key=next(iter(anchor['positions']))
            anchor['positions'][key]['terminal_hash']='incorrect'
            self.sleeve.db.execute('UPDATE sleeve_positions SET body=? WHERE id=?',
                (__import__('json').dumps(anchor['positions'][key],sort_keys=True,separators=(',',':')),key))
            archive._save(self.sleeve,anchor)
        before=self.book.reconcile()
        with self.assertRaisesRegex(ValueError,'acknowledgement'):archive.compact(self.book,self.sleeve,self.history)
        self.assertEqual(self.book.reconcile(),before)
