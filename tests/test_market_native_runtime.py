import tempfile
import unittest
from pathlib import Path

from meme_machine.__main__ import _retire_scout_state
from meme_machine.engine import Engine
from meme_machine.market_native_runtime import MarketNativeAuthority, MarketNativeRuntime
from meme_machine.store import Store
from tests.support import evidence, event, SCOUT


class MarketNativeRuntimeTests(unittest.TestCase):
    def test_market_native_authority_uses_real_anchor_without_persisting_scout(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(str(Path(td)/'state.db'),'synthetic',100_000_000,'test')
            engine=Engine(store,[])
            authority=MarketNativeAuthority(engine)
            nomination=event(now=100,id='market-native-anchor')
            ev=evidence(now=100)
            reason=authority.consider(nomination,ev,100)
            self.assertEqual(reason,'qualified')
            self.assertEqual(engine.seeds,set())
            self.assertEqual(store.state['wallets'],{})
            self.assertEqual(store.state['orders']['market-native-anchor']['status'],'reserved')
            self.assertEqual(store.state['funnel']['qualification_attempts'],1)
            store.close()

    def test_retirement_migration_archives_scout_config_and_clears_only_scout_caches(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(str(Path(td)/'state.db'),'synthetic',100_000_000,'test')
            scout=Engine(store,[SCOUT])
            scout.scout([event(now=100,wallet=SCOUT,id='old-scout')],100)
            cash=store.state['cash']
            old_config=store.state['scout_config']
            self.assertTrue(store.state['wallets'])
            self.assertTrue(store.state['seen'])
            self.assertGreater(store.state['progress'],0)
            self.assertTrue(_retire_scout_state(store))
            self.assertEqual(store.state['retired_scout_config'],old_config)
            self.assertNotIn('scout_config',store.state)
            self.assertEqual(store.state['wallets'],{})
            self.assertEqual(store.state['seen'],{})
            self.assertEqual(store.state['progress'],0)
            self.assertEqual(store.state['last_time'],0)
            self.assertEqual(store.state['funnel']['scout_batches'],0)
            self.assertEqual(store.state['funnel']['seed_events'],0)
            self.assertEqual(store.state['funnel']['nominations'],0)
            self.assertEqual(store.state['cash'],cash)
            market_engine=Engine(store,[])
            self.assertEqual(market_engine.seeds,set())
            self.assertFalse(_retire_scout_state(store))
            self.assertEqual(store.state['cash'],cash)
            store.close()

    def test_market_native_runtime_refuses_configured_scouts(self):
        class RPC:
            limit=240;calls=1;http_requests=0;failures=0;cache_hits=0
            url='https://api.mainnet-beta.solana.com'
        class Adapter:
            rpc=RPC()
        with tempfile.TemporaryDirectory() as td:
            store=Store(str(Path(td)/'state.db'),'synthetic',100_000_000,'test')
            engine=Engine(store,[event()['wallet']])
            with self.assertRaisesRegex(ValueError,'scouts_must_be_disabled'):
                MarketNativeRuntime(engine,Adapter(),3300)
            store.close()

    def test_market_native_runtime_reserves_monitoring_rpc_capacity(self):
        class RPC:
            limit=120;calls=1;http_requests=0;failures=0;cache_hits=0
            url='https://api.mainnet-beta.solana.com'
        class Adapter:
            rpc=RPC()
        with tempfile.TemporaryDirectory() as td:
            store=Store(str(Path(td)/'state.db'),'synthetic',100_000_000,'test')
            engine=Engine(store,[])
            with self.assertRaisesRegex(ValueError,'market_native_budget_exceeds'):
                MarketNativeRuntime(engine,Adapter(),3300,preflight_budget=60,full_evidence_budget=20)
            runtime=MarketNativeRuntime(engine,Adapter(),3300,preflight_budget=10,full_evidence_budget=5)
            self.assertFalse(runtime.status()['scout_lane_active'])
            self.assertFalse(runtime.status()['scout_storage_active'])
            self.assertEqual(runtime.status()['configured_scouts'],0)
            store.close()


    def test_provider_rotation_allows_150_preflights_without_spending_monitoring_reserve(self):
        class RPC:
            def __init__(self):
                self.limit=240;self.calls=1;self.http_requests=0;self.failures=0;self.cache_hits=0
                self.url='https://api.mainnet-beta.solana.com'
        class Adapter:
            def __init__(self):
                self.rpc=RPC()
            def concentration_status(self):
                return {'initialized':False}
        with tempfile.TemporaryDirectory() as td:
            store=Store(str(Path(td)/'state.db'),'synthetic',100_000_000,'test')
            engine=Engine(store,[])
            with self.assertRaisesRegex(ValueError,'market_native_budget_exceeds'):
                MarketNativeRuntime(
                    engine,Adapter(),3300,preflight_budget=150,full_evidence_budget=40)
            runtime=MarketNativeRuntime(
                engine,Adapter(),3300,preflight_budget=150,full_evidence_budget=40,
                provider_rotation_threshold=160)
            self.assertEqual(runtime.status()['preflight_budget'],150)
            self.assertEqual(runtime.status()['provider_rotation_threshold'],160)
            runtime.replace_adapter(Adapter())
            self.assertEqual(runtime.status()['provider_rotations'],1)
            self.assertEqual(len(runtime.status()['prior_provider_sessions']),1)
            store.close()


if __name__=='__main__':
    unittest.main()
