import unittest

from tests.parallel_pump_stream_comparison import _overlap


class ParallelPumpStreamComparisonTests(unittest.TestCase):
    def test_overlap_reports_directional_coverage_and_jaccard(self):
        auth={'a','b'}
        public={'a','b','c','d'}
        got=_overlap(auth,public)
        self.assertEqual(got['intersection'],2)
        self.assertEqual(got['union'],4)
        self.assertEqual(got['jaccard'],0.5)
        self.assertEqual(got['onfinality_coverage_of_public'],0.5)
        self.assertEqual(got['public_coverage_of_onfinality'],1.0)

    def test_empty_reference_is_explicit_not_divide_by_zero(self):
        got=_overlap({'a'},set())
        self.assertEqual(got['intersection'],0)
        self.assertEqual(got['union'],1)
        self.assertEqual(got['jaccard'],0.0)
        self.assertIsNone(got['onfinality_coverage_of_public'])
        self.assertEqual(got['public_coverage_of_onfinality'],0.0)


if __name__=='__main__':
    unittest.main()
