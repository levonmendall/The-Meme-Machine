import unittest

from robinhood_research import BoundaryError
from robinhood_research.keccak import keccak256
from robinhood_research.pons_natural_paper import (
    V4_SELECTOR, _v4_quoter_calldata,
)
from robinhood_research.protocols import PoolKey

ZERO="0x0000000000000000000000000000000000000000"
TOKEN="0x1111111111111111111111111111111111111111"
HOOK="0xe5e702641ea86f4ae6cc3cdaed2b886f976be044"


class NaturalPaperHarnessTests(unittest.TestCase):
    def test_v4_quoter_selector_and_empty_hook_encoding(self):
        key=PoolKey(ZERO,TOKEN,200,200,HOOK)
        data=_v4_quoter_calldata(key,False,12345)
        self.assertTrue(data.startswith("0x"+V4_SELECTOR))
        expected=keccak256(
            b"quoteExactInputSingle(((address,address,uint24,int24,address),bool,uint128,bytes))"
        ).hex()[:8]
        self.assertEqual(V4_SELECTOR,expected)
        # selector + outer offset + eight tuple-head words + empty-bytes length.
        self.assertEqual(len(bytes.fromhex(data[2:])),4+10*32)

    def test_v4_quoter_amount_must_fit_uint128(self):
        key=PoolKey(ZERO,TOKEN,200,200,HOOK)
        with self.assertRaisesRegex(BoundaryError,"amount"):
            _v4_quoter_calldata(key,False,1<<128)


if __name__=="__main__":
    unittest.main()
