"""Compatibility shim for Meme Machine's canonical Solana read topology.

DLMM now uses the existing authenticated Alchemy endpoint directly for HTTP
reconstruction. Public Solana WebSocket remains the discovery surface. Existing
imports remain valid so ongoing research code does not need strategy-layer changes.
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
    primary_provider,
    primary_rpc_url,
    secondary_rpc_url,
    validate_topology,
)

ENV_NAME = ALCHEMY_ENV_NAME
PROVIDER_LABEL = TOPOLOGY_LABEL

# DLMM uses direct Alchemy HTTP reconstruction at a hard 5 requests/second ceiling.
DLMM_MIN_REQUEST_INTERVAL_SECONDS = 0.2
DLMM_PRIMARY_REQUESTS_PER_SECOND = 5

class AlchemyPacer(SolanaReadPacer):
    """Backward-compatible DLMM pacer name; paces direct Alchemy at 5 rps."""
    def __init__(self, minimum_interval=DLMM_MIN_REQUEST_INTERVAL_SECONDS):
        super().__init__(minimum_interval=minimum_interval)

class AlchemyPoolScanRPC(ReadOnlyFailoverPoolScanRPC):
    """DLMM read client with a hard 5-rps physical-request ceiling.

    Base RPC.call/call_many historically request >=0.5-second pacing. For DLMM
    acquisition, ignore that legacy requested interval and apply the shared
    0.2-second pacer directly. Logical budgets, retries, evidence bounds and all
    strategy thresholds remain unchanged.
    """
    def _pace(self, interval=0.5):
        if self.transport == self._http:
            self.read_pacer.pace(self, DLMM_MIN_REQUEST_INTERVAL_SECONDS)


ALCHEMY_MIN_REQUEST_INTERVAL_SECONDS = DLMM_MIN_REQUEST_INTERVAL_SECONDS
ALCHEMY_429_MIN_BACKOFF_SECONDS = PROVIDER_429_MIN_BACKOFF_SECONDS


def rpc_url(environ=None):
    """Return the authenticated Alchemy endpoint used directly by DLMM."""
    return secondary_rpc_url(environ, required=True)


def alchemy_rpc_url(environ=None, *, required=False):
    return secondary_rpc_url(environ, required=required)


def new_rpc(limit=240, pacer=None, environ=None, **kwargs):
    # DLMM no longer sends reconstruction traffic to OnFinality. Use the existing
    # authenticated Alchemy endpoint directly and preserve the same 0.2s ceiling.
    pacer = pacer or AlchemyPacer()
    return AlchemyPoolScanRPC(
        secondary_rpc_url(environ,required=True),
        secondary_url=None,
        primary_provider=SECONDARY_PROVIDER,
        limit=limit,
        pacer=pacer,
        **kwargs,
    )


def metadata(environ=None):
    return dict(
        topology="dlmm_public_ws_alchemy_http",
        primary_provider=SECONDARY_PROVIDER,
        primary_credential=ALCHEMY_ENV_NAME,
        secondary_provider=None,
        secondary_configured=False,
        fallback_allowed=False,
        network="solana-mainnet",
        signing=False,
        submission=False,
        dlmm_minimum_request_interval_seconds=DLMM_MIN_REQUEST_INTERVAL_SECONDS,
        dlmm_primary_requests_per_second=DLMM_PRIMARY_REQUESTS_PER_SECOND,
    )


def main():
    secondary_rpc_url(required=True)
    print(
        "DLMM Solana read topology validated: public WebSocket discovery; "
        "authenticated Alchemy HTTP reconstruction at 5 rps; OnFinality disabled"
    )


if __name__ == "__main__":
    main()