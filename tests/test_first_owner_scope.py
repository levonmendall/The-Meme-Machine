"""Offline funding-scope regressions; no provider or operating portfolio I/O."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from meme_machine.operational.admission import configure,decision,available
from meme_machine.operational.position_continuation import (
    funding_scope,position_lanes,readiness,validate_envelope,
)
from meme_machine.operational.supervisor import Supervisor
from meme_machine.shared_capital.model import CapitalError
from tests.test_position_continuation import envelope,healthy,proof


def resources(regimes=('pump_survivor',)):
    row=envelope()
    row['bootstrap_funding_scope']=dict(regimes=list(regimes),
        maximum_initial_basis_usd='50',maximum_addition_basis_usd='25',
        maximum_fee_reserve_usd='2')  # Synthetic allowance, not an owner approval.
    return row


def scoped_state(row=None):
    row=resources() if row is None else row
    health,portfolio,rss=healthy()
    state=dict(positions={},reservations={},commitments={},runtime_pending={},
        runtime_native_requests={},native_aliases={},runtime_admission=dict(
            mode='OBSERVATION',run_id='fixture',started_at=100,
            continuation_envelope=row,bootstrap_used=False))
    configure(state,dict(mode='BOOTSTRAP',run_id='fixture',
        continuation_ready=readiness(health,portfolio,rss,row)),100)
    return state


def grant(state,basis,total,*,regime='pump_survivor',kind='new',life='pump:owner'):
    key='pump:lot'+(':scale' if kind=='scale' else '')
    state['native_aliases']['pump:lot']=life
    state['runtime_native_requests'][key]=kind
    return decision(state,dict(request_id=kind,regime=regime,kind=kind),
        dict(status='RESERVED',basis=basis,total=total),101)


class ScopeTests(unittest.TestCase):
    def test_original_five_hundred_epoch_can_bound_basis_and_fees_separately(self):
        row=resources()
        row['bootstrap_funding_scope'].update(maximum_initial_basis_usd='25',
            maximum_addition_basis_usd='12.50',maximum_fee_reserve_usd='0.10')
        state=scoped_state(row)
        self.assertEqual(grant(state,'25','25.05')['status'],'RESERVED')
        self.assertEqual(grant(state,'12.50','12.55',kind='scale')['status'],'RESERVED')
        before=deepcopy(state['runtime_admission'])
        self.assertEqual(grant(state,'0.01','0.01',kind='scale')['reason'],'bootstrap_basis_limit')
        self.assertEqual(state['runtime_admission'],before)

    def test_restart_preserves_claimed_basis_fees_identity_and_closed_funding(self):
        state=scoped_state()
        self.assertEqual(grant(state,'50','51')['status'],'RESERVED')
        before=deepcopy(state['runtime_admission'])
        configure(state,dict(mode='OBSERVATION',run_id='fixture',pid=123,
            process_start='fixture-start',continuation_envelope=resources()),102)
        after=state['runtime_admission']
        for key in ('initial_basis_reserved','addition_basis_reserved','fee_reserved',
                    'gross_reserved','lifecycle_id','started_at','funding_until','bootstrap_used'):
            self.assertEqual(after[key],before[key])
        self.assertEqual(available(state,103),'observation_only_funding_closed')
        with self.assertRaisesRegex(CapitalError,'bootstrap_requires_unused_observation_run'):
            configure(state,dict(mode='BOOTSTRAP',run_id='fixture',
                continuation_ready=before['continuation_ready']),103)

    def test_selected_scope_still_requires_all_pump_safety_and_financial_gates(self):
        row=resources()
        for gate in ('reconciliation','subscription','provider','resource','native_exit'):
            with self.subTest(gate=gate):
                health,portfolio,rss=healthy()
                del health['lanes']['pons']
                del health['providers']['robinhood']
                if gate=='reconciliation':portfolio['reconciliation']['checks']['exact_conservation']=False
                elif gate=='subscription':health['providers']['evidence']['startup_released']=False
                elif gate=='provider':health['providers']['solana']['state']='STALE'
                elif gate=='resource':health['continuation_resources']['limits_verified']=False
                else:health['lanes']['pump']['native_continuation']['exit_path_bound']=False
                with self.assertRaises(ValueError):readiness(health,portfolio,rss,row)

    def test_scope_requires_exact_basis_fee_and_selected_family(self):
        for field,value in [('maximum_fee_reserve_usd',None),('maximum_initial_basis_usd','51'),
                            ('maximum_initial_basis_usd',50.0),('maximum_addition_basis_usd','26'),
                            ('maximum_fee_reserve_usd','-1'),('regimes',['pump_survivor','pons_survivor']),
                            ('regimes',['pump_survivor','pump_survivor']),('regimes',['meteora'])]:
            with self.subTest(field=field):
                row=resources();row['bootstrap_funding_scope'][field]=value
                with self.assertRaises(CapitalError):validate_envelope(row)

    def test_selected_readiness_does_not_require_an_unfunded_provider(self):
        for selected,excluded in [('pump','pons'),('pons','pump')]:
            with self.subTest(selected=selected):
                health,portfolio,rss=healthy();row=resources((selected+'_survivor',))
                del health['lanes'][excluded]
                del health['providers']['robinhood' if excluded=='pons' else 'solana']
                if selected=='pons':del health['providers']['evidence']
                evidence=readiness(health,portfolio,rss,row)
                self.assertEqual(evidence['funding_regimes'],[selected+'_survivor'])
                health['lanes'][selected]['native_continuation']['exit_path_bound']=False
                with self.assertRaises(ValueError):readiness(health,portfolio,rss,row)

    def test_legacy_readiness_and_state_remain_unchanged(self):
        state=scoped_state(envelope());scope=state['runtime_admission']
        self.assertNotIn('fee_reserved',scope)
        self.assertNotIn('funding_regimes',scope['continuation_ready'])
        self.assertEqual(grant(state,'25','25')['status'],'RESERVED')
        self.assertEqual(grant(state,'0.01','0.01',kind='scale')['reason'],'bootstrap_gross_capital_limit')
        health,portfolio,rss=healthy();del health['lanes']['pons']
        with self.assertRaises(KeyError):readiness(health,portfolio,rss,envelope())

    def test_generic_or_other_regime_proof_cannot_arm_selected_scope(self):
        state=scoped_state();scope=state['runtime_admission']
        scope.update(mode='OBSERVATION',bootstrap_used=False)
        before=deepcopy(state)
        for value in (proof(),dict(proof(),funding_regimes=['pons_survivor'])):
            with self.assertRaisesRegex(CapitalError,'selected_regime_continuation_not_ready'):
                configure(state,dict(mode='BOOTSTRAP',run_id='fixture',continuation_ready=value),101)
            self.assertEqual(state,before)

    def test_fifty_basis_and_twenty_five_addition_have_separate_fee_reserve(self):
        state=scoped_state()
        self.assertEqual(grant(state,'50','51')['status'],'RESERVED')
        self.assertEqual(grant(state,'25','26',kind='scale')['status'],'RESERVED')
        scope=state['runtime_admission']
        self.assertEqual((scope['initial_basis_reserved'],scope['addition_basis_reserved'],
                          scope['fee_reserved'],scope['gross_reserved']),('50','25','2','77'))
        before=deepcopy(scope)
        self.assertEqual(grant(state,'0.01','0.01',kind='scale')['reason'],'bootstrap_basis_limit')
        self.assertEqual(scope,before)

    def test_oversized_strategy_request_is_refused_without_clipping_or_consumption(self):
        state=scoped_state();before=deepcopy(state['runtime_admission'])
        result=grant(state,'50.01','50.01')
        self.assertEqual(result['reason'],'bootstrap_basis_limit')
        self.assertEqual(state['runtime_admission'],before)

    def test_fee_exhaustion_does_not_spend_principal_or_refill_after_exit(self):
        state=scoped_state()
        self.assertEqual(grant(state,'50','52')['status'],'RESERVED')
        before=deepcopy(state['runtime_admission'])
        self.assertEqual(grant(state,'25','25.01',kind='scale')['reason'],'bootstrap_fee_reserve_limit')
        self.assertEqual(state['runtime_admission'],before)
        state['positions'].clear()
        self.assertEqual(grant(state,'1','1',life='pump:second')['reason'],'bootstrap_one_lifecycle_limit')
        self.assertEqual(state['runtime_admission'],before)

    def test_selected_funding_does_not_narrow_protection_of_existing_obligations(self):
        state=scoped_state()
        self.assertEqual(grant(state,'1','1',regime='pons_survivor')['reason'],'bootstrap_regime_not_selected')
        self.assertIsNone(state['runtime_admission']['lifecycle_id'])
        state['positions']['held']=dict(status='OPEN',regime='pons_survivor')
        state['reservations']['pending']=dict(regime='pump_survivor')
        self.assertEqual(position_lanes(state),('pump','pons'))
        self.assertEqual(available(state,1300),'bootstrap_funding_deadline')
        self.assertEqual(state['positions']['held']['status'],'OPEN')


class SharedAuthorityTests(unittest.TestCase):
    from tests.test_pump_pons_capital_preparation import RuntimeIntegrationTests as Native
    fixture=Native.fixture
    queue=Native.queue

    def test_flat_unfunded_pons_owner_cannot_veto_pump_first_shared_allocation(self):
        import os
        root,a,now,s=self.service('pump')
        health,portfolio,rss=healthy()
        a.command('arm-pump-only','runtime_admission',dict(s.admission_data,mode='BOOTSTRAP',
            continuation_ready=readiness(health,portfolio,rss,s.admission_data['continuation_envelope'])),now)
        for r in ('pons_current','pons_survivor'):
            a.owner(r,'unfunded-not-ready',os.getpid(),ready=False,at=now)
        self.queue(a,'pump_survivor','pump-only',now)
        a.drain(at=now)
        self.assertEqual(a.ledger()['requests']['pump-only']['status'],'RESERVED')
        self.assertFalse(any(p['regime'].startswith('pons') for p in a.ledger()['reservations'].values()))
        a.verify_replay()

    def test_pump_first_quorum_still_includes_every_unselected_position_or_obligation(self):
        from meme_machine.shared_capital.runtime import allocation_regimes,ACTIVE_REGIMES
        state=scoped_state(resources(('pump_current','pump_survivor')))
        self.assertEqual(allocation_regimes(state),('pump_current','pump_survivor'))
        obligations=(('positions',{'held':dict(regime='pons_current',status='OPEN')}),
                     ('reservations',{'held':dict(regime='pons_survivor')}),
                     ('commitments',{'held':dict(regime='pons_current')}),
                     ('obligations',{'held':dict(regime='pons_survivor')}),
                     ('pending_deliveries',{'held':dict(lane='pons')}),
                     ('runtime_pending',{'held':dict(lane='pons')}),
                     ('runtime_inbox',{'held':dict(regime='pons_survivor')}))
        for key,value in obligations:
            with self.subTest(obligation=key):
                changed=deepcopy(state);changed[key]=value
                self.assertEqual(allocation_regimes(changed),ACTIVE_REGIMES)
        for mode in ('NORMAL','AUTONOMY','CONTINUATION','OBSERVATION'):
            changed=deepcopy(state);changed['runtime_admission']['mode']=mode
            self.assertEqual(allocation_regimes(changed),ACTIVE_REGIMES)
        changed=deepcopy(state);changed['runtime_admission']['continuation_envelope'].pop('bootstrap_funding_scope')
        self.assertEqual(allocation_regimes(changed),ACTIVE_REGIMES)

    def test_unfunded_manifest_exception_never_waives_selected_owner_readiness(self):
        import os
        root,a,now,s=self.service('pump')
        health,portfolio,rss=healthy()
        a.command('arm-selected-owners','runtime_admission',dict(s.admission_data,mode='BOOTSTRAP',
            continuation_ready=readiness(health,portfolio,rss,s.admission_data['continuation_envelope'])),now)
        self.queue(a,'pump_survivor','selected-required',now)
        a.owner('pump_current','selected-not-ready',os.getpid(),ready=False,at=now)
        with self.assertRaisesRegex(CapitalError,'missing_active_manifest:pump_current'):a.drain(at=now)
        self.assertTrue(a.ledger()['runtime_inbox']);self.assertFalse(a.ledger()['reservations'])
        a.verify_replay()

    def test_scoped_round_fences_quorum_changes_and_replays_original_manifest_semantics(self):
        from meme_machine.shared_capital.runtime import ACTIVE_REGIMES
        root,a,now,s=self.service('pump')
        health,portfolio,rss=healthy()
        a.command('arm-fenced-quorum','runtime_admission',dict(s.admission_data,mode='BOOTSTRAP',
            continuation_ready=readiness(health,portfolio,rss,s.admission_data['continuation_envelope'])),now)
        self.queue(a,'pump_survivor','fenced-round',now)
        state=a.ledger();data=dict(request_ids=sorted(state['runtime_inbox']),owners=state['runtime_owners'])
        with self.assertRaisesRegex(CapitalError,'missing_or_changed_active_manifest'):
            a.command('changed-quorum','runtime_allocate',dict(data,required_regimes=list(ACTIVE_REGIMES)),now)
        self.assertTrue(a.ledger()['runtime_inbox']);self.assertFalse(a.ledger()['reservations'])
        # Historical round shape has no scoped quorum field and still needs
        # all four ready owners. Its deterministic replay remains supported.
        a.command('old-four-owner-round','runtime_allocate',data,now)
        self.assertEqual(a.ledger()['requests']['fenced-round']['status'],'RESERVED')
        a.verify_replay()

    def service(self,family):
        from tests.test_paper_bootstrap import AdmissionTests
        root,a,now,_=self.fixture()
        budget,data=AdmissionTests.scope(self,a,now,root,arm=False,resources=resources((family+'_survivor',)))
        s=Supervisor(root,offline=True,admission='BOOTSTRAP')
        s.shared_capital=a;s.provider_budget=budget;s.run_id=data['run_id'];s.admission_data=data
        s.ready_since=None;s.ready_frontiers={};s.bootstrap_armed=False
        return root,a,now,s

    def test_unselected_native_funding_refuses_before_funding_only_USD_acquisition(self):
        from meme_machine.runtime.directional_sleeve import open_sleeve,policies
        from meme_machine.shared_capital.native_sleeve import FundingDenied
        from meme_machine.operational.admission import configure
        root,a,now,s=self.service('pump')
        health,portfolio,rss=healthy()
        a.command('arm-native-scope','runtime_admission',dict(s.admission_data,mode='BOOTSTRAP',
            continuation_ready=readiness(health,portfolio,rss,s.admission_data['continuation_envelope'])),now)
        sleeve=open_sleeve('pump',125000);self.addCleanup(sleeve.close)
        strategy=next(p for p in policies('pump') if 'survivor' not in p)
        with patch('meme_machine.runtime.usd_valuation.native_reader',side_effect=AssertionError('unfunded USD acquisition')):
            with self.assertRaisesRegex(FundingDenied,'bootstrap_regime_not_selected'):
                sleeve._grant('unselected',strategy=strategy,units=6250,at=now,asset='fixture-asset',evidence={})
        self.assertFalse(a.ledger()['reservations']);a.verify_replay()

    def test_sixty_seconds_progress_only_selected_family_and_atomic_shared_grant(self):
        from meme_machine.shared_capital.operational_candidate import ACTIVE_REGIMES
        for family in ('pump','pons'):
            with self.subTest(family=family):
                root,a,now,s=self.service(family)
                def sample(slot):
                    health,portfolio,rss=healthy();excluded='pons' if family=='pump' else 'pump'
                    del health['lanes'][excluded]
                    del health['providers']['robinhood' if excluded=='pons' else 'solana']
                    if family=='pump':
                        health['providers']['evidence']['frontiers']=[dict(scope='program:'+p,slot=slot) for p in ('pump','pumpswap')]
                    else:
                        del health['providers']['evidence'];health['active_evidence']=dict(pons_canonical_cursor=slot)
                    return health,portfolio,rss
                start=s.provider_budget.started
                for elapsed,slot in [(0,1),(59,2),(60,2)]:
                    with patch('meme_machine.operational.acceptance.observe',return_value=sample(slot)),patch('time.monotonic',return_value=start+elapsed):
                        s.bootstrap_tick()
                    self.assertEqual(s.bootstrap_armed,elapsed==60)
                for regime in ACTIVE_REGIMES:self.queue(a,regime,regime,now)
                a.drain(at=now)
                state=a.ledger();granted=[r for r in state['requests'].values() if r['status']=='RESERVED']
                self.assertEqual(len(granted),1)
                self.assertEqual(granted[0]['value']['regime'],family+'_survivor')
                self.assertEqual(len(state['observations']),4)
                a.verify_replay()
                with patch('meme_machine.operational.acceptance.observe',side_effect=ValueError('native_fault')):
                    s.bootstrap_tick()
                self.assertFalse(s.stop_requested)
                self.assertEqual(a.ledger()['runtime_admission']['mode'],'CONTINUATION')
                self.assertTrue(a.ledger()['reservations'])
                a.verify_replay()


if __name__=='__main__':unittest.main()
