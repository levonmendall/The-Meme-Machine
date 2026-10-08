"""Offline failure injection for every executable NEXT_PROOF boundary."""
from argparse import Namespace
import asyncio
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import Request
from unittest.mock import patch

from engineering.solana_capacity.proof_limits import (Budget,CeilingReached,QueueEvidence,load_contract,
    CONTRACT_PATH,LIMITS,TIMES,MAX_FRAME,PUBLISHED,endpoint_family,validate_native_bindings)
from engineering.solana_capacity.proof_host import (ResourceWatch,WriteAdmission,RECEIPT_RESERVE,HostUnavailable,
    LinuxGroup,group_sample,KernelAdmission,install_notifications,receive_listener)
from engineering.solana_capacity.proof_transport import Transports
from engineering.solana_capacity.pump_pons_proof import classify,main,validate_resume,supervise

SOL='https://solana-mainnet.g.alchemy.com/v2/offline-test'
RH='https://robinhood-mainnet.g.alchemy.com/v2/offline-test'


def call(method='getSlot',params=None):return dict(jsonrpc='2.0',id=1,method=method,params=[] if params is None else params)
class Clock:
    def __init__(self):self.at=0.
    def __call__(self):return self.at
    def advance(self,n):self.at+=n


class ContractTests(unittest.TestCase):
    def test_exact_contract_loads_and_all_values_are_pinned(self):
        c=load_contract();self.assertEqual(c.limits,LIMITS);self.assertEqual(c.time,TIMES)
        self.assertFalse(c.body['production_epoch_access']);self.assertEqual(c.body['paused_operational_workloads'],dict(meteora=0,ramses=0))
        validate_native_bindings(c)
    def test_missing_malformed_duplicate_nonfinite_and_legacy_contracts_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'contract.json'
            cases=[None,b'{}',b'{',b'{"limits":{},"limits":{}}',b'{"limits":NaN}',b'{"wall_seconds":300}']
            for value in cases:
                with self.subTest(value=value):
                    if value is not None:p.write_bytes(value)
                    with self.assertRaises(ValueError):load_contract(p)
    def test_each_published_value_and_limit_change_is_rejected(self):
        c=load_contract()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'contract.json'
            for section,fields in [('limits',c.limits),('time',c.time)]:
                for field in fields:
                    body=deepcopy(c.body);body[section][field]+=1;p.write_text(json.dumps(body))
                    with self.subTest(field=field),self.assertRaises(ValueError):load_contract(p)
            body=deepcopy(c.body);body['dispatch_allowed']=True;p.write_text(json.dumps(body))
            with self.assertRaises(ValueError):load_contract(p)
            body=deepcopy(c.body);body['limits']['queue_capacity']=64.;p.write_text(json.dumps(body))
            with self.assertRaises(ValueError):load_contract(p)
    def test_every_published_leaf_including_workload_and_recovery_is_pinned(self):
        body=load_contract().body
        def leaves(value,path=()):
            if isinstance(value,dict):
                for key,child in value.items():yield from leaves(child,path+(key,))
            elif isinstance(value,list):
                for key,child in enumerate(value):yield from leaves(child,path+(key,))
            else:yield path,value
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'contract.json'
            for path,value in leaves(body):
                altered=deepcopy(body);node=altered
                for key in path[:-1]:node=node[key]
                node[path[-1]]=not value if isinstance(value,bool) else value+1 if isinstance(value,(int,float)) else value+' altered'
                p.write_text(json.dumps(altered))
                with self.subTest(path=path),self.assertRaises(ValueError):load_contract(p)


class BudgetTests(unittest.TestCase):
    def setUp(self):self.clock=Clock();self.b=Budget(load_contract(),clock=self.clock)
    def reserve(self,calls=None,url=SOL,**kw):return self.b.reserve_http(url,calls or [call()],**kw)
    def stop(self,reason,fn):
        with self.assertRaises(CeilingReached) as e:fn()
        self.assertEqual(e.exception.reason,reason);self.assertTrue(self.b.stop.is_set())
    def test_unknown_methods_unpriced_methods_and_wrong_families_prevent_dispatch(self):
        for method in ('unpriced','sendTransaction','eth_call','getAssetTransfers'):
            self.setUp();self.stop('unpriced_or_unapproved_method',lambda:self.reserve([call(method)]))
            self.assertEqual(self.b.counts['physical_http_attempts'],0)
    def test_unknown_endpoints_schemes_credentials_paths_and_aliases_prevent_dispatch(self):
        for url in ('https://evil.invalid','http://solana-mainnet.g.alchemy.com/v2/x',SOL+'?token=x',SOL+'/path',
                    'https://user:token@solana-mainnet.g.alchemy.com/v2/x','https://solana-mainnet.g.alchemy.com.evil/v2/x',
                    'https://solana-mainnet.g.alchemy.com:80/v2/x',SOL+'%2fextra',SOL+'%00'):
            self.setUp();self.stop('unapproved_provider_endpoint',lambda:self.reserve(url=url))
            self.assertEqual(self.b.counts['physical_http_attempts'],0)
    def test_batch_has_multiple_elements_one_attempt_and_independent_cu(self):
        self.reserve([call(),call('getTokenLargestAccounts')]).close()
        self.assertEqual(self.b.counts['physical_http_attempts'],1)
        self.assertEqual(self.b.counts['total_rpc_elements'],2)
        self.assertEqual(self.b.counts['published_rpc_cu'],3020)
        self.assertEqual(self.b.counts['diagnostic_rpc_cu'],40)
        self.reserve([call('eth_getLogs',[dict(fromBlock='0x1',toBlock='0xa')])],RH).close()
        self.assertEqual(self.b.counts['published_rpc_cu'],3080)
        self.assertEqual(self.b.counts['diagnostic_rpc_cu'],140)
        self.assertIsNone(self.b.snapshot()['actual_provider_billed_cu'])
    def test_rpc_element_and_attempt_ceilings_at_boundary_and_next_rejected(self):
        for name in ('physical_http_attempts','total_rpc_elements','solana_rpc_elements','robinhood_rpc_elements'):
            self.setUp();self.b.limits[name]=2
            url=RH if name=='robinhood_rpc_elements' else SOL
            method='eth_blockNumber' if url==RH else 'getSlot'
            r=self.reserve([call(method)],url);r.close()
            r=self.reserve([call(method)],url);self.stop(name,r.close)
            self.assertEqual(self.b.counts[name],2)
            self.stop(name,lambda:self.reserve([call(method)],url))
            self.assertEqual(self.b.counts[name],2)
    def test_published_diagnostic_and_total_cu_ceilings_prevent_additional_request(self):
        for name in ('published_rpc_cu','diagnostic_rpc_cu','total_diagnostic_cu'):
            self.setUp();self.b.limits[name]=20;r=self.reserve();self.stop(name,r.close)
            self.stop(name,lambda:self.reserve());self.assertEqual(self.b.counts[name],20)
    def test_concurrent_pump_and_pons_atomic_boundaries(self):
        for ceiling in ('total_rpc_elements','physical_http_attempts','published_rpc_cu','diagnostic_rpc_cu'):
            self.setUp();self.b.limits[ceiling]=20 if ceiling.endswith('_cu') else 2
            barrier=threading.Barrier(3);accepted=[];errors=[]
            def worker(url,method):
                barrier.wait()
                try:
                    for _ in range(20):
                        r=self.reserve([call(method)],url);accepted.append((url,method));r.close()
                except CeilingReached as exc:errors.append(exc.reason)
            a=threading.Thread(target=worker,args=(SOL,'getSlot'));b=threading.Thread(target=worker,args=(RH,'eth_blockNumber'))
            a.start();b.start();barrier.wait();a.join(2);b.join(2)
            self.assertFalse(a.is_alive() or b.is_alive());self.assertTrue(errors)
            self.assertLessEqual(self.b.counts[ceiling],self.b.limits[ceiling])
            self.assertEqual(self.b.counts['total_rpc_elements'],len(accepted))
    def test_log_range_ten_accepted_eleven_dynamic_or_reverse_refused(self):
        self.reserve([call('eth_getLogs',[dict(fromBlock='0x1',toBlock='0xa')])],RH).close()
        for lo,hi in [('0x1','0xb'),('latest','latest'),('0xa','0x1')]:
            self.setUp();self.stop('maximum_log_range_blocks',lambda:self.reserve([call('eth_getLogs',[dict(fromBlock=lo,toBlock=hi)])],RH))
    def test_no_retry_rule(self):self.stop('rpc_retries',lambda:self.reserve(retry=1))
    def test_malformed_batch_and_envelopes_refused_before_attempt(self):
        for rows in ([],[call()]*201,[dict(method='getSlot')],['getSlot']):
            self.setUp()
            with self.assertRaises(CeilingReached):self.b.reserve_http(SOL,rows)
            self.assertEqual(self.b.counts['physical_http_attempts'],0)
    def test_http_stream_meter_stops_before_oversized_body_is_buffered(self):
        self.b.limits['per_http_response_bytes']=32768;r=self.reserve();raw=io.BytesIO(b'x'*100000)
        self.stop('per_http_response_bytes',lambda:r.acquire(raw.read))
        self.assertEqual(raw.tell(),32768);self.assertEqual(self.b.counts['http_response_bytes'],32768);r.close()
    def test_http_individual_just_below_boundary_passes_and_exact_boundary_stops(self):
        self.b.limits['per_http_response_bytes']=100
        r=self.reserve();self.assertEqual(len(r.acquire(io.BytesIO(b'x'*99).read)),99);r.close()
        self.stop('per_http_response_bytes',lambda:self.reserve().acquire(io.BytesIO(b'x'*100).read))
    def test_cumulative_http_reservation_is_atomic_under_concurrency(self):
        self.b.limits['per_http_response_bytes']=100;self.b.limits['http_response_bytes']=200
        a=self.reserve();b=self.reserve();self.stop('http_response_reservation',lambda:self.reserve())
        self.assertEqual(self.b.counts['physical_http_attempts'],2);a.close();b.close();self.assertEqual(self.b.http_reserved,0)
    def test_cumulative_actual_http_exhaustion_stops_acquisition(self):
        self.b.limits['per_http_response_bytes']=100;self.b.limits['http_response_bytes']=100
        r=self.reserve();self.stop('http_response_bytes',lambda:r.acquire(io.BytesIO(b'x'*100).read))
    def test_native_delivery_ceilings_diag_total_and_shutdown_margin(self):
        for name,size,limit,reason in [('native_stream_bytes',1025,1024,'native_stream_bytes'),
            ('diagnostic_native_cu',1025,2,'diagnostic_native_cu'),('total_diagnostic_cu',1025,2,'total_diagnostic_cu'),
            ('native_stream_bytes',1024,1024,'native_shutdown_margin')]:
            self.setUp();self.b.limits['native_inflight_shutdown_reserve_bytes']=0;self.b.limits[name]=limit
            self.stop(reason,lambda:self.b.native('yellowstone',size))
            self.assertEqual(self.b.counts['native_stream_bytes'],size)
    def test_native_transports_sum_and_received_delivery_after_stop_is_charged(self):
        self.b.native('yellowstone',511);self.b.stop_work();self.b.native('solana_websocket',2)
        self.assertEqual(self.b.counts['native_stream_bytes'],513);self.assertEqual(self.b.counts['diagnostic_native_cu'],2)
        self.assertEqual(self.b.snapshot()['published_modeled_solana_ws_cu'],'0.0004')
    def test_native_inflight_reserve_and_no_evm_subscription(self):
        reserves=[self.b.stream_open('yellowstone') for _ in range(8)]
        self.stop('native_inflight_shutdown_reserve_bytes',lambda:self.b.stream_open('solana_websocket'))
        for r in reserves:self.b.stream_close(r)
        self.assertEqual(self.b.native_inflight,0);self.setUp()
        self.stop('unapproved_native_transport',lambda:self.b.stream_open('evm_websocket'))
    def test_sdk_unread_shutdown_reservations_are_charged_separately_from_known_payload(self):
        reserve=self.b.stream_open('yellowstone');self.b.native('yellowstone',100)
        self.b.stream_close(reserve,transport='yellowstone',unread_possible=True)
        snapshot=self.b.snapshot()
        self.assertEqual(snapshot['native_known_delivered_bytes'],100)
        self.assertEqual(snapshot['native_possible_unread_shutdown_bytes']['yellowstone'],reserve)
        self.assertEqual(snapshot['counts']['native_stream_bytes'],100+reserve)
        self.assertEqual(snapshot['native_inflight_reserved_bytes'],0)
    def test_native_subscribe_and_websocket_upgrade_are_physical_attempts_not_rpc_elements(self):
        a=self.b.stream_open('yellowstone');b=self.b.stream_open('solana_websocket')
        self.assertEqual(self.b.counts['physical_http_attempts'],2)
        self.assertEqual(self.b.counts['total_rpc_elements'],0)
        self.b.stream_close(a);self.b.stream_close(b)
        self.b.limits['physical_http_attempts']=2
        self.stop('physical_http_attempts',lambda:self.b.stream_open('yellowstone'))
    def test_concurrent_native_transports_share_diagnostic_and_byte_ceiling(self):
        self.b.limits['native_stream_bytes']=1024;self.b.limits['native_inflight_shutdown_reserve_bytes']=512
        barrier=threading.Barrier(3);errors=[]
        def worker(transport):
            barrier.wait()
            try:self.b.native(transport,512)
            except CeilingReached as exc:errors.append(exc.reason)
        workers=[threading.Thread(target=worker,args=(t,)) for t in ('yellowstone','solana_websocket')]
        for w in workers:w.start()
        barrier.wait()
        for w in workers:w.join(1)
        self.assertEqual(self.b.counts['native_stream_bytes'],1024)
        self.assertEqual(self.b.counts['diagnostic_native_cu'],2);self.assertTrue(errors)
    def test_startup_wall_and_stop_admission_use_monotonic_time(self):
        self.clock.advance(59.99);self.b.ready();self.clock.advance(210.01)
        self.assertGreaterEqual(self.clock(),270)
        with self.assertRaises(CeilingReached) as e:self.reserve()
        self.assertEqual(e.exception.reason,'admission_closed');self.assertEqual(self.b.counts['physical_http_attempts'],0)
        self.clock.at=300;self.stop('wall_time_ceiling',self.b.check_time)
        self.setUp();self.clock.at=60;self.stop('startup_ceiling',self.b.check_time)
    def test_failed_rpc_cannot_be_retried_through_another_client(self):
        calls=[]
        def opener(*a,**kw):calls.append(1);return io.BytesIO(b'{"jsonrpc":"2.0","id":1,"error":{"code":-1}}')
        t=Transports(self.b,QueueEvidence(self.b),offline=True,opener=opener)
        request=Request(SOL,json.dumps(call()).encode())
        with self.assertRaises(CeilingReached):
            with t.open(request) as response:response.read()
        with self.assertRaises(CeilingReached):t.open(request)
        self.assertEqual(len(calls),1)
    def test_unknown_dispatch_refused_before_fake_transport_is_called(self):
        calls=[];t=Transports(self.b,QueueEvidence(self.b),offline=True,opener=lambda *a,**kw:calls.append(1))
        with self.assertRaises(CeilingReached):t.open(Request(SOL,json.dumps(call('sendTransaction')).encode()))
        self.assertEqual(calls,[])


class SchedulerTests(unittest.TestCase):
    def setUp(self):self.clock=Clock();self.b=Budget(load_contract(),clock=self.clock);self.q=QueueEvidence(self.b)
    def test_capacity_at_64_above_64_and_sustained_at_5_seconds(self):
        self.q.occupancy('native',64)
        with self.assertRaises(CeilingReached):self.q.occupancy('native',65)
        self.setUp();self.q.occupancy('native',32);self.clock.advance(4.999);self.q.poll()
        self.clock.advance(.0011)
        with self.assertRaises(CeilingReached) as e:self.q.poll()
        self.assertEqual(e.exception.reason,'sustained_queue_overload')
    def test_depth_below_32_resets_sustained_timer_not_single_snapshot_pass(self):
        self.q.occupancy('native',32);self.clock.advance(4.9);self.q.occupancy('native',31)
        self.clock.advance(100);self.q.occupancy('native',32);self.clock.advance(4.9);self.q.poll()
        self.assertFalse(self.b.stop.is_set());self.assertFalse(self.q.snapshot()['drain_proven'])
    def test_position_violation_stops_while_waiting_without_dispatch(self):
        self.q.enqueue('authentic-preserved-position',kind='position',deadline=1)
        self.clock.at=1;self.q.poll();self.clock.at=1.001
        with self.assertRaises(CeilingReached) as e:self.q.poll()
        self.assertEqual(e.exception.reason,'position_deadline_violation')
    def test_two_overdue_candidates_stop_even_if_both_are_blocked(self):
        for identity in ('pump','pons'):self.q.enqueue(identity,kind='candidate',deadline=1)
        self.clock.at=1.01
        with self.assertRaises(CeilingReached) as e:self.q.poll()
        self.assertEqual(e.exception.reason,'consecutive_candidate_deadline_violations')
    def test_cancellation_cannot_reset_candidate_streak_but_success_can(self):
        self.q.enqueue('late',kind='candidate',deadline=0);self.q.dispatch('late');self.clock.advance(1);self.q.finish('late')
        self.q.enqueue('cancel',kind='candidate',deadline=10);self.q.finish('cancel',cancelled=True)
        self.assertEqual(self.q.candidate_streak,1)
        self.q.enqueue('success',kind='candidate',deadline=10);self.q.dispatch('success');self.q.finish('success')
        self.assertEqual(self.q.candidate_streak,0)
        self.q.enqueue('late2',kind='candidate',deadline=0);self.q.finish('late2',cancelled=True)
        self.assertEqual(self.q.candidate_streak,1)
    def test_actual_native_job_clocks_dispatch_and_completion_are_preserved(self):
        job=dict(id='native',created=99,deadline=103,status='pending',priority=3)
        self.q.scheduler_snapshot([job],source_now=100)
        self.assertEqual(self.q.pending['acquisition:native']['original_wall_deadline'],103)
        self.clock.advance(2);self.q.scheduler_snapshot([job],source_now=102,claimed='native')
        self.assertEqual(self.q.running['acquisition:native']['queue_wait'],3)
        job['status']='complete';self.q.scheduler_snapshot([job],source_now=102)
        self.assertFalse(self.q.snapshot()['drain_proven']);self.assertEqual(self.q.completed,1)
    def test_repeated_running_service_is_required_and_shutdown_drain_cannot_create_a_witness(self):
        self.q.poll()
        for at,identity in [(0,'first'),(6,'second')]:
            self.clock.at=at;self.q.enqueue(identity);self.q.dispatch(identity);self.q.finish(identity);self.q.poll()
        self.assertTrue(self.q.snapshot()['drain_proven'])
        self.setUp();self.q.poll();self.q.enqueue('shutdown-work');self.q.dispatch('shutdown-work')
        self.b.stop_work();self.q.finish('shutdown-work');self.clock.advance(6);self.q.poll()
        self.assertFalse(self.q.snapshot()['drain_proven'])
    def test_native_deadline_disposal_between_censuses_is_not_erased(self):
        jobs=[dict(id=i,created=99,deadline=100,status='deadline_missed',priority=3) for i in ('pump','pons')]
        with self.assertRaises(CeilingReached):self.q.scheduler_snapshot(jobs,source_now=101)
        self.assertEqual(self.q.violations['candidate'],2)
    def test_shutdown_cancels_admission_without_renewing_candidate_deadlines(self):
        self.q.enqueue('pending',kind='candidate',deadline=2);self.b.stop_work()
        with self.assertRaises(CeilingReached):self.q.enqueue('new',kind='candidate',deadline=4)
        self.assertEqual(self.q.pending['pending']['deadline'],2)


class NativeTransportTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.b=Budget(load_contract(),clock=self.clock);self.t=Transports(self.b,QueueEvidence(self.b),offline=True)
    def test_paused_native_filters_are_refused_before_subscription_write(self):
        from engineering.solana_capacity.proof_transport import Stream
        from meme_machine.yellowstone import geyser_pb2 as pb
        from meme_machine.solana_selective_history import PROGRAMS
        class Raw:
            written=0
            async def write(self,request):self.written+=1
        for kind in ('accounts','transactions','transactions_status'):
            self.setUp();raw=Raw();request=pb.SubscribeRequest();filters=getattr(request,kind)
            (filters['paused'].owner if kind=='accounts' else filters['paused'].account_include).append(PROGRAMS['meteora'])
            with self.assertRaises(CeilingReached):asyncio.run(Stream(raw,self.t,0).write(request))
            self.assertEqual(raw.written,0)
    def test_disconnect_resubscription_retains_checkpoint_floor_and_charges_cancel_tail_once(self):
        import grpc
        from engineering.solana_capacity.proof_transport import Stream
        from meme_machine.yellowstone import geyser_pb2 as pb
        class Raw:
            cancellations=0
            def cancel(self):self.cancellations+=1
            async def write(self,request):pass
        raw=Raw();reserve=self.b.stream_open('yellowstone');s=Stream(raw,self.t,reserve)
        checkpoint=dict(control_checkpoint=1000,candidates=[['pump','original',990,12.5]],checkpoints=[['scope',999]])
        async def probe():return checkpoint
        self.t.recovery_probe=probe
        request=pb.SubscribeRequest(from_slot=744);request.blocks_meta['b'].SetInParent()
        asyncio.run(s.write(request));self.b.ready();self.clock.advance(60)
        self.assertIs(asyncio.run(s.read()),grpc.aio.EOF)
        s.cancel();s.cancel();self.assertEqual(self.b.counts['native_stream_bytes'],reserve)
        new=Stream(Raw(),self.t,0);asyncio.run(new.write(request))
        self.assertTrue(self.t.disconnect_receipt['resubscribed'])
        self.assertEqual(self.t.disconnect_receipt['resume_from_slot'],744)
    def test_websocket_connection_context_cannot_authorize_another_http_client(self):
        from engineering.solana_capacity.proof_transport import WebSocketContext,_NETWORK
        class Raw:
            async def __aenter__(raw):
                self.assertIsNotNone(_NETWORK.get());return raw
            async def __aexit__(raw,*a):pass
        async def run():
            async with WebSocketContext(Raw(),self.t):self.assertIsNone(_NETWORK.get())
            self.assertIsNone(_NETWORK.get())
        asyncio.run(run());self.assertEqual(self.t.ws_opening,0)
        self.assertEqual(self.b.native_inflight,0)


class ResourceTests(unittest.TestCase):
    def row(self,**kw):
        result=dict(at=0.,cpu_seconds=0.,group_rss_bytes=0,minimum_system_available_bytes=LIMITS['minimum_system_available_bytes'],
            output_stock_bytes=0,memory_events={},cumulative_process_write_bytes=0);result.update(kw);return result
    def test_group_rss_at_and_above_ceiling_stops(self):
        for n,reason in [(LIMITS['proof_group_rss_bytes']-1,None),(LIMITS['proof_group_rss_bytes'],'proof_group_rss_bytes'),
                         (LIMITS['proof_group_rss_bytes']+1,'proof_group_rss_bytes')]:
            self.assertEqual(ResourceWatch(LIMITS).check(self.row(group_rss_bytes=n)),reason)
    def test_low_system_available_memory_stops(self):
        self.assertIsNone(ResourceWatch(LIMITS).check(self.row()))
        self.assertEqual(ResourceWatch(LIMITS).check(self.row(minimum_system_available_bytes=LIMITS['minimum_system_available_bytes']-1)),
            'minimum_system_available_bytes')
    def test_cpu_30_second_average_just_below_at_and_above_1_point_8(self):
        for cores,expected in [(1.799,None),(1.8,None),(1.801,'maximum_group_cpu_cores_30_second_average')]:
            w=ResourceWatch(LIMITS);w.check(self.row());self.assertEqual(w.check(self.row(at=30,cpu_seconds=30*cores)),expected)
    def test_cpu_is_rolling_window_including_exited_workers(self):
        w=ResourceWatch(LIMITS)
        for at,cpu in [(0,0),(10,5),(20,25),(30,45)]:w.check(self.row(at=at,cpu_seconds=cpu))
        self.assertEqual(w.check(self.row(at=40,cpu_seconds=65)),'maximum_group_cpu_cores_30_second_average')
    def test_cumulative_write_reservations_and_stock_independently_stop(self):
        limits=dict(LIMITS,cumulative_process_write_bytes=RECEIPT_RESERVE+100,output_stock_bytes=RECEIPT_RESERVE+100)
        w=WriteAdmission(limits,'/unused')
        self.assertIsNone(w.reserve(99,key='same-inode',end=1))
        self.assertIsNone(w.reserve(1,key='same-inode',end=1))
        self.assertEqual(w.stock,1);self.assertEqual(w.reserve(1,key='same-inode',end=1),'cumulative_process_write_bytes')
        w=WriteAdmission(limits,'/unused');self.assertIsNone(w.reserve(1,key='sparse',end=100))
        self.assertEqual(w.reserve(0,key='sparse',end=101),'output_stock_bytes');self.assertEqual(w.writes,1)
    def test_output_stock_low_and_exact_guard(self):
        boundary=LIMITS['output_stock_bytes']-RECEIPT_RESERVE
        self.assertIsNone(ResourceWatch(LIMITS).check(self.row(output_stock_bytes=boundary-1)))
        self.assertEqual(ResourceWatch(LIMITS).check(self.row(output_stock_bytes=boundary)),'output_stock_bytes')
    def test_unavailable_measurements_fail_closed(self):
        with self.assertRaises(HostUnavailable):ResourceWatch(LIMITS).check({})
        with self.assertRaises(HostUnavailable):WriteAdmission(LIMITS,'/unused').reserve(-1)
        for key,value in [('cpu_seconds',float('nan')),('group_rss_bytes',-1),('cumulative_process_write_bytes',None)]:
            with self.assertRaises(HostUnavailable):ResourceWatch(LIMITS).check(self.row(**{key:value}))
    def test_actual_cumulative_write_counter_reaches_guard_independently_of_output_stock(self):
        boundary=LIMITS['cumulative_process_write_bytes']-16*1024*1024
        self.assertIsNone(ResourceWatch(LIMITS).check(self.row(cumulative_process_write_bytes=boundary-1)))
        self.assertEqual(ResourceWatch(LIMITS).check(self.row(cumulative_process_write_bytes=boundary)),'cumulative_process_write_bytes')
    def test_cgroup_oom_events_fail_even_if_current_rss_dropped_after_worker_exit(self):
        self.assertEqual(ResourceWatch(LIMITS).check(self.row(memory_events={'oom_kill':1})),'cgroup_memory_limit')


class DispatchAndShutdownTests(unittest.TestCase):
    def command(self,code,*args):
        return subprocess.run([sys.executable,'-c',code,*args],cwd=Path(__file__).resolve().parents[1],
            env={'PATH':os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=5)
    def test_import_default_description_and_private_child_make_zero_connections(self):
        code="""import socket,json
calls=[]
socket.socket.connect=lambda *a,**k:calls.append(1)
import engineering.solana_capacity.pump_pons_proof as p
assert not calls
assert p.main([])==0
assert p.main(['--child'])==2
assert p.main(['--execute','--output','/unused','--env','/credentials-must-not-be-read'])==2
assert not calls
"""
        result=self.command(code);self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('separate_authorized_live_invocation_required',result.stderr)
    def test_ci_cannot_deliberately_open_live_execution(self):
        with patch.dict(os.environ,{'CI':'true'}),patch('engineering.solana_capacity.pump_pons_proof.environment') as env:
            self.assertEqual(main(['--execute','--authorized-live-proof','--output','/unused','--source-commit','x','--env','/unused']),2)
            env.assert_not_called()
    def test_failed_killed_incomplete_and_short_observation_never_pass(self):
        good=dict(reason=None,returncode=0,forced=False,ready_elapsed=1,elapsed=181,done=True)
        self.assertEqual(classify(**good),'PASS')
        for change in (dict(reason='limit'),dict(returncode=-9),dict(forced=True),dict(done=False),dict(descendants_survived=True),dict(elapsed=180.99)):
            self.assertEqual(classify(**dict(good,**change)),'FAIL')
        self.assertEqual(classify(**dict(good,insufficient=['missing_authentic_position'])),'INSUFFICIENT_SAMPLE')
        self.assertEqual(classify(**dict(good,normal_drain_proven=False)),'INSUFFICIENT_SAMPLE')
    def test_checkpoint_resume_preserves_identity_source_clocks_and_nonregressing_frontiers(self):
        before=dict(control_checkpoint=100,candidates=[['pump','native-id',99,123.5]],checkpoints=[['native-scope',100]])
        after=deepcopy(before);after['control_checkpoint']=101;after['checkpoints'][0][1]=101
        self.assertTrue(validate_resume(before,after))
        for change in (dict(control_checkpoint=99),dict(candidates=[['pump','native-id',99,124.]]),dict(checkpoints=[['native-scope',99]])):
            self.assertFalse(validate_resume(before,dict(after,**change)))
    def test_actual_cgroup_contains_and_kills_escaped_descendant(self):
        # Real setsid escape proves killpg alone would be insufficient.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);group=LinuxGroup(LIMITS);read,write=os.pipe();pid=os.fork()
            if pid==0:
                os.close(read)
                try:
                    group.attach_self();grandchild=os.fork()
                    if grandchild==0:
                        os.setsid();os.write(write,str(os.getpid()).encode());os.close(write)
                        while True:time.sleep(.02)
                    os.close(write)
                    while True:time.sleep(.02)
                finally:os._exit(1)
            os.close(write)
            try:
                import select
                self.assertTrue(select.select([read],[],[],3)[0]);grandchild=int(os.read(read,64));sample=group_sample(group,root)
                self.assertIn(pid,sample['pids']);self.assertIn(grandchild,sample['pids'])
                values=[r['rss_bytes'] for r in sample['processes']]
                self.assertEqual(sample['group_rss_bytes'],sum(values));self.assertGreater(sum(values),max(values))
                group.kill();until=time.monotonic()+3
                while group.populated() and time.monotonic()<until:time.sleep(.005)
                self.assertFalse(group.populated())
                # Reap direct child; escaped child is adopted by init unless the
                # full finite-proof supervisor has enabled its subreaper.
                os.waitpid(pid,0)
            finally:
                os.close(read)
                if group.populated():group.kill()
                group.close()
    def test_native_owner_expiry_and_async_queue_lifecycle_are_observed_offline(self):
        code="""import asyncio,time
from types import SimpleNamespace
from engineering.solana_capacity.proof_limits import Budget,QueueEvidence,load_contract
from engineering.solana_capacity.proof_transport import Transports
from engineering.solana_capacity.proof_workload import FakeHTTP
from meme_machine.solana_evidence_control import PriorityOwner
b=Budget(load_contract());q=QueueEvidence(b);t=Transports(b,q,offline=True,opener=FakeHTTP());t.install()
owner=PriorityOwner(lambda:SimpleNamespace(close=lambda:None));owner.ready.result(2)
f=owner.submit(lambda s:42,expires=time.time()-1)
try:f.result(2)
except Exception:pass
assert not q.pending and not q.running and q.completed==1
assert q.snapshot()['events'][-1]['error']=='EvidenceUnavailable'
async def run():
 queue=asyncio.Queue();assert queue.maxsize==64
 await queue.put('original');assert await queue.get()=='original'
 queue.task_done();await queue.join()
asyncio.run(run());assert q.completed==2
with owner.cv:owner.closed=True;owner.cv.notify_all()
owner.thread.join(2);assert not owner.thread.is_alive()
assert b.dispatched==0 and b.fake_dispatches==0
t.close()
"""
        result=self.command(code);self.assertEqual(result.returncode,0,result.stderr)
    def test_alternative_http_clients_and_unapproved_native_channels_fail_without_connection(self):
        code="""import socket,grpc
from engineering.solana_capacity.proof_limits import Budget,QueueEvidence,load_contract,CeilingReached
from engineering.solana_capacity.proof_transport import Transports
from engineering.solana_capacity.proof_workload import FakeHTTP
b=Budget(load_contract());t=Transports(b,QueueEvidence(b),offline=True,opener=FakeHTTP());t.install()
for fn in (lambda:grpc.secure_channel('unsupported',grpc.ssl_channel_credentials()),
           lambda:grpc.aio.secure_channel('unsupported',grpc.ssl_channel_credentials()),
           lambda:socket.socket().connect(('127.0.0.1',9))):
 try:fn();raise AssertionError('unmetered dispatch admitted')
 except CeilingReached:pass
assert b.dispatched==0
t.close()
"""
        result=self.command(code);self.assertEqual(result.returncode,0,result.stderr)
    def test_actual_provider_admission_waits_are_recorded_without_provider_dispatch(self):
        code="""import tempfile
from pathlib import Path
from engineering.solana_capacity.proof_limits import Budget,QueueEvidence,load_contract
from engineering.solana_capacity.proof_transport import Transports
from engineering.solana_capacity.proof_workload import FakeHTTP
from meme_machine.runtime.governor import Governor
from meme_machine.lanes.pons.provider_admission import Admission
from meme_machine.lanes.pons.provider_topology import ProviderPacer
b=Budget(load_contract());q=QueueEvidence(b);t=Transports(b,q,offline=True,opener=FakeHTTP());t.install()
with tempfile.TemporaryDirectory() as d:
 Governor(Path(d)/'solana.sqlite').acquire('solana','pump',methods=('getSlot',))
 Admission(Path(d)/'robinhood.sqlite','https://robinhood-mainnet.g.alchemy.com/v2/offline-test',lane='pons').acquire('candidate')
 ProviderPacer(2).pace()
assert q.completed==3 and not q.pending and not q.running
assert {r['queue'] for r in q.snapshot()['events']}=={'solana-provider','robinhood-provider','robinhood-pacer'}
assert all(r['queue_wait']>=0 for r in q.snapshot()['events'])
assert b.dispatched==b.fake_dispatches==0
t.close()
"""
        result=self.command(code);self.assertEqual(result.returncode,0,result.stderr)
    def test_live_constructor_uses_preflight_identity_without_subprocess_or_network(self):
        code="""import tempfile,socket
from pathlib import Path
from unittest.mock import patch
from engineering.solana_capacity.final_mixed import FinalMixed
calls=[]
with tempfile.TemporaryDirectory() as d,patch('subprocess.check_output',side_effect=AssertionError('exec')),patch.object(socket.socket,'connect',side_effect=AssertionError('network')):
 c=FinalMixed(Path(d),180,{'MM_SOLANA_READ_RPC_URL':'https://solana-mainnet.g.alchemy.com/v2/offline-test'},proof_source={'commit':'test','tree':'test'})
 assert c.source_commit=='test'
 c.probe.close();c.transport.close()
"""
        result=self.command(code);self.assertEqual(result.returncode,0,result.stderr)
    def test_supervisor_deadline_kills_hung_worker_and_setsid_descendant(self):
        # Only the test's internal watchdog clock is shortened. The published
        # loader/CLI still requires 300/180, and this injected run must FAIL.
        code="""import sys,os,socket,json,time,signal
from pathlib import Path
from engineering.solana_capacity.proof_host import install_notifications
s=socket.socket(fileno=int(sys.argv[1]));init=json.loads(s.recv(16384))
(Path(init['group'])/'cgroup.procs').write_text(str(os.getpid()))
install_notifications(s);signal.signal(signal.SIGTERM,signal.SIG_IGN)
pid=os.fork()
if pid==0:
 os.setsid();s.close()
 while True:time.sleep(.02)
(Path(init['output'])/'escaped.pid').write_text(str(pid))
ready=time.monotonic()-init['started']
while True:
 s.send(json.dumps({'kind':'status','ready_elapsed':ready,'reason':None,'counts':{},'shutdown':False}).encode())
 time.sleep(.02)
"""
        contract=load_contract();contract.time=dict(contract.time,total_wall_seconds=4,maximum_startup_seconds=2,
            stop_new_work_at_seconds=2,term_after_shutdown_seconds=.25,kill_after_shutdown_seconds=.5)
        native_popen=subprocess.Popen
        def popen(command,*a,**kw):
            if '--child' in command:command=[sys.executable,'-c',code,command[command.index('--control-fd')+1]]
            return native_popen(command,*a,**kw)
        with tempfile.TemporaryDirectory(prefix='proof-deadline-') as d:
            out=Path(d)/'output';args=Namespace(offline=True,authorized_live_proof=False,env=None,source_commit=None,
                output=str(out),contract=str(CONTRACT_PATH))
            started=time.monotonic()
            with patch('engineering.solana_capacity.pump_pons_proof.subprocess.Popen',popen):self.assertEqual(supervise(args,contract),1)
            self.assertLess(time.monotonic()-started,4)
            result=json.loads((out/'process.json').read_text());self.assertEqual(result['classification'],'FAIL')
            self.assertTrue(result['forced_termination']);self.assertFalse(result['descendants_survived'])
            self.assertEqual(result['network']['kernel_connections'],0)
            escaped=int((out/'escaped.pid').read_text())
            self.assertFalse(Path(f'/proc/{escaped}').exists())
    def kernel_case(self,action):
        import select
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET);pid=os.fork()
            if pid==0:
                parent.close()
                try:install_notifications(child);action(root)
                except BaseException:pass
                finally:os._exit(0)
            child.close();kernel=None;status=None
            try:
                self.assertTrue(select.select([parent],[],[],3)[0]);fd=receive_listener(parent)
                kernel=KernelAdmission(fd,LIMITS,root,offline=True);until=time.monotonic()+3
                while time.monotonic()<until:
                    kernel.service(maximum=32);exited,status=os.waitpid(pid,os.WNOHANG)
                    if exited:break
                    if kernel.reason:os.kill(pid,signal.SIGKILL)
                    time.sleep(.001)
                else:os.kill(pid,signal.SIGKILL);self.fail('independent kernel guard did not terminate')
                return kernel.reason,kernel.network_denied,kernel.writes.writes
            finally:
                parent.close()
                if kernel:kernel.close()
                if status is None:
                    try:os.kill(pid,signal.SIGKILL)
                    except ProcessLookupError:pass
    def test_indirect_sdk_socket_is_denied_by_kernel_offline(self):
        def action(root):socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        reason,denied,_=self.kernel_case(action);self.assertEqual(reason,'offline_network_attempt');self.assertEqual(denied,1)
    def test_production_epoch_and_money_write_is_denied_before_kernel(self):
        with tempfile.TemporaryDirectory() as d:
            sentinel=Path(d)/'preserved-epoch';sentinel.write_bytes(b'$500 original epoch')
            def action(root):sentinel.write_bytes(b'unauthorized replacement')
            reason,_,_=self.kernel_case(action)
            # open(O_TRUNC) itself is a mutation: the write guard must guard
            # opening too. A failure here exposes an actual preservation bug.
            self.assertEqual(sentinel.read_bytes(),b'$500 original epoch')
            self.assertIsNotNone(reason)
    def test_actual_file_write_reservation_is_independent_of_final_stock(self):
        def action(root):
            with (root/'same').open('wb') as f:
                f.write(b'a'*100);f.flush();f.seek(0);f.write(b'b'*100);f.flush()
        reason,_,writes=self.kernel_case(action);self.assertIsNone(reason);self.assertGreaterEqual(writes,8192)
