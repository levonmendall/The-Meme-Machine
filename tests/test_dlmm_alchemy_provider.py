"""Regression coverage for Solana ROI Alchemy-only DLMM routing."""
import unittest

from meme_machine.provider import Unavailable
from tests import dlmm_alchemy_provider as provider


class DlmmAlchemyProvider(unittest.TestCase):
    def test_constructs_solana_mainnet_endpoint_from_sol_roi_key(self):
        env = {provider.ENV_NAME: "example-solana-roi-key"}
        self.assertEqual(
            provider.rpc_url(env),
            "https://solana-mainnet.g.alchemy.com/v2/example-solana-roi-key",
        )
        meta = provider.metadata()
        self.assertEqual(
            meta["provider"], "solana_roi_alchemy_solana_mainnet"
        )
        self.assertEqual(meta["credential"], "SOLANA_ROI_ALCHEMY_API_KEY")
        self.assertEqual(meta["inherited_from"], "solana-roi-convergence")
        self.assertFalse(meta["fallback_allowed"])
        self.assertFalse(meta["signing"])
        self.assertFalse(meta["submission"])

    def test_missing_key_fails_closed(self):
        with self.assertRaisesRegex(
            Unavailable, "solana_roi_alchemy_key_missing"
        ):
            provider.rpc_url({})

    def test_full_urls_and_other_provider_shapes_are_rejected(self):
        for value in (
            "https://solana-mainnet.g.alchemy.com/v2/example-key",
            "https://api.mainnet-beta.solana.com",
            "https://solana-rpc.publicnode.com",
            "key/with/slash",
            "key?query",
            "key#fragment",
            "<api-key>",
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                Unavailable, "solana_roi_alchemy_key_shape"
            ):
                provider.rpc_url({provider.ENV_NAME: value})

    def test_short_or_whitespace_key_is_rejected(self):
        for value in ("short", " leading-key", "trailing-key "):
            with self.subTest(value=value), self.assertRaises(Unavailable):
                provider.rpc_url({provider.ENV_NAME: value})


if __name__ == "__main__":
    unittest.main()
