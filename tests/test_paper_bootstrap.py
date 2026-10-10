"""Offline startup/admission/finite-exposure boundaries; no genuine evidence."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from decimal import Decimal
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from meme_machine.operational.admission import available,configure,decision,require_normal
from meme_machine.operational.bounded_provider import Budget,LIMITS
from meme_machine.shared_capital.model import CapitalError
from meme_machine.shared_capital.runtime import RuntimeCapital,process_identity
from tests import test_pump_pons_capital_preparation as native_tests


class AdmissionTests(unittest.TestCase):
    fixture=native_tests.RuntimeIntegrationTests.fixture
    queue=native_tests.RuntimeIntegrationTests.queue
    native_position=native_tests.RuntimeIntegrationTests.native_position

    def scope(self,a,now,root,*,arm=True):
        from tests.test_position_continuation import envelope,proof
        from meme_machine.operational.bounded_provider import PhaseBudget
        # The provider and accounting scopes share the same original start.
        # Fixture setup can cross a wall-clock second under a full suite.
        with patch('time.time',return_value=now):
            budget=Budget.create(root/'bootstrap-test.sqlite',continuation=envelope())
        data=dict(mode='OBSERVATION',run_id='offline-test',pid=os.getpid(),
            process_start=process_identity(os.getpid()),provider_db=str(budget.path),continuation_envelope=envelope())
        a.command('observe','runtime_admission',data,now)
        if arm:a.command('arm','runtime_admission',dict(data,mode='BOOTSTRAP',continuation_ready=proof()),now)
        return PhaseBudget(budget.path),data

    def test_observation_denies_funding_without_changing_cash_or_qualification(self):
        from meme_machine.runtime.directional_sleeve import open_sleeve,policies
        from meme_machine.shared_capital.native_sleeve import FundingDenied
        root,a,now,_=self.fixture();self.scope(a,now,root,arm=False)
        sleeve=open_sleeve('pump',125000);self.addCleanup(sleeve.close)
        strategy=next(s for s in policies('pump') if 'survivor' not in s)
        candidate=sleeve.observe('candidate',strategy=strategy,at=now,state='qualified',evidence={'qualified':True},regime={})
        with self.assertRaisesRegex(FundingDenied,'observation_only'):
            sleeve.reserve('blocked',strategy=strategy,amount=6250,at=now,candidate='candidate',generation=candidate['generation'])
        self.assertEqual(sleeve.candidate('candidate')['state'],'qualified')
        self.assertEqual(Decimal(a.ledger()['cash']),Decimal('500'));self.assertFalse(a.ledger()['positions']);a.verify_replay()

    def test_four_qualified_regimes_compete_for_one_unchanged_atomic_grant(self):
        from meme_machine.shared_capital.operational_candidate import ACTIVE_REGIMES
        root,a,now,_=self.fixture();self.scope(a,now,root)
        for r in ACTIVE_REGIMES:self.queue(a,r,r,now)
        def allocate(_):
            client=RuntimeCapital(root/'shared-capital.sqlite')
            try:return client.drain(at=now)
            finally:client.close()
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(allocate,range(2)))
        state=a.ledger();granted=[r for r in state['requests'].values() if r['status']=='RESERVED']
        self.assertEqual(len(granted),1);self.assertEqual(granted[0]['decision']['basis'],'6.25')
        self.assertEqual(len(state['observations']),4);self.assertEqual(state['runtime_admission']['gross_reserved'],'6.25')
        a.verify_replay()

    def test_authentic_fixture_book_mark_and_settlement_work_after_admission_closes(self):
        from meme_machine.runtime.directional_continuation import native_sync
        root,a,now,_=self.fixture();budget,data=self.scope(a,now,root)
        book,sleeve,identity=self.native_position(root,now)
        budget.bootstrap.change(reason='offline-budget-stop',check=False)
        book.transition(identity,'mark',now+1,amount=6250)
        book.transition(identity,'settled',now+2,amount=6250);native_sync(book,sleeve,identity)
        self.assertEqual(Decimal(a.snapshot()['capital']['actual_cash']),Decimal('500'))
        self.assertTrue(book.replay()['verified']);a.verify_replay()
        # This is a fixture, never a production certificate.
        with self.assertRaisesRegex(Exception,'combined_position_and_candidate'):require_normal()

    def test_dead_supervisor_and_clock_expiry_close_only_new_exposure(self):
        root,a,now,_=self.fixture();self.scope(a,now,root)
        state=a.ledger();scope=state['runtime_admission']
        self.assertEqual(available(state,scope['funding_until']), 'bootstrap_funding_deadline')
        with patch('meme_machine.shared_capital.runtime.process_identity',side_effect=OSError):
            self.assertEqual(available(state,now,live=True),'bootstrap_supervisor_not_running')
        # Deterministic replay does not depend on the original PID still living.
        with patch('meme_machine.shared_capital.runtime.process_identity',side_effect=OSError):a.verify_replay()

    def test_operational_client_cannot_omit_the_funding_scope(self):
        root,a,now,_=self.fixture()
        with patch.dict(os.environ,{'MM_OPERATIONAL_PHASE':'continuous'}):
            with self.assertRaisesRegex(CapitalError,'operational_funding_scope_required'):
                self.queue(a,'pump_current','missing-scope',now)
        self.assertFalse(a.ledger().get('runtime_inbox'))

    def test_bootstrap_requires_sixty_healthy_seconds_and_all_three_frontiers(self):
        from meme_machine.operational.supervisor import Supervisor
        root,a,now,_=self.fixture();budget,data=self.scope(a,now,root,arm=False)
        service=Supervisor(root,offline=True,admission='BOOTSTRAP')
        service.provider_budget=budget;service.shared_capital=a;service.run_id=data['run_id']
        service.admission_data=data;service.ready_since=None;service.ready_frontiers={};service.bootstrap_armed=False
        def healthy(slot):
            from tests.test_position_continuation import healthy as base
            health,portfolio,rss=base()
            health['providers']['evidence']['frontiers']=[dict(scope='program:pump',slot=slot),dict(scope='program:pumpswap',slot=slot)]
            health['active_evidence']=dict(pons_canonical_cursor=slot)
            return health,portfolio,rss
        t=budget.started
        with patch('meme_machine.operational.acceptance.observe',return_value=healthy(1)),patch('time.monotonic',return_value=t):
            service.bootstrap_tick()
        with patch('meme_machine.operational.acceptance.observe',return_value=healthy(2)),patch('time.monotonic',return_value=t+59):
            service.bootstrap_tick();self.assertFalse(service.bootstrap_armed)
        with patch('meme_machine.operational.acceptance.observe',return_value=healthy(1)),patch('time.monotonic',return_value=t+60):
            service.bootstrap_tick();self.assertFalse(service.bootstrap_armed)
        with patch('meme_machine.operational.acceptance.observe',return_value=healthy(2)),patch('time.monotonic',return_value=t+61):
            service.bootstrap_tick()
        with patch('meme_machine.operational.acceptance.observe',return_value=healthy(3)),patch('time.monotonic',return_value=t+121):
            service.bootstrap_tick();self.assertTrue(service.bootstrap_armed)
        self.assertEqual(a.ledger()['runtime_admission']['mode'],'BOOTSTRAP')
        self.assertFalse(a.ledger()['positions'])
        with patch('meme_machine.operational.acceptance.observe',side_effect=ValueError('health-failure')):
            service.bootstrap_tick()
        self.assertFalse(service.stop_requested)
        self.assertEqual(available(a.ledger(),now,live=True),'observation_only_funding_closed')
        a.verify_replay()

    def test_restart_observation_does_not_replenish_a_used_claim(self):
        root,a,now,_=self.fixture();_,data=self.scope(a,now,root)
        self.native_position(root,now)
        a.command('restart-observation','runtime_admission',dict(data,run_id='restart'),now+1)
        before=deepcopy(a.ledger()['runtime_admission'])
        with self.assertRaisesRegex(CapitalError,'unused_observation_run'):
            a.command('restart-arm','runtime_admission',dict(data,mode='BOOTSTRAP',run_id='restart'),now+1)
        self.assertEqual(a.ledger()['runtime_admission'],before);a.verify_replay()

    def test_capital_allowance_never_truncates_strategy_size(self):
        root,a,now,_=self.fixture();self.scope(a,now,root)
        state=a.ledger();state['runtime_admission']['gross_reserved']='24'
        state.setdefault('runtime_native_requests',{})['pump:first']='req';state['native_aliases']['pump:first']='pump:n1'
        result=decision(state,dict(request_id='req'),dict(status='RESERVED',basis='6.25',total='6.25'),now)
        self.assertEqual(result['reason'],'bootstrap_gross_capital_limit')
        self.assertEqual(state['runtime_admission']['gross_reserved'],'24')

    def test_observation_cutover_keeps_provider_proof_false_and_legacy_fenced(self):
        from meme_machine.shared_capital.cutover import install
        from meme_machine.shared_capital.operational_candidate import prepare_plan
        from tests.shared_capital_support import legacy_fixture,empty_mapping
        from meme_machine.portfolio_accounting import PortfolioAccounting
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);old=legacy_fixture(root/'portfolio.sqlite');old.close()
            from meme_machine.shared_capital import RiskPolicy
            plan=prepare_plan(root/'portfolio.sqlite',empty_mapping(),policy=RiskPolicy())
            proof={k:True for k in ('writers_stopped','coherent_backup_verified','native_mapping_verified','recovery_verified')}
            proof['provider_proof_verified']=False
            with self.assertRaisesRegex(CapitalError,'unverified_cutover'):
                install(root,plan,approved_policy=plan['policy'],prerequisites=proof)
            marker=install(root,plan,approved_policy=plan['policy'],prerequisites=proof,observation_only=True)
            self.assertIs(marker['prerequisites']['provider_proof_verified'],False)
            client=RuntimeCapital(root/'shared-capital.sqlite')
            try:
                self.assertEqual(client.ledger()['runtime_admission']['mode'],'OBSERVATION')
                self.assertEqual(Decimal(client.ledger()['cash']),Decimal('500'));client.verify_replay()
            finally:client.close()
            with self.assertRaisesRegex(RuntimeError,'legacy_funding_authority_retired'):PortfolioAccounting(root/'portfolio.sqlite')


class ProviderBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.budget=Budget.create(Path(self.tmp.name)/'limits.sqlite')

    def test_independent_clients_count_batches_and_retries_before_dispatch(self):
        def attempt(_):
            Budget(self.budget.path).reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',
                [dict(method='getTokenLargestAccounts'),dict(method='getSlot')])
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(attempt,range(8)))
        state=self.budget.snapshot()
        self.assertEqual(int(state['rpc_cu']),8*3020);self.assertEqual(int(state['http_attempts']),8)
        self.assertEqual(int(state['rpc_elements']),16)
        self.assertEqual(Budget(self.budget.path).snapshot(),state)
        with self.assertRaises(FileExistsError):Budget.create(self.budget.path)

    def test_unknown_or_writing_method_has_no_dispatch_allowance(self):
        with self.assertRaises(BaseException):
            self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='sendTransaction')])
        self.assertEqual(self.budget.snapshot()['rpc_cu'],'0')

    def test_rpc_limit_refuses_next_attempt_and_preserves_consumption(self):
        self.budget.change(dict(rpc_cu=LIMITS['rpc_cu']))
        with self.assertRaises(BaseException):
            self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        self.assertEqual(int(self.budget.snapshot()['rpc_cu']),LIMITS['rpc_cu'])
        self.assertEqual(self.budget.snapshot()['http_attempts'],'0')

    def test_shutdown_reservation_and_received_bytes_are_never_free(self):
        reserve=self.budget.stream_open('yellowstone')
        reserved=int(self.budget.snapshot()['native_reserved'])
        self.budget.native('yellowstone',1024,token=reserve)
        self.budget.stream_close(reserve,transport='yellowstone',unread_possible=True)
        state=self.budget.snapshot()
        self.assertEqual(int(state['native_bytes']),1024);self.assertEqual(int(state['native_uncertain_bytes']),reserved)
        self.assertEqual(state['native_reserved'],'0')
        second=self.budget.stream_open('yellowstone')
        self.budget.change(dict(native_bytes=LIMITS['native_stop_bytes']-1024-reserved-1),check=False)
        with self.assertRaises(BaseException):self.budget.native('yellowstone',1024,token=second)
        with self.assertRaises(BaseException):self.budget.stream_open('yellowstone')

    def test_wall_limit_and_host_restart_fail_closed(self):
        # Exact boundary without host-dependent floating-point cancellation.
        with patch('meme_machine.operational.bounded_provider.time.monotonic',return_value=100.):
            budget=Budget.create(Path(self.tmp.name)/'exact-expiry.sqlite')
        with patch('meme_machine.operational.bounded_provider.time.monotonic',return_value=1900.):
            with self.assertRaises(BaseException):budget.admission()
        self.assertEqual(budget.snapshot()['reason'],'bounded_run_wall_limit')
        with patch('meme_machine.operational.bounded_provider.Path.read_text',return_value='different-host-boot'):
            with self.assertRaises(BaseException):self.budget.admission()
        self.assertEqual(self.budget.snapshot()['reason'],'bounded_run_host_restarted')

    def test_received_shutdown_tail_consumes_its_reserve_without_double_counting(self):
        from engineering.solana_capacity.proof_limits import MAX_FRAME
        token=self.budget.stream_open('yellowstone')
        self.budget.change(reason='offline-stop',check=False)
        with self.assertRaises(BaseException):self.budget.native('yellowstone',MAX_FRAME,token=token)
        self.budget.stream_close(token,unread_possible=True)
        self.budget.stream_close(token,unread_possible=True)
        row=self.budget.snapshot()
        self.assertEqual(int(row['native_bytes']),MAX_FRAME)
        self.assertEqual(int(row['native_uncertain_bytes']),MAX_FRAME)
        self.assertEqual(row['native_reserved'],'0')

    def test_physical_boundary_refuses_dispatch_when_budget_is_exhausted(self):
        import urllib.request
        import grpc
        from meme_machine.lanes.pons import provider
        from meme_machine import solana_selective_source as source
        from meme_machine.operational.bounded_provider import install
        from unittest.mock import MagicMock
        opener=MagicMock()
        with patch.dict(os.environ,{'MM_BOUNDED_PROVIDER_DB':str(self.budget.path)}),\
                patch('urllib.request.build_opener',return_value=opener),\
                patch('urllib.request.urlopen'),patch.object(provider,'urlopen'),\
                patch.object(grpc.aio,'secure_channel'),patch.object(source,'connect'):
            install();self.budget.change(dict(rpc_cu=LIMITS['rpc_cu']))
            request=urllib.request.Request('https://solana-mainnet.g.alchemy.com/v2/offline',
                data=b'{"jsonrpc":"2.0","id":1,"method":"getSlot","params":[]}')
            with self.assertRaises(BaseException):urllib.request.urlopen(request)
            opener.open.assert_not_called()
