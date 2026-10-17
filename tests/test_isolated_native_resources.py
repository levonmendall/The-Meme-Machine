"""Offline component proofs, not complete native bootstrap/held protection."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import hmac
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from meme_machine.runtime.directional_sleeve import open_sleeve, policies
from meme_machine.runtime.isolated_native_resources import (
    AuthenticatedSizingFacts, IsolatedFinancialWriteDenied,
    IsolatedNativeResources, NativeObservationState,
)
from meme_machine.runtime.journal import canonical


def receipt(now=1000):
    return dict(schema='isolated-native-sizing-v1', scope='offline-component-fixture',
        source_commit='a'*40, source_tree='b'*40, epoch_reference='parent-reference-only',
        portfolio_sequence=73, observed_at=now, valid_until=now+5,
        lanes={lane: dict(realized_equity=10**18, available=9*10**17, reserved=10**17,
            policies=policies(lane), native_unit='lamports' if lane=='pump' else 'wei',
            usd_evidence_hash='c'*64, valuation_observed_at=now,
            valuation_valid_until=now+(120 if lane=='pump' else 5)) for lane in ('pump','pons')})


def authenticated(value):
    # An offline test parent supplies authentication independently of the child
    # value. No production signer/provider/epoch is loaded by this fixture.
    key=b'offline-parent-only-key'
    signature=hmac.new(key,canonical(value).encode(),hashlib.sha256).digest()
    return AuthenticatedSizingFacts(value, authenticate=lambda candidate:
        hmac.compare_digest(signature,hmac.new(key,canonical(candidate).encode(),hashlib.sha256).digest()))


class IsolatedNativeResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/'owned'
        self.now=[1000]
        self.facts=authenticated(receipt())
        self.resources=IsolatedNativeResources(self.root,sizing_facts=self.facts,clock=lambda:self.now[0])

    def tearDown(self):
        self.resources.close()
        self.tmp.cleanup()

    def tables(self):
        result=set()
        for path in self.root.glob('*.sqlite'):
            with sqlite3.connect(path) as db:
                result.update(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        return result

    def assert_no_financial_tables(self):
        forbidden={'genesis','positions','journal','journal_archive','sleeve_genesis',
            'sleeve_positions','sleeve_journal','sleeve_archive','capital_genesis',
            'capital_positions','capital_journal','pons_selective_paper','portfolio_events',
            'portfolio_genesis','shared_capital_genesis','shared_capital_journal'}
        self.assertFalse(self.tables() & forbidden, self.tables() & forbidden)

    def test_authentication_immutability_expiry_and_positive_sizing(self):
        with self.assertRaisesRegex(ValueError,'authentication'):
            AuthenticatedSizingFacts(receipt(),authenticate=lambda _:False)
        with self.assertRaisesRegex(ValueError,'authentication'):
            AuthenticatedSizingFacts(receipt(),authenticate=None)
        with self.assertRaises(AttributeError):
            self.facts.receipt_hash='forged'
        detached=self.facts.value();detached['lanes']['pump']['available']=0
        basis=self.resources.basis('pump',500)
        self.assertEqual(basis['target'],5*10**16)
        self.assertEqual(basis['available'],9*10**17)
        self.assertFalse(basis['allocation_authority'])
        self.now[0]=1121
        with self.assertRaisesRegex(ValueError,'stale'):
            self.resources.basis('pump',500)

    def test_reject_existing_root_symlink_and_financial_ancestor(self):
        with self.assertRaises(FileExistsError):
            IsolatedNativeResources(self.root,sizing_facts=self.facts,clock=lambda:1000)
        alias=Path(self.tmp.name)/'alias';alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'root'):
            IsolatedNativeResources(alias/'nested',sizing_facts=self.facts,clock=lambda:1000)
        parent=Path(self.tmp.name)/'financial';parent.mkdir();(parent/'portfolio.sqlite').touch()
        with self.assertRaisesRegex(ValueError,'financial_ancestor'):
            IsolatedNativeResources(parent/'nested',sizing_facts=self.facts,clock=lambda:1000)

    def test_units_and_receipt_cannot_extend_native_valuation_validity(self):
        for lane,wrong in (('pump','wei'),('pons','lamports')):
            value=receipt();value['lanes'][lane]['native_unit']=wrong
            with self.subTest(lane=lane),self.assertRaisesRegex(ValueError,'lane_facts'):
                authenticated(value)
        for lane,ttl in (('pump',120),('pons',5)):
            value=receipt();value['lanes'][lane]['valuation_valid_until']=1000+ttl+1
            with self.subTest(lane=lane),self.assertRaisesRegex(ValueError,'lane_facts'):
                authenticated(value)
        value=receipt();value['valid_until']=1300
        with self.assertRaisesRegex(ValueError,'lane_facts'):
            authenticated(value)
        # A genuine SOL publication can already be old at parent capture. The
        # receipt must stop at its original expiry, rather than adding 120s.
        value=receipt();value['lanes']['pump'].update(
            valuation_observed_at=882,valuation_valid_until=1002)
        with self.assertRaisesRegex(ValueError,'lane_facts'):
            authenticated(value)
        value['valid_until']=1002
        facts=authenticated(value)
        self.assertGreater(facts.basis('pump',500,at=1002)['target'],0)
        with self.assertRaisesRegex(ValueError,'stale'):
            facts.basis('pump',500,at=1003)

    def test_authenticated_refresh_keeps_binding_sequence_and_underlying_expiry(self):
        self.now[0]=1004
        value=receipt(1004);value['portfolio_sequence']=74
        value['lanes']['pump']['realized_equity']=2*10**18
        refreshed=authenticated(value)
        outcome=self.resources.replace_authenticated_sizing_facts(refreshed)
        self.assertEqual(outcome['previous_receipt_hash'],self.facts.receipt_hash)
        self.assertEqual(outcome['receipt_hash'],refreshed.receipt_hash)
        self.assertFalse(outcome['allocation_authority'])
        self.assertEqual(self.resources.basis('pump',500)['target'],10**17)
        with self.assertRaises(AttributeError):self.resources.facts=self.facts
        for field,replacement in (('scope','other'),('source_commit','d'*40),
                ('source_tree','e'*40),('epoch_reference','other')):
            wrong=deepcopy(value);wrong[field]=replacement
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'binding_changed'):
                self.resources.replace_authenticated_sizing_facts(authenticated(wrong))
        wrong=deepcopy(value);wrong['portfolio_sequence']=73
        with self.assertRaisesRegex(ValueError,'sequence_regression'):
            self.resources.replace_authenticated_sizing_facts(authenticated(wrong))
        with self.assertRaisesRegex(ValueError,'sequence_regression'):
            self.resources.replace_authenticated_sizing_facts(self.facts)
        with self.assertRaisesRegex(ValueError,'authentication_required'):
            self.resources.replace_authenticated_sizing_facts(value)
        self.now[0]=1010
        with self.assertRaisesRegex(ValueError,'stale'):
            self.resources.basis('pump',500)
        with self.assertRaisesRegex(ValueError,'stale'):
            self.resources.replace_authenticated_sizing_facts(refreshed)
        current=receipt(1010);current['portfolio_sequence']=74
        self.resources.replace_authenticated_sizing_facts(authenticated(current))
        self.assertGreater(self.resources.basis('pons',500)['target'],0)

    def test_candidate_history_connections_are_owner_local_with_real_concurrent_transactions(self):
        main=self.resources.candidate_history()
        barrier=threading.Barrier(4,timeout=5);connections=[];errors=[]
        def consume(owner):
            try:
                with self.assertRaisesRegex(ValueError,'history_owner'):
                    self.resources.require_history(main)
                history=self.resources.candidate_history()
                self.resources.require_history(history)
                self.assertIs(history,self.resources.candidate_history())
                connections.append(history.db)
                barrier.wait()
                for index in range(20):
                    candidate=f'owner-{owner}-candidate-{index}'
                    decision=history.record_decision('pump',candidate,mode='current',observed_at=1000,
                        qualified=True,decision={'qualification':{'qualified':True}})
                    self.resources.deny_qualified(history,decision,'pump',candidate,mode='current',at=1000)
                history.close()
            except BaseException as error:errors.append(error)
        threads=[threading.Thread(target=consume,args=(owner,)) for owner in range(4)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors,[])
        self.assertEqual(len({id(db) for db in connections}),4)
        self.assertEqual(main.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],80)
        self.assertEqual(main.db.execute("SELECT COUNT(*) FROM funding WHERE status='denied'").fetchone()[0],80)
        self.assertEqual(len(self.resources._candidate_histories),1)
        self.assertEqual(self.resources._histories,[main])
        main.close()
        self.assertEqual(self.resources._candidate_histories,{})
        reopened=self.resources.candidate_history()
        self.assertEqual(reopened.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],80)
        self.assert_no_financial_tables()

    def test_new_history_owner_cannot_adopt_replaced_owned_database(self):
        original=self.resources.candidate_history()
        path=self.root/'candidate-history.sqlite'
        path.rename(self.root/'original-owned.sqlite')
        with sqlite3.connect(path) as foreign:foreign.execute('CREATE TABLE foreign_evidence(value)')
        before=path.read_bytes()
        with patch('sqlite3.connect',side_effect=AssertionError('opened replacement')):
            with self.assertRaisesRegex(ValueError,'foreign_state'):
                self.resources.require_history(original)
            with self.assertRaisesRegex(ValueError,'foreign_state'):
                self.resources.candidate_history()
            original.close()
            with self.assertRaisesRegex(ValueError,'foreign_state'):
                self.resources.candidate_history()
        self.assertEqual(path.read_bytes(),before)

    def test_native_observation_algorithms_reopen_without_financial_constructor(self):
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        self.assertIs(NativeObservationState.observe,SleeveReservations.observe)
        self.assertIs(NativeObservationState._observe_rally,SleeveReservations._observe_rally)
        self.assertIs(NativeObservationState._opportunity,SleeveReservations._opportunity)
        with patch('meme_machine.runtime.sleeve_reservations.SleeveReservations.__init__',
                   side_effect=AssertionError('financial constructor called')):
            state=open_sleeve('pump',1,native_resources=self.resources)
            strategy=next(iter(policies('pump')))
            from tests.test_rally_cycle_authority import cycle
            regime=dict(rally_cycle=cycle(policy_hash=policies('pump')[strategy]))
            row=state.observe('mint',strategy=strategy,at=1000,state='qualified',
                evidence={'source':'offline-canonical-fixture'},regime=regime)
            self.assertEqual(row['generation'],1)
            self.assertEqual(state.observe('mint',strategy=strategy,at=1000,state='qualified',
                evidence={'source':'offline-canonical-fixture'},regime=regime),row)
            self.assertEqual(state.rally('mint',strategy=strategy)['cycle'],regime['rally_cycle'])
            self.assertIsNotNone(state.opportunity('mint',identity='decision',regime='current',
                status='qualified',at=1000,decision={'qualification':{'qualified':True}}))
            proof=state.verify_observations();state.close()
            reopened=open_sleeve('pump',1,native_resources=self.resources)
            self.assertEqual(reopened.candidate('mint'),row)
            self.assertEqual(reopened.verify_observations(),proof)
            self.assertFalse(hasattr(reopened,'reserve'))
            self.assertFalse(hasattr(reopened,'reconcile'))
            self.assertFalse(hasattr(reopened,'replay'))
            self.assertEqual(proof['held_protection'],'UNEXERCISED')
            with self.assertRaises(IsolatedFinancialWriteDenied):
                reopened._event('reserved',dict(id='forbidden'))
        self.assert_no_financial_tables()

    def test_financial_constructors_and_attach_reject_before_any_open_or_genesis(self):
        from meme_machine.lanes.pump.paper_accounting import PaperBook as PumpBook
        from meme_machine.runtime.survivor_paper_book import PaperBook as SurvivorBook
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper
        from meme_machine.runtime.native_boundary import attach
        path=self.root/'must-not-exist.sqlite'
        kwargs=dict(run_id='r',lane='pump',policy_hash='p',initial=1000,native_resources=self.resources)
        store=Mock()
        calls=(lambda:PumpBook(path,**kwargs),lambda:SurvivorBook(path,**kwargs),
            lambda:SleeveReservations(path,lane='pump',capital=1000,policies=policies('pump'),
                cohort='c',native_resources=self.resources),
            lambda:CohortCapital(path,1000,native_resources=self.resources),
            lambda:SelectivePaper(store,'pons-selective-continuation-v1:test',1000,
                natural_policy_hash='p',native_resources=self.resources),
            lambda:attach(object(),'pump',native_resources=self.resources))
        with patch('sqlite3.connect',side_effect=AssertionError('SQLite opened')):
            for call in calls:
                with self.subTest(call=call):
                    with self.assertRaises(IsolatedFinancialWriteDenied):call()
        self.assertFalse(path.exists());self.assertEqual(store.mock_calls,[])

    def test_environment_cannot_select_or_redirect_native_resources(self):
        with patch.dict('os.environ',{'MM_DIRECTIONAL_SLEEVE_DB':str(self.root/'danger.sqlite'),
                'MM_DIRECTIONAL_COHORT_ID':'wrong','MM_PORTFOLIO_ACCOUNTING_DB':'/wrong/portfolio.sqlite',
                'MM_PAPER_EPOCH':'wrong','MM_ISOLATED_NATIVE_RESOURCES':'1'}):
            state=open_sleeve('pons',1,native_resources=self.resources)
            self.assertEqual(state.identity['cohort'],'offline-component-fixture')
            self.assertFalse((self.root/'danger.sqlite').exists())
        with patch.dict('os.environ',{},clear=True):
            self.assertIsNone(open_sleeve('pump',1000))
        with self.assertRaisesRegex(ValueError,'resources_required'):
            open_sleeve('pump',1,native_resources=object())
        self.assert_no_financial_tables()

    def current_signal(self):
        from tests.lanes.pump.test_pump_acceleration_strategy import PumpAccelerationStrategyTests
        return PumpAccelerationStrategyTests().strong_late()

    def test_actual_pump_current_decision_preserved_and_no_lifecycle_intent(self):
        from meme_machine.lanes.pump import runner
        from meme_machine.lanes.pump.pump_acceleration_strategy import qualify
        signal=self.current_signal();qualification=qualify(signal)
        self.assertTrue(qualification.qualified)
        history=self.resources.candidate_history()
        report=dict(qualifiers=[],attempts=[],full_evidence_candidates=[])
        snapshot=dict(available_time=1000,market_time=1000,slot=11)
        with patch.object(runner,'ACCOUNTING',None),patch.object(runner,'PIPELINE',None),\
                patch.object(runner,'CANDIDATE_HISTORY',history),\
                patch.object(runner,'FILL_PERSISTENCE_CONTEXT',None),\
                patch.object(runner.time,'time',return_value=1000),\
                patch.object(runner,'PumpAccelerationPaperLifecycle',side_effect=AssertionError('intent created')):
            decision=runner._record_attempt(report,signal,qualification,'full_point_in_time',
                snapshot=snapshot,native_resources=self.resources)
            prior=history.db.execute('SELECT * FROM decisions').fetchall()
            self.assertFalse(runner._reserve_position(report,{}, {},signal,qualification,snapshot,
                signal.phase,decision_id=decision['decision_id'],native_resources=self.resources))
            self.assertEqual(history.db.execute('SELECT * FROM decisions').fetchall(),prior)
        denial=report['funding_denials'][0]
        self.assertTrue(denial['qualification_preserved'])
        self.assertGreater(denial['sizing']['target'],0)
        self.assertEqual(denial['reason'],'isolated_native_no_allocation')
        self.assertEqual(history.db.execute('SELECT status FROM funding').fetchall(),[('denied',)])
        self.assertEqual(len(report['full_evidence_candidates']),1)
        with patch.object(runner,'PIPELINE',Mock()),patch.object(runner,'CANDIDATE_HISTORY',history):
            with self.assertRaisesRegex(ValueError,'existing_runtime_resources'):
                runner._record_attempt(report,signal,qualification,'full_point_in_time',
                    snapshot=snapshot,native_resources=self.resources)
            with self.assertRaisesRegex(ValueError,'existing_runtime_resources'):
                runner._reserve_position(report,{}, {},signal,qualification,snapshot,
                    signal.phase,decision_id=decision['decision_id'],native_resources=self.resources)
        self.assert_no_financial_tables()

    def test_repeated_actual_current_helpers_retain_only_live_sleeves(self):
        from meme_machine.lanes.pump import runner
        from meme_machine.lanes.pump.pump_acceleration_strategy import qualify
        signal=self.current_signal();qualification=qualify(signal)
        history=self.resources.candidate_history()
        report=dict(qualifiers=[],attempts=[],full_evidence_candidates=[])
        with patch.object(runner,'ACCOUNTING',None),patch.object(runner,'PIPELINE',None),\
                patch.object(runner,'FILL_PERSISTENCE_CONTEXT',None),\
                patch.object(runner,'CANDIDATE_HISTORY',history):
            for _ in range(100):
                runner._record_attempt(report,signal,qualification,'full_point_in_time',
                    snapshot=dict(available_time=1000,market_time=1000,slot=11),native_resources=self.resources)
                self.assertGreater(runner._current_pump_sizing(native_resources=self.resources)['target'],0)
                self.assertEqual(len(self.resources._sleeves),0)
        live=[open_sleeve(lane,1,native_resources=self.resources) for lane in ('pump','pons')]
        self.assertEqual(len(self.resources._sleeves),2)
        self.resources.close()
        self.assertTrue(all(s.closed for s in live))
        self.assertEqual(len(self.resources._sleeves),0)
        self.assert_no_financial_tables()

    def test_deny_requires_owned_committed_qualified_untampered_decision(self):
        history=self.resources.candidate_history()
        decision=history.record_decision('pump','mint',mode='current',observed_at=1000,
            qualified=False,decision={'qualification':{'qualified':False}})
        with self.assertRaisesRegex(ValueError,'qualification_invalid'):
            self.resources.deny_qualified(history,decision,'pump','mint',mode='current',at=1000)
        with self.assertRaisesRegex(ValueError,'qualification_required'):
            self.resources.deny_qualified(history,'missing','pump','mint',mode='current',at=1000)
        decision=history.record_decision('pump','other',mode='current',observed_at=1000,
            qualified=True,decision={'qualification':{'qualified':True}})
        with history.transaction():
            with self.assertRaisesRegex(ValueError,'uncommitted_qualification'):
                self.resources.deny_qualified(history,decision,'pump','other',mode='current',at=1000)
        with self.assertRaisesRegex(ValueError,'qualification_mismatch'):
            self.resources.deny_qualified(history,decision,'pump','other',mode='current',at=1000,
                qualification={'qualified':False})
        with self.assertRaisesRegex(ValueError,'qualification_mismatch'):
            self.resources.deny_qualified(history,decision,'pump','other',mode='current',at=1000,
                stage='full_point_in_time')
        with self.assertRaisesRegex(ValueError,'stale'):
            self.resources.deny_qualified(history,decision,'pump','other',mode='current',at=1121)
        self.now[0]=1006
        with self.assertRaisesRegex(ValueError,'stale'):
            self.resources.deny_qualified(history,decision,'pump','other',mode='current',at=1000)
        self.now[0]=1000
        with self.assertRaisesRegex(ValueError,'history_owner'):
            self.resources.deny_qualified(object(),decision,'pump','other',mode='current',at=1000)
        history.db.execute("UPDATE decisions SET hash='tampered' WHERE id=?",(decision,))
        with self.assertRaisesRegex(ValueError,'qualification_invalid'):
            self.resources.deny_qualified(history,decision,'pump','other',mode='current',at=1000)
        self.assertEqual(history.db.execute('SELECT COUNT(*) FROM funding').fetchone()[0],0)

    def test_all_four_real_qualifiers_keep_positive_budget_before_common_denial(self):
        """Component parity only: three complete native runner loops are absent."""
        from meme_machine.lanes.pump.pump_acceleration_strategy import qualify
        from meme_machine.lanes.pump.pumpswap_survivor import evaluate_entry as pump_survivor
        from tests.lanes.pump.test_pumpswap_survivor import facts as pump_facts
        from tests.lanes.pons.test_pons_postgrad_survivor import facts as pons_facts
        from meme_machine.lanes.pons.pons_postgrad_survivor import evaluate_entry as pons_survivor
        from tests.lanes.pons.test_pons_selective_continuation import vector as pons_current
        capital=self.resources.basis('pons',500)['realized_equity']
        current=asdict(qualify(self.current_signal()))
        pump=pump_survivor(pump_facts())
        pons=pons_survivor(pons_facts(capital_quote=capital))
        selective=pons_current(strategy_capital_quote=capital)
        cases=(('pump','current',current,current['qualified'],1000),
               ('pump','survivor',pump,pump['candidate'],pump_facts()['now']),
               ('pons','current',selective,selective['current_threshold_pass'],202),
               ('pons','survivor',pons,pons['candidate'],pons_facts()['now']))
        for lane,mode,decision,qualified,at in cases:
            with self.subTest(lane=lane,mode=mode):
                # Each native fixture keeps its genuine clock. Parent facts
                # are authenticated at that clock rather than backdating it.
                resources=IsolatedNativeResources(Path(self.tmp.name)/(lane+'-'+mode),
                    sizing_facts=authenticated(receipt(at)),clock=lambda:at)
                self.addCleanup(resources.close)
                history=resources.candidate_history()
                self.assertGreater(resources.basis(lane,500)['target'],0)
                with patch('sqlite3.connect',side_effect=AssertionError('financial constructor opened')):
                    self.assertTrue(qualified,decision)
                    identity=history.record_decision(lane,lane+'-'+mode,mode=mode,observed_at=at,
                        qualified=qualified,decision=deepcopy(decision))
                    denied=resources.deny_qualified(history,identity,lane,lane+'-'+mode,mode=mode,at=at)
                    self.assertTrue(denied['qualification_preserved'])
                self.assertEqual(history.db.execute('SELECT COUNT(*) FROM funding WHERE status=\'denied\'').fetchone()[0],1)
                resources.close()
        self.assert_no_financial_tables()
