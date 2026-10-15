from email.message import Message
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.provider import Rpc
from meme_machine.lanes.pons.provider_topology import ObservationFallbackRpc, ProviderPacer
from meme_machine.lanes.pons.provider_topology import PacedRpc
from meme_machine.lanes.pons.provider_admission import Admission


class Clock:
    def __init__(self):
        self.now=0.0
    def time(self):
        return self.now
    def sleep(self,seconds):
        self.now+=float(seconds)


class Recovery:
    def __init__(self):
        self.calls=[]
    def call(self,method,params,scope="connectivity"):
        self.calls.append((method,params,scope))
        return [{"recovered":True}]
    def telemetry(self):
        return {"calls":len(self.calls)}


class PublicLog429AdaptiveTests(unittest.TestCase):
    def rpc(self,transport,recovery=None,limit=100):
        clock=Clock()
        pacer=ProviderPacer(2.0,clock=clock.time,sleeper=clock.sleep)
        rpc=ObservationFallbackRpc(
            "https://rpc.mainnet.chain.robinhood.com",
            role="pons_discovery_public_observation",
            requests_per_second=2.0,
            pacer=pacer,
            recovery_rpc=recovery,
            transport=transport,
            retries=0,limit=limit,per_scope=limit,
        )
        return rpc,clock

    def test_public_log_429_retries_identical_range_once_before_recovery(self):
        calls=[]
        def transport(method,params):
            calls.append((method,params))
            if len(calls)==1:
                raise BoundaryError("provider_http_429")
            return [{"ok":True}]
        recovery=Recovery();rpc,clock=self.rpc(transport,recovery)
        params=[{"fromBlock":"0x10","toBlock":"0x19","topics":[["0xaa"]]}]
        result=rpc.call("eth_getLogs",params,scope="pons_natural")
        self.assertEqual(result,[{"ok":True}])
        self.assertEqual(calls,[("eth_getLogs",params),("eth_getLogs",params)])
        self.assertEqual(recovery.calls,[])
        ctl=rpc.telemetry()["public_eth_getLogs_429_control"]
        self.assertEqual(ctl["public_429s"],1)
        self.assertEqual(ctl["same_endpoint_retry_successes"],1)
        self.assertEqual(ctl["alchemy_exact_range_recoveries"],0)
        self.assertAlmostEqual(ctl["cooldown_seconds"],0.6)
        self.assertEqual(ctl["effective_requests_per_second"],1.5)

    def test_second_429_uses_exact_alchemy_recovery_once(self):
        calls=[]
        def transport(method,params):
            calls.append((method,params))
            raise BoundaryError("provider_http_429")
        recovery=Recovery();rpc,_=self.rpc(transport,recovery)
        params=[{"fromBlock":"0x20","toBlock":"0x29","topics":[["0xbb"]]}]
        result=rpc.call("eth_getLogs",params,scope="pons_natural")
        self.assertEqual(result,[{"recovered":True}])
        self.assertEqual(calls,[("eth_getLogs",params),("eth_getLogs",params)])
        self.assertEqual(recovery.calls,[("eth_getLogs",params,"pons_natural")])
        ctl=rpc.telemetry()["public_eth_getLogs_429_control"]
        self.assertEqual(ctl["same_endpoint_retry_failures"],1)
        self.assertEqual(ctl["alchemy_exact_range_recoveries"],1)
        self.assertEqual(ctl["unrecovered_ranges"],0)

    def test_non_log_429_keeps_existing_direct_recovery_without_retry(self):
        calls=[]
        def transport(method,params):
            calls.append((method,params))
            raise BoundaryError("provider_http_429")
        recovery=Recovery();rpc,_=self.rpc(transport,recovery)
        rpc.call("eth_getBlockByNumber",["0x20",False],scope="pons_natural")
        self.assertEqual(len(calls),1)
        self.assertEqual(len(recovery.calls),1)
        self.assertEqual(rpc.telemetry()["public_eth_getLogs_429_control"]["public_429s"],0)

    def test_twenty_public_log_successes_cautiously_recover_rate(self):
        attempts=[0]
        def transport(method,params):
            attempts[0]+=1
            if attempts[0]==1:
                raise BoundaryError("provider_http_429")
            return []
        rpc,_=self.rpc(transport)
        params=[{"fromBlock":"0x1","toBlock":"0x1","topics":[]}]
        rpc.call("eth_getLogs",params)
        self.assertEqual(rpc.pacer.requests_per_second,1.5)
        for _ in range(19):
            rpc.call("eth_getLogs",params)
        self.assertAlmostEqual(rpc.pacer.requests_per_second,1.6)
        self.assertLessEqual(rpc.pacer.requests_per_second,2.0)

    def test_retry_after_header_is_captured_only_when_short(self):
        for header,expected in (("0.25",0.25),("5",None),("invalid",None)):
            headers=Message();headers["Retry-After"]=header
            error=HTTPError("https://redacted.invalid",429,"rate",headers,None)
            rpc=Rpc("https://example.invalid",limit=40,retries=0)
            with self.subTest(header=header),patch(
                    "meme_machine.lanes.pons.provider.urlopen",side_effect=error):
                with self.assertRaisesRegex(BoundaryError,"provider_http_429"):
                    rpc._http("eth_getLogs",[{}])
                self.assertEqual(rpc.last_retry_after_seconds,expected)


class PublicBatch429ActualPathTests(unittest.TestCase):
    """Real wrapper/admission/HTTP path; fake clock and disposable FULL ledgers.

    The retained observation's four filtered log elements are represented by
    contiguous, unchanged ten-block ranges. No provider quota is simulated.
    """
    public = "https://rpc.mainnet.chain.robinhood.com"
    canonical = "https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_BATCH_FIXTURE"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {
            'MM_ROBINHOOD_READ_RPC_URL': self.canonical,
            'MM_ROBINHOOD_STATE_DIR': self.tmp.name,
        }, clear=True)
        env.start(); self.addCleanup(env.stop)
        self.clock = Clock(); self.clock.now = 100
        clock = patch('time.monotonic', side_effect=self.clock.time)
        clock.start(); self.addCleanup(clock.stop)
        self.starts = []
        self.reject_public = True
        self.calls = [('eth_getLogs', [dict(address='0xcurve', topics=[['0xaa','0xbb']],
            fromBlock=hex(first), toBlock=hex(first+9))]) for first in (101,111,121,131)]
        self.gates = {}
        for endpoint in (self.public, self.canonical):
            with patch('meme_machine.operational.position_continuation.provider_interval', return_value=.1):
                self.gates[endpoint] = Admission(Path(self.tmp.name)/'provider.sqlite', endpoint,
                    lane='pons', clock=self.clock.time, sleeper=self.clock.sleep)
        configured = patch('meme_machine.lanes.pons.provider_admission.configured',
                           side_effect=lambda endpoint, **kw: self.gates[endpoint])
        configured.start(); self.addCleanup(configured.stop)
        self.recovery = PacedRpc(self.canonical, role='pons_discovery_gap_recovery_primary',
            requests_per_second=2, retries=0, limit=100, per_scope=100)
        # The preceding startup chain verification is fixture state here;
        # wrong-chain/endpoint guards are exercised by the routing regressions.
        self.recovery.chain_verified = True
        self.rpc = ObservationFallbackRpc(self.public, role='pons_discovery_public_observation',
            requests_per_second=2, pacer=ProviderPacer(2, clock=self.clock.time,
                sleeper=self.clock.sleep), recovery_rpc=self.recovery,
            retries=0, limit=100, per_scope=100)
        http = patch('meme_machine.lanes.pons.provider.urlopen', side_effect=self.http)
        http.start(); self.addCleanup(http.stop)

    def http(self, request, **kwargs):
        payload = json.loads(request.data)
        public = request.full_url == self.public
        self.starts.append((self.clock.time(), 'public' if public else 'canonical', payload))
        self.clock.sleep(.125)
        if public and self.reject_public:
            self.reject_public = False
            raise HTTPError(self.public, 429, 'offline_rejection', {}, io.BytesIO(b'{}'))
        def response(row):
            return dict(jsonrpc='2.0', id=row['id'], result=[dict(
                blockNumber=row['params'][0].get('fromBlock','0x1'), logIndex='0x0',
                transactionHash='fixture-tx')])
        result = [response(row) for row in payload] if isinstance(payload,list) else response(payload)
        return io.BytesIO(json.dumps(result).encode())

    def rows(self, table):
        with sqlite3.connect(self.gates[self.public].path) as db:
            return [json.loads(row[0]) for row in db.execute('SELECT body FROM '+table+' ORDER BY seq')]

    def test_batch_feedback_precedes_exact_fallback_without_an_added_attempt(self):
        result = self.rpc.batch(self.calls, scope='pons_natural')
        self.assertEqual([row[0]['blockNumber'] for row in result], ['0x65','0x6f','0x79','0x83'])
        self.assertAlmostEqual(self.rpc.pacer.current_requests_per_second(), 1.5)
        self.assertEqual([kind for _,kind,_ in self.starts], ['public','canonical'])
        self.assertEqual([row['params'] for row in self.starts[0][2]],
                         [row['params'] for row in self.starts[1][2]])
        rows = self.rows('transports')
        self.assertEqual([row['physical_requests'] for row in rows], [1,1])
        self.assertEqual([len(row['methods']) for row in rows], [4,4])
        self.assertEqual([row['http_status'] for row in rows], [429,200])
        self.assertEqual([row['retry_count'] for row in rows], [0,0])
        control = self.rpc.telemetry()['public_eth_getLogs_429_control']
        self.assertEqual(control['public_429s'], 1)
        self.assertEqual(control['alchemy_exact_range_recoveries'], 1)
        self.assertEqual(control['same_endpoint_retry_successes'], 0)
        self.assertEqual(control['same_endpoint_retry_failures'], 0)

    def test_eight_second_cooldown_keeps_five_second_guard_exposure_honest(self):
        self.rpc.batch(self.calls, scope='pons_natural')
        after_fallback = self.clock.time()
        self.rpc.batch(self.calls, scope='pons_natural')
        admission = self.rows('admissions')[-1]
        self.assertGreaterEqual(admission['wait_seconds'], 7.875-1e-8)
        self.assertGreater(admission['wait_seconds'], 5)
        self.assertEqual(admission['deadline'], after_fallback+30)
        self.assertGreaterEqual(self.starts[-1][0]-self.starts[0][0], 8)
        self.assertAlmostEqual(self.rpc.pacer.current_requests_per_second(), 1.5)

    def test_absolute_deadline_during_cooldown_refuses_transport_without_renewal(self):
        self.rpc.batch(self.calls, scope='pons_natural')
        starts = len(self.starts)
        absolute = self.clock.time()+3
        self.rpc.evidence_deadline = absolute
        self.recovery.evidence_deadline = absolute
        with self.assertRaisesRegex(BoundaryError, 'provider_shared_admission_deadline'):
            self.rpc.batch(self.calls, scope='pons_natural')
        self.assertEqual(len(self.starts), starts)
        self.assertEqual(self.rows('admissions')[-1]['deadline'], absolute)
        self.assertFalse(self.rows('admissions')[-1]['granted'])

    def test_fallback_preserves_wrapper_deadline_when_recovery_client_has_no_deadline(self):
        self.rpc.evidence_deadline = self.clock.time()+3
        with sqlite3.connect(self.gates[self.canonical].path) as db:
            db.execute('UPDATE limits SET next_at=? WHERE endpoint=?',
                       (104,self.gates[self.canonical].endpoint))
        with self.assertRaisesRegex(BoundaryError, 'provider_shared_admission_deadline'):
            self.rpc.batch(self.calls,scope='pons_natural')
        self.assertEqual([kind for _,kind,_ in self.starts],['public'])
        self.assertEqual(self.rows('admissions')[-1]['deadline'],103)
        self.assertFalse(hasattr(self.recovery,'evidence_deadline'))

    def test_non_log_batch_429_does_not_change_log_feedback(self):
        calls = [('eth_getBlockByNumber',['0x1',False])]*4
        # Reply details do not establish headers here; use a noncanonical
        # recovery stub so this case isolates unchanged non-log feedback.
        class Recovery:
            def batch(self,calls,scope):return [None]*len(calls)
        self.rpc.recovery_rpc = Recovery()
        self.assertEqual(self.rpc.batch(calls,scope='pons_natural'),[None]*4)
        self.assertEqual(self.rpc.public_log_429s,0)
        self.assertEqual(self.rpc.pacer.current_requests_per_second(),2)

    def test_fallback_does_not_extend_existing_stricter_canonical_deadline(self):
        self.rpc.evidence_deadline = 105
        self.recovery.evidence_deadline = 102
        with sqlite3.connect(self.gates[self.canonical].path) as db:
            db.execute('UPDATE limits SET next_at=? WHERE endpoint=?',
                       (103,self.gates[self.canonical].endpoint))
        with self.assertRaisesRegex(BoundaryError,'provider_shared_admission_deadline'):
            self.rpc.batch(self.calls,scope='pons_natural')
        self.assertEqual(self.rows('admissions')[-1]['deadline'],102)
        self.assertEqual(self.recovery.evidence_deadline,102)

    def test_single_recoverable_failure_also_preserves_original_fallback_deadline(self):
        self.rpc.evidence_deadline = 103
        with sqlite3.connect(self.gates[self.canonical].path) as db:
            db.execute('UPDATE limits SET next_at=? WHERE endpoint=?',
                       (104,self.gates[self.canonical].endpoint))
        def unavailable(request,**kwargs):
            self.starts.append((self.clock.time(),'public',json.loads(request.data)))
            raise HTTPError(self.public,503,'offline_unavailable',{},io.BytesIO(b'{}'))
        with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=unavailable):
            with self.assertRaisesRegex(BoundaryError,'provider_shared_admission_deadline'):
                self.rpc.call('eth_getLogs',[self.calls[0][1][0]],scope='pons_natural')
        self.assertEqual([kind for _,kind,_ in self.starts],['public'])
        self.assertEqual(self.rows('admissions')[-1]['deadline'],103)
        self.assertFalse(hasattr(self.recovery,'evidence_deadline'))

    def test_fallback_deadline_is_thread_local_and_cannot_expire_peer_protection(self):
        self.rpc.evidence_deadline = 103
        gate = self.gates[self.canonical]
        original = gate.acquire
        fallback_entered = threading.Event(); release = threading.Event()
        def acquire(scope, *args, **kwargs):
            if scope == 'pons_natural':
                self.assertEqual(self.recovery.evidence_deadline,103)
                fallback_entered.set()
                if not release.wait(5):raise RuntimeError('offline_test_coordination_timeout')
            return original(scope,*args,**kwargs)
        with patch.object(gate,'acquire',side_effect=acquire),ThreadPoolExecutor(1) as pool:
            pending = pool.submit(self.rpc.batch,self.calls,scope='pons_natural')
            try:
                self.assertTrue(fallback_entered.wait(5))
                self.assertFalse(hasattr(self.recovery,'evidence_deadline'))
                # The peer remains valid after the other request's deadline;
                # its own three-second protective window is not renewed.
                self.clock.sleep(3.1)
                self.recovery.evidence_deadline = self.clock.time()+3
                protected_deadline = self.recovery.evidence_deadline
                self.recovery.batch(self.calls,scope='paper_exit')
                self.assertEqual(self.rows('admissions')[-1]['deadline'],protected_deadline)
                self.assertEqual(self.rows('admissions')[-1]['priority'],0)
                self.assertLess(self.clock.time(),protected_deadline)
            finally:
                if hasattr(self.recovery,'evidence_deadline'):del self.recovery.evidence_deadline
                release.set()
            with self.assertRaisesRegex(BoundaryError,'provider_shared_admission_deadline'):
                pending.result(timeout=5)
        self.assertFalse(hasattr(self.recovery,'evidence_deadline'))
        self.assertEqual([kind for _,kind,_ in self.starts],['public','canonical'])

    def test_canonical_protection_remains_independent_of_public_cooldown(self):
        self.rpc.batch(self.calls, scope='pons_natural')
        before = self.clock.time()
        self.recovery.evidence_deadline = before+3
        self.recovery.batch(self.calls, scope='paper_exit')
        self.assertLess(self.clock.time()-before, 3)
        self.assertEqual(self.starts[-1][1], 'canonical')
        self.assertEqual(self.rows('admissions')[-1]['priority'], 0)

    def test_public_batch_success_counts_one_transport_not_four_recovery_steps(self):
        self.rpc.batch(self.calls, scope='pons_natural')
        for _ in range(19):
            self.rpc.batch(self.calls, scope='pons_natural')
        self.assertAlmostEqual(self.rpc.pacer.current_requests_per_second(), 1.5)
        self.rpc.batch(self.calls, scope='pons_natural')
        self.assertAlmostEqual(self.rpc.pacer.current_requests_per_second(), 1.6)


if __name__=="__main__":
    unittest.main()
