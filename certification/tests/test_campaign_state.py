"""State transport keeps actual Survivor history, partials and capital unchanged."""
from copy import deepcopy
import json
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
