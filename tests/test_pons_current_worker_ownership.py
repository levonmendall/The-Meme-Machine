"""Native durable ownership outlives physical Current worker occupancy."""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import os
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch,MagicMock

from meme_machine.lanes.pons import pons_selective_paper as paper
from meme_machine.lanes.pons import pons_selective_recovery as recovery
from meme_machine.lanes.pons.pons_current_workers import LifecyclePool
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
from tests import test_pons_ongoing_scale as fixture


class CurrentWorkerOwnershipTests(unittest.TestCase):
    def wait_for(self,predicate):
        limit=time.monotonic()+15
        while not predicate():
            if time.monotonic()>=limit:self.fail('native controller worker did not reach its durable wait')
            time.sleep(.005)

    def test_twenty_new_native_entries_transfer_to_protected_owners_without_repeat_provider_purchases(self):
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        from tests.lanes.pons.test_pons_position_provider_recovery import PositionRecoveryTests
        from meme_machine.runtime.execution_capacity import resize
        from meme_machine.lanes.pons.evidence import Store
        quote=PartialAccountingTests().quote;providers=[]
        def provider(*args):
            from meme_machine.runtime.provider_purchases import work_label
            from meme_machine.lanes.pons.provider_admission import priority
            self.assertEqual(work_label()['operation'],'pons_current_qualification')
            self.assertEqual(priority('pons_paper'),5)
            rpc=MagicMock();rpc.used=0;rpc.telemetry.return_value={};providers.append(rpc);return rpc
        def buy(*args,**kw):return replace(quote(102,'buy',100,1000),market=args[1]['curve']),dict(block=102,block_hash='h102',event_at=102),None
        with tempfile.TemporaryDirectory() as td,ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ,{},clear=True))
            patches=dict(paper_rpc=provider,_gas_quote=lambda *a:(2,1),
                _entry_capacity=lambda *a:resize(100,1,lambda n:100,ordinary_limit=600),
                _wait_curve_quote=buy,_stop_sleep=lambda *a:None,
                _refresh_entry_persistence_signal=PositionRecoveryTests.persistent_entry_signal,
                _validate_final_entry=lambda *a:None,_confirm_entry_delta=lambda *a:(a[5],[],{}),
                _fresh_fill_full_exit_check=lambda *a:dict(executable=True))
            for name,value in patches.items():stack.enter_context(patch.object(paper,name,side_effect=value))
            stack.enter_context(patch.object(paper.time,'time',return_value=102))
            with LifecyclePool(max_workers=8) as pool:
                futures=[]
                for i in range(20):
                    state=MagicMock();state.buy_with_snipe.return_value=dict(refund=0,ready_to_graduate=False,tokens_out=1000)
                    evaluation=dict(vector=dict(current_threshold_pass=True,policy_hash=POLICY_HASH,
                        proposed_size={'amount_quote':100},evidence_available_at=100,
                        trajectory={'graduation_eta_seconds':100},demand={'largest_buyer_flow_bps':100}),
                        candidate=dict(receipt={'gasUsed':hex(21000)},curve='m'+str(i),state=state,
                            report={},token='token'+str(i),record={},auth={}),
                        token='token'+str(i),curve='m'+str(i),source_transaction='source'+str(i),market_events=[])
                    self.wait_for(pool.entry_capacity_available)
                    futures.append(pool.submit(paper.run_lifecycle,'unused',evaluation,db_path=Path(td)/('native-'+str(i)+'.sqlite')))
                def ready():
                    for future in futures:
                        if future.done():self.fail('new native owner ended: '+repr(future.exception() or future.result()))
                    state=pool.telemetry()
                    return state['entry_owner_handoffs']==20 and state['active_physical_workers']==0 and state['entry_tasks']==0
                self.wait_for(ready)
                self.assertEqual(len(providers),20)
                self.assertEqual(sum(p.verify_chain.call_count for p in providers),20)
                self.assertTrue(all(not f.done() for f in futures))
                self.assertTrue(pool.entry_capacity_available())
                telemetry=pool.telemetry()
                self.assertLessEqual(telemetry['peak_physical_workers'],8)
                self.assertLessEqual(telemetry['peak_entry_workers'],8)
                self.assertEqual(telemetry['total_physical_worker_limit'],16)
                pool.request_handoff()
                results=[f.result(timeout=15) for f in futures]
                for result in results:
                    self.assertEqual(result['status'],'handoff_required')
                    self.assertFalse(result['entry_authority'])
                    self.assertEqual(result['qualification_vector']['proposed_size']['amount_quote'],100)
                    self.assertTrue(result['reconciliation']['cash_basis_conservation'])
                    p=result['final_position'];self.assertEqual(p['entry_tokens'],1000);self.assertEqual(p['tokens'],1000)
                    self.assertEqual(p['realized_pnl'],0)
                    self.assertEqual(p['controller_state']['opened_at'],102)
                    self.assertEqual(p['controller_state']['high_water'],-10**9)
                self.assertEqual(len(providers),20)
                self.assertEqual(sum(p.verify_chain.call_count for p in providers),20)

    def test_blocked_entry_never_occupies_a_due_protection_worker(self):
        started=threading.Event();owner_ready=threading.Event();release=threading.Event();trace=[];clock=[0.]
        def protect(*args,**kw):
            owner_ready.set()
            command=yield dict(kind='monitor_wait',seconds=5,position='native',pending_exit=True)
            if command=='handoff':return dict(status='handoff_required')
            trace.append(clock[0])
            yield dict(kind='monitor_wait',seconds=5,position='native',pending_exit=True)
            return dict(status='handoff_required')
        def entry(*args,**kw):
            started.set();release.wait(10)
            return dict(status='entry_failed')
            yield
        with patch.object(recovery,'_resume_receipt_steps',side_effect=protect),\
             patch.object(paper,'run_lifecycle_steps',side_effect=entry),LifecyclePool(max_workers=1,clock=lambda:clock[0]) as pool:
            held=pool.submit(recovery._resume_receipt,'unused',None,None)
            self.wait_for(lambda:owner_ready.is_set() and pool.telemetry()['active_physical_workers']==0)
            queued=pool.submit(paper.run_lifecycle,'unused',{})
            try:
                self.assertTrue(started.wait(5));clock[0]=5
                with pool.lock:pool.lock.notify_all()
                self.wait_for(lambda:trace==[5])
                self.assertFalse(queued.done());self.assertFalse(held.done())
                self.assertEqual(pool.telemetry()['max_queue_age_seconds'],0)
                self.assertEqual(pool.telemetry()['peak_entry_workers'],1)
            finally:release.set()
            self.assertEqual(queued.result(timeout=5)['status'],'entry_failed')

    def test_native_handoff_does_not_restart_the_initial_monitor_clock(self):
        clock=[100.];trace=[]
        def entry(*args,**kw):
            command=yield dict(kind='monitor_wait',seconds=5,position='native',pending_exit=False,
                continued_session=dict(position='native',endpoint='unused',rpc=object()))
            self.assertEqual(command,'handoff');clock[0]+=3
            return dict(status='handoff_required',final_position={'id':'native'})
        def recovered(*args,**kw):
            self.assertEqual(kw['_first_monitor_due'],105);clock[0]+=2
            command=yield dict(kind='monitor_wait',seconds=5,due_at=kw['_first_monitor_due'],pending_exit=False)
            if command=='handoff':return dict(status='handoff_required')
            trace.append(clock[0])
            yield dict(kind='monitor_wait',seconds=5,pending_exit=False)
            return dict(status='handoff_required')
        with patch.object(paper,'run_lifecycle_steps',side_effect=entry),\
             patch.object(recovery,'resume_lifecycle_steps',side_effect=recovered),LifecyclePool(max_workers=1,clock=lambda:clock[0]) as pool:
            future=pool.submit(paper.run_lifecycle,'unused',{},db_path='offline-native')
            self.wait_for(lambda:trace==[105])
            self.assertFalse(future.done());self.assertEqual(pool.telemetry()['entry_owner_handoffs'],1)
            self.assertEqual(pool.telemetry()['max_queue_age_seconds'],0)

    def test_shutdown_keeps_protection_workers_until_inflight_entry_handoff_completes(self):
        started=threading.Event();release=threading.Event();owned=threading.Event()
        def protect(*args,**kw):
            yield dict(kind='monitor_wait',seconds=5,pending_exit=False)
            return dict(status='handoff_required')
        def entry(*args,**kw):
            started.set();release.wait(10)
            yield dict(kind='monitor_wait',seconds=5,pending_exit=False,
                continued_session=dict(position='new',endpoint='unused',rpc=object()))
            return dict(status='handoff_required',final_position={'id':'new'})
        def recovered(*args,**kw):
            owned.set()
            yield dict(kind='monitor_wait',seconds=5,pending_exit=False,due_at=kw['_first_monitor_due'])
            return dict(status='handoff_required')
        with patch.object(recovery,'_resume_receipt_steps',side_effect=protect),\
             patch.object(paper,'run_lifecycle_steps',side_effect=entry),\
             patch.object(recovery,'resume_lifecycle_steps',side_effect=recovered),LifecyclePool(max_workers=1) as pool:
            old=pool.submit(recovery._resume_receipt,'unused',None,None)
            self.wait_for(lambda:pool.telemetry()['active_physical_workers']==0)
            new=pool.submit(paper.run_lifecycle,'unused',{},db_path='offline-native')
            try:
                self.assertTrue(started.wait(5));pool.request_handoff()
                self.assertEqual(old.result(timeout=5)['status'],'handoff_required')
            finally:release.set()
            self.assertEqual(new.result(timeout=5)['status'],'handoff_required')
            self.assertTrue(owned.is_set());self.assertEqual(pool.telemetry()['entry_owner_handoffs'],1)

    def test_twenty_native_recovered_owners_share_eight_workers_without_reentry_or_extra_chain_checks(self):
        natives=[];calls=[]
        for i in range(20):
            from meme_machine.lanes.pons.evidence import Store
            from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
            from meme_machine.lanes.pons.pons_selective_continuation import EXIT_POLICY
            from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
            tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
            store=Store(Path(tmp.name)/'native.sqlite');identity=f'pons:winner:{i}';market=f'curve-{i}'
            book=SelectivePaper(store,STRATEGY_NAMESPACE,100000,
                delay=EXIT_POLICY['entry_delay_seconds'],natural_policy_hash=POLICY_HASH)
            native_quote=PartialAccountingTests().quote
            book.reserve(identity,market=market,amount=5000,gas_budget=2,now=100,
                features=dict(PartialAccountingTests().features(100),market=market))
            candidate=dict(token=f'token-{i}',curve=market,auth={'valid':True},record={})
            evaluation=dict(token=candidate['token'],curve=market,source_transaction=f'tx-{i}',
                candidate=candidate,vector=dict(current_threshold_pass=True,policy_hash=POLICY_HASH,
                    trajectory={'graduation_eta_seconds':100},demand={'largest_buyer_flow_bps':3000}),market_events=[])
            state=recovery.LifecycleState.create(store,identity,evaluation,100000,1,opened_at=102,last_block=1)
            book.controller_context=state.checkpoint
            book.advance(identity,now=102,action='entry',quote=replace(native_quote(102,'buy',5000,1000),market=market))
            state.partial_taken=True;state.high_water=10000;state.first_tail_crossed_at=103
            book.advance(identity,now=103,action='exit_intent',exit_tokens=250)
            before=book.advance(identity,now=105,action='exit',quote=replace(native_quote(105,'sell',250,2000),market=market))
            natives.append(SimpleNamespace(identity=identity,temp=tmp,before=before));store.close()
        rpc=MagicMock();rpc.used=0;rpc.telemetry.return_value={}
        def provider(*a):calls.append(threading.get_ident());return rpc
        with patch.object(paper,'paper_rpc',side_effect=provider),LifecyclePool(max_workers=8) as pool:
            futures=[pool.submit(recovery._resume_receipt,'offline',None,
                (i,Path(n.temp.name)/'native.sqlite',dict(curve=f'curve-{i}',token='token',source_transaction='tx'),None))
                for i,n in enumerate(natives)]
            def ready():
                for future in futures:
                    if future.done():self.fail('controller ended before its wait: '+repr(future.exception() or future.result()))
                return pool.telemetry()['owners']==20 and pool.telemetry()['active_physical_workers']==0 and len(calls)==20
            self.wait_for(ready)
            self.assertTrue(pool.entry_capacity_available())
            self.assertTrue(all(not f.done() for f in futures))
            self.assertLessEqual(len(set(calls)),8)
            self.assertEqual(rpc.verify_chain.call_count,20)
            pool.request_handoff()
            results=[f.result(timeout=15) for f in futures]
            for result,native in zip(results,natives):
                self.assertEqual(result['status'],'handoff_required')
                self.assertFalse(result['entry_authority'])
                p=result['final_position'];self.assertEqual(p['id'],native.identity)
                for name in ('tokens','entry_tokens','remaining_cost','realized_pnl','original_basis','version'):
                    self.assertEqual(p[name],native.before[name])
                self.assertEqual(p['controller_state']['opened_at'],102)
                self.assertTrue(p['controller_state']['partial_taken'])
                self.assertEqual(p['controller_state']['high_water'],10000)
                self.assertEqual(len(result['reconciliation']['accounting']),1)
                self.assertTrue(result['reconciliation']['cash_basis_conservation'])
            self.assertEqual(len(calls),20)
            self.assertEqual(rpc.verify_chain.call_count,20)
            self.assertEqual(pool.telemetry()['peak_owners'],20)
            self.assertLessEqual(pool.telemetry()['peak_physical_workers'],8)

    def test_idle_native_owners_keep_the_same_thread_context_and_ordered_protection_before_entry(self):
        # Exercise the scheduler boundary directly; native entry/recovery above
        # proves the real generator and durable monetary state, independently.
        trace=[];local=threading.local();clock=[0.]
        from contextvars import ContextVar
        own=ContextVar('test_current_owner',default=None)
        def steps(*args,**kw):
            identity=args[0];own.set(identity);thread=threading.get_ident()
            local.token=identity
            trace.append(('start',identity,thread))
            value=yield dict(kind='monitor_wait',seconds=5,position=identity,pending_exit=identity=='exit')
            self.assertEqual(own.get(),identity);self.assertEqual(threading.get_ident(),thread)
            if value=='handoff':return dict(status='handoff_required')
            trace.append(('protect',identity,thread))
            yield dict(kind='monitor_wait',seconds=5,position=identity,pending_exit=False)
            return dict(status='handoff_required')
        with patch.object(recovery,'_resume_receipt_steps',side_effect=steps),LifecyclePool(max_workers=1,clock=lambda:clock[0]) as pool:
            a=pool.submit(recovery._resume_receipt,'exit',None,None);self.wait_for(lambda:len(trace)==1 and pool.entries==0)
            b=pool.submit(recovery._resume_receipt,'hold',None,None);self.wait_for(lambda:len(trace)==2 and pool.entries==0)
            self.assertTrue(pool.entry_capacity_available());clock[0]=5
            with pool.lock:pool.lock.notify_all()
            self.wait_for(lambda:len(trace)==4)
            self.assertEqual([r[:2] for r in trace[2:]],[('protect','exit'),('protect','hold')])
            self.assertFalse(a.done());self.assertFalse(b.done())
            pool.request_handoff();self.assertEqual(a.result(timeout=5)['status'],'handoff_required')
            self.assertEqual(b.result(timeout=5)['status'],'handoff_required')
