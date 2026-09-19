import unittest

from tests.market_native_paper_cohort import _cohort_counts, _cohort_target_reached, _paper_rows


class PaperCohortAccounting(unittest.TestCase):
    def test_multiple_settlements_and_pumpswap_handoff_are_counted_without_authority(self):
        state={
            'positions':{},
            'orders':{
                'a':{
                    'status':'settled','mint':'A','created':1,
                    'fill':{'time':2,'cost':100,'tokens':10},
                    'exit':{'time':20,'reason':'take_profit','realized':20,'surface':'pump.fun'},
                },
                'b':{
                    'status':'settled','mint':'B','created':3,
                    'fill':{'time':4,'cost':100,'tokens':10},
                    'exit':{'time':30,'reason':'timeout','realized':-8,'surface':'pumpswap'},
                },
                'c':{
                    'status':'settled','mint':'C','created':5,
                    'fill':{'time':6,'cost':100,'tokens':10},
                    'exit':{'time':40,'reason':'risk','realized':-10,'surface':'pump.fun'},
                },
            },
        }
        rows=_paper_rows(state)
        counts=_cohort_counts(state)
        self.assertEqual(len(rows),3)
        self.assertEqual(counts['settled'],3)
        self.assertEqual(counts['pumpswap_handoffs'],1)
        self.assertEqual(counts['pumpswap_settlements'],1)
        self.assertTrue(_cohort_target_reached(state,3))

    def test_open_or_reserved_exposure_prevents_target_completion(self):
        state={
            'positions':{'A':{'surface':'pump.fun'}},
            'orders':{
                'a':{
                    'status':'settled','mint':'A','created':1,
                    'fill':{'time':2,'cost':100,'tokens':10},
                },
                'b':{
                    'status':'reserved','mint':'B','created':3,
                },
            },
        }
        counts=_cohort_counts(state)
        self.assertEqual(counts['filled'],1)
        self.assertEqual(counts['settled'],0)
        self.assertEqual(counts['active_positions'],1)
        self.assertEqual(counts['reserved_orders'],1)
        self.assertFalse(_cohort_target_reached(state,1))


if __name__=='__main__':
    unittest.main()
