"""Whole native Current owners consume a shared quote and authenticated delta."""
from contextlib import ExitStack
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import pons_selective_paper as paper
from meme_machine.lanes.pons import pons_selective_recovery as recovery
from meme_machine.lanes.pons.pons_current_history import CurrentHistory
from meme_machine.lanes.pons.pons_current_workers import LifecyclePool
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH,EXIT_POLICY
from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
from meme_machine.lanes.pons.evidence import Store
from meme_machine.runtime.robinhood.plane import Plane
from tests.lanes.pons import test_pons_partial_accounting as accounting
from tests.lanes.pons import test_pons_finalization as native
from tests.test_pons_protective_capacity import ActiveRPC


class CurrentSharedOwnerTests(unittest.TestCase):
    def wait_for(self,predicate):
        until=time.perf_counter()+15
        while not predicate():
            if time.perf_counter()>until:self.fail('Current native owners failed to reach a bounded scheduling boundary')
            time.sleep(.002)

    def run_owners(self,count,*,sharing,stagger=False,paced=False,latency=0,failure=None,unavailable=False,advertised_latency=None,
                   price_factor=1.,rps=2,exit_sharing=True,survivor_count=0,allow_capacity_refusal=False,
                   exit_transport_failure=False,real_time=False):
        quote=accounting.PartialAccountingTests().quote;clock=[100.];sessions=[];thread_sessions={};events=[]
        real_origin=[None]
        def now_clock():
            return clock[0]+(time.perf_counter()-real_origin[0] if real_time and real_origin[0] is not None else 0)
        with tempfile.TemporaryDirectory() as td,ExitStack() as stack:
            root=Path(td);plane_path=root/'candidate-evidence.sqlite'
            stack.enter_context(patch.dict(os.environ,{},clear=True))
            original_init=SelectivePaper.__init__
            original_advance=SelectivePaper.advance
            def trace_native(book,identity,**kwargs):
                result=original_advance(book,identity,**kwargs)
                if now_clock()>=105:events.append(dict(identity=identity,action=kwargs['action'],
                    completed_monotonic=now_clock(),tokens=result['tokens'],status=result['status']))
                return result
            stack.enter_context(patch.object(SelectivePaper,'advance',trace_native))
            def deterministic_clock(book,*args,**kwargs):
                kwargs.setdefault('clock_ns',lambda:int(now_clock()*10**9))
                return original_init(book,*args,**kwargs)
            stack.enter_context(patch.object(SelectivePaper,'__init__',deterministic_clock))
            plane=Plane(plane_path);history=CurrentHistory(plane,native.ENDPOINT)
            paths=[]
            for i in range(1,count+1):
                identity='current:owner:'+str(i);curve=native.address(100+i);market=native.graduation(i)['transition']['market']
                path=root/('trial-'+str(i)+'.sqlite');paths.append(path)
                store=Store(path);book=SelectivePaper(store,STRATEGY_NAMESPACE,10**18,
                    delay=EXIT_POLICY['entry_delay_seconds'],natural_policy_hash=POLICY_HASH)
                book.reserve(identity,market=curve,amount=10**16,gas_budget=2,now=90,
                    features=dict(accounting.PartialAccountingTests().features(90),market=curve))
                evaluation=dict(token=native.address(i),curve=curve,source_transaction='source:'+str(i),
                    candidate=dict(token=native.address(i),curve=curve,auth={'valid':True},record={}),
                    vector=dict(current_threshold_pass=True,policy_hash=POLICY_HASH,
                        trajectory={'graduation_eta_seconds':100},demand={'largest_buyer_flow_bps':3000}),
                    # Recovery rebinds this original locator to the local Plane;
                    # equal immutable bases must not hash different temp names.
                    market_events=[],candidate_plane_path='original/candidate-evidence.sqlite',
                    candidate_broker_identity='candidate:'+str(i))
                state=recovery.LifecycleState.create(store,identity,evaluation,10**18,200000,opened_at=96,last_block=100)
                book.controller_context=state.checkpoint
                book.advance(identity,now=96,action='entry',quote=replace(quote(96,'buy',10**16,10**18+i*10000),market=curve))
                from meme_machine.lanes.pons.protocols import PoolKey
                state.v4_key=PoolKey(**native.graduation(i)['key'])
                state.transition=dict(previous_market=curve,market=market,proof_hash='graduation:'+str(i))
                state.graduation_at=50;state.graduation_block=50;state.post_grad_checked=True
                store.put('graduation',state.transition['proof_hash'],state.transition)
                book.advance(identity,now=97,action='transition',transition=state.transition)
                header=dict(native.block_header(100),timestamp=hex(100))
                history.remember(market,header,[],from_time=0)
                self.assertTrue(book.reconcile()['cash_basis_conservation']);store.close()
            plane.close()
            transport_lock=threading.RLock()
            class ClockRPC(ActiveRPC):
                @property
                def clock(self):return now_clock()
                @clock.setter
                def clock(self,value):
                    if not real_time:clock[0]=value
                def sleep(self,seconds):
                    if real_time:time.sleep(seconds)
                    else:super().sleep(seconds)
                def purchase(self,*args,**kwargs):
                    if real_time:return super().purchase(*args,**kwargs)
                    with transport_lock:return super().purchase(*args,**kwargs)
                def value(self,method,params):
                    result=super().value(method,params)
                    if ((survivor_count or real_time) and method=='eth_getBlockByNumber' and result['number']=='0x65'):
                        # One fixed canonical market frontier at the common
                        # due instant, never renewed during execution.
                        result['timestamp']=hex(105)
                    return result
            def provider(endpoint):
                rpc=(ClockRPC if paced or latency or real_time else ActiveRPC)(
                    proved=sharing,count=count,paced=paced,latency=latency,
                    admission_path=str(root/'provider.sqlite'),price_factor=price_factor,rps=rps)
                rpc.real_latency=real_time
                if advertised_latency is not None:
                    rpc.shared_quote_resources['max_latency_seconds']=advertised_latency
                if failure=='fork':rpc.fork=True
                elif failure:rpc.failure=failure
                if exit_transport_failure:
                    batch=rpc.batch
                    def failed_exit(calls,**kwargs):
                        if now_clock()>=107:rpc.failure='eth_call'
                        return batch(calls,**kwargs)
                    rpc.batch=failed_exit
                sessions.append(rpc);thread_sessions[threading.get_ident()]=rpc
                self.addCleanup(rpc.close);return rpc
            stack.enter_context(patch.object(paper,'paper_rpc',side_effect=provider))
            if not exit_sharing:
                stack.enter_context(patch('meme_machine.lanes.pons.pons_current_workers.exit_acquisition_request',return_value=None))
            stack.enter_context(patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',
                side_effect=lambda *a,**kw:thread_sessions[threading.get_ident()]))
            stack.enter_context(patch.object(paper.time,'time',side_effect=now_clock))
            stack.enter_context(patch.object(paper.time,'monotonic',side_effect=now_clock))
            native_steps=recovery._resume_receipt_steps
            def one_turn(*args,**kwargs):
                # Bound the fixture to one actual native turn per recovered
                # owner. Finish its original delayed exit too; then perform the
                # existing durable handoff instead of starting another cycle.
                steps=native_steps(*args,**kwargs);monitored=False
                try:
                    wait=next(steps)
                    while True:
                        if wait['kind']=='monitor_wait':
                            if monitored:
                                try:steps.send('handoff')
                                except StopIteration as done:return done.value
                                raise AssertionError('native handoff did not finish')
                            monitored=True
                        command=yield wait
                        try:wait=steps.send(command)
                        except StopIteration as done:return done.value
                finally:steps.close()
            stack.enter_context(patch.object(recovery,'_resume_receipt_steps',one_turn))
            survivor_ready=threading.Event();survivor_due=threading.Event();survivor_done=threading.Event();mixed={}
            def survivor_turn():
                # Own native connections stay on this thread. Share only the
                # physical account admission and mock endpoint, not books.
                from meme_machine.lanes.pons import pons_survivor_runtime as survivor
                from meme_machine.runtime.survivor_commit import restore_risk
                r=None
                try:
                    with patch.dict(os.environ,dict(MM_DIRECTIONAL_SLEEVE_DB=str(root/'survivor-sleeve'),
                            MM_DIRECTIONAL_COHORT_ID='mixed-survivor')):
                        r=survivor.Runtime(root/'survivor',10**18,'mixed-survivor',native.ENDPOINT)
                    r.rpc=provider(native.ENDPOINT);r.deployments_verified=True;r.now=lambda:int(now_clock())
                    r.rpc.fixture_consumer='survivor';mixed['native_events']=[]
                    for i in range(1,survivor_count+1):
                        token=native.address(i);row=r.history.graduate(token,native.graduation(i))
                        identity='mixed-survivor:position:'+str(i);amount=10**16;qty=10**18+i*10000
                        r.sleeve.reserve(identity,strategy=survivor.STRATEGY_VERSION,amount=amount,at=95,asset=token)
                        r.book.reserve(identity,amount,95,dict(candidate=token))
                        r.book.transition(identity,'filled',96,amount=amount,tokens=qty,evidence=dict(execution=dict(gas=0)))
                        r.sleeve.acknowledge_native(identity,basis=amount,pnl=0,at=96,native_hash='offline-native-replay',
                            native_verified=r.book.replay()['verified'])
                        row.update(position=identity,state='open',generation=0,block=100,
                            block_hash=r.rpc.value('eth_getBlockByNumber',['0x64',False])['hash']);r.history.save(row)
                    transition=r.book.transition
                    def trace_transition(identity,action,*args,**kwargs):
                        result=transition(identity,action,*args,**kwargs)
                        mixed['native_events'].append(dict(identity=identity,action=action,completed_monotonic=now_clock()))
                        return result
                    r.book.transition=trace_transition
                    survivor_ready.set();survivor_due.wait(20)
                    mixed['first_required_at']=105.;mixed['started_at']=now_clock()
                    with patch('meme_machine.runtime.storage.compact_survivor'):
                        result=r.step(admit=False)
                    mixed.update(completed_at=now_clock(),result=result,
                        positions=[r.book._load('mixed-survivor:position:'+str(i)) for i in range(1,survivor_count+1)])
                    mixed['risks']=[restore_risk(r.book,p['id']) for p in mixed['positions']]
                    mixed['native_accounting_verified']=r.book.replay()['verified'] and r.sleeve.reconcile()['reconciled']
                except BaseException as exc:mixed['error']=repr(exc);survivor_ready.set()
                finally:
                    if r is not None:r.close()
                    survivor_done.set()
            mixed_thread=None
            if survivor_count:
                mixed_thread=threading.Thread(target=survivor_turn,name='native-mixed-survivor')
                mixed_thread.start();self.assertTrue(survivor_ready.wait(15),mixed)
                self.assertNotIn('error',mixed)
            with LifecyclePool(max_workers=8,clock=now_clock) as pool:
                futures=[pool.submit(recovery._resume_receipt,native.ENDPOINT,None,
                    (i,path,dict(curve=native.address(101+i),token=native.address(i+1),source_transaction='source'),None))
                    for i,path in enumerate(paths)]
                def waiting():
                    for f in futures:
                        if f.done():
                            error=f.exception()
                            raise AssertionError('native recovery terminated: '+repr(error or f.result())) from error
                    return pool.telemetry()['active_physical_workers']==0 and len(sessions)==count+bool(survivor_count)
                self.wait_for(waiting)
                turn_wall=time.perf_counter();turn_cpu=time.process_time()
                if stagger:
                    with pool.lock:
                        for worker in pool.workers:
                            rows=[]
                            for row in worker['queue']:
                                owner=row[3];owner['due']+=owner['sequence']*.1
                                rows.append((owner['due'],row[1],row[2],owner))
                            import heapq
                            worker['queue']=rows;heapq.heapify(worker['queue'])
                    clock[0]=105.1
                else:
                    clock[0]=105
                if real_time:real_origin[0]=time.perf_counter()
                survivor_due.set()
                with pool.lock:pool.lock.notify_all()
                # Advance only to the next native due boundary, never rewind
                # after a paced acquisition or hold an already-due request.
                until=time.perf_counter()+20
                while not (all(f.done() for f in futures) and (not survivor_count or survivor_done.is_set())):
                    if time.perf_counter()>until:self.fail('bounded native Current turn did not finish')
                    with pool.lock:
                        if not real_time and pool.counts['active_physical_workers']==0 and (not survivor_count or survivor_done.is_set()):
                            dues=[row[0] for worker in pool.workers for row in worker['queue']]
                            if dues:clock[0]=max(clock[0],min(dues));pool.lock.notify_all()
                    time.sleep(.002)
                telemetry=pool.telemetry()
                telemetry.update(native_local_wall_seconds=time.perf_counter()-turn_wall,
                    native_cpu_seconds=time.process_time()-turn_cpu)
                pool.request_handoff()
                results=[f.result(timeout=15) for f in futures]
                for result in results:
                    capacity_refusal=allow_capacity_refusal and result['final_position']['status']=='exit_pending'
                    self.assertEqual(result['status'],'settled' if price_factor==.6 and not unavailable and not capacity_refusal else 'handoff_required',result.get('boundary'))
                    self.assertTrue(result['reconciliation']['cash_basis_conservation'])
                    if capacity_refusal:
                        self.assertTrue(result['final_position']['pending_exit_tokens']>0)
                        self.assertTrue(result['provider_recoveries'])
                        self.assertEqual(len(result['monitor']),2)
                        self.assertFalse(result['monitor'][1]['available'])
                        self.assertTrue(result['monitor'][1]['provider_recovery'])
                    else:self.assertEqual(len(result['monitor']),1,result)
                    if failure or unavailable:
                        self.assertFalse(result['monitor'][0]['available'])
                    else:self.assertEqual(result['monitor'][0]['action']['action'],
                        'hold' if price_factor==1 else ('full_exit' if price_factor==.6 else 'partial_exit'))
                    if price_factor==1:self.assertEqual(result['final_position']['tokens'],result['final_position']['entry_tokens'])
            plane=Plane(plane_path);history=CurrentHistory(plane,native.ENDPOINT)
            for i in range(1,count+1):
                row=history.get(native.graduation(i)['transition']['market'])
                if failure=='fork':self.assertIsNone(row)
                elif failure or unavailable:self.assertEqual(row['block'],100)
                else:
                    self.assertEqual(row['block'],101);self.assertEqual(row['last_interval']['event_count'],1)
            plane.close()
            if mixed_thread is not None:
                mixed_thread.join(15);self.assertFalse(mixed_thread.is_alive());self.assertNotIn('error',mixed)
                self.assertTrue(mixed['native_accounting_verified'])
                telemetry['mixed_survivor']=mixed
            telemetry['complete_modeled_seconds']=now_clock()-105
            telemetry['native_events']=events
            telemetry['real_clock_with_injected_transport_sleep']=real_time
            telemetry['complete_modeled_with_local_seconds']=(telemetry['complete_modeled_seconds']+
                (0 if real_time else telemetry['native_local_wall_seconds']))
            return results,sessions,telemetry

    def test_whole_native_two_current_owners_share_history_quotes_and_preserve_each_ledger(self):
        old,baseline,_=self.run_owners(2,sharing=False)
        new,optimized,t=self.run_owners(2,sharing=True)
        for a,b in zip(old,new):
            self.assertEqual(a['final_position'],b['final_position'])
            self.assertEqual(a['reconciliation'],b['reconciliation'])
            self.assertEqual(a['monitor'][0]['action'],b['monitor'][0]['action'])
            self.assertEqual(a['monitor'][0]['activity']['swaps'],b['monitor'][0]['activity']['swaps'])
        before=sum(len(r.transports) for r in baseline);after=sum(len(r.transports) for r in optimized)
        self.assertEqual(t['shared_consumers'],2);self.assertEqual(after,4)
        self.assertGreater(before,after)
        print('NATIVE_CURRENT_SHARED_OWNERS',json.dumps(dict(positions=2,before=before,after=after,
            worker=t,traces=[r.transports for r in optimized if r.transports])),flush=True)

    def test_four_eight_twenty_whole_current_owners_keep_eight_native_workers(self):
        for count in (4,8,20):
            with self.subTest(positions=count):
                results,rpcs,t=self.run_owners(count,sharing=True)
                self.assertEqual(sum(len(r.transports) for r in rpcs),4)
                self.assertEqual(t['shared_consumers'],count)
                self.assertLessEqual(t['peak_physical_workers'],8)
                self.assertEqual(t['shared_failures'],0)
                self.assertEqual(len(results),count)

    def test_adversarial_stagger_never_waits_to_create_a_cohort(self):
        _,rpcs,t=self.run_owners(4,sharing=True,stagger=True)
        self.assertEqual(t['shared_acquisitions'],0)
        self.assertGreater(sum(len(r.transports) for r in rpcs),4)

    def test_actual_admission_and_responses_finish_twenty_current_decisions_within_five_seconds(self):
        results,rpcs,t=self.run_owners(20,sharing=True,paced=True,latency=.1)
        self.assertEqual(sum(len(r.transports) for r in rpcs),4)
        self.assertLess(t['complete_modeled_seconds'],5)
        self.assertLess(t['complete_modeled_with_local_seconds'],5)
        self.assertEqual(t['shared_failures'],0)
        starts=[s for r in rpcs for s in r.starts]
        self.assertEqual(starts,[105,105.5,106,106.5])
        self.assertTrue(all(r['monitor'][0]['available'] for r in results))
        print('NATIVE_CURRENT_ADMISSION_ENVELOPE',json.dumps(dict(worker=t,starts=starts,
            responses=[s for r in rpcs for s in r.responses],modeled_http_rtt=.1)),flush=True)

    def test_failed_partial_and_reorganized_batches_preserve_native_owners_and_accounting(self):
        for fault in ('partial','eth_call','fork'):
            with self.subTest(fault=fault):
                results,_,t=self.run_owners(2,sharing=True,failure=fault)
                self.assertEqual(t['shared_failures'],1)
                self.assertTrue(all(r['final_position']['status']=='open' for r in results))
                self.assertTrue(all(r['reconciliation']['cash_basis_conservation'] for r in results))

    def test_slow_provider_refuses_late_shared_quotes_without_settlement_or_owner_loss(self):
        results,_,t=self.run_owners(2,sharing=True,paced=True,latency=2,unavailable=True,advertised_latency=.1)
        self.assertEqual(t['shared_failures'],1)
        self.assertGreater(t['complete_modeled_seconds'],5)
        self.assertTrue(all(r['final_position']['status']=='open' for r in results))
        self.assertTrue(all(r['reconciliation']['cash_basis_conservation'] for r in results))
