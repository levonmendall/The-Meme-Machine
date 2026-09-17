import unittest

from meme_machine.market_native_research import analyze_market_native_reports


def vector(reason='concentration',rejections=None):
    return dict(
        actual_reason=reason,
        all_rejections=list(rejections if rejections is not None else ([] if reason=='qualified' else [reason])),
        sensitivity={'values':{'max_concentration_bps':{'3500':reason=='qualified','4000':True}}},
    )


def report(rows):
    return dict(
        kind='prioritized_market_native_shadow',
        qualification_policy='continuation-v1',
        preflights=rows,
    )


class MarketNativeResearchTests(unittest.TestCase):
    def test_deduplicates_full_vectors_and_holds_policy_below_sample(self):
        rows=[
            dict(nomination_id='a',full_evidence_complete=True,qualification_vector=vector()),
            dict(nomination_id='a',full_evidence_complete=True,qualification_vector=vector('qualified')),
            dict(nomination_id='b',full_evidence_complete=False,qualification_vector=vector('qualified')),
        ]
        result=analyze_market_native_reports([report(rows)],min_sample=2)
        self.assertEqual(result['unique_complete_market_native_nominations'],1)
        self.assertFalse(result['sample_ready'])
        self.assertEqual(result['conclusion'],'insufficient_sample_for_threshold_revision')
        self.assertFalse(result['automatic_threshold_change'])

    def test_ready_sample_reports_rejections_without_selecting_threshold(self):
        rows=[
            dict(nomination_id='a',full_evidence_complete=True,
                 qualification_vector=vector('concentration',['concentration','exit_liquidity'])),
            dict(nomination_id='b',full_evidence_complete=True,
                 qualification_vector=vector('qualified',[])),
        ]
        result=analyze_market_native_reports([report(rows)],min_sample=2)
        self.assertTrue(result['sample_ready'])
        self.assertEqual(result['current_policy_qualified'],1)
        self.assertEqual(result['all_rejection_counts']['concentration'],1)
        self.assertEqual(result['multiple_rejection_vectors'],1)
        self.assertEqual(result['conclusion'],'ready_for_human_threshold_review')
        self.assertFalse(result['automatic_threshold_change'])


if __name__=='__main__':
    unittest.main()
