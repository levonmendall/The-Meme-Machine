"""Real native Governor/Admission/Budget, offline HTTP and fixed head facts."""
import io
import http.client
import json
import os
from pathlib import Path
import subprocess
import socket
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import grpc
from meme_machine.runtime import stop
from meme_machine.runtime.market_heads import HeadSource,MarketHeads,HeadRefresh,MAXIMUM_BYTES
from meme_machine.runtime.evidence_worker import RepairRPC,DeliveredRPCError
from meme_machine.runtime.governor import Governor
from meme_machine.operational import bounded_provider as bounded
from meme_machine.lanes.pons import provider
from meme_machine.lanes.pons.provider_topology import PacedRpc
from meme_machine.lanes.pons.provider_admission import Admission,OfflineProfile
from meme_machine.solana_provider_config import GENESIS
from tests.test_bounded_provider_preflight import observation_file
from tests.test_provider_clock_domain import identity

SOL='https://solana-mainnet.g.alchemy.com/v2/offline-head-secret'
PONS='https://robinhood-mainnet.g.alchemy.com/v2/offline-head-secret'


class Clock:
    def __init__(self):self.now=1000.
    def __call__(self):return self.now
    def sleep(self,seconds):self.now+=float(seconds)


class OfflineSocket:
    """Native HTTPResponse/SocketIO; no network or synthetic read(n) bound."""
    def __init__(self,body,*,hook=None,chunk=None,mode='length'):
        declared_length=len(body)+(10 if mode=='truncated' else 0)
        headers=(b'Content-Length: '+str(declared_length).encode()+b'\r\n' if mode in ('length','truncated')
            else b'Transfer-Encoding: chunked\r\n' if mode=='chunked' else b'')
        self.headers=io.BytesIO(b'HTTP/1.1 200 OK\r\n'+headers+b'Connection: close\r\n\r\n')
        self.body=io.BytesIO(body);self.hook=hook;self.chunk=chunk;self.timeout=8;self.timeouts=[]
    def makefile(self,*args):return io.BufferedReader(socket.SocketIO(self,'rb'))
    def recv_into(self,buffer,*args):
        value=self.headers.read(len(buffer))
        if not value:
            if self.hook:self.hook()
            value=self.body.read(min(len(buffer),self.chunk or len(buffer)))
        buffer[:len(value)]=value
        return len(value)
    def gettimeout(self):return self.timeout
    def settimeout(self,value):self.timeout=value;self.timeouts.append(value)
    def _decref_socketios(self):pass


class HeadMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.clock=Clock();self.requests=[]
        self.enterContext(patch('time.monotonic',self.clock))
        self.enterContext(patch('time.sleep',self.clock.sleep))
        self.enterContext(patch('meme_machine.runtime.provider_clock.current_identity',return_value=identity()))
        self.enterContext(patch.object(stop,'requested',threading.Event()))
        self.enterContext(patch.dict(os.environ,{
            'MM_BOUNDED_PROVIDER_DB':str(self.root/'usage.sqlite'),
            'MM_PROVIDER_OPERATION_MODE':'VALIDATION',
            'MM_SOLANA_EVIDENCE_PLANE_DB':str(self.root/'source.sqlite'),
            'MM_ROBINHOOD_READ_RPC_URL':PONS,'MM_ROBINHOOD_STATE_DIR':str(self.root/'pons')},clear=True))
        self.budget=bounded.Budget.create(self.root/'usage.sqlite')
        envelope=observation_file(self.root,self.budget)
        os.environ['MM_BOUNDED_PROVIDER_ENVELOPE']=str(envelope)
        self.enterContext(patch('urllib.request.urlopen',__import__('urllib.request',fromlist=['urlopen']).urlopen))
        self.enterContext(patch.object(provider,'urlopen',provider.urlopen))
        self.enterContext(patch.object(grpc.aio,'secure_channel',grpc.aio.secure_channel))
        from meme_machine import solana_selective_source
        self.enterContext(patch.object(solana_selective_source,'connect',solana_selective_source.connect))
        self.enterContext(patch('urllib.request.build_opener',return_value=SimpleNamespace(open=self.physical)))
        bounded.install()
        self.generation='c'*32
        self.source=HeadSource('a'*40,'b'*40,os.getpid(),123,self.generation)
        self.heads=MarketHeads(self.source,generation=lambda:self.generation,clock=self.clock,wall=lambda:2000.)
        self.governor=Governor(self.root/'governor.sqlite')
        self.sol=self.heads.attach(RepairRPC(SOL,self.governor),'solana')
        self.header=dict(number='0x64',hash='0x'+'d'*64,timestamp='0x3e8')
        self.slot=100;self.fail=None;self.before_physical=None
        self.body_hook=None;self.body_chunk=None;self.response_mode='length';self.sockets=[]
        self.admission=Admission(self.root/'pons-admission.sqlite',PONS,lane='pons',
            clock=self.clock,sleeper=self.clock.sleep,offline_profile=OfflineProfile(2))
        self.pons=self.heads.attach(PacedRpc(PONS,role='directional_evidence_primary',
            requests_per_second=2,offline_admission=self.admission,retries=0),'pons')

    def physical(self,request,**kwargs):
        self.requests.append((json.loads(request.data),kwargs['timeout']))
        if self.before_physical:self.before_physical()
        if self.fail:
            raise HTTPError(request.full_url,self.fail,'private-http-canary',{},None)
        def reply(row):
            method=row['method']
            value=(GENESIS if method=='getGenesisHash' else self.slot if method=='getSlot'
                else '0x1237' if method=='eth_chainId' else dict(self.header))
            return dict(jsonrpc='2.0',id=row['id'],result=value)
        body=json.loads(request.data)
        body=[reply(row) for row in body] if isinstance(body,list) else reply(body)
        body=json.dumps(body).encode()
        if self.response_mode=='unknown_wrapper':return io.BytesIO(body)
        sock=OfflineSocket(body,hook=self.body_hook,chunk=self.body_chunk,mode=self.response_mode)
        self.sockets.append(sock)
        response=http.client.HTTPResponse(sock);response.begin()
        return response

    def verify_solana(self):
        self.sol.validate_network()
        self.assertTrue(self.sol.network_verified)

    def test_actual_physical_solana_head_is_captured_before_any_owner_publication(self):
        self.verify_solana()
        value,_=self.sol.call_delivered('getSlot',[dict(commitment='finalized')],2)
        self.assertEqual(value,100)
        row=self.heads.snapshot('solana_finalized')
        self.assertEqual(row['state'],'OBSERVED')
        self.assertEqual(row['receipt']['height'],100)
        self.assertEqual(row['receipt']['network'],GENESIS)
        self.assertEqual(row['receipt']['source_pid'],os.getpid())
        self.assertEqual(row['receipt']['source_process_start_ticks'],123)
        self.assertEqual(row['receipt']['commitment'],'finalized')
        completed=row['receipt']['physical_completed_monotonic']
        self.clock.sleep(4)
        later=self.heads.snapshot('solana_finalized')
        self.assertEqual(later['age_seconds'],4)
        self.assertEqual(later['receipt']['physical_completed_monotonic'],completed)
        self.assertFalse(row['canonical_coverage']);self.assertIsNone(row['economic_arrival_count'])
        self.assertNotIn('secret',json.dumps(row));self.assertNotIn('https://',json.dumps(row))
        self.assertEqual(self.budget.snapshot()['http_attempts'],'2')
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')

    def test_solana_nonfinalized_boolean_height_and_unverified_network_are_unavailable(self):
        self.sol.call_delivered('getSlot',[dict(commitment='finalized')],2)
        self.assertEqual(self.heads.snapshot('solana_finalized')['state'],'UNAVAILABLE')
        self.verify_solana()
        self.sol.call_delivered('getSlot',[dict(commitment='confirmed')],2)
        self.assertIsNone(self.heads.snapshot('solana_finalized')['receipt'])
        self.slot=True
        self.sol.call_delivered('getSlot',[dict(commitment='finalized')],2)
        row=self.heads.snapshot('solana_finalized')
        self.assertEqual(row['state'],'UNAVAILABLE');self.assertIsNone(row['receipt'])

    def test_fresh_existing_read_suppresses_refresh_and_stale_only_reuses_original_budget(self):
        self.verify_solana()
        self.sol.call_delivered('getSlot',[dict(commitment='finalized')],2)
        refresh=HeadRefresh(self.heads,'solana',rpc=self.sol,stopped=lambda:False,
            deadline=self.clock()+100,clock=self.clock)
        before=len(self.requests)
        self.assertFalse(refresh.step());self.assertEqual(len(self.requests),before)
        self.clock.sleep(5.1);self.slot=105
        self.assertTrue(refresh.step())
        self.assertEqual(len(self.requests),before+1)
        self.assertEqual(self.heads.snapshot('solana_finalized')['receipt']['height'],105)
        self.assertEqual(self.budget.snapshot()['http_attempts'],str(len(self.requests)))
        self.assertFalse(refresh.step())
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')

    def test_429_retains_original_debt_and_no_controller_retry_or_catchup_burst(self):
        self.verify_solana();self.fail=429
        refresh=HeadRefresh(self.heads,'solana',rpc=self.sol,stopped=lambda:False,
            deadline=self.clock()+100,clock=self.clock)
        before=len(self.requests)
        self.assertFalse(refresh.step())
        self.assertEqual(len(self.requests),before+1)
        self.assertFalse(refresh.step());self.assertEqual(len(self.requests),before+1)
        row=self.heads.snapshot('solana_finalized')
        self.assertEqual(row['state'],'UNAVAILABLE');self.assertEqual(row['failed_refreshes'],1)
        import sqlite3
        with sqlite3.connect(self.governor.path) as db:
            cooldown=db.execute("SELECT cooldown FROM pressure WHERE provider='solana'").fetchone()[0]
        self.assertGreater(cooldown,self.clock())
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')

    def test_freshness_boundary_skip_does_not_postpone_the_next_stale_attempt(self):
        self.verify_solana();self.sol.call_delivered('getSlot',[dict(commitment='finalized')],2)
        refresh=HeadRefresh(self.heads,'solana',rpc=self.sol,stopped=lambda:False,
            deadline=self.clock()+100,clock=self.clock)
        before=len(self.requests)
        self.assertFalse(refresh.step())
        self.clock.sleep(5)
        self.assertFalse(refresh.step());self.assertEqual(len(self.requests),before)
        self.clock.sleep(.1)
        self.assertTrue(refresh.step());self.assertEqual(len(self.requests),before+1)

    def test_newer_native_read_during_refresh_gap_does_not_renew_old_age(self):
        self.verify_solana();self.sol.call_delivered('getSlot',[dict(commitment='finalized')],2)
        first=self.heads.snapshot('solana_finalized')['receipt']
        self.clock.sleep(6)
        self.assertEqual(self.heads.snapshot('solana_finalized')['state'],'UNAVAILABLE')
        self.slot=101;self.sol.call_delivered('getSlot',[dict(commitment='finalized')],2)
        last=self.heads.snapshot('solana_finalized')
        self.assertEqual(last['state'],'OBSERVED')
        self.assertEqual(last['first_receipt'],first)
        self.assertGreater(last['receipt']['physical_completed_monotonic'],first['physical_completed_monotonic'])

    def test_deadline_and_cancel_before_dispatch_do_not_open_transport(self):
        self.verify_solana();self.clock.sleep(1)
        stopped=threading.Event()
        refresh=HeadRefresh(self.heads,'solana',rpc=self.sol,stopped=stopped.is_set,
            deadline=self.clock()+1,clock=self.clock)
        before=len(self.requests);stopped.set()
        self.assertFalse(refresh.step());self.assertEqual(len(self.requests),before)
        self.assertTrue(self.heads.snapshot('solana_finalized')['collection_stopped'])
        with self.assertRaises(DeliveredRPCError):
            self.sol.call_delivered('getSlot',[dict(commitment='finalized')],2,deadline=self.clock()-1)
        self.assertEqual(len(self.requests),before)

    def test_cancel_between_budget_reservation_and_socket_dispatch_closes_receipt(self):
        self.verify_solana();self.clock.sleep(1)
        stopped=threading.Event();refresh=HeadRefresh(self.heads,'solana',rpc=self.sol,
            stopped=stopped.is_set,deadline=self.clock()+10,clock=self.clock)
        original=bounded.Budget.admission
        def cancel_after_admission(budget):
            result=original(budget);stopped.set();return result
        before=len(self.requests)
        with patch.object(bounded.Budget,'admission',cancel_after_admission):
            self.assertFalse(refresh.step())
        self.assertEqual(len(self.requests),before)
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')

    def test_one_inflight_refresh_per_chain_and_no_missed_tick_burst(self):
        self.verify_solana();self.clock.sleep(1)
        first=HeadRefresh(self.heads,'solana',rpc=self.sol,stopped=lambda:False,
            deadline=self.clock()+100,clock=self.clock)
        second=HeadRefresh(self.heads,'solana',rpc=self.sol,stopped=lambda:False,
            deadline=self.clock()+100,clock=self.clock)
        entered=threading.Event();release=threading.Event()
        self.before_physical=lambda:(entered.set(),release.wait(2))
        thread=threading.Thread(target=first.step)
        thread.start()
        try:
            self.assertTrue(entered.wait(1));before=len(self.requests)
            self.assertFalse(second.step());self.assertEqual(len(self.requests),before)
        finally:release.set();thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.clock.sleep(60)
        self.before_physical=None
        before=len(self.requests)
        self.assertTrue(first.step());self.assertEqual(len(self.requests),before+1)
        self.assertFalse(first.step())

    def test_pons_latest_and_finalized_are_separate_actual_physical_header_receipts(self):
        self.pons.call('eth_getBlockByNumber',['latest',False],scope='pons_evidence_head')
        latest=self.heads.snapshot('pons_latest')
        self.assertEqual(latest['state'],'OBSERVED')
        self.assertEqual(latest['receipt']['network'],4663)
        self.assertEqual(latest['receipt']['commitment'],'latest')
        self.assertEqual(latest['receipt']['header_hash'],self.header['hash'])
        self.assertEqual(latest['receipt']['header_timestamp'],1000)
        self.assertIsNone(self.heads.snapshot('pons_finalized')['receipt'])
        self.clock.sleep(.5)
        self.pons.batch([('eth_getBlockByNumber',['latest',False]),
                         ('eth_getBlockByNumber',['finalized',False])],scope='pons_evidence_head')
        final=self.heads.snapshot('pons_finalized')
        self.assertEqual(final['state'],'OBSERVED')
        self.assertEqual(final['receipt']['commitment'],'finalized')
        self.assertEqual(self.budget.snapshot()['http_attempts'],'3')
        self.assertEqual(self.budget.snapshot()['rpc_elements'],'4')
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')

    def test_injected_transport_cache_numeric_header_and_sequencer_cannot_refresh_head(self):
        rpc=PacedRpc(PONS,role='directional_evidence_primary',requests_per_second=2,
            offline_admission=self.admission,transport=lambda method,params:self.header)
        with self.assertRaisesRegex(ValueError,'canonical_native_rpc_required'):
            self.heads.attach(rpc,'pons')
        self.pons.call('eth_getBlockByNumber',['0x64',False],scope='pons_evidence_head')
        self.assertIsNone(self.heads.snapshot('pons_latest')['receipt'])
        self.pons.call('eth_getBlockByHash',[self.header['hash'],False],scope='pons_evidence_head')
        before=len(self.requests)
        self.pons.call('eth_getBlockByHash',[self.header['hash'],False],scope='pons_evidence_head')
        self.assertEqual(len(self.requests),before)
        self.assertIsNone(self.heads.snapshot('pons_latest')['receipt'])

    def test_pons_refresh_is_non_position_and_keeps_original_admission_and_deadline(self):
        refresh=HeadRefresh(self.heads,'pons',rpc=self.pons,stopped=lambda:False,
            deadline=self.clock()+100,clock=self.clock)
        self.assertTrue(refresh.step())
        self.assertTrue(self.pons.chain_verified)
        import sqlite3
        with sqlite3.connect(self.admission.path) as db:
            priorities=[json.loads(row[0])['priority'] for row in db.execute('SELECT body FROM admissions')]
        self.assertTrue(priorities)
        self.assertTrue(all(value>0 for value in priorities))
        self.assertLessEqual(max(timeout for _,timeout in self.requests),8)
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')
        self.assertIsNone(getattr(self.pons,'_evidence_deadline',None))

    def test_source_generation_provider_change_regression_and_reorg_fail_closed(self):
        self.verify_solana();self.sol.call_delivered('getSlot',[dict(commitment='finalized')],2)
        self.clock.sleep(.1);self.slot=99
        self.sol.call_delivered('getSlot',[dict(commitment='finalized')],2)
        self.assertEqual(self.heads.snapshot('solana_finalized')['state'],'UNAVAILABLE')
        self.assertEqual(self.heads.snapshot('solana_finalized')['discontinuities'],1)
        self.pons.call('eth_getBlockByNumber',['latest',False],scope='pons_evidence_head')
        self.clock.sleep(.5);self.header['hash']='0x'+'e'*64
        self.pons.call('eth_getBlockByNumber',['latest',False],scope='pons_evidence_head')
        self.assertEqual(self.heads.snapshot('pons_latest')['discontinuities'],1)
        self.generation='d'*32
        self.assertEqual(self.heads.snapshot('pons_latest')['state'],'UNAVAILABLE')
        self.sol.endpoint='https://solana-mainnet.g.alchemy.com/v2/changed'
        with self.assertRaises(ValueError):self.heads.attach(self.sol,'solana')

    def test_missing_budget_wrapper_refuses_refresh_before_any_native_work(self):
        with patch('urllib.request.urlopen',side_effect=AssertionError('ungoverned transport')):
            with self.assertRaisesRegex(ValueError,'original_budget_transport_required'):
                HeadRefresh(self.heads,'solana',rpc=self.sol,stopped=lambda:False,
                    deadline=self.clock()+100,clock=self.clock)
        self.assertFalse(self.requests)

    def test_pons_429_does_not_gain_controller_retries_or_position_priority(self):
        self.pons.verify_chain();self.pons.retries=2;self.clock.sleep(1);self.fail=429
        refresh=HeadRefresh(self.heads,'pons',rpc=self.pons,stopped=lambda:False,
            deadline=self.clock()+100,clock=self.clock)
        before=len(self.requests)
        self.assertFalse(refresh.step());self.assertEqual(len(self.requests),before+1)
        self.assertFalse(refresh.step());self.assertEqual(len(self.requests),before+1)
        self.assertEqual(self.heads.snapshot('pons_latest')['failed_refreshes'],1)
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')

    def test_pons_stop_after_budget_admission_never_dispatches_new_socket_work(self):
        self.pons.verify_chain();self.clock.sleep(1)
        stopped=threading.Event()
        refresh=HeadRefresh(self.heads,'pons',rpc=self.pons,stopped=stopped.is_set,
            deadline=self.clock()+100,clock=self.clock)
        original=bounded.Budget.admission
        def stop_after_admission(budget):
            result=original(budget);stopped.set();return result
        before=len(self.requests)
        with patch.object(bounded.Budget,'admission',stop_after_admission):
            self.assertFalse(refresh.step())
        self.assertEqual(len(self.requests),before)
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')
        self.assertTrue(self.heads.snapshot('pons_latest')['collection_stopped'])

    def test_successful_trickle_body_stops_at_absolute_bound_with_partial_bytes_preserved(self):
        self.verify_solana()
        refresh=HeadRefresh(self.heads,'solana',rpc=self.sol,stopped=lambda:False,
            deadline=self.clock()+100,clock=self.clock)
        before=self.budget.snapshot();started=self.clock()
        self.body_chunk=1;self.body_hook=lambda:self.clock.sleep(.6)
        self.assertFalse(refresh.step())
        self.assertLess(self.clock()-started,9)
        after=self.budget.snapshot()
        self.assertGreater(int(after['http_bytes']),int(before['http_bytes']))
        self.assertGreater(int(after['http_uncertain_bytes']),int(before['http_uncertain_bytes']))
        self.assertEqual(after['http_reserved'],'0')
        self.assertEqual(self.heads.snapshot('solana_finalized')['state'],'UNAVAILABLE')
        self.assertIsNone(self.heads.snapshot('solana_finalized')['receipt'])
        self.assertTrue(self.sockets[-1].timeouts)
        self.assertLess(self.sockets[-1].timeouts[-1],self.sockets[-1].timeouts[0])

    def test_successful_body_cancel_checks_each_read_and_preserves_delivered_accounting(self):
        self.pons.verify_chain();stopped=threading.Event()
        refresh=HeadRefresh(self.heads,'pons',rpc=self.pons,stopped=stopped.is_set,
            deadline=self.clock()+100,clock=self.clock)
        before=self.budget.snapshot();self.body_chunk=1;self.body_hook=stopped.set
        self.assertFalse(refresh.step())
        after=self.budget.snapshot()
        self.assertEqual(int(after['http_bytes'])-int(before['http_bytes']),1)
        self.assertGreater(int(after['http_uncertain_bytes']),int(before['http_uncertain_bytes']))
        self.assertEqual(after['http_reserved'],'0')
        self.assertTrue(self.heads.snapshot('pons_latest')['collection_stopped'])
        self.assertIsNone(self.heads.snapshot('pons_latest')['receipt'])

    def test_unknown_chunked_or_unframed_head_body_is_unavailable_without_partial_authority(self):
        self.verify_solana()
        for mode in ('unknown_wrapper','chunked','unframed'):
            self.response_mode=mode
            refresh=HeadRefresh(self.heads,'solana',rpc=self.sol,stopped=lambda:False,
                deadline=self.clock()+100,clock=self.clock)
            self.assertFalse(refresh.step())
            self.assertIsNone(self.heads.snapshot('solana_finalized')['receipt'])
            self.assertEqual(self.budget.snapshot()['http_reserved'],'0')
            self.clock.sleep(6)

    def test_truncated_known_length_body_keeps_uncertain_tail_and_partial_bytes(self):
        self.verify_solana();self.response_mode='truncated'
        refresh=HeadRefresh(self.heads,'solana',rpc=self.sol,stopped=lambda:False,
            deadline=self.clock()+100,clock=self.clock)
        before=self.budget.snapshot()
        self.assertFalse(refresh.step())
        after=self.budget.snapshot()
        self.assertGreater(int(after['http_bytes']),int(before['http_bytes']))
        self.assertGreater(int(after['http_uncertain_bytes']),int(before['http_uncertain_bytes']))
        self.assertEqual(after['http_reserved'],'0')
        self.assertIsNone(self.heads.snapshot('solana_finalized')['receipt'])

    def test_provider_binding_survives_original_session_garbage_collection(self):
        import gc
        heads=MarketHeads(self.source,generation=lambda:self.generation,clock=self.clock,wall=lambda:2000.)
        rpc=heads.attach(RepairRPC(SOL,self.governor),'solana')
        del rpc;gc.collect()
        self.assertEqual(len(heads.bindings),0)
        changed=RepairRPC(SOL.replace('offline-head-secret','different-secret'),self.governor)
        with self.assertRaisesRegex(ValueError,'head_provider_changed'):
            heads.attach(changed,'solana')

    def test_refresh_deadline_and_cancel_context_cannot_mutate_shared_pons_peer(self):
        self.pons.verify_chain();stopped=threading.Event();entered=threading.Event();release=threading.Event()
        peer_deadline=self.clock()+50;self.pons.evidence_deadline=peer_deadline
        refresh=HeadRefresh(self.heads,'pons',rpc=self.pons,stopped=stopped.is_set,
            deadline=self.clock()+100,clock=self.clock)
        worker_deadlines=[]
        def block():
            worker_deadlines.append(self.pons.evidence_deadline)
            entered.set();release.wait(2)
        self.before_physical=block
        thread=threading.Thread(target=refresh.step);thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.pons.evidence_deadline,peer_deadline)
            self.assertIsNone(getattr(self.pons,'market_head_cancelled',None))
            self.assertIsNone(bounded._head_remaining())
            self.assertTrue(worker_deadlines)
            self.assertLessEqual(worker_deadlines[0],self.clock()+8)
        finally:release.set();thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.pons.evidence_deadline,peer_deadline)

    def test_invalid_canonical_header_fields_are_never_inferred_as_zero(self):
        self.pons.verify_chain()
        for index,(field,value) in enumerate([('number',True),('timestamp','0x'),('hash','private-secret')]):
            self.header['hash']='0x'+str(index+1)*64
            original=dict(self.header);self.header[field]=value
            self.clock.sleep(.5)
            self.pons.call('eth_getBlockByNumber',['latest',False],scope='pons_evidence_head')
            row=self.heads.snapshot('pons_latest')
            self.assertEqual(row['state'],'UNAVAILABLE');self.assertIsNone(row['receipt'])
            self.assertNotIn('secret',json.dumps(row))
            self.header=original

    def test_older_overlapping_physical_response_does_not_replace_newer_head_or_fake_regression(self):
        self.verify_solana();self.clock.now=1010
        self.heads.physical_response(self.sol,'getSlot',[dict(commitment='finalized')],102,
            started=1003,completed=1004)
        self.heads.physical_response(self.sol,'getSlot',[dict(commitment='finalized')],100,
            started=1001,completed=1005)
        row=self.heads.snapshot('solana_finalized')
        self.assertEqual(row['receipt']['height'],102)
        self.assertEqual(row['discontinuities'],0)
        self.assertEqual(row['out_of_order_physical_responses'],1)

    def test_owned_pons_refresh_rotates_only_exhausted_original_native_session(self):
        clients=[]
        def configured():
            rpc=PacedRpc(PONS,role='directional_evidence_primary',requests_per_second=2,
                offline_admission=self.admission,retries=0,limit=3,per_scope=2)
            clients.append(rpc);return rpc
        with patch('meme_machine.lanes.pons.provider_topology.configured_rpc',configured):
            refresh=HeadRefresh.pons(self.heads,stopped=lambda:False,
                deadline=self.clock()+100,clock=self.clock)
            self.assertTrue(refresh.step())
            first=self.heads.snapshot('pons_latest')['receipt']['rpc_session']
            self.clock.sleep(5.1);self.assertTrue(refresh.step())
            self.assertEqual(len(clients),1)
            self.clock.sleep(5.1);self.assertTrue(refresh.step())
        self.assertEqual(len(clients),2)
        self.assertNotEqual(self.heads.snapshot('pons_latest')['receipt']['rpc_session'],first)
        self.assertEqual(self.budget.snapshot()['http_attempts'],'5')
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')
        self.assertTrue(all(client.limit==3 and client.per_scope==2 for client in clients))

    def test_small_public_projection_has_no_url_secret_or_economic_authority(self):
        self.verify_solana();self.sol.call_delivered('getSlot',[dict(commitment='finalized')],2)
        self.pons.call('eth_getBlockByNumber',['latest',False],scope='pons_evidence_head')
        data={kind:self.heads.snapshot(kind) for kind in ('solana_finalized','pons_latest','pons_finalized')}
        raw=json.dumps(data,allow_nan=False).encode()
        self.assertLess(len(raw),MAXIMUM_BYTES)
        self.assertNotIn(b'secret',raw);self.assertNotIn(b'https://',raw)
        self.assertTrue(all(row['canonical_coverage'] is False and row['normal_readiness'] is False
            and row['economic_arrival_count'] is None for row in data.values()))


class HeadSourceBindingTests(unittest.TestCase):
    def test_source_binding_requires_exact_clean_head_tree_and_real_process_identity(self):
        responses=[SimpleNamespace(stdout=value) for value in (b'a'*40+b'\n',b'b'*40+b'\n',b'')]
        with patch('subprocess.run',side_effect=responses) as run:
            value=HeadSource.verified_checkout(expected_commit='a'*40,expected_tree='b'*40,generation='c'*32)
        self.assertEqual(value.pid,os.getpid());self.assertGreater(value.process_start_ticks,0)
        self.assertEqual(value.commit,'a'*40)
        self.assertTrue(all(call.kwargs['timeout']==5 for call in run.call_args_list))
        responses=[SimpleNamespace(stdout=value) for value in (b'a'*40+b'\n',b'b'*40+b'\n',b' M native.py\n')]
        with patch('subprocess.run',side_effect=responses):
            with self.assertRaisesRegex(ValueError,'changed_or_dirty'):
                HeadSource.verified_checkout(expected_commit='a'*40,expected_tree='b'*40,generation='c'*32)


if __name__=='__main__':unittest.main()
