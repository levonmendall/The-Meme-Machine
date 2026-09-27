"""Raw sleeve history is preserved before bounded hot-prefix replacement."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from certification.archive_native import copy_snapshot
from certification.sleeve_reservations import SleeveReservations

class SleevePreservedCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'directional-sleeve.sqlite'
        self.args=dict(lane='pump',capital=1000,policies={'current':'a','survivor':'b'},cohort='fixture')
        self.book=SleeveReservations(self.path,**self.args);self.addCleanup(lambda:self.book.close())
    def observe(self,n):
        return self.book.observe('candidate',strategy='survivor',at=n,state='qualified',evidence={'at':n},regime={'original':True})
    def snapshot(self,n=0):
        path=self.root/('preserved-'+str(n)+'.sqlite');rows=[]
        copy_snapshot(self.path,path,rows)
        self.assertNotIn('error_type',rows[0])
        return path,dict(schema='preserved-native-prefix-v1',snapshot_sha256=rows[0]['sha256'],
            snapshot_name='pump/directional-sleeve.sqlite',state_hash=str(n).zfill(64),
            artifact={'digest':'sha256:'+'a'*64},campaign_id='fixture-campaign',window_index=n)
    def test_checkpoint_keeps_generation_capital_terminal_dedup_and_newer_rows(self):
        row=self.observe(1)
        self.book.reserve('held',strategy='current',amount=100,at=1)
        with self.book.commit_fence('held'):pass
        source,authority=self.snapshot()
        self.observe(2) # A newer write is not in the preserved prefix.
        before=self.book.reconcile();latest=self.book.candidate('candidate')
        self.assertTrue(self.book._compact_preserved(source,authority))
        self.assertEqual(self.book.reconcile(),before);self.assertEqual(self.book.candidate('candidate'),latest)
        self.assertEqual(self.book.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone()[0],1)
        self.assertFalse(self.book._compact_preserved(source,authority))
        self.book.close();self.book=SleeveReservations(self.path,**self.args)
        self.assertEqual(self.book.reconcile(),before)
        self.assertEqual(self.observe(3)['generation'],row['generation']+2)
        self.book.release('held',pnl=10,at=3,terminal_hash='native',native_verified=True)
        terminal=self.book.reconcile();source,authority=self.snapshot(1)
        self.book._compact_preserved(source,authority)
        self.book.release('held',pnl=10,at=3,terminal_hash='native',native_verified=True)
        self.assertEqual(self.book.reconcile(),terminal)
        with self.assertRaisesRegex(ValueError,'terminal_reservation_reused'):
            self.book.reserve('held',strategy='current',amount=100,at=4)
        with self.assertRaisesRegex(ValueError,'duplicate_settlement_conflict'):
            self.book.release('held',pnl=11,at=3,terminal_hash='native',native_verified=True)
        self.assertEqual(terminal['available'],1010)
    def test_interrupted_prefix_replacement_rolls_back_anchor_and_delete_trigger(self):
        self.observe(1);source,authority=self.snapshot();before=self.book.reconcile();original=self.book.reconcile;calls=[]
        def cut():
            calls.append(True)
            if len(calls)==2:raise SystemExit('before checkpoint commit')
            return original()
        with patch.object(self.book,'reconcile',side_effect=cut):
            with self.assertRaises(SystemExit):self.book._compact_preserved(source,authority)
        self.assertEqual(self.book.reconcile(),before)
        self.assertIsNone(self.book._archive())
        with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):
            self.book.db.execute('DELETE FROM sleeve_journal')
        self.assertTrue(self.book._compact_preserved(source,authority))
    def test_wrong_snapshot_or_prefix_is_rejected_without_state_change(self):
        self.observe(1);source,authority=self.snapshot();before=self.book.reconcile()
        with self.assertRaisesRegex(ValueError,'snapshot_identity'):
            self.book._compact_preserved(source,dict(authority,snapshot_sha256='b'*64))
        other=SleeveReservations(self.root/'foreign',**self.args)
        other.observe('different',strategy='survivor',at=1,state='watching',evidence={},regime={})
        other.close();rows=[];conflict=self.root/'conflict'
        copy_snapshot(self.root/'foreign',conflict,rows)
        with self.assertRaisesRegex(ValueError,'prefix_conflict'):
            self.book._compact_preserved(conflict,dict(authority,snapshot_sha256=rows[0]['sha256']))
        self.assertEqual(self.book.reconcile(),before)
    def test_real_controller_restore_compacts_on_open_and_rejects_missing_preservation(self):
        from certification.tests.test_campaign_state import CampaignStateTests
        from certification import campaign_state as transfer
        fixture=CampaignStateTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.target_run.mkdir();claim=fixture.claim()
        for lane in ('pump','pons'):
            claim['previous']['positions'][lane]=['original-paper-books:position']
            claim['window']['positions'][lane]=['original-paper-books:position']
        claim['previous']['artifact']={'digest':'sha256:'+'a'*64}
        transfer.prepare_window(claim,worktrees=fixture.target,run=fixture.target_run,
            phase='hourly',seconds=3600,prior_state=fixture.capsule)
        with patch.dict(os.environ,MM_AUTONOMOUS_STATE_RECEIPT=str(fixture.target_run/'restored-campaign-state.json'),
                        MM_CERTIFICATION_RUN_ID=fixture.window['native_run_id']):
            args=dict(lane='pump',capital=1000,policies={'current':'frozen-current','survivor':'frozen-pump'},cohort='autonomous-fixture')
            path=fixture.target/'pump/directional-sleeve.sqlite'
            sleeve=SleeveReservations(path,**args)
            self.assertEqual(sleeve.reconcile()['reserved'],100)
            self.assertEqual(sleeve.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone()[0],0)
            self.assertEqual(sleeve._archive()['authority']['state_hash'],fixture.body['state_hash'])
            sleeve.close()
            sleeve=SleeveReservations(path,**args);self.assertEqual(sleeve.reconcile()['reserved'],100);sleeve.close()
            claim['previous']['artifact']={}
            (fixture.target_run/'autonomous-window-claim.json').write_text(json.dumps(claim))
            with self.assertRaisesRegex(ValueError,'preservation_authority'):SleeveReservations(path,**args)
    def test_seven_day_fixed_hot_set_has_bounded_prefix_and_preserves_every_raw_window(self):
        hot=[];hashes=[]
        self.book.reserve('held',strategy='current',amount=100,at=0)
        with self.book.commit_fence('held'):pass
        for hour in range(168):
            for tick in range(200):self.observe(hour*200+tick)
            before=self.book.reconcile();source,authority=self.snapshot(hour)
            hashes.append(authority['snapshot_sha256'])
            self.book._compact_preserved(source,authority)
            self.assertEqual(self.book.reconcile(),before)
            self.assertEqual(self.book.db.execute('SELECT COUNT(*) FROM sleeve_journal').fetchone()[0],0)
            self.book.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            hot.append(self.path.stat().st_size)
            self.book.close();self.book=SleeveReservations(self.path,**self.args)
        self.assertEqual(len(set(hashes)),168)
        self.assertEqual(self.book.candidate('candidate')['generation'],168*200)
        self.assertEqual(self.book.reconcile()['reserved'],100)
        self.assertLessEqual(max(hot[4:])-min(hot[4:]),65536)
        self.assertEqual(self.book.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        print('168-hour sleeve component: observations',168*200,'hot bytes',min(hot[4:]),max(hot[4:]),'preserved snapshots',len(hashes))
