"""Offline native process ownership, real SQLite replay and crash delivery."""
from decimal import Decimal
from contextlib import closing
import json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch

from meme_machine.operational.supervisor import Supervisor,validate_environment,SOURCE_ROOT
from meme_machine.operational.offline import open_native,open_position,close
from meme_machine.portfolio_accounting import PortfolioAccounting,LANES,digest
from meme_machine.runtime.portfolio import NativePortfolio
from meme_machine.runtime.usd_valuation import ValuationUnavailable,utc


class NativeDeliveryRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.service=Supervisor(self.root,offline=True)
        self.service.initialize();self.addCleanup(self.service.lock.close)
        for lane in LANES:(self.root/lane).mkdir()
        self.env=patch.dict(os.environ,{'MM_PAPER_EPOCH':self.service.epoch})
        self.env.start();self.addCleanup(self.env.stop)

    def test_four_native_commits_recover_lost_shared_ack_once(self):
        for lane in LANES:
            with self.subTest(lane=lane):
                book,_,_=open_native(self.root,lane,self.service.epoch)
                original=book.portfolio.flush
                calls=[0]
                def fail_entry_ack():
                    calls[0]+=1
                    if calls[0]==2:raise RuntimeError('simulated_process_loss_after_native_commit')
                    return original()
                with patch.object(book.portfolio,'flush',side_effect=fail_entry_ack):
                    with self.assertRaisesRegex(RuntimeError,'simulated_process_loss'):
                        open_position(book,lane,self.service.epoch,int(time.time()))
                close(book,lane)
                recovered,rows,_=open_native(self.root,lane,self.service.epoch)
                self.assertEqual(len(rows),1)
                self.assertFalse(recovered.portfolio.client.pending())
                recovered.portfolio.recover();recovered.portfolio.recover()
                close(recovered,lane)
        with self.service.account() as account:
            state=account.snapshot()
            self.assertEqual(len(state['positions']),4)
            self.assertEqual(len(state['reservations']),0)
            self.assertTrue(account._reconcile(state)['checks']['cash_basis_conservation'])

    def test_uncommitted_native_reserve_releases_usd_without_provider(self):
        book,_,_=open_native(self.root,'pump',self.service.epoch)
        client=book.portfolio.client
        client.prepare('missing',event_key='lost-reserve',journal_hash='f'*64,kind='reserve',at=utc(time.time()),data={'amount':'6.25'})
        with patch.object(book.portfolio,'value_reader',side_effect=AssertionError('no provider for reservation recovery')):
            book.portfolio.recover();book.portfolio.recover()
        with self.service.account() as account:
            self.assertEqual(account.snapshot()['available'],Decimal('500.00'))
            self.assertFalse(account.snapshot()['reservations'])
        close(book,'pump')

    def test_meteora_native_cancel_releases_shared_hold_during_price_outage(self):
        book,_,_=open_native(self.root,'meteora',self.service.epoch)
        native=book.identity();book.append(native,'reserve',dict(amount=100000000,pool='fixture'))
        with patch.object(book.portfolio,'value_reader',side_effect=ValuationUnavailable('provider_outage')):
            self.assertEqual(book.recover_unfilled_reservations(),[native])
            self.assertEqual(book.recover_unfilled_reservations(),[])
        with self.service.account() as account:self.assertEqual(account.snapshot()['available'],Decimal('500'))

    def test_duplicate_delivery_survives_checkpoint(self):
        client=NativePortfolio(self.root/'portfolio.sqlite','pump')
        fact=dict(event_key='reserve',journal_hash='e'*64,kind='reserve',at=utc(time.time()),data={'amount':'6.25'})
        client.deliver('native',**fact)
        with self.service.account() as account:account.compact()
        result=client.deliver('native',**fact)
        self.assertTrue(result['idempotent'])
        with self.service.account() as account:self.assertEqual(account._reconcile(account.snapshot())['reserved'],Decimal('6.25'))

    def test_publication_failure_cannot_stop_lane_or_supervisor(self):
        from meme_machine.operational.lane import health
        with patch('meme_machine.operational.lane._atomic_json',side_effect=OSError('read_only_dashboard')):
            health(self.root,'pump','MANAGING')
        with patch('meme_machine.operational.supervisor._atomic_json',side_effect=OSError('read_only_dashboard')):
            self.service.publish()


class ProcessSupervisor(unittest.TestCase):
    def wait_health(self,root,predicate):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            try:
                value=json.loads((root/'health.json').read_text())
                if predicate(value):return value
            except (OSError,ValueError):pass
            time.sleep(.05)
        self.fail('mocked supervisor did not reach required health')

    def test_four_process_crash_restart_same_exposure_sigterm_and_second_start(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);log=(root/'test.log').open('w')
            command=[sys.executable,'-m','meme_machine.operational','offline','--state-root',td,'--seconds','90']
            process=subprocess.Popen(command,cwd=SOURCE_ROOT,stdout=log,stderr=log)
            try:
                self.wait_health(root,lambda h:len(h['lanes'])==4 and all(r.get('native_lifecycle') for r in h['lanes'].values()))
                with closing(PortfolioAccounting(root/'portfolio.sqlite',wait_for_writer=True)) as account:
                    initial=set(account.snapshot()['positions'])
                for lane in LANES:
                    health=json.loads((root/'health.json').read_text());old=health['lanes'][lane]['pid']
                    os.kill(old,signal.SIGKILL)
                    recovered=self.wait_health(root,lambda h:h['lanes'][lane]['pid']!=old and h['lanes'][lane].get('reconciled') is True and h['lanes'][lane].get('native_lifecycle'))
                    self.assertGreaterEqual(recovered['lanes'][lane]['restarts'],1)
                process.send_signal(signal.SIGTERM);self.assertEqual(process.wait(timeout=20),0)
                final=json.loads((root/'health.json').read_text())
                self.assertTrue(all(row['exit_code']==0 for row in final['lanes'].values()))
                again=subprocess.run(command[:-1]+['2'],cwd=SOURCE_ROOT,stdout=log,stderr=log,timeout=25)
                self.assertEqual(again.returncode,0)
                with closing(PortfolioAccounting(root/'portfolio.sqlite',wait_for_writer=True)) as account:
                    state=account.snapshot();self.assertEqual(set(state['positions']),initial)
                    self.assertEqual(len(initial),4);self.assertFalse(state['reservations'])
                    self.assertTrue(account.verify_archive()['verified'])
                    self.assertTrue(state['receipt']['epoch_id'].startswith('offline-fixture-'))
            finally:
                if process.poll() is None:process.terminate();process.wait(timeout=20)
                log.close()

    def test_paper_boundary_and_missing_anchor_create_no_epoch(self):
        with self.assertRaisesRegex(ValueError,'PAPER_only'):validate_environment(offline=True,environ={'MM_MODE':'LIVE'})
        with self.assertRaisesRegex(ValueError,'wallet'):validate_environment(offline=True,environ={'WALLET_PRIVATE_KEY':'forbidden-fixture'})
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'never-created'
            with self.assertRaisesRegex(ValuationUnavailable,'USDG/USD'):Supervisor(root).initialize()
            self.assertFalse(root.exists())

    def test_runtime_imports_have_no_historical_certification_dependency(self):
        code='import sys;from meme_machine.operational.supervisor import identities;identities();from meme_machine.operational import offline;from meme_machine.lanes.pump import runner;from meme_machine.lanes.pons import pons_selective_cohort;from meme_machine.lanes.meteora import runner;from meme_machine.lanes.ramses import ramses_extended_test;assert not any(n=="certification" or n.startswith("certification.") for n in sys.modules)'
        self.assertEqual(subprocess.run([sys.executable,'-c',code],cwd=SOURCE_ROOT).returncode,0)
