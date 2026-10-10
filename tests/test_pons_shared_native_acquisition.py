"""Actual Survivor dispatch uses one union and independent native risk owners."""
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
import json
import time
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError,pons_survivor_runtime as runtime
from meme_machine.lanes.pons.pons_quotes import shared_v4_quotes
from meme_machine.runtime.survivor_commit import restore_risk
from tests.lanes.pons import test_pons_finalization as fixture


class TraceRPC(fixture.ExactQuoteRPC):
    provider_fingerprint='offline-native-shared'
    max_response=2_000_000;per_scope=190;limit=200;timeout=1
    def __init__(self,*,proved=False):
        super().__init__();self.used=0;self.counts=Counter();self.gas=1;self.clock=100.;self.top=101
        self.methods=Counter();self.failure=None
        self.shared_quote_resources=(dict(validated=True,provider_fingerprint=self.provider_fingerprint,
            max_response_bytes=self.max_response,max_latency_seconds=.001,max_logical_elements=50,
            max_throughput_cu=2000) if proved else None)
    def verify_chain(self):self.chain_verified=True
    def telemetry(self):return dict(methods=dict(self.methods),physical=len(self.transports))
    def value(self,method,params):
        if self.failure==method:raise BoundaryError('provider_transport_failure')
        if method=='eth_getBlockByNumber':
            n=self.top if params[0]=='latest' else int(params[0],16)
            h=dict(fixture.block_header(n),parentHash=fixture.block_header(n-1)['hash'],timestamp=hex(100))
            return dict(h,hash='fork') if self.fork and params[0]!='latest' else h
        if method=='eth_getLogs':return []
        if method=='eth_gasPrice':return hex(self.gas)
        return super().value(method,params)
    def call(self,method,params,*,scope):
        self.methods[method]+=1;self.used+=1;self.counts[scope]+=1
        self.clock+=.001
        return super().call(method,params,scope=scope)
    def batch(self,calls,*,scope):
        self.methods.update(m for m,p in calls);self.used+=len(calls);self.counts[scope]+=len(calls)
        self.clock+=.001
        values=super().batch(calls,scope=scope)
        return values[:-1] if self.failure=='partial' else values


class SharedNativeAcquisitionTests(unittest.TestCase):
    def run_positions(self,count,*,proved,gas=1,pending=False,predecessor=False,moving_clock=False,before_step=None):
        f=fixture.RuntimeCase();f.setUp();self.addCleanup(f.doCleanups)
        r=f.runtime;self.native_runtime=r
        rpc=TraceRPC(proved=proved);rpc.gas=gas;r.rpc=rpc
        r.now=(lambda:int(rpc.clock)) if moving_clock else (lambda:100)
        for i in range(1,count+1):
            token=fixture.address(i);row=r.history.graduate(token,fixture.graduation(i))
            identity='pons-finalization:position:'+str(i);amount=10**16;qty=10**18+i*10000
            r.sleeve.reserve(identity,strategy=runtime.STRATEGY_VERSION,amount=amount,at=95,asset=token)
            r.book.reserve(identity,amount,95,dict(candidate=token))
            r.book.transition(identity,'filled',96,amount=amount,tokens=qty,evidence=dict(execution=dict(gas=0)))
            r.sleeve.acknowledge_native(identity,basis=amount,pnl=0,at=96,native_hash='offline-native-replay',native_verified=r.book.replay()['verified'])
            row.update(position=identity,state='open',generation=0,block=100,block_hash=rpc.value('eth_getBlockByNumber',['0x64',False])['hash'])
            if pending and i==1:row['position_safety']=dict(pending_exit=True)
            r.history.save(row)
        if before_step is not None:before_step(r,rpc)
        with ExitStack() as stack:
            if predecessor:
                import ast,subprocess
                from meme_machine.lanes.pons import pons_quotes
                baseline=predecessor if isinstance(predecessor,str) else 'e1070404849dfa86eb3e47d57cf24263b2fefc25'
                source=subprocess.check_output(['git','show',baseline+':'+runtime.__name__.replace('.','/')+'.py'])
                cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='Runtime')
                for name in ('_prepare_held_acquisition','exit_quote','validate_exit','step'):
                    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
                    method.decorator_list=[];namespace=dict(vars(runtime))
                    exec(compile(ast.Module(body=[method],type_ignores=[]),'<PR129 predecessor held path>','exec'),namespace)
                    stack.enter_context(patch.object(runtime.Runtime,name,namespace[name]))
                quote_source=subprocess.check_output(['git','show',baseline+':'+pons_quotes.__name__.replace('.','/')+'.py'])
                method=next(n for n in ast.parse(quote_source).body if isinstance(n,ast.FunctionDef) and n.name=='shared_v4_quotes')
                namespace=dict(vars(pons_quotes))
                exec(compile(ast.Module(body=[method],type_ignores=[]),'<PR129 predecessor shared quote>','exec'),namespace)
                stack.enter_context(patch.object(pons_quotes,'shared_v4_quotes',namespace[method.name]))
            stack.enter_context(patch('time.time',side_effect=lambda:rpc.clock))
            stack.enter_context(patch('time.monotonic',side_effect=lambda:rpc.clock))
            stack.enter_context(patch('meme_machine.runtime.storage.compact_survivor'))
            stack.enter_context(patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=rpc))
            wall=time.perf_counter();cpu=time.process_time()
            result=r.step(admit=False)
            rpc.native_completed_at=rpc.clock
            rpc.local_wall_seconds=time.perf_counter()-wall
            rpc.local_cpu_seconds=time.process_time()-cpu
        self.assertFalse(result['deferred_boundaries'],result['deferred_boundaries'])
        self.assertTrue(r.book.replay()['verified']);self.assertTrue(r.sleeve.reconcile()['reconciled'])
        positions=[r.book._load('pons-finalization:position:'+str(i)) for i in range(1,count+1)]
        risks=[restore_risk(r.book,p['id']) for p in positions]
        return positions,risks,rpc,result

    def test_two_native_quiet_survivors_share_quotes_and_complete_history_with_identical_money_and_protection(self):
        old,a,baseline,_=self.run_positions(2,proved=False)
        new,b,optimized,_=self.run_positions(2,proved=True)
        self.assertEqual(old,new);self.assertEqual(a,b)
        self.assertEqual((len(baseline.transports),len(optimized.transports)),(10,3))
        self.assertEqual([m for m,p in optimized.transports[-1][1]],
            ['eth_getBlockByNumber','eth_getBlockByNumber'])
        self.assertIn('eth_getLogs',[m for m,p in optimized.transports[1][1]])
        self.assertEqual(optimized.methods['eth_getLogs'],1)
        simulations=sum(m=='eth_call' and p[0]['data']!=runtime.calldata('poolManager()')
            for kind,rows in optimized.transports for m,p in rows)
        self.assertEqual(simulations,2)
        print('NATIVE_SHARED_TRACE',json.dumps(dict(original_physical=10,optimized_physical=3,
            original_methods=dict(baseline.methods),optimized_methods=dict(optimized.methods),
            traces=optimized.transports)),flush=True)

    def test_twenty_native_positions_share_only_common_acquisition_without_a_position_count_veto(self):
        _,risks,rpc,result=self.run_positions(20,proved=True)
        self.assertEqual(len(rpc.transports),3)
        self.assertTrue(all(r['last_action']['action']=='hold' for r in risks))
        self.assertEqual(result['accounting']['open_positions'],20)
        self.assertEqual(result['admission']['position_count_limit'],None)

    def test_changed_gas_is_acquired_again_and_pending_protection_uses_original_path(self):
        old,a,_,_=self.run_positions(2,proved=False,gas=2)
        new,b,rpc,_=self.run_positions(2,proved=True,gas=2)
        self.assertEqual(old,new);self.assertEqual(a,b)
        before,a,original,_=self.run_positions(2,proved=True,pending=True,
            predecessor='da090e6d080383f0309517a5eb39aa4ead3360e8')
        after,b,rpc,_=self.run_positions(2,proved=True,pending=True)
        self.assertEqual(before,after);self.assertEqual(a,b)
        # The pending owner still completes first. The ordinary cohort then
        # uses its own native frame instead of the repeated private path.
        self.assertEqual((len(original.transports),len(rpc.transports)),(8,6))

    def test_unknown_or_mismatched_resources_refuse_before_any_transport(self):
        rpc=TraceRPC();requests=[dict(key=fixture.PoolKey(**fixture.graduation(i)['key']),
            pool_id=fixture.graduation(i)['transition']['market'],amount=10**18,gas_units=200000) for i in (1,2)]
        with self.assertRaisesRegex(BoundaryError,'unproved'):shared_v4_quotes(rpc,requests)
        self.assertFalse(rpc.transports)
        rpc.shared_quote_resources=dict(validated=True,provider_fingerprint='other')
        with self.assertRaisesRegex(BoundaryError,'unproved'):shared_v4_quotes(rpc,requests)
        self.assertFalse(rpc.transports)

    def test_partial_transport_failure_and_fork_never_publish_shared_quotes(self):
        requests=[dict(key=fixture.PoolKey(**fixture.graduation(i)['key']),
            pool_id=fixture.graduation(i)['transition']['market'],amount=10**18,gas_units=200000) for i in (1,2)]
        for failure in ('partial','eth_call','fork'):
            rpc=TraceRPC(proved=True);rpc.failure=failure;rpc.fork=failure=='fork'
            with patch('time.time',side_effect=lambda:rpc.clock),patch('time.monotonic',side_effect=lambda:rpc.clock):
                with self.assertRaises(BoundaryError):shared_v4_quotes(rpc,requests)
