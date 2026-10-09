"""Offline Pons held PAPER observer / canonical event scope validation.

No network or real provider. Positions and risk decisions remain owned by the
existing native Pons Current/Survivor controllers.
"""
from unittest import TestCase
from unittest.mock import patch
import os
import time

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.abi import signature,topic
from meme_machine.lanes.pons.identity import load
from meme_machine.lanes.pons.held_event_coverage import (
    NativeHeldCoverage, native_coverage_filters)
from meme_machine.lanes.pons.held_paper_shadow import PaperHeldShadow
from meme_machine.lanes.pons import pons_survivor_runtime,pons_selective_paper
from meme_machine.runtime.robinhood.provider_authority import fingerprint

URL='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_PONS_HELD'
POOL='0x'+'1'*64
START_HASH='0x'+'a'*64
END_HASH='0x'+'b'*64
TX='0x'+'c'*64
QUOTE=123456


def ev(role,name):
    pin=load(role)
    spec=next(x for x in pin['abi'] if x['type']=='event' and x['name']==name)
    return dict(address=pin['address'],topics=[topic(signature(spec)),POOL],
        data='0x'+'00'*32,blockNumber=hex(101),transactionIndex='0x0',
        logIndex='0x0',blockHash=END_HASH,transactionHash=TX,removed=False)


class FakeCanonicalRpc:
    canonical_authority=True
    chain_verified=True
    provider_fingerprint=fingerprint(URL)
    def __init__(self,events=(),*,fork=False,fail=False):
        self.events=tuple(events)
        self.fork=fork;self.fail=fail;self.calls=[]
        self.header_reads=0

    def batch(self,calls,*,scope):
        self.calls.append((scope,list(calls)))
        if self.fail:raise BoundaryError('provider_transport_failure')
        out=[]
        for method,args in calls:
            if method=='eth_getBlockByNumber':
                number=int(args[0],16)
                assert number in (100,101)
                self.header_reads+=1
                block_hash=(START_HASH if number==100 else END_HASH)
                if self.fork and self.header_reads>=3 and number==100:
                    block_hash='0x'+'f'*64
                out.append(dict(number=hex(number),hash=block_hash,
                                parentHash=START_HASH))
            elif method=='eth_getLogs':
                query=args[0];first=int(query['fromBlock'],16)
                last=int(query['toBlock'],16);rows=[]
                for e in self.events:
                    height=int(e['blockNumber'],16)
                    if height<first or height>last:continue
                    if e['address'].lower() not in [
                        a.lower() for a in (query['address'] if
                        isinstance(query['address'],list) else [query['address']])]:
                        continue
                    requested=query['topics']
                    if len(e['topics'])<len(requested):continue
                    if all(want is None or
                           e['topics'][i].lower() in (
                               [x.lower() for x in want] if isinstance(want,list)
                               else [want.lower()])
                           for i,want in enumerate(requested)):
                        rows.append(e)
                out.append(rows)
            else:
                raise AssertionError('unexpected native method '+method)
        return out


def observe(rpc,**overrides):
    kwargs=dict(pool_id=POOL,
        quote_head=dict(number=hex(100),hash=START_HASH),
        current_head=dict(number=hex(101),hash=END_HASH),
        token_behavior_proven=False,
        hook_time_invariant_proven=False,
        gas_and_fee_bound_valid=False)
    kwargs.update(overrides)
    return NativeHeldCoverage(rpc,URL,maximum_blocks=40).observe(**kwargs)


class NativeEventCoverageTests(TestCase):
    def test_all_native_manager_hook_events_are_in_scope(self):
        addresses,scoped,globals_=native_coverage_filters()
        self.assertEqual(len(addresses),2)
        self.assertGreater(len(scoped),6)
        self.assertGreater(len(globals_),6)
        for role,name in (('uniswap_v4_manager','Swap'),
                          ('uniswap_v4_manager','ModifyLiquidity'),
                          ('pons_v2_hook','HookFeeCollected'),
                          ('pons_v2_hook','PoolRegistered')):
            pin=load(role)
            spec=next(x for x in pin['abi'] if x['type']=='event' and x['name']==name)
            self.assertIn(topic(signature(spec)),scoped)
        spec=next(x for x in load('pons_v2_hook')['abi']
                  if x['type']=='event' and x['name']=='HookFeeBpsUpdated')
        self.assertIn(topic(signature(spec)),globals_)

    def test_empty_interval_unproven_semantics_does_not_authorize_skips(self):
        rpc=FakeCanonicalRpc()
        proof=observe(rpc)
        self.assertEqual(proof.reason,'token_hook_or_fee_equivalence_unproven')
        self.assertFalse(proof.can_consider_quiet)
        self.assertIsNotNone(proof.window)
        self.assertFalse(proof.window.token_behavior_proven)
        self.assertEqual(proof.scoped_elements,1)
        self.assertEqual(proof.global_elements,1)
        self.assertEqual(rpc.header_reads,4)

    def test_complete_semantic_fixture_can_consider_quiet_but_does_not_mark(self):
        result=observe(FakeCanonicalRpc(),
            token_behavior_proven=True,hook_time_invariant_proven=True,
            gas_and_fee_bound_valid=True)
        self.assertTrue(result.can_consider_quiet)
        from meme_machine.lanes.pons.held_quote_wakeup import plan_held_quote
        result_plan=plan_held_quote(pool_id=POOL,quantity=100,
            quote=dict(pool_id=POOL,quantity=100,block=100,
                block_hash=START_HASH,acquired=time.monotonic()-1),
            proof=result.window,current_head=dict(number=101,hash=END_HASH),
            now_monotonic=time.monotonic(),risk_distance_bps=2500)
        self.assertEqual(result_plan.decision,'QUIET_HOLD_ONLY')
        self.assertFalse(result_plan.may_publish_new_mark)
        self.assertFalse(result_plan.may_execute_with_previous_quote)

    def test_swap_or_hook_fee_requires_native_quote(self):
        for role,name in [('uniswap_v4_manager','Swap'),
                          ('pons_v2_hook','HookFeeCollected')]:
            with self.subTest(role=role):
                rpc=FakeCanonicalRpc((ev(role,name),))
                result=observe(rpc,token_behavior_proven=True,
                    hook_time_invariant_proven=True,gas_and_fee_bound_valid=True)
                self.assertEqual(result.outcome,'QUOTE_REQUIRED')
                self.assertEqual(len(result.events),1)
                self.assertEqual(result.reason,'pool_or_hook_mutation')

    def test_fork_after_filtered_logs_fails_closed(self):
        with self.assertRaisesRegex(BoundaryError,'held_coverage_boundary_reorg'):
            observe(FakeCanonicalRpc(fork=True))

    def test_transport_failure_and_unverified_provider_fail_closed(self):
        with self.assertRaisesRegex(BoundaryError,'provider_transport_failure'):
            observe(FakeCanonicalRpc(fail=True))
        rpc=FakeCanonicalRpc();rpc.chain_verified=False
        with self.assertRaisesRegex(BoundaryError,'chain_unverified'):
            observe(rpc)
        self.assertEqual(rpc.calls,[])
        mismatch=FakeCanonicalRpc()
        mismatch.provider_fingerprint='different_authentication'
        with self.assertRaisesRegex(BoundaryError,'endpoint_fingerprint_disagreement'):
            observe(mismatch)
        self.assertEqual(mismatch.calls,[])

    def test_unbounded_gap_never_buys_missing_interval(self):
        with self.assertRaisesRegex(BoundaryError,'gap_exceeds_finite_window'):
            observe(FakeCanonicalRpc(),
                current_head=dict(number=hex(200),hash=END_HASH))


def quote_turn(trial,*,rpc,block,net=QUOTE,quantity=100,hold=True):
    return trial.observe_after_hold(rpc=rpc,pool_id=POOL,
        quantity=quantity,quote_block=block,
        quote_hash=(START_HASH if block==100 else END_HASH),
        net_proceeds=net,position_open=hold,
        no_pending_exit=hold,no_pending_partial=hold,owner_protected=hold,
        risk_distance_bps=2500)


class ShadowIntegrationTests(TestCase):
    def test_disabled_by_default_no_provider_work(self):
        shadow=PaperHeldShadow(URL,environ={})
        rpc=FakeCanonicalRpc()
        self.assertIsNone(quote_turn(shadow,rpc=rpc,block=100))
        self.assertEqual(rpc.calls,[])
        self.assertFalse(shadow.status()['quote_suppression_enabled'])

    def test_bounded_live_paper_shadow_counts_only_counterfactual(self):
        shadow=PaperHeldShadow(URL,environ={
            'MM_PONS_HELD_PAPER_SHADOW':'1',
            'MM_PONS_HELD_SHADOW_MAX_SAMPLES':'1',
            'MM_PONS_HELD_SHADOW_EVERY_TICKS':'2'})
        rpc=FakeCanonicalRpc()
        self.assertIsNone(quote_turn(shadow,rpc=rpc,block=100))
        report=quote_turn(shadow,rpc=rpc,block=101)
        self.assertEqual(report['status'],'QUOTE_REQUIRED')
        self.assertTrue(report['unchanged_net_quote'])
        self.assertEqual(shadow.status()['counts']['counterfactual_unchanged_net_quote'],1)
        self.assertEqual(shadow.status()['counts']['coverage_samples'],1)
        self.assertFalse(shadow.status()['can_skip_quotes'])
        self.assertEqual(len(rpc.calls),4)
        # Same observed quantity, new quote: no further provider work after cap.
        quote_turn(shadow,rpc=rpc,block=101)
        self.assertEqual(len(rpc.calls),4)

    def test_quote_changed_without_events_suspends_shadow(self):
        shadow=PaperHeldShadow(URL,environ={
            'MM_PONS_HELD_PAPER_SHADOW':'1',
            'MM_PONS_HELD_SHADOW_EVERY_TICKS':'2'})
        rpc=FakeCanonicalRpc()
        quote_turn(shadow,rpc=rpc,block=100,net=1000)
        quote_turn(shadow,rpc=rpc,block=101,net=950)
        self.assertTrue(shadow.unsafe)
        self.assertEqual(shadow.counts['silent_net_quote_differences'],1)
        self.assertFalse(shadow.status()['quote_suppression_enabled'])

    def test_pending_or_partial_exit_never_dispatches_probe(self):
        shadow=PaperHeldShadow(URL,environ={
            'MM_PONS_HELD_PAPER_SHADOW':'1',
            'MM_PONS_HELD_SHADOW_EVERY_TICKS':'1'})
        rpc=FakeCanonicalRpc()
        quote_turn(shadow,rpc=rpc,block=100,hold=False)
        self.assertEqual(rpc.calls,[])
        self.assertGreater(shadow.counts['unsafe_position_state_no_work'],0)

    def test_provider_failure_is_inconclusive_not_a_strategy_exit(self):
        shadow=PaperHeldShadow(URL,environ={
            'MM_PONS_HELD_PAPER_SHADOW':'1',
            'MM_PONS_HELD_SHADOW_EVERY_TICKS':'2'})
        rpc=FakeCanonicalRpc(fail=True)
        quote_turn(shadow,rpc=rpc,block=100)
        result=quote_turn(shadow,rpc=rpc,block=101)
        self.assertEqual(result['status'],'INCONCLUSIVE')
        self.assertEqual(shadow.counts['coverage_failures'],1)
        self.assertFalse(shadow.status()['exit_authority'])

    def test_protective_margin_gates_optional_provider_work(self):
        from meme_machine.lanes.pons.held_paper_shadow import protective_margin_bps
        self.assertEqual(protective_margin_bps(
            current=-800,high=0,stop=-800,first_profit=1800,
            trail_bps=1200),0)
        self.assertGreater(protective_margin_bps(
            current=10000,high=10000,stop=-800,first_profit=1800,
            trail_bps=1200),1000)
        self.assertEqual(protective_margin_bps(
            current=6000,high=10000,stop=-800,first_profit=1800,
            trail_bps=1200),0)
        shadow=PaperHeldShadow(URL,environ={
            'MM_PONS_HELD_PAPER_SHADOW':'1',
            'MM_PONS_HELD_SHADOW_EVERY_TICKS':'1'})
        rpc=FakeCanonicalRpc()
        shadow.observe_after_hold(rpc=rpc,pool_id=POOL,quantity=100,
            quote_block=100,quote_hash=START_HASH,net_proceeds=QUOTE,
            risk_distance_bps=0)
        shadow.observe_after_hold(rpc=rpc,pool_id=POOL,quantity=100,
            quote_block=101,quote_hash=END_HASH,net_proceeds=QUOTE,
            risk_distance_bps=300)
        self.assertEqual(rpc.calls,[])
        self.assertGreater(shadow.counts['near_original_protective_exit_no_work'],0)

    def test_native_monitors_call_shadow_only_after_original_exit_logic(self):
        from inspect import getsource
        surv=getsource(pons_survivor_runtime.Runtime._manage_position)
        cur=getsource(pons_selective_paper._run_lifecycle)
        self.assertLess(surv.index('action=monitor('),surv.index('shadow.observe_after_hold('))
        self.assertLess(cur.index('action=runner_action('),cur.index('held_shadow.observe_after_hold('))
        self.assertLess(cur.index('paper.advance(identity,now=mark.stamp.observed_at,action="mark"'),
                        cur.index('held_shadow.observe_after_hold('))
