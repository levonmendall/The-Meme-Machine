"""Regression coverage for authenticated-OnFinality / Alchemy-rescue Solana routing."""
import urllib.error
import unittest
from types import SimpleNamespace

from meme_machine.provider import Unavailable
from meme_machine import solana_read_rpc as topology
from tests import dlmm_alchemy_provider as provider


ALCHEMY = "https://solana-mainnet.g.alchemy.com/v2/example-key"
ONFINALITY = "https://solana.api.onfinality.io/rpc?apikey=example-key"
ONFINALITY_WS = "wss://solana.api.onfinality.io/ws?apikey=example-key"
AUTH_ENV = {
    topology.ONFINALITY_RPC_ENV_NAME: ONFINALITY,
    topology.ONFINALITY_WS_ENV_NAME: ONFINALITY_WS,
    provider.ENV_NAME: ALCHEMY,
}


class _Clock:
    def __init__(self, now=100.0):
        self.now = float(now)
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(float(seconds))
        self.now += float(seconds)


class SolanaReadProviderTopology(unittest.TestCase):
    def test_onfinality_public_is_primary_without_secret(self):
        self.assertEqual(provider.rpc_url({}), topology.PRIMARY_RPC_URL)
        meta = provider.metadata({})
        self.assertEqual(meta["primary_provider"], topology.PRIMARY_PROVIDER)
        self.assertTrue(meta["primary_public"])
        self.assertFalse(meta["secondary_configured"])
        self.assertTrue(meta["fallback_allowed"])
        self.assertFalse(meta["load_balancing"])

    def test_authenticated_onfinality_secret_overrides_public_primary(self):
        self.assertEqual(topology.primary_rpc_url(AUTH_ENV), ONFINALITY)
        self.assertEqual(topology.primary_ws_url(AUTH_ENV), ONFINALITY_WS)
        meta = provider.metadata(AUTH_ENV)
        self.assertEqual(
            meta["primary_provider"], topology.AUTHENTICATED_PRIMARY_PROVIDER
        )
        self.assertFalse(meta["primary_public"])
        self.assertEqual(
            meta["primary_credential"], topology.ONFINALITY_RPC_ENV_NAME
        )
        self.assertEqual(
            meta["primary_ws_credential"], topology.ONFINALITY_WS_ENV_NAME
        )

    def test_existing_alchemy_secret_is_secondary_rescue(self):
        env = AUTH_ENV
        self.assertEqual(
            provider.alchemy_rpc_url(env, required=True),
            ALCHEMY,
        )
        meta = provider.metadata(env)
        self.assertEqual(meta["secondary_provider"], topology.SECONDARY_PROVIDER)
        self.assertEqual(meta["secondary_credential"], "MM_SOLANA_READ_RPC_URL")
        self.assertTrue(meta["secondary_configured"])

    def test_required_secondary_fails_closed_when_missing(self):
        with self.assertRaisesRegex(Unavailable, "alchemy_rpc_missing"):
            provider.alchemy_rpc_url({}, required=True)

    def test_non_alchemy_secondary_routes_are_rejected(self):
        for value in (
            "https://api.mainnet-beta.solana.com",
            "https://api.mainnet.solana.com",
            "https://solana-rpc.publicnode.com",
            "https://example.com/v2/key",
            "http://solana-mainnet.g.alchemy.com/v2/key",
            "https://solana-devnet.g.alchemy.com/v2/key",
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                Unavailable, "alchemy_rpc_endpoint_required"
            ):
                provider.alchemy_rpc_url(
                    {provider.ENV_NAME: value},
                    required=True,
                )

    def test_key_only_placeholder_and_url_extras_are_rejected(self):
        for value in (
            "alchemy-key-only",
            "https://solana-mainnet.g.alchemy.com/v2/",
            "https://solana-mainnet.g.alchemy.com/v2/<api-key>",
            "https://solana-mainnet.g.alchemy.com/v2/key?x=1",
            "https://solana-mainnet.g.alchemy.com/v2/key#fragment",
            "https://user:pass@solana-mainnet.g.alchemy.com/v2/key",
        ):
            with self.subTest(value=value), self.assertRaises(Unavailable):
                provider.alchemy_rpc_url(
                    {provider.ENV_NAME: value},
                    required=True,
                )

    def test_authenticated_primary_rejects_public_or_wrong_host(self):
        for value in (
            topology.PRIMARY_RPC_URL,
            "https://example.com/rpc?apikey=key",
            "http://solana.api.onfinality.io/rpc?apikey=key",
        ):
            with self.subTest(value=value), self.assertRaises(Unavailable):
                topology.primary_rpc_url({
                    topology.ONFINALITY_RPC_ENV_NAME: value
                }, require_authenticated=True)

    def test_authenticated_primary_is_required_by_live_validation(self):
        with self.assertRaisesRegex(
            Unavailable, "onfinality_authenticated_rpc_missing"
        ):
            topology.validate_topology(
                {provider.ENV_NAME: ALCHEMY},
                require_secondary=True,
                require_authenticated_primary=True,
            )

    def test_primary_override_cannot_redirect_to_arbitrary_provider(self):
        with self.assertRaisesRegex(
            Unavailable, "onfinality_public_rpc_endpoint_required"
        ):
            topology.primary_rpc_url(
                {topology.PUBLIC_OVERRIDE_ENV_NAME: "https://example.com"}
            )

    def test_dlmm_defaults_to_onfinality_primary_at_five_rps(self):
        pacer = provider.AlchemyPacer()
        self.assertAlmostEqual(pacer.minimum_interval, 0.2)
        meta = provider.metadata(AUTH_ENV)
        self.assertEqual(
            meta["primary_provider"], topology.AUTHENTICATED_PRIMARY_PROVIDER
        )
        self.assertEqual(meta["dlmm_primary_requests_per_second"], 5)
        self.assertAlmostEqual(meta["dlmm_minimum_request_interval_seconds"], 0.2)

        clock = _Clock()
        rpc_a = SimpleNamespace(clock=clock.time, sleep=clock.sleep, last_request=None)
        rpc_b = SimpleNamespace(clock=clock.time, sleep=clock.sleep, last_request=None)
        self.assertEqual(pacer.pace(rpc_a, 0.0), 0.0)
        self.assertAlmostEqual(pacer.pace(rpc_b, 0.0), 0.2)
        self.assertEqual(len(clock.sleeps), 1)
        self.assertAlmostEqual(clock.sleeps[0], 0.2)

    def test_dlmm_rpc_call_uses_point_two_second_spacing_not_legacy_half_second(self):
        clock = _Clock()
        rpc = provider.new_rpc(
            limit=40,
            environ=AUTH_ENV,
            clock=clock.time,
            sleeper=clock.sleep,
        )
        rpc._request_url = lambda _url, request: {
            "jsonrpc":"2.0","id":request["id"],"result":"mainnet"
        }
        self.assertEqual(
            rpc.call("getGenesisHash", priority=True, fresh=True), "mainnet"
        )
        self.assertEqual(
            rpc.call("getGenesisHash", priority=True, fresh=True), "mainnet"
        )
        self.assertEqual(len(clock.sleeps), 1)
        self.assertAlmostEqual(clock.sleeps[0], 0.2)
        self.assertLess(clock.sleeps[0], 0.5)

    def test_dlmm_batch_transport_uses_same_point_two_second_physical_cap(self):
        clock = _Clock()
        rpc = provider.new_rpc(
            limit=40,
            environ=AUTH_ENV,
            clock=clock.time,
            sleeper=clock.sleep,
        )
        def request(_url, body):
            if isinstance(body,list):
                return [
                    {"jsonrpc":"2.0","id":item["id"],"result":{"slot":i}}
                    for i,item in enumerate(body)
                ]
            return {"jsonrpc":"2.0","id":body["id"],"result":"mainnet"}
        rpc._request_url = request
        params=[[f"sig-{i}",{"encoding":"json","commitment":"finalized"}]
                for i in range(8)]
        out=rpc.call_many("getTransaction",params,True,batch_size=4)
        self.assertEqual(len(out),8)
        # Two physical batch transports: only one inter-request sleep, at 0.2s.
        self.assertEqual(len(clock.sleeps),1)
        self.assertAlmostEqual(clock.sleeps[0],0.2)
        self.assertLess(clock.sleeps[0],0.5)

    def test_shared_pacer_serializes_independent_rpc_objects(self):
        clock = _Clock()
        pacer = provider.AlchemyPacer(minimum_interval=1.0)
        rpc_a = SimpleNamespace(
            clock=clock.time, sleep=clock.sleep, last_request=None
        )
        rpc_b = SimpleNamespace(
            clock=clock.time, sleep=clock.sleep, last_request=None
        )
        self.assertEqual(pacer.pace(rpc_a, 0.5), 0.0)
        self.assertAlmostEqual(pacer.pace(rpc_b, 0.5), 1.0)
        self.assertEqual(clock.sleeps, [1.0])
        telemetry = pacer.telemetry()
        self.assertEqual(telemetry["paced_requests"], 2)
        self.assertAlmostEqual(telemetry["throttle_sleep_seconds"], 1.0)

    def test_429_retry_wait_keeps_two_second_floor(self):
        error = urllib.error.HTTPError(
            "https://example.invalid",
            429,
            "rate limited",
            {},
            None,
        )
        self.assertGreaterEqual(
            provider.AlchemyPoolScanRPC._retry_delay(error),
            provider.ALCHEMY_429_MIN_BACKOFF_SECONDS,
        )

    def test_healthy_primary_never_touches_alchemy(self):
        rpc = provider.new_rpc(
            limit=40,
            environ=AUTH_ENV,
        )
        calls = []

        def request(url, request):
            calls.append(url)
            return {"jsonrpc": "2.0", "id": request["id"], "result": "mainnet"}

        rpc._request_url = request
        self.assertEqual(rpc.call("getGenesisHash", priority=True), "mainnet")
        self.assertEqual(calls, [ONFINALITY])
        self.assertEqual(rpc.calls, 1)
        self.assertEqual(rpc.http_requests, 1)
        self.assertEqual(rpc.failover_count, 0)

    def test_primary_http_failure_rescues_to_alchemy_without_extra_logical_call(self):
        rpc = provider.new_rpc(
            limit=40,
            environ=AUTH_ENV,
        )
        calls = []

        def request(url, request):
            calls.append(url)
            if url == ONFINALITY:
                raise urllib.error.HTTPError(
                    url, 429, "rate limited", {}, None
                )
            return {"jsonrpc": "2.0", "id": request["id"], "result": "mainnet"}

        rpc._request_url = request
        self.assertEqual(rpc.call("getGenesisHash", priority=True), "mainnet")
        self.assertEqual(calls, [ONFINALITY, ALCHEMY])
        self.assertEqual(rpc.calls, 1)
        self.assertEqual(rpc.http_requests, 2)
        telemetry = rpc.provider_telemetry()
        self.assertEqual(telemetry["failover_count"], 1)
        self.assertEqual(
            telemetry["provider_http_requests"][
                topology.AUTHENTICATED_PRIMARY_PROVIDER
            ], 1
        )
        self.assertEqual(
            telemetry["provider_http_requests"][topology.SECONDARY_PROVIDER], 1
        )

    def test_null_get_transaction_rescues_to_alchemy(self):
        rpc = provider.new_rpc(
            limit=40,
            environ=AUTH_ENV,
        )
        calls = []
        expected = {"slot": 123, "meta": {"err": None}}

        def request(url, request):
            calls.append(url)
            result = None if url == ONFINALITY else expected
            return {"jsonrpc": "2.0", "id": request["id"], "result": result}

        rpc._request_url = request
        value = rpc.call(
            "getTransaction",
            ["signature", {"commitment": "finalized"}],
            priority=True,
            fresh=True,
        )
        self.assertEqual(value, expected)
        self.assertEqual(calls, [ONFINALITY, ALCHEMY])
        self.assertEqual(rpc.calls, 1)
        self.assertEqual(rpc.http_requests, 2)
        self.assertEqual(rpc.failover_count, 1)

    def test_batch_rejection_retries_public_items_before_alchemy(self):
        rpc = provider.new_rpc(
            limit=40,
            environ=AUTH_ENV,
        )
        calls = []

        def request(url, request):
            calls.append((url, isinstance(request, list)))
            if isinstance(request, list):
                return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600}}
            return {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"slot": 1, "signature": request["params"][0]},
            }

        rpc._request_url = request
        params = [
            [f"sig-{i}", {"encoding": "json", "commitment": "finalized"}]
            for i in range(3)
        ]
        out = rpc.call_many("getTransaction", params, True, batch_size=3)
        self.assertEqual(len(out), 3)
        self.assertEqual(rpc.failover_count, 0)
        self.assertTrue(all(url == ONFINALITY for url, _ in calls))
        self.assertEqual(rpc.http_requests, 4)

    def test_new_rpc_objects_keep_independent_logical_budgets(self):
        pacer = provider.AlchemyPacer()
        env = {provider.ENV_NAME: ALCHEMY}
        first = provider.new_rpc(
            limit=240,
            pacer=pacer,
            environ=env,
            transport=lambda _request: {"result": "ok"},
        )
        second = provider.new_rpc(
            limit=240,
            pacer=pacer,
            environ=env,
            transport=lambda _request: {"result": "ok"},
        )
        self.assertIsNot(first, second)
        self.assertEqual(first.limit, 240)
        self.assertEqual(second.limit, 240)
        self.assertEqual(first.calls, 0)
        self.assertEqual(second.calls, 0)
        self.assertIs(first.alchemy_pacer, second.alchemy_pacer)
        self.assertIs(first.read_pacer, second.read_pacer)


if __name__ == "__main__":
    unittest.main()