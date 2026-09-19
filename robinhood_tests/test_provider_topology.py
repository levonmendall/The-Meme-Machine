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
        self.assertEqual(t["role"],"pons_discovery_primary")
        self.assertEqual(t["provider_kind"],"validation_cloud")
        self.assertEqual(t["pacing"]["requests_per_second"],5.0)
        self.assertFalse(rpc.primary_fallback)

    def test_discovery_can_share_dlmm_endpoint(self):
        env={
            PRIMARY_ENV:"https://primary.invalid/v2/key",
            DLMM_ENV:"https://rpc.validationcloud.io/key",
        }
        rpc=configured_discovery_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        self.assertEqual(rpc.telemetry()["provider_kind"],"validation_cloud")
        self.assertFalse(rpc.primary_fallback)

    def test_discovery_explicitly_falls_back_to_primary_until_configured(self):
        env={PRIMARY_ENV:"https://primary.invalid/v2/key"}
        rpc=configured_discovery_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        self.assertTrue(rpc.primary_fallback)
        self.assertEqual(rpc.telemetry()["role"],"pons_discovery_primary_fallback")
        self.assertEqual(rpc.telemetry()["pacing"]["requests_per_second"],2.0)

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

    def test_primary_fallback_lanes_share_directional_pacer(self):
        env={PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/key"}
        directional=configured_rpc(
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
        self.assertIs(directional.pacer,discovery.pacer)
        self.assertIs(directional.pacer,dlmm.pacer)
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

    def test_topology_metadata_never_exposes_endpoint(self):
        env={
            PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/secret",
            DLMM_ENV:"https://rpc.validationcloud.io/secret",
            SHADOW_ENV:"https://shadow.quiknode.pro/secret",
        }
        meta=topology_metadata(environ=env)
        body=str(meta)
        self.assertEqual(meta["directional"]["evidence_provider_kind"],"alchemy")
        self.assertEqual(meta["dlmm"]["provider_kind"],"validation_cloud")
        self.assertNotIn("/secret",body)
        self.assertNotIn("https://",body)


if __name__=="__main__":
    unittest.main()