"""Deterministic physical transport controls; no market endpoint is contacted."""
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import signal
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from engineering.pons_history.bounded import (
    Execution, Stop, NoRedirect, wall_guard, FIRST, LAST, RESPONSE, STORAGE, REFERENCE_TX)
from engineering.pons_history.capability import compare
from engineering.pons_history.fixtures import Tape
from engineering.pons_history.run_capability import supervise, classify, worker
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.pons_history import PonsHistory
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
from meme_machine.lanes.pons.provider import Rpc
from meme_machine.lanes.pons.provider_topology import PacedRpc, ProviderPacer
from meme_machine.lanes.pons.pons_historical import Preparation
from meme_machine.lanes.pons.pons_historical import order


class Response(io.BytesIO):
    def __init__(self, raw, *, length=True):
        super().__init__(raw)
        self.headers={'Content-Length':str(len(raw))} if length else {}
    read1=io.BytesIO.read


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,dict(MM_RUNTIME_LANE='pons',
            MM_PROVIDER_DB=str(self.root/'governor.sqlite'),
            MM_RPC_CACHE_DB=str(self.root/'cache.sqlite')),clear=True)
        self.env.start();self.addCleanup(self.env.stop)
        self.tape=Tape()
        self.tape.logs.sort(key=order)
        tick=[0.]
        def sleep(n):tick[0]+=n
        pacer=ProviderPacer(2,clock=lambda:tick[0],sleeper=sleep)
        self.rpc=PacedRpc('https://robinhood-mainnet.g.alchemy.com/v2/offline-test-key',
            role='directional_evidence_primary',requests_per_second=2,pacer=pacer,
            limit=64,per_scope=64,retries=0)
        self.rpc.shared_admission.clock=lambda:tick[0]
        self.rpc.shared_admission.sleep=sleep
        self.addCleanup(self.rpc.evidence_reuse.store.db.close)
        self.history=PonsHistory(self.root/'history.sqlite',policy=POLICY_HASH)
        self.addCleanup(self.history.close)
        self.requests=[]
        self.execution=Execution(self.rpc,self.root,time.monotonic()+45,opener=self.open)

    def open(self,request,**_):
        decoded=json.loads(request.data)
        rows=decoded if isinstance(decoded,list) else [decoded]
        self.requests.append(rows)
        replies=[dict(jsonrpc='2.0',id=r['id'],result=self.tape._read(r['method'],r['params'])) for r in rows]
        return Response(json.dumps(replies if isinstance(decoded,list) else replies[0]).encode())

    @contextmanager
    def installed(self):
        with self.execution.install():
            self.rpc.verify_chain()
            yield

    def test_full_comparison_has_exact_five_ranges_and_wire_accounting(self):
        with self.installed():
            receipt=compare(self.history,lambda:self.rpc,FIRST,required_transaction=REFERENCE_TX)
        self.assertTrue(receipt['equal'])
        self.assertEqual(receipt['baseline_digest'],receipt['candidate_digest'])
        self.assertEqual(self.execution.physical,len(self.requests))
        self.assertEqual(self.execution.wire_elements,sum(map(len,self.requests)))
        self.assertEqual(self.execution.request_bytes,self.rpc.request_bytes)
        self.assertEqual(self.execution.response_bytes,self.rpc.response_bytes)
        spans=[(int(r['params'][0]['fromBlock'],16),int(r['params'][0]['toBlock'],16))
               for rows in self.requests for r in rows if r['method']=='eth_getLogs']
        self.assertEqual(spans,[(b,b+9) for b in range(FIRST,LAST+1,10)]+[(FIRST,LAST)])
        self.assertTrue(self.history.get_meta('pons_capability_baseline')['authenticated'])

    def test_nested_boundary_transport_is_counted_before_dispatch(self):
        original=self.rpc._http_batch
        def nested(calls):
            if any(m=='eth_getTransactionReceipt' for m,_ in calls):
                self.rpc.call('eth_getBlockByNumber',[hex(FIRST),False],scope='nested_witness')
            return original(calls)
        self.rpc._http_batch=nested
        with self.installed():compare(self.history,lambda:self.rpc,FIRST)
        self.assertEqual(self.execution.physical,len(self.requests))
        self.assertEqual(self.execution.wire_elements,sum(map(len,self.requests)))
        self.assertEqual(self.execution.logical,self.execution.wire_elements+1) # chain cache hit
        self.assertTrue(any(r['method']=='eth_getBlockByNumber' for rows in self.requests for r in rows))

    def test_physical_ceiling_stops_nested_call_without_dispatch(self):
        with self.installed():
            self.execution.physical=32
            with self.assertRaises(Stop) as caught:
                self.rpc.call('eth_getBlockByNumber',[hex(FIRST),False])
        self.assertEqual(caught.exception.reason,'physical_attempt_ceiling')
        self.assertEqual(len(self.requests),1)
        self.assertEqual(self.rpc.physical_http_requests,1)

    def test_logical_ceiling_includes_cache_hits_and_batches(self):
        with self.installed():
            self.execution.logical=64
            with self.assertRaises(Stop):self.rpc.call('eth_chainId',[])
        self.assertEqual(len(self.requests),1)

    def test_diagnostic_cu_stops_before_wire_batch(self):
        with self.installed():
            self.execution.wire_elements=64
            with self.assertRaises(Stop):
                self.rpc.batch([('eth_getBlockByNumber',[hex(FIRST),False])])
        self.assertEqual(len(self.requests),1)

    def test_method_endpoint_and_range_allowlists(self):
        for method,params in [('eth_sendRawTransaction',['0x00']),('eth_blockNumber',[]),
                              ('eth_getBlockByNumber',['latest',False])]:
            self.execution.stopped=None
            with self.assertRaises(Stop):self.execution.demand([(method,params)])
        self.execution.stopped=None
        query=Preparation.population_filter()
        with self.assertRaises(Stop):self.execution.demand([
            ('eth_getLogs',[dict(query,fromBlock=hex(FIRST),toBlock=hex(LAST+1))])])
        self.execution.stopped=None
        with self.assertRaises(Stop):self.execution.http(Request('https://other.invalid',data=b'{}'),timeout=1)
        self.assertFalse(self.requests)

    def test_redirect_is_terminal_and_never_followed(self):
        with self.assertRaises(Stop):NoRedirect().redirect_request(None,None,302,None,None,None)

    def test_failed_transport_counts_and_cannot_be_retried(self):
        def fail(*_,**__):raise URLError('secret-credential-must-not-be-recorded')
        self.execution.opener=fail
        with self.execution.install():
            with self.assertRaises(BoundaryError):self.rpc.verify_chain()
            with self.assertRaises(Stop):self.rpc.verify_chain()
        self.assertEqual(self.execution.physical,1)
        self.assertEqual(self.execution.wire_elements,1)
        usage=(self.root/'usage.json').read_text()
        self.assertNotIn('secret-credential',usage)
        self.assertEqual(json.loads(usage)['attempts'][0]['status'],'failed')

    def test_explicit_candidate_range_rejection_and_preserved_authenticated_baseline(self):
        original=self.execution.opener
        def reject(request,**kwargs):
            rows=json.loads(request.data)
            if isinstance(rows,dict):rows=[rows]
            if any(r['method']=='eth_getLogs' and r['params'][0]['toBlock']==hex(LAST)
                   and r['params'][0]['fromBlock']==hex(FIRST) for r in rows):
                raw=json.dumps([dict(jsonrpc='2.0',id=1,error=dict(code=-32602,
                    message='eth_getLogs is limited to a 10 block range'))]).encode()
                raise HTTPError(request.full_url,400,'bad request',{'Content-Length':str(len(raw))},io.BytesIO(raw))
            return original(request,**kwargs)
        self.execution.opener=reject
        with self.installed():
            with self.assertRaises(Stop) as caught:compare(self.history,lambda:self.rpc,FIRST)
        self.assertEqual(caught.exception.classification,'UNSUPPORTED_40_BLOCK_RANGE')
        self.assertTrue(self.history.get_meta('pons_capability_baseline')['authenticated'])
        self.assertEqual(self.execution.physical,len(self.requests)+1)

    def test_response_content_length_is_rejected_before_read(self):
        response=Response(b'x'*(RESPONSE+1))
        with self.assertRaises(Stop):self.execution.read(response,{})
        self.assertEqual(response.tell(),0)
        self.assertEqual(self.execution.response_bytes,0)

    def test_chunked_response_never_reads_over_two_million_bytes(self):
        response=Response(b'x'*(RESPONSE+1),length=False)
        with self.assertRaises(Stop):self.execution.read(response,{})
        self.assertEqual(response.tell(),RESPONSE)
        self.assertEqual(self.execution.response_bytes,RESPONSE)

    def test_truncated_payload_and_bad_rpc_envelope_fail_closed(self):
        response=Response(b'{}');response.headers['Content-Length']='100'
        with self.assertRaises(Stop):self.execution.read(response,{})
        self.execution.stopped=None
        self.execution.opener=lambda *a,**k:Response(b'{"id":1,"result":"0x1237"}')
        with self.execution.install():
            with self.assertRaises(Stop):self.rpc.verify_chain()

    def test_storage_is_checked_before_dispatch_and_atomic_artifact_write(self):
        self.execution.storage=lambda:STORAGE-100
        with self.assertRaises(Stop):self.execution.save('big.json',b'x'*101)
        self.assertFalse((self.root/'big.json').exists())

    def test_alarm_interrupts_blocked_io_independently(self):
        began=time.monotonic()
        with self.assertRaises(Stop):
            with wall_guard(began+.03):time.sleep(5)
        self.assertLess(time.monotonic()-began,.5)

    def test_parent_kills_worker_even_when_alarm_is_ignored(self):
        marker=self.root/'before-stall.json'
        def stalled(_):
            signal.signal(signal.SIGALRM,signal.SIG_IGN)
            marker.write_text('{"physical_http_attempts":1}')
            time.sleep(5)
        result=supervise(stalled,seconds=.05,root=self.root)
        self.assertTrue(result['forced_shutdown'])
        self.assertLess(result['provider_window_seconds'],.5)
        self.assertEqual(json.loads(marker.read_text())['physical_http_attempts'],1)

    def test_wrong_chain_stops_without_logs(self):
        original=self.tape._read
        self.tape._read=lambda m,p:'0x1' if m=='eth_chainId' else original(m,p)
        with self.assertRaises(BoundaryError):
            with self.installed():compare(self.history,lambda:self.rpc,FIRST)
        self.assertEqual(self.execution.physical,1)

    def test_credential_echo_is_not_saved(self):
        self.execution.opener=lambda *a,**k:Response(json.dumps(dict(jsonrpc='2.0',id=1,
            result='offline-test-key')).encode())
        with self.execution.install():
            with self.assertRaises(BoundaryError):self.rpc.verify_chain()
        self.assertFalse(list(self.root.glob('response-*.json')))
        self.assertNotIn('offline-test-key',(self.root/'usage.json').read_text())

    def test_no_retry_preflight_and_generic_error_classification(self):
        self.rpc.retries=1
        with self.assertRaises(Stop):
            with self.execution.install():pass
        self.assertFalse(self.requests)
        self.assertEqual(classify(ValueError('some-secret')),('BLOCKED','provider_boundary_failure'))

    def test_reordered_candidate_cannot_pass_after_sorting(self):
        original=self.tape._read
        def reversed_candidate(method,params):
            value=original(method,params)
            if method=='eth_getLogs' and int(params[0]['toBlock'],16)-int(params[0]['fromBlock'],16)==39:
                return list(reversed(value))
            return value
        self.tape._read=reversed_candidate
        with self.installed():
            with self.assertRaisesRegex(BoundaryError,'event_order_disagreement'):
                compare(self.history,lambda:self.rpc,FIRST)

    def test_candidate_with_additional_duplicate_is_a_disagreement(self):
        original=self.tape._read
        def additional(method,params):
            value=original(method,params)
            if method=='eth_getLogs' and int(params[0]['toBlock'],16)-int(params[0]['fromBlock'],16)==39:
                return sorted(value+[value[-1]],key=order)
            return value
        self.tape._read=additional
        with self.installed():
            with self.assertRaisesRegex(BoundaryError,'duplicate_disagreement'):
                compare(self.history,lambda:self.rpc,FIRST)

    def test_boundary_reorganization_and_factory_code_mismatch_fail(self):
        original=self.tape._read
        seen=[0]
        def reorganized(method,params):
            value=original(method,params)
            if method=='eth_getBlockByNumber' and params[0]==hex(LAST):
                seen[0]+=1
                if seen[0]>1:value=dict(value,hash='0x'+'1'*64)
            return value
        self.tape._read=reorganized
        with self.installed():
            with self.assertRaisesRegex(BoundaryError,'range_reorg'):
                compare(self.history,lambda:self.rpc,FIRST)

    def test_factory_identity_mismatch_prevents_log_dispatch(self):
        original=self.tape._read
        self.tape._read=lambda m,p:'0x00' if m=='eth_getCode' else original(m,p)
        with self.installed():
            with self.assertRaisesRegex(BoundaryError,'bytecode_disagreement'):
                compare(self.history,lambda:self.rpc,FIRST)
        self.assertFalse(self.execution.log_spans)

    def test_complete_worker_shutdown_and_evidence_receipt_offline(self):
        root=self.root/'worker';root.mkdir()
        def action(started):
            os.environ['MM_ROBINHOOD_READ_RPC_URL']=self.rpc._endpoint
            os.environ['MM_RPC_CACHE_DB']=str(root/'evidence.sqlite')
            worker(root,started,opener=self.open)
        supervision=supervise(action,seconds=10,root=root)
        self.assertFalse(supervision['forced_shutdown'])
        data=json.loads((root/'worker-result.json').read_text())
        self.assertEqual(data['classification'],'SUPPORTED_40_BLOCK_SAMPLE')
        self.assertEqual(data['usage']['physical_http_attempts'],data['native_telemetry']['physical_http_requests'])
        self.assertTrue((root/'usage.json').exists())
        self.assertLess(data['usage']['estimated_cu'],6400)


if __name__=='__main__':unittest.main()
