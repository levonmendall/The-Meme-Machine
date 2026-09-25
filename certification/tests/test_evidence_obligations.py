import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

from certification.evidence_obligations import summarize
from certification.market_assurance import pipeline


def event(candidate, stage, classification=None):
    return dict(candidate=candidate, stage=stage, classification=classification)


class EvidenceObligationTests(unittest.TestCase):
    def test_earlier_rejection_does_not_erase_later_same_token_evidence_loss(self):
        rows = [event('mint', 'evidence_not_required'),
                event('mint', 'evidence_required'), event('mint', 'evidence_requested'),
                event('mint', 'terminal', 'reconstruction_incomplete'),
                event('mint', 'evidence_required'), event('mint', 'evidence_requested'),
                event('mint', 'evidence_complete')]
        result = summarize(rows)
        self.assertEqual(result['candidates_requiring_full_evidence'], 1)
        self.assertEqual(result['observations_requiring_full_evidence'], 2)
        self.assertEqual(result['infrastructure_failed'], 1)
        self.assertEqual(result['evidence_completed_in_time'], 1)
        self.assertEqual(result['valid_rejections_before_full_evidence_required'], 1)

    def test_completed_zero_swap_rejection_never_fabricates_full_economic_vector(self):
        rows = [event('pool', 'evidence_required'), event('pool', 'evidence_requested'),
                event('pool', 'evidence_not_required')]
        result = summarize(rows)
        self.assertEqual(result['became_unnecessary_after_valid_earlier_rejection'], 1)
        self.assertEqual(result['evidence_completed_in_time'], 0)
        self.assertEqual(result['infrastructure_failed'], 0)

    def test_later_early_rejection_does_not_rewrite_an_earlier_failed_observation(self):
        rows = [event('mint', 'evidence_required'), event('mint', 'evidence_requested'),
                event('mint', 'terminal', 'reconstruction_incomplete'),
                event('mint', 'evidence_not_required')]
        result = summarize(rows)
        self.assertEqual(result['infrastructure_failed'], 1)
        self.assertEqual(result['valid_rejections_before_full_evidence_required'], 1)

    def test_pending_superseded_and_genuine_failure_remain_separate(self):
        rows = [event('pending', 'evidence_required'), event('pending', 'evidence_requested'),
                event('old', 'evidence_required'), event('old', 'terminal', 'superseded_candidate_state'),
                event('failed', 'evidence_required'), event('failed', 'terminal', 'provider_failed')]
        result = summarize(rows)
        self.assertEqual(result['pending_at_observation_close'], 1)
        self.assertEqual(result['superseded_candidate_state'], 1)
        self.assertEqual(result['infrastructure_failed'], 1)

    def test_legacy_and_orphan_completions_do_not_invent_obligations(self):
        result = summarize([event('old', 'evidence_requested'), event('old', 'evidence_complete')])
        self.assertFalse(result['available'])
        self.assertIsNone(result['candidates_requiring_full_evidence'])
        self.assertEqual(result['unscoped_full_requests'], 1)
        self.assertEqual(result['completions_without_scoped_request'], 1)

    def test_unresolved_stream_gap_remains_an_evidence_failure(self):
        result = summarize([event('pool', 'evidence_required'),
                            event('pool', 'terminal', 'stream_gap')])
        self.assertEqual(result['infrastructure_failed'], 1)
        self.assertEqual(result['pending_at_observation_close'], 0)
        self.assertEqual(result['infrastructure_failure_observations']['stream_gap'], 1)

    def test_pump_history_attempt_is_separate_from_full_concentration_request(self):
        rows = [event('mint', 'decision_evidence_requested'),
                event('mint', 'decision_evidence_complete'),
                event('mint', 'evidence_required'), event('mint', 'full_evidence_requested'),
                event('mint', 'evidence_complete')]
        result = summarize(rows)
        self.assertEqual(result['decision_evidence_requested'], 1)
        self.assertEqual(result['evidence_requested'], 1)
        self.assertEqual(result['evidence_completed_in_time'], 1)

    def test_two_pump_modes_sharing_one_holder_read_keep_separate_obligations(self):
        rows=[]
        for mode in ('momentum', 'second_leg'):
            for stage in ('evidence_required', 'full_evidence_requested'):
                rows.append(dict(event('mint',stage),details=dict(mode=mode,decision_at=100)))
        for mode in ('momentum', 'second_leg'):
            rows.append(dict(event('mint','evidence_complete'),details=dict(mode=mode,decision_at=100)))
        result=summarize(rows)
        self.assertEqual(result['candidates_requiring_full_evidence'],1)
        self.assertEqual(result['observations_requiring_full_evidence'],2)
        self.assertEqual(result['evidence_completed_in_time'],2)
        self.assertEqual(result['pending_at_observation_close'],0)

    def test_meteora_superseded_trigger_does_not_leave_a_false_pending_obligation(self):
        old=dict(observation_id='pool:10');new=dict(observation_id='pool:11')
        rows=[dict(event('pool','evidence_required'),details=old),
              dict(event('pool','evidence_superseded','superseded_candidate_state'),details=old),
              dict(event('pool','evidence_required'),details=new),
              dict(event('pool','evidence_requested'),details=new),
              dict(event('pool','evidence_complete'),details=new)]
        result=summarize(rows)
        self.assertEqual(result['superseded_candidate_state'],1)
        self.assertEqual(result['evidence_completed_in_time'],1)
        self.assertEqual(result['pending_at_observation_close'],0)

    def test_every_lane_preserves_causal_classes_and_required_stages_on_restart(self):
        root = Path(os.environ.get('MM_TEST_LANE_WORKTREES', '/nonexistent'))
        if not root.is_dir():
            self.skipTest('prepared exact lane sources unavailable')
        for lane in ('pump', 'pons', 'meteora', 'ramses'):
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as temp:
                package = 'robinhood_research' if lane in ('pons', 'ramses') else 'meme_machine'
                spec = importlib.util.spec_from_file_location('pipeline_' + lane, root/lane/package/'pipeline.py')
                module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                path = Path(temp)/'opportunity-pipeline.sqlite'
                book = module.Pipeline(path, lane, 'frozen')
                book.record('candidate', 'evidence_required')
                book.record('candidate', 'evidence_requested')
                book.record('candidate', 'terminal', classification='superseded_candidate_state')
                book.close()
                restored = module.Pipeline(path, lane, 'frozen')
                snapshot = restored.snapshot(); restored.close()
                self.assertEqual(snapshot['stages']['evidence_required'], 1)
                self.assertEqual(snapshot['unique_classes']['superseded_candidate_state'], 1)
                self.assertEqual(pipeline(temp)['evidence_obligations']['superseded_candidate_state'], 1)
