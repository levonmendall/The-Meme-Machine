import unittest

from robinhood_research import BoundaryError
from robinhood_research.pons_natural_observation import (
    RESEARCH_BUY_WEI, _one_word, _two_uints,
)


class PonsNaturalObservationTests(unittest.TestCase):
    def test_word_decoders_are_strict(self):
        one="0x"+f"{123:064x}"
        two="0x"+f"{123:064x}"+f"{456:064x}"
        self.assertEqual(_one_word(one),123)
        self.assertEqual(_two_uints(two),(123,456))
        with self.assertRaisesRegex(BoundaryError,"shape"):
            _one_word(two)
        with self.assertRaisesRegex(BoundaryError,"shape"):
            _two_uints(one)

    def test_observation_size_is_fixed_research_only_amount(self):
        self.assertEqual(RESEARCH_BUY_WEI,10**16)


if __name__=="__main__":
    unittest.main()
