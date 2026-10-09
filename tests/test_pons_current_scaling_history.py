"""Native Current scaling consumes retained authenticated history, not a new window."""
import ast
from collections import Counter
from copy import deepcopy
from dataclasses import asdict,replace
import json
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch
import unittest

from meme_machine.lanes.pons import BoundaryError,pons_selective_paper as paper
from meme_machine.lanes.pons import pons_selective_v4 as v4
from meme_machine.lanes.pons.pons_current_history import CurrentHistory,_active
from meme_machine.lanes.pons.pons_selective_continuation import ongoing_scale_requalification
from meme_machine.runtime.robinhood.plane import Plane
from meme_machine.runtime.cu import estimate
from tests.test_pons_dense_v4_receipts import fixture,ENDPOINT
from tests import test_pons_ongoing_scale as scale_fixture

BASE='cd1c16c4e867b8121e6ff8a8b02b6759ca46bef2'


def original_reader():
    source=subprocess.check_output(['git','show',BASE+':meme_machine/lanes/pons/pons_selective_paper.py'],text=True)
    fn=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_ongoing_scale_evidence')
    namespace=dict(paper.__dict__)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<original-current-scale>','exec'),namespace)
    return namespace['_ongoing_scale_evidence']


class CurrentScalingHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tape,self.context,opts=fixture(relevant=25,total=40)
        self.key=opts['key'];self.pool=opts['pool_id'];self.token=opts['token']
        self.top=opts['end_block'];old=self.tape.header
        self.tape.header=lambda n:dict(old(n),timestamp=hex(max(0,2000+n-self.top)))
        from meme_machine.lanes.pons.pons_selective_recovery import LifecycleState
        create=LifecycleState.create
        def authentic_create(store,identity,evaluation,*args,**kwargs):
            evaluation=deepcopy(evaluation)
            evaluation['candidate']['token']=self.token;evaluation['token']=self.token
            return create(store,identity,evaluation,*args,**kwargs)
        self.native=scale_fixture.ScaleIntegrationTests()
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        reserve=SelectivePaper.reserve;quote=PartialAccountingTests.quote
        def native_reserve(book,*args,**kwargs):
            kwargs['market']=self.pool;kwargs['features']=dict(kwargs['features'],market=self.pool)
            return reserve(book,*args,**kwargs)
        def native_quote(test,*args,**kwargs):return replace(quote(test,*args,**kwargs),market=self.pool)
        with patch.object(LifecycleState,'create',side_effect=authentic_create),\
                patch.object(SelectivePaper,'reserve',native_reserve),\
                patch.object(PartialAccountingTests,'quote',native_quote):self.native.setUp()
        self.addCleanup(self.native.doCleanups);self.addCleanup(self.native.sleeve.close)
        self.candidate=deepcopy(self.native.candidate);self.candidate['token']=self.token
        self.native.state.transition={'proof_hash':'authenticated-transition'}
        self.native.state.v4_key=self.key
        # Use this fixture's actual native book market for quote checks; the
        # authenticated pool history remains independently bound to that market.
        self.market=self.native.paper._get(self.native.identity)['market']
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'plane.sqlite';self.plane=Plane(self.path)
        self.addCleanup(lambda:self.plane.close())
        self.history=CurrentHistory(self.plane,ENDPOINT)
        self.bind_market()

    def bind_market(self):
        real_get=self.history.get
        self.history.get=lambda k:real_get(self.pool if k==self.market else k)

    def reads(self,function=paper._ongoing_scale_evidence,*,history=True):
        mark=self.native.native_quote(2000,'sell',self.native.before['tokens'],self.native.before['remaining_cost']*2)
        meta=dict(block=self.top,block_hash=self.tape.header(self.top)['hash'],event_at=2000)
        # Pool locator is independent from the native book's fixture market.
        real_roll=v4.rolling_position_activity
        def roll(endpoint,**kw):
            kw['pool_id']=self.pool
            result=real_roll(endpoint,**kw)
            return result
        token=_active.set(self.history if history else None)
        try:
            with patch.object(paper.time,'time',return_value=2000),patch('time.monotonic',return_value=100),\
                    patch.object(paper,'_v4_quote',return_value=(mark,meta,None)),\
                    patch.object(paper,'_latest_header',side_effect=lambda rpc:self.tape.call('eth_getBlockByNumber',[hex(self.top),False],scope='pons_scale')),\
                    patch.object(paper,'evidence_rpc',return_value=self.tape),\
                    patch.object(v4,'rolling_position_activity',side_effect=roll),\
                    patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=self.tape):
                # The original reader still obtains the same actual pool.
                original_collect=paper.collect_v4_activity
                def collect(endpoint,**kw):kw['pool_id']=self.pool;return original_collect(endpoint,**kw)
                with patch.object(paper,'collect_v4_activity',side_effect=collect):
                    if function is not paper._ongoing_scale_evidence:
                        function.__wrapped__.__globals__.update(_v4_quote=paper._v4_quote,
                            evidence_rpc=paper.evidence_rpc,collect_v4_activity=paper.collect_v4_activity)
                    return function(ENDPOINT,self.tape,self.native.paper,self.native.identity,self.native.state,
                        self.candidate,1,self.native.store,self.native.sleeve)
        finally:_active.reset(token)

    def prepare(self):
        with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=self.tape),patch('time.monotonic',return_value=100):
            activity=v4.collect_v4_activity(ENDPOINT,pool_id=self.pool,key=self.key,token=self.token,
                start_block=self.top-900,end_block=self.top,evidence_context=self.context)
        rows=[dict(r,canonical_order=[r['block'],r['transaction_index'],r['log_index']]) for r in activity['swaps']]
        self.history.remember(self.pool,self.tape.header(self.top),rows,from_time=1100)
        return activity

    def test_same_evidence_has_identical_native_qualification_without_full_window_repurchase(self):
        original=self.reads(original_reader(),history=False)
        self.prepare();before=Counter(self.tape.methods);wire=self.tape.batches
        optimized=self.reads();after=Counter(self.tape.methods)
        self.assertEqual(original[0],optimized[0])
        a=ongoing_scale_requalification(position=original[1],controller=vars(self.native.state),evidence=original[0],now=2000)
        b=ongoing_scale_requalification(position=optimized[1],controller=vars(self.native.state),evidence=optimized[0],now=2000)
        self.assertEqual(a,b)
        self.assertTrue(b['scale_qualified'],b)
        self.assertEqual(after['eth_getLogs'],before['eth_getLogs'])
        self.assertEqual(after['eth_getTransactionReceipt'],before['eth_getTransactionReceipt'])
        self.assertEqual(after['eth_getBlockReceipts'],before['eth_getBlockReceipts'])
        self.assertEqual(optimized[1],self.native.before)
        self.assertTrue(self.native.paper.accounting(self.native.identity)['replay_verified'])
        print('SCALING_HISTORY_TRACE',json.dumps(dict(same_head_additional_physical=self.tape.batches-wire,
            same_head_additional_methods=dict(after-before),unchanged_native_qualification=True)),flush=True)

    def test_restart_and_second_sizing_pass_reuse_native_frontier_without_receipt_refetch(self):
        self.prepare();first=self.reads();before=Counter(self.tape.methods)
        self.plane.close();self.plane=Plane(self.path);self.history=CurrentHistory(self.plane,ENDPOINT)
        self.bind_market()
        second=self.reads()
        self.assertEqual(first,second)
        delta=Counter(self.tape.methods)-before
        self.assertEqual(delta['eth_getLogs'],0);self.assertEqual(delta['eth_getTransactionReceipt'],0)
        self.assertEqual(self.history.get(self.pool)['last_interval']['kind'],'already_complete_no_delta')

    def test_missing_preparation_refuses_before_new_executable_quote_or_capital(self):
        token=_active.set(self.history)
        try:
            with patch.object(paper,'_v4_quote') as quote,patch.object(paper.time,'time',return_value=2000):
                self.assertIsNone(paper._attempt_current_scale(ENDPOINT,self.tape,self.native.paper,
                    self.native.identity,self.native.state,self.candidate,1,self.native.store,{},self.native.before,demand={}))
            quote.assert_not_called()
        finally:_active.reset(token)
        self.assertEqual(self.native.paper._get(self.native.identity),self.native.before)
        self.assertIsNone(self.native.sleeve.get(self.native.identity).get('scale_reservation'))

    def test_reorganization_invalidates_history_without_mutating_the_native_position(self):
        self.prepare();self.tape.forks[self.top]=1
        with self.assertRaisesRegex(BoundaryError,'membership'):self.reads()
        self.assertIsNone(self.history.get(self.pool))
        self.assertEqual(self.native.paper._get(self.native.identity),self.native.before)

    def test_missing_prefix_prepares_only_uncovered_blocks_before_any_executable_clock(self):
        from meme_machine.lanes.pons.pons_current_history import _prepare_scale_prefix
        activity=self.prepare()
        self.history.invalidate(self.pool,'offline-gap')
        rows=[dict(r,canonical_order=[r['block'],r['transaction_index'],r['log_index']]) for r in activity['swaps']]
        self.history.remember(self.pool,self.tape.header(self.top),rows,from_time=1985)
        self.tape.request_log=[];before=Counter(self.tape.methods)
        with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=self.tape),\
                patch.object(paper,'_v4_quote',side_effect=AssertionError('history preparation cannot quote')):
            self.assertTrue(_prepare_scale_prefix(self.path,ENDPOINT,self.pool,self.candidate,self.key,
                Path(self.native.temp.name)/'native.sqlite',self.native.identity))
        queries=[p[0] for m,p in self.tape.request_log if m=='eth_getLogs']
        self.assertTrue(queries)
        self.assertTrue(all(int(q['toBlock'],16)<self.top-15 for q in queries))
        self.assertEqual(self.history.get(self.pool)['from_time'],1100)
        self.assertEqual(Counter(self.tape.methods)['eth_getTransactionReceipt']-before['eth_getTransactionReceipt'],0)
        self.assertEqual(self.native.paper._get(self.native.identity),self.native.before)
        self.assertTrue(self.reads()[0]['horizon']['independent_groups']>=25)

    def test_pending_protection_cancels_preparation_without_provider_purchase(self):
        from meme_machine.lanes.pons.pons_current_history import _prepare_scale_prefix
        self.prepare()
        pending=self.native.paper.advance(self.native.identity,now=2000,action='exit_intent',exit_tokens=self.native.before['tokens'])
        before=Counter(self.tape.methods)
        self.assertFalse(_prepare_scale_prefix(self.path,ENDPOINT,self.pool,self.candidate,self.key,
            Path(self.native.temp.name)/'native.sqlite',self.native.identity))
        self.assertEqual(Counter(self.tape.methods),before)
        self.assertEqual(self.native.paper._get(self.native.identity),pending)
