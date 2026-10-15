"""Bounded HTTP attribution through actual transport and admission wrappers.

All HTTP is replaced. Temporary ledgers never share production paths.
"""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.provider import HTTP_ERROR_BYTES, Rpc
from meme_machine.lanes.pons.provider_topology import (ObservationFallbackRpc,
    PacedRpc, ProviderPacer, PUBLIC_DIAGNOSTIC_RPC_URL)
from meme_machine.runtime.provider_purchases import provider_work


URL = 'https://example.invalid/v2/SYNTHETIC_SECRET_839485'


class Clock:
    def __init__(self):self.now=100.
    def time(self):return self.now
    def sleep(self, value):self.now+=value


class HTTPFailureContextTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,{},clear=True)
        env.start();self.addCleanup(env.stop)

    def failure(self, *, status=429, body=None, headers=None, fp=None):
        if body is None:body=json.dumps({'error':{'code':429,'message':'rate limit exceeded'}}).encode()
        return HTTPError(URL,status,URL,headers or {},fp if fp is not None else io.BytesIO(body))

    def caught(self, rpc, error, *, batch=False):
        with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=error) as opened:
            with self.assertRaises(BoundaryError) as caught:
                if batch:rpc.batch([('eth_getLogs',[{'secret':URL}]),('eth_getBlockByNumber',['0x1',False])])
                else:rpc.call('eth_getLogs',[{'secret':URL}])
        return caught.exception,opened

    def assert_redacted(self, value):
        encoded=json.dumps(value)
        self.assertNotIn(URL,encoded)
        self.assertNotIn('SYNTHETIC_SECRET_839485',encoded)
        self.assertNotIn('arbitrary_error_data',encoded)

    def test_single_429_retains_safe_context_bytes_and_original_no_retry(self):
        body=json.dumps({'error':{'code':-32005,'message':'rate limit exceeded '+URL,
            'data':{'arbitrary_error_data':URL}}}).encode()
        rpc=Rpc(URL,retries=2)
        error,opened=self.caught(rpc,self.failure(body=body,headers={
            'Retry-After':'.75','X-RateLimit-Remaining':'0','X-Request-ID':'req-42',
            'X-Correlation-ID':'SYNTHETIC_SECRET_839485','Authorization':URL}))
        self.assertEqual(str(error),'provider_http_429')
        self.assertEqual(opened.call_count,1)
        context=error.provider_http_context
        self.assertEqual(context['response_headers'],{
            'retry-after':.75,'x-ratelimit-remaining':'0','x-request-id':'req-42'})
        self.assertTrue(context['header_value_redacted'])
        self.assertEqual(context['error_fields']['errors'],[{
            'code':-32005,'message_classes':['rate_limit']}])
        self.assertEqual(context['methods'],['eth_getLogs'])
        self.assertEqual(context['logical_elements'],1)
        self.assertEqual(context['body_bytes_read'],len(body))
        self.assertFalse(context['body_read_failed'])
        self.assertEqual(context['inflight_scope'],'process_endpoint')
        self.assertGreaterEqual(context['completion_monotonic'],context['dispatch_monotonic'])
        self.assertEqual(rpc.last_retry_after_seconds,.75)
        telemetry=rpc.telemetry()
        self.assertEqual(telemetry['physical_http_requests'],1)
        self.assertEqual(telemetry['response_bytes'],len(body))
        self.assertEqual(telemetry['provider_purchases']['totals']['delivered_payload_bytes'],len(body))
        self.assertEqual(telemetry['last_transport_failure']['http_context'],context)
        self.assert_redacted(telemetry)
        self.assert_redacted(error.__notes__)

    def test_batch_429_retains_elements_without_request_bindings_or_attempts(self):
        rpc=Rpc(URL,retries=2)
        error,opened=self.caught(rpc,self.failure(),batch=True)
        self.assertEqual(str(error),'provider_http_429')
        self.assertEqual(opened.call_count,1)
        context=error.provider_http_context
        self.assertTrue(context['batch'])
        self.assertEqual(context['logical_elements'],2)
        self.assertEqual(context['methods'],['eth_getLogs','eth_getBlockByNumber'])
        self.assertEqual(rpc.used,2)
        self.assertEqual(rpc.transport_used,1)
        self.assertEqual(rpc.retry_count,0)
        self.assert_redacted(context)

    def test_body_read_is_capped_and_only_delivered_bytes_are_booked(self):
        rpc=Rpc(URL,retries=0)
        error,_=self.caught(rpc,self.failure(body=b'x'*(HTTP_ERROR_BYTES+100)))
        context=error.provider_http_context
        self.assertEqual(context['body_bytes_read'],HTTP_ERROR_BYTES)
        self.assertTrue(context['body_truncated'])
        self.assertFalse(context['error_fields']['json_valid'])
        self.assertEqual(rpc.response_bytes,HTTP_ERROR_BYTES)

    def test_read_failure_preserves_status_and_exposes_unknown_read_bytes(self):
        class Broken(io.BytesIO):
            def read(self,_):raise OSError(URL)
            def close(self):raise OSError(URL)
        rpc=Rpc(URL,retries=1)
        error,opened=self.caught(rpc,self.failure(fp=Broken()))
        self.assertEqual(str(error),'provider_http_429')
        self.assertEqual(opened.call_count,1)
        self.assertTrue(error.provider_http_context['body_read_failed'])
        self.assertTrue(error.provider_http_context['body_read_bytes_unknown'])
        self.assertTrue(error.provider_http_context['response_close_failed'])
        self.assertEqual(rpc.response_bytes,0)
        self.assert_redacted(error.__notes__)

    def test_optional_header_probe_failure_cannot_replace_original_status(self):
        rpc=Rpc(URL,retries=1)
        with patch.object(rpc,'_error_headers',side_effect=RuntimeError(URL)):
            error,opened=self.caught(rpc,self.failure())
        self.assertEqual(str(error),'provider_http_429')
        self.assertEqual(opened.call_count,1)
        self.assertEqual(error.provider_http_context['http_status'],429)
        self.assertTrue(error.provider_http_context['context_capture_failed'])
        self.assertFalse(error.provider_http_context['context_complete'])
        self.assert_redacted(error.__notes__)

    def test_socket_read_timeout_uses_remaining_original_deadline(self):
        clock=Clock();timeouts=[]
        class Socket:
            def settimeout(self,value):timeouts.append(value)
        class Body:
            def __init__(self):
                self.fp=type('Buffered',(),{'raw':type('Raw',(),{'_sock':Socket()})()})()
                self.body=io.BytesIO(b'{"error":{"code":429}}')
            def read1(self,n):return self.body.read(n)
            def close(self):pass
        rpc=Rpc(URL,retries=0);rpc.evidence_deadline=100.5
        error=self.failure(fp=Body())
        def rejected(*args,**kwargs):
            self.assertAlmostEqual(kwargs['timeout'],.5)
            clock.now+=.3
            raise error
        with patch('meme_machine.lanes.pons.provider.time.monotonic',side_effect=clock.time),\
             patch('meme_machine.lanes.pons.provider.urlopen',side_effect=rejected):
            with self.assertRaisesRegex(BoundaryError,'provider_http_429') as caught:
                rpc.call('eth_getLogs',[{}])
        self.assertTrue(timeouts)
        self.assertTrue(all(abs(value-.2)<1e-9 for value in timeouts))
        self.assertEqual(caught.exception.provider_http_context['body_bytes_read'],22)

    def test_expired_deadline_does_not_read_or_replace_429(self):
        clock=Clock();body=io.BytesIO(b'{"error":{"code":429}}')
        rpc=Rpc(URL,retries=0);rpc.evidence_deadline=100.5
        read=patch.object(body,'read',wraps=body.read)
        def rejected(*args,**kwargs):
            clock.now=100.6
            raise self.failure(fp=body)
        with patch('meme_machine.lanes.pons.provider.time.monotonic',side_effect=clock.time),\
             patch('meme_machine.lanes.pons.provider.urlopen',side_effect=rejected),read as received:
            with self.assertRaisesRegex(BoundaryError,'provider_http_429') as caught:
                rpc.call('eth_getLogs',[{}])
        self.assertEqual(received.call_count,0)
        context=caught.exception.provider_http_context
        self.assertTrue(context['body_read_skipped'])
        self.assertEqual(context['body_read_skip_reason'],'original_deadline')
        self.assertEqual(rpc.response_bytes,0)

    def test_unknown_response_wrapper_is_left_unread_when_deadline_unbound(self):
        class Body:
            def read(self,_):raise AssertionError('must_not_read_unbounded_wrapper')
            def close(self):pass
        error,_=self.caught(Rpc(URL),self.failure(fp=Body()))
        self.assertEqual(str(error),'provider_http_429')
        context=error.provider_http_context
        self.assertEqual(context['body_read_skip_reason'],'timeout_binding_unavailable')
        self.assertEqual(context['body_bytes_read'],0)

    def test_retry_after_date_and_safe_policy_headers_are_bounded(self):
        error,_=self.caught(Rpc(URL),self.failure(headers={
            'Retry-After':'Wed, 14 Oct 2026 12:00:00 GMT',
            'RateLimit-Policy':'10;w=1,100;w=60','X-Request-ID':'x'*129,
            'RateLimit-Remaining':URL}))
        context=error.provider_http_context
        self.assertEqual(context['response_headers'],{
            'retry-after':'2026-10-14T12:00:00+00:00',
            'ratelimit-policy':'10;w=1,100;w=60'})
        self.assert_redacted(context)

    def test_existing_400_range_boundary_still_records_payload(self):
        body=b'{"error":{"message":"block range limit exceeded"}}'
        for batch in (False,True):
            with self.subTest(batch=batch):
                rpc=Rpc(URL,retries=0)
                error,_=self.caught(rpc,self.failure(status=400,body=body),batch=batch)
                self.assertEqual(str(error),'provider_log_block_range_limit')
                self.assertEqual(error.provider_http_context['http_status'],400)
                self.assertEqual(rpc.response_bytes,len(body))

    def test_wrapper_ancestry_and_actual_admission_row_retain_terminal_context(self):
        with tempfile.TemporaryDirectory() as td:
            clock=Clock();path=Path(td)/'admission.sqlite'
            with patch.dict(os.environ,{'MM_PROVIDER_DB':str(path)}):
                rpc=PacedRpc(URL,role='public_observation_diagnostic',requests_per_second=2,
                    pacer=ProviderPacer(2,clock=clock.time,sleeper=clock.sleep),retries=2)
            rpc.shared_admission.clock=clock.time
            rpc.shared_admission.sleep=clock.sleep
            with provider_work('retries_duplicates',family='pons',consumer='discovery',
                    purpose='discovery',retry_attempt=2):
                error,opened=self.caught(rpc,self.failure(headers={'X-Request-ID':'public-42'}))
            self.assertEqual(opened.call_count,1)
            context=error.provider_http_context
            self.assertEqual(context['wrapper_retry_ancestry']['retry_attempt'],2)
            self.assertEqual(context['rpc_retry_attempt'],0)
            self.assertEqual(context['admission_retry_attempt'],0)
            connection=rpc.shared_admission.connect()
            try:
                row=json.loads(connection.execute('SELECT body FROM transports').fetchone()[0])
                counters=dict(connection.execute('SELECT metric,SUM(value) FROM provider_usage GROUP BY metric'))
            finally:connection.close()
            self.assertEqual(row['http_status'],429)
            self.assertEqual(row['http_error_context'],context)
            self.assertEqual(row['response_bytes'],context['body_bytes_read'])
            self.assertEqual(row['transport_dispatch_monotonic'],context['dispatch_monotonic'])
            self.assertEqual(row['transport_complete_monotonic'],context['completion_monotonic'])
            self.assertEqual(row['transport_inflight_scope'],'process_endpoint')
            self.assertEqual(counters['physical_http_requests'],1)
            self.assertEqual(counters['responses_429'],1)
            self.assertEqual(counters['response_bytes'],context['body_bytes_read'])
            self.assertEqual(rpc.telemetry()['last_transport_failure']['http_context'],context)
            self.assert_redacted(row)

    def test_canonical_request_fingerprints_correlate_exact_logical_duplicates(self):
        def capture(calls):
            rpc=Rpc(URL,retries=0)
            with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=self.failure()):
                with self.assertRaises(BoundaryError) as caught:
                    if len(calls)==1:rpc.call(*calls[0])
                    else:rpc.batch(calls)
            return caught.exception.provider_http_context
        first=('eth_getLogs',[{'fromBlock':'0x1','toBlock':'0x2','secret':URL}])
        reordered=('eth_getLogs',[{'toBlock':'0x2','secret':URL,'fromBlock':'0x1'}])
        changed=('eth_getLogs',[{'toBlock':'0x3','secret':URL,'fromBlock':'0x1'}])
        single=capture([first]);same=capture([reordered]);different=capture([changed])
        batch=capture([first,reordered,changed])
        self.assertEqual(single['request_fingerprint'],same['request_fingerprint'])
        self.assertNotEqual(single['request_fingerprint'],different['request_fingerprint'])
        self.assertEqual(batch['logical_request_fingerprints'],[
            single['logical_request_fingerprints'][0],same['logical_request_fingerprints'][0],
            different['logical_request_fingerprints'][0]])
        self.assertEqual(batch['method_counts'],{'eth_getLogs':3})
        self.assert_redacted(batch)

    def test_partial_read_rebinds_absolute_timeout_and_books_known_bytes(self):
        clock=Clock();timeouts=[];reads=[]
        class Socket:
            def settimeout(self,value):timeouts.append(value)
        class Body:
            def __init__(self):
                self.fp=type('Buffered',(),{'raw':type('Raw',(),{'_sock':Socket()})()})()
            def read1(self,n):
                reads.append(n)
                if len(reads)==1:
                    clock.now+=.1
                    return b'{"error":'
                raise TimeoutError(URL)
            def close(self):pass
        rpc=Rpc(URL,retries=0);rpc.evidence_deadline=100.5
        with patch('meme_machine.lanes.pons.provider.time.monotonic',side_effect=clock.time):
            error,opened=self.caught(rpc,self.failure(fp=Body()))
        self.assertEqual(str(error),'provider_http_429')
        self.assertEqual(opened.call_count,1)
        self.assertEqual(reads,[1024,1024])
        self.assertAlmostEqual(timeouts[-1],.4)
        self.assertEqual(rpc.response_bytes,9)
        context=error.provider_http_context
        self.assertEqual(context['body_bytes_read'],9)
        self.assertTrue(context['body_read_failed'])
        self.assertTrue(context['body_read_bytes_unknown'])
        self.assertFalse(context['body_read_complete'])

    def test_chunked_body_is_not_read_under_an_unbounded_header_parser(self):
        class Body:
            chunked=True
            def read1(self,_):raise AssertionError('must_not_parse_chunk_headers')
            def close(self):pass
        error,_=self.caught(Rpc(URL),self.failure(fp=Body()))
        self.assertEqual(str(error),'provider_http_429')
        self.assertEqual(error.provider_http_context['body_read_skip_reason'],
            'chunked_deadline_unbounded')
        self.assertEqual(error.provider_http_context['body_bytes_read'],0)

    def test_actual_retry_and_fallback_calls_retain_bounded_wrapper_ancestry(self):
        clock=Clock();started=[];recovery=Rpc(URL,retries=0)
        rpc=ObservationFallbackRpc(PUBLIC_DIAGNOSTIC_RPC_URL,
            role='public_observation_diagnostic',requests_per_second=2,
            pacer=ProviderPacer(2,clock=clock.time,sleeper=clock.sleep),
            recovery_rpc=recovery,retries=0)
        def rejected(request,**kwargs):
            started.append(request.full_url)
            raise HTTPError(request.full_url,429,URL,{},io.BytesIO(
                b'{"error":{"code":429,"message":"rate limit exceeded"}}'))
        with patch('meme_machine.lanes.pons.provider.time.monotonic',side_effect=clock.time),\
             patch('meme_machine.lanes.pons.provider.urlopen',side_effect=rejected):
            with self.assertRaisesRegex(BoundaryError,'provider_http_429') as caught:
                rpc.call('eth_getLogs',[{'fromBlock':'0x1','toBlock':'0x2'}])
        self.assertEqual(started,[PUBLIC_DIAGNOSTIC_RPC_URL,PUBLIC_DIAGNOSTIC_RPC_URL,URL])
        path=caught.exception.provider_http_context['wrapper_retry_path']
        self.assertEqual([row['wrapper'] for row in path],[
            'public_same_endpoint_retry','canonical_exact_fallback'])
        self.assertEqual([row['cause_boundary'] for row in path],[
            'provider_http_429','provider_http_429'])
        self.assertEqual(rpc.public_log_retry_failures,1)
        self.assertEqual(rpc.recovery_requests,1)
        self.assertEqual(rpc.recovery_failures,1)
        self.assert_redacted(caught.exception.__notes__)
        # Context is task-local and must not leak into an unrelated next call.
        independent,_=self.caught(Rpc(URL,retries=0),self.failure())
        self.assertEqual(independent.provider_http_context['wrapper_retry_path'],[])

    def test_endpoint_slash_alias_context_matches_shared_admission_identity(self):
        canonical='https://robinhood-mainnet.g.alchemy.com/v2/SYNTHETIC_SECRET_839485'
        for base,alias in ((URL,URL+'/'),(canonical,canonical.replace('.com/','.com:443/')+'/')):
            with self.subTest(base=base),tempfile.TemporaryDirectory() as td:
                clock=Clock();path=Path(td)/'admission.sqlite';contexts=[]
                for endpoint in (base,alias):
                    with patch.dict(os.environ,{'MM_PROVIDER_DB':str(path)}):
                        rpc=PacedRpc(endpoint,role='public_observation_diagnostic',requests_per_second=2,
                            pacer=ProviderPacer(2,clock=clock.time,sleeper=clock.sleep),retries=0)
                    rpc.shared_admission.clock=clock.time;rpc.shared_admission.sleep=clock.sleep
                    error,_=self.caught(rpc,self.failure(headers={
                        'X-Request-ID':'SYNTHETIC_SECRET_839485'}))
                    context=error.provider_http_context;contexts.append(context)
                    self.assertEqual(context['endpoint_fingerprint'],rpc.shared_admission.endpoint)
                    self.assertTrue(context['header_value_redacted'])
                    self.assert_redacted(context)
                self.assertEqual(contexts[0]['endpoint_fingerprint'],contexts[1]['endpoint_fingerprint'])
                connection=rpc.shared_admission.connect()
                try:rows=[json.loads(row[0]) for row in connection.execute('SELECT body FROM transports')]
                finally:connection.close()
                self.assertEqual(len(rows),2)
                for row in rows:
                    self.assertEqual(row['endpoint_fingerprint'],row['http_error_context']['endpoint_fingerprint'])
