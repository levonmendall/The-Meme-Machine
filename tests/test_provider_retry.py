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

    def test_batch_item_error_falls_back_only_for_failed_item(self):
        class PartialBatchRPC(RPC):
            def __init__(self):
                self.single=[]
                super().__init__('https://example.invalid',limit=40,clock=lambda:100.0,sleeper=lambda _seconds:None)
            def _http(self,request):
                if isinstance(request,list):
                    rows=[]
                    for i,item in enumerate(request):
                        if i==1:
                            rows.append({'jsonrpc':'2.0','id':item['id'],'error':{'code':-32005}})
                        else:
                            rows.append({'jsonrpc':'2.0','id':item['id'],'result':{'signature':item['params'][0]}})
                    return rows
                self.single.append(request['params'][0])
                return {'jsonrpc':'2.0','id':request['id'],'result':{'signature':request['params'][0]}}
        rpc=PartialBatchRPC()
        params=[[f'sig-{i}',{'encoding':'json','commitment':'finalized','maxSupportedTransactionVersion':0}] for i in range(4)]
        out=rpc.call_many('getTransaction',params,True,batch_size=4)
        self.assertEqual([x['signature'] for x in out],[f'sig-{i}' for i in range(4)])
        self.assertEqual(rpc.single,['sig-1'])
        self.assertEqual((rpc.batch_fallbacks,rpc.batch_fallback_items),(1,1))
        self.assertEqual(rpc.failure_methods,{'getTransaction:provider_error':1})
        self.assertEqual((rpc.calls,rpc.http_requests),(5,2))

    def test_rejected_batch_degrades_to_bounded_individual_reads(self):
        class NoBatchRPC(RPC):
            def __init__(self):
                self.singles=0
                super().__init__('https://example.invalid',limit=40,clock=lambda:100.0,sleeper=lambda _seconds:None)
            def _http(self,request):
                if isinstance(request,list):
                    return {'jsonrpc':'2.0','id':1,'error':{'code':-32600}}
                self.singles+=1
                return {'jsonrpc':'2.0','id':request['id'],'result':{'signature':request['params'][0]}}
        rpc=NoBatchRPC()
        params=[[f'sig-{i}',{'encoding':'json','commitment':'finalized','maxSupportedTransactionVersion':0}] for i in range(4)]
        out=rpc.call_many('getTransaction',params,True,batch_size=4)
        self.assertEqual(len(out),4);self.assertEqual(rpc.singles,4)
        self.assertEqual((rpc.batch_fallbacks,rpc.batch_fallback_items),(1,4))
        self.assertEqual(rpc.failure_methods,{'getTransaction:provider_error':4})
        self.assertEqual((rpc.calls,rpc.http_requests),(8,5))

    def test_individual_transaction_null_retries_once(self):
        class NullOnceRPC(RPC):
            def __init__(self):
                self.n=0
                super().__init__('https://example.invalid',limit=40,clock=lambda:100.0,sleeper=lambda _seconds:None)
            def _http(self,request):
                self.n+=1
                return {'jsonrpc':'2.0','id':request['id'],'result':None if self.n==1 else {'slot':1}}
        rpc=NullOnceRPC()
        value=rpc.call('getTransaction',['sig',{'encoding':'json','commitment':'finalized','maxSupportedTransactionVersion':0}],True)
        self.assertEqual(value,{'slot':1})
        self.assertEqual((rpc.null_retries,rpc.retries,rpc.failures),(1,1,1))
        self.assertEqual(rpc.failure_methods,{'getTransaction:null_result':1})

    def test_dense_dlmm_bodies_are_serialized_without_batch_transport(self):
        from tests import dlmm_boundary_acquisition as boundary
        class Dense:
            def __init__(self):
                self.calls=[];self.sleeps=[];self.batch_calls=0
            def sleep(self,seconds): self.sleeps.append(seconds)
            def call(self,method,params,priority):
                self.calls.append((method,params,priority))
                return {'signature':params[0],'slot':1}
            def call_many(self,*args,**kwargs):
                self.batch_calls+=1
                raise AssertionError('dense interval must not batch transaction bodies')
        rpc=Dense()
        relevant=[dict(signature=f'sig-{i}') for i in range(14)]
        telemetry={}
        out=boundary._fetch_transaction_bodies(rpc,relevant,telemetry)
        self.assertEqual(len(out),14)
        self.assertEqual(rpc.batch_calls,0)
        self.assertEqual(len(rpc.calls),14)
        self.assertEqual(rpc.sleeps,[boundary.DENSE_TRANSACTION_PACE_SECONDS]*13)
        self.assertEqual(telemetry['transaction_retrieval_mode'],'serialized_single_getTransaction')

    def test_small_dlmm_body_set_keeps_bounded_batching(self):
        from tests import dlmm_boundary_acquisition as boundary
        class Small:
            def __init__(self): self.batch=None
            def call_many(self,method,params,priority,batch_size):
                self.batch=(method,len(params),priority,batch_size)
                return [{'signature':p[0]} for p in params]
        rpc=Small();telemetry={}
        out=boundary._fetch_transaction_bodies(
            rpc,[dict(signature=f'sig-{i}') for i in range(3)],telemetry)
        self.assertEqual(len(out),3)
        self.assertEqual(rpc.batch,('getTransaction',3,True,4))
        self.assertEqual(telemetry['transaction_retrieval_mode'],'bounded_call_many_batch_size_4')

    def test_gettransaction_provider_error_retry_uses_longer_backoff(self):
        sleeps=[]
        class ProviderErrorOnceRPC(RPC):
            def __init__(self):
                self.n=0
                super().__init__('https://example.invalid',limit=40,clock=lambda:100.0,
                                 sleeper=lambda seconds:sleeps.append(seconds))
            def _http(self,request):
                self.n+=1
                if self.n==1:
                    return {'jsonrpc':'2.0','id':request['id'],
                            'error':{'code':-32005}}
                return {'jsonrpc':'2.0','id':request['id'],'result':{'slot':1}}
        rpc=ProviderErrorOnceRPC()
        value=rpc.call('getTransaction',
            ['sig',{'encoding':'json','commitment':'finalized',
                    'maxSupportedTransactionVersion':0}],True)
        self.assertEqual(value,{'slot':1})
        self.assertEqual((rpc.failures,rpc.retries),(1,1))
        self.assertIn(1.5,sleeps)

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
