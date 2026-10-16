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
        reservation=dict(asset='asset:'+identity,funding_evidence=dict(qualified=True,policy_hash=policies(family)[strategy]))
        if survivor:
            from tests.shared_rally_support import observe_survivor
            observed=observe_survivor(sleeve,strategy,'asset:'+identity,now)
            reservation.update(candidate=observed['id'],generation=observed['generation'],regime=observed['regime'])
        sleeve.reserve(identity,strategy=strategy,amount=6250,at=now,**reservation)
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

    def test_failed_local_scale_hold_compensates_shared_grant_exactly_once(self):
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
        self.assertEqual(Decimal(a.snapshot()['capital']['active_reservations']),Decimal(0))
        self.assertEqual(a.snapshot()['capital']['free_cash'],before)
        events=a.verify_replay()['events']
        sleeve.recover_unmaterialized({identity:book._load(identity)},strategy=book.identity['lane'],verified=book.replay()['verified'])
        self.assertEqual(a.verify_replay()['events'],events)
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


    def _grant_test_sleeve(self,root,family):
        from pathlib import Path
        from unittest.mock import patch
        import os
        from meme_machine.runtime.directional_sleeve import open_sleeve
        (root/family).mkdir(exist_ok=True)
        setting=patch.dict(os.environ,{'MM_DIRECTIONAL_SLEEVE_DB':str(root/family/'directional-sleeve.sqlite')})
        setting.start();self.addCleanup(setting.stop)
        sleeve=open_sleeve(family,125000);self.addCleanup(sleeve.close)
        return sleeve

    def _grant_test_regime(self,candidate,now,*,policy_hash):
        from meme_machine.runtime.rally_cycle import build_cycle
        cycle=build_cycle(candidate=candidate,venue='offline-native-venue',
            chain='synthetic-offline',pool='synthetic-pool',policy_hash=policy_hash,
            input_version='synthetic-canonical-history-v1',
            graduation=dict(at=now-12000,native_receipt='authenticated-offline-fixture'),peak_at=now-10000,
            reset_at=now-8000,base_start=now-7000,base_end=now-1000,breakout_at=now-60,decision_at=now,
            evidence_id='offline-canonical-rally',authoritative=True,complete=True,minimum_base_seconds=3600)
        return dict(at=now,base_id='first-base',rally_cycle=cycle)

    def test_rejected_survivor_same_regime_never_leaves_global_grant(self):
        from meme_machine.runtime.directional_sleeve import policies
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.directional_continuation import native_sync
        for family in ('pump','pons'):
            with self.subTest(family=family):
                root,a,now,_=self.fixture();sleeve=self._grant_test_sleeve(root,family)
                strategy=next(s for s in policies(family) if 'survivor' in s)
                candidate='survivor-repeat:'+family;prior_regime=self._grant_test_regime(candidate,now,
                    policy_hash=policies(family)[strategy])
                observed=sleeve.observe(candidate,strategy=strategy,at=now,state='qualified',
                    evidence={'qualified':True},regime=prior_regime)
                prior_regime=observed['regime']
                identity=family+':first'
                sleeve.reserve(identity,strategy=strategy,amount=6250,at=now,candidate=candidate,
                    generation=observed['generation'],regime=prior_regime)
                book=PaperBook(root/family/'survivor-native.sqlite',run_id=family,lane=strategy,
                    policy_hash=policies(family)[strategy],initial=125000)
                self.addCleanup(book.close)
                book.reserve(identity,6250,now,dict(qualified=True))
                book.transition(identity,'filled',now,amount=6250,tokens=100,evidence=dict(execution={'gas':0}))
                book.transition(identity,'mark',now,amount=6250)
                native_sync(book,sleeve,identity)
                self.assertEqual(Decimal(a.snapshot()['capital']['active_reservations']),Decimal(0))
                book.transition(identity,'settled',now+1,amount=6250)
                from meme_machine.runtime.directional_sleeve import native_terminal
                native_terminal(sleeve,identity,book._load(identity),now+1,verified=book.replay()['verified'])
                self.assertEqual(sleeve.get(identity)['status'],'settled')
                self.assertEqual(Decimal(a.snapshot()['capital']['active_reservations']),Decimal(0))
                second=family+':second'
                observed=sleeve.observe(candidate,strategy=strategy,at=now+2,state='qualified',
                    evidence={'qualified':True},regime=dict(prior_regime,at=now+2))
                with self.assertRaisesRegex(ValueError,'same_survivor_regime'):
                    sleeve.reserve(second,strategy=strategy,amount=6250,at=now+2,candidate=candidate,
                        generation=observed['generation'],regime=observed['regime'])
                self.assertIsNone(sleeve.get(second))
                self.assertEqual(Decimal(a.snapshot()['capital']['active_reservations']),Decimal(0))
                self.assertNotIn(family+':'+second,a.ledger()['runtime_native_requests'])
                a.verify_replay()

    def test_native_same_asset_fence_precedes_shared_grant(self):
        from unittest.mock import patch
        from meme_machine.runtime.directional_sleeve import policies
        root,a,now,_=self.fixture();sleeve=self._grant_test_sleeve(root,'pump')
        strategy=next(s for s in policies('pump') if 'survivor' not in s)
        sleeve.reserve('old',strategy=strategy,amount=6250,at=now,asset='identical-mint',
            funding_evidence=dict(qualified=True))
        before=a.snapshot()['capital']['active_reservations']
        with patch.object(sleeve,'_grant',wraps=sleeve._grant) as grant:
            with self.assertRaisesRegex(ValueError,'same_asset_exposure'):
                sleeve.reserve('new',strategy=strategy,amount=6250,at=now,asset='identical-mint',
                    funding_evidence=dict(qualified=True))
            self.assertEqual(grant.call_count,0)
        self.assertEqual(a.snapshot()['capital']['active_reservations'],before)
        a.verify_replay()

    def test_native_failure_after_global_grant_cancels_and_reconciles(self):
        from unittest.mock import patch
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.runtime.directional_sleeve import policies
        root,a,now,_=self.fixture();sleeve=self._grant_test_sleeve(root,'pons')
        strategy=next(s for s in policies('pons') if 'survivor' not in s)
        with patch.object(SleeveReservations,'reserve',side_effect=ValueError('injected_native_rejection')):
            with self.assertRaisesRegex(ValueError,'injected_native_rejection'):
                sleeve.reserve('reject-now',strategy=strategy,amount=6250,at=now,asset='rejected',
                    funding_evidence=dict(qualified=True))
        state=a.ledger();key='pons:reject-now';req_id=state['runtime_native_requests'][key]
        self.assertIsNone(sleeve.get('reject-now'))
        self.assertEqual(state['requests'][req_id]['status'],'CANCELLED')
        self.assertEqual(Decimal(a.snapshot()['capital']['active_reservations']),Decimal(0))
        self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),Decimal(500))
        a.verify_replay()

    def test_failed_cancellation_retains_funding_until_verified_recovery(self):
        from unittest.mock import patch
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.runtime.directional_sleeve import policies
        root,a,now,_=self.fixture();sleeve=self._grant_test_sleeve(root,'pump')
        strategy=next(s for s in policies('pump') if 'survivor' not in s)
        original=sleeve.authority.command
        def fail_cancel(op,action,data,at):
            if action=='runtime_compensate':raise OSError('injected_cancel_storage_failure')
            return original(op,action,data,at)
        with patch.object(sleeve.authority,'command',side_effect=fail_cancel):
            with patch.object(SleeveReservations,'reserve',side_effect=ValueError('injected_native_rejection')):
                with self.assertRaisesRegex(CapitalError,'reconciliation_required'):
                    sleeve.reserve('needs-recovery',strategy=strategy,amount=6250,at=now,asset='orphan',
                        funding_evidence=dict(qualified=True))
        state=a.ledger();req_id=state['runtime_native_requests']['pump:needs-recovery']
        self.assertEqual(state['requests'][req_id]['status'],'RESERVED')
        self.assertEqual(Decimal(a.snapshot()['capital']['active_reservations']),Decimal('6.25'))
        # Only startup with verified native absence can resolve an interrupted cancellation.
        sleeve.recover_unmaterialized(set(),strategy=strategy,verified=True)
        self.assertEqual(a.ledger()['requests'][req_id]['status'],'CANCELLED')
        self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),Decimal(500))
        a.verify_replay()

    def test_supersession_after_grant_cancels_exact_request(self):
        from unittest.mock import patch
        from meme_machine.runtime.directional_sleeve import policies
        root,a,now,_=self.fixture();sleeve=self._grant_test_sleeve(root,'pump')
        strategy=next(s for s in policies('pump') if 'survivor' in s)
        regime=self._grant_test_regime('candidate',now,policy_hash=policies('pump')[strategy])
        observed=sleeve.observe('candidate',strategy=strategy,at=now,state='qualified',evidence={'qualified':True},regime=regime)
        regime=observed['regime']
        original=sleeve._grant
        def supersede(*args,**kwargs):
            grant=original(*args,**kwargs)
            sleeve.observe('candidate',strategy=strategy,at=now+1,state='qualified',evidence={'qualified':True,'new':True},regime=regime)
            return grant
        with patch.object(sleeve,'_grant',side_effect=supersede):
            with self.assertRaisesRegex(ValueError,'superseded_reservation'):
                sleeve.reserve('superseded',strategy=strategy,amount=6250,at=now,candidate='candidate',generation=1,regime=regime)
        req_id=a.ledger()['runtime_native_requests']['pump:superseded']
        self.assertEqual(a.ledger()['requests'][req_id]['status'],'CANCELLED')
        self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),Decimal(500));a.verify_replay()

    def test_lost_grant_reply_after_native_fill_preserves_single_position(self):
        from unittest.mock import patch
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.directional_sleeve import policies
        from meme_machine.runtime.directional_continuation import native_sync
        root,a,now,_=self.fixture();sleeve=self._grant_test_sleeve(root,'pump')
        strategy=next(s for s in policies('pump') if 'survivor' not in s)
        book=PaperBook(root/'pump/racing.sqlite',run_id='race',lane=strategy,
            policy_hash=policies('pump')[strategy],initial=125000);self.addCleanup(book.close)
        original=sleeve._grant
        def fill_before_reply(*args,**kwargs):
            grant=original(*args,**kwargs);sleeve._grant_receipt=grant
            SleeveReservations.reserve(sleeve,'race:one',strategy=strategy,amount=6250,at=now,asset='racing-asset')
            book.reserve('race:one',6250,now,dict(qualified=True))
            book.transition('race:one','filled',now,amount=6250,tokens=100,evidence=dict(execution={'gas':0}))
            book.transition('race:one','mark',now,amount=6250);native_sync(book,sleeve,'race:one')
            raise RuntimeError('lost_grant_reply_after_fill')
        with patch.object(sleeve,'_grant',side_effect=fill_before_reply):
            with self.assertRaisesRegex(RuntimeError,'lost_grant_reply_after_fill'):
                sleeve.reserve('race:one',strategy=strategy,amount=6250,at=now,asset='racing-asset',funding_evidence={'qualified':True})
        req_id=a.ledger()['runtime_native_requests']['pump:race:one']
        self.assertEqual(a.ledger()['requests'][req_id]['status'],'CONSUMED')
        self.assertEqual(Decimal(a.snapshot()['capital']['deployed_basis']),Decimal('6.25'))
        self.assertEqual(len(a.ledger()['positions']),1)
        self.assertEqual(sleeve.reserve('race:one',strategy=strategy,amount=6250,at=now,asset='racing-asset',
            funding_evidence={'qualified':True})['id'],'race:one')
        self.assertTrue(book.replay()['verified']);a.verify_replay()

    def test_committed_native_obligation_cannot_be_compensated_from_local_absence(self):
        from unittest.mock import patch
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.directional_sleeve import policies
        root,a,now,_=self.fixture();sleeve=self._grant_test_sleeve(root,'pump')
        strategy=next(s for s in policies('pump') if 'survivor' not in s)
        book=PaperBook(root/'pump/native-obligation.sqlite',run_id='pending',lane=strategy,
            policy_hash=policies('pump')[strategy],initial=125000);self.addCleanup(book.close)
        original=sleeve._grant
        def commit_before_reply(*args,**kwargs):
            original(*args,**kwargs)
            book.reserve('pending:one',6250,now,dict(qualified=True))
            raise RuntimeError('lost_native_reservation_reply')
        with patch.object(sleeve,'_grant',side_effect=commit_before_reply):
            with self.assertRaisesRegex(CapitalError,'reconciliation_required'):
                sleeve.reserve('pending:one',strategy=strategy,amount=6250,at=now,asset='pending-asset',funding_evidence={'qualified':True})
        req_id=a.ledger()['runtime_native_requests']['pump:pending:one']
        self.assertEqual(a.ledger()['requests'][req_id]['status'],'COMMITTED')
        self.assertEqual(Decimal(a.snapshot()['capital']['pending_authoritative_commitments']),Decimal('6.25'))
        sleeve.recover_unmaterialized({'pending:one':book._load('pending:one')},strategy=strategy,verified=True)
        self.assertEqual(a.ledger()['requests'][req_id]['status'],'COMMITTED');a.verify_replay()

    def test_compensation_lost_reply_replay_is_idempotent(self):
        from unittest.mock import patch
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.runtime.directional_sleeve import policies
        root,a,now,_=self.fixture();sleeve=self._grant_test_sleeve(root,'pump')
        strategy=next(s for s in policies('pump') if 'survivor' not in s)
        original=sleeve.authority.command
        def lose_reply(op,action,data,at):
            result=original(op,action,data,at)
            if action=='runtime_compensate':raise OSError('lost_compensation_reply')
            return result
        with patch.object(sleeve.authority,'command',side_effect=lose_reply):
            with patch.object(SleeveReservations,'reserve',side_effect=ValueError('native_rejected')):
                with self.assertRaisesRegex(CapitalError,'reconciliation_required'):
                    sleeve.reserve('lost:one',strategy=strategy,amount=6250,at=now,asset='lost',funding_evidence={'qualified':True})
        req_id=a.ledger()['runtime_native_requests']['pump:lost:one']
        self.assertEqual(a.ledger()['requests'][req_id]['status'],'CANCELLED')
        count=a.verify_replay()['events'];sleeve._compensate_failed_reservation('lost:one',kind='new',error=RuntimeError())
        self.assertEqual(a.verify_replay()['events'],count)
        self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),Decimal(500));a.verify_replay()

    @unittest.skipUnless(hasattr(__import__('os'),'fork'),'requires Linux process crash')
    def test_process_death_at_each_native_hold_boundary_recovers_exactly_once(self):
        import os
        from unittest.mock import patch
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.directional_sleeve import policies,recover_pump_terminals
        for stage in ('after_grant','after_native_sleeve_commit'):
            with self.subTest(stage=stage):
                root,a,now,_=self.fixture();sleeve=self._grant_test_sleeve(root,'pump')
                strategy=next(s for s in policies('pump') if 'survivor' not in s)
                book=PaperBook(root/'pump/crash.sqlite',run_id='crash',lane=strategy,
                    policy_hash=policies('pump')[strategy],initial=125000);self.addCleanup(book.close)
                child=os.fork()
                if child==0:
                    try:
                        original=SleeveReservations.reserve
                        def interrupted(*args,**kwargs):
                            if stage=='after_native_sleeve_commit':original(*args,**kwargs)
                            os._exit(88)
                        with patch.object(SleeveReservations,'reserve',new=interrupted):
                            sleeve.reserve('crash:one',strategy=strategy,amount=6250,at=now,asset='crash',funding_evidence={'qualified':True})
                    except BaseException:
                        os._exit(97)
                    os._exit(99)
                _,status=os.waitpid(child,0);self.assertEqual(os.waitstatus_to_exitcode(status),88)
                self.assertEqual(Decimal(a.snapshot()['capital']['active_reservations']),Decimal('6.25'))
                recover_pump_terminals(book)
                self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),Decimal(500))
                count=a.verify_replay()['events'];recover_pump_terminals(book)
                self.assertEqual(a.verify_replay()['events'],count);a.verify_replay()

    def test_reentry_requires_exact_durable_global_settlement_ack(self):
        from unittest.mock import patch
        from meme_machine.runtime.directional_continuation import native_sync
        root,a,now,_=self.fixture();book,sleeve,identity=self.native_position(root,now,survivor=True)
        self.assertIsNone(sleeve.reentry_verified(identity))
        with patch('meme_machine.runtime.native_boundary.time.time',return_value=now+10), \
                patch.object(book.portfolio.client,'committed',side_effect=RuntimeError('lost_global_ack')):
            with self.assertRaisesRegex(RuntimeError,'lost_global_ack'):
                book.transition(identity,'settled',now+1,amount=7000)
        self.assertIsNone(sleeve.reentry_verified(identity))
        with patch('meme_machine.shared_capital.runtime.time.time',return_value=now+20):
            book.portfolio.recover();book.portfolio.prepared.clear();native_sync(book,sleeve,identity)
        proof=sleeve.reentry_verified(identity)
        self.assertEqual(proof['terminal_at'],now+1)
        self.assertEqual(proof['financial_settlement_at'],now+10)
        self.assertEqual(proof['global_ack_at'],now+20)
        self.assertTrue(proof['obligations_clear']);self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),Decimal('500.75'))
        self.assertEqual(proof,sleeve.reentry_verified(identity));self.assertTrue(book.replay()['verified']);a.verify_replay()

    def test_preexisting_terminal_receipt_replays_and_keeps_conservative_clock(self):
        from unittest.mock import patch
        root,a,now,_=self.fixture();book,sleeve,identity=self.native_position(root,now,survivor=True)
        original=book.portfolio.client.prepare
        def legacy_metadata(*args,**kwargs):
            kwargs['metadata']={k:v for k,v in kwargs.get('metadata',{}).items() if k!='native_event_at'}
            return original(*args,**kwargs)
        with patch('meme_machine.runtime.native_boundary.time.time',return_value=now+10), \
                patch.object(book.portfolio.client,'prepare',side_effect=legacy_metadata):
            book.transition(identity,'settled',now+1,amount=7000)
        state=a.ledger();life=state['native_aliases']['pump:'+identity]
        receipt=state['positions'][life]['terminal_receipt']
        self.assertNotIn('native_settlement_at',receipt)
        proof=sleeve.reentry_verified(identity)
        self.assertEqual(proof['terminal_at'],now+10)
        self.assertEqual(proof['financial_settlement_at'],now+10)
        self.assertEqual(proof['global_ack_at'],now+10)
        a.verify_replay();self.assertTrue(book.replay()['verified'])


if __name__=='__main__':unittest.main()
