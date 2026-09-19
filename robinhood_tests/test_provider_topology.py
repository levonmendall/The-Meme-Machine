import unittest

from robinhood_research import BoundaryError
from robinhood_research.provider_topology import MultiSourceRpc


class MultiSourceProviderTests(unittest.TestCase):
    def test_primary_success_never_touches_secondary(self):
        secondary_calls=[]
        rpc=MultiSourceRpc(
            "https://primary.invalid",
            secondary_endpoint="https://secondary.invalid",
            retries=0,
            primary_transport=lambda method,params: "0x1237",
            secondary_transport=lambda method,params: secondary_calls.append((method,params)) or "0x1237",
        )
        self.assertEqual(rpc.verify_chain(),4663)
        self.assertEqual(secondary_calls,[])
        t=rpc.telemetry()
        self.assertEqual(t["failover_successes"],0)
        self.assertTrue(t["secondary_configured"])

    def test_transport_failure_rescues_to_secondary(self):
        secondary_calls=[]
        def primary(*_):
            raise BoundaryError("provider_transport_failure")
        def secondary(method,params):
            secondary_calls.append((method,params))
            return "0x1237"
        rpc=MultiSourceRpc(
            "https://primary.invalid",
            secondary_endpoint="https://secondary.invalid",
            retries=0,
            primary_transport=primary,
            secondary_transport=secondary,
        )
        self.assertEqual(rpc.verify_chain(),4663)
        self.assertEqual([x[0] for x in secondary_calls],["eth_chainId"])
        t=rpc.telemetry()
        self.assertEqual(t["failover_successes"],1)
        self.assertEqual(t["failovers"],{"provider_transport_failure":1})

    def test_primary_budget_exhaustion_does_not_escape_to_secondary(self):
        secondary_calls=[]
        rpc=MultiSourceRpc(
            "https://primary.invalid",
            secondary_endpoint="https://secondary.invalid",
            limit=1,
            per_scope=1,
            retries=0,
            primary_transport=lambda *_:"0x1237",
            secondary_transport=lambda method,params: secondary_calls.append((method,params)) or "0x1237",
        )
        self.assertEqual(rpc.call("eth_chainId",[],scope="one"),"0x1237")
        with self.assertRaisesRegex(BoundaryError,"budget_exhausted"):
            rpc.call("eth_chainId",[],scope="one")
        self.assertEqual(secondary_calls,[])

    def test_alchemy_specific_method_remains_primary_only(self):
        secondary_calls=[]
        def primary(*_):
            raise BoundaryError("provider_transport_failure")
        rpc=MultiSourceRpc(
            "https://primary.invalid",
            secondary_endpoint="https://secondary.invalid",
            retries=0,
            primary_transport=primary,
            secondary_transport=lambda method,params: secondary_calls.append((method,params)) or [],
        )
        with self.assertRaisesRegex(BoundaryError,"transport_failure"):
            rpc.call("alchemy_getAssetTransfers",[{}],scope="history")
        self.assertEqual(secondary_calls,[])

    def test_batch_can_fail_over_without_widening_logical_scope(self):
        primary_calls=[];secondary_calls=[]
        def primary(method,params):
            primary_calls.append((method,params))
            raise BoundaryError("provider_http_503")
        def secondary(method,params):
            secondary_calls.append((method,params))
            return "0x1237" if method=="eth_chainId" else "0x1"
        rpc=MultiSourceRpc(
            "https://primary.invalid",
            secondary_endpoint="https://secondary.invalid",
            limit=10,per_scope=10,retries=0,
            primary_transport=primary,
            secondary_transport=secondary,
        )
        out=rpc.batch([
            ("eth_chainId",[]),
            ("eth_blockNumber",[]),
        ],scope="sample")
        self.assertEqual(out,["0x1237","0x1"])
        self.assertEqual(rpc.telemetry()["logical_requests"],2)
        self.assertEqual(rpc.telemetry()["failover_successes"],1)


if __name__=="__main__":
    unittest.main()
