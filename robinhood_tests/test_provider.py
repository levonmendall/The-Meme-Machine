import unittest
from robinhood_research import BoundaryError
from robinhood_research.provider import Rpc


class ProviderTests(unittest.TestCase):
    def test_wrong_chain(self):
        rpc = Rpc('https://example.invalid', transport=lambda *_: '0x1')
        with self.assertRaisesRegex(BoundaryError, 'wrong_chain'):
            rpc.verify_chain()

    def test_scope_exhaustion_does_not_starve_other_pool(self):
        rpc = Rpc('https://example.invalid', limit=10, per_scope=2, transport=lambda *_: '0x1237')
        for _ in range(2):
            rpc.call('eth_chainId', [], scope='pool_a')
        with self.assertRaisesRegex(BoundaryError, 'pool_budget'):
            rpc.call('eth_chainId', [], scope='pool_a')
        self.assertEqual(rpc.call('eth_chainId', [], scope='pool_b'), '0x1237')

    def test_signing_and_submission_rejected(self):
        rpc = Rpc('https://example.invalid')
        for method in ('eth_sendRawTransaction', 'eth_sendTransaction', 'eth_sign'):
            with self.assertRaisesRegex(BoundaryError, 'not_read_only'):
                rpc.call(method, [])
        self.assertEqual(rpc.used, 0)

    def test_quota_no_retry(self):
        def fail(*_):
            raise BoundaryError('provider_http_429')
        rpc = Rpc('https://example.invalid', transport=fail)
        with self.assertRaisesRegex(BoundaryError, '429'):
            rpc.verify_chain()
        self.assertEqual(rpc.used, 1)

    def test_future_missing_secret_does_not_print_url(self):
        from robinhood_research.probe import run
        result = run('secret-only')
        self.assertEqual(result['status'], 'blocked')
        self.assertNotIn('secret-only', str(result))
