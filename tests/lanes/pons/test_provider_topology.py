"""Canonical authority regressions; all HTTP is replaced before invocation."""
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.error import HTTPError
from meme_machine.runtime.robinhood import provider_authority as authority
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.provider_topology import (
    PacedRpc, ProviderPacer, configured_rpc, configured_dlmm_rpc,
    configured_discovery_rpc, configured_shadow_rpc, topology_metadata)
from meme_machine.lanes.pons.provider_admission import Admission

URL='https://robinhood-mainnet.g.alchemy.com/v2/SYNTHETIC_SECRET_839485'

class Clock:
    def __init__(self):self.now=100.;self.lock=threading.Lock()
    def time(self):
        with self.lock:return self.now
    def sleep(self,n):
        with self.lock:self.now+=n

class ProviderAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'MM_ROBINHOOD_READ_RPC_URL':URL,
            'MM_ROBINHOOD_STATE_DIR':self.tmp.name},clear=True)
        self.env.start();self.addCleanup(self.env.stop)
        self.clock=Clock();self.requests=[]
    def client(self,factory=configured_rpc,**kwargs):
        rpc=factory(retries=0,limit=80,per_scope=80,**kwargs)
        rpc.pacer=ProviderPacer(2,clock=self.clock.time,sleeper=self.clock.sleep)
        rpc.shared_admission.clock=self.clock.time;rpc.shared_admission.sleep=self.clock.sleep
        return rpc
    def http(self,request,**kwargs):
        payload=json.loads(request.data);self.requests.append(payload)
        def reply(row):
            method=row['method']
            value='0x1237' if method=='eth_chainId' else '0x123'
            if method=='eth_getBlockByHash':value={'hash':row['params'][0],'number':'0x1','timestamp':'0x2'}
            return dict(jsonrpc='2.0',id=row['id'],result=value)
        result=[reply(r) for r in payload] if isinstance(payload,list) else reply(payload)
        return io.BytesIO(json.dumps(result).encode())
    def test_runtime_composition_retains_broker_boundaries(self):
        # Supplemental wiring guard; coalescing/fencing and provider tests above
        # exercise the actual broker and transport implementations.
        from meme_machine.lanes.pons import pons_selective_cohort
        source=Path(pons_selective_cohort.__file__).read_text()
        for required in ['queue=Broker(', 'queue.committed()', 'evidence_context.generation_guard=', 'queue.finish(']:self.assertIn(required,source)

    def test_one_authority_and_mandatory_shared_store(self):
        a,b=self.client(),self.client(configured_dlmm_rpc)
        self.assertEqual(a.provider_fingerprint,b.provider_fingerprint)
        self.assertEqual(a.shared_admission.path,b.shared_admission.path)
        self.assertIs(a.evidence_reuse.store,b.evidence_reuse.store)
        self.assertEqual(a.shared_admission.interval,.5)
        self.assertLessEqual(b.pacer.requests_per_second,2)
    def test_configuration_rejects_alternate_authority_and_missing(self):
        for value in ('https://elsewhere.invalid/key', URL+'/extra',URL+'?key=x',URL.replace('alchemy.com','alchemy.com.evil'), 'http://robinhood-mainnet.g.alchemy.com/v2/key'):
            with self.subTest(value=value),patch.dict(os.environ,{'MM_ROBINHOOD_READ_RPC_URL':value}):
                with self.assertRaises(BoundaryError):configured_rpc()
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(BoundaryError):configured_rpc()
        with patch.dict(os.environ,{'MM_ROBINHOOD_DLMM_RPC_URL':URL+'other'}):
            with self.assertRaisesRegex(BoundaryError,'authority_mismatch'):configured_dlmm_rpc()
    def test_equivalent_legacy_alias_and_opaque_reference(self):
        alias=URL.replace('.com/', '.com:443/')+'/'
        with patch.dict(os.environ,{'MM_ROBINHOOD_DLMM_RPC_URL':alias}):
            self.assertEqual(authority.endpoint(),URL)
            ref=authority.reference();self.assertNotIn('SECRET',ref)
            self.assertEqual(self.client().provider_fingerprint,authority.fingerprint(ref))
            self.assertEqual(authority.endpoint(ref),URL)
    def test_public_and_shadow_never_have_canonical_cache_or_authority(self):
        with patch.dict(os.environ,{'MM_ROBINHOOD_DISCOVERY_RPC_URL':URL,'MM_ROBINHOOD_SHADOW_RPC_URL':'https://shadow.invalid/key'}):
            for rpc in (configured_discovery_rpc(),configured_shadow_rpc()):
                self.assertFalse(rpc.canonical_authority)
                self.assertIsNone(rpc.evidence_reuse)
                with self.assertRaisesRegex(ValueError,'role_not_canonical'):authority.require_canonical(rpc)
    def test_chain_required_before_shared_evidence_and_no_rescue(self):
        calls=[]
        rpc=self.client(transport=lambda m,p:calls.append(m) or '0x1')
        with self.assertRaisesRegex(BoundaryError,'wrong_chain'):rpc.call('eth_getCode',['a','latest'])
        self.assertEqual(calls,['eth_chainId']);self.assertFalse(rpc.chain_verified)
        self.assertEqual(rpc.evidence_reuse.store.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],0)
    def test_session_and_configuration_identity_continuity(self):
        a=self.client(transport=lambda m,p:'0x1237');a.verify_chain()
        with patch.dict(os.environ,{'MM_ROBINHOOD_READ_RPC_URL':URL+'changed'}):
            with self.assertRaisesRegex(BoundaryError,'identity_changed'):a.call('eth_blockNumber',[])
        b=self.client(transport=lambda m,p:'0x1')
        with self.assertRaises(BoundaryError):b.call('eth_blockNumber',[])
    def test_batch_is_one_physical_n_logical_and_shared_reuse_zero(self):
        a,b=self.client(),self.client(configured_dlmm_rpc)
        with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=self.http):
            a.verify_chain();b.verify_chain()
            a.batch([('eth_getCode',[str(i),'latest']) for i in range(4)])
            a.call('eth_getBlockByHash',['h1',False])
            before=len(self.requests)
            b.call('eth_getBlockByHash',['h1',False])
            self.assertEqual(len(self.requests),before)
        t=b.telemetry()['shared_provider']
        self.assertEqual(t['physical_http_requests'],4)
        self.assertEqual(t['logical_rpc_calls'],7)
        self.assertEqual(t['batch_transports'],1);self.assertEqual(t['batch_members'],4)
        self.assertEqual(t['consumer_logical_calls'],8)
        self.assertTrue(t['estimated_cu']['billing_estimate_only'])
    def test_aggregate_governor_concurrent_lane_clients(self):
        a,b=self.client(),self.client(configured_dlmm_rpc)
        with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=self.http),ThreadPoolExecutor(2) as pool:
            futures=[pool.submit(r.call,'eth_chainId',[]) for r in (a,b)]
            for f in futures:self.assertEqual(f.result(),'0x1237')
        db=sqlite3.connect(a.shared_admission.path)
        rows=[json.loads(r[0]) for r in db.execute('SELECT body FROM transports')];db.close()
        times=sorted(r['admitted_at'] for r in rows)
        self.assertGreaterEqual(times[1]-times[0],.5)
        with self.assertRaises(BoundaryError):Admission(Path(self.tmp.name)/'other',URL,lane='pons',interval=.1)
    def test_secrets_absent_from_sqlite_telemetry_and_exception_output(self):
        rpc=self.client(transport=lambda m,p:(_ for _ in ()).throw(RuntimeError(URL)))
        with self.assertRaisesRegex(BoundaryError,'provider_boundary_failure') as caught:rpc.verify_chain()
        self.assertNotIn('SYNTHETIC_SECRET',str(caught.exception))
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(rpc.telemetry()))
        for path in Path(self.tmp.name).glob('*'):
            if path.is_file():self.assertNotIn(b'SYNTHETIC_SECRET',path.read_bytes())
    def test_response_cannot_export_credentials(self):
        rpc=self.client(transport=lambda m,p:'0x1237' if m=='eth_chainId' else URL)
        with self.assertRaisesRegex(BoundaryError,'response_contains_credential'):rpc.call('eth_getCode',['a','latest'])
    def test_process_death_preserves_unresolved_physical_attempt(self):
        import subprocess,sys,meme_machine
        script="""import os,sys
from unittest.mock import patch
from meme_machine.lanes.pons.provider_topology import configured_rpc
def guard(event,args):
    if event in ('socket.connect','socket.getaddrinfo'):raise RuntimeError('offline_only')
sys.addaudithook(guard)
with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=lambda *a,**k:os._exit(73)):
    configured_rpc(retries=0).verify_chain()
"""
        env=dict(os.environ,PYTHONPATH=str(Path(meme_machine.runtime.__file__).parent.parent)+os.pathsep+str(Path(__file__).resolve().parents[1]))
        child=subprocess.run([sys.executable,'-c',script],env=env,capture_output=True,timeout=10)
        self.assertEqual(child.returncode,73,child.stderr)
        t=self.client().telemetry()['shared_provider']
        self.assertEqual(t['physical_http_requests'],1)
        self.assertEqual(t['unresolved_transport_attempts'],1)

    def test_retry_counts_distinct_wire_attempts(self):
        rpc=configured_rpc(retries=1,limit=10,per_scope=10)
        rpc.pacer=ProviderPacer(2,clock=self.clock.time,sleeper=self.clock.sleep)
        rpc.shared_admission.clock=self.clock.time;rpc.shared_admission.sleep=self.clock.sleep
        attempts=[]
        def http(request,**kwargs):
            attempts.append(1)
            if len(attempts)==1:raise HTTPError(URL,500,'secret',{},None)
            return self.http(request,**kwargs)
        with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=http),patch('meme_machine.lanes.pons.provider.time.sleep'):
            rpc.verify_chain()
        t=rpc.telemetry()['shared_provider']
        self.assertEqual(t['physical_http_requests'],2)
        self.assertEqual(t['logical_rpc_calls'],2)
        self.assertEqual(t['consumer_logical_calls'],1)
        self.assertEqual(t['retries'],1)
        self.assertEqual(t['unresolved_transport_attempts'],0)

    def test_429_recorded_once_no_retry_or_alternate_provider(self):
        rpc=self.client()
        with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=HTTPError(URL,429,'secret',{},None)):
            with self.assertRaisesRegex(BoundaryError,'provider_http_429'):rpc.verify_chain()
        t=rpc.telemetry()['shared_provider']
        self.assertEqual(t['physical_http_requests'],1);self.assertEqual(t['responses_429'],1)
        self.assertEqual(t['retries'],0);self.assertGreater(t['health']['cooldown_until_monotonic'],100)
    def test_acquisition_refuses_public_client_even_after_chain_verification(self):
        from meme_machine.lanes.pons import pons_selective_acquisition as acquisition
        rpc=configured_discovery_rpc(transport=lambda *_:'0x1237')
        with patch.object(acquisition,'configured_rpc',return_value=rpc):
            with self.assertRaisesRegex(BoundaryError,'role_not_canonical'):acquisition._rpc(URL)

    def test_broker_coalesces_and_fences_provider_completion(self):
        from meme_machine.runtime.robinhood.pons import Broker
        broker=Broker(Path(self.tmp.name)/'candidates.sqlite','frozen',clock=lambda:100,source=authority.reference())
        self.addCleanup(broker.close)
        def event(n):return dict(address='0xcurve',transactionHash='tx'+str(n),logIndex=hex(n),
            transactionIndex='0x0',blockNumber=hex(n),blockHash='h'+str(n))
        for n in range(1,11):broker.enqueue(event(n))
        self.assertEqual(len(broker.rows),1)
        old=broker.pop();self.assertEqual(old['work']['generation'],10)
        self.assertIsNone(broker.pop())
        broker.enqueue(event(11))
        self.assertFalse(broker.finish(old,{'qualified':True},.1))
        new=broker.pop();self.assertEqual(new['work']['generation'],11)
        self.assertTrue(broker.finish(new,{'qualified':False},.1))
        self.assertFalse(broker.enqueue(event(11)))
        metrics=broker.telemetry()
        self.assertEqual(metrics['unique_candidates'],1)
        self.assertEqual(metrics['provider_jobs_claimed'],2)
        self.assertEqual(metrics['obsolete_completions_fenced'],1)
        self.assertEqual(metrics['observations_received_since_instrumentation'],12)

    def test_candidate_provenance_reports_archives_and_crash_output_are_secret_free(self):
        import traceback
        import zipfile
        from meme_machine.runtime.robinhood.plane import Plane
        rpc=self.client()
        with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=self.http):rpc.verify_chain()
        plane=Plane(Path(self.tmp.name)/'candidate.sqlite',clock=lambda:100)
        plane.observe('curve','pons','event',{},ordering=(1,),watermark={'hash':'h1'},
            interpretation={'provider':rpc.provider_fingerprint},observed=100,deadline=105,priority=2)
        plane.put('canonical','h1',{},dict(provider=rpc.provider_fingerprint,chain=4663))
        report={'provider':rpc.telemetry(),'candidate':plane.snapshot()};plane.close()
        try:
            failing=self.client(transport=lambda *_:(_ for _ in ()).throw(RuntimeError(URL)))
            failing.verify_chain()
        except BoundaryError:
            report['crash_diagnostic']=traceback.format_exc()
        report_path=Path(self.tmp.name)/'report.json';report_path.write_text(json.dumps(report))
        archive=Path(self.tmp.name)/'report.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for path in Path(self.tmp.name).glob('*'):
                if path.is_file() and path!=archive:z.write(path,path.name)
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():self.assertNotIn(b'SYNTHETIC_SECRET',z.read(name))

    def test_non_alchemy_diagnostic_rejects_alchemy_method(self):
        rpc=PacedRpc('https://shadow.invalid/key',role='shadow_diagnostic_only',requests_per_second=2,transport=lambda *_:[])
        with self.assertRaisesRegex(BoundaryError,'wrong_provider'):rpc.call('alchemy_getAssetTransfers',[{}])
    def test_topology_has_no_secret_or_automatic_failover(self):
        result=topology_metadata()
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(result))
        self.assertFalse(result['directional']['automatic_failover'])
        self.assertFalse(result['dlmm']['automatic_failover'])
        self.assertEqual(result['dlmm']['provider_kind'],'alchemy')

if __name__=='__main__':unittest.main()
