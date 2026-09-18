"""Canonical read-only RPC routing for DLMM research.

All DLMM live/replay acquisition must use Alchemy Solana Mainnet. The endpoint is
provided only through environment configuration and is never logged. There is no
fallback to Solana Labs, PublicNode, or another provider.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from meme_machine.provider import Unavailable

ENV_NAME = "MM_ALCHEMY_SOLANA_RPC_URL"
ALCHEMY_SOLANA_MAINNET_HOST = "solana-mainnet.g.alchemy.com"
PROVIDER_LABEL = "alchemy_solana_mainnet"


def rpc_url(environ=None):
    source = os.environ if environ is None else environ
    value = str(source.get(ENV_NAME, "") or "").strip()
    if not value:
        raise Unavailable("dlmm_alchemy_rpc_missing")
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != ALCHEMY_SOLANA_MAINNET_HOST
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise Unavailable("dlmm_alchemy_rpc_endpoint_required")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0] != "v2" or not parts[1] or "<" in parts[1] or ">" in parts[1]:
        raise Unavailable("dlmm_alchemy_rpc_endpoint_required")
    return value


def metadata():
    return dict(
        provider=PROVIDER_LABEL,
        network="solana-mainnet",
        host=ALCHEMY_SOLANA_MAINNET_HOST,
        fallback_allowed=False,
        signing=False,
        submission=False,
    )


def main():
    rpc_url()
    print(
        "DLMM Alchemy Solana Mainnet RPC route configured; "
        "provider fallback is disabled"
    )


if __name__ == "__main__":
    main()
