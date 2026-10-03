import unittest
from meme_machine.lanes.meteora.provider import RPC,Unavailable


class LocalAdmissionRetryTests(unittest.TestCase):
    def test_local_batch_or_single_rejection_never_retries_or_counts_provider_failure(self):
        for batch in (False,True):
            for reason in ('evidence_deadline_before_transport','certification_provider_queue_deadline',
                           'certification_provider_queue_capacity'):
                with self.subTest(batch=batch,reason=reason):
                    class AdmissionRpc(RPC):
                        attempts=0
                        def _http(self,request):
                            self.attempts+=1
                            self.evidence_local_failure=reason
                            raise TimeoutError(reason)
                    rpc=AdmissionRpc('https://invalid.example',clock=lambda:10,sleeper=lambda _:None)
                    rpc.evidence_deadline=11
                    with self.assertRaisesRegex(Unavailable,reason):
                        if batch:rpc.call_many('getTransaction',[[str(i)] for i in range(8)])
                        else:rpc.call('getTransaction',['sig'])
                    self.assertEqual(rpc.attempts,1)
                    self.assertEqual(rpc.http_requests,0)
                    self.assertEqual(rpc.retries,0)
                    self.assertEqual(rpc.failures,0)
                    self.assertEqual(rpc.failure_kinds,{})
                    self.assertEqual(rpc.evidence_deadline,11)

    def test_pacer_cannot_send_after_original_deadline(self):
        for batch in (False,True):
            for initial in (10,12):
                with self.subTest(batch=batch,initial=initial):
                    clock=[initial]
                    class ExpiringRpc(RPC):
                        def _pace(self,*args):clock[0]=12
                        def _http(self,request):raise AssertionError('expired request reached transport')
                    rpc=ExpiringRpc('https://invalid.example',clock=lambda:clock[0],sleeper=lambda _:None)
                    rpc.evidence_deadline=11
                    with self.assertRaisesRegex(Unavailable,'evidence_deadline_before_transport'):
                        if batch:rpc.call_many('getTransaction',[['sig']])
                        else:rpc.call('getTransaction',['sig'])
                    self.assertEqual(rpc.calls,0)
                    self.assertEqual(rpc.http_requests,0)
                    self.assertEqual(rpc.failures,0)
                    self.assertEqual(rpc.retries,0)
