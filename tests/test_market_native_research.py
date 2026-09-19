import unittest

from meme_machine.market_native_research import analyze_market_native_reports
from meme_machine.outcome_research import new_tracker, observe_trade


def vector(reason='concentration',rejections=None,liquidity=True):
    return dict(
        actual_reason=reason,
        all_rejections=list(rejections if rejections is not None else ([] if reason=='qualified' else [reason])),
        sensitivity={'values':{
            'max_concentration_bps':{'3500':reason=='qualified','4000':True},
            'min_real_sol_lamports':{
                '5000000000':liquidity,'7500000000':liquidity,'10000000000':reason=='qualified'},
        }},
    )


def natural_report(rows):
    return dict(kind='market_native_natural_sample',qualification_policy='continuation-v1',results=rows)


def study_report(rows,trackers=None):
    return dict(kind='market_native_opportunity_outcome_study',qualification_policy='continuation-v1',
                natural_results=rows,cohort_trackers=trackers or [])


def priority_report(rows):
    return dict(kind='prioritized_market_native_shadow',qualification_policy='continuation-v1',preflights=rows)


class MarketNativeResearchTests(unittest.TestCase):
    def test_deduplicates_natural_vectors_and_holds_policy_below_sample(self):
        rows=[
            dict(nomination_id='a',natural_market_native_sample=True,evidence_stage='complete',qualification_vector=vector()),
            dict(nomination_id='a',natural_market_native_sample=True,evidence_stage='complete',qualification_vector=vector('qualified')),
            dict(nomination_id='b',natural_market_native_sample=True,evidence_stage='incomplete',qualification_vector=vector('qualified')),
        ]
        result=analyze_market_native_reports([natural_report(rows)],min_sample=2)
        self.assertEqual(result['unique_complete_market_native_nominations'],1)
        self.assertFalse(result['sample_ready'])
        self.assertEqual(result['conclusion'],'insufficient_sample_for_threshold_revision')
        self.assertFalse(result['automatic_threshold_change'])

    def test_prioritized_vectors_are_diagnostic_only_and_never_count_toward_review(self):
        priority=[
            dict(nomination_id='p1',full_evidence_complete=True,qualification_vector=vector('qualified')),
            dict(nomination_id='p2',full_evidence_complete=True,qualification_vector=vector()),
        ]
        result=analyze_market_native_reports([priority_report(priority)],min_sample=1)
        self.assertEqual(result['prioritized_complete_diagnostic_vectors'],2)
        self.assertEqual(result['unique_complete_market_native_nominations'],0)
        self.assertFalse(result['sample_ready'])

    def test_outcome_study_natural_rows_count_and_future_labels_do_not_select(self):
        tracker=new_tracker('m',100,100,100,['feasible_unpreflighted'],horizons=(60,))
        observe_trade(tracker,dict(mint='m',market_time=160,amount=120,tokens=100))
        rows=[dict(
            nomination_id='a',natural_market_native_sample=True,evidence_stage='complete',
            qualification_vector=vector('qualified',[]),
            liquidity_floor_eligibility={'5000000000':True,'7500000000':True,'10000000000':True},
            future_outcomes=tracker,
        )]
        result=analyze_market_native_reports([study_report(rows,[tracker])],min_sample=1)
        self.assertTrue(result['sample_ready'])
        self.assertEqual(result['future_outcome_labeled_complete_nominations'],1)
        self.assertFalse(result['future_labels_used_for_selection'])
        self.assertEqual(result['missed_opportunity_cohorts']['feasible_unpreflighted']['count'],1)

    def test_ready_natural_sample_reports_rejections_without_selecting_threshold(self):
        rows=[
            dict(nomination_id='a',natural_market_native_sample=True,evidence_stage='complete',
                 qualification_vector=vector('concentration',['concentration','exit_liquidity'])),
            dict(nomination_id='b',natural_market_native_sample=True,evidence_stage='complete',
                 qualification_vector=vector('qualified',[])),
        ]
        result=analyze_market_native_reports([natural_report(rows)],min_sample=2)
        self.assertTrue(result['sample_ready'])
        self.assertEqual(result['current_policy_qualified'],1)
        self.assertEqual(result['all_rejection_counts']['concentration'],1)
        self.assertEqual(result['multiple_rejection_vectors'],1)
        self.assertEqual(result['conclusion'],'ready_for_human_threshold_review')
        self.assertFalse(result['automatic_threshold_change'])


    def test_same_legacy_nomination_id_different_mints_are_distinct(self):
        rows=[
            dict(nomination_id='legacy:45',mint='MintA',natural_market_native_sample=True,
                 evidence_stage='complete',qualification_vector=vector('qualified',[])),
            dict(nomination_id='legacy:45',mint='MintB',natural_market_native_sample=True,
                 evidence_stage='complete',qualification_vector=vector('qualified',[])),
        ]
        result=analyze_market_native_reports([natural_report(rows)],min_sample=2)
        self.assertEqual(result['unique_complete_market_native_nominations'],2)
        self.assertTrue(result['sample_ready'])



if __name__=='__main__':
    unittest.main()
