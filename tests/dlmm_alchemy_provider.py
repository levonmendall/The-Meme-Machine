"""Canonical read-only RPC routing and pacing for DLMM research.

DLMM uses the existing Meme Machine GitHub secret MM_SOLANA_READ_RPC_URL.
The configured value must be the full Alchemy Solana Mainnet HTTPS endpoint.
There is no fallback to Solana Labs, PublicNode, another Alchemy app, or another
provider.

Live DLMM acquisition uses a shared pacing gate across otherwise independent RPC
budget objects. This lets every attempted pool have its own bounded logical-call
budget without turning each budget reset into an HTTP burst.
"""
from __future__ import annotations

import os
import urllib.error
from urllib.parse import urlparse

from meme_machine.postgrad import PoolScanRPC
from meme_machine.provider import RPC, Unavailable

ENV_NAME = "MM_SOLANA_READ_RPC_URL"
ALCHEMY_SOLANA_MAINNET_HOST = "solana-mainnet.g.alchemy.com"
PROVIDER_LABEL = "alchemy_solana_mainnet_existing_secret"

ALCHEMY_MIN_REQUEST_INTERVAL_SECONDS = 1.0
ALCHEMY_429_MIN_BACKOFF_SECONDS = 2.0


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


class AlchemyPacer:
    """One serialized request clock shared across per-pool RPC budget objects."""

    def __init__(self, minimum_interval=ALCHEMY_MIN_REQUEST_INTERVAL_SECONDS):
        if minimum_interval < 0.5 or minimum_interval > 5.0:
            raise ValueError("dlmm_alchemy_pace_bound")
        self.minimum_interval = float(minimum_interval)
        self.next_request_at = -float("inf")
        self.paced_requests = 0
        self.sleep_seconds = 0.0

    def pace(self, rpc, requested_interval=0.5):
        interval = max(float(requested_interval), self.minimum_interval)
        now = float(rpc.clock())
        wait = max(0.0, self.next_request_at - now)
        if wait:
            rpc.sleep(wait)
            self.sleep_seconds += wait
            # Test clocks may not advance when their sleeper is a no-op.
            now = max(float(rpc.clock()), now + wait)
        else:
            now = float(rpc.clock())
        self.next_request_at = now + interval
        rpc.last_request = now
        self.paced_requests += 1
        return wait

    def telemetry(self):
        return dict(
            minimum_interval_seconds=self.minimum_interval,
            paced_requests=self.paced_requests,
            throttle_sleep_seconds=self.sleep_seconds,
        )


class AlchemyPoolScanRPC(PoolScanRPC):
    """PoolScanRPC with Alchemy-safe pacing and bounded 429 cooldown."""

    def __init__(self, url, limit=240, pacer=None, **kwargs):
        self.alchemy_pacer = pacer or AlchemyPacer()
        super().__init__(url, limit=limit, **kwargs)

    def _pace(self, interval=0.5):
        if self.transport == self._http:
            self.alchemy_pacer.pace(self, interval)

    @staticmethod
    def _retry_delay(exc):
        delay = RPC._retry_delay(exc)
        if isinstance(exc, urllib.error.HTTPError) and int(exc.code) == 429:
            return max(float(delay), ALCHEMY_429_MIN_BACKOFF_SECONDS)
        return delay


def new_rpc(limit=240, pacer=None, **kwargs):
    return AlchemyPoolScanRPC(
        rpc_url(),
        limit=limit,
        pacer=pacer,
        **kwargs,
    )


def metadata():
    return dict(
        provider=PROVIDER_LABEL,
        credential=ENV_NAME,
        network="solana-mainnet",
        host=ALCHEMY_SOLANA_MAINNET_HOST,
        fallback_allowed=False,
        signing=False,
        submission=False,
        minimum_request_interval_seconds=ALCHEMY_MIN_REQUEST_INTERVAL_SECONDS,
        minimum_429_backoff_seconds=ALCHEMY_429_MIN_BACKOFF_SECONDS,
    )


def main():
    rpc_url()
    print(
        "DLMM existing MM_SOLANA_READ_RPC_URL is configured for "
        "Alchemy Solana Mainnet; provider fallback is disabled"
    )


if __name__ == "__main__":
    main()
