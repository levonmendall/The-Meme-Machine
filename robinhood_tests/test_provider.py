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

    def test_batch_preserves_logical_budget_and_reduces_transport_count(self):
        rpc = Rpc('https://example.invalid', limit=5, per_scope=5,
                  transport=lambda method, params: method + ':' + str(params[0] if params else ''))
        got = rpc.batch([
            ('eth_getBlockByNumber', ['0x1', False]),
            ('eth_getBlockByNumber', ['0x2', False]),
            ('eth_gasPrice', []),
        ], scope='sample')
        self.assertEqual(got, ['eth_getBlockByNumber:0x1', 'eth_getBlockByNumber:0x2', 'eth_gasPrice:'])
        telemetry = rpc.telemetry()
        self.assertEqual(telemetry['requests'], 3)
        self.assertEqual(telemetry['logical_requests'], 3)
        self.assertEqual(telemetry['transport_requests'], 1)
        with self.assertRaisesRegex(BoundaryError, 'budget_exhausted'):
            rpc.batch([
                ('eth_chainId', []),
                ('eth_chainId', []),
                ('eth_chainId', []),
            ], scope='sample')

    def test_batch_rejects_write_method(self):
        rpc = Rpc('https://example.invalid', transport=lambda *_: '0x1')
        with self.assertRaisesRegex(BoundaryError, 'not_read_only'):
            rpc.batch([('eth_sendTransaction', [])])
        self.assertEqual(rpc.used, 0)

    def test_future_missing_secret_does_not_print_url(self):
        from robinhood_research.probe import run
        result = run('secret-only')
        self.assertEqual(result['status'], 'blocked')
        self.assertNotIn('secret-only', str(result))


class ProviderHeaderTests(unittest.TestCase):
    class _Response:
        def __init__(self, body):
            self._body = body
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self, _):
            return self._body

    def _assert_headers(self, request):
        self.assertEqual(request.get_header('Accept'), 'application/json')
        self.assertEqual(
            request.get_header('User-agent'),
            'Meme-Machine/1.0 (+https://github.com/levonmendall/The-Meme-Machine)',
        )

    def test_single_request_uses_explicit_public_compatible_headers(self):
        def fake_urlopen(request, timeout):
            self._assert_headers(request)
            self.assertEqual(timeout, 10)
            return self._Response(json.dumps(
                {'jsonrpc':'2.0','id':1,'result':'0x1237'}
            ).encode())
        with patch('robinhood_research.provider.urlopen', side_effect=fake_urlopen):
            rpc = Rpc('https://example.invalid')
            self.assertEqual(rpc.call('eth_chainId', []), '0x1237')

    def test_batch_request_uses_explicit_public_compatible_headers(self):
        def fake_urlopen(request, timeout):
            self._assert_headers(request)
            self.assertEqual(timeout, 10)
            return self._Response(json.dumps([
                {'jsonrpc':'2.0','id':1,'result':'0x1237'},
                {'jsonrpc':'2.0','id':2,'result':'0x1'},
            ]).encode())
        with patch('robinhood_research.provider.urlopen', side_effect=fake_urlopen):
            rpc = Rpc('https://example.invalid')
            self.assertEqual(
                rpc.batch([
                    ('eth_chainId', []),
                    ('eth_blockNumber', []),
                ]),
                ['0x1237', '0x1'],
            )
