"""Canonical read-only Solana RPC topology for Meme Machine.

Provider policy:
- MM_SOLANA_READ_RPC_URL (Alchemy) is the only authenticated Solana HTTP evidence endpoint.
- Public Solana WebSocket discovery remains separate from HTTP evidence acquisition.
- Public HTTP is an uncredentialed local-development fallback only when Alchemy is not
  explicitly required; production certification requires Alchemy.
- There is no automatic HTTP rescue provider or load balancing.
- One logical RPC budget remains authoritative and every physical HTTP request is counted.
- This module never signs or submits transactions.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from urllib.parse import urlparse

from .postgrad import PoolScanRPC
from .provider import RPC, Unavailable


PRIMARY_PROVIDER = "alchemy_solana_mainnet"
PUBLIC_HTTP_PROVIDER = "solana_public_mainnet_fallback"
PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"
PUBLIC_RPC_HOST = "api.mainnet-beta.solana.com"
PUBLIC_OVERRIDE_ENV_NAME = "MM_SOLANA_PUBLIC_RPC_URL"

# Backward-compatible import only. Production callers pass required=True and must
# resolve the authenticated Alchemy endpoint; this constant is not runtime authority.
PRIMARY_RPC_URL = PUBLIC_RPC_URL
PRIMARY_RPC_HOST = "solana-mainnet.g.alchemy.com"


SECONDARY_PROVIDER = "none"
ALCHEMY_ENV_NAME = "MM_SOLANA_READ_RPC_URL"
ALCHEMY_SOLANA_MAINNET_HOST = "solana-mainnet.g.alchemy.com"

TOPOLOGY_LABEL = "alchemy_primary_no_rescue_public_ws_discovery"
SOLANA_MIN_REQUEST_INTERVAL_SECONDS = 1.0
PROVIDER_429_MIN_BACKOFF_SECONDS = 2.0


def _source(environ=None):
    return os.environ if environ is None else environ


def _validate_alchemy_url(value):
    parsed=urlparse(value)
    if (
        parsed.scheme!="https"
        or parsed.hostname!=ALCHEMY_SOLANA_MAINNET_HOST
        or parsed.port not in (None,443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise Unavailable("alchemy_rpc_endpoint_required")
    parts=[part for part in parsed.path.split("/") if part]
    if len(parts)!=2 or parts[0]!="v2" or not parts[1] or "<" in parts[1] or ">" in parts[1]:
        raise Unavailable("alchemy_rpc_endpoint_required")
    return value


def primary_rpc_url(environ=None, *, required=False):
    source=_source(environ)
    value=str(source.get(ALCHEMY_ENV_NAME,"") or "").strip()
    if value:
        return _validate_alchemy_url(value)
    if required:
        raise Unavailable("alchemy_rpc_missing")
    override=str(source.get(PUBLIC_OVERRIDE_ENV_NAME,"") or "").strip()
    if override:
        parsed=urlparse(override)
        if parsed.scheme!="https" or parsed.hostname!=PUBLIC_RPC_HOST or parsed.query or parsed.fragment:
            raise Unavailable("solana_public_rpc_endpoint_required")
        return override
    return PUBLIC_RPC_URL


def primary_provider(environ=None):
    source=_source(environ)
    return PRIMARY_PROVIDER if str(source.get(ALCHEMY_ENV_NAME,"") or "").strip() else PUBLIC_HTTP_PROVIDER


def secondary_rpc_url(environ=None, *, required=False):
    if required:
        raise Unavailable("solana_http_secondary_disabled")
    return None


class SolanaReadPacer:
    """One conservative request clock shared across bounded RPC objects.

    The conservative default cadence is shared across bounded Alchemy RPC objects so
    session rotation cannot silently broaden evidence acquisition or request volume.
    """

    def __init__(self, minimum_interval=SOLANA_MIN_REQUEST_INTERVAL_SECONDS):
        if minimum_interval < 0.2 or minimum_interval > 5.0:
            raise ValueError("solana_read_pace_bound")
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


class _ReadOnlyFailoverMixin:
    """Single-provider Alchemy HTTP transport; legacy class name is import-compatible."""

    def _init_failover(self, secondary_url, pacer, primary_label=PRIMARY_PROVIDER):
        self.primary_provider = primary_label
        self.secondary_url = secondary_url
        self.read_pacer = pacer or SolanaReadPacer()
        # Compatibility for existing DLMM research code that still reads this name.
        self.alchemy_pacer = self.read_pacer
        self.provider_http_requests = Counter()
        self.provider_successes = Counter()
        self.provider_failures = Counter()
        self.provider_failure_reasons = Counter()
        self.failover_count = 0
        self.failover_reasons = Counter()

    def _pace(self, interval=0.5):
        if self.transport == self._http:
            self.read_pacer.pace(self, interval)

    @staticmethod
    def _retry_delay(exc):
        delay = RPC._retry_delay(exc)
        if isinstance(exc, urllib.error.HTTPError) and int(exc.code) == 429:
            return max(float(delay), PROVIDER_429_MIN_BACKOFF_SECONDS)
        return delay

    @staticmethod
    def _request_url(url, request):
        data = json.dumps(request).encode()
        req = urllib.request.Request(url, data, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise Unavailable("response_size_limit")
        return json.loads(raw)

    @staticmethod
    def _single_response_issue(request, response):
        if not isinstance(response, dict):
            return "invalid_jsonrpc_shape"
        if response.get("error") or "result" not in response:
            return "provider_error"
        if (
            isinstance(request, dict)
            and request.get("method") == "getTransaction"
            and response.get("result") is None
        ):
            return "null_getTransaction"
        return None

    @classmethod
    def _response_issue(cls, request, response):
        if not isinstance(request, list):
            return cls._single_response_issue(request, response)
        # A semantic batch rejection is not rerouted to another provider. The base
        # call_many() implementation may degrade missing/error/null batch members to
        # bounded individual logical calls against the same Alchemy authority.
        return None

    @staticmethod
    def _exception_reason(exc):
        if isinstance(exc, urllib.error.HTTPError):
            return f"http_{int(exc.code)}"
        if isinstance(exc, (TimeoutError, urllib.error.URLError)):
            return "network_or_timeout"
        if isinstance(exc, json.JSONDecodeError):
            return "invalid_json"
        if isinstance(exc, Unavailable):
            return str(exc) or "provider_unavailable"
        return type(exc).__name__

    def _provider_attempt(self, label, url, request):
        self.provider_http_requests[label] += 1
        try:
            response = self._request_url(url, request)
            issue = self._response_issue(request, response)
            if issue is not None:
                raise Unavailable(issue)
            self.provider_successes[label] += 1
            return response
        except Exception as exc:
            self.provider_failures[label] += 1
            self.provider_failure_reasons[
                f"{label}:{self._exception_reason(exc)}"
            ] += 1
            raise

    def _http(self, request):
        try:
            return self._provider_attempt(self.primary_provider, self.url, request)
        except Exception as primary_exc:
            if not self.secondary_url:
                raise
            reason = self._exception_reason(primary_exc)
            self.failover_count += 1
            self.failover_reasons[reason] += 1
            # RPC.call/call_many already counted the primary physical transport.
            # Count the rescue transport explicitly so http_requests remains physical.
            self.http_requests += 1
            return self._provider_attempt(
                SECONDARY_PROVIDER,
                self.secondary_url,
                request,
            )

    def provider_telemetry(self):
        return dict(
            topology=TOPOLOGY_LABEL,
            primary_provider=self.primary_provider,
            secondary_provider=SECONDARY_PROVIDER,
            secondary_configured=bool(self.secondary_url),
            logical_calls=int(self.calls),
            physical_http_requests=int(self.http_requests),
            provider_http_requests=dict(sorted(self.provider_http_requests.items())),
            provider_successes=dict(sorted(self.provider_successes.items())),
            provider_failures=dict(sorted(self.provider_failures.items())),
            provider_failure_reasons=dict(sorted(self.provider_failure_reasons.items())),
            failover_count=int(self.failover_count),
            failover_reasons=dict(sorted(self.failover_reasons.items())),
            pacing=self.read_pacer.telemetry(),
        )


class ReadOnlyFailoverRPC(_ReadOnlyFailoverMixin, RPC):
    def __init__(
        self,
        primary_url,
        *,
        secondary_url=None,
        limit=120,
        pacer=None,
        **kwargs,
    ):
        primary_provider=kwargs.pop("primary_provider",PRIMARY_PROVIDER)
        self._init_failover(secondary_url, pacer, primary_provider)
        super().__init__(primary_url, limit=limit, **kwargs)


class ReadOnlyFailoverPoolScanRPC(_ReadOnlyFailoverMixin, PoolScanRPC):
    # Historical DLMM diagnostics also require getBlock. It remains read-only and is
    # included here so every Solana research path shares the same provider topology.
    ALLOWED = PoolScanRPC.ALLOWED | {"getBlock"}

    def __init__(
        self,
        primary_url,
        *,
        secondary_url=None,
        limit=240,
        pacer=None,
        **kwargs,
    ):
        primary_provider=kwargs.pop("primary_provider",PRIMARY_PROVIDER)
        self._init_failover(secondary_url, pacer, primary_provider)
        super().__init__(primary_url, limit=limit, **kwargs)


def new_rpc(limit=120, pacer=None, environ=None, **kwargs):
    return ReadOnlyFailoverRPC(
        primary_rpc_url(environ),
        secondary_url=None,
        primary_provider=primary_provider(environ),
        limit=limit,
        pacer=pacer,
        **kwargs,
    )


def new_pool_scan_rpc(limit=240, pacer=None, environ=None, **kwargs):
    return ReadOnlyFailoverPoolScanRPC(
        primary_rpc_url(environ),
        secondary_url=None,
        primary_provider=primary_provider(environ),
        limit=limit,
        pacer=pacer,
        **kwargs,
    )


def metadata(environ=None):
    source=_source(environ)
    alchemy=bool(str(source.get(ALCHEMY_ENV_NAME,"") or "").strip())
    return dict(
        topology=TOPOLOGY_LABEL,
        primary_provider=primary_provider(environ),
        primary_public=not alchemy,
        primary_credential=(ALCHEMY_ENV_NAME if alchemy else None),
        secondary_provider=SECONDARY_PROVIDER,
        secondary_credential=None,
        secondary_configured=False,
        fallback_allowed=False,
        fallback_policy="fail_closed_no_automatic_http_rescue",
        load_balancing=False,
        network="solana-mainnet",
        signing=False,
        submission=False,
        minimum_request_interval_seconds=SOLANA_MIN_REQUEST_INTERVAL_SECONDS,
        minimum_429_backoff_seconds=PROVIDER_429_MIN_BACKOFF_SECONDS,
    )


def validate_topology(environ=None, *, require_secondary=False, require_authenticated_primary=False):
    primary_rpc_url(environ,required=True)
    if require_secondary:
        raise Unavailable("solana_http_secondary_disabled")
    return metadata(environ)
