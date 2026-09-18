from dataclasses import asdict, replace
import copy
import tempfile
import unittest

from robinhood_research import BoundaryError
from robinhood_research.evidence import Stamp, Store, ingest_batch
from robinhood_research.directional import Trade, features
from robinhood_research.protocols import (Launch, PoolKey, prove_graduation,
    classify_discovery, decode_pons_launch, decode_curve_trade, PONS_LAUNCH, PONS_BUY)
from robinhood_research.outcomes import Outcomes, summarize
from robinhood_research.paper import Paper, Quote
from robinhood_research.keccak import keccak256
from robinhood_research.liquidity import Bin, BinDelta, RamsesAdapter, apply_delta, case60, replay60

A, B, C, D, E = [f'0x{i:040x}' for i in range(1,6)]


def stamp(at=120, **kw):
    return replace(Stamp(4663, 1, 'hash1', at, at, 'finalized', 'synthetic'), **kw)


def word(n):
    return '0x' + f'{n:064x}'


def feature_args():
    return dict(market=A, origin='pons_v2_curve', asof=120, launch_at=0,
                coverage_start=0, coverage_end=120, trades=[], liquidity=10000,
                previous_liquidity=9000, full_exit_depth=1000, entry_cost=100,
                round_trip_cost=5, state_stamp=stamp())


def graduation():
    launch = Launch(B, A, C, D, 'pons_v2_curve', E, 'source', stamp(100))
    key = PoolKey(B, C, 10000, 200, D)
    common = dict(stamp=asdict(stamp(120)), pool_id=key.pool_id())
    state = dict(common, factory=E, curve=A, token=B, phase=2, pool_manager=C)
    reg = dict(common, hook=D, curve=A, token=B)
    init = dict(common, key=asdict(key), pool_manager=C)
    return launch, key, state, reg, init


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.s = Store(':memory:')

    def tearDown(self):
        self.s.close()

    def batch(self):
        event = dict(block=1, block_hash='hash1', log_index=0, transaction_hash='tx',
                     address=A, removed=False, data='0x', topics=[])
        return dict(scope='directional', headers=[dict(stamp=asdict(stamp()), parent_hash='hash0', transactions=['tx'])],
                    receipts=[dict(block_hash='hash1', transaction_hash='tx', logs=[event])],
                    logs=[event], addresses={A}, observed_at=120, kind='synthetic')

    def test_duplicate_logs_deduplicate_atomically(self):
        batch = self.batch()
        batch['logs'] *= 2
        self.assertEqual(len(ingest_batch(self.s, **batch)), 1)
        self.assertEqual(self.s.cursor('directional'), (1, 'hash1'))

    def test_missing_log_fails_without_advancing(self):
        batch = self.batch()
        batch['logs'] = []
        with self.assertRaisesRegex(BoundaryError, 'missing_or_unexpected_logs'):
            ingest_batch(self.s, **batch)
        self.assertIsNone(self.s.cursor('directional'))

    def test_missing_receipt(self):
        batch = self.batch()
        batch['receipts'] = []
        with self.assertRaisesRegex(BoundaryError, 'missing_or_duplicate_receipts'):
            ingest_batch(self.s, **batch)

    def test_conflicting_logs(self):
        batch = self.batch()
        batch['logs'].append(dict(batch['logs'][0], data='0x01'))
        with self.assertRaisesRegex(BoundaryError, 'conflicting_logs'):
            ingest_batch(self.s, **batch)

    def test_reorg_and_nonfinalized_fail(self):
        batch = self.batch()
        batch['headers'][0]['stamp']['finality'] = 'sequencer'
        with self.assertRaisesRegex(BoundaryError, 'unfinalized'):
            ingest_batch(self.s, **batch)
        ingest_batch(self.s, **self.batch())
        batch = self.batch()
        batch['headers'][0]['stamp'].update(block=2, block_hash='hash2')
        with self.assertRaisesRegex(BoundaryError, 'reorg_parent_conflict'):
            ingest_batch(self.s, **batch)

    def test_removed_log(self):
        batch = self.batch()
        batch['logs'][0]['removed'] = True
        with self.assertRaisesRegex(BoundaryError, 'removed_log_reorg'):
            ingest_batch(self.s, **batch)

    def test_storage_bound_preserves_evidence(self):
        s = Store(':memory:', max_records=2)
        s.put('decision','a', {'x':1})
        s.put('decision','b', {'x':2})
        with self.assertRaisesRegex(BoundaryError, 'storage_capacity'):
            s.put('decision','c', {'x':3})
        self.assertEqual(s.get('decision','a'), {'x':1})
        with self.assertRaisesRegex(BoundaryError, 'conflicting_immutable'):
            s.put('decision','a', {'x':9})
        s.close()

    def test_storage_transaction_rolls_back_cursor_and_logs(self):
        s = Store(':memory:', max_records=1)
        with self.assertRaisesRegex(BoundaryError, 'storage_capacity'):
            ingest_batch(s, **self.batch())
        self.assertEqual(s.db.execute('SELECT count(*) FROM records').fetchone()[0], 0)
        self.assertIsNone(s.cursor('directional'))
        s.close()


class ProtocolTests(unittest.TestCase):
    def test_ethereum_keccak_not_sha3(self):
        self.assertEqual(keccak256(b'').hex(), 'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470')
        self.assertEqual(keccak256(b'abc').hex(), '4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45')

    def test_launch_and_curve_trade_decode(self):
        log = dict(address=E, topics=[PONS_LAUNCH,word(2),word(1),word(4)],
                   data='0x'+''.join(f'{v:064x}' for v in (3,1,4200)))
        launch = decode_pons_launch(log, stamp(), E)
        self.assertEqual((launch.token,launch.market,launch.quote), (B,A,C))
        trade = dict(address=A, topics=[PONS_BUY,word(4),word(4)],
                     data='0x'+''.join(f'{v:064x}' for v in (100,200,2,3)))
        decoded = decode_curve_trade(trade, launch)
        self.assertEqual((decoded['quote'],decoded['tokens']), (100,200))
        with self.assertRaisesRegex(BoundaryError, 'unverified'):
            decode_pons_launch(log, stamp(kind='natural'), E)

    def test_graduation_exact_pool_lineage(self):
        launch,key,state,reg,init = graduation()
        result = prove_graduation(launch,key=key,factory_state=state,registration=reg,initialization=init,asof=120)
        self.assertEqual(result['pregraduation_source'],'source')
        self.assertEqual(result['market'],key.pool_id())

    def test_unrelated_v4_pool_rejected(self):
        launch,key,state,reg,init = graduation()
        reg['hook'] = E
        with self.assertRaisesRegex(BoundaryError, 'unrelated_v4'):
            prove_graduation(launch,key=key,factory_state=state,registration=reg,initialization=init,asof=120)

    def test_wrong_pool_id_rejected(self):
        launch,key,state,reg,init = graduation()
        state['pool_id'] = 'other'
        with self.assertRaisesRegex(BoundaryError, 'incorrect_pool_identity'):
            prove_graduation(launch,key=key,factory_state=state,registration=reg,initialization=init,asof=120)

    def test_v1_v2_and_nonpons_classification(self):
        for origin in ('pons_v1_v3','pons_v2_curve','non_pons_v4'):
            self.assertEqual(classify_discovery(origin=origin,asset_class='speculative',
                provenance=True,executable=True,kind='synthetic'),origin)
        for asset in ('tokenized_equity','stablecoin','wrapped_major','established'):
            self.assertEqual(classify_discovery(origin='non_pons_v4',asset_class=asset,
                provenance=True,executable=True,kind='synthetic'),'excluded_'+asset)


class FeatureOutcomeTests(unittest.TestCase):
    def test_future_and_stale_evidence_rejected(self):
        for st, reason in ((stamp(121),'future'),(stamp(-1),'stale'),(stamp(120,observed_at=121),'future')):
            args=feature_args()
            args['trades']=[Trade('x',A,B,'buy',100,100,st)]
            with self.assertRaisesRegex(BoundaryError, reason):
                features(**args)

    def test_multiwindow_flows_not_thresholds(self):
        args=feature_args()
        args['trades']=[Trade('a',A,B,'buy',100,100,stamp(100)),
                        Trade('b',A,C,'sell',40,40,stamp(117)),
                        Trade('c',A,D,'buy',80,40,stamp(119))]
        value=features(**args)
        self.assertEqual(value['windows']['5']['net_buy'],40)
        self.assertEqual(value['windows']['30']['net_buy'],140)
        self.assertEqual(value['qualification'],'policy_not_established')

    def test_missing_coverage(self):
        args=feature_args(); args['coverage_start']=1
        with self.assertRaisesRegex(BoundaryError,'incomplete_feature_coverage'):
            features(**args)

    def enroll(self, s, identity='x', origin='pons_v2_curve'):
        o=Outcomes(s)
        o.enroll(identity, features=features(**feature_args()), selected_at=120,entry_cost=100,tokens=10,
                 cohort='natural_unbiased',kind='synthetic',origin=origin)
        return o

    def test_forward_horizon_tails_and_no_future_leak(self):
        s=Store(':memory:'); o=self.enroll(s)
        frozen=s.get('enrollment','x')
        for at,value in ((125,125),(130,200),(135,90)):
            o.observe('x',at=at,observed_at=at,market=A,tokens=10,net_exit_value=value)
        with self.assertRaisesRegex(BoundaryError,'not_due'):
            o.finish('x',15,now=134)
        r=o.finish('x',15,now=135)
        self.assertEqual(r['return_bps'],-1000)
        self.assertTrue(r['sampled_tail_hits']['10000'])
        self.assertTrue(r['sampled_tail_hits']['-1000'])
        self.assertEqual(s.get('enrollment','x'),frozen)
        s.close()

    def test_unavailable_exit_not_survivor_only(self):
        s=Store(':memory:');o=self.enroll(s)
        for at in (125,130,135):
            o.observe('x',at=at,observed_at=at,market=A,tokens=10,net_exit_value=None,
                      reason='impossible_full_position_exit',liquidity_collapse=True)
        r=o.finish('x',15,now=135)
        self.assertEqual(r['status'],'incomplete')
        self.assertIsNone(r['return_bps'])
        summary=list(summarize([r]).values())[0]
        self.assertEqual((summary['enrolled'],summary['incomplete']),(1,1))
        s.close()

    def test_late_observation_not_backdated(self):
        s=Store(':memory:');o=self.enroll(s)
        o.observe('x',at=135,observed_at=150,market=A,tokens=10,net_exit_value=200)
        r=o.finish('x',15,now=135)
        self.assertIsNone(r['return_bps'])
        s.close()


class PaperTests(unittest.TestCase):
    def test_connected_graduation_restart_unavailable_exit_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            path=directory+'/paper.db'
            s=Store(path);p=Paper(s,'directional-synthetic',1000)
            p.reserve('p',market=A,amount=100,gas_budget=10,now=120,features=features(**feature_args()))
            with self.assertRaisesRegex(BoundaryError,'entry_not_due'):
                p.advance('p',now=121,action='entry',quote=Quote(A,'buy',100,20,2,3,stamp(121)))
            p.advance('p',now=122,action='entry',quote=Quote(A,'buy',100,20,2,3,stamp(122)))
            before=p.reconcile();s.close()
            s=Store(path);p=Paper(s,'directional-synthetic',1000)
            self.assertEqual(before,p.reconcile())
            launch,key,state,reg,init=graduation()
            transition=prove_graduation(launch,key=key,factory_state=state,registration=reg,initialization=init,asof=123)
            s.put('graduation',transition['proof_hash'],transition)
            p.advance('p',now=123,action='transition',transition=transition)
            p.advance('p',now=124,action='exit_intent')
            failed=Quote(key.pool_id(),'sell',20,None,2,0,stamp(126),'impossible_full_position_exit')
            r=p.advance('p',now=126,action='exit',quote=failed)
            self.assertEqual((r['status'],r['tokens']),('exit_pending',20))
            count=s.db.execute('SELECT count(*) FROM records').fetchone()[0]
            p.advance('p',now=127,action='exit',quote=replace(failed,stamp=stamp(127)))
            self.assertEqual(count,s.db.execute('SELECT count(*) FROM records').fetchone()[0])
            s.close();s=Store(path);p=Paper(s,'directional-synthetic',1000)
            r=p.advance('p',now=128,action='exit',quote=Quote(key.pool_id(),'sell',20,120,2,1,stamp(128)))
            self.assertEqual(r['pnl'],16)
            self.assertEqual(p.reconcile()['available'],1016)
            with self.assertRaisesRegex(BoundaryError,'exit_not_due'):
                p.advance('p',now=129,action='exit',quote=Quote(key.pool_id(),'sell',20,120,2,1,stamp(129)))
            s.close()

    def test_natural_allocation_disabled_and_capital_isolated(self):
        s=Store(':memory:');p=Paper(s,'x',100)
        with self.assertRaisesRegex(BoundaryError,'policy_not_established'):
            p.reserve('p',market=A,amount=10,gas_budget=2,now=120,features=features(**feature_args()),kind='natural')
        with self.assertRaisesRegex(BoundaryError,'capital_exhausted'):
            p.reserve('p',market=A,amount=100,gas_budget=1,now=120,features=features(**feature_args()))
        self.assertEqual(p.reconcile()['available'],100)
        s.close()


class LiquidityTests(unittest.TestCase):
    def fixture(self):
        bins=[Bin(i,50,50,100,1,1) for i in (1,2,3)]
        return bins

    def case(self, bins=None, warmup=None, proposed=(1,2)):
        bins=bins or self.fixture()
        return case60(bins=bins, proposed=proposed,warmup=warmup or [],asof=120,warmup_start=60,
                      capital=20,costs=1,inventory_risk_reserve=1,stamp=stamp())

    def test_exact_range_liquidity_and_nonzero_activity_not_enough(self):
        b=self.fixture();e=BinDelta(100,100,3,b[2],b[2],'swap',100000,1000,50,1050,10500)
        c=self.case(warmup=[e])
        self.assertEqual(c['range_liquidity'],200)
        self.assertEqual(c['range_volume'],0)
        self.assertEqual(c['near_range_volume'],100000)
        self.assertFalse(c['economic_case'])

    def test_variable_fee_capture_lp_share_and_protocol_exclusion(self):
        b=self.fixture()
        a=BinDelta(90,90,1,b[0],b[0],'swap',100,10,5,15,150000)
        z=BinDelta(100,100,1,b[0],b[0],'swap',100,20,5,25,250000)
        c=self.case(warmup=[a,z])
        self.assertEqual(c['lp_fees'],30)
        self.assertAlmostEqual(c['projected_fees'],30/11)
        self.assertGreater(c['projected_net'],0)

    def test_add_remove_and_unsupported_mutation(self):
        b=self.fixture()[0]; state={1:b};added=replace(b,x=60,y=60,shares=120)
        apply_delta(state,BinDelta(121,121,1,b,added,'add'))
        apply_delta(state,BinDelta(122,122,1,added,b,'remove'))
        self.assertEqual(state[1],b)
        with self.assertRaisesRegex(BoundaryError,'unsupported_mutation'):
            apply_delta(state,BinDelta(123,123,1,b,b,'unknown'))

    def test_bin_identity_and_fee_conservation(self):
        b=self.fixture()[0]
        with self.assertRaisesRegex(BoundaryError,'exact_bin_identity'):
            apply_delta({1:b},BinDelta(121,121,2,b,b,'swap'))
        with self.assertRaisesRegex(BoundaryError,'fee_conservation'):
            apply_delta({1:b},BinDelta(121,121,1,b,b,'swap',100,10,5,10))

    def test_never_partially_and_fully_touched_ranges(self):
        b=self.fixture();c=self.case()
        for touched in ((),(1,),(1,2)):
            events=[BinDelta(130+i,130+i,i,b[i-1],b[i-1],'swap',100,10,0,10,100000) for i in touched]
            r=replay60(case=c,initial=b,events=events,owned_shares={1:10,2:10},
                       liquidation=dict(amount_x=10,net_quote=10,at=180),now=180)
            self.assertEqual(r['touched_bins'],list(touched))
            self.assertEqual(r['fee_income'],len(touched))

    def test_liquidation_unavailable_preserves_inventory(self):
        b=self.fixture();c=self.case()
        r=replay60(case=c,initial=b,events=[],owned_shares={1:10,2:10},liquidation=None,now=180)
        self.assertEqual((r['status'],r['residual_x']),('unresolved',10))

    def test_no_future_warmup_or_hindsight_range(self):
        b=self.fixture();e=BinDelta(121,121,1,b[0],b[0],'swap')
        with self.assertRaisesRegex(BoundaryError,'future'):
            self.case(warmup=[e])
        with self.assertRaisesRegex(BoundaryError,'position_range_mismatch'):
            replay60(case=self.case(),initial=b,events=[],owned_shares={3:10},liquidation=None,now=180)

    def test_ramses_raw_adapter_fails_closed(self):
        with self.assertRaisesRegex(BoundaryError,'unverified'):
            RamsesAdapter().snapshot(A,1)
        with self.assertRaisesRegex(BoundaryError,'unsupported_raw_mutation'):
            RamsesAdapter().decode({})
