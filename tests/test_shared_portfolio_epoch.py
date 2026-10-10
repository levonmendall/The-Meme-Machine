"""New explicit PAPER inception; actual native funding and dashboard, offline only."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard.api import Dashboard
from dashboard.model import Reader
from dashboard.snapshots import SnapshotReader, SnapshotStore
from dashboard.tests.test_server_security import snapshot
from meme_machine.portfolio_accounting import (PortfolioAccounting, PortfolioIntegrityError,
    inception_receipt, validate_inception, canonical)
from meme_machine.portfolio_snapshot_transport import (build_snapshot, apply_snapshot, current_paths,
    SnapshotTransportError)
from meme_machine.shared_capital import CapitalError, RiskPolicy
from meme_machine.shared_capital.operational_candidate import (initialize_new_epoch, PumpPonsCapital, ACTIVE_REGIMES)
from meme_machine.shared_capital.reporting import export, summary
from meme_machine.shared_capital.runtime import RuntimeCapital
from meme_machine.runtime.directional_continuation import BRIDGE_GATES
from tests.shared_capital_support import Harness, CONTRACTS, legacy_identities, legacy_fixture, utc
from tests import test_pump_pons_capital_preparation as native_fixtures


class NewHarness(Harness):
    def restart(self):
        before=self.authority.snapshot();kind=type(self.authority);self.authority.close()
        self.authority=kind(self.path)
        assert self.authority.snapshot()==before

    def finish_round(self,round_id,requests):
        for r in ACTIVE_REGIMES:
            self.authority.seal(operation_id='seal:'+round_id+':'+r,round_id=round_id,regime_name=r,
                request_ids=[q.request_id for q in requests if q.regime==r],at=self.at)

    def native(self,*args,**kwargs):
        return dict(super().native(*args,**kwargs),epoch_id=self.plan['seed']['epoch_id'])

    def prepare(self,*args,**kwargs):
        return replace(super().prepare(*args,**kwargs),epoch_id=self.plan['seed']['epoch_id'])


class SharedEpochTests(unittest.TestCase):
    def test_actual_dashboard_fixture_cli_contract_supports_both_epochs(self):
        from dashboard.fixtures import write,FIXTURE_NOW
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for shared,capital in ((False,500),(True,1000)):
                path=root/str(capital);write(path,shared=shared)
                view=Reader(path/'inception.json',path/'accounting.json',path/'telemetry.json',mode='fixture',clock=lambda:FIXTURE_NOW).view()
                self.assertEqual(Decimal(view['portfolio']['starting_capital']['value']),capital)
                self.assertEqual(view['portfolio']['state'],'CURRENT')
                if shared:
                    self.assertEqual(view['portfolio']['metrics']['open_positions']['value'],0)
                    self.assertEqual(view['system']['lanes']['meteora']['operational']['value'],'paused')
                    self.assertEqual(view['system']['lanes']['ramses']['operational']['value'],'paused')
    def harness(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        receipt=inception_receipt('offline-fixture-new-1000',utc(0),'new-inception',starting_capital='1000.00',shared=True)
        plan=initialize_new_epoch(root/'new',receipt,portfolio_identities=legacy_identities(),
            lane_identities={f:legacy_identities(f) for f in ('pump','pons','meteora','ramses')},
            contracts=CONTRACTS,policy=RiskPolicy(sizing_basis='shared_realized_equity'))
        h=NewHarness(root,plan=plan);h.authority.close();h.authority=PumpPonsCapital(h.path)
        self.addCleanup(h.close)
        return h

    def view(self,h):
        receipt=h.plan['seed']['inception'];projection=export(h.authority,at=h.at)
        root=h.root/'dashboard';root.mkdir(exist_ok=True)
        (root/'inception.json').write_text(canonical(receipt))
        (root/'accounting.json').write_text(canonical(projection))
        reader=Reader(root/'inception.json',root/'accounting.json',clock=lambda:h.at,
            expected_epoch=receipt['epoch_id'],expected_inception_sha256=h.plan['seed']['inception_sha256'])
        return reader,reader.view(),projection

    def test_explicit_new_inception_has_no_family_funds_and_four_50_targets(self):
        h=self.harness();s=h.check()
        self.assertEqual(Decimal(s['capital']['realized_equity']),1000)
        self.assertEqual(Decimal(s['capital']['free_cash']),1000)
        self.assertFalse(s['ledger']['positions']);self.assertFalse(s['ledger']['reservations'])
        self.assertFalse(s['ledger']['family_sizing_genesis'])
        self.assertEqual(set(s['ledger']['realized'].values()),{'0'})
        _,v,e=self.view(h);p=v['portfolio']
        self.assertEqual(p['state'],'CURRENT')
        self.assertEqual(Decimal(p['starting_capital']['value']),1000)
        self.assertEqual(Decimal(p['metrics']['return_pct']['value']),0)
        self.assertEqual(p['metrics']['open_positions']['value'],0)
        details=e['shared_capital']
        self.assertNotIn('family_equivalent_equity',details)
        for r in ACTIVE_REGIMES:
            self.assertEqual(Decimal(details['directional_sizing'][r]['new_position_target']),50)
            self.assertEqual(Decimal(details['directional_sizing'][r]['staged_add_equity_ceiling']),25)
            self.assertEqual(Decimal(details['directional_sizing'][r]['combined_basis_ceiling']),75)
        self.assertEqual(details['paused_families'],dict(meteora='PAUSED',ramses='PAUSED'))
        requests,result=h.allocate([(r,dict(requested='50')) for r in ACTIVE_REGIMES])
        self.assertEqual({v['basis'] for v in result['decisions'].values()},{'50'})
        for q in requests:h.fill(q)
        self.assertEqual(h.check()['capital']['deployed_basis'],'200')
        self.assertEqual(Decimal(h.check()['capital']['free_cash']),800);h.restart()

    def test_pump_can_use_shared_cash_beyond_any_equal_family_allocation(self):
        h=self.harness()
        for _ in range(6):
            requests,result=h.allocate([('pump_current',dict(requested='50'))])
            self.assertEqual(result['decisions'][requests[0].request_id]['basis'],'50');h.fill(requests[0])
        self.assertEqual(h.check()['capital']['deployed_basis'],'300')
        self.assertEqual(Decimal(h.check()['capital']['free_cash']),700)
        # Genuine concentration limits still constrain new risk.
        requests,result=h.allocate([('pump_current',dict(requested='1000',minimum_basis='50',asset='large'))])
        self.assertEqual(Decimal(result['decisions'][requests[0].request_id]['basis']),50)
        with self.assertRaisesRegex(CapitalError,'paused_family_capital_admission'):
            h.authority.observe(operation_id='paused',regime_name='meteora',candidate_id='paused',generation=1,
                status='QUALIFIED',economic_keys=['paused'],evidence={},policy_hash=CONTRACTS['meteora']['policy_hash'],at=h.at)

    def test_twenty_concurrent_requests_obey_aggregate_risk_without_a_position_count_veto(self):
        h=self.harness()
        q,result=h.allocate([(r,dict(requested='50')) for _ in range(5) for r in ACTIVE_REGIMES])
        funded=[request for request in q if result['decisions'][request.request_id]['status']=='RESERVED']
        # 80% directional aggregate exposure, rather than a worker/owner count.
        self.assertEqual(sum(Decimal(result['decisions'][request.request_id]['basis']) for request in funded),800)
        self.assertEqual(len(funded),16)
        self.assertTrue(all(result['decisions'][request.request_id]['status']=='QUALIFIED_BUT_CAPITAL_UNAVAILABLE'
                            for request in q if request not in funded))
        self.assertTrue(all(row['status']=='QUALIFIED' for row in h.check()['ledger']['observations'].values()))
        for request in funded:h.fill(request)
        self.assertEqual(Decimal(h.check()['capital']['free_cash']),200)
        self.assertEqual(h.check()['capital']['deployed_basis'],'800');h.restart();h.authority.verify_replay()

    def test_realized_profit_and_loss_compound_all_regimes_but_marks_do_not(self):
        h=self.harness()
        q,_=h.allocate([('pump_current',dict(requested='50')),('pons_survivor',dict(requested='50'))])
        pump,_=h.fill(q[0]);pons,_=h.fill(q[1]);h.at=1
        h.mark('pump_current',pump,'100')
        _,v,e=self.view(h)
        self.assertEqual(Decimal(v['portfolio']['metrics']['equity']['value']),1050)
        self.assertEqual(Decimal(v['portfolio']['metrics']['realized_equity']['value']),1000)
        self.assertTrue(all(Decimal(row['new_position_target'])==50 for row in e['shared_capital']['directional_sizing'].values()))
        h.realize('pump_current',pump,'60');h.at=2
        _,v,e=self.view(h)
        self.assertEqual(Decimal(v['portfolio']['metrics']['return_pct']['value']),1)
        self.assertTrue(all(Decimal(row['new_position_target'])==Decimal('50.5') for row in e['shared_capital']['directional_sizing'].values()))
        h.realize('pons_survivor',pons,'35')
        _,v,e=self.view(h)
        self.assertEqual(Decimal(v['portfolio']['metrics']['realized_equity']['value']),995)
        self.assertEqual(Decimal(v['portfolio']['metrics']['return_pct']['value']),Decimal('-.5'))
        self.assertEqual(Decimal(v['portfolio']['regimes']['pons_survivor']['metrics']['realized_pnl']['value']),-15)
        self.assertTrue(all(Decimal(row['new_position_target'])==Decimal('49.75') for row in e['shared_capital']['directional_sizing'].values()))
        h.restart();h.authority.verify_replay()

    def test_partial_exit_add_limits_and_one_add_survive_recovery(self):
        h=self.harness();q,_=h.allocate([('pons_current',dict(requested='50'))]);life,_=h.fill(q[0]);h.at=1
        h.realize('pons_current',life,'20',released='12.5',terminal=False);h.mark('pons_current',life,'100')
        h.at=900
        control=dict(opened_at=0,high_water_bps=10000,first_tail_crossed_at=0,realization_taken=True,original_basis=1)
        facts=dict({gate:True for gate in BRIDGE_GATES},fresh_strategy_requalified=True,fresh_execution_requalified=True,after_cost_return_bps=7000)
        _,v,e=self.view(h);row=e['positions'][0]
        self.assertEqual(row['partial_exits'],1);self.assertEqual(Decimal(row['staged_add_limits']['maximum_basis']),25)
        self.assertEqual(Decimal(v['portfolio']['metrics']['realized_pnl']['value']),Decimal('7.5'))
        q,result=h.allocate([('pons_current',dict(requested='25',asset=h.check()['ledger']['positions'][life]['economic_keys'][0],
            kind='scale',lifecycle_id=life,scale_state=control,scale_facts=facts))])
        self.assertEqual(result['decisions'][q[0].request_id]['basis'],'25');h.fill(q[0]);h.restart()
        _,v,e=self.view(h);row=e['positions'][0]
        self.assertEqual(row['original_basis'],'50');self.assertEqual(row['staged_add_basis'],'25')
        self.assertTrue(row['scale_committed']);self.assertEqual(row['staged_add_limits']['maximum_basis'],'0')
        q,result=h.allocate([('pons_current',dict(requested='1',asset=h.check()['ledger']['positions'][life]['economic_keys'][0],
            kind='scale',lifecycle_id=life,scale_state=control,scale_facts=facts))])
        self.assertEqual(result['decisions'][q[0].request_id]['status'],'QUALIFIED_BUT_CAPITAL_UNAVAILABLE')
        h.authority.verify_replay()

    def test_other_regime_realized_loss_reduces_the_combined_add_headroom(self):
        h=self.harness();q,_=h.allocate([('pons_survivor',dict(requested='50')),('pump_current',dict(requested='50'))])
        winner,_=h.fill(q[0]);loser,_=h.fill(q[1]);h.at=1
        h.realize('pons_survivor',winner,'20',released='12.5',terminal=False)
        h.mark('pons_survivor',winner,'100');h.realize('pump_current',loser,'30');h.at=900
        _,_,projection=self.view(h);position=next(p for p in projection['positions'] if p['state']=='OPEN')
        self.assertEqual(Decimal(position['staged_add_limits']['maximum_basis']),Decimal('24.0625'))
        control=dict(opened_at=0,high_water_bps=10000,first_tail_crossed_at=0,realization_taken=True,original_basis=1)
        facts=dict({gate:True for gate in BRIDGE_GATES},fresh_strategy_requalified=True,fresh_execution_requalified=True,after_cost_return_bps=7000)
        requests,result=h.allocate([('pons_survivor',dict(requested='25',minimum_basis='1',kind='scale',lifecycle_id=winner,
            asset=h.check()['ledger']['positions'][winner]['economic_keys'][0],scale_state=control,scale_facts=facts))])
        self.assertEqual(Decimal(result['decisions'][requests[0].request_id]['basis']),Decimal('24.0625'))

    def test_missing_liquidity_execution_and_cash_still_refuse_native_funding(self):
        h=self.harness()
        for field in ('liquidity_capacity','execution_capacity'):
            q,result=h.allocate([('pons_survivor',dict(requested='50',**{field:'0'}))])
            self.assertEqual(result['decisions'][q[0].request_id]['status'],'QUALIFIED_BUT_CAPITAL_UNAVAILABLE')
        q,result=h.allocate([('pons_current',dict(requested='50',cost_headroom='1000'))])
        self.assertEqual(result['decisions'][q[0].request_id]['status'],'QUALIFIED_BUT_CAPITAL_UNAVAILABLE')
        self.assertEqual(Decimal(h.check()['capital']['free_cash']),1000)

    def test_wrong_sizing_policy_or_reusing_an_existing_epoch_is_refused(self):
        h=self.harness();old=h.root/'old.sqlite';book=legacy_fixture(old);book.close()
        before=hashlib.sha256(old.read_bytes()).hexdigest()
        receipt=h.plan['seed']['inception']
        with self.assertRaises(FileExistsError):
            initialize_new_epoch(h.root,receipt,portfolio_identities=legacy_identities(),lane_identities={},contracts=CONTRACTS,
                policy=RiskPolicy(sizing_basis='shared_realized_equity'))
        with self.assertRaisesRegex(CapitalError,'shared_inception_sizing_policy_mismatch'):
            initialize_new_epoch(h.root/'wrong',receipt,portfolio_identities=legacy_identities(),lane_identities={},
                contracts=CONTRACTS,policy=RiskPolicy())
        self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(),before)
        with closing(PortfolioAccounting(h.root/'new'/'portfolio.sqlite')) as frozen:
            with self.assertRaisesRegex(PortfolioIntegrityError,'no_family_allocations'):frozen.configure_family_sleeves()
            with self.assertRaisesRegex(PortfolioIntegrityError,'conflicting_inception'):
                frozen.establish_inception(inception_receipt('different',utc(0),'different'),portfolio_identities={},lane_identities={})

    def test_return_contribution_api_chart_and_regime_filters_use_validated_inception(self):
        h=self.harness();q,_=h.allocate([('pump_survivor',dict(requested='50'))]);life,_=h.fill(q[0]);h.at=1
        h.realize('pump_survivor',life,'60')
        reader,v,_=self.view(h);app=Dashboard(reader)
        def get(route):
            status,_,body=app.response('GET','/api/dashboard/'+route);self.assertEqual(status,200);return json.loads(body)
        self.assertEqual(get('equity')['reference'],'1000.00')
        self.assertEqual(Decimal(v['lanes']['pump']['metrics']['contribution_pct']['value']),1)
        self.assertEqual(len(get('regimes')['data']),4)
        self.assertEqual(get('trades?regime=pump_survivor')['total'],1)
        self.assertEqual(get('trades?regime=pump_current')['total'],0)

    def test_unavailable_stale_and_mismatched_shared_exports_are_honest(self):
        h=self.harness();q,_=h.allocate([('pons_survivor',dict(requested='50'))]);life,_=h.fill(q[0],mark=False)
        reader,v,e=self.view(h)
        self.assertIsNone(v['portfolio']['metrics']['equity']['value'])
        self.assertEqual(Decimal(v['portfolio']['metrics']['realized_equity']['value']),1000)
        h.mark('pons_survivor',life);reader,_,e=self.view(h);reader.clock=lambda:100001
        v=reader.view();self.assertEqual(v['portfolio']['state'],'STALE');self.assertIsNone(v['portfolio']['metrics']['equity']['value'])
        for field,wrong in (('inception_equity','500'),('realized_equity','1100')):
            bad=deepcopy(e);bad['shared_capital'][field]=wrong
            Path(reader.accounting).write_text(canonical(bad))
            self.assertEqual(reader.view()['portfolio']['state'],'FAIL_CLOSED')
        self.assertEqual(Reader().view()['portfolio']['desired_starting_capital'],'1000.00')
        self.assertIsNone(Reader().view()['portfolio']['epoch'])

    def test_explicit_new_replica_and_reader_never_rebind_old_epoch(self):
        h=self.harness();reader,_,e=self.view(h);receipt=h.plan['seed']['inception']
        bundle=build_snapshot(receipt,e);path=h.root/'bundle.json';path.write_text(canonical(bundle))
        new=h.root/'new-replica'
        apply_snapshot(path,new,expected_epoch=receipt['epoch_id'],expected_inception_sha256=bundle['inception_sha256'])
        paths=current_paths(new)
        pinned=Reader(paths['inception_path'],paths['accounting_path'],clock=lambda:0,expected_epoch=receipt['epoch_id'])
        self.assertEqual(pinned.view()['portfolio']['starting_capital']['value'],'1000.00')
        old=legacy_fixture(h.root/'historical.sqlite')
        legacy=build_snapshot(old.binding()['receipt'],old.publish(epoch_id=old.binding()['receipt']['epoch_id'],event_id='publish',as_of=utc(0),valid_until=utc(30)));old.close()
        old_path=h.root/'old-bundle.json';old_path.write_text(canonical(legacy))
        old_root=h.root/'old-replica';apply_snapshot(old_path,old_root)
        with self.assertRaisesRegex(SnapshotTransportError,'replica_cross_epoch'):apply_snapshot(path,old_root)
        with self.assertRaisesRegex(SnapshotTransportError,'selected_replica_epoch'):apply_snapshot(old_path,new,expected_epoch=receipt['epoch_id'])
        Path(reader.inception).write_text(canonical(legacy['receipt']))
        self.assertEqual(reader.view()['portfolio']['state'],'FAIL_CLOSED')

    def test_protected_render_reader_and_snapshot_pins_support_new_epoch(self):
        h=self.harness();_,_,e=self.view(h);receipt=h.plan['seed']['inception']
        value=snapshot(0);value['source']['epoch_id']=receipt['epoch_id'];value['observer']['epoch_id']=receipt['epoch_id']
        value['portfolio']=dict(bundle=build_snapshot(receipt,e),observation=dict(state='CURRENT',at=utc(0),epoch_id=receipt['epoch_id'],
            sequence=e['sequence'],inception_sha256=e['inception_sha256'],reconciliation='PASS',checks=summary(h.authority,0)['checks'],balances=e['balances']))
        path=h.root/'render-new.json';store=SnapshotStore(path,epoch=receipt['epoch_id'],candidate='a'*40,clock=lambda:0);store.accept(value)
        v=SnapshotReader(store,clock=lambda:0).view()
        self.assertEqual(v['portfolio']['starting_capital']['value'],'1000.00')
        self.assertEqual(Decimal(v['portfolio']['metrics']['realized_equity']['value']),1000)
        self.assertEqual(v['system']['paper_state'],'STOPPED')
        stale=SnapshotReader(store,clock=lambda:61).view()
        self.assertEqual(stale['portfolio']['regimes']['pump_current']['metrics']['realized_pnl']['state'],'STALE')
        with self.assertRaisesRegex(ValueError,'snapshot_epoch'):
            SnapshotStore(path,epoch='old-500',candidate='a'*40,clock=lambda:0)
        changed=deepcopy(value);changed['portfolio']['bundle']['receipt']['canonical_event_id']='different'
        with self.assertRaises(RuntimeError):store.accept(changed)

    def test_new_history_is_journalled_bounded_and_replayable(self):
        h=self.harness();h.authority.close();a=RuntimeCapital(h.path);h.authority=a
        q,_=h.allocate([('pump_current',dict(requested='50'))]);life,_=h.fill(q[0]);h.at=1
        h.realize('pump_current',life,'60')
        a.command('history:1','runtime_publish',{},1)
        e=export(a,at=1);points=[p for p in e['history'] if p['series']=='portfolio']
        self.assertEqual(points[0]['value'],'1000.00');self.assertEqual(Decimal(points[-1]['value']),1010)
        before=deepcopy(e['history']);a.verify_replay();a.close();h.authority=RuntimeCapital(h.path)
        self.assertEqual(export(h.authority,at=1)['history'],before)
        # Exercise the existing reducer's retention boundary without 400 costly
        # SQL/replay operations that would only repeat the same monetary test.
        state=h.authority.ledger();state['reporting_history']=state['reporting_history']*201
        state,_=h.authority._apply(state,dict(action='runtime_publish',at=2,data={}))
        self.assertLessEqual(len(state['reporting_history']),2000)


class NewNativeEpochTests(unittest.TestCase):
    fixture=native_fixtures.RuntimeIntegrationTests.fixture
    def test_four_actual_native_regimes_target_50_and_use_one_shared_authority(self):
        from meme_machine.runtime.directional_sleeve import open_sleeve,policies
        from meme_machine.lanes.pump.paper_accounting import PaperBook
        from meme_machine.runtime.directional_continuation import native_sync
        root,a,now,plan=self.fixture(new_epoch=True)
        for family in ('pump','pons'):
            (root/family).mkdir(exist_ok=True)
            with patch.dict(os.environ,{'MM_DIRECTIONAL_SLEEVE_DB':str(root/family/'directional-sleeve.sqlite')}):
                sleeve=open_sleeve(family,1_000_000);self.addCleanup(sleeve.close)
                self.assertEqual(sleeve.sizing_basis(500)['target'],50_000)
                self.assertEqual(sleeve.sizing_basis(250)['target'],25_000)
                self.assertEqual(sleeve.sizing_basis(500)['sizing_basis'],'shared_realized_equity')
                for strategy,policy in policies(family).items():
                    book=PaperBook(root/family/(strategy+'.sqlite'),run_id='new-test',lane=strategy,policy_hash=policy,initial=1_000_000)
                    self.addCleanup(book.close);identity='new-test:'+strategy
                    sleeve.reserve(identity,strategy=strategy,amount=50_000,at=now,asset=identity,funding_evidence=dict(qualified=True))
                    book.reserve(identity,50_000,now,dict(qualified=True))
                    book.transition(identity,'filled',now,amount=50_000,tokens=100,evidence=dict(execution={'gas':0}))
                    book.transition(identity,'mark',now,amount=50_000);native_sync(book,sleeve,identity)
                    book.replay();book.reconcile()
        self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),800)
        self.assertEqual(a.snapshot()['capital']['deployed_basis'],'200');a.verify_replay()

    def test_actual_pons_current_50_quote_partial_loss_and_restart_reconcile(self):
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        from meme_machine.lanes.pons.evidence import Store,digest
        from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        from meme_machine.runtime.directional_sleeve import open_sleeve
        root,a,now,_=self.fixture(new_epoch=True);(root/'pons').mkdir()
        with patch.dict(os.environ,{'MM_DIRECTIONAL_SLEEVE_DB':str(root/'pons/directional-sleeve.sqlite')}):
            store=Store(root/'pons/current.sqlite');self.addCleanup(store.close)
            guard=CohortCapital(root/'pons/capital.sqlite',1_000_000)
            paper=SelectivePaper(store,STRATEGY_NAMESPACE,1_000_000,delay=1,natural_policy_hash=POLICY_HASH,on_commit=guard.observe)
            fixture=PartialAccountingTests();decision=fixture.features(now)
            with closing(open_sleeve('pons',1_000_000)) as sleeve:self.assertEqual(sleeve.sizing_basis(500)['target'],50_000)
            guard.reserve('pons-50',50_250,at=now,decision_hash=digest(decision),trial_path=root/'pons/current.sqlite',
                native_reservation_intent=dict(market='m',amount=50_000,gas_budget=250,features=decision,now=now,kind='natural'))
            paper.reserve('pons-50',market='m',amount=50_000,gas_budget=250,now=now,features=decision)
            paper.advance('pons-50',now=now+1,action='entry',quote=fixture.quote(now+1,'buy',50_000,1000))
            # Original marks use the actual remaining quantity and expire at
            # the original five-second clock. No event-only price substitution.
            paper.advance('pons-50',now=now+2,action='mark',quote=fixture.quote(now+2,'sell',1000,60_000))
            paper.advance('pons-50',now=now+3,action='exit_intent',exit_tokens=250)
            paper.advance('pons-50',now=now+4,action='exit',quote=fixture.quote(now+4,'sell',250,15_000))
            self.assertEqual(len(a.snapshot()['ledger']['positions']),1)
            self.assertGreater(Decimal(a.snapshot()['capital']['realized_equity']),1000)
            paper.advance('pons-50',now=now+5,action='exit_intent')
            p=paper.advance('pons-50',now=now+6,action='exit',quote=fixture.quote(now+6,'sell',750,30_000))
            guard.settle('pons-50',p,at=now+6)
            self.assertTrue(paper.accounting('pons-50')['replay_verified']);self.assertTrue(guard.reconcile()['cash_basis_conservation'])
            self.assertEqual(Decimal(a.snapshot()['capital']['realized_equity']),Decimal('994.994'))
            self.assertEqual(a.snapshot()['capital']['deployed_basis'],'0')
            with closing(open_sleeve('pons',1_000_000)) as sleeve:self.assertEqual(sleeve.sizing_basis(500)['target'],49_749)
            a.verify_replay()
            with closing(RuntimeCapital(root/'shared-capital.sqlite')) as restored:
                self.assertEqual(restored.snapshot()['capital'],a.snapshot()['capital']);restored.verify_replay()

    def test_supervisor_can_restore_selected_new_epoch_without_reseeding(self):
        from meme_machine.operational.supervisor import Supervisor
        root,a,_,plan=self.fixture(new_epoch=True)
        before=a.snapshot()
        supervisor=Supervisor(root,offline=True);supervisor.initialize()
        try:
            self.assertEqual(supervisor.epoch,plan['seed']['epoch_id'])
            self.assertEqual(supervisor.shared_capital.snapshot(),before)
        finally:supervisor.lock.close()
