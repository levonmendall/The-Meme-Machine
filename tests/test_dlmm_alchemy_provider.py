"""Regression coverage for DLMM Alchemy-only RPC routing."""
import unittest

from meme_machine.provider import Unavailable
from tests import dlmm_alchemy_provider as provider


class DlmmAlchemyProvider(unittest.TestCase):
    def test_accepts_only_alchemy_solana_mainnet_full_endpoint(self):
        env = {
            provider.ENV_NAME:
                "https://solana-mainnet.g.alchemy.com/v2/example-key"
        }
        self.assertEqual(provider.rpc_url(env), env[provider.ENV_NAME])
        meta = provider.metadata()
        self.assertEqual(meta["provider"], "alchemy_solana_mainnet")
        self.assertFalse(meta["fallback_allowed"])
        self.assertFalse(meta["signing"])
        self.assertFalse(meta["submission"])

    def test_missing_route_fails_closed(self):
        with self.assertRaisesRegex(Unavailable, "alchemy_rpc_missing"):
            provider.rpc_url({})

    def test_public_and_non_alchemy_routes_are_rejected(self):
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


if __name__ == "__main__":
    unittest.main()
