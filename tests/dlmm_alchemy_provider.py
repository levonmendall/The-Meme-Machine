"""Canonical read-only RPC routing for DLMM research.

DLMM uses the existing Meme Machine GitHub secret MM_SOLANA_READ_RPC_URL.
The configured value must be the full Alchemy Solana Mainnet HTTPS endpoint.
There is no fallback to Solana Labs, PublicNode, another Alchemy app, or another
provider.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from meme_machine.provider import Unavailable

ENV_NAME = "MM_SOLANA_READ_RPC_URL"
ALCHEMY_SOLANA_MAINNET_HOST = "solana-mainnet.g.alchemy.com"
PROVIDER_LABEL = "alchemy_solana_mainnet_existing_secret"


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
    if (
        len(parts) != 2
        or parts[0] != "v2"
        or not parts[1]
        or "<" in parts[1]
        or ">" in parts[1]
    ):
        raise Unavailable("dlmm_alchemy_rpc_endpoint_required")
    return value


def metadata():
    return dict(
        provider=PROVIDER_LABEL,
        credential=ENV_NAME,
        network="solana-mainnet",
        host=ALCHEMY_SOLANA_MAINNET_HOST,
        fallback_allowed=False,
        signing=False,
        submission=False,
    )


def main():
    rpc_url()
    print(
        "DLMM existing MM_SOLANA_READ_RPC_URL is configured for "
        "Alchemy Solana Mainnet; provider fallback is disabled"
    )


if __name__ == "__main__":
    main()
