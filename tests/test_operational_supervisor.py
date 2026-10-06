"""Offline native process ownership, real SQLite replay and crash delivery."""
from decimal import Decimal
from contextlib import closing
import hashlib,json,os,signal,subprocess,sys,tempfile,time,unittest
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
        self.service.initialize();self.addCleanup(lambda: self.service.lock.close() if self.service.lock else None)
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

    def _check_missing_canonical_restart(self, *, empty_replacement):
        book,_,_=open_native(self.root,'pump',self.service.epoch)
        native=open_position(book,'pump',self.service.epoch,int(time.time()))
        close(book,'pump')
        with self.service.account() as account:
            original=account.snapshot()
        self.service.lock.close();self.service.lock=None
        database=self.root/'portfolio.sqlite'
        preserved=self.root/'preserved-portfolio.sqlite'
        database.rename(preserved)
        # The journal alone must prevent reseeding, before any projection has
        # been published. An empty replacement is equally unsafe to activate.
        (self.root/'OFFLINE_ONLY.json').unlink()
        before={p:hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (self.root/'pump').glob('*.sqlite*')}
        if empty_replacement:
            with closing(PortfolioAccounting(database)) as account:
                self.assertIsNone(account.binding())
        failed=Supervisor(self.root,offline=True)
        try:
            with self.assertRaisesRegex(RuntimeError,'existing_epoch_state_requires_bound_portfolio'):
                failed.initialize()
        finally:
            if failed.lock:failed.lock.close()
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in before})
        if empty_replacement:
            with closing(PortfolioAccounting(database)) as account:
                self.assertIsNone(account.binding())
                self.assertEqual(account.db.execute('SELECT COUNT(*) FROM portfolio_events').fetchone()[0],0)
            database.rename(self.root/'preserved-empty-portfolio.sqlite')
        else:self.assertFalse(database.exists())
        preserved.rename(database)
        restarted=Supervisor(self.root,offline=True)
        restarted.initialize();self.addCleanup(restarted.lock.close)
        self.assertEqual(restarted.epoch,self.service.epoch)
        with restarted.account() as account:self.assertEqual(account.snapshot(),original)
        recovered,rows,_=open_native(self.root,'pump',restarted.epoch)
        self.assertEqual([r['id'] for r in rows],[native])
        close(recovered,'pump')

    def test_missing_canonical_portfolio_cannot_replace_native_epoch(self):
        self._check_missing_canonical_restart(empty_replacement=False)

    def test_unbound_canonical_portfolio_cannot_replace_native_epoch(self):
        self._check_missing_canonical_restart(empty_replacement=True)

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

    def test_restarted_child_cannot_inherit_predecessor_readiness(self):
        from types import SimpleNamespace
        path=self.root/'pump'/'health.json';path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(dict(pid=100,process_instance='previous',phase='MANAGING',
            reconciled=True,native_lifecycle='old-lifecycle')))
        self.service.processes={'pump':SimpleNamespace(pid=200,poll=lambda:None)}
        self.service.process_instances={'pump':'replacement'}
        self.service.publish()
        row=json.loads((self.root/'health.json').read_text())['lanes']['pump']
        self.assertEqual(row['phase'],'STARTING')
        self.assertFalse(row.get('reconciled',False))
        self.assertNotIn('native_lifecycle',row)
        # PID reuse still cannot confer predecessor readiness.
        path.write_text(json.dumps(dict(pid=200,process_instance='previous',phase='MANAGING',reconciled=True)))
        self.service.publish()
        self.assertEqual(json.loads((self.root/'health.json').read_text())['lanes']['pump']['phase'],'STARTING')
        path.write_text(json.dumps(dict(pid=200,process_instance='replacement',phase='MANAGING',reconciled=True)))
        self.service.publish()
        self.assertTrue(json.loads((self.root/'health.json').read_text())['lanes']['pump']['reconciled'])

    def test_malformed_child_health_cannot_stop_supervisor_or_confer_readiness(self):
        from types import SimpleNamespace
        path=self.root/'pump'/'health.json'
        self.service.processes={'pump':SimpleNamespace(pid=200,poll=lambda:None)}
        self.service.process_instances={'pump':'replacement'}
        for body in (b'[]',b'null',b'"ready"',b'123',b'\xff',b'{'):
            with self.subTest(body=body):
                path.write_bytes(body)
                self.service.publish()
                row=json.loads((self.root/'health.json').read_text())['lanes']['pump']
                self.assertEqual(row['phase'],'STARTING')
                self.assertFalse(row.get('reconciled',False))
                self.assertEqual(row['pid'],200)

    def test_child_health_read_is_bounded_before_json_decode(self):
        from io import BytesIO
        from types import SimpleNamespace
        path=self.root/'pump'/'health.json'
        self.service.processes={'pump':SimpleNamespace(pid=200,poll=lambda:None)}
        self.service.process_instances={'pump':'replacement'}
        payload=b'{"pid":200,"process_instance":"replacement","phase":"MANAGING","reconciled":true,"padding":"'+b'x'*300000+b'"}'
        reads=[]
        class Tracked(BytesIO):
            def read(self,size=-1):
                reads.append(size)
                return super().read(size)
        original=Path.open
        def opened(target,*args,**kwargs):
            if target==path:return Tracked(payload)
            return original(target,*args,**kwargs)
        with patch.object(Path,'open',opened):self.service.publish()
        self.assertEqual(reads,[262145])
        row=json.loads((self.root/'health.json').read_text())['lanes']['pump']
        self.assertEqual(row['phase'],'STARTING')
        self.assertFalse(row.get('reconciled',False))

    def test_publication_failure_cannot_stop_lane_or_supervisor(self):
        from meme_machine.operational.lane import health
        with patch('meme_machine.operational.lane._atomic_json',side_effect=OSError('read_only_dashboard')):
            health(self.root,'pump','MANAGING')
        with patch('meme_machine.operational.supervisor._atomic_json',side_effect=OSError('read_only_dashboard')):
            self.service.publish()

    def test_health_contains_this_cycles_reconciled_portfolio_without_extended_validity(self):
        self.service.portfolio_observation={'state':'UNAVAILABLE','timestamp':0}
        self.service.publish()
        health=json.loads((self.root/'health.json').read_text())
        with self.service.account() as account:
            exported=account._export(account.snapshot())
        facts=health['portfolio_observation']
        self.assertEqual(facts['state'],'CURRENT')
        self.assertEqual(facts['sequence'],exported['sequence'])
        self.assertEqual(facts['valid_until'],exported['valid_until'])
        self.assertEqual(facts['reconciliation'],'PASS')
        self.assertEqual(facts['marked_equity'],'500.00')
        # The next cycle must publish its own facts too, rather than reuse this
        # cycle's sequence or extend an old mark's validity to the health time.
        previous=facts['sequence'];self.service.publish()
        latest=json.loads((self.root/'health.json').read_text())['portfolio_observation']
        with self.service.account() as account:
            self.assertEqual(latest['sequence'],account.snapshot()['sequence'])
        self.assertGreater(latest['sequence'],previous)

    def test_failed_incremental_delivery_keeps_original_native_and_usd_position(self):
        book,_,_=open_native(self.root,'pump',self.service.epoch)
        native=open_position(book,'pump',self.service.epoch,int(time.time()))
        original=book._load(native)
        with self.service.account() as account:usd=account.snapshot()['positions']
        prepare=book.portfolio.client.prepare
        def failed_add(*args,**kwargs):
            if kwargs.get('kind')=='rebalance':raise RuntimeError('incremental_commit_failed')
            return prepare(*args,**kwargs)
        with patch.object(book.portfolio.client,'prepare',side_effect=failed_add):
            with self.assertRaisesRegex(RuntimeError,'incremental_commit_failed'):
                book.transition(native,'scale_add',int(time.time()),amount=3000000000,tokens=500,evidence={'request':'one-add'})
        self.assertEqual(book._load(native),original)
        with self.service.account() as account:
            self.assertEqual(account.snapshot()['positions'],usd)
            self.assertFalse(account.snapshot()['reservations'])
        close(book,'pump')


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
                self.assertTrue(all(row['exit_code']==0 for row in final['lanes'].values()),
                    {'lanes':final['lanes'],'offline_log':(root/'test.log').read_text()[-8000:]})
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

    def _check_single_shutdown_signal(self, *, timeout):
        from types import SimpleNamespace
        events=[]
        def child(pid):
            calls=[0]
            def wait(*,timeout):
                calls[0]+=1;events.append(('wait',pid))
                if calls[0]==1 and pid==11 and fail_wait:
                    raise subprocess.TimeoutExpired('fixture-lane',timeout)
                return 0
            return SimpleNamespace(pid=pid,poll=lambda:None,wait=wait)
        fail_wait=timeout
        service=Supervisor('/unused-fixture',offline=True)
        service.processes={'pump':child(11),'pons':child(22)}
        def send(pid,signum):events.append((signum,pid))
        with patch('meme_machine.operational.supervisor.os.killpg',side_effect=send):
            service.stop_lanes()
        # Both lanes receive their cooperative stop before waiting for either.
        # A second SIGTERM could kill CPython after it restores the handler.
        self.assertEqual(events[:2],[(signal.SIGTERM,11),(signal.SIGTERM,22)])
        self.assertEqual([e for e in events if e[0]==signal.SIGTERM],
                         [(signal.SIGTERM,11),(signal.SIGTERM,22)])
        self.assertEqual([e for e in events if e[0]==signal.SIGKILL],
                         [(signal.SIGKILL,11)] if timeout else [])

    def test_parallel_shutdown_sends_one_term_to_each_lane(self):
        self._check_single_shutdown_signal(timeout=False)

    def test_shutdown_timeout_escalates_once_without_repeating_term(self):
        self._check_single_shutdown_signal(timeout=True)

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
