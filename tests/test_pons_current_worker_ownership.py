"""Native durable ownership outlives physical Current worker occupancy."""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
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
        with patch.object(paper,'run_lifecycle_steps',side_effect=steps),LifecyclePool(max_workers=1,clock=lambda:clock[0]) as pool:
            a=pool.submit(paper.run_lifecycle,'exit',{});self.wait_for(lambda:len(trace)==1 and pool.entries==0)
            b=pool.submit(paper.run_lifecycle,'hold',{});self.wait_for(lambda:len(trace)==2 and pool.entries==0)
            self.assertTrue(pool.entry_capacity_available());clock[0]=5
            with pool.lock:pool.lock.notify_all()
            self.wait_for(lambda:len(trace)==4)
            self.assertEqual([r[:2] for r in trace[2:]],[('protect','exit'),('protect','hold')])
            self.assertFalse(a.done());self.assertFalse(b.done())
            pool.request_handoff();self.assertEqual(a.result(timeout=5)['status'],'handoff_required')
            self.assertEqual(b.result(timeout=5)['status'],'handoff_required')
