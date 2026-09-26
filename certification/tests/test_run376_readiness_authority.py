"""Preserved Run 376: freshness and flat books cannot hide evidence censorship."""
import copy
import json
from pathlib import Path
import unittest
from certification.controls import smoke_engineering
from certification.single_campaign_control import begin_phase, end_phase

FIXTURE = Path(__file__).parent/'fixtures/run376-readiness.json'

class Run376ReadinessAuthorityTests(unittest.TestCase):
    def test_preserved_run376_is_not_clean_readiness(self):
        result = json.loads(FIXTURE.read_text())['result']
        self.assertEqual(result['smoke_engineering']['status'], 'PASS')
        verdict = smoke_engineering(result)
        self.assertEqual(verdict['status'], 'FAIL')
        self.assertIn('pump:capacity_censored_local_evidence', verdict['failures'])

    def test_flat_smoke_cannot_authorize_hourly_or_mutate_exposure(self):
        result = json.loads(FIXTURE.read_text())['result']
        state = dict(phase='CLAIMED', identity=dict(integration_sha=result['integration_sha']),
                     phase_records=dict(smoke=dict(started_at=1, native_exposure='unknown')),
                     history=[], successor_allowed=False, continuation_allowed=False,
                     retry_allowed=False, authorized_phases=['smoke'])
        completed = end_phase(state, 'smoke', result, 'success')
        before = copy.deepcopy(completed)
        with self.assertRaisesRegex(ValueError, 'phase_not_authorized'):
            begin_phase(completed, 'hourly')
        self.assertEqual(completed, before)
        self.assertEqual(completed['phase'], 'SMOKE_COMPLETE')
        self.assertEqual(completed['phase_records']['smoke']['native_exposure'], 'flat')
        self.assertNotIn('hourly', completed['phase_records'])

    def test_explicit_phase_list_cannot_override_successor_prohibition(self):
        state = dict(phase='CLAIMED',phase_records=dict(smoke=dict(job_result='success',native_exposure='flat')),
                     history=[],successor_allowed=False,authorized_phases=['smoke','hourly'])
        with self.assertRaisesRegex(ValueError,'phase_not_authorized'):
            begin_phase(state,'hourly')

    def test_healthy_zero_trade_smoke_remains_valid(self):
        from certification.tests.test_controls import ControlsTests
        self.assertEqual(smoke_engineering(ControlsTests().smoke())['status'],'PASS')

    def test_failed_pre_native_phase_does_not_invent_unknown_exposure(self):
        state=dict(phase='CLAIMED',identity=dict(integration_sha='a'*40),phase_records={},
                   history=[],authorized_phases=['smoke'],successor_allowed=False)
        state=begin_phase(state,'smoke')
        terminal=end_phase(state,'smoke',None,'failure')
        self.assertEqual(terminal['phase'],'HALTED')
        self.assertEqual(terminal['phase_records']['smoke']['native_exposure'],'not_started')

    def test_started_native_without_result_remains_unresolved(self):
        state=dict(phase='CLAIMED',identity=dict(integration_sha='a'*40),phase_records={},
                   history=[],authorized_phases=['smoke'],successor_allowed=False)
        state=begin_phase(state,'smoke');state['phase_records']['smoke']['native_started']=True
        terminal=end_phase(state,'smoke',None,'failure')
        self.assertEqual(terminal['phase'],'HALTED_UNRESOLVED')

    def test_six_regime_gate_requires_working_active_survivors_in_one_sleeve(self):
        from certification.controls import regime_machinery
        from certification.tests.test_controls import ControlsTests
        r=ControlsTests().smoke();r['strategy_manifest']={}
        for lane in ('pump','pons','meteora','ramses'):
            policies={lane:'hash'}
            if lane in ('pump','pons'):
                policies[lane+'-survivor']='survivor-hash'
                row=r['lanes'][lane]
                row.update(active_regimes=list(policies),survivor=dict(active=True,paper_only=True,
                    policies=policies,machinery=dict(completed_steps=3,successful_steps=2,admission_enabled_steps=3)))
                key='native_accounting' if lane=='pump' else 'cohort_accounting'
                row[key]=dict(one_funded_genesis=True,shared_sleeve=dict(reconciled=True))
            r['strategy_manifest'][lane]=dict(strategies=policies)
        self.assertEqual(regime_machinery(r),[])
        r['lanes']['pump']['survivor']['machinery']['successful_steps']=0
        self.assertIn('pump:survivor_evidence_progression_unproven',regime_machinery(r))
        r['lanes']['pons']['cohort_accounting']['one_funded_genesis']=False
        self.assertIn('pons:shared_sleeve_unverified',regime_machinery(r))

    def test_worker_records_bounded_progress_including_terminal_drain(self):
        from certification.survivor_history import Worker
        class Service:
            def step(self,admit):return dict(active=True,last_boundary=None)
            def close(self):pass
        w=Worker(Service)
        try:
            a=w._step(True);b=w._step(False)
            self.assertEqual(a['machinery']['admission_enabled_steps'],1)
            self.assertEqual(b['machinery']['admission_enabled_steps'],1)
            self.assertEqual(b['machinery']['successful_steps'],2)
        finally:w.close()
