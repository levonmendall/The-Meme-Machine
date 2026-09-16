import unittest
from meme_machine import pump
from meme_machine.provider import RPC, PumpAdapter
from tests.support import SCOUT


class BoundedRetry(unittest.TestCase):
    def test_real_http_path_retries_once_and_counts_budget(self):
        class FlakyRPC(RPC):
            def __init__(self):
                self.attempts=0
                super().__init__('https://example.invalid',limit=40,clock=lambda:100.0)
            def _http(self,request):
                self.attempts+=1
                if self.attempts==1:
                    raise TimeoutError('transient')
                return {'result':'ok'}
        rpc=FlakyRPC()
        self.assertEqual(rpc.call('getGenesisHash',priority=True),'ok')
        self.assertEqual(rpc.calls,2)
        self.assertEqual(rpc.failures,1)
        self.assertEqual(rpc.retries,1)
        # Cached replay makes no additional provider attempt.
        self.assertEqual(rpc.call('getGenesisHash',priority=True),'ok')
        self.assertEqual(rpc.calls,2)
        self.assertEqual(rpc.cache_hits,1)

    def test_custom_transport_remains_single_attempt(self):
        attempts=[]
        def failure(request):
            attempts.append(request)
            raise TimeoutError('transient')
        rpc=RPC('https://example.invalid',limit=40,transport=failure)
        with self.assertRaisesRegex(RuntimeError,'provider_request_failed'):
            rpc.call('getGenesisHash',priority=True)
        self.assertEqual(len(attempts),1)
        self.assertEqual(rpc.retries,0)

    def test_required_pool_window_short_circuits_before_transaction_reads(self):
        calls=[]
        def transport(request):
            calls.append(request)
            if request['method']=='getGenesisHash':
                return {'result':pump.MAINNET}
            if request['method']=='getSignaturesForAddress':
                # Forty recent signatures still do not reach the start of the
                # 60-second evidence window. No transaction body can make this
                # window complete, so the adapter must stop here.
                return {'result':[{'signature':f'sig-{i}','blockTime':90,'err':None} for i in range(40)]}
            raise AssertionError('transaction body should not be requested')
        rpc=RPC('https://example.invalid',limit=40,transport=transport,clock=lambda:100.0)
        adapter=PumpAdapter(rpc)
        events,covered=adapter.history(SCOUT,100,priority=True,require_coverage=True)
        self.assertEqual(events,[])
        self.assertFalse(covered)
        self.assertEqual([x['method'] for x in calls],['getGenesisHash','getSignaturesForAddress'])
        self.assertEqual(calls[-1]['params'][1]['limit'],40)


if __name__=='__main__':
    unittest.main()
