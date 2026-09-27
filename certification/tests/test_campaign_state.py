"""State transport keeps actual Survivor history, partials and capital unchanged."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from certification import campaign_state as transfer
from certification.survivor_history import History
from certification.survivor_paper_book import PaperBook
from certification.sleeve_reservations import SleeveReservations
from certification.journal import digest


class CampaignStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.lanes=self.root/'lanes';self.run=self.root/'run'
        self.run.mkdir();self.capsule=self.root/'capsule'
        self.identity=dict(integration_sha='a'*40,implementation_hash='b'*64,
            source_manifest_hash='c'*64,policy_manifest_hash='d'*64,
            source_diff_hashes={lane:'e'*64 for lane in transfer.LANES},paper_only=True,live_money=False)
        self.window=dict(campaign_id='autonomous-fixture',index=0,workflow_run_id=1,
            native_run_id='original-paper-books',authorization_hash='f'*64)
        self.patch=patch.object(transfer,'identity',return_value=self.identity)
        self.patch.start();self.addCleanup(self.patch.stop)
        terminal={}
        for lane in transfer.LANES:
            folder=self.lanes/lane;folder.mkdir(parents=True)
            if lane in ('pump','pons'):
                folder=folder/('pump-survivor' if lane=='pump' else 'pons-selective-continuation-v1-cohort/pons-survivor')
                folder.mkdir(parents=True)
                h=History(folder/'history.sqlite',policy='frozen-'+lane)
                row=h.graduate('candidate',dict(at=0,identity='authenticated-graduation'))
                h.append(row['id'],through=3600,events=[],points=[(0,'100'),(3600,'110')],complete=True)
                row=h.get(row['id']);row.update(position='original-paper-books:position',state='runner');h.save(row)
                h.set_meta('discovery_cursor',100);h.close()
                book=PaperBook(folder/'paper.sqlite',run_id='original-paper-books',lane='survivor',policy_hash='frozen-'+lane,initial=1000)
                book.reserve(row['position'],100,1,{'qualified':True});book.transition(row['position'],'filled',2,amount=100,tokens=100)
                book.transition(row['position'],'partial_harvest',3500,amount=40,tokens=25)
                account=book.reconcile();book.close()
                sleeve=SleeveReservations(self.lanes/lane/'directional-sleeve.sqlite',lane=lane,capital=1000,
                    policies={'current':'frozen-current','survivor':'frozen-'+lane},cohort='autonomous-fixture')
                sleeve.reserve(row['position'],strategy='survivor',amount=100,at=1);sleeve.close()
                terminal[lane]=dict(verified=True,accounting=account,open_positions=1,durable_handoff=True)
            else:
                name='solana-dlmm-independent-v1-live.json' if lane=='meteora' else 'robinhood-ramses-extended-market-report.json'
                (folder/name).write_text(json.dumps({'explicit_offline_transport_fixture':True}))
                terminal[lane]=dict(verified=True,accounting={'open_positions':0},open_positions=0)
        for name in transfer.SHARED:
            if name.endswith('.sqlite'):
                with sqlite3.connect(self.run/name) as db:
                    db.execute('CREATE TABLE evidence(id PRIMARY KEY, hash)');db.execute("INSERT INTO evidence VALUES(1,'preserved')")
        self.terminal=dict(status='FINISHED',integration_sha=self.identity['integration_sha'],
            implementation_hash=self.identity['implementation_hash'],lanes={lane:dict(exit_code=0,
            accounting_reconciled=True,terminal_reconciliation=proof) for lane,proof in terminal.items()})
        self.body=transfer.seal(self.capsule,worktrees=self.lanes,run=self.run,
            window=self.window,terminal=self.terminal,expected_identity=self.identity)
        self.target=self.root/'successor';self.target_run=self.root/'successor-run'

    def restore(self,**changes):
        args=dict(expected_identity=self.identity,expected_state_hash=self.body['state_hash'],
            campaign_id=self.window['campaign_id'],prior_index=0,authorization_hash=self.window['authorization_hash'])
        args.update(changes)
        return transfer.restore(self.capsule,worktrees=self.target,run=self.target_run,**args)

    def claim(self, *, index=1):
        window=dict(index=index,mode='hourly' if index else 'smoke',seconds=3600 if index else 600,
            workflow_run_id=2,native_run_id=self.window['native_run_id'],entry_authority=True,
            nonce='a'*32,parent_state_hash=self.body['state_hash'] if index else None)
        previous=dict(index=0,state_hash=self.body['state_hash'],native_run_id=self.window['native_run_id'],
            workflow_run_id=1,discovery_window=self.body['discovery_window'],
            positions={lane:[] for lane in transfer.LANES}) if index else None
        return dict(schema='autonomous-paper-window-claim-v1',identity=self.identity,
            campaign_id=self.window['campaign_id'],authorization_hash=self.window['authorization_hash'],
            certificate=dict(self.identity,passed=True),window=window,previous=previous)

    def settle_fixture(self):
        for lane in ('pump','pons'):
            folder=self.lanes/lane/('pump-survivor' if lane=='pump' else 'pons-selective-continuation-v1-cohort/pons-survivor')
            book=PaperBook(folder/'paper.sqlite',run_id=self.window['native_run_id'],lane='survivor',
                policy_hash='frozen-'+lane,initial=1000)
            identity=self.window['native_run_id']+':position'
            book.transition(identity,'settled',4000,amount=90)
            position=book._load(identity)
            sleeve=SleeveReservations(self.lanes/lane/'directional-sleeve.sqlite',lane=lane,capital=1000,
                policies={'current':'frozen-current','survivor':'frozen-'+lane},cohort='autonomous-fixture')
            sleeve.release(identity,pnl=position['realized'],at=4000,terminal_hash=digest(position),native_verified=book.replay()['verified'])
            self.terminal['lanes'][lane]['terminal_reconciliation'].update(accounting=book.reconcile(),open_positions=0)
            book.close();sleeve.close()

    def test_history_crosses_four_hour_age_without_resetting_partial_or_capital(self):
        receipt=self.restore();self.assertFalse(receipt['entry_authority'])
        self.assertEqual(self.restore(),receipt)
        for lane in ('pump','pons'):
            folder=self.target/lane/('pump-survivor' if lane=='pump' else 'pons-selective-continuation-v1-cohort/pons-survivor')
            h=History(folder/'history.sqlite',policy='frozen-'+lane)
            h.append('candidate',through=14400,events=[],points=[(14400,'120')],complete=True)
            row=h.get('candidate')
            self.assertEqual(14400-row['graduation']['at'],14400)
            self.assertEqual(h.get_meta('discovery_cursor'),100)
            self.assertEqual(len(h.facts('candidate',14400)[0]),3);h.close()
            book=PaperBook(folder/'paper.sqlite',run_id='original-paper-books',lane='survivor',policy_hash='frozen-'+lane,initial=1000)
            self.assertEqual(book.reconcile(),self.body['accounting'][lane]['accounting'])
            p=book._load(row['position']);self.assertEqual((p['tokens'],p['basis'],p['realized']),(75,75,15))
            sleeve=SleeveReservations(self.target/lane/'directional-sleeve.sqlite',lane=lane,capital=1000,
                policies={'current':'frozen-current','survivor':'frozen-'+lane},cohort='autonomous-fixture')
            self.assertEqual(sleeve.reconcile()['reserved'],100)
            book.transition(row['position'],'settled',15000,amount=90)
            p=book._load(row['position'])
            sleeve.release(row['position'],pnl=p['realized'],at=15000,terminal_hash=digest(p),native_verified=book.replay()['verified'])
            self.assertEqual(sleeve.reconcile()['available'],1030)
            self.assertEqual(book.reconcile()['marked_equity'],1030)
            book.close();sleeve.close()

    def test_interrupted_install_resumes_exact_files_before_publishing_receipt(self):
        original=transfer.os.replace;calls=[]
        def crash(source,target):
            original(source,target);calls.append(str(target))
            if len(calls)==2:raise SystemExit('cut_after_second_file')
        with patch.object(transfer.os,'replace',side_effect=crash),self.assertRaises(SystemExit):self.restore()
        self.assertFalse((self.target_run/'restored-campaign-state.json').exists())
        receipt=self.restore();self.assertEqual(receipt['state_hash'],self.body['state_hash'])
        self.assertEqual(self.restore(),receipt)

    def test_changed_sha_policy_campaign_authorization_and_stale_window_rejected(self):
        for changes in (dict(expected_identity=dict(self.identity,integration_sha='b'*40)),
                        dict(expected_identity=dict(self.identity,policy_manifest_hash='e'*64)),
                        dict(campaign_id='wrong-campaign'),dict(authorization_hash='0'*64),dict(prior_index=1)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.restore(**changes)
            self.assertFalse(self.target_run.exists())

    def test_corrupt_source_or_existing_target_is_not_overwritten(self):
        self.restore()
        file=self.body['files'][0];path=self.target.joinpath(file['path'])
        if file['path'].startswith('shared/'):path=self.target_run.joinpath(*Path(file['path']).parts[1:])
        path.write_bytes(b'conflicting committed state')
        with self.assertRaisesRegex(ValueError,'collision'):self.restore()
        self.assertEqual(path.read_bytes(),b'conflicting committed state')
        source=self.capsule/'files'/self.body['files'][-1]['path'];source.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'file_hash'):self.restore()

    def test_untruthful_terminal_cannot_seal_a_successor(self):
        terminal=deepcopy(self.terminal);terminal['lanes']['pump']['unexpected_exit']=True
        with self.assertRaisesRegex(ValueError,'unreconciled'):
            transfer.seal(self.root/'bad',worktrees=self.lanes,run=self.run,
                window=self.window,terminal=terminal,expected_identity=self.identity)
        self.assertFalse((self.root/'bad').exists())

    def test_window_requires_exact_claim_before_installing_state(self):
        # An open predecessor must take the position-only path, never normal entry.
        claim=self.claim();claim['previous']['positions']['pump']=['original-paper-books:position']
        self.target_run.mkdir()
        with self.assertRaisesRegex(ValueError,'open_positions'):
            transfer.prepare_window(claim,worktrees=self.target,run=self.target_run,
                phase='hourly',seconds=3600,prior_state=self.capsule)
        self.assertFalse(self.target.exists())
        self.assertFalse((self.target_run/'autonomous-window-claim.json').exists())
        for field,value in (('mode','position'),('entry_authority',False),('seconds',1)):
            changed=self.claim();changed['window'][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'entry_authority'):
                transfer.prepare_window(changed,worktrees=self.target,run=self.target_run,
                    phase='hourly',seconds=3600,prior_state=self.capsule)
        initial=self.claim(index=0)
        bound=transfer.prepare_window(initial,worktrees=self.target,run=self.target_run,
            phase='smoke',seconds=600)
        self.assertEqual(bound['native_run_id'],self.window['native_run_id'])
        with patch.dict(os.environ,MM_AUTONOMOUS_WINDOW_CLAIM=str(self.target_run/'autonomous-window-claim.json'),
                        MM_CERTIFICATION_RUN_ID=bound['native_run_id']):
            self.assertEqual(transfer.active_window()['index'],0)
            with patch.dict(os.environ,MM_CERTIFICATION_RUN_ID='replacement-books'):
                with self.assertRaisesRegex(ValueError,'identity'):transfer.active_window()

    def test_sealed_native_exposure_cannot_be_hidden_by_a_flat_claim(self):
        self.target_run.mkdir()
        with self.assertRaisesRegex(ValueError,'native_exposure'):
            transfer.prepare_window(self.claim(),worktrees=self.target,run=self.target_run,
                phase='hourly',seconds=3600,prior_state=self.capsule)
        self.assertFalse(self.target.exists())

    def test_closed_window_reuses_native_identity_and_verified_restore_receipt(self):
        self.settle_fixture()
        self.capsule=self.root/'flat-capsule'
        self.body=transfer.seal(self.capsule,worktrees=self.lanes,run=self.run,
            window=self.window,terminal=self.terminal,expected_identity=self.identity)
        self.target_run.mkdir()
        bound=transfer.prepare_window(self.claim(),worktrees=self.target,run=self.target_run,
            phase='hourly',seconds=3600,prior_state=self.capsule)
        with patch.dict(os.environ,MM_AUTONOMOUS_STATE_RECEIPT=str(self.target_run/'restored-campaign-state.json'),
                        MM_CERTIFICATION_RUN_ID=bound['native_run_id']):
            self.assertEqual(transfer.restored_window()['window']['index'],1)
            with patch.dict(os.environ,MM_CERTIFICATION_RUN_ID='new-capital'):
                with self.assertRaisesRegex(ValueError,'authority'):transfer.restored_window()
        sleeve=SleeveReservations(self.target/'pons/directional-sleeve.sqlite',lane='pons',capital=1000,
            policies={'current':'frozen-current','survivor':'frozen-pons'},cohort='autonomous-fixture')
        self.assertEqual(sleeve.reconcile()['available'],1030);sleeve.close()


PONS_WINDOW = r'''
from contextlib import chdir
import json,os
from pathlib import Path
from unittest.mock import patch
from certification.tests.test_campaign_state import CampaignStateTests
from certification import campaign_state as transfer
from certification.robinhood.pons import save_cohort_checkpoint,recover_cohort
from certification.robinhood.plane import Plane
from robinhood_research import BoundaryError
t=CampaignStateTests();t.setUp()
try:
 t.settle_fixture()
 initial=t.claim(index=0);initial['window']['workflow_run_id']=1
 (t.run/'autonomous-window-claim.json').write_text(json.dumps(initial))
 cohort=t.lanes/'pons/pons-selective-continuation-v1-cohort'
 rows=cohort/'candidate-rows.jsonl';rows.write_text(json.dumps(dict(index=0,curve='original-curve'))+'\n')
 plane=t.run/'shared-robinhood-evidence.candidates.sqlite'
 result=dict(policy_hash='frozen',candidate_plane_path=str(plane),started_at=1,ended_at=2,
   native_archive_paths=dict(rows=str(Path(cohort.name)/rows.name)),rows=[dict(index=0,curve='original-curve')])
 with chdir(t.lanes/'pons'),patch.dict(os.environ,MM_AUTONOMOUS_WINDOW_CLAIM=str(t.run/'autonomous-window-claim.json'),
        MM_CERTIFICATION_RUN_ID=t.window['native_run_id']):
  save_cohort_checkpoint(result,100,'finalizing')
 p=Plane(plane);saved=p.checkpoint_read('pons_cohort');saved['owner']='previous-boot:1:1';p.checkpoint('pons_cohort',saved);p.close()
 with chdir(t.lanes/'pons'),patch.dict(os.environ,{},clear=True):
  try:recover_cohort(plane,'frozen')
  except BoundaryError as exc:assert str(exc)=='selective_completed_run_cannot_restart'
  else:raise AssertionError('ordinary rerun acquired entry authority')
 t.capsule=t.root/'flat';t.body=transfer.seal(t.capsule,worktrees=t.lanes,run=t.run,
   window=t.window,terminal=t.terminal,expected_identity=t.identity)
 t.target_run.mkdir();claim=t.claim()
 transfer.prepare_window(claim,worktrees=t.target,run=t.target_run,phase='hourly',seconds=3600,prior_state=t.capsule)
 restored=t.target_run/'shared-robinhood-evidence.candidates.sqlite'
 with chdir(t.target/'pons'),patch.dict(os.environ,
    MM_AUTONOMOUS_STATE_RECEIPT=str(t.target_run/'restored-campaign-state.json'),
    MM_CERTIFICATION_RUN_ID=t.window['native_run_id']):
  r=recover_cohort(restored,'frozen')
  assert r['rows']==result['rows'] and r['started_at']>2 and 'ended_at' not in r
  assert r['autonomous_predecessor']['workflow_run_id']==1
  p=Plane(restored);saved=p.checkpoint_read('pons_cohort');saved['autonomous_window']['index']=9;p.checkpoint('pons_cohort',saved);p.close()
  try:recover_cohort(restored,'frozen')
  except BoundaryError as exc:assert str(exc)=='selective_completed_window_identity'
  else:raise AssertionError('wrong checkpoint window accepted')
finally:t.doCleanups()
print('Pons completed checkpoint restores only under exact verified successor; rerun and stale-window reject')
'''


class NativeCampaignWindowTests(unittest.TestCase):
    def test_pons_completed_checkpoint_requires_verified_new_window(self):
        from certification.tests.test_survivor_candidate_progress import SurvivorCandidateProgressTests
        SurvivorCandidateProgressTests.run_native(self,PONS_WINDOW,lanes=('pons',))
