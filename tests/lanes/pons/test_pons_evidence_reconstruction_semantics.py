"""Offline regressions for accepted-block Pons evidence attribution.

Synthetic inputs exercise the native authentication and frozen qualification
paths; these tests do not claim new natural-market completions.
"""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons import pons_selective_acquisition as acquisition
from meme_machine.lanes.pons.abi import calldata
from meme_machine.lanes.pons.pipeline import Pipeline
from meme_machine.lanes.pons.pons_natural_observation import _authenticate_candidate
from meme_machine.lanes.pons.pons_selective_cohort import _record_candidate_boundary
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
from tests.lanes.pons.test_pons_factory_hint_reuse import CandidateContext, CURVE, TOKEN, NON_NATIVE
from tests.lanes.pons import test_pons_selective_continuation as selective_fixtures
from tests.lanes.pons.test_pons_selective_continuation import state, snapshots, events


class AuthenticatedEarlyRejectionTests(unittest.TestCase):
    def setUp(self):
        self.ctx=CandidateContext()
        self.pair='0x'+'00'*20
        module='meme_machine.lanes.pons.pons_natural_observation.'
        self.auth=self.enterContext(patch(module+'authenticate_curve',return_value={
            'immutables':{'feeBps':100,'creatorTaxBps':0}}))
        self.enterContext(patch(module+'factory_record',side_effect=lambda raw,role:dict(
            token=TOKEN,curve=CURVE,deployer=TOKEN,creatorFeeRecipient=TOKEN,
            pairToken=self.pair,exists=True)))
        self.enterContext(patch(module+'raw_event',return_value={
            'decoded':{'name':'CurveBuy'},'event_at':1000}))
        self.enterContext(patch(module+'time.time',return_value=1000.0))
        self.enterContext(patch(module+'time.monotonic',return_value=100.0))

    def authenticate_boundary(self,boundary):
        event=self.ctx.observe(123);report={'reads':[]}
        with self.assertRaisesRegex(BoundaryError,'^'+boundary+'$'):
            _authenticate_candidate(self.ctx,event,report)
        return event,report

    def record(self,event,boundary,evidence):
        context=SimpleNamespace(timing={},boundary_evidence=evidence)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pipeline.sqlite'
            pipeline=Pipeline(path,'pons',POLICY_HASH)
            row=_record_candidate_boundary(pipeline,'candidate',event,0,context,boundary,
                dispatch=100,observed_monotonic=100)
            stages={key:set(value) for key,value in pipeline.stages.items()}
            classes={key:set(value) for key,value in pipeline.classes.items()}
            pipeline.close()
            restarted=Pipeline(path,'pons',POLICY_HASH)
            self.assertEqual(dict(restarted.stages),stages)
            self.assertEqual(dict(restarted.classes),classes)
            restarted.close()
        return row,stages,classes

    def test_non_native_is_authenticated_structural_screen_without_completion(self):
        self.pair=NON_NATIVE
        event,report=self.authenticate_boundary('natural_non_native_quote_not_supported')
        row,stages,classes=self.record(event,'natural_non_native_quote_not_supported',
            report['authenticated_rejection'])
        self.assertEqual(row['causal_bucket'],'valid_early_structural_rejection')
        self.assertEqual(row['vector']['all_rejections'],['non_native_quote'])
        self.assertEqual(classes,{'structural_ineligible':{'candidate'}})
        self.assertIn('evidence_not_required',stages)
        for stage in ('evidence_required','evidence_requested','evidence_complete'):
            self.assertNotIn(stage,stages)
        self.assertFalse(row['vector']['complete'])
        self.assertFalse(row['vector']['current_threshold_pass'])

    def test_high_raw_snipe_keeps_quote_boundary_and_proves_existing_zero_rate_veto(self):
        self.ctx.snipe=9900
        event,report=self.authenticate_boundary('invalid_current_snipe_bps')
        proof=report['authenticated_rejection']
        self.assertEqual(proof['current_snipe_bps'],9900)
        self.assertEqual(proof['fee_bps'],100)
        row,stages,classes=self.record(event,'invalid_current_snipe_bps',proof)
        self.assertEqual(row['causal_bucket'],'valid_early_strategy_rejection')
        self.assertEqual(row['vector']['all_rejections'],['snipe_tax_nonzero'])
        self.assertEqual(row['boundary'],'invalid_current_snipe_bps')
        self.assertEqual(classes,{'strategy_rejection':{'candidate'}})
        self.assertNotIn('evidence_complete',stages)

    def test_authentication_failure_never_creates_screen_authority(self):
        self.ctx.snipe=9900
        self.auth.side_effect=BoundaryError('curve_factory_disagreement')
        _,report=self.authenticate_boundary('curve_factory_disagreement')
        self.assertNotIn('authenticated_rejection',report)

    def test_boundary_name_alone_or_malformed_proof_remains_a_failure(self):
        self.ctx.snipe=9900
        event,report=self.authenticate_boundary('invalid_current_snipe_bps')
        valid=report['authenticated_rejection']
        for proof in (None,dict(valid,current_snipe_bps=0),dict(valid,fee_bps=10_000),
                      dict(valid,authentication_complete=False),dict(valid,boundary='other')):
            with self.subTest(proof=proof):
                row,stages,classes=self.record(event,'invalid_current_snipe_bps',proof)
                self.assertEqual(row['status'],'incomplete')
                self.assertEqual(classes,{'reconstruction_incomplete':{'candidate'}})
                self.assertNotIn('evidence_not_required',stages)

    def test_late_authentication_does_not_turn_staleness_into_strategy_rejection(self):
        self.pair=NON_NATIVE
        event,report=self.authenticate_boundary('natural_non_native_quote_not_supported')
        proof=dict(report['authenticated_rejection'],decision_age_seconds=5.001)
        row,stages,classes=self.record(event,'natural_non_native_quote_not_supported',proof)
        self.assertEqual(row['status'],'incomplete')
        self.assertEqual(row['stale_stage'],'stale_during_evidence')
        self.assertEqual(classes,{'stale_during_evidence':{'candidate'}})
        self.assertNotIn('evidence_not_required',stages)


class FullEvidenceRequestTests(unittest.TestCase):
    def evaluate(self,launch=50,*,trajectory=None,window_error=None):
        ctx=MagicMock();ctx.telemetry.return_value={}
        ctx.window_coverage=dict(complete=True)
        ctx.cache=acquisition.ImmutableEvidenceCache()
        if launch is not None:ctx.cache.remember_launch('curve',launch)
        candidate=dict(token='token',curve='curve',block=1,
            stamp=SimpleNamespace(event_at=200),header={'timestamp':hex(200)},
            state=state(timestamp=200),record={'graduationThreshold':10**18,
                'pairToken':'0x'+'00'*20},current_snipe_bps=0,roundtrip_gas_wei=10**10,
            decoded_event={'decoded':{'name':'CurveBuy'}})
        event=dict(blockNumber='0x1',blockHash='hash',transactionHash='tx',logIndex='0x0')
        stages=[]
        with patch.object(acquisition,'_authenticate_candidate',return_value=candidate), \
             patch('meme_machine.lanes.pons.pons_current_window.canonical_window',return_value=[]), \
             patch.object(acquisition,'_trajectory',return_value=(
                 snapshots() if trajectory is None else trajectory,
                 50 if launch is None else launch,{})) as acquire_trajectory, \
             patch.object(acquisition,'_authenticate_window',return_value=(events(),[]),
                          side_effect=window_error) as acquire_window, \
             patch.object(acquisition.time,'time',return_value=202):
            try:
                row=acquisition.evaluate_candidate('unused',event,[],strategy_capital_quote=10**18,
                    evidence_context=ctx,on_stage=stages.append)
            except BoundaryError as exc:row=exc
        return row,stages,acquire_trajectory,acquire_window

    def test_cached_age_rejection_never_requests_full_evidence_or_history(self):
        row,stages,trajectory,window=self.evaluate(launch=111)
        self.assertEqual(row['vector']['all_rejections'],['token_age'])
        self.assertFalse(row['vector']['complete'])
        trajectory.assert_not_called();window.assert_not_called()
        self.assertEqual(stages,['current_state_complete','prospect_admitted'])

    def test_completed_trajectory_rejection_is_not_full_reconstruction(self):
        slow=[dict(row,progress_bps=5500+i*10) for i,row in enumerate(snapshots())]
        row,stages,trajectory,window=self.evaluate(trajectory=slow)
        self.assertTrue(row['trajectory_preflight']['trajectory']['complete'])
        self.assertTrue(row['screened_out'])
        self.assertFalse(row['vector']['complete'])
        self.assertIn('trajectory_complete',stages)
        self.assertNotIn('evidence_required',stages)
        self.assertNotIn('evidence_requested',stages)
        trajectory.assert_called_once();window.assert_not_called()

    def test_full_request_occurs_only_after_all_existing_preflight_rules_pass(self):
        row,stages,trajectory,window=self.evaluate()
        self.assertTrue(row['vector']['complete'])
        self.assertTrue(row['vector']['current_threshold_pass'],row['vector']['all_rejections'])
        self.assertEqual(stages[-4:],['trajectory_admitted','evidence_required','admitted','evidence_requested'])
        trajectory.assert_called_once();window.assert_called_once()

    def test_required_window_failure_still_counts_as_full_request(self):
        row,stages,_,window=self.evaluate(window_error=BoundaryError('selective_window_header_disagreement'))
        self.assertIsInstance(row,BoundaryError)
        self.assertIn('evidence_required',stages)
        self.assertIn('evidence_requested',stages)
        self.assertNotIn('evidence_complete',stages)
        window.assert_called_once()

    def test_boundary_evidence_is_reset_before_each_candidate(self):
        ctx=MagicMock();ctx.boundary_evidence={'authentication_complete':True}
        event=dict(blockNumber='0x1',blockHash='hash',transactionHash='tx',logIndex='0x0')
        with patch.object(acquisition,'_authenticate_candidate',side_effect=BoundaryError('provider_rpc_3')):
            with self.assertRaisesRegex(BoundaryError,'provider_rpc_3'):
                acquisition.evaluate_candidate('unused',event,[],strategy_capital_quote=10**18,
                    evidence_context=ctx)
        self.assertIsNone(ctx.boundary_evidence)


class ColdAgeAcquisitionTests(unittest.TestCase):
    def test_newly_authenticated_age_veto_stops_before_reserves_and_window_receipts(self):
        fixtures=selective_fixtures.SelectiveEvidenceThroughputTests()
        ctx=fixtures.BatchContext(launch_at=920);candidate=fixtures._candidate(200)
        tape=[dict(address=candidate['curve'],blockNumber='0xbe',blockHash='hash',
                   transactionHash='tx',transactionIndex='0x0',logIndex='0x0')]
        result,launch,meta=acquisition._trajectory('unused',candidate,evidence_context=ctx,
            window_tape=tape,screen_launch_age=True)
        self.assertEqual(launch,920)
        self.assertEqual(result,[])
        self.assertTrue(meta['launch_age_screen_only'])
        self.assertEqual(len(ctx.batches),1)
        calls=ctx.batches[0][1]
        self.assertEqual([params[0]['data'] for method,params in calls if method=='eth_call'],
                         [calldata('launchedAt()')])
        self.assertFalse(any(method=='eth_getTransactionReceipt' for method,_ in calls))

    def test_in_age_candidate_keeps_identical_trajectory_requirements(self):
        fixtures=selective_fixtures.SelectiveEvidenceThroughputTests();outputs=[]
        for screen in (False,True):
            ctx=fixtures.BatchContext();candidate=fixtures._candidate(200)
            ctx.cache.remember_launch(candidate['curve'],850)
            row,launch,_=acquisition._trajectory('unused',candidate,evidence_context=ctx,
                                                screen_launch_age=screen)
            outputs.append((row,launch,copy.deepcopy(ctx.batches)))
        self.assertEqual(outputs[0],outputs[1])


if __name__=='__main__':
    unittest.main()
