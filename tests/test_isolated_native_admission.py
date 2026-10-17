"""Actual native publication/admission methods; complete bootstrap is absent."""
from copy import deepcopy
from dataclasses import asdict,is_dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from meme_machine.runtime.directional_sleeve import open_sleeve
from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
from tests.test_isolated_native_resources import authenticated, receipt


class IsolatedNativeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.resources=[]

    def tearDown(self):
        for resources in reversed(self.resources):resources.close()
        self.tmp.cleanup()

    def owned(self,at=1000):
        now=[at]
        resources=IsolatedNativeResources(Path(self.tmp.name)/('owned-'+str(len(self.resources))),
            sizing_facts=authenticated(receipt(at)),clock=lambda:now[0])
        self.resources.append(resources)
        return resources,now

    def assert_no_money(self,resources):
        forbidden={'genesis','positions','journal','journal_archive','sleeve_genesis',
            'sleeve_positions','sleeve_journal','capital_genesis','capital_positions',
            'capital_journal','pons_selective_paper','portfolio_genesis','portfolio_events'}
        for path in resources.root.glob('*.sqlite'):
            with sqlite3.connect(path) as db:
                names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertFalse(names & forbidden,names & forbidden)

    def survivor(self,lane,*,qualified=True):
        if lane=='pump':
            from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime
            from meme_machine.lanes.pump.pumpswap_survivor import evaluate_entry
            from tests.lanes.pump.test_pumpswap_survivor import facts
            f=facts()
            if not qualified:f['lineage_proven']=False
            decision=evaluate_entry(f);at=f['now'];candidate='mint'
        else:
            from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
            from tests.lanes.pons.test_pons_postgrad_survivor import PonsPostgradSurvivorTests
            f=PonsPostgradSurvivorTests().cycle_facts()
            if not qualified:f['lineage_proven']=False
            at=f['now'];candidate='native-token'
            with patch('meme_machine.lanes.pons.pons_survivor_runtime.time.time',return_value=at):
                decision=object.__new__(Runtime).qualify(f)
        self.assertEqual(decision['candidate'],qualified,decision)
        resources,now=self.owned(at)
        runtime=object.__new__(Runtime)
        runtime.native_resources=resources
        runtime.now=lambda:now[0]
        runtime.history=resources.survivor_history(lane)
        runtime.sleeve=open_sleeve(lane,1,native_resources=resources)
        runtime.candidate_history=resources.candidate_history()
        runtime.history.graduate(candidate,dict(at=f['graduation_at'],identity='offline-native-graduation'))
        runtime._enter=Mock(side_effect=AssertionError('native intent created'))
        if lane=='pons':
            from meme_machine.lanes.pons.pons_attempts import Attempts
            runtime.plane=resources.pons_plane();runtime.attempts=Attempts(runtime.plane)
        return runtime,decision,resources,now

    def publish_survivor(self,runtime,decision,lane):
        row=runtime.history.rows()[0]
        at=runtime.now()
        state=dict(market_time=at,at=at,slot=11,block=11,block_hash='offline-canonical-block')
        regime=dict(at=at)
        if decision.get('rally_cycle'):regime['rally_cycle']=decision['rally_cycle']
        with patch('meme_machine.lanes.pons.pons_survivor_runtime.time.time',return_value=at):
            row,_,_=runtime._publish_qualification(row,decision,regime,state=state)
        return row

    def test_pump_survivor_real_publication_then_denial_without_book_or_intent(self):
        runtime,decision,resources,_=self.survivor('pump')
        with self.assertRaisesRegex(ValueError,'qualification_required'):
            runtime._allocation_allowed(runtime.history.rows()[0],decision)
        row=self.publish_survivor(runtime,decision,'pump')
        shared=resources.candidate_history()
        before=shared.db.execute('SELECT * FROM decisions').fetchall()
        with patch('meme_machine.runtime.lifecycle_identity.issue',side_effect=AssertionError('identity issued')):
            if decision['candidate'] and runtime._allocation_allowed(row,decision):runtime._enter(row)
        self.assertEqual(shared.db.execute('SELECT * FROM decisions').fetchall(),before)
        self.assertFalse(hasattr(runtime,'book'));runtime._enter.assert_not_called()
        saved=runtime.history.get(row['id'])
        self.assertIsNone(saved['position'])
        self.assertTrue(saved['decision']['candidate'])
        self.assertEqual(saved['funding_denial']['reason'],'isolated_native_no_allocation')
        self.assertEqual(shared.db.execute('SELECT status FROM funding').fetchall(),[('denied',)])
        self.assert_no_money(resources)

    def test_pons_survivor_real_plane_attempt_history_then_denial(self):
        runtime,decision,resources,_=self.survivor('pons')
        row=self.publish_survivor(runtime,decision,'pons')
        qualified=deepcopy(runtime.attempts.rows(row['id']))
        self.assertEqual(qualified[0]['category'],'QUALIFIED')
        plane_before=runtime.plane.get('pons:survivor:'+row['id'])
        with patch('meme_machine.runtime.lifecycle_identity.issue',side_effect=AssertionError('identity issued')):
            if decision['candidate'] and runtime._allocation_allowed(row,decision):runtime._enter(row)
        self.assertEqual(runtime.attempts.rows(row['id'])[:len(qualified)],qualified)
        self.assertEqual(runtime.attempts.rows(row['id'])[-1]['reason'],'isolated_native_no_allocation')
        self.assertEqual(runtime.plane.get('pons:survivor:'+row['id']),plane_before)
        saved=runtime.history.get(row['id'])
        self.assertIsNone(saved['position']);self.assertTrue(saved['decision']['candidate'])
        self.assertEqual(saved['funding_denial']['reason'],'isolated_native_no_allocation')
        self.assertFalse(hasattr(runtime,'book'));runtime._enter.assert_not_called()
        self.assert_no_money(resources)

    def current_pons(self,*,qualified=True,record_attempt=True):
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        from meme_machine.lanes.pons.pons_attempts import Attempts,decision_category
        from tests.lanes.pons.test_pons_selective_continuation import vector,state
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        resources,now=self.owned(202)
        plane=resources.pons_plane();attempts=Attempts(plane)
        v=vector(strategy_capital_quote=resources.basis('pons',500)['realized_equity'],
            current_snipe_bps=0 if qualified else 1)
        self.assertEqual(v['current_threshold_pass'],qualified,v)
        evaluation=dict(vector=v,token='native-token',curve='native-curve',evaluation_completed_at=202,
            candidate=dict(state=state()))
        plane.observe('pons:native-curve','pons','canonical-observation',{'nomination':'offline-fixture'},
            ordering=(11,),watermark=dict(block=11,hash='canonical-block'),
            interpretation=dict(policy=POLICY_HASH),observed=202,deadline=207,priority=4)
        work=plane.claim(lane='pons');self.assertIsNotNone(work)
        # Same typed serialization contract as Broker.finish; the gate gets
        # the actual native dataclass result, rather than a simplified sample.
        encoded=json.loads(json.dumps(evaluation,default=lambda item:asdict(item) if is_dataclass(item) else None))
        self.assertTrue(plane.finish(work,result=encoded))
        self.assertTrue(plane.decision(work['id'],work['generation'],'qualified' if qualified else 'strategy_rejected'))
        if record_attempt:
            cohort._record_qualification(attempts,work['id'],work['generation'],evaluation,
                decision_category(evaluation),at=202,explanation={'offline':'unchanged-native-reentry'})
        return cohort,SimpleNamespace(plane=plane,clock=lambda:now[0]),dict(key=work['id'],work=work),evaluation,attempts,resources,now

    def test_pons_current_actual_committed_result_and_attempt_before_denial(self):
        cohort,queue,scheduled,evaluation,attempts,resources,_=self.current_pons()
        before=queue.plane.get(scheduled['key'])
        original_attempts=attempts.rows(scheduled['key'])
        with patch('meme_machine.lanes.pons.pons_selective_cohort.run_lifecycle',
                side_effect=AssertionError('controller created')):
            self.assertFalse(cohort._allocation_allowed(queue,scheduled,evaluation,attempts,
                native_resources=resources))
        after=queue.plane.get(scheduled['key'])
        self.assertEqual(after['result'],before['result'])
        self.assertEqual(after['generation'],before['generation'])
        self.assertEqual(after['state'],'funding_denied')
        self.assertEqual(attempts.rows(scheduled['key'])[:1],original_attempts)
        self.assertEqual(attempts.rows(scheduled['key'])[-1]['execution']['entry_authorized'],False)
        kinds=[r[0] for r in queue.plane.db.execute('SELECT kind FROM transitions ORDER BY seq')]
        self.assertIn('qualified',kinds);self.assertIn('funding_denied',kinds)
        self.assertNotIn('entry_confirmation',kinds);self.assertNotIn('entry_reserved',kinds)
        self.assertEqual(queue.plane.db.execute("SELECT COUNT(*) FROM runtime WHERE key LIKE 'native_entry_generation:%'").fetchone()[0],0)
        self.assert_no_money(resources)

    def test_native_negative_qualifications_publish_without_funding_disposition(self):
        for lane in ('pump','pons'):
            runtime,decision,resources,_=self.survivor(lane,qualified=False)
            row=self.publish_survivor(runtime,decision,lane)
            self.assertFalse(runtime.history.get(row['id'])['decision']['candidate'])
            if decision['candidate'] and runtime._allocation_allowed(row,decision):runtime._enter(row)
            runtime._enter.assert_not_called()
            shared=resources.candidate_history()
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM funding').fetchone()[0],0)
            self.assert_no_money(resources)
        cohort,queue,scheduled,evaluation,attempts,resources,_=self.current_pons(qualified=False)
        with self.assertRaisesRegex(ValueError,'current_qualification'):
            cohort._allocation_allowed(queue,scheduled,evaluation,attempts,native_resources=resources)
        self.assertEqual(attempts.rows(scheduled['key'])[0]['category'],'STRATEGY_REJECT')
        self.assertEqual(resources.candidate_history().db.execute('SELECT COUNT(*) FROM funding').fetchone()[0],0)
        self.assert_no_money(resources)
        from meme_machine.lanes.pump import runner
        from meme_machine.lanes.pump.pump_acceleration_strategy import qualify
        from tests.lanes.pump.test_pump_acceleration_strategy import PumpAccelerationStrategyTests
        signal=PumpAccelerationStrategyTests().strong_late(curve_velocity_bps_per_s=0)
        qualification=qualify(signal);self.assertFalse(qualification.qualified)
        resources,_=self.owned(1000);shared=resources.candidate_history()
        report=dict(qualifiers=[],attempts=[],full_evidence_candidates=[])
        with patch.object(runner,'ACCOUNTING',None),patch.object(runner,'PIPELINE',None),\
                patch.object(runner,'FILL_PERSISTENCE_CONTEXT',None),\
                patch.object(runner,'CANDIDATE_HISTORY',shared):
            attempt=runner._record_attempt(report,signal,qualification,'full_point_in_time',
                snapshot=dict(available_time=1000,market_time=1000,slot=11),native_resources=resources)
            self.assertFalse(attempt['qualified'])
        self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM funding').fetchone()[0],0)
        self.assert_no_money(resources)

    def test_pons_current_rejects_missing_attempt_changed_result_expiry_and_uncommitted_state(self):
        cohort,queue,scheduled,evaluation,attempts,resources,now=self.current_pons(record_attempt=False)
        with self.assertRaisesRegex(ValueError,'qualified_attempt_required'):
            cohort._allocation_allowed(queue,scheduled,evaluation,attempts,native_resources=resources)
        cohort._record_qualification(attempts,scheduled['key'],scheduled['work']['generation'],evaluation,
            'QUALIFIED',at=202,explanation={})
        with self.assertRaisesRegex(ValueError,'plane_qualification_required'):
            cohort._allocation_allowed(queue,scheduled,dict(evaluation,token='other'),attempts,native_resources=resources)
        with queue.plane.transaction():
            with self.assertRaisesRegex(ValueError,'uncommitted_qualification'):
                cohort._allocation_allowed(queue,scheduled,evaluation,attempts,native_resources=resources)
        now[0]=208
        with self.assertRaisesRegex(ValueError,'plane_qualification_required'):
            cohort._allocation_allowed(queue,scheduled,evaluation,attempts,native_resources=resources)
        self.assertEqual(resources.candidate_history().db.execute('SELECT COUNT(*) FROM funding').fetchone()[0],0)

    def test_production_default_gates_do_not_acquire_isolated_resources(self):
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime as Pump
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime as Pons
        from meme_machine.lanes.pons.pons_selective_cohort import _allocation_allowed
        self.assertTrue(object.__new__(Pump)._allocation_allowed(None,None))
        self.assertTrue(object.__new__(Pons)._allocation_allowed(None,None))
        self.assertTrue(_allocation_allowed(None,None,None,None))

    def test_full_isolated_bootstrap_still_refused_before_state_or_financial_constructor(self):
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime as Pump
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime as Pons
        from meme_machine.lanes.pons.pons_selective_cohort import run
        resources,_=self.owned()
        root=Path(self.tmp.name)/'must-not-exist'
        with patch('sqlite3.connect',side_effect=AssertionError('SQLite opened')):
            for call in (lambda:Pump(root,1,'run',None,native_resources=resources),
                lambda:Pons(root,1,'run','offline',native_resources=resources),
                lambda:run('offline',native_resources=resources)):
                with self.assertRaisesRegex(ValueError,'full_bootstrap_unsupported'):call()
        self.assertFalse(root.exists());self.assert_no_money(resources)

    def test_native_store_factories_reject_links_and_foreign_files_before_open(self):
        resources,_=self.owned()
        external=Path(self.tmp.name)/'external.sqlite'
        with sqlite3.connect(external) as db:
            db.execute('CREATE TABLE unique_evidence(value TEXT)')
            db.execute("INSERT INTO unique_evidence VALUES('preserve-original')")
        original=external.read_bytes();checksum=hashlib.sha256(original).hexdigest()
        cases=(('candidate-history.sqlite',resources.candidate_history),
            ('pump-survivor-history.sqlite',lambda:resources.survivor_history('pump')),
            ('pons-survivor-history.sqlite',lambda:resources.survivor_history('pons')),
            ('pons-candidates.sqlite',resources.pons_plane))
        for name,construct in cases:
            for suffix in ('','-wal','-shm','-journal'):
                link=resources.root/(name+suffix);link.symlink_to(external)
                with self.subTest(name=name,suffix=suffix),\
                        patch('sqlite3.connect',side_effect=AssertionError('opened foreign state')):
                    with self.assertRaisesRegex(ValueError,'state_symlink'):construct()
                link.unlink()
            foreign=resources.root/name;foreign.write_bytes(original)
            with patch('sqlite3.connect',side_effect=AssertionError('opened foreign state')):
                with self.assertRaisesRegex(ValueError,'foreign_state'):construct()
            foreign.unlink()
        self.assertEqual(hashlib.sha256(external.read_bytes()).hexdigest(),checksum)
        self.assertEqual(resources._histories,[])
