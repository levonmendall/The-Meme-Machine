"""Offline USDG oracle and native quote composition; no market transport."""
import ast
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import subprocess
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from meme_machine.lanes.ramses.abi import calldata
from meme_machine.lanes.ramses.identity import load
from meme_machine.runtime.usd_valuation import (
    USDG_ASSET,USDG_FEED,USDG_HEARTBEAT,NativeValueReader,
    ValuationUnavailable,robinhood_usd,sol_usd,
)

ROOT=Path(__file__).resolve().parents[1]
BASE='f05dcf09ebbded45e09aa7a95bfbe82c07b4fd38'
NOW=1791077122
ROUND=(1<<64)+121
UPDATED=1791042001
AGGREGATOR='0x8beee3503f6860d5dac4ce26b5eee92982951c2e'
WNATIVE='0x'+'a1'*20
POOL='0x'+'a2'*20


def baseline(path):
    try:
        return subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT,stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        # Normal CI uses a shallow checkout. No historical/network fetch belongs
        # to a deterministic unit suite; full source comparisons run locally.
        raise unittest.SkipTest('Historical source comparison needs the existing baseline commit') from None


# Explicit owner-approved removal of holding-age sales. Every other economic
# node stays pinned to the original nine-change source. These reviewed methods
# have their own exact AST identities; valuation cannot change them implicitly.
# The later owner directive also requires adverse flow for Pons's legacy
# stale-thesis helper. Its exact two-node delta from fe752458 is independently
# derived by SourceDeltaTests; constants, interfaces and siblings remain pinned.
HOLDING_DELTAS = {'meme_machine/lanes/pump/pump_acceleration_strategy.py': {'exit_decision': 'a2c3d9c0755ac779dc77298eda3a0b88b33eb1e4e3ebada5b34b93dea1dd1535'}, 'meme_machine/lanes/pump/pump_acceleration_paper.py': {'PumpAccelerationPaperLifecycle.mark': '094bb23a9533d1f96183d0239482d3a49afeb55b29567268bc8c6493e87ba671', 'PumpAccelerationPaperLifecycle.exceptional_exit_intent': '6e31ca62cbc145ec2ad27a9cd46cde386772a4cf7f1a6753a171833929534e23', 'PumpAccelerationPaperLifecycle.restore': '0c4afd4cd3497e47a452baf809face20a756d114eb90b8c05c093f229b1a9065'}, 'meme_machine/lanes/pump/runner.py': {'_monitor_positions': '9ff7f86373d2598cf6a9fa0130822ba4aafb9a6b8bfce504e0d80e998b794ba1'}, 'meme_machine/lanes/pump/pumpswap_survivor_runtime.py': {'Runtime._position': 'eb6a182cd92506c80c0506dcef8894a7c14bdd698bbf7eec63a35fe39038dcf2'}, 'meme_machine/lanes/pons/pons_selective_continuation.py': {'pregraduation_action': '123c3c69fcb29d907ea62109e7b7fb96793470439114279ce6a74b791f253ee2'}, 'meme_machine/lanes/pons/pons_postgrad_survivor.py': {'exit_action': 'a7418d0279afe5c8a1ff6e08b3fd48b1a995b81509cb6bf0cd6ef477b7a6e463'}, 'meme_machine/runtime/directional_continuation.py': {'bridge_state': 'ef830dabb4491bd7be1ed77599060e0e0d0b496a3655111b97deb330e6b16763'}, 'meme_machine/runtime/survivor_risk.py': {'mark': 'f3b06981eddd1e839624db849fe8c80fbfa2d520f0c17ed73f37922ce8581d19'}, 'tests/test_operational_nine.py': {'NineChanges.test_bridge_exact_age_and_all_required_evidence': 'd7890408ef6ac990d22ab3afafe32a4c68ecfbb82f5cff033ceae3dce4d92553'}}

# Owner-approved continuous discovery removes only main's engineering clocks.
# Keep an exact AST identity for the entire updated runtime loop, while the
# comparison below still pins all economic helpers, interfaces and siblings.
HOLDING_DELTAS['meme_machine/lanes/pump/runner.py']['main']='5dd3dbdffec0db1d2b51465298d5e3c70732c3fdee84b3297cbd8f6fb2259686'

# Separately authorized volume-quality-attention-v1. Pin the complete reviewed
# functions, including their existing economics; only candidate attention and
# fresh requalification changed. A different body still fails this source guard.
# New helpers have an exact identity too. No quote, stop, sizing or exit method
# receives a blanket exemption, and all remaining nodes/interfaces still pin.
ATTENTION_DELTAS = {
    'meme_machine/lanes/pump/runner.py': {
        # d6059e48 removes only the unused duplicate observer. Original
        # qualification/quotes/exits and the canonical LocalPumpTape remain.
        'main': '7677550cab1f9d4bb10836e1dfd77e79c55d20f3ae3e510cebc11c34b38aba79',
        '_confirmation_meta': '1cc0f6803425581dd6dd91fcd4b037142764d23ae5fbc5a855914ea5f346c000',
        '_volume_quality_attention': 'a4e73e44c66164b18aadd8102d53d86f7483573fec8d9af8c611fae230cec6ab',
        '_late_signal': '2ed9c66d2dbbb1fdbbb7f1317d40ed65eeb1cea2fd923545016b38d74c5b6e6f',
        '_volume_price_signal': 'ca32e28c8363e5ceba28b67fc7edf6d0e3ac98820bf3a06d3234522495ac4b9a',
        '_record_attempt': 'e0d61bb5bda067f4b12274a946a93af485d03a43ca394938dc38f8754ae5bb6e',
    },
    'meme_machine/lanes/pump/pumpswap_survivor_runtime.py': {
        'Runtime.__init__': 'ea88001e5397533149a47b438dddf56a57babb6bb167c768e809c43e36e90cc7',
        'Runtime._quality_rank': '503bd866a7a3a660a7710386918f292c9e7b7f444e6a4aeecd1326dfdd6338fd',
        'Runtime.reconstruct': 'bac6cac5d29640d85e3e21bc217b58ca99d0fee696598aa37a6791c0ae9a9176',
        'Runtime.step': 'aeca30c345bd2d1955a268853b43a3787dea93fac9fc20441c1d37dd9507622f',
    },
    'meme_machine/lanes/pons/pons_history.py': {
        'PonsHistory.__init__': '499d6eed49f38ff1477e1d28873b8bb8a9bd4b57e41019899f58684caa70be50',
        'PonsHistory._quality_rank': '503bd866a7a3a660a7710386918f292c9e7b7f444e6a4aeecd1326dfdd6338fd',
        'PonsHistory.qualification_turn': 'a7ade8682f589a00202bb292fda823c4357d7c0f32ebd12a719a8ed0bf17c3a4',
    },
    'meme_machine/lanes/pons/pons_survivor_runtime.py': {
        'Runtime._watch_due': '53d9f1504e9eb48459179e76cd43df6e0e0d229b4f8a22f4f857387e7bc64987',
        'Runtime._schedule_watch': '9c5959d7e61c6dd69fc1079f928e260b5b34dbcf2dede8aec156055585552b8a',
        'Runtime.reconstruct': '29f6151b8ebbe4ff385ce4388de3932735e8c01d4f3a411a271cae75a05562ee',
    },
}

# Reviewed operational contention repairs retain the same candidate history,
# graduation horizon and 8,192-entry cache. Pin only their exact changed nodes;
# every other economic function and interface remains compared to the baseline.
OPERATION_DELTAS = {
    'meme_machine/lanes/pump/pumpswap_survivor_runtime.py': {
        # Owner-authorized history separation: exact retained reset-prefix
        # reuse and window reads. All economics and maintenance remain pinned;
        # HistoryCalculationTests compares the two changed acquisition nodes.
        'Runtime.reconstruct': 'debef54d753279920b6ec5c0619edd984bee44ad536a5897eea3be954e99f8d8',
    },
    'meme_machine/lanes/pump/solana_evidence_health.py': {
        # Restore the maintained indexed and verified-volume health path in
        # the actual Pump worker; all freshness and coverage checks stay pinned.
        'evidence_health': '3473d68023a84021ec718f2a7d7a92fe10dee7ef4b7ed4958ed21c382cfed011',
    },
    'meme_machine/lanes/pump/solana_evidence_plane.py': {
        # Only the existing coverage_end_hint access path differs. Gap,
        # availability, interval ordering and membership checks remain pinned.
        'EvidenceReader.covered': '06b4169316bc8f6410235f947719956dce7eb731f03c2dbb788784a7b2556626',
    },
    'meme_machine/lanes/pump/runner.py': {
        '_retain_tape_history': '7e2546ac6ea91029b22809fd3b95fa3ff20a891ad1095a1fd1a39f853e3a6cbd',
        '_observed_creation': '45a63d1aec238ecd9c13498b4bace0ccf532d757b2866fd215c2c1fa1940f5ec',
    },
    'meme_machine/lanes/pons/immutable_rpc.py': {
        'EvidenceStore.__init__': 'e6558c2232a88f43b6ac74805395343768cfbbfdd453390ba28cf6f4fb16aa3e',
        'EvidenceStore.put': '28b55b13579655f0aebcc2b45de5c55404d4a1cdf495a62de0f47189adc4a2de',
    },
    'meme_machine/lanes/pump/solana_evidence_runtime.py': {
        # 5ec6a2b6 keeps creation lookup and its bounded per-poll attention
        # cache separate. Missing lineage is forgotten on the next poll.
        'LocalPumpTape.creation': 'a233fc5649ccc393970f4de814b3462884155a0daf3618a9e608b2990624f0d7',
        'LocalPumpTape._creation': '1533476e797f59f1d7a241f9134fba9d860d998a2d2156b9ed9a9332bb2a3113',
        'LocalPumpTape.events_since': 'ba20cb5653544e5ae46696fbc47bf95c684b4e0042df9f76c52c09cca981e631',
    },
}

# cf443e86 is the reviewed acquisition-only Pons wider-window integration;
# the subsequent explicit owner directive removes only mandatory team_id.
# Freeze that complete file byte-for-byte, rather than exempting it as generic
# infrastructure. The source before this exact transition stays pinned too;
# strategy economics, constants and the nine-change tests retain their guards.
ACQUISITION_SOURCE_DELTAS = {
    'meme_machine/lanes/pons/log_windows.py': {
        'reference': 'cf443e860ee21795453fd7b6311732267562bf1a',
        'before_sha256': 'bba8cfafcedb7223c4259d2c2a509ec8cb786307cea24ac6ffcbf2b241bf3e84',
        'reviewed_sha256': '7cc289d0041c21b7758fa0a742e1b792ff96d5049954a063d823556088e8db48',
    },
}

# The owner explicitly approved the completed lifecycle/reporting package at
# 9cdc1b54. Its three previously protected files remain pinned byte-for-byte;
# first validate the exact prior source with the original economic guard. This
# permits only that published package, including the reviewed readonly keyword
# interface and canonical confirmation fields, rather than exempting Pons code.
LIFECYCLE_PACKAGE_BASE = 'e8f7d2ec8ccc0d530c94171390e1966d5c42a70f'
LIFECYCLE_PACKAGE_REFERENCE = '9cdc1b5428f8ebf0bfcc6206cb8122b354654d9d'
LIFECYCLE_SOURCE_DELTAS = {
    'meme_machine/lanes/pons/pons_selective_continuation.py': {
        'before_sha256': '1461b456fba76e3e27674eb3cd626f856176d4ba9fdc00c3907fc75b350da0ed',
        'reviewed_sha256': 'e25cd6074cb283dd0924c942094877ff79ed0a21f613ea0974fe16424007e145',
    },
    'meme_machine/lanes/pons/pons_selective_capital.py': {
        'before_sha256': 'c16fc1d787692997222e1fa7003f04d52242d31385efa707d91ee98edefec2f2',
        'reviewed_sha256': '54f9621fed567b8e68b2e18dddc10eb0f0e7db5b4bfb243d434f173d8a5d5716',
    },
    'meme_machine/lanes/pons/pons_selective_recovery.py': {
        'before_sha256': '037a5c21aead51273bbe6d150ed6f2b608d7cee92bd0c8919c3f08374e03c753',
        'reviewed_sha256': '700a09510f2e1eda0f9ea5ef552561d3b13827078c6797dd5ba765e08ec06226',
    },
}

def assert_attention_node(test,relative,name,node):
    expected={**ATTENTION_DELTAS.get(relative,{}),**OPERATION_DELTAS.get(relative,{})}[name]
    test.assertEqual(__import__('hashlib').sha256(ast.dump(node).encode()).hexdigest(),expected,relative+':'+name)


def assert_holding_delta(test, relative, original, current, *, reviewed_lifecycle=True):
    if reviewed_lifecycle and relative in LIFECYCLE_SOURCE_DELTAS:
        reviewed=LIFECYCLE_SOURCE_DELTAS[relative]
        prior=subprocess.check_output(['git','show',LIFECYCLE_PACKAGE_BASE+':'+relative],cwd=ROOT)
        sha256=__import__('hashlib').sha256
        test.assertEqual(sha256(prior).hexdigest(),reviewed['before_sha256'],relative+':prior lifecycle source')
        test.assertEqual(sha256(current).hexdigest(),reviewed['reviewed_sha256'],relative+':reviewed lifecycle source')
        assert_holding_delta(test,relative,original,prior,reviewed_lifecycle=False)
        return
    if relative in ACQUISITION_SOURCE_DELTAS:
        reviewed=ACQUISITION_SOURCE_DELTAS[relative]
        sha256=__import__('hashlib').sha256
        test.assertEqual(sha256(original).hexdigest(),reviewed['before_sha256'],relative+':original')
        test.assertEqual(sha256(current).hexdigest(),reviewed['reviewed_sha256'],relative+':reviewed acquisition')
        return
    expected=dict(HOLDING_DELTAS.get(relative,{}))
    expected.update(ATTENTION_DELTAS.get(relative,{}))
    expected.update(OPERATION_DELTAS.get(relative,{}))
    old=ast.parse(original);new=ast.parse(current)
    for name,pinned in expected.items():
        before=old;after=new
        for part in name.split('.'):
            before=next((n for n in before.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==part),None) if before is not None else None
            after=next(n for n in after.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==part)
        test.assertEqual(__import__('hashlib').sha256(ast.dump(after).encode()).hexdigest(),pinned,relative+':'+name)
        if before is None:
            # Only the explicitly pinned attention helper may be new. Remove
            # that node for the historical sibling/interface comparison.
            test.assertIn(name,('_volume_quality_attention','Runtime._quality_rank','_retain_tape_history','_observed_creation','LocalPumpTape._creation'))
            owner=new
            for part in name.split('.')[:-1]:owner=next(n for n in owner.body if isinstance(n,ast.ClassDef) and n.name==part)
            owner.body.remove(after)
            continue
        # Retain the full function interface/decorators and every sibling node.
        before.body=[ast.Pass()];after.body=[ast.Pass()]
    test.assertEqual(ast.dump(old),ast.dump(new),relative)


def abi(*values):
    return '0x'+''.join(f'{int(v,16) if isinstance(v,str) else v%(1<<256):064x}' for v in values)


def text_abi(value):
    raw=value.encode()
    return abi(32,len(raw))+raw.hex()+('00'*((-len(raw))%32))


class ReadRPC:
    """The real authentication/route decoders consume these synthetic RPC facts."""
    def __init__(self):
        self.now=NOW
        self.answer=100013961
        self.round=[ROUND,self.answer,UPDATED-12,UPDATED,ROUND]
        self.description='USDG / USD'
        self.feed_decimals=8
        self.token_decimals=6
        self.chain=4663
        self.chain_verified=False
        self.feed_code='0x60006000'
        self.failed=False
        self.calls=[]
        self.route_output=2500000  # 0.001 ETH -> 2.5 USDG, including route fee
        self.unfilled=0
        self.hooks=0
        self.no_pairs=False
        self.bad_factory=False
        self.bad_pool=False
        self.router=load('ramses_router')
        self.factory=load('ramses_factory')
        implementation=load('ramses_pool_implementation')['address'][2:]
        self.pool_code=('0x363d3d373d3d3d3d61002c806035363936013d73'+implementation
            +'5af43d3d93803e603357fd5bf3'+WNATIVE[2:]+USDG_ASSET[2:]+'000a002c')

    def verify_chain(self):
        self.call('eth_chainId',[])
        self.chain_verified=True
        return self.chain

    def batch(self,calls,*,scope):
        return [self.call(method,params,scope=scope) for method,params in calls]

    def call(self,method,params,*,scope=None):
        self.calls.append((method,params,scope))
        if self.failed:raise OSError('https://example.invalid/private-provider-secret')
        if method=='eth_chainId':return hex(self.chain)
        if not self.chain_verified:raise AssertionError('provider_chain_identity_unverified')
        if method=='eth_getBlockByNumber':
            return dict(number='0x4bdc170',hash='0x'+'12'*32,timestamp=hex(self.now))
        if method=='eth_getCode':
            address=params[0].lower()
            if address==USDG_FEED.lower():return self.feed_code
            if address==self.router['address'].lower():return self.router['runtimeBytecode']['onchainBytecode']
            if address==self.factory['address'].lower():
                return '0x6000' if self.bad_factory else self.factory['runtimeBytecode']['onchainBytecode']
            if address==POOL:return '0x6000' if self.bad_pool else self.pool_code
            if address in (USDG_ASSET,AGGREGATOR):return '0x6000'
        if method=='eth_call':
            address=params[0]['to'].lower();data=params[0]['data']
            if address==USDG_FEED.lower():
                reads={
                    calldata('description()'):text_abi(self.description),
                    calldata('decimals()'):abi(self.feed_decimals),
                    calldata('latestRoundData()'):abi(*self.round),
                    calldata('aggregator()'):abi(AGGREGATOR),
                    calldata('version()'):abi(6),
                }
                return reads[data]
            if address==USDG_ASSET and data==calldata('decimals()'):return abi(self.token_decimals)
            if address==self.router['address'].lower() and data==calldata('getWNATIVE()'):return abi(WNATIVE)
            if address==self.factory['address'].lower():
                if data!=calldata('getAllLBPairs(address,address)',WNATIVE,USDG_ASSET):raise AssertionError('wrong route tokens')
                return abi(32,0) if self.no_pairs else abi(32,1,10,POOL,1,0)
            if address==POOL:
                if data==calldata('getLBHooksParameters()'):return abi(self.hooks)
                if data==calldata('getSwapOut(uint128,bool)',10**15,1):return abi(self.unfilled,self.route_output,1000)
        raise AssertionError('unexpected read-only RPC call')


class RobinhoodUSDTests(unittest.TestCase):
    def setUp(self):
        self.rpc=ReadRPC()
        clock=patch('meme_machine.runtime.usd_valuation.time.time',side_effect=lambda:self.rpc.now)
        clock.start();self.addCleanup(clock.stop)

    def value(self):return robinhood_usd(self.rpc,now=self.rpc.now)

    def unavailable(self,reason=None):
        with self.assertRaisesRegex(ValuationUnavailable,reason or 'VALUATION_UNAVAILABLE:USDG/USD'):
            self.value()

    def test_block_acquired_after_caller_time_succeeds(self):
        self.rpc.now=NOW+3
        self.rpc.round=[ROUND,100000000,NOW+1,NOW+2,ROUND]
        value=robinhood_usd(self.rpc,now=NOW)
        self.assertEqual(value.observed_at,NOW+2)
        self.assertEqual(value.amount(1000000,NOW+3),Decimal('1'))

    def test_future_block_after_completion_fails(self):
        original=self.rpc.call
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_getBlockByNumber':result['timestamp']=hex(NOW+4)
            return result
        with patch.object(self.rpc,'call',side_effect=call):
            self.unavailable('invalid_block_time')

    def test_provider_delay_does_not_refresh_stale_oracle(self):
        self.rpc.now=UPDATED+USDG_HEARTBEAT+3
        with self.assertRaisesRegex(ValuationUnavailable,'stale_round'):
            robinhood_usd(self.rpc,now=UPDATED+USDG_HEARTBEAT-1)

    def test_route_expiring_during_transport_fails_at_completion(self):
        original=self.rpc.call
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_call' and params[0]['data']==calldata('getSwapOut(uint128,bool)',10**15,1):
                self.rpc.now=NOW+6
            return result
        with patch.object(self.rpc,'call',side_effect=call):
            with self.assertRaises(ValuationUnavailable):NativeValueReader('pons',rpc=self.rpc)(NOW)

    def test_verified_readback_decode_and_decimal_normalization(self):
        value=self.value()
        self.assertEqual(value.usd_per_unit,Decimal('1.00013961'))
        self.assertEqual((value.asset,value.decimals),('USDG',6))
        self.assertEqual(value.amount(125000000,NOW),Decimal('125.01745125'))
        self.assertEqual(value.observed_at,UPDATED)
        self.assertEqual(value.valid_until,UPDATED+86400)
        self.assertEqual(len(value.evidence_hash),64)

    def test_positive_sub_parity_answer_reflects_depeg(self):
        self.rpc.round[1]=80000000
        self.assertEqual(self.value().amount(1000000,NOW),Decimal('.8'))

    def test_heartbeat_boundary_is_inclusive_and_never_extended(self):
        self.rpc.now=UPDATED+USDG_HEARTBEAT
        value=self.value()
        self.assertEqual(value.valid_until,self.rpc.now)
        self.rpc.now+=1
        self.unavailable('stale_round')

    def test_zero_and_negative_answer_rejected(self):
        for answer in (0,-1):
            with self.subTest(answer=answer):
                self.rpc.round[1]=answer;self.unavailable('nonpositive_answer')

    def test_incomplete_future_and_older_answered_rounds_rejected(self):
        for fields in (
            [0,100,UPDATED,UPDATED,ROUND],
            [1,100,UPDATED,UPDATED,1],
            [1<<64,100,UPDATED,UPDATED,1<<64],
            [ROUND,100,0,UPDATED,ROUND],
            [ROUND,100,UPDATED,0,ROUND],
            [ROUND,100,UPDATED+1,UPDATED,ROUND],
            [ROUND,100,NOW+1,NOW+1,ROUND],
            [ROUND,100,UPDATED,UPDATED,ROUND-1],
            [ROUND,100,UPDATED,UPDATED,(2<<64)+121],
            [1<<80,100,UPDATED,UPDATED,1<<80],
        ):
            with self.subTest(fields=fields):
                self.rpc.round=fields;self.unavailable()

    def test_malformed_round_length_and_hex_rejected(self):
        original=self.rpc.call
        for raw in ('0x','0xgg',abi(ROUND,1),abi(*self.rpc.round)+'00'):
            with self.subTest(raw=raw):
                def call(method,params,**kw):
                    if method=='eth_call' and params[0]['data']==calldata('latestRoundData()'):return raw
                    return original(method,params,**kw)
                with patch.object(self.rpc,'call',side_effect=call):self.unavailable()

    def test_wrong_feed_description_rejected(self):
        for description in ('USDC / USD','USDG/USD','USDG / EUR'):
            with self.subTest(description=description):
                self.rpc.description=description;self.unavailable('wrong_feed_description')

    def test_wrong_feed_decimals_or_invalid_padding_rejected(self):
        for decimals in (0,6,18,256):
            with self.subTest(decimals=decimals):
                self.rpc.feed_decimals=decimals;self.unavailable()

    def test_missing_contract_code_rejected(self):
        for code in ('0x','0x00','0xxyz'):
            with self.subTest(code=code):self.rpc.feed_code=code;self.unavailable()

    def test_wrong_chain_rejected(self):
        self.rpc.chain=1;self.unavailable('wrong_chain')

    def test_exact_proxy_and_token_addresses_and_read_only_methods(self):
        self.value()
        calls=[params[0]['to'] for method,params,_ in self.rpc.calls if method=='eth_call']
        self.assertTrue(all(address in (USDG_FEED,USDG_ASSET) for address in calls))
        self.assertEqual(USDG_FEED,'0x61B7e5650328764B076A108EFF5fa7282a1B9aD2')
        self.assertLessEqual(set(method for method,_,_ in self.rpc.calls),
            {'eth_chainId','eth_getCode','eth_call','eth_getBlockByNumber'})

    def test_unavailable_rpc_has_no_price_fallback_or_credential_leak(self):
        self.rpc.failed=True
        with self.assertRaises(ValuationUnavailable) as caught:self.value()
        self.assertNotIn('private-provider-secret',str(caught.exception))
        self.assertIn('RPC_unavailable_or_invalid',str(caught.exception))

    def test_missing_config_fails_without_market_io(self):
        with patch.dict('os.environ',{},clear=True),patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            with self.assertRaises(ValuationUnavailable):robinhood_usd(now=NOW)

    def test_cache_reuses_only_within_sixty_seconds(self):
        reader=NativeValueReader('ramses',rpc=self.rpc)
        first=reader(NOW);count=len(self.rpc.calls)
        self.assertIs(reader(NOW+60),first)
        self.assertEqual(len(self.rpc.calls),count)
        self.rpc.now=NOW+61;self.rpc.round[1]=90000000
        self.assertEqual(reader(NOW+61).usd_per_unit,Decimal('.9'))
        self.assertGreater(len(self.rpc.calls),count)

    def test_expired_cache_does_not_fallback_during_outage(self):
        reader=NativeValueReader('ramses',rpc=self.rpc)
        value=reader(NOW);self.rpc.failed=True
        self.assertIs(reader(NOW+59),value)
        with self.assertRaises(ValuationUnavailable):reader(NOW+61)
        from meme_machine.runtime.status import snapshot
        self.assertEqual(snapshot()['phase'],'VALUATION_UNAVAILABLE')

    def test_cache_never_extends_oracle_heartbeat(self):
        self.rpc.now=UPDATED+USDG_HEARTBEAT-1
        reader=NativeValueReader('ramses',rpc=self.rpc)
        reader(self.rpc.now)
        self.rpc.now+=2
        with self.assertRaisesRegex(ValuationUnavailable,'stale_round'):reader(self.rpc.now)

    def test_ramses_usdg_to_usd_and_exact_quote_identity(self):
        book=SimpleNamespace(quote_asset=USDG_ASSET.upper())
        value=NativeValueReader('ramses',book,rpc=self.rpc)(NOW)
        self.assertEqual(value.amount(1000000,NOW),Decimal('1.00013961'))
        book.quote_asset=WNATIVE
        with self.assertRaisesRegex(ValuationUnavailable,'wrong_Ramses_quote_asset'):
            NativeValueReader('ramses',book,rpc=self.rpc)(NOW)

    def test_usdg_token_decimals_must_match_accounting_units(self):
        self.rpc.token_decimals=18;self.unavailable('wrong_USDG_token_decimals')

    def test_wrong_proxy_interface_and_address_padding_rejected(self):
        original=self.rpc.call
        for name,raw in (('aggregator()',abi(0)),('aggregator()',abi(1<<160)),('version()',abi(5))):
            with self.subTest(name=name,raw=raw):
                def call(method,params,**kw):
                    if method=='eth_call' and params[0]['data']==calldata(name):return raw
                    return original(method,params,**kw)
                with patch.object(self.rpc,'call',side_effect=call):self.unavailable()

    def test_round_must_exist_at_pinned_block(self):
        original=self.rpc.call
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_getBlockByNumber':result['timestamp']=hex(UPDATED-1)
            return result
        with patch.object(self.rpc,'call',side_effect=call):self.unavailable('round_after_pinned_block')

    def test_pons_native_to_authenticated_executable_usdg_to_usd(self):
        value=NativeValueReader('pons',rpc=self.rpc)(NOW)
        self.assertEqual((value.asset,value.decimals),('ETH',18))
        self.assertEqual(value.usd_per_unit,Decimal('2500.349025'))
        self.assertEqual(value.amount(10**15,NOW),Decimal('2.500349025'))
        self.assertEqual(value.valid_until,NOW+5)
        self.assertLessEqual(len(value.evidence_id),150)
        # $125 family equity is translated by this live composed rate.
        capital=int(Decimal('125')*Decimal(10**18)/value.usd_per_unit)
        self.assertLessEqual(value.amount(capital,NOW),Decimal('125'))
        self.assertLess(Decimal('125')-value.amount(capital,NOW),value.amount(1,NOW))

    def test_pons_execution_capacity_and_route_identity_fail_closed(self):
        for field,value in (('no_pairs',True),('unfilled',1),('route_output',0),
                ('hooks',1),('bad_factory',True),('bad_pool',True)):
            with self.subTest(field=field):
                rpc=ReadRPC();setattr(rpc,field,value)
                with self.assertRaises(ValuationUnavailable):NativeValueReader('pons',rpc=rpc)(NOW)

    def test_pons_quote_cache_expires_without_extending_five_second_window(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        first=reader(NOW);count=len(self.rpc.calls)
        self.assertIs(reader(NOW+5),first)
        self.assertEqual(len(self.rpc.calls),count)
        self.rpc.now+=6;self.rpc.route_output=2000000
        self.assertEqual(reader(self.rpc.now).usd_per_unit,Decimal('2000.27922'))
        self.assertGreater(len(self.rpc.calls),count)
        # A fresh production RPC session must verify chain even with a cached oracle.
        self.assertGreaterEqual(sum(1 for method,_,_ in self.rpc.calls if method=='eth_chainId'),2)

    def test_pons_concurrent_use_refreshes_before_original_cache_expiration(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        first=reader(NOW);count=len(self.rpc.calls)
        self.rpc.now=NOW+4
        refreshed=reader(NOW+4,valid_through=NOW+7)
        self.assertIsNot(refreshed,first)
        self.assertGreater(len(self.rpc.calls),count)
        self.assertEqual(first.valid_until,NOW+5)
        self.assertEqual(refreshed.valid_until,NOW+9)
        self.assertEqual(refreshed.amount(10**15,NOW+7),Decimal('2.500349025'))
        with self.assertRaises(ValuationUnavailable):first.amount(1,NOW+7)

    def test_pons_concurrent_use_reuses_compatible_cache_without_provider_work(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        first=reader(NOW);count=len(self.rpc.calls)
        self.rpc.now=NOW+2
        self.assertIs(reader(NOW+2,valid_through=NOW+5),first)
        self.assertEqual(len(self.rpc.calls),count)

    def test_pons_consumption_deadline_cannot_extend_quote_or_hide_outage(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        first=reader(NOW);self.rpc.now=NOW+4;self.rpc.failed=True
        with self.assertRaises(ValuationUnavailable):reader(NOW+4,valid_through=NOW+7)
        self.assertEqual(first.valid_until,NOW+5)
        self.rpc.failed=False
        with self.assertRaises(ValuationUnavailable):reader(NOW+4,valid_through=NOW+20)
        self.assertLessEqual(reader.cached.valid_until,NOW+9)

    def test_invalid_consumption_deadline_fails_before_provider_acquisition(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        for deadline in (True,NOW-1,Decimal(NOW+3),'later'):
            with self.subTest(deadline=deadline):
                with self.assertRaises(ValuationUnavailable):reader(NOW,valid_through=deadline)
        self.assertEqual(self.rpc.calls,[])

    def test_pons_cached_oracle_refresh_verifies_new_provider_session(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        reader(NOW)
        fresh=ReadRPC();fresh.now=NOW+6
        reader.rpc=fresh
        self.assertEqual(reader(NOW+6).usd_per_unit,Decimal('2500.349025'))
        self.assertTrue(fresh.chain_verified)
        self.assertNotIn(calldata('latestRoundData()'),
            [params[0]['data'] for method,params,_ in fresh.calls if method=='eth_call'])

    def test_pons_oracle_and_conversion_reuse_one_pinned_block(self):
        NativeValueReader('pons',rpc=self.rpc)(NOW)
        self.assertEqual(sum(method=='eth_getBlockByNumber' and params[0]=='latest'
            for method,params,_ in self.rpc.calls),1)
        self.assertEqual(self.rpc.calls[-1][:2],('eth_getBlockByNumber',['0x4bdc170',False]))
        blocks=[params[1] for method,params,_ in self.rpc.calls if method in ('eth_call','eth_getCode')]
        self.assertEqual(set(blocks),{'0x4bdc170'})

    def test_pons_currency_fence_runs_after_route_state_and_refuses_reorganization(self):
        original=self.rpc.call;fork=[False];reader=NativeValueReader('pons',rpc=self.rpc)
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_call' and params[0]['data']==calldata('getSwapOut(uint128,bool)',10**15,1):
                fork[0]=True
            if method=='eth_getBlockByNumber' and params[0]!='latest' and fork[0]:
                result['hash']='0x'+'34'*32
            return result
        with patch.object(self.rpc,'call',side_effect=call):
            with self.assertRaisesRegex(ValuationUnavailable,'canonical_block_changed'):reader(NOW)
        self.assertIsNone(reader.cached);self.assertIsNone(reader.oracle)
        self.assertIsNone(reader.oracle_block);self.assertFalse(reader.route_state)
        self.assertEqual(self.rpc.calls[-1][0],'eth_getBlockByNumber')
        # Refusal never permanently rejects a future canonical observation.
        self.assertEqual(reader(NOW).usd_per_unit,Decimal('2500.349025'))

    def test_pons_currency_fence_compares_numeric_identity_without_encoding_veto(self):
        original=self.rpc.call
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_getBlockByNumber' and params[0]!='latest':result['number']='0x4BDC170'
            return result
        with patch.object(self.rpc,'call',side_effect=call):
            self.assertEqual(NativeValueReader('pons',rpc=self.rpc)(NOW).usd_per_unit,Decimal('2500.349025'))

    def test_concurrent_pons_currency_consumers_share_one_complete_acquisition(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        entered=threading.Event();release=threading.Event();values=[];errors=[]
        original=self.rpc.call
        def call(method,params,**kw):
            if method=='eth_getBlockByNumber' and params[0]=='latest':
                entered.set()
                if not release.wait(2):raise AssertionError('fixture_release_missing')
            return original(method,params,**kw)
        def consume():
            try:values.append(reader(NOW))
            except Exception as error:errors.append(error)
        with patch.object(self.rpc,'call',side_effect=call):
            threads=[threading.Thread(target=consume) for _ in range(8)]
            try:
                for thread in threads:thread.start()
                self.assertTrue(entered.wait(2))
            finally:
                release.set()
                for thread in threads:thread.join(3)
        self.assertFalse(errors);self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(len(values),8);self.assertTrue(all(v is values[0] for v in values))
        self.assertEqual(sum(m=='eth_getBlockByNumber' and p[0]=='latest' for m,p,_ in self.rpc.calls),1)
        self.assertEqual(sum(m=='eth_chainId' for m,_,_ in self.rpc.calls),1)
        self.assertEqual(len(self.rpc.calls),19)
        self.assertEqual(values[0].amount(10**15,NOW),Decimal('2.500349025'))
        self.assertEqual(values[1].amount(3*10**15,NOW),Decimal('7.501047075'))

    def test_local_currency_wait_cannot_renew_or_return_expired_evidence(self):
        reader=NativeValueReader('pons',rpc=self.rpc);first=reader(NOW)
        started=threading.Event();values=[]
        def consume():started.set();values.append(reader(NOW))
        with reader._lock:
            thread=threading.Thread(target=consume);thread.start()
            self.assertTrue(started.wait(2))
            self.rpc.now=NOW+6;self.rpc.route_output=2000000
        thread.join(3);self.assertFalse(thread.is_alive())
        self.assertIsNot(values[0],first)
        self.assertEqual(values[0].observed_at,NOW+6);self.assertEqual(values[0].valid_until,NOW+11)
        self.assertEqual(values[0].usd_per_unit,Decimal('2000.27922'))

    def test_pons_cached_oracle_block_remains_an_independent_canonical_obligation(self):
        reader=NativeValueReader('pons',rpc=self.rpc);reader(NOW)
        original=self.rpc.call;self.rpc.now=NOW+6
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_getBlockByNumber':
                result.update(number='0x4bdc171',hash='0x'+'34'*32)
                if params[0]=='0x4bdc170':result.update(number=params[0],hash='0x'+'56'*32)
            return result
        with patch.object(self.rpc,'call',side_effect=call):
            with self.assertRaisesRegex(ValuationUnavailable,'canonical_block_changed'):reader(NOW+6)
            self.assertIsNone(reader.oracle)
            # Fresh oracle and route on the new canonical block restore safely.
            value=reader(NOW+6)
            self.assertEqual(value.valid_until,NOW+11)
            self.assertEqual(reader.oracle_block[0],int('4bdc171',16))

    def test_pons_currency_fence_partial_response_and_delay_cannot_publish_or_refresh(self):
        original=self.rpc.batch
        def partial(calls,**kw):
            result=original(calls,**kw)
            return [] if calls[0][0]=='eth_getBlockByNumber' else result
        reader=NativeValueReader('pons',rpc=self.rpc)
        with patch.object(self.rpc,'batch',side_effect=partial):
            with self.assertRaisesRegex(ValuationUnavailable,'canonical_block_proof_incomplete'):reader(NOW)
        self.assertIsNone(reader.cached)
        def delayed(calls,**kw):
            result=original(calls,**kw)
            if calls[0][0]=='eth_getBlockByNumber':self.rpc.now=NOW+6
            return result
        with patch.object(self.rpc,'batch',side_effect=delayed):
            with self.assertRaises(ValuationUnavailable):reader(NOW)
        self.assertIsNone(reader.cached)

    def test_pons_feed_depeg_is_composed_without_fixed_dollar_fallback(self):
        self.rpc.round[1]=80000000
        self.assertEqual(NativeValueReader('pons',rpc=self.rpc)(NOW).usd_per_unit,Decimal('2000'))

    def test_pons_transport_delay_cannot_extend_execution_freshness(self):
        with patch('meme_machine.runtime.usd_valuation.time.monotonic',side_effect=[0,6]):
            with self.assertRaises(ValuationUnavailable):NativeValueReader('pons',rpc=self.rpc)(NOW)

    def test_outage_preserves_shared_capital_and_existing_positions(self):
        from meme_machine.portfolio_accounting import PortfolioAccounting,inception_receipt,LANES
        from meme_machine.runtime.native_boundary import NativeBoundary
        from meme_machine.runtime.usd_valuation import utc
        from meme_machine.runtime.journal import digest
        ids=dict(source_sha='a'*40,policy_hash='b'*64,config_hash='c'*64)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'offline-fixture.sqlite'
            with closing(PortfolioAccounting(path)) as account:
                account.establish_inception(inception_receipt('offline-usdg-fixture',utc(NOW),'offline-inception'),
                    portfolio_identities=ids,lane_identities={lane:ids for lane in LANES})
                account.configure_family_sleeves()
            reader=NativeValueReader('ramses',rpc=self.rpc)
            boundary=NativeBoundary(path,'ramses',SimpleNamespace(),value_reader=reader)
            value=reader(NOW)
            for key,kind,data in (
                ('reserve','reserve',{'amount':'6.25'}),
                ('enter','enter',{'asset':POOL,'basis':'6.25','fee':'0','strategy_id':'ramses'}),
            ):
                boundary.client.deliver('existing',event_key=key,journal_hash=digest([key,data]),kind=kind,
                    at=utc(NOW),data=data,value_evidence=value.evidence(NOW) if kind=='enter' else None)
            with closing(PortfolioAccounting(path)) as account:before=account.snapshot()
            self.rpc.failed=True
            for native,action in (('new','reserved'),('existing','settled')):
                with self.assertRaises(ValuationUnavailable):
                    boundary.record(native,action,{'reserved':1000000},None,at=NOW+61,checksum='b'*64)
            with closing(PortfolioAccounting(path)) as account:self.assertEqual(account.snapshot(),before)
            self.assertFalse(boundary.prepared)
            self.assertFalse(boundary.client.pending())

    def test_unavailable_robinhood_does_not_affect_solana_reader_or_decoder(self):
        from meme_machine.runtime.usd_valuation import USDValue
        for lane in ('pump','meteora'):
            reader=NativeValueReader(lane)
            reader.cached=USDValue('SOL',9,Decimal('100'),NOW,NOW+120,'offline-sol','a'*64)
            with patch('meme_machine.runtime.usd_valuation.robinhood_usd',side_effect=ValuationUnavailable('offline outage')):
                self.assertEqual(reader(NOW).amount(10**9,NOW),Decimal('100'))
        old=baseline('meme_machine/runtime/usd_valuation.py').decode()
        current=(ROOT/'meme_machine/runtime/usd_valuation.py').read_text()
        def decoder(source):
            node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='sol_usd')
            # The unchanged decoder now runs under the canonical exact-money
            # context. Compare the oracle parsing/finality/conversion body.
            node.decorator_list=[]
            return ast.dump(node)
        self.assertEqual(decoder(old),decoder(current))

    def test_strategy_sources_and_nine_change_tests_byte_unchanged(self):
        # USD valuation originally had no authority to alter trading source.
        # Keep that economic guard and the original nine changes. The owner's
        # PR #129 finalization names e1070404 as the implementation predecessor;
        # later reviewed transport/storage repairs are no longer USD changes.
        assert_holding_delta(self,'tests/test_operational_nine.py',
            baseline('tests/test_operational_nine.py'),(ROOT/'tests/test_operational_nine.py').read_bytes())
        economic_reference='b1f215edd3dc079b623401c7e09e9c91a380e6a0'
        for rel in ('meme_machine/lanes/pump/pump_acceleration_strategy.py',
                    'meme_machine/lanes/pump/pumpswap_survivor.py',
                    'meme_machine/lanes/pons/pons_selective_continuation.py',
                    'meme_machine/runtime/directional_continuation.py',
                    'meme_machine/runtime/survivor_risk.py',
                    'operational/nine-change-implementation.json'):
            original=subprocess.check_output(['git','show',economic_reference+':'+rel],cwd=ROOT)
            assert_holding_delta(self,rel,original,(ROOT/rel).read_bytes())
        rel='meme_machine/lanes/pons/pons_postgrad_survivor.py'
        original=subprocess.check_output(['git','show',economic_reference+':'+rel],cwd=ROOT)
        def survivor_economics(content):
            # Explicit owner exception: remove the two-position selection veto.
            # Policy identity and every qualification still pin; the owner's
            # holding-age exit removal is separately pinned below.
            return [ast.dump(n) for n in ast.parse(content).body
                if not isinstance(n,ast.FunctionDef) or n.name not in ('select_entries','exit_action')]
        self.assertEqual(survivor_economics(original),survivor_economics((ROOT/rel).read_bytes()))
        approved=ast.parse((ROOT/rel).read_bytes())
        node=next(n for n in approved.body if isinstance(n,ast.FunctionDef) and n.name=='exit_action')
        self.assertEqual(__import__('hashlib').sha256(ast.dump(node).encode()).hexdigest(),HOLDING_DELTAS[rel]['exit_action'])
        active='e1070404849dfa86eb3e47d57cf24263b2fefc25'
        def source(path):
            return subprocess.check_output(['git','show',active+':'+path],cwd=ROOT)
        paths=subprocess.check_output(['git','ls-tree','-r','--name-only',active,'meme_machine/lanes'],cwd=ROOT,text=True).splitlines()
        infrastructure={'meme_machine/lanes/pons/pons_historical.py',
                        'meme_machine/lanes/pons/pons_history.py',
                        'meme_machine/lanes/pons/pons_survivor_runtime.py',
                        'meme_machine/lanes/pons/pons_natural_observation.py',
                        'meme_machine/lanes/pons/pons_selective_cohort.py',
                        'meme_machine/lanes/pons/pons_selective_v4.py',
                        'meme_machine/lanes/pons/pons_quotes.py',
                        'meme_machine/lanes/pons/pons_selective_paper.py',
                        'meme_machine/lanes/pons/pons_current_workers.py',
                        'meme_machine/lanes/pons/pons_selective_acquisition.py',
                        'meme_machine/lanes/pons/provider_topology.py',
                        'meme_machine/lanes/pons/provider_admission.py',
                        'meme_machine/lanes/pons/provider.py',
                        'meme_machine/lanes/pons/sequencer_feed.py',
                        'meme_machine/lanes/pons/abi.py'}
        for rel in paths:
            if rel not in infrastructure:assert_holding_delta(self,rel,source(rel),(ROOT/rel).read_bytes())
        for rel in ('meme_machine/runtime/directional_continuation.py','meme_machine/runtime/survivor_risk.py',
                    'operational/nine-change-implementation.json'):
            assert_holding_delta(self,rel,source(rel),(ROOT/rel).read_bytes())
        rel='meme_machine/lanes/pons/pons_history.py'
        # The only history reducer change is transport work order near the
        # original expiry. All native append, recovery and retention math pins.
        def history_methods(content,*,reviewed=False):
            cls=next(n for n in ast.parse(content).body if isinstance(n,ast.ClassDef))
            if reviewed:
                for name in ('__init__','_quality_rank','qualification_turn'):
                    node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
                    assert_attention_node(self,rel,'PonsHistory.'+name,node)
            # The reviewed attention additions do not alter any history reducer.
            next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__').body=[ast.Pass()]
            return {n.name:ast.dump(n) for n in cls.body if isinstance(n,ast.FunctionDef)
                    and n.name not in ('qualification_turn','_quality_rank')}
        self.assertEqual(history_methods((ROOT/rel).read_bytes(),reviewed=True),history_methods(source(rel)))
        rel='meme_machine/lanes/pons/pons_survivor_runtime.py'
        original=ast.parse(source(rel));current=ast.parse((ROOT/rel).read_bytes())
        def functions(tree):
            return {n.name:n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        old=functions(original);new=functions(current)
        for name,node in old.items():
            if name=='Quotes':
                old_quotes=functions(node);new_quotes=functions(new[name])
                for method,value in old_quotes.items():
                    value.decorator_list=[];new_quotes[method].decorator_list=[]
                    self.assertEqual(ast.dump(value),ast.dump(new_quotes[method]),rel+':Quotes.'+method)
            elif name!='Runtime':self.assertEqual(ast.dump(node),ast.dump(new[name]),rel+':'+name)
        old_methods=functions(old['Runtime']);new_methods=functions(new['Runtime'])
        mechanical={'__init__','historical_preparation_step','_provider','discover','_bootstrap_cursor',
                    '_increment_candidates','reconstruct','step','_prepare_held_acquisition','_manage_position',
                    '_position','exit_quote','validate_exit'}
        for name,node in old_methods.items():
            if 'Runtime.'+name in ATTENTION_DELTAS[rel]:
                assert_attention_node(self,rel,'Runtime.'+name,new_methods[name])
                if name!='reconstruct':continue
            if name not in mechanical:
                node.decorator_list=[];new_methods[name].decorator_list=[]
                self.assertEqual(ast.dump(node),ast.dump(new_methods[name]),rel+':'+name)
        # Quote timing and individual completeness authority change. The actual
        # price/buyer reducers, sizing and executable-capacity expression pin.
        before=old_methods['reconstruct'];after=new_methods['reconstruct']
        def facts_keywords(node):
            call=next(n.value for n in ast.walk(node) if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Attribute) and t.attr=='facts' for t in n.targets))
            return {k.arg:ast.dump(k.value) for k in call.keywords
                    if k.arg not in ('continuity_complete','execution')}
        self.assertEqual(facts_keywords(before),facts_keywords(after))
        def economic_expressions(node):
            assigns={t.id:ast.dump(n.value) for n in ast.walk(node) if isinstance(n,ast.Assign)
                for t in n.targets if isinstance(t,ast.Name) and t.id in ('flow','sizing','cap','capacity')}
            assigns['window']=ast.dump(next(n for n in ast.walk(node) if isinstance(n,ast.FunctionDef) and n.name=='window'))
            return assigns
        self.assertEqual(economic_expressions(before),economic_expressions(after))
        # This release changes acquisition order/reuse, not native settlement
        # arithmetic or its exact-quantity/five-second commit prerequisites.
        def net_expressions(node):
            return {ast.dump(k.value) for n in ast.walk(node) if isinstance(n,ast.Call)
                for k in n.keywords if k.arg in ('net_proceeds','gas')}
        self.assertEqual(net_expressions(old_methods['exit_quote']),net_expressions(new_methods['exit_quote']))
        def stale_expression(node):
            return ast.dump(next(n.test for n in ast.walk(node) if isinstance(n,ast.If)
                and any(isinstance(a,ast.Constant) and a.value=='survivor_exit_quote_stale'
                    for a in ast.walk(n))))
        self.assertEqual(stale_expression(old_methods['validate_exit']),stale_expression(new_methods['validate_exit']))
        def constants(tree):
            return [ast.dump(n) for n in tree.body if isinstance(n,(ast.Assign,ast.AnnAssign))]
        self.assertEqual(constants(original),constants(current))

    def test_reviewed_attention_nodes_reject_unapproved_edits(self):
        from copy import deepcopy
        reviewed={relative:{**ATTENTION_DELTAS.get(relative,{}),**OPERATION_DELTAS.get(relative,{})}
                  for relative in ATTENTION_DELTAS.keys()|OPERATION_DELTAS.keys()}
        for relative,methods in reviewed.items():
            tree=ast.parse((ROOT/relative).read_text())
            for name in methods:
                node=tree
                for part in name.split('.'):
                    node=next(n for n in node.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==part)
                assert_attention_node(self,relative,name,node)
                changed=deepcopy(node);changed.body.append(ast.Expr(ast.Constant('unapproved change')))
                with self.assertRaises(AssertionError):assert_attention_node(self,relative,name,changed)

    def test_reviewed_acquisition_source_rejects_any_unapproved_change(self):
        for relative,reviewed in ACQUISITION_SOURCE_DELTAS.items():
            original=subprocess.check_output(['git','show','e1070404849dfa86eb3e47d57cf24263b2fefc25:'+relative],cwd=ROOT)
            approved=subprocess.check_output(['git','show',reviewed['reference']+':'+relative],cwd=ROOT)
            delta=b"and row.get('app_id') and row.get('team_id')"
            self.assertEqual(approved.count(delta),1)
            approved=approved.replace(delta,b"and row.get('app_id')")
            self.assertEqual(approved,(ROOT/relative).read_bytes())
            assert_holding_delta(self,relative,original,approved)
            for changed in (approved+b'\n# unreviewed change\n',
                    approved.replace(b'SAFE_BLOCKS = 10',b'SAFE_BLOCKS = 40'),
                    approved.replace(b"and row.get('equal') is True",b"and True")):
                self.assertNotEqual(changed,approved)
                with self.assertRaises(AssertionError):assert_holding_delta(self,relative,original,changed)
            with self.assertRaises(AssertionError):assert_holding_delta(self,relative,original+b'\n',approved)

    def test_reviewed_lifecycle_sources_reject_unapproved_changes_and_preserve_economics(self):
        for relative in LIFECYCLE_SOURCE_DELTAS:
            original=subprocess.check_output(['git','show','e1070404849dfa86eb3e47d57cf24263b2fefc25:'+relative],cwd=ROOT)
            published=subprocess.check_output(['git','show',LIFECYCLE_PACKAGE_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(published,(ROOT/relative).read_bytes())
            assert_holding_delta(self,relative,original,published)
            for changed in (published+b'\n# unreviewed change\n',published.replace(b'False',b'True',1)):
                self.assertNotEqual(changed,published)
                with self.assertRaises(AssertionError):assert_holding_delta(self,relative,original,changed)
        relative='meme_machine/lanes/pons/pons_selective_continuation.py'
        def economic_nodes(content):
            nodes={}
            for node in ast.parse(content).body:
                if isinstance(node,ast.FunctionDef) and node.name=='reentry_regime_reset':
                    nodes[node.name]=ast.dump(node)
                elif isinstance(node,ast.Assign):
                    for target in node.targets:
                        if isinstance(target,ast.Name) and target.id in ('REENTRY_POLICY','ENTRY_THRESHOLDS','EXIT_POLICY','POLICY'):
                            nodes[target.id]=ast.dump(node)
            return nodes
        prior=subprocess.check_output(['git','show',LIFECYCLE_PACKAGE_BASE+':'+relative],cwd=ROOT)
        before=economic_nodes(prior);after=economic_nodes((ROOT/relative).read_bytes())
        self.assertEqual(set(before),{'reentry_regime_reset','REENTRY_POLICY','ENTRY_THRESHOLDS','EXIT_POLICY','POLICY'})
        self.assertEqual(before,after)

    def test_resolved_startup_check_uses_config_only_no_oracle_calls_or_state(self):
        from meme_machine.operational.supervisor import validate_environment
        env={'MM_ROBINHOOD_READ_RPC_URL':'https://robinhood-mainnet.g.alchemy.com/v2/offline-fixture'}
        with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            self.assertIsNone(validate_environment(environ=env))


if __name__=='__main__':unittest.main()
