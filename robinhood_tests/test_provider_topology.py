import unittest

from robinhood_research import BoundaryError
from robinhood_research.provider_topology import (
    DLMM_ENV,
    DISCOVERY_ENV,
    PRIMARY_ENV,
    SHADOW_ENV,
    PacedRpc,
    ProviderPacer,
    configured_discovery_rpc,
    configured_discovery_recovery_rpc,
    configured_dlmm_rpc,
    configured_rpc,
    configured_shadow_rpc,
    topology_metadata,
)


class _Clock:
    def __init__(self):
        self.now=0.0
        self.sleeps=[]
    def time(self):
        return self.now
    def sleep(self,seconds):
        self.sleeps.append(float(seconds))
        self.now+=float(seconds)


class LaneProviderTests(unittest.TestCase):
    def test_directional_primary_is_two_rps_and_fail_closed(self):
        calls=[]
        rpc=PacedRpc(
            "https://robinhood-mainnet.g.alchemy.com/v2/key",
            role="directional_evidence_primary",
            requests_per_second=2.0,
            transport=lambda method,params: calls.append(method) or "0x1237",
        )
        self.assertEqual(rpc.verify_chain(),4663)
        t=rpc.telemetry()
        self.assertEqual(t["provider_kind"],"alchemy")
        self.assertEqual(t["role"],"directional_evidence_primary")
        self.assertEqual(t["pacing"]["requests_per_second"],2.0)
        self.assertFalse(t["automatic_failover"])
        self.assertEqual(calls,["eth_chainId"])

    def test_configured_directional_does_not_use_shadow_on_failure(self):
        env={
            PRIMARY_ENV:"https://primary.invalid/v2/key",
            SHADOW_ENV:"https://shadow.invalid/key",
        }
        def fail(*_):
            raise BoundaryError("provider_transport_failure")
        rpc=configured_rpc(
            environ=env,limit=10,per_scope=10,retries=0,transport=fail
        )
        with self.assertRaisesRegex(BoundaryError,"transport_failure"):
            rpc.call("eth_chainId",[],scope="candidate")
        self.assertFalse(rpc.telemetry()["automatic_failover"])

    def test_discovery_prefers_dedicated_endpoint_at_five_rps(self):
        env={
            PRIMARY_ENV:"https://primary.invalid/v2/key",
            DISCOVERY_ENV:"https://discovery.validationcloud.io/key",
        }
        rpc=configured_discovery_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        self.assertEqual(rpc.verify_chain(),4663)
        t=rpc.telemetry()
        self.assertEqual(t["role"],"pons_discovery_observation")
        self.assertEqual(t["provider_kind"],"validation_cloud")
        self.assertEqual(t["pacing"]["requests_per_second"],5.0)
        self.assertFalse(rpc.primary_fallback)

    def test_discovery_uses_official_public_rpc_when_only_alchemy_bulk_is_configured(self):
        env={
            PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/key",
            DLMM_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/other",
        }
        rpc=configured_discovery_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        self.assertEqual(rpc.telemetry()["provider_kind"],"robinhood_public")
        self.assertFalse(rpc.primary_fallback)
        self.assertEqual(rpc.telemetry()["role"],"pons_discovery_public_observation")
        self.assertEqual(rpc.telemetry()["pacing"]["requests_per_second"],2.0)

    def test_discovery_defaults_public_and_gap_recovery_uses_primary(self):
        env={PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/key"}
        discovery=configured_discovery_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        recovery=configured_discovery_recovery_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        self.assertEqual(discovery.telemetry()["provider_kind"],"robinhood_public")
        self.assertFalse(discovery.primary_fallback)
        self.assertFalse(discovery.gap_recovery)
        self.assertEqual(recovery.telemetry()["provider_kind"],"alchemy")
        self.assertTrue(recovery.primary_fallback)
        self.assertTrue(recovery.gap_recovery)


    def test_public_discovery_uses_alchemy_only_after_recoverable_failure(self):
        env={PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/key"}
        calls=[]
        def transport(method,params):
            calls.append(method)
            if len(calls)==1:
                raise BoundaryError("provider_transport_failure")
            return "0x1237"
        rpc=configured_discovery_rpc(
            env[PRIMARY_ENV],environ=env,limit=10,per_scope=10,retries=0,
            transport=transport,
        )
        self.assertEqual(rpc.call("eth_chainId",[],scope="discovery"),"0x1237")
        t=rpc.telemetry()
        self.assertEqual(t["provider_kind"],"robinhood_public")
        self.assertEqual(t["alchemy_gap_recovery_requests"],1)
        self.assertEqual(t["alchemy_gap_recovery_failures"],0)
        self.assertEqual(t["alchemy_gap_recovery"]["provider_kind"],"alchemy")
        self.assertEqual(calls,["eth_chainId","eth_chainId"])

    def test_dlmm_uses_dedicated_five_rps_lane(self):
        env={
            PRIMARY_ENV:"https://primary.invalid/v2/key",
            DLMM_ENV:"https://robinhood.validationcloud.io/key",
        }
        rpc=configured_dlmm_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        self.assertEqual(rpc.verify_chain(),4663)
        t=rpc.telemetry()
        self.assertEqual(t["role"],"dlmm_reconstruction_primary")
        self.assertEqual(t["provider_kind"],"validation_cloud")
        self.assertEqual(t["pacing"]["requests_per_second"],5.0)
        self.assertFalse(rpc.primary_fallback)

    def test_dlmm_fallback_is_explicit_not_failover(self):
        env={PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/key"}
        rpc=configured_dlmm_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        self.assertTrue(rpc.primary_fallback)
        self.assertEqual(
            rpc.telemetry()["role"],"dlmm_reconstruction_primary_fallback"
        )
        self.assertEqual(rpc.telemetry()["pacing"]["requests_per_second"],2.0)
        self.assertFalse(rpc.telemetry()["automatic_failover"])

    def test_primary_evidence_gap_recovery_and_dlmm_fallback_share_directional_pacer(self):
        env={PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/key"}
        directional=configured_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        recovery=configured_discovery_recovery_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        discovery=configured_discovery_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        dlmm=configured_dlmm_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        self.assertIs(directional.pacer,recovery.pacer)
        self.assertIs(directional.pacer,dlmm.pacer)
        self.assertIsNot(directional.pacer,discovery.pacer)
        self.assertEqual(directional.pacer.requests_per_second,2.0)

    def test_shadow_is_diagnostic_only(self):
        env={
            PRIMARY_ENV:"https://primary.invalid/v2/key",
            SHADOW_ENV:"https://shadow.quiknode.pro/key",
        }
        rpc=configured_shadow_rpc(environ=env)
        self.assertIsNotNone(rpc)
        t=rpc.telemetry()
        self.assertEqual(t["role"],"shadow_diagnostic_only")
        self.assertEqual(t["provider_kind"],"quicknode")
        self.assertFalse(t["automatic_failover"])

    def test_non_alchemy_provider_rejects_alchemy_specific_method(self):
        rpc=PacedRpc(
            "https://rpc.validationcloud.io/key",
            role="shadow_diagnostic_only",
            requests_per_second=5.0,
            transport=lambda *_:[],
        )
        with self.assertRaisesRegex(BoundaryError,"wrong_provider"):
            rpc.call("alchemy_getAssetTransfers",[{}],scope="history")

    def test_pacer_enforces_physical_rate(self):
        clock=_Clock()
        pacer=ProviderPacer(2.0,clock=clock.time,sleeper=clock.sleep)
        self.assertEqual(pacer.pace(),0.0)
        self.assertAlmostEqual(pacer.pace(),0.5)
        self.assertEqual(clock.sleeps,[0.5])
        self.assertEqual(pacer.telemetry()["paced_requests"],2)

    def test_pacer_backpressure_only_slows_and_is_shared(self):
        clock=_Clock()
        pacer=ProviderPacer(5.0,clock=clock.time,sleeper=clock.sleep)
        self.assertTrue(pacer.slow_to(2.0))
        self.assertFalse(pacer.slow_to(5.0))
        self.assertEqual(pacer.requests_per_second,2.0)
        self.assertEqual(pacer.minimum_interval_seconds,0.5)
        self.assertEqual(pacer.telemetry()["backpressure_events"],1)
        self.assertEqual(pacer.pace(),0.5)

    def test_topology_metadata_never_exposes_endpoint(self):
        env={
            PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/secret",
            DLMM_ENV:"https://rpc.validationcloud.io/secret",
            SHADOW_ENV:"https://shadow.quiknode.pro/secret",
        }
        meta=topology_metadata(environ=env)
        body=str(meta)
        self.assertEqual(meta["directional"]["evidence_provider_kind"],"alchemy")
        self.assertEqual(meta["directional"]["discovery_provider_kind"],"robinhood_public")
        self.assertEqual(meta["directional"]["gap_recovery_provider_kind"],"alchemy")
        self.assertIsNone(meta["directional"]["discovery_credential"])
        self.assertEqual(meta["dlmm"]["provider_kind"],"validation_cloud")
        self.assertNotIn("/secret",body)
        self.assertNotIn("https://",body)


if __name__=="__main__":
    unittest.main()