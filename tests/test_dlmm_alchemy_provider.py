"""Regression coverage for existing-secret Alchemy-only DLMM routing."""
import urllib.error
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine.provider import Unavailable
from tests import dlmm_alchemy_provider as provider


class _Clock:
    def __init__(self, now=100.0):
        self.now = float(now)
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(float(seconds))
        self.now += float(seconds)


class DlmmAlchemyProvider(unittest.TestCase):
    def test_accepts_existing_full_alchemy_mainnet_url(self):
        env = {
            provider.ENV_NAME:
                "https://solana-mainnet.g.alchemy.com/v2/example-key"
        }
        self.assertEqual(provider.rpc_url(env), env[provider.ENV_NAME])
        meta = provider.metadata()
        self.assertEqual(
            meta["provider"], "alchemy_solana_mainnet_existing_secret"
        )
        self.assertEqual(meta["credential"], "MM_SOLANA_READ_RPC_URL")
        self.assertFalse(meta["fallback_allowed"])

    def test_missing_route_fails_closed(self):
        with self.assertRaisesRegex(Unavailable, "alchemy_rpc_missing"):
            provider.rpc_url({})

    def test_non_alchemy_and_non_mainnet_routes_are_rejected(self):
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
                provider.rpc_url({provider.ENV_NAME: value})

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
                provider.rpc_url({provider.ENV_NAME: value})

    def test_shared_pacer_serializes_independent_pool_rpc_objects(self):
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

    def test_429_retry_wait_has_two_second_floor(self):
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

    def test_new_rpc_objects_have_independent_240_call_budgets(self):
        pacer = provider.AlchemyPacer()
        with patch.object(
            provider,
            "rpc_url",
            return_value="https://solana-mainnet.g.alchemy.com/v2/example-key",
        ):
            first = provider.new_rpc(
                limit=240,
                pacer=pacer,
                transport=lambda _request: {"result": "ok"},
            )
            second = provider.new_rpc(
                limit=240,
                pacer=pacer,
                transport=lambda _request: {"result": "ok"},
            )
        self.assertIsNot(first, second)
        self.assertEqual(first.limit, 240)
        self.assertEqual(second.limit, 240)
        self.assertEqual(first.calls, 0)
        self.assertEqual(second.calls, 0)
        self.assertIs(first.alchemy_pacer, second.alchemy_pacer)


if __name__ == "__main__":
    unittest.main()
