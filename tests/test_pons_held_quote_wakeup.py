"""Offline Pons quote wake tests; no endpoints, positions, or provider access."""
from dataclasses import replace
from unittest.mock import patch
import time
import unittest

from meme_machine.lanes.pons import held_quote_wakeup as wake
from meme_machine.lanes.pons import pons_survivor_runtime as survivor
from meme_machine.lanes.pons.abi import topic, signature
from meme_machine.lanes.pons.identity import load


POOL = '0x' + 'a' * 64
OTHER = '0x' + 'b' * 64
HASH = '0x' + 'c' * 64
HEAD_HASH = '0x' + 'd' * 64


def event_log(role, event_name, pool=POOL):
    pin = load(role)
    event = next(x for x in pin['abi'] if x.get('type') == 'event'
                 and x.get('name') == event_name)
    topics = [topic(signature(event))]
    if event['inputs'] and event['inputs'][0].get('indexed'):
        topics.append(pool)
    return dict(address=pin['address'], topics=topics, blockHash=HEAD_HASH)


def proof(**changes):
    defaults = dict(pool_id=POOL, quote_block=100, quote_block_hash=HASH,
        through_block=120, through_hash=HEAD_HASH, observed_monotonic=1004,
        source='authenticated_canonical_manager_hook_and_token',
        canonical_contiguous=True, exact_manager_scope_complete=True,
        exact_hook_scope_complete=True, token_behavior_proven=True,
        gas_and_fee_bound_valid=True, mutation_count=0, unknown_count=0)
    defaults.update(changes)
    return wake.WindowProof(**defaults)


def plan(**changes):
    defaults = dict(pool_id=POOL, quantity=100,
        quote=dict(pool_id=POOL, quantity=100, block=100,
                   block_hash=HASH, acquired=1000),
        proof=proof(), current_head=dict(number=120, hash=HEAD_HASH),
        now_monotonic=1004, risk_distance_bps=2500,
        cadence_seconds=3)
    defaults.update(changes)
    return wake.plan_held_quote(**defaults)


class PonsWakeClassifierTests(unittest.TestCase):
    def test_pool_swap_and_liquidity_and_hook_fee_wake(self):
        for role, name in (('uniswap_v4_manager', 'Swap'),
                           ('uniswap_v4_manager', 'ModifyLiquidity'),
                           ('uniswap_v4_manager', 'ProtocolFeeUpdated'),
                           ('pons_v2_hook', 'HookFeeCollected'),
                           ('pons_v2_hook', 'BuybackEnabledUpdated')):
            with self.subTest(event=name):
                self.assertEqual(wake.classify_native_log(event_log(role,name),POOL),'WAKE')
                self.assertEqual(wake.classify_native_log(event_log(role,name,OTHER),POOL),'OTHER_POOL')

    def test_global_hook_fee_and_manager_control_wake_all(self):
        for role, name in (('pons_v2_hook', 'HookFeeBpsUpdated'),
                           ('pons_v2_hook', 'MaxInternalPriceImpactUpdated'),
                           ('uniswap_v4_manager','ProtocolFeeControllerUpdated')):
            with self.subTest(event=name):
                self.assertEqual(wake.classify_native_log(event_log(role,name),POOL),'WAKE')

    def test_unknown_malformed_and_other_contract_never_certify_quiet(self):
        self.assertEqual(wake.classify_native_log(dict(address='0x'+'e'*40,
            topics=['0x'+'f'*64]),POOL),'OTHER_CONTRACT')
        pin=load('pons_v2_hook')
        self.assertEqual(wake.classify_native_log(dict(address=pin['address'],
            topics=['0x'+'f'*64]),POOL),'UNKNOWN')
        self.assertEqual(wake.classify_native_log(dict(address=pin['address'],
            topics=[]),POOL),'UNKNOWN')
        self.assertEqual(wake.classify_native_log(None,POOL),'UNKNOWN')


class QuotePlanTests(unittest.TestCase):
    def test_complete_quiet_interval_cannot_publish_marks_or_execute(self):
        choice=plan()
        self.assertEqual(choice.decision,'QUIET_HOLD_ONLY')
        self.assertFalse(choice.request_fresh_quote)
        self.assertFalse(choice.may_publish_new_mark)
        self.assertFalse(choice.may_execute_with_previous_quote)

    def test_absent_real_adapter_requires_quote(self):
        self.assertTrue(plan(proof=None).request_fresh_quote)
        self.assertTrue(plan(quote=None).request_fresh_quote)

    def test_all_required_windows_and_chain_equivalence(self):
        changes=[
            ('canonical_contiguous',False),
            ('exact_manager_scope_complete',False),
            ('exact_hook_scope_complete',False),
            ('token_behavior_proven',False),
            ('gas_and_fee_bound_valid',False),
            ('source','public_scout_only'),
            ('mutation_count',1),
            ('unknown_count',1),
            ('through_block',119),
            ('through_hash','0x'+'f'*64),
        ]
        for key,value in changes:
            with self.subTest(key=key):
                self.assertTrue(plan(proof=proof(**{key:value})).request_fresh_quote)
        self.assertTrue(plan(current_head=dict(number=121,hash=HEAD_HASH)).request_fresh_quote)
        self.assertTrue(plan(current_head=dict(number=120,hash='0x'+'f'*64)).request_fresh_quote)
        self.assertTrue(plan(proof=proof(unknown_count=-1)).request_fresh_quote)

    def test_exact_quantity_identity_and_no_automatic_restart_reuse(self):
        self.assertTrue(plan(quantity=99).request_fresh_quote)
        self.assertTrue(plan(quote=dict(pool_id=POOL,quantity=100,block=100,
            block_hash='0x'+'f'*64,acquired=1000)).request_fresh_quote)
        self.assertTrue(plan(proof=proof(quote_block=101)).request_fresh_quote)
        self.assertTrue(plan(quote=None).request_fresh_quote)

    def test_protective_actions_risk_and_freshness_force_quote(self):
        for key in ('pending_exit','pending_partial','scale_or_requalification','renewal_due'):
            with self.subTest(key=key):
                self.assertTrue(plan(**{key:True}).request_fresh_quote)
        self.assertTrue(plan(risk_distance_bps=1000).request_fresh_quote)
        self.assertTrue(plan(risk_distance_bps=None).request_fresh_quote)
        self.assertTrue(plan(now_monotonic=1060).request_fresh_quote)
        self.assertTrue(plan(proof=proof(observed_monotonic=998)).request_fresh_quote)
        self.assertTrue(plan(cadence_seconds=10).request_fresh_quote)
        self.assertTrue(plan(maximum_quote_age_seconds=600).request_fresh_quote)

    def test_quiet_loop_always_preserves_original_cadence(self):
        for cadence in (3,5):
            for offset in (1,2,3,4):
                with self.subTest(cadence=cadence,offset=offset):
                    self.assertEqual(plan(now_monotonic=1000+offset,
                        proof=proof(observed_monotonic=1000+offset),
                        cadence_seconds=cadence).decision,'QUIET_HOLD_ONLY')
        self.assertEqual(wake.modeled_quote_elements(hours=72,every_seconds=3)['turns'],86400)
        self.assertEqual(wake.modeled_quote_elements(hours=72,every_seconds=5)['turns'],51840)


class SurvivorQuoteHeadReuseTests(unittest.TestCase):
    def setUp(self):
        self.runtime=object.__new__(survivor.Runtime)
        self.runtime.rpc=object()
        self.row=dict(block=110,block_hash=HASH,graduation=dict(block_hash=HASH))

    def test_same_turn_quote_removes_extra_latest_read(self):
        q=dict(block=111,block_hash=HEAD_HASH,acquired=time.monotonic()-1)
        with patch.object(survivor,'_latest_header',
                          side_effect=AssertionError('redundant provider read')):
            header=self.runtime._position_head(self.row,q)
        self.assertEqual(header,dict(number=hex(111),hash=HEAD_HASH))

    def test_stale_missing_or_behind_quotes_take_original_fallback(self):
        expected=dict(number=hex(112),hash=HEAD_HASH)
        q=dict(block=111,block_hash=HEAD_HASH,acquired=time.monotonic()-10)
        with patch.object(survivor,'_latest_header',return_value=expected) as provider:
            self.assertEqual(self.runtime._position_head(self.row,q),expected)
            self.assertEqual(self.runtime._position_head(self.row,None),expected)
            q=dict(block=109,block_hash=HEAD_HASH,acquired=time.monotonic())
            self.assertEqual(self.runtime._position_head(self.row,q),expected)
            q=dict(block=110,block_hash=HEAD_HASH,acquired=time.monotonic())
            self.assertEqual(self.runtime._position_head(self.row,q),expected)
            self.assertEqual(provider.call_count,4)

    def test_same_block_matching_canonical_pin_is_accepted(self):
        q=dict(block=110,block_hash=HASH,acquired=time.monotonic())
        with patch.object(survivor,'_latest_header',
                          side_effect=AssertionError('same block should reuse')):
            self.assertEqual(self.runtime._position_head(self.row,q)['hash'],HASH)


if __name__ == '__main__':
    unittest.main()
