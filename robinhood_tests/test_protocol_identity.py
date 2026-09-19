import copy
import unittest
from robinhood_research import BoundaryError
from robinhood_research.identity import ROOT, load, verify_compilation, authenticate, compiler_input
from robinhood_research.abi import topic, calldata, decode_event


class IdentityTests(unittest.TestCase):
    def test_all_captured_compiler_transformations_match(self):
        for path in ROOT.glob('*.json'):
            with self.subTest(role=path.stem):
                pin = load(path.stem)
                verify_compilation(pin)
                authenticate(path.stem, pin['address'], pin['runtimeBytecode']['onchainBytecode'])

    def test_code_or_role_disagreement(self):
        pin = load('pons_v2_factory')
        for address, code in [('0x'+'01'*20, pin['runtimeBytecode']['onchainBytecode']), (pin['address'], '0x00')]:
            with self.assertRaises(BoundaryError):
                authenticate('pons_v2_factory', address, code)

    def test_compiler_code_change_cannot_be_masked(self):
        pin = load('ramses_factory')
        pin['runtimeBytecode']['recompiledBytecode'] = '0x00' + pin['runtimeBytecode']['recompiledBytecode'][4:]
        with self.assertRaisesRegex(BoundaryError, 'disagreement'):
            verify_compilation(pin)

    def test_proxy_not_treated_as_implementation(self):
        pin = load('pons_v2_factory')
        pin['proxyResolution']['isProxy'] = True
        with self.assertRaisesRegex(BoundaryError, 'proxy'):
            verify_compilation(pin)

    def test_verified_source_includes_deployed_snipe_tax(self):
        pin = load('pons_v2_factory')
        source = compiler_input(pin)['sources']['contracts/src/v2/PonsV2BondingCurve.sol']['content']
        self.assertIn('function currentSnipeTaxBps', source)
        hashes = pin['source_comparison']['contracts/src/v2/PonsV2BondingCurve.sol']
        self.assertNotEqual(hashes['verified_sha256'], hashes['repository_sha256'])

    def test_selector_and_pinned_event_layout(self):
        self.assertEqual(calldata('balanceOf(address)', '0x'+'00'*20)[:10], '0x70a08231')
        abi = load('pons_v2_factory')['abi']
        event = dict(topics=[topic('TokenLaunched(address,address,address,address,uint256,uint256)')]+['0x'+f'{x:064x}' for x in (1,2,3)], data='0x'+''.join(f'{x:064x}' for x in (4,5,6)))
        got = decode_event(abi, event)
        self.assertEqual(got['args']['graduationThreshold'],6)
        event['data'] += '00'*32
        with self.assertRaisesRegex(BoundaryError,'length'):
            decode_event(abi,event)
