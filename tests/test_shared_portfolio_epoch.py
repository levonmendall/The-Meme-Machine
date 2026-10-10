"""New explicit PAPER inception; actual native funding and dashboard, offline only."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext, Inexact, Rounded
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
from meme_machine.shared_capital.model import UNIT
from meme_machine.shared_capital.operational_candidate import (initialize_new_epoch, PumpPonsCapital, ACTIVE_REGIMES)
from meme_machine.shared_capital.reporting import export, summary
from meme_machine.shared_capital.runtime import RuntimeCapital
from meme_machine.runtime.directional_continuation import BRIDGE_GATES
from tests.shared_capital_support import Harness, CONTRACTS, legacy_identities, legacy_fixture, utc
from tests import test_pump_pons_capital_preparation as native_fixtures


def shared_risk_candidate():
    # Deliberate offline selection. No runtime or deployment imports this file.
    root=Path(__file__).resolve().parents[1]
    return RiskPolicy(**json.loads((root/'operational/shared-capital-activation/risk-policy.shared-1000.proposed.json').read_text()))


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
    def test_inception_validation_ignores_ambient_decimal_precision(self):
        # The canonical-money suite deliberately changes ambient precision.
        # New and historical receipts must replay without mutating that context.
        for shared, capital in ((False, '500.00'), (True, '1000.00')):
            expected = inception_receipt('explicit-offline-epoch', utc(0), 'inception',
                starting_capital=capital, shared=shared)
            with localcontext() as context:
                context.prec=1;context.traps[Inexact]=True;context.traps[Rounded]=True
                before=context.copy()
                self.assertEqual(validate_inception(expected), expected)
                self.assertEqual(inception_receipt('explicit-offline-epoch', utc(0), 'inception',
                    starting_capital=capital, shared=shared), expected)
                with self.assertRaises(ValueError):
                    inception_receipt('explicit-offline-epoch', utc(0), 'inception',
                        starting_capital=capital+'1', shared=shared)
                self.assertEqual(context.prec,before.prec)
                self.assertEqual(context.flags,before.flags)
                self.assertEqual(context.traps,before.traps)

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
    def harness(self,policy=None):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        receipt=inception_receipt('offline-fixture-new-1000',utc(0),'new-inception',starting_capital='1000.00',shared=True)
        plan=initialize_new_epoch(root/'new',receipt,portfolio_identities=legacy_identities(),
            lane_identities={f:legacy_identities(f) for f in ('pump','pons','meteora','ramses')},
            contracts=CONTRACTS,policy=policy or RiskPolicy(sizing_basis='shared_realized_equity'))
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


class SharedRiskPolicyTests(unittest.TestCase):
    harness=SharedEpochTests.harness
    view=SharedEpochTests.view

    def old_policy(self):
        root=Path(__file__).resolve().parents[1]
        return RiskPolicy(**json.loads((root/'operational/shared-capital-activation/risk-policy.proposed.json').read_text()))

    def conflicting_authority(self,policy):
        # Reproduce the old cap through the actual authority, without using the
        # new initializer that now refuses this contradiction before persistence.
        from meme_machine.shared_capital.migration import plan_migration
        from tests.shared_capital_support import empty_mapping
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        with closing(PortfolioAccounting(root/'empty.sqlite')) as a:
            a.establish_inception(inception_receipt('offline-risk-conflict',utc(0),'new',starting_capital='1000.00',shared=True),
                portfolio_identities=legacy_identities(),lane_identities={f:legacy_identities(f) for f in ('pump','pons','meteora','ramses')})
        h=NewHarness(root,plan=plan_migration(root/'empty.sqlite',empty_mapping(),policy))
        h.authority.close();h.authority=PumpPonsCapital(h.path)
        self.addCleanup(h.close);return h

    def stage(self,h,r,life,requested='25',**changes):
        p=h.check()['ledger']['positions'][life]
        control=dict(opened_at=0,high_water_bps=10000,first_tail_crossed_at=0,realization_taken=True,
            original_basis=p['original_native_basis'])
        facts=dict({g:True for g in BRIDGE_GATES},fresh_strategy_requalified=True,
            fresh_execution_requalified=True,after_cost_return_bps=10000)
        control.update(changes.pop('control',{}));facts.update(changes.pop('facts',{}))
        return h.allocate([(r,dict(requested=requested,minimum_basis='0.01',kind='scale',lifecycle_id=life,
            asset=p['economic_keys'][0],scale_state=control,scale_facts=facts,**changes))])

    def winner(self,r,policy=None):
        h=self.harness(policy or shared_risk_candidate())
        q,decision=h.allocate([(r,dict(requested='50'))]);self.assertEqual(Decimal(decision['decisions'][q[0].request_id]['basis']),Decimal('50'))
        life,_=h.fill(q[0]);h.at=1;h.mark(r,life,'100')
        self.assertEqual(Decimal(h.check()['capital']['realized_equity']),Decimal('1000'))
        h.realize(r,life,'25',released='12.5',terminal=False);h.mark(r,life,'75');h.at=900
        return h,life

    def test_recommended_policy_is_explicit_and_original_identity_is_unchanged(self):
        from meme_machine.shared_capital.model import digest
        original=self.old_policy().value();candidate=shared_risk_candidate().value()
        self.assertEqual(digest(original),'e87385900145e53956df18956ee2390f0d95787e6ffc44243251f9b147eb65f2')
        self.assertNotIn('asset_invested_bps',original)
        self.assertEqual({k:v for k,v in candidate.items() if original.get(k)!=v},
            dict(asset_bps=1000,asset_invested_bps=750,sizing_basis='shared_realized_equity'))
        with self.assertRaisesRegex(ValueError,'invested_limit_exceeds_marked_asset_limit'):
            replace(shared_risk_candidate(),asset_bps=500).value()
        h=self.harness(shared_risk_candidate());h.restart();h.authority.verify_replay()

    def test_old_approved_cap_reduces_or_denies_50_and_conflicting_inception_is_refused(self):
        policy=replace(self.old_policy(),sizing_basis='shared_realized_equity')
        for r in ACTIVE_REGIMES:
            with self.subTest(regime=r):
                h=self.conflicting_authority(policy)
                q,result=h.allocate([(r,dict(requested='50',minimum_basis='1'))])
                d=result['decisions'][q[0].request_id]
                self.assertEqual(Decimal(d['basis']),Decimal('25'));self.assertTrue(any(c.startswith('ASSET_CONCENTRATION:') for c in d['binding_constraints']))
                h.authority.cancel(operation_id='cancel-old',request_id=q[0].request_id,at=h.at,proof_sha256='d'*64,proof_kind='VERIFIED_NATIVE_ABSENCE')
                q,result=h.allocate([(r,dict(requested='50'))])
                self.assertEqual(result['decisions'][q[0].request_id]['status'],'QUALIFIED_BUT_CAPITAL_UNAVAILABLE')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'refused'
            with self.assertRaisesRegex(CapitalError,'new_shared_initial_target_conflicts_with_asset_policy'):
                initialize_new_epoch(root,inception_receipt('offline-refusal',utc(0),'inception',starting_capital='1000.00',shared=True),
                    portfolio_identities=legacy_identities(),lane_identities={},contracts=CONTRACTS,policy=policy)
            self.assertFalse(root.exists())

    def test_numeric_75_marked_ceiling_still_blocks_full_staged_add(self):
        for ceiling,expected in ((500,'0'),(750,'0.9375'),(1000,'25')):
            h,life=self.winner('pons_current',replace(shared_risk_candidate(),asset_bps=ceiling,asset_invested_bps=None))
            q,result=self.stage(h,'pons_current',life)
            d=result['decisions'][q[0].request_id]
            self.assertEqual(Decimal(d['basis']),Decimal(expected))
            if ceiling<1000:self.assertTrue(any(c.startswith('ASSET_CONCENTRATION:') for c in d['binding_constraints']))
            self.assertEqual(Decimal(h.check()['capital']['realized_equity']),Decimal('1012.5'))

    def test_first_25_percent_realization_and_25_add_for_each_native_contract(self):
        for r in ACTIVE_REGIMES:
            with self.subTest(regime=r):
                h,life=self.winner(r);before=h.check();p=before['ledger']['positions'][life]
                original_native=p['original_native_basis']
                self.assertEqual(Decimal(p['basis']),Decimal('37.5'));self.assertEqual(Decimal(p['realized_pnl']),Decimal('12.5'))
                self.assertEqual(Decimal(before['risk']['marked_exposure']),Decimal('75'));self.assertEqual(Decimal(before['capital']['free_cash']),Decimal('975'))
                q,result=self.stage(h,r,life);d=result['decisions'][q[0].request_id]
                self.assertEqual(Decimal(d['basis']),Decimal('25'));self.assertEqual(Decimal(d['limits']['STAGED_SCALE_CONTRACT']),25)
                h.fill(q[0]);h.mark(r,life,'100');h.restart();after=h.check();p=after['ledger']['positions'][life]
                self.assertEqual(Decimal(p['original_basis']),Decimal('50'));self.assertEqual(p['original_native_basis'],original_native)
                self.assertEqual(Decimal(p['basis']),Decimal('62.5'));self.assertEqual(Decimal(p['capital_deployed']),Decimal('75'));self.assertEqual(p['partials'],1)
                self.assertTrue(p['scale_committed']);self.assertEqual(Decimal(after['capital']['realized_equity']),Decimal('1012.5'))
                self.assertEqual(Decimal(after['capital']['actual_cash']),Decimal('950'));self.assertEqual(Decimal(after['risk']['marked_equity']),Decimal('1050'))
                q,result=self.stage(h,r,life)
                self.assertEqual(result['decisions'][q[0].request_id]['status'],'QUALIFIED_BUT_CAPITAL_UNAVAILABLE')
                h.authority.verify_replay()

    def test_original_scaling_conditions_are_still_required(self):
        cases=[dict(control=dict(first_tail_crossed_at=1)),dict(control=dict(high_water_bps=9999)),
            dict(control=dict(pending_exit=True)),dict(control=dict(last_action=dict(action='full_exit'))),
            dict(facts=dict(after_cost_return_bps=6999)),dict(facts=dict(fresh_strategy_requalified=False)),
            dict(facts=dict(fresh_execution_requalified=False)),dict(facts=dict(creator_distribution_safe=False))]
        for changes in cases:
            h,life=self.winner('pons_survivor');q,result=self.stage(h,'pons_survivor',life,**changes)
            self.assertEqual(result['decisions'][q[0].request_id]['status'],'QUALIFIED_BUT_CAPITAL_UNAVAILABLE')
        h=self.harness(shared_risk_candidate());q,_=h.allocate([('pump_current',dict(requested='50'))]);life,_=h.fill(q[0]);h.at=900
        q,result=self.stage(h,'pump_current',life)
        self.assertEqual(result['decisions'][q[0].request_id]['status'],'QUALIFIED_BUT_CAPITAL_UNAVAILABLE')

    def test_appreciation_is_marked_risk_not_cash_or_a_sale_and_other_assets_keep_independent_headroom(self):
        for multiple in (2,5,10,25,50):
            h=self.harness(shared_risk_candidate());q,_=h.allocate([('pump_current',dict(requested='50'))]);life,_=h.fill(q[0])
            h.at=1;h.mark('pump_current',life,str(50*multiple));before=h.check()
            self.assertEqual(Decimal(before['capital']['realized_equity']),Decimal('1000'));self.assertEqual(Decimal(before['capital']['free_cash']),Decimal('950'))
            self.assertEqual(before['risk']['marked_exposure'],str(50*multiple))
            q,result=h.allocate([('pons_survivor',dict(requested='50'))])
            self.assertEqual(result['decisions'][q[0].request_id]['status'],
                'RESERVED' if multiple<=10 else 'QUALIFIED_BUT_CAPITAL_UNAVAILABLE')
            self.assertEqual(h.check()['ledger']['positions'][life]['status'],'OPEN')
            _,v,e=self.view(h)
            self.assertEqual(Decimal(e['shared_capital']['directional_sizing']['pump_current']['new_position_target']),50)
            self.assertEqual(Decimal(v['positions'][0]['risk_exposure']['marked_value']),50*multiple)

    def test_simultaneous_funding_preserves_approved_aggregate_ceilings_and_candidates(self):
        h=self.harness(shared_risk_candidate());q,result=h.allocate([(r,dict(requested='50')) for _ in range(5) for r in ACTIVE_REGIMES])
        granted=[r for r in q if result['decisions'][r.request_id]['status']=='RESERVED']
        self.assertEqual(len(granted),15);self.assertEqual(sum(Decimal(result['decisions'][r.request_id]['basis']) for r in granted),750)
        self.assertTrue(all(o['status']=='QUALIFIED' for o in h.check()['ledger']['observations'].values()))
        for r in granted:h.fill(r)
        s=h.check();self.assertEqual(Decimal(s['capital']['free_cash']),Decimal('250'))
        self.assertLessEqual(Decimal(s['risk']['exposure']['family']['pump']),450)
        self.assertLessEqual(Decimal(s['risk']['exposure']['family']['pons']),450)
        h.restart();h.authority.verify_replay()

    def test_realized_compounding_900_1100_1500_2000_and_material_drawdown(self):
        for equity in (900,1100,1500,2000):
            h=self.harness(shared_risk_candidate());q,_=h.allocate([('pump_current',dict(requested='50')),('pons_current',dict(requested='50'))])
            a,_=h.fill(q[0]);b,_=h.fill(q[1]);h.at=1
            h.realize('pump_current',a,'0' if equity==900 else str(equity-950))
            h.realize('pons_current',b,'0' if equity==900 else '50')
            _,_,e=self.view(h);self.assertEqual(Decimal(e['shared_capital']['realized_equity']),equity)
            self.assertTrue(all(Decimal(s['new_position_target'])==Decimal(equity)*Decimal('.05') for s in e['shared_capital']['directional_sizing'].values()))
            self.assertTrue(all(Decimal(s['staged_add_equity_ceiling'])==Decimal(equity)*Decimal('.025') for s in e['shared_capital']['directional_sizing'].values()))
            target=str(Decimal(equity)*Decimal('.05'));q,result=h.allocate([('pons_survivor',dict(requested=target))])
            d=result['decisions'][q[0].request_id]
            if equity==900:self.assertEqual(d['reason'],'PORTFOLIO_DRAWDOWN_LIMIT')
            else:
                self.assertEqual(Decimal(d['basis']),Decimal(target));life,_=h.fill(q[0]);h.at=2
                original=Decimal(target)
                h.mark('pons_survivor',life,str(original*2))
                h.realize('pons_survivor',life,str(original/2),released=str(original/4),terminal=False)
                h.mark('pons_survivor',life,str(original*Decimal('1.5')));h.at=902
                q,result=self.stage(h,'pons_survivor',life,requested=str(original/2),control=dict(first_tail_crossed_at=2))
                self.assertEqual(Decimal(result['decisions'][q[0].request_id]['basis']),original/2)
                h.fill(q[0]);self.assertEqual(Decimal(h.check()['ledger']['positions'][life]['capital_deployed']),original*Decimal('1.5'))
            h.restart();h.authority.verify_replay()

    def test_cash_liquidity_execution_and_investment_limits_still_bind(self):
        for field in ('liquidity_capacity','execution_capacity'):
            h=self.harness(shared_risk_candidate());q,result=h.allocate([('pons_current',dict(requested='50',minimum_basis='1',**{field:'20'}))])
            self.assertEqual(Decimal(result['decisions'][q[0].request_id]['basis']),Decimal('20'))
            self.assertIn(field.upper(),result['decisions'][q[0].request_id]['binding_constraints'])
        h,life=self.winner('pump_survivor');h.authority.require_obligation(operation_id='reserve-existing',
            obligation_id='existing',regime_name='pump_survivor',amount_usd='965',at=h.at,proof_sha256='f'*64)
        q,result=self.stage(h,'pump_survivor',life)
        self.assertEqual(result['decisions'][q[0].request_id]['status'],'QUALIFIED_BUT_CAPITAL_UNAVAILABLE')
        self.assertEqual(h.check()['ledger']['positions'][life]['status'],'OPEN')
        # Released basis never enlarges the original-plus-add investment cap.
        h,life=self.winner('pump_current',replace(shared_risk_candidate(),asset_invested_bps=500))
        q,result=self.stage(h,'pump_current',life);d=result['decisions'][q[0].request_id]
        self.assertEqual(Decimal(d['basis']),Decimal('.625'))
        self.assertTrue(any(c.startswith('ASSET_INVESTED_BASIS:') for c in d['binding_constraints']))
        h,life=self.winner('pons_survivor')
        q,result=self.stage(h,'pons_survivor',life,cost_headroom='2');d=result['decisions'][q[0].request_id]
        self.assertEqual(Decimal(d['basis']),(Decimal('1012.5')-2)*Decimal('.075')-50-2)
        self.assertTrue(any(c.startswith('ASSET_INVESTED_BASIS:') for c in d['binding_constraints']))

    def test_native_currency_appreciation_cannot_double_original_usd_add_limit(self):
        h,life=self.winner('pons_survivor')
        q,_=h.allocate([('pump_current',dict(requested='50'))]);other,_=h.fill(q[0])
        h.realize('pump_current',other,'1037.5');h.mark('pons_survivor',life,'150')
        self.assertEqual(Decimal(h.check()['capital']['realized_equity']),2000)
        q,result=self.stage(h,'pons_survivor',life,requested='50',native_sizing=dict(
            realized_equity_units=int(Decimal('2000')/(UNIT*2)),usd_per_native_unit=format(UNIT*2,'f'),journal_sha256='b'*64))
        d=result['decisions'][q[0].request_id]
        self.assertEqual(Decimal(d['limits']['STAGED_SCALE_CONTRACT']),25)
        self.assertEqual(Decimal(d['basis']),25)
        h.fill(q[0]);p=h.check()['ledger']['positions'][life]
        self.assertEqual(Decimal(p['original_basis']),50);self.assertEqual(Decimal(p['capital_deployed']),75)
        h.restart();h.authority.verify_replay()

    def test_actual_dashboard_matches_selected_risk_authority_and_funding_constraints(self):
        h,life=self.winner('pons_current');q,result=self.stage(h,'pons_current',life);h.fill(q[0]);h.mark('pons_current',life,'100')
        reader,v,e=self.view(h);p=v['positions'][0];c=e['shared_capital']
        self.assertEqual(c['risk_limits']['asset_bps'],1000);self.assertEqual(c['risk_limits']['asset_invested_bps'],750)
        self.assertEqual(Decimal(p['risk_exposure']['invested_basis']),Decimal('75'));self.assertEqual(Decimal(p['remaining_basis']),Decimal('62.5'))
        self.assertEqual(Decimal(p['risk_exposure']['marked_value']),Decimal('100'));self.assertEqual(Decimal(p['staged_add_limits']['maximum_basis']),Decimal('0'))
        self.assertEqual({d['granted_basis'] for d in p['funding_decisions']},{'25','50'})
        api=Dashboard(reader);status,_,body=api.response('GET','/api/dashboard/positions/'+life)
        self.assertEqual(status,200);self.assertIn(b'asset_invested_ceiling',body)
        tampered=deepcopy(e);tampered['positions'][0]['risk_exposure']['marked_value']='101'
        (h.root/'dashboard/accounting.json').write_text(canonical(tampered))
        self.assertEqual(reader.view()['portfolio']['state'],'FAIL_CLOSED')


class NewNativeEpochTests(unittest.TestCase):
    fixture=native_fixtures.RuntimeIntegrationTests.fixture
    def test_long_held_native_protection_survives_readonly_transport_and_fails_closed_on_staleness(self):
        from meme_machine.lanes.pump.paper_accounting import PaperBook
        from meme_machine.runtime.directional_sleeve import open_sleeve,policies
        root,a,now,plan=self.fixture(new_epoch=True);(root/'pump').mkdir()
        with patch.dict(os.environ,{'MM_DIRECTIONAL_SLEEVE_DB':str(root/'pump/directional-sleeve.sqlite')}):
            sleeve=open_sleeve('pump',1_000_000);self.addCleanup(sleeve.close)
            strategy=next(k for k in policies('pump') if 'survivor' in k);policy=policies('pump')[strategy]
            book=PaperBook(root/'pump/native-long.sqlite',run_id='long',lane=strategy,policy_hash=policy,initial=1_000_000)
            self.addCleanup(book.close);identity='long:original'
            sleeve.reserve(identity,strategy=strategy,amount=50_000,at=now,asset='asset:long',funding_evidence=dict(qualified=True))
            book.reserve(identity,50_000,now,dict(qualified=True))
            book.transition(identity,'filled',now,amount=50_000,tokens=400,evidence=dict(execution={'gas':0}))
            age=30*86400;at=now+age
            from meme_machine.runtime.usd_valuation import USDValue
            # New authenticated synthetic valuation at the new economic clock;
            # the old fixture's observation/expiry is never renewed in place.
            book.portfolio.value_reader=lambda t:USDValue('offline-native',3,Decimal('1'),t,t+5,'offline-long-'+str(t),'d'*64)
            risk=dict(opened_at=now,high_water_bps=10000,last_action=dict(action='hold',reason=None))
            book.transition(identity,'mark',at,amount=90_000,evidence=dict(risk_state=risk,observation=dict(evidence_current=True,after_cost_return_bps=8000)))
            def view(clock,projection=None):
                p=projection or export(a,at=clock);folder=root/'view';folder.mkdir(exist_ok=True)
                (folder/'inception.json').write_text(canonical(plan['seed']['inception']))
                (folder/'accounting.json').write_text(canonical(p))
                reader=Reader(folder/'inception.json',folder/'accounting.json',clock=lambda:clock,
                    expected_epoch=plan['seed']['epoch_id'],expected_inception_sha256=plan['seed']['inception_sha256'])
                return reader,reader.view(),p
            reader,v,p=view(at);row=v['positions'][0]
            self.assertEqual(row['entered_at'],utc(now).replace('+00:00','Z'));self.assertEqual(row['original_basis'],'50')
            self.assertEqual(row['age_seconds'],age);self.assertEqual(row['protection']['state'],'MONITORING')
            self.assertTrue(row['protection']['evidence_current']);self.assertEqual(row['protection']['trail']['return_floor_bps'],6000)
            # A current economic valuation cannot conceal stale monitoring.
            _,stale,_=view(at+6,p)
            self.assertEqual(stale['positions'][0]['protection']['state'],'DEGRADED_PROTECTION')
            self.assertFalse(stale['positions'][0]['protection']['evidence_current'])
            replica=root/'new-replica';receipt=plan['seed']['inception']
            packed=build_snapshot(receipt,p)
            bundle=root/'new-bundle.json';bundle.write_text(canonical(packed))
            apply_snapshot(bundle,replica,expected_epoch=receipt['epoch_id'],expected_inception_sha256=plan['seed']['inception_sha256'])
            paths=current_paths(replica)
            transported=Reader(paths['inception_path'],paths['accounting_path'],clock=lambda:at,
                expected_epoch=receipt['epoch_id'],expected_inception_sha256=plan['seed']['inception_sha256']).view()
            self.assertEqual(transported['positions'],v['positions'])
            # Pending exit publication uses durable native facts, no new oracle
            # purchase, fabricated valuation, proceeds or realized accounting.
            before=a.snapshot()['capital'];book.portfolio.value_reader=lambda *_:(_ for _ in ()).throw(AssertionError('no oracle for unavailable protection'))
            with patch('time.time',return_value=at+1):
                book.transition(identity,'mark',at+1,amount=90_000,evidence=dict(
                    risk_state=dict(risk,last_action=dict(action='full_exit',reason='hard_stop')),
                    observation=dict(after_cost_return_bps=None,evidence_current=False)))
            self.assertEqual(a.snapshot()['capital'],before)
            _,pending,_=view(at+1)
            self.assertEqual(pending['positions'][0]['protection']['state'],'EXIT_PENDING')
            self.assertEqual(pending['positions'][0]['protection']['last_reason'],'hard_stop')
            self.assertEqual(pending['positions'][0]['protection']['decision_kind'],'PROTECTIVE_EXIT')
            self.assertFalse(pending['positions'][0]['protection']['evidence_current'])
            self.assertIsNone(pending['positions'][0]['current_value']['value']);a.verify_replay()

    def test_four_actual_native_regimes_target_50_and_use_one_shared_authority(self):
        from meme_machine.runtime.directional_sleeve import open_sleeve,policies
        from meme_machine.lanes.pump.paper_accounting import PaperBook
        from meme_machine.runtime.directional_continuation import native_sync
        root,a,now,plan=self.fixture(policy=shared_risk_candidate(),new_epoch=True)
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
        root,a,now,_=self.fixture(policy=shared_risk_candidate(),new_epoch=True);(root/'pons').mkdir()
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
