"""Canonical read-only RPC routing for DLMM research.

DLMM inherits the established Solana ROI Alchemy provider credential. The secret is
the API key only; this module constructs the Solana Mainnet endpoint internally so a
different Alchemy app/account or arbitrary RPC URL cannot be substituted silently.
"""
from __future__ import annotations

import os

from meme_machine.provider import Unavailable

ENV_NAME = "SOLANA_ROI_ALCHEMY_API_KEY"
ALCHEMY_SOLANA_MAINNET_HOST = "solana-mainnet.g.alchemy.com"
PROVIDER_LABEL = "solana_roi_alchemy_solana_mainnet"


def _valid_key(value):
    return (
        isinstance(value, str)
        and 8 <= len(value) <= 256
        and value.strip() == value
        and "://" not in value
        and "/" not in value
        and "?" not in value
        and "#" not in value
        and "<" not in value
        and ">" not in value
    )


def api_key(environ=None):
    source = os.environ if environ is None else environ
    value = str(source.get(ENV_NAME, "") or "").strip()
    if not value:
        raise Unavailable("dlmm_solana_roi_alchemy_key_missing")
    if not _valid_key(value):
        raise Unavailable("dlmm_solana_roi_alchemy_key_shape")
    return value


def rpc_url(environ=None):
    key = api_key(environ)
    return f"https://{ALCHEMY_SOLANA_MAINNET_HOST}/v2/{key}"


def metadata():
    return dict(
        provider=PROVIDER_LABEL,
        credential=ENV_NAME,
        network="solana-mainnet",
        host=ALCHEMY_SOLANA_MAINNET_HOST,
        inherited_from="solana-roi-convergence",
        fallback_allowed=False,
        signing=False,
        submission=False,
    )


def main():
    api_key()
    print(
        "DLMM Solana ROI Alchemy credential configured for Solana Mainnet; "
        "provider fallback is disabled"
    )


if __name__ == "__main__":
    main()
