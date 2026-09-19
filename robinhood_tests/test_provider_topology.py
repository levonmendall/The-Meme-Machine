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
        self.assertEqual(len(t["endpoint_fingerprint"]),16)
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
        telemetry=rpc.telemetry()
        self.assertFalse(telemetry["automatic_failover"])
        self.assertEqual(telemetry["credential_role"],PRIMARY_ENV)

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

    def test_discovery_fails_closed_instead_of_using_primary(self):
        env={PRIMARY_ENV:"https://primary.invalid/v2/key"}
        with self.assertRaisesRegex(
            BoundaryError,"robinhood_discovery_provider_required"
        ):
            configured_discovery_rpc(
                environ=env,limit=10,per_scope=10,retries=0,
                transport=lambda *_:"0x1237",
            )

    def test_discovery_accepts_distinct_alchemy_endpoint(self):
        env={
            PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/primary",
            DISCOVERY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/discovery",
        }
        rpc=configured_discovery_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        t=rpc.telemetry()
        self.assertEqual(t["provider_kind"],"alchemy")
        self.assertEqual(t["credential_role"],DISCOVERY_ENV)
        self.assertFalse(rpc.primary_fallback)
        self.assertNotEqual(
            t["endpoint_fingerprint"],
            configured_rpc(
                environ=env,limit=10,per_scope=10,retries=0,
                transport=lambda *_:"0x1237",
            ).telemetry()["endpoint_fingerprint"],
        )

    def test_discovery_bypasses_exact_primary_to_isolated_dlmm_provider(self):
        primary="https://robinhood-mainnet.g.alchemy.com/v2/primary"
        env={
            PRIMARY_ENV:primary,
            DISCOVERY_ENV:primary,
            DLMM_ENV:"https://rpc.validationcloud.io/dlmm",
        }
        rpc=configured_discovery_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        t=rpc.telemetry()
        self.assertEqual(t["provider_kind"],"validation_cloud")
        self.assertEqual(t["credential_role"],DLMM_ENV)
        self.assertFalse(rpc.primary_fallback)

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
        self.assertEqual(t["credential_role"],DLMM_ENV)
        self.assertEqual(t["pacing"]["requests_per_second"],5.0)
        self.assertFalse(rpc.primary_fallback)

    def test_dlmm_fails_closed_instead_of_using_primary(self):
        env={PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/key"}
        with self.assertRaisesRegex(
            BoundaryError,"robinhood_dlmm_provider_required"
        ):
            configured_dlmm_rpc(
                environ=env,limit=10,per_scope=10,retries=0,
                transport=lambda *_:"0x1237",
            )

    def test_explicit_primary_alias_uses_bounded_shared_dlmm_mode(self):
        endpoint="https://robinhood-mainnet.g.alchemy.com/v2/key"
        env={PRIMARY_ENV:endpoint,DLMM_ENV:endpoint}
        rpc=configured_dlmm_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        t=rpc.telemetry()
        self.assertTrue(rpc.primary_shared)
        self.assertTrue(t["primary_shared"])
        self.assertEqual(
            t["role"],"dlmm_reconstruction_primary_shared_observation"
        )
        self.assertEqual(t["pacing"]["requests_per_second"],1.0)
        self.assertFalse(rpc.primary_fallback)

    def test_explicit_primary_alias_preserves_discovery_at_bounded_rate(self):
        endpoint="https://robinhood-mainnet.g.alchemy.com/v2/key"
        env={
            PRIMARY_ENV:endpoint,
            DISCOVERY_ENV:endpoint,
            DLMM_ENV:endpoint,
        }
        rpc=configured_discovery_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        t=rpc.telemetry()
        self.assertTrue(rpc.primary_shared)
        self.assertTrue(t["primary_shared"])
        self.assertEqual(
            t["role"],"pons_discovery_primary_shared_observation"
        )
        self.assertEqual(t["pacing"]["requests_per_second"],2.0)
        self.assertEqual(t["credential_role"],DISCOVERY_ENV)
        self.assertFalse(rpc.primary_fallback)

    def test_bulk_lanes_have_independent_pacers_from_directional_primary(self):
        env={
            PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/key",
            DISCOVERY_ENV:"https://discovery.validationcloud.io/key",
            DLMM_ENV:"https://dlmm.validationcloud.io/key",
        }
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
        self.assertIsNot(directional.pacer,discovery.pacer)
        self.assertIsNot(directional.pacer,dlmm.pacer)
        self.assertFalse(discovery.primary_fallback)
        self.assertFalse(dlmm.primary_fallback)
        self.assertFalse(discovery.primary_shared)
        self.assertFalse(dlmm.primary_shared)
        self.assertEqual(discovery.pacer.requests_per_second,5.0)
        self.assertEqual(dlmm.pacer.requests_per_second,5.0)

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
        self.assertEqual(meta["dlmm"]["provider_kind"],"validation_cloud")
        self.assertEqual(meta["directional"]["discovery_credential"],DLMM_ENV)
        self.assertFalse(
            meta["directional"]["discovery_primary_candidate_bypassed"]
        )
        self.assertTrue(meta["provider_role_isolation"])
        self.assertTrue(meta["endpoint_isolation_complete"])
        self.assertFalse(meta["bulk_primary_shared"])
        self.assertFalse(meta["bulk_primary_fallback"])
        self.assertFalse(meta["directional"]["discovery_primary_fallback"])
        self.assertFalse(meta["dlmm"]["primary_fallback"])
        self.assertEqual(
            len(meta["directional"]["evidence_endpoint_fingerprint"]),16
        )
        self.assertEqual(len(meta["dlmm"]["endpoint_fingerprint"]),16)
        self.assertNotIn("/secret",body)
        self.assertNotIn("https://",body)

    def test_topology_metadata_marks_exact_primary_discovery_bypass(self):
        primary="https://robinhood-mainnet.g.alchemy.com/v2/primary"
        env={
            PRIMARY_ENV:primary,
            DISCOVERY_ENV:primary,
            DLMM_ENV:"https://rpc.validationcloud.io/dlmm",
        }
        meta=topology_metadata(environ=env)
        self.assertTrue(meta["directional"]["discovery_configured"])
        self.assertEqual(
            meta["directional"]["discovery_provider_kind"],
            "validation_cloud",
        )
        self.assertEqual(meta["directional"]["discovery_credential"],DLMM_ENV)
        self.assertTrue(
            meta["directional"]["discovery_primary_candidate_bypassed"]
        )
        self.assertFalse(meta["bulk_primary_fallback"])

    def test_dlmm_accepts_distinct_alchemy_endpoint_but_not_primary_reuse(self):
        env={
            PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/primary",
            DLMM_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/dlmm",
        }
        rpc=configured_dlmm_rpc(
            environ=env,limit=10,per_scope=10,retries=0,
            transport=lambda *_:"0x1237",
        )
        t=rpc.telemetry()
        self.assertEqual(t["provider_kind"],"alchemy")
        self.assertEqual(t["credential_role"],DLMM_ENV)
        self.assertFalse(rpc.primary_fallback)

    def test_topology_metadata_exposes_explicit_shared_primary_mode(self):
        endpoint="https://robinhood-mainnet.g.alchemy.com/v2/shared"
        env={
            PRIMARY_ENV:endpoint,
            DISCOVERY_ENV:endpoint,
            DLMM_ENV:endpoint,
        }
        meta=topology_metadata(environ=env)
        self.assertTrue(meta["bulk_primary_shared"])
        self.assertFalse(meta["endpoint_isolation_complete"])
        self.assertTrue(meta["directional"]["discovery_primary_shared"])
        self.assertTrue(meta["dlmm"]["primary_shared"])
        self.assertEqual(
            meta["directional"]["discovery_requests_per_second"],2.0
        )
        self.assertEqual(meta["dlmm"]["requests_per_second"],1.0)
        self.assertFalse(meta["bulk_primary_fallback"])

    def test_topology_metadata_reports_missing_bulk_lanes_without_primary_fallback(self):
        env={PRIMARY_ENV:"https://robinhood-mainnet.g.alchemy.com/v2/secret"}
        meta=topology_metadata(environ=env)
        self.assertFalse(meta["directional"]["discovery_configured"])
        self.assertEqual(
            meta["directional"]["discovery_error"],
            "robinhood_discovery_provider_required",
        )
        self.assertFalse(meta["dlmm"]["configured"])
        self.assertEqual(meta["dlmm"]["error"],"robinhood_dlmm_provider_required")
        self.assertFalse(meta["bulk_primary_fallback"])


if __name__=="__main__":
    unittest.main()