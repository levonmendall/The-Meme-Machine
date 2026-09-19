"""Regression coverage for public-primary / Alchemy-rescue Solana routing."""
import urllib.error
import unittest
from types import SimpleNamespace

from meme_machine.provider import Unavailable
from meme_machine import solana_read_rpc as topology
from tests import dlmm_alchemy_provider as provider


ALCHEMY = "https://solana-mainnet.g.alchemy.com/v2/example-key"


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

    def test_existing_alchemy_secret_is_secondary_rescue(self):
        env = {provider.ENV_NAME: ALCHEMY}
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
        meta = provider.metadata({provider.ENV_NAME: ALCHEMY})
        self.assertEqual(meta["primary_provider"], topology.PRIMARY_PROVIDER)
        self.assertEqual(meta["dlmm_primary_requests_per_second"], 5)
        self.assertAlmostEqual(meta["dlmm_minimum_request_interval_seconds"], 0.2)

        clock = _Clock()
        rpc_a = SimpleNamespace(clock=clock.time, sleep=clock.sleep, last_request=None)
        rpc_b = SimpleNamespace(clock=clock.time, sleep=clock.sleep, last_request=None)
        self.assertEqual(pacer.pace(rpc_a, 0.0), 0.0)
        self.assertAlmostEqual(pacer.pace(rpc_b, 0.0), 0.2)
        self.assertEqual(len(clock.sleeps), 1)
        self.assertAlmostEqual(clock.sleeps[0], 0.2)

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
            environ={provider.ENV_NAME: ALCHEMY},
        )
        calls = []

        def request(url, request):
            calls.append(url)
            return {"jsonrpc": "2.0", "id": request["id"], "result": "mainnet"}

        rpc._request_url = request
        self.assertEqual(rpc.call("getGenesisHash", priority=True), "mainnet")
        self.assertEqual(calls, [topology.PRIMARY_RPC_URL])
        self.assertEqual(rpc.calls, 1)
        self.assertEqual(rpc.http_requests, 1)
        self.assertEqual(rpc.failover_count, 0)

    def test_primary_http_failure_rescues_to_alchemy_without_extra_logical_call(self):
        rpc = provider.new_rpc(
            limit=40,
            environ={provider.ENV_NAME: ALCHEMY},
        )
        calls = []

        def request(url, request):
            calls.append(url)
            if url == topology.PRIMARY_RPC_URL:
                raise urllib.error.HTTPError(
                    url, 429, "rate limited", {}, None
                )
            return {"jsonrpc": "2.0", "id": request["id"], "result": "mainnet"}

        rpc._request_url = request
        self.assertEqual(rpc.call("getGenesisHash", priority=True), "mainnet")
        self.assertEqual(calls, [topology.PRIMARY_RPC_URL, ALCHEMY])
        self.assertEqual(rpc.calls, 1)
        self.assertEqual(rpc.http_requests, 2)
        telemetry = rpc.provider_telemetry()
        self.assertEqual(telemetry["failover_count"], 1)
        self.assertEqual(
            telemetry["provider_http_requests"][topology.PRIMARY_PROVIDER], 1
        )
        self.assertEqual(
            telemetry["provider_http_requests"][topology.SECONDARY_PROVIDER], 1
        )

    def test_null_get_transaction_rescues_to_alchemy(self):
        rpc = provider.new_rpc(
            limit=40,
            environ={provider.ENV_NAME: ALCHEMY},
        )
        calls = []
        expected = {"slot": 123, "meta": {"err": None}}

        def request(url, request):
            calls.append(url)
            result = None if url == topology.PRIMARY_RPC_URL else expected
            return {"jsonrpc": "2.0", "id": request["id"], "result": result}

        rpc._request_url = request
        value = rpc.call(
            "getTransaction",
            ["signature", {"commitment": "finalized"}],
            priority=True,
            fresh=True,
        )
        self.assertEqual(value, expected)
        self.assertEqual(calls, [topology.PRIMARY_RPC_URL, ALCHEMY])
        self.assertEqual(rpc.calls, 1)
        self.assertEqual(rpc.http_requests, 2)
        self.assertEqual(rpc.failover_count, 1)

    def test_batch_rejection_retries_public_items_before_alchemy(self):
        rpc = provider.new_rpc(
            limit=40,
            environ={provider.ENV_NAME: ALCHEMY},
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
        self.assertTrue(all(url == topology.PRIMARY_RPC_URL for url, _ in calls))
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