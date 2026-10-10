"""Explicit synthetic risk policy; no migration or activation of a runtime."""
from dataclasses import replace
from decimal import Decimal
import tempfile
import unittest
from meme_machine.shared_capital import CapitalError,RiskPolicy
from meme_machine.shared_capital.operational_candidate import PumpPonsCapital,ACTIVE_REGIMES,verify_two_family_plan
from tests.shared_capital_support import Harness,CONTRACTS


class PreparedCapitalTests(unittest.TestCase):
    def harness(self,policy=RiskPolicy()):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup)
        h=Harness(td.name,policy);h.authority.close()
        h.authority=PumpPonsCapital(h.path);self.addCleanup(h.close)
        def finish(round_id,requests):
            for r in ACTIVE_REGIMES:
                h.authority.seal(operation_id='seal:'+round_id+':'+r,round_id=round_id,
                    regime_name=r,request_ids=[q.request_id for q in requests if q.regime==r],at=h.at)
        h.finish_round=finish
        return h

    def test_shared_cash_can_fund_beyond_old_sleeve_without_enlarging_native_targets(self):
        h=self.harness();basis=Decimal(0)
        for i in range(21):
            requests,result=h.allocate([('pump_current',{'asset':'asset:'+str(i)})])
            q=requests[0];decision=result['decisions'][q.request_id]
            self.assertEqual(decision['basis'],'6.25')
            h.fill(q);basis+=Decimal(decision['basis'])
        self.assertEqual(basis,Decimal('131.25'))
        snap=h.check()
        self.assertEqual(Decimal(snap['capital']['realized_equity']),Decimal('500'))
        self.assertEqual(snap['capital']['actual_cash'],'368.75')
        self.assertIs(snap['capital']['conservation'],True)

    def test_paused_empty_manifests_survive_restart_but_active_silence_still_blocks(self):
        h=self.harness();a=h.authority
        a.open_round(operation_id='open:r',round_id='r',at=0,cutoff=0)
        before=a.snapshot();a.close();h.authority=PumpPonsCapital(h.path);a=h.authority
        self.assertEqual(before,a.snapshot())
        a.open_round(operation_id='open:r',round_id='r',at=0,cutoff=0)
        with self.assertRaisesRegex(CapitalError,'watermarks'):a.allocate(round_id='r',at=0)
        h.finish_round('r',[])
        result=a.allocate(round_id='r',at=0)
        self.assertEqual(result['decisions'],{})

    def test_paused_admissions_cannot_acquire_new_claims_or_block_pons(self):
        h=self.harness();a=h.authority
        before=a.snapshot()
        for r in ('meteora','ramses'):
            with self.assertRaisesRegex(CapitalError,'paused_family_capital_admission'):
                a.observe(operation_id='obs:'+r,at=0,regime_name=r,candidate_id='old',generation=1,status='QUALIFIED',economic_keys=['old'],evidence={},policy_hash=CONTRACTS[r]['policy_hash'])
            with self.assertRaisesRegex(CapitalError,'paused_family_capital_admission'):
                a.require_obligation(operation_id='risk:'+r,obligation_id=r,regime_name=r,amount_usd='1',at=0,proof_sha256='a'*64)
        self.assertEqual(a.snapshot(),before)
        requests,result=h.allocate([('pons_current',{})])
        self.assertEqual(result['decisions'][requests[0].request_id]['basis'],'6.25')

    def test_unapproved_sizing_and_adaptive_economics_fail_closed_on_restore(self):
        for policy in (replace(RiskPolicy(),sizing_basis='shared_realized_equity'),replace(RiskPolicy(),adaptive=True)):
            td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup)
            h=Harness(td.name,policy);h.close()
            with self.assertRaisesRegex(CapitalError,'fixed_native_equivalent_sizing_required'):PumpPonsCapital(h.path)
            with self.assertRaisesRegex(CapitalError,'fixed_native_equivalent_sizing_required'):verify_two_family_plan(h.plan)


class RuntimeIntegrationTests(unittest.TestCase):
    def fixture(self,policy=None,owners=True,*,new_epoch=False):
        import os,time
        from pathlib import Path
        from unittest.mock import patch
        from meme_machine.runtime.directional_sleeve import policies
        from meme_machine.runtime.usd_valuation import USDValue
        from meme_machine.shared_capital.runtime import RuntimeCapital
        from meme_machine.shared_capital.cutover import install
        from tests.shared_capital_support import legacy_fixture,empty_mapping
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup);root=Path(td.name)
        if not new_epoch:
            old=legacy_fixture(root/'portfolio.sqlite');old.close()
        mapping=empty_mapping()
        for family in ('pump','pons'):
            for strategy,strategy_policy in policies(family).items():
                r=family+('_survivor' if 'survivor' in strategy else '_current')
                mapping['contracts'][r]=dict(strategy_id=strategy,policy_hash=strategy_policy)
        from meme_machine.shared_capital.operational_candidate import prepare_plan
        if new_epoch:
            from meme_machine.portfolio_accounting import inception_receipt
            from meme_machine.operational.supervisor import identities
            from meme_machine.runtime.usd_valuation import utc
            from meme_machine.shared_capital.operational_candidate import initialize_new_epoch
            root=root/'new-1000'
            receipt=inception_receipt('offline-fixture-shared-1000',utc(0),'explicit-new-inception',starting_capital='1000.00',shared=True)
            ids=identities(receipt)
            plan=initialize_new_epoch(root,receipt,portfolio_identities=ids['pump'],lane_identities=ids,
                contracts=mapping['contracts'],policy=policy or RiskPolicy(sizing_basis='shared_realized_equity'))
        else:
            plan=prepare_plan(root/'portfolio.sqlite',mapping,policy=policy or RiskPolicy())
        prerequisites={k:True for k in ('writers_stopped','coherent_backup_verified','native_mapping_verified','recovery_verified','provider_proof_verified')}
        install(root,plan,approved_policy=plan['policy'],prerequisites=prerequisites)
        authority=RuntimeCapital(root/'shared-capital.sqlite');self.addCleanup(authority.close)
        now=int(time.time());token='offline-native-owner'
        if owners:
            for r in ACTIVE_REGIMES:authority.owner(r,token,os.getpid(),ready=True,at=now)
        value=USDValue('offline-native',3,Decimal('1'),now-1,now+100000,'offline-usd','e'*64)
        env=patch.dict(os.environ,{'MM_PORTFOLIO_ACCOUNTING_DB':str(root/'portfolio.sqlite'),
            'MM_DIRECTIONAL_SLEEVE_DB':str(root/'pump/directional-sleeve.sqlite'),
            'MM_DIRECTIONAL_COHORT_ID':plan['seed']['epoch_id'],'MM_LANE_PROCESS_INSTANCE':token})
        env.start();self.addCleanup(env.stop)
        p=patch('meme_machine.runtime.usd_valuation.native_reader',return_value=lambda at:value);p.start();self.addCleanup(p.stop)
        p=patch('meme_machine.runtime.usd_valuation.NativeValueReader',side_effect=lambda *args:lambda at:value);p.start();self.addCleanup(p.stop)
        return root,authority,now,plan

    def test_native_pump_shared_funding_exceeds_125_with_original_625_targets(self):
        from pathlib import Path
        from meme_machine.lanes.pump.paper_accounting import PaperBook
        from meme_machine.runtime.directional_sleeve import open_sleeve,policies
        from meme_machine.runtime.directional_continuation import native_sync
        root,a,now,_=self.fixture();(root/'pump').mkdir(exist_ok=True)
        strategy=next(s for s in policies('pump') if 'survivor' not in s)
        book=PaperBook(root/'pump/current.sqlite',run_id='pump-test',lane=strategy,
            policy_hash=policies('pump')[strategy],initial=125000);self.addCleanup(book.close)
        sleeve=open_sleeve('pump',125000);self.addCleanup(sleeve.close)
        for i in range(21):
            import time
            now=int(time.time())
            identity='pump-test:'+str(i)
            self.assertEqual(sleeve.sizing_basis(500)['target'],6250)
            sleeve.reserve(identity,strategy=strategy,amount=6250,at=now,asset='asset-'+str(i),
                funding_evidence=dict(qualification=dict(qualified=True,policy_hash=policies('pump')[strategy])))
            book.reserve(identity,6250,now,dict(qualified=True))
            book.transition(identity,'filled',now,amount=6250,tokens=100,evidence=dict(execution={'gas':0}))
            book.transition(identity,'mark',now,amount=6250)
            native_sync(book,sleeve,identity)
        self.assertEqual(book.reconcile()['initial'],125000)
        self.assertEqual(book.reconcile()['cash'],-6250) # signed family attribution
        self.assertTrue(book.replay()['verified'])
        state=a.snapshot();self.assertEqual(state['capital']['deployed_basis'],'131.25')
        self.assertEqual(state['capital']['actual_cash'],'368.75')
        self.assertTrue(state['capital']['conservation']);a.verify_replay()

    def test_legacy_authority_fenced_and_unused_rollback_preserves_epoch(self):
        from meme_machine.portfolio_accounting import PortfolioAccounting
        from meme_machine.shared_capital.cutover import rollback_unused
        root,a,now,plan=self.fixture()
        with self.assertRaisesRegex(RuntimeError,'legacy_funding_authority_retired'):PortfolioAccounting(root/'portfolio.sqlite')
        with self.assertRaisesRegex(CapitalError,'shared_compatible'):rollback_unused(root)

    def test_missing_active_manifest_blocks_grants_but_not_settlement(self):
        import os
        root,a,now,_=self.fixture()
        book,sleeve,identity=self.native_position(root,now)
        a.owner('pons_survivor','offline-native-owner',os.getpid(),ready=False,at=now)
        self.queue(a,'pump_current','blocked',now)
        with self.assertRaisesRegex(CapitalError,'missing_active_manifest'):a.drain(at=now)
        self.assertEqual(len(a.snapshot()['ledger']['reservations']),0)
        book.transition(identity,'settled',now+1,amount=6250)
        from meme_machine.runtime.directional_continuation import native_sync
        native_sync(book,sleeve,identity)
        self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),Decimal('500'))
        a.verify_replay()

    def queue(self,a,r,identity,now):
        from meme_machine.shared_capital import CapitalRequest,Valuation
        q=CapitalRequest(identity,a.snapshot()['epoch_id'],'inbox',r,'candidate:'+identity,1,'0'*64,
            '6.25','6.25','6.25','6.25','6.25','0','0',Valuation('test-value','e'*64,now-1,now+100),
            native_sizing=dict(realized_equity_units=125000,usd_per_native_unit='0.001',journal_sha256='e'*64))
        a.queue(q,native_id=identity,economic_keys=['asset:'+identity],
            evidence=dict(native_requested_units=6250,funding_deadline=now+5,qualified=True),
            policy_hash=a.snapshot()['ledger']['contracts'][r]['policy_hash'],token='offline-native-owner',at=now)
        return q

    def native_position(self,root,now,*,family='pump',survivor=False,identity='native-test:position'):
        import os
        from unittest.mock import patch
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.directional_sleeve import open_sleeve,policies
        from meme_machine.runtime.directional_continuation import native_sync
        (root/family).mkdir(exist_ok=True)
        p=patch.dict(os.environ,{'MM_DIRECTIONAL_SLEEVE_DB':str(root/family/'directional-sleeve.sqlite')})
        p.start();self.addCleanup(p.stop)
        strategy=next(s for s in policies(family) if ('survivor' in s)==survivor)
        book=PaperBook(root/family/(identity+'.sqlite'),run_id=identity.split(':')[0],lane=strategy,
            policy_hash=policies(family)[strategy],initial=125000);self.addCleanup(book.close)
        sleeve=open_sleeve(family,125000);self.addCleanup(sleeve.close)
        sleeve.reserve(identity,strategy=strategy,amount=6250,at=now,asset='asset:'+identity,
            funding_evidence=dict(qualified=True,policy_hash=policies(family)[strategy]))
        book.reserve(identity,6250,now,dict(qualified=True))
        book.transition(identity,'filled',now,amount=6250,tokens=100,evidence=dict(execution={'gas':0}))
        book.transition(identity,'mark',now,amount=6250);native_sync(book,sleeve,identity)
        return book,sleeve,identity

    def test_four_native_regimes_share_one_atomic_round_from_independent_connections(self):
        from concurrent.futures import ThreadPoolExecutor
        from meme_machine.shared_capital.runtime import RuntimeCapital
        root,a,now,_=self.fixture()
        def producer(r):
            client=RuntimeCapital(root/'shared-capital.sqlite')
            try:self.queue(client,r,r,now)
            finally:client.close()
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(producer,ACTIVE_REGIMES))
        a.close();a=RuntimeCapital(root/'shared-capital.sqlite');self.addCleanup(a.close)
        result=a.drain(at=now)
        self.assertEqual(set(result['decisions']),set(ACTIVE_REGIMES))
        self.assertTrue(all(v['basis']=='6.25' for v in result['decisions'].values()))
        self.assertEqual(Decimal(a.snapshot()['capital']['active_reservations']),Decimal('25'))
        round_value=next(reversed(a.snapshot()['ledger']['rounds'].values()))
        self.assertEqual(round_value['manifests']['meteora'],[]);self.assertEqual(round_value['manifests']['ramses'],[])
        a.verify_replay()

    def test_queued_deadline_is_preserved_and_expired_qualification_is_not_erased(self):
        _,a,now,_=self.fixture();self.queue(a,'pons_survivor','late',now)
        d=a.drain(at=now+6)['decisions']['late']
        self.assertEqual(d['reason'],'FUNDING_EVIDENCE_EXPIRED')
        self.assertEqual(a.snapshot()['lanes']['pons_survivor']['qualified'],1)
        self.assertEqual(a.snapshot()['lanes']['pons_survivor']['qualified_but_unfunded'],1)
        self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),500);a.verify_replay()

    def test_partial_profit_compounds_family_only_and_settlement_releases_cash(self):
        root,a,now,_=self.fixture();book,sleeve,identity=self.native_position(root,now,survivor=True)
        book.transition(identity,'partial_harvest',now+1,amount=2500,tokens=25)
        from meme_machine.runtime.directional_continuation import native_sync
        native_sync(book,sleeve,identity)
        self.assertEqual(Decimal(a.snapshot()['capital']['realized_equity']),Decimal('500.938'))
        self.assertEqual(sleeve.sizing_basis(500)['target'],6296)
        self.assertEqual(Decimal(a.snapshot()['capital']['deployed_basis']),Decimal('4.688'))
        book.transition(identity,'settled',now+2,amount=8000);native_sync(book,sleeve,identity)
        self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),Decimal('504.25'))
        self.assertEqual(Decimal(a.snapshot()['capital']['deployed_basis']),0)
        self.assertTrue(book.replay()['verified']);a.verify_replay()

    def test_native_crash_before_and_after_commit_and_duplicate_acknowledgement(self):
        from meme_machine.runtime.directional_sleeve import recover_pump_terminals
        from unittest.mock import patch
        root,a,now,_=self.fixture();book,sleeve,identity=self.native_position(root,now)
        boundary=book.portfolio
        client=boundary.client
        # Lose the reply after the native fill/settlement journal commits.
        with patch.object(client,'committed',side_effect=RuntimeError('lost_ack')):
            with self.assertRaisesRegex(RuntimeError,'lost_ack'):
                book.transition(identity,'settled',now+1,amount=7000)
        self.assertEqual(len(client.pending()),1)
        boundary.recover();boundary.prepared.clear();recover_pump_terminals(book)
        self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),Decimal('500.75'))
        self.assertEqual(len(client.pending()),0)
        boundary.recover();self.assertTrue(book.replay()['verified']);a.verify_replay()

    def test_unmaterialized_grant_and_queued_request_release_only_on_native_absence(self):
        from meme_machine.runtime.directional_sleeve import open_sleeve,policies
        root,a,now,_=self.fixture();q=self.queue(a,'pump_current','orphan',now);a.drain(at=now)
        self.queue(a,'pump_current','unallocated',now)
        sleeve=open_sleeve('pump',125000);self.addCleanup(sleeve.close)
        strategy=next(s for s in policies('pump') if 'survivor' not in s)
        with self.assertRaisesRegex(CapitalError,'native_replay_required'):
            sleeve.recover_unmaterialized({},strategy=strategy,verified=False)
        self.assertEqual(Decimal(a.snapshot()['capital']['active_reservations']),Decimal('6.25'))
        sleeve.recover_unmaterialized({},strategy=strategy,verified=True)
        self.assertEqual(a.snapshot()['ledger']['runtime_inbox'],{})
        self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),500);a.verify_replay()

    def test_pons_current_native_partial_settlement_and_replay_use_shared_authority(self):
        import os
        from unittest.mock import patch
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        from meme_machine.lanes.pons.evidence import Store,digest
        from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        root,a,now,_=self.fixture();(root/'pons').mkdir()
        with patch.dict(os.environ,{'MM_DIRECTIONAL_SLEEVE_DB':str(root/'pons/directional-sleeve.sqlite')}):
            path=root/'pons/trial.sqlite';store=Store(path);self.addCleanup(store.close)
            guard=CohortCapital(root/'pons/capital.sqlite',125000)
            paper=SelectivePaper(store,STRATEGY_NAMESPACE,125000,delay=1,natural_policy_hash=POLICY_HASH,on_commit=guard.observe)
            fixture=PartialAccountingTests();decision=fixture.features(now)
            guard.reserve('pons-native',6500,at=now,decision_hash=digest(decision),trial_path=path,
                native_reservation_intent=dict(market='m',amount=6250,gas_budget=250,features=decision,now=now,kind='natural'))
            paper.reserve('pons-native',market='m',amount=6250,gas_budget=250,now=now,features=decision)
            paper.advance('pons-native',now=now+1,action='entry',quote=fixture.quote(now+1,'buy',6250,1000))
            paper.advance('pons-native',now=now+2,action='exit_intent',exit_tokens=250)
            paper.advance('pons-native',now=now+3,action='exit',quote=fixture.quote(now+3,'sell',250,2000))
            paper.advance('pons-native',now=now+4,action='exit_intent')
            p=paper.advance('pons-native',now=now+5,action='exit',quote=fixture.quote(now+5,'sell',750,7000))
            guard.settle('pons-native',p,at=now+5)
            self.assertTrue(paper.accounting('pons-native')['replay_verified'])
            self.assertTrue(guard.reconcile()['cash_basis_conservation'])
            self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),Decimal('502.744'))
            self.assertEqual(a.snapshot()['capital']['deployed_basis'],'0');a.verify_replay()

    def test_staged_add_is_an_actual_hold_and_preserves_original_native_basis(self):
        from meme_machine.runtime.directional_continuation import BRIDGE_GATES,native_sync
        root,a,now,_=self.fixture();book,sleeve,identity=self.native_position(root,now,survivor=True)
        book.transition(identity,'partial_harvest',now,amount=3125,tokens=25);native_sync(book,sleeve,identity)
        # Marked exposure remains inside the illustrative test cap.
        book.transition(identity,'mark',now,amount=7000)
        state=dict(opened_at=now-1000,high_water_bps=10000,first_tail_crossed_at=now-900,
            original_basis=6250,realization_taken=True)
        facts=dict({gate:True for gate in BRIDGE_GATES},fresh_strategy_requalified=True,
            fresh_execution_requalified=True,after_cost_return_bps=7000)
        sleeve.reserve_scale(identity,amount=3125,original_basis=6250,at=now,request='winner-add',
            scale_state=state,scale_facts=facts)
        self.assertEqual(Decimal(a.snapshot()['capital']['active_reservations']),Decimal('3.125'))
        book.transition(identity,'scale_add',now,amount=3125,tokens=25,evidence=dict(request='winner-add'))
        native_sync(book,sleeve,identity);p=next(iter(a.snapshot()['ledger']['positions'].values()))
        self.assertEqual(p['original_native_basis'],6250);self.assertTrue(p['scale_committed'])
        self.assertEqual(Decimal(p['basis']),Decimal('7.813'));self.assertTrue(book.replay()['verified']);a.verify_replay()
        with self.assertRaisesRegex(ValueError,'scale_lifecycle_state'):
            sleeve.reserve_scale(identity,amount=1,original_basis=6250,at=now,request='second',scale_state=state,scale_facts=facts)

    def test_identical_cutover_and_unused_rollback_keep_original_epoch(self):
        from meme_machine.shared_capital.cutover import install,rollback_unused
        from meme_machine.shared_capital.runtime import selected
        from meme_machine.portfolio_accounting import PortfolioAccounting
        root,a,_,plan=self.fixture(owners=False)
        prerequisites={k:True for k in ('writers_stopped','coherent_backup_verified','native_mapping_verified','recovery_verified','provider_proof_verified')}
        install(root,plan,approved_policy=plan['policy'],prerequisites=prerequisites)
        self.assertEqual(a.verify_replay()['events'],1)
        rollback_unused(root);self.assertIsNone(selected(root/'portfolio.sqlite'))
        old=PortfolioAccounting(root/'portfolio.sqlite');self.addCleanup(old.close)
        self.assertEqual(old.snapshot()['receipt']['epoch_id'],plan['seed']['epoch_id'])

    def test_pons_survivor_and_dashboard_distinguish_shared_cash_from_sizing(self):
        from meme_machine.shared_capital.reporting import export,summary
        from dashboard.model import validate_export
        root,a,now,_=self.fixture();book,sleeve,_=self.native_position(root,now,family='pons',survivor=True)
        self.assertEqual(sleeve.sizing_basis(500)['target'],6250)
        projection=export(a);validated=validate_export(projection,a.snapshot()['ledger']['inception'],'canonical')
        details=validated['shared_capital']
        self.assertEqual(Decimal(details['free_cash']),Decimal('493.75'))
        self.assertEqual(Decimal(details['family_equivalent_equity']['pons']),125)
        self.assertEqual(details['paused_families'],{'meteora':'PAUSED','ramses':'PAUSED'})
        self.assertEqual(summary(a,now)['positions_by_lane']['pons'],1)
        self.assertTrue(book.replay()['verified']);a.verify_replay()

    def test_runtime_duplicate_identity_is_atomic_across_connections_with_changed_retry_clock(self):
        from concurrent.futures import ThreadPoolExecutor
        from meme_machine.shared_capital.runtime import RuntimeCapital
        root,a,now,_=self.fixture()
        def deliver(offset):
            other=RuntimeCapital(root/'shared-capital.sqlite')
            try:return other.command('same-event','runtime_publish',{},now+offset)
            finally:other.close()
        before=a.verify_replay()['events']
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(deliver,[0,1]))
        self.assertEqual(results[0],results[1]);self.assertEqual(a.verify_replay()['events'],before+1)
        with self.assertRaisesRegex(CapitalError,'conflicting_operation_identity'):
            a.command('same-event','runtime_publish',{'changed':True},now+2)

    def test_crash_after_scale_grant_before_local_hold_cannot_strand_actual_cash(self):
        from unittest.mock import patch
        from meme_machine.runtime.directional_continuation import BRIDGE_GATES,native_sync
        root,a,now,_=self.fixture();book,sleeve,identity=self.native_position(root,now,survivor=True)
        book.transition(identity,'partial_harvest',now,amount=3125,tokens=25);native_sync(book,sleeve,identity)
        book.transition(identity,'mark',now,amount=7000)
        state=dict(opened_at=now-1000,high_water_bps=10000,first_tail_crossed_at=now-900,
            original_basis=6250,realization_taken=True)
        facts=dict({g:True for g in BRIDGE_GATES},fresh_strategy_requalified=True,
            fresh_execution_requalified=True,after_cost_return_bps=7000)
        before=a.snapshot()['capital']['free_cash']
        with patch.object(sleeve,'_event',side_effect=RuntimeError('local_hold_interrupted')):
            with self.assertRaisesRegex(RuntimeError,'local_hold_interrupted'):
                sleeve.reserve_scale(identity,amount=3125,original_basis=6250,at=now,request='interrupted-add',
                    scale_state=state,scale_facts=facts)
        self.assertEqual(Decimal(a.snapshot()['capital']['active_reservations']),Decimal('3.125'))
        sleeve.recover_unmaterialized({identity:book._load(identity)},strategy=book.identity['lane'],verified=book.replay()['verified'])
        self.assertEqual(a.snapshot()['capital']['free_cash'],before);self.assertFalse(book._load(identity).get('scale_request'))
        a.verify_replay()

    def test_dashboard_refresh_is_read_only_and_keeps_original_valuation_expiry(self):
        from meme_machine.shared_capital.reporting import export
        from dashboard.model import validate_export
        root,a,now,_=self.fixture();book,_,_=self.native_position(root,now,survivor=True)
        before=a.verify_replay()['events'];first=export(a,at=now+10);later=export(a,at=now+20)
        validate_export(later,a.ledger()['inception'],'canonical')
        self.assertEqual(a.verify_replay()['events'],before)
        self.assertEqual(first['positions'][0]['mark'],later['positions'][0]['mark'])
        self.assertNotEqual(first['as_of'],later['as_of'])
        self.assertTrue(book.replay()['verified'])

    def test_operational_observer_and_recovery_read_actual_shared_pending_journals(self):
        from copy import deepcopy
        from unittest.mock import patch
        from meme_machine.operational.observation import observed_portfolio
        from meme_machine.operational.backup import state_identity
        from meme_machine.operational.acceptance import verify_recovery_identity
        root,a,now,plan=self.fixture();book,_,identity=self.native_position(root,now,survivor=True)
        before=state_identity(root);events=a.verify_replay()['events']
        self.assertEqual(before['sequence'],plan['source']['sequence']+events)
        observed=observed_portfolio(root,{})
        self.assertEqual(observed['state'],'CURRENT');self.assertEqual(observed['open_positions'],1)
        self.assertEqual(observed['funding_authority'],'SHARED');self.assertEqual(a.verify_replay()['events'],events)
        with patch.object(book.portfolio.client,'committed',side_effect=RuntimeError('lost_ack')):
            with self.assertRaisesRegex(RuntimeError,'lost_ack'):book.transition(identity,'settled',now+1,amount=7000)
        pending=state_identity(root);self.assertEqual(len(pending['pending_deliveries']),1)
        self.assertFalse(verify_recovery_identity(before,pending))
        book.portfolio.recover();after=state_identity(root)
        self.assertTrue(verify_recovery_identity(before,after));a.verify_replay()
        corrupt=deepcopy(after);corrupt['replayed_state']['positions']={}
        with self.assertRaisesRegex(ValueError,'recovery_lost_position'):verify_recovery_identity(before,corrupt)


if __name__=='__main__':unittest.main()
