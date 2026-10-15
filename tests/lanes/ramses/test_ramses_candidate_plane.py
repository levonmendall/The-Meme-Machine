from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.runtime.robinhood.ramses import RouteIndex
from meme_machine.lanes.ramses import BoundaryError
from meme_machine.lanes.ramses.ramses_strategy import POLICY_HASH, pool_features


class RoutePlaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'plane';self.index=RouteIndex(self.path,POLICY_HASH,source='alchemy')
        self.addCleanup(lambda:self.index.close())
        self.row=dict(pool='pool',token_x='x',token_y='y',quote_side='y')
        self.frontier=dict(number='0x10',hash='hash-a');self.costs={'add_liquidity':10}
    def begin(self,frontier=None,inputs=None):
        return self.index.begin('factory',self.row,frontier or self.frontier,inputs or {'costs':self.costs})
    def check(self,frontier=None,costs=None):
        from types import SimpleNamespace
        rpc=SimpleNamespace(canonical_authority=True,chain_verified=True,provider_fingerprint='offline-authenticated-fixture')
        return self.index.check(rpc,'factory',self.row,frontier or self.frontier,costs or self.costs,{})
    def test_negative_route_is_block_bound_not_immutable(self):
        with patch('meme_machine.lanes.ramses.ramses_costs.quote_native_cycle',return_value=(None,{'reason':'no_executable_bounded_wnative_quote_route'})) as quote:
            self.begin();v=self.check();self.assertTrue(v['skip_deep'])
            self.assertEqual(self.check(),v);self.assertEqual(quote.call_count,1)
            self.index.complete('pool',{'route_preflight':v})
            newer=dict(number='0x11',hash='hash-b');self.begin(newer);self.check(newer)
            self.assertEqual(quote.call_count,2)
    def test_positive_route_does_not_complete_strategy(self):
        self.begin()
        with patch('meme_machine.lanes.ramses.ramses_costs.quote_native_cycle',return_value=({'cost':10},{})):
            self.assertFalse(self.check()['skip_deep'])
        self.assertIsNone(self.index.plane.get(self.index.work['pool']['id'])['completed'])
    def test_error_is_not_negative_capability(self):
        self.begin()
        with patch('meme_machine.lanes.ramses.ramses_costs.quote_native_cycle',side_effect=BoundaryError('provider_http_429')):
            with self.assertRaises(BoundaryError):self.check()
        self.index.fail('pool','provider_http_429')
        self.assertEqual(self.index.plane.snapshot()['candidate_states'],{'authoritative_evidence_failure':1})
        self.assertEqual(self.index.plane.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],0)
    def test_committed_screen_reused_after_restart(self):
        self.begin();value={'decision':{'qualified':False,'reasons':['frozen']},'prestate':{'bins':{}}}
        self.index.complete('pool',value);self.index.close()
        self.index=RouteIndex(self.path,POLICY_HASH,source='alchemy')
        self.assertEqual(self.begin(),value);self.assertEqual(self.index.work,{})
    def test_native_cost_change_invalidates_capability(self):
        self.begin()
        with patch('meme_machine.lanes.ramses.ramses_costs.quote_native_cycle',return_value=(None,{'reason':'no_executable_bounded_wnative_quote_route'})) as quote:
            self.check();self.check(costs={'add_liquidity':11});self.assertEqual(quote.call_count,2)
    def test_new_frontier_fences_deep_result(self):
        self.begin();old=self.index.work['pool']
        with self.assertRaises(BoundaryError):self.begin(dict(number='0x11',hash='hash-b'))
        self.assertFalse(self.index.plane.finish(old,result={'decision':{'qualified':True}}))
    def test_close_releases_inflight_failure(self):
        self.begin();key=self.index.work['pool']['id'];self.index.close()
        self.index=RouteIndex(self.path,POLICY_HASH,source='alchemy')
        self.assertIsNone(self.index.plane.get(key)['claim'])
    def test_active_bin_features_identical_without_deep_bins(self):
        active=1<<23
        state=dict(active=active,step=10,static=[40000,30,600,5000,40000,500,350000],variable=[0,0,active,1000],
            bins={n:dict(reserves=[10**18,10**18],supply=10**18) for n in range(active-100,active+101)})
        small=dict(state,bins={k:v for k,v in state['bins'].items() if abs(k-active)<=1})
        self.assertEqual(pool_features(state,[],'y'),pool_features(small,[],'y'))
