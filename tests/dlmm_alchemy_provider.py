"""Compatibility shim for Meme Machine's canonical Solana read topology.

Historically DLMM used an Alchemy-only helper in this module. Authenticated OnFinality
is now primary and the existing MM_SOLANA_READ_RPC_URL Alchemy secret is a bounded
rescue path. Existing imports remain valid so ongoing frozen experiments do
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
    primary_provider,
    primary_rpc_url,
    secondary_rpc_url,
    validate_topology,
)

ENV_NAME = ALCHEMY_ENV_NAME
PROVIDER_LABEL = TOPOLOGY_LABEL

# DLMM uses authenticated OnFinality primary at 5 requests/second.
# Other Solana lanes retain the canonical topology's more conservative default.
DLMM_MIN_REQUEST_INTERVAL_SECONDS = 0.2
DLMM_PRIMARY_REQUESTS_PER_SECOND = 5

class AlchemyPacer(SolanaReadPacer):
    """Backward-compatible DLMM pacer name; now paces the primary at 5 rps."""
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
    """Return the canonical PRIMARY read endpoint (authenticated when configured)."""
    return primary_rpc_url(environ)


def alchemy_rpc_url(environ=None, *, required=False):
    return secondary_rpc_url(environ, required=required)


def new_rpc(limit=240, pacer=None, environ=None, **kwargs):
    # Authenticated OnFinality remains primary. DLMM physical transports are
    # paced at 0.2s (5 rps); Alchemy is contacted only through bounded rescue.
    pacer = pacer or AlchemyPacer()
    return AlchemyPoolScanRPC(
        primary_rpc_url(environ),
        secondary_url=secondary_rpc_url(environ,required=False),
        primary_provider=primary_provider(environ),
        limit=limit,
        pacer=pacer,
        **kwargs,
    )


def metadata(environ=None):
    data=_metadata(environ)
    data.update(
        dlmm_minimum_request_interval_seconds=DLMM_MIN_REQUEST_INTERVAL_SECONDS,
        dlmm_primary_requests_per_second=DLMM_PRIMARY_REQUESTS_PER_SECOND,
    )
    return data


def main():
    validate_topology(require_secondary=True,require_authenticated_primary=True)
    print(
        "DLMM Solana read topology validated: authenticated OnFinality primary at 5 rps; "
        "existing MM_SOLANA_READ_RPC_URL Alchemy endpoint is rescue-only"
    )


if __name__ == "__main__":
    main()