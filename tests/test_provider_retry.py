import unittest
from meme_machine import pump
from meme_machine.provider import RPC, PumpAdapter
from tests.support import SCOUT


class BoundedRetry(unittest.TestCase):
    def test_real_http_path_retries_once_and_counts_budget(self):
        class FlakyRPC(RPC):
            def __init__(self):
                self.attempts=0
                super().__init__('https://example.invalid',limit=40,clock=lambda:100.0,sleeper=lambda _seconds:None)
            def _http(self,request):
                self.attempts+=1
                if self.attempts==1:
                    raise TimeoutError('transient')
                return {'result':'ok'}
        rpc=FlakyRPC()
        self.assertEqual(rpc.call('getGenesisHash',priority=True),'ok')
        self.assertEqual(rpc.calls,2)
        self.assertEqual(rpc.http_requests,2)
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
        rpc=RPC('https://example.invalid',limit=40,transport=failure,sleeper=lambda _seconds:None)
        with self.assertRaisesRegex(RuntimeError,'provider_request_failed'):
            rpc.call('getGenesisHash',priority=True)
        self.assertEqual(len(attempts),1)
        self.assertEqual(rpc.retries,0)
        self.assertEqual(rpc.http_requests,0)

    def test_required_pool_window_short_circuits_before_transaction_reads(self):
        calls=[]
        def transport(request):
            calls.append(request)
            if request['method']=='getGenesisHash':
                return {'result':pump.MAINNET}
            if request['method']=='getSignaturesForAddress':
                # Even the maximum bounded signature census does not reach strictly
                # before the 60-second cutoff. No body fetch can make it complete.
                return {'result':[{'signature':f'sig-{i}','blockTime':90,'err':None} for i in range(1000)]}
            raise AssertionError('transaction body should not be requested')
        rpc=RPC('https://example.invalid',limit=40,transport=transport,clock=lambda:100.0,sleeper=lambda _seconds:None)
        adapter=PumpAdapter(rpc)
        events,covered=adapter.history(SCOUT,100,priority=True,require_coverage=True)
        self.assertEqual(events,[])
        self.assertFalse(covered)
        self.assertEqual([x['method'] for x in calls],['getGenesisHash','getSignaturesForAddress'])
        self.assertEqual(calls[-1]['params'][1]['limit'],1000)

    def test_dense_complete_window_batches_bodies_but_counts_logical_budget(self):
        class DenseRPC(RPC):
            def __init__(self):
                self.batch_sizes=[]
                super().__init__('https://example.invalid',limit=120,clock=lambda:100.0,sleeper=lambda _seconds:None)
            def _http(self,request):
                if isinstance(request,list):
                    self.batch_sizes.append(len(request))
                    if request and request[0]['method']=='getTransaction':
                        self.assert_v1=all(
                            item['params'][1]['maxSupportedTransactionVersion']==1
                            for item in request)
                    # JSON-RPC batch responses need not preserve request order.
                    return list(reversed([
                        {'jsonrpc':'2.0','id':item['id'],
                         'result':{'slot':500,'meta':{'err':None,'logMessages':[]}}}
                        for item in request
                    ]))
                if request['method']=='getGenesisHash':
                    return {'jsonrpc':'2.0','id':request['id'],'result':pump.MAINNET}
                if request['method']=='getSignaturesForAddress':
                    rows=[{'signature':f'sig-{i}','blockTime':99-i,'err':None} for i in range(60)]
                    rows.append({'signature':'older-boundary','blockTime':39,'err':None})
                    return {'jsonrpc':'2.0','id':request['id'],'result':rows}
                raise AssertionError(request['method'])
        rpc=DenseRPC();adapter=PumpAdapter(rpc)
        events,covered=adapter.history(SCOUT,100,priority=True,require_coverage=True)
        self.assertTrue(covered)
        self.assertEqual(events,[])
        self.assertEqual(rpc.calls,62)  # genesis + signature census + 60 logical tx reads
        self.assertEqual(rpc.http_requests,10)  # 2 singles + eight <=8-item HTTP batches
        self.assertEqual(rpc.batch_sizes,[8,8,8,8,8,8,8,4])
        self.assertEqual(rpc.failures,0)
        self.assertTrue(rpc.assert_v1)

    def test_unknown_signature_time_cannot_claim_complete_window(self):
        calls=[]
        def transport(request):
            calls.append(request)
            if request['method']=='getGenesisHash':
                return {'result':pump.MAINNET}
            if request['method']=='getSignaturesForAddress':
                return {'result':[
                    {'signature':'new','blockTime':99,'err':None},
                    {'signature':'unknown','blockTime':None,'err':None},
                    {'signature':'old','blockTime':39,'err':None},
                ]}
            raise AssertionError('unknown timestamp must fail closed before body reads')
        rpc=RPC('https://example.invalid',limit=40,transport=transport,clock=lambda:100.0,sleeper=lambda _seconds:None)
        adapter=PumpAdapter(rpc)
        events,covered=adapter.history(SCOUT,100,priority=True,require_coverage=True)
        self.assertEqual(events,[])
        self.assertFalse(covered)
        self.assertEqual(len(calls),2)


if __name__=='__main__':
    unittest.main()
