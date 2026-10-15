import unittest
from meme_machine.lanes.meteora import pump
from meme_machine.lanes.meteora.provider import RPC, PumpAdapter

class BoundedRetry(unittest.TestCase):

    def test_real_http_path_retries_once_and_counts_budget(self):

        class FlakyRPC(RPC):

            def __init__(self):
                self.attempts = 0
                super().__init__('https://example.invalid', limit=40, clock=lambda: 100.0, sleeper=lambda _seconds: None)

            def _http(self, request):
                self.attempts += 1
                if self.attempts == 1:
                    raise TimeoutError('transient')
                return {'result': 'ok'}
        rpc = FlakyRPC()
        self.assertEqual(rpc.call('getGenesisHash', priority=True), 'ok')
        self.assertEqual(rpc.calls, 2)
        self.assertEqual(rpc.http_requests, 2)
        self.assertEqual(rpc.failures, 1)
        self.assertEqual(rpc.retries, 1)
        self.assertEqual(rpc.call('getGenesisHash', priority=True), 'ok')
        self.assertEqual(rpc.calls, 2)
        self.assertEqual(rpc.cache_hits, 1)

    def test_custom_transport_remains_single_attempt(self):
        attempts = []

        def failure(request):
            attempts.append(request)
            raise TimeoutError('transient')
        rpc = RPC('https://example.invalid', limit=40, transport=failure, sleeper=lambda _seconds: None)
        with self.assertRaisesRegex(RuntimeError, 'provider_request_failed'):
            rpc.call('getGenesisHash', priority=True)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(rpc.retries, 0)
        self.assertEqual(rpc.http_requests, 0)
if __name__ == '__main__':
    unittest.main()
