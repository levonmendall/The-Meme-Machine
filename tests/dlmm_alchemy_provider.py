"""Compatibility shim for Meme Machine's canonical Solana read topology.

Historically DLMM used an Alchemy-only helper in this module. The public OnFinality
endpoint is now primary and the existing MM_SOLANA_READ_RPC_URL Alchemy secret is a
bounded rescue path. Existing imports remain valid so ongoing frozen experiments do
not need strategy-layer changes.
"""
from meme_machine.provider import Unavailable
from meme_machine.solana_read_rpc import (
    ALCHEMY_ENV_NAME,
    ALCHEMY_SOLANA_MAINNET_HOST,
    PRIMARY_PROVIDER,
    PRIMARY_RPC_URL,
    PROVIDER_429_MIN_BACKOFF_SECONDS,
    ReadOnlyFailoverPoolScanRPC,
    SOLANA_MIN_REQUEST_INTERVAL_SECONDS,
    SECONDARY_PROVIDER,
    SolanaReadPacer,
    TOPOLOGY_LABEL,
    metadata as _metadata,
    new_pool_scan_rpc,
    primary_rpc_url,
    secondary_rpc_url,
    validate_topology,
)

ENV_NAME = ALCHEMY_ENV_NAME
PROVIDER_LABEL = TOPOLOGY_LABEL

# Backward-compatible names retained for existing DLMM research modules/tests.
AlchemyPacer = SolanaReadPacer
AlchemyPoolScanRPC = ReadOnlyFailoverPoolScanRPC
ALCHEMY_MIN_REQUEST_INTERVAL_SECONDS = SOLANA_MIN_REQUEST_INTERVAL_SECONDS
ALCHEMY_429_MIN_BACKOFF_SECONDS = PROVIDER_429_MIN_BACKOFF_SECONDS


def rpc_url(environ=None):
    """Return the canonical PRIMARY read endpoint (OnFinality public)."""
    return primary_rpc_url(environ)


def alchemy_rpc_url(environ=None, *, required=False):
    return secondary_rpc_url(environ, required=required)


def new_rpc(limit=240, pacer=None, environ=None, **kwargs):
    return new_pool_scan_rpc(
        limit=limit,
        pacer=pacer,
        environ=environ,
        **kwargs,
    )


def metadata(environ=None):
    return _metadata(environ)


def main():
    validate_topology(require_secondary=True)
    print(
        "DLMM Solana read topology validated: OnFinality public primary; "
        "existing MM_SOLANA_READ_RPC_URL Alchemy endpoint is rescue-only"
    )


if __name__ == "__main__":
    main()