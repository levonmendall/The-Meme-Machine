"""Lane-specific Robinhood RPC governance modeled on current Solana behavior.

Roles:
- directional/Pons: authenticated primary evidence RPC, 2 RPS, fail closed, no
  automatic alternate-provider evidence;
- Ramses/DLMM: dedicated bulk/reconstruction RPC, 5 RPS, bounded sessions, no
  automatic rescue. Until MM_ROBINHOOD_DLMM_RPC_URL is configured it explicitly
  falls back to the authenticated primary while preserving separate pacing;
- shadow: optional independent provider for disagreement/diagnostic reads only;
- official Robinhood public RPC: diagnostic-only;
- official sequencer feed: discovery/observation plane, never trade authority.

This module never signs or submits transactions and never changes strategy rules.
"""
from __future__ import annotations

from collections import Counter
import os
import threading
import time
from urllib.parse import urlsplit

from . import BoundaryError, CHAIN_ID
from .provider import Rpc


PRIMARY_ENV = "MM_ROBINHOOD_READ_RPC_URL"
DLMM_ENV = "MM_ROBINHOOD_DLMM_RPC_URL"
SHADOW_ENV = "MM_ROBINHOOD_SHADOW_RPC_URL"
QUICKNODE_ENV = "MM_ROBINHOOD_QUICKNODE_RPC_URL"  # compatibility-only alias

PUBLIC_DIAGNOSTIC_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
SEQUENCER_FEED_URL = "wss://feed.mainnet.chain.robinhood.com"

DIRECTIONAL_RPS = 2.0
DLMM_RPS = 5.0
SHADOW_RPS = 5.0

ALCHEMY_ONLY_METHODS = frozenset({"alchemy_getAssetTransfers"})


def _env(name, environ=None):
    source = os.environ if environ is None else environ
    return str(source.get(name, "") or "").strip()


def _provider_kind(endpoint):
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or "").lower()
    if not host:
        return "unknown"
    if host.endswith("alchemy.com") or ".alchemy.com" in host:
        return "alchemy"
    if "quiknode" in host or "quicknode" in host:
        return "quicknode"
    if "validationcloud" in host:
        return "validation_cloud"
    if "chainstack" in host:
        return "chainstack"
    if host == "rpc.mainnet.chain.robinhood.com":
        return "robinhood_public"
    return "other_authenticated"


def _require_https(endpoint, error):
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise BoundaryError(error)
    return endpoint


def primary_endpoint(primary_endpoint=None, *, environ=None):
    value = str(primary_endpoint or "").strip() or _env(PRIMARY_ENV, environ)
    if not value:
        raise BoundaryError("MM_ROBINHOOD_READ_RPC_URL_requires_full_https_url")
    return _require_https(
        value,
        "MM_ROBINHOOD_READ_RPC_URL_requires_full_https_url",
    )


def dlmm_endpoint(primary_fallback_endpoint=None, *, environ=None):
    value = _env(DLMM_ENV, environ)
    if value:
        return _require_https(
            value,
            "MM_ROBINHOOD_DLMM_RPC_URL_requires_full_https_url",
        ), False
    return primary_endpoint(primary_fallback_endpoint, environ=environ), True


def shadow_endpoint(*, environ=None):
    value = _env(SHADOW_ENV, environ) or _env(QUICKNODE_ENV, environ)
    if not value:
        return None
    return _require_https(
        value,
        "MM_ROBINHOOD_SHADOW_RPC_URL_requires_full_https_url",
    )


class ProviderPacer:
    """Thread-safe physical-request pacer shared across bounded RPC sessions."""

    def __init__(self, requests_per_second, *, clock=time.monotonic, sleeper=time.sleep):
        rps = float(requests_per_second)
        if not 0.2 <= rps <= 25.0:
            raise BoundaryError("invalid_provider_rps")
        self.requests_per_second = rps
        self.minimum_interval_seconds = 1.0 / rps
        self.clock = clock
        self.sleep = sleeper
        self._lock = threading.Lock()
        self.next_at = -float("inf")
        self.paced_requests = 0
        self.sleep_seconds = 0.0

    def pace(self):
        with self._lock:
            now = float(self.clock())
            wait = max(0.0, self.next_at - now)
            if wait:
                self.sleep(wait)
                self.sleep_seconds += wait
                now = max(float(self.clock()), now + wait)
            self.next_at = now + self.minimum_interval_seconds
            self.paced_requests += 1
            return wait

    def telemetry(self):
        return dict(
            requests_per_second=self.requests_per_second,
            minimum_interval_seconds=self.minimum_interval_seconds,
            paced_requests=self.paced_requests,
            throttle_sleep_seconds=self.sleep_seconds,
        )


class PacedRpc(Rpc):
    """Existing bounded Rpc with a physical-request pace and explicit provider role."""

    def __init__(
        self,
        endpoint,
        *,
        role,
        requests_per_second,
        pacer=None,
        transport=None,
        **kwargs,
    ):
        self.role = str(role)
        self.provider_kind = _provider_kind(endpoint)
        self.pacer = pacer or ProviderPacer(requests_per_second)
        self._injected_transport = transport
        if transport is None:
            super().__init__(endpoint, transport=None, **kwargs)
        else:
            def paced_transport(method, params):
                self.pacer.pace()
                return transport(method, params)
            super().__init__(endpoint, transport=paced_transport, **kwargs)

    def _http(self, method, params):
        self.pacer.pace()
        return super()._http(method, params)

    def _http_batch(self, calls):
        self.pacer.pace()
        return super()._http_batch(calls)

    def _method_allowed_for_provider(self, method):
        if method in ALCHEMY_ONLY_METHODS and self.provider_kind != "alchemy":
            raise BoundaryError("provider_specific_method_wrong_provider")

    def call(self, method, params, *, scope="connectivity"):
        self._method_allowed_for_provider(method)
        return super().call(method, params, scope=scope)

    def batch(self, calls, *, scope="connectivity"):
        for row in calls or []:
            if isinstance(row, (list, tuple)) and row:
                self._method_allowed_for_provider(row[0])
        return super().batch(calls, scope=scope)

    def telemetry(self):
        data = super().telemetry()
        data.update(
            role=self.role,
            provider_kind=self.provider_kind,
            pacing=self.pacer.telemetry(),
            automatic_failover=False,
        )
        return data


# Shared clocks prevent session rotation or concurrent candidate evaluation from
# multiplying provider throughput.
_DIRECTIONAL_PACER = ProviderPacer(DIRECTIONAL_RPS)
_DLMM_PACERS = {}
_SHADOW_PACERS = {}


def _pacer_for(store, endpoint, rps):
    kind = _provider_kind(endpoint)
    key = (kind, urlsplit(endpoint).hostname or "")
    pacer = store.get(key)
    if pacer is None:
        pacer = ProviderPacer(rps)
        store[key] = pacer
    return pacer


def configured_rpc(primary_endpoint_value=None, *, environ=None, **kwargs):
    """Authoritative Pons/directional evidence RPC: 2 RPS, no automatic rescue."""
    endpoint = primary_endpoint(primary_endpoint_value, environ=environ)
    return PacedRpc(
        endpoint,
        role="directional_evidence_primary",
        requests_per_second=DIRECTIONAL_RPS,
        pacer=_DIRECTIONAL_PACER,
        **kwargs,
    )


def configured_dlmm_rpc(primary_fallback_endpoint=None, *, environ=None, **kwargs):
    """Ramses reconstruction RPC: dedicated 5 RPS lane, no automatic rescue."""
    endpoint, primary_fallback = dlmm_endpoint(
        primary_fallback_endpoint, environ=environ
    )
    pacer = _pacer_for(_DLMM_PACERS, endpoint, DLMM_RPS)
    rpc = PacedRpc(
        endpoint,
        role=(
            "dlmm_reconstruction_primary_fallback"
            if primary_fallback
            else "dlmm_reconstruction_primary"
        ),
        requests_per_second=DLMM_RPS,
        pacer=pacer,
        **kwargs,
    )
    rpc.primary_fallback = bool(primary_fallback)
    return rpc


def configured_shadow_rpc(*, environ=None, limit=40, per_scope=40, retries=0):
    """Independent comparison source only; never returned by evidence constructors."""
    endpoint = shadow_endpoint(environ=environ)
    if not endpoint:
        return None
    pacer = _pacer_for(_SHADOW_PACERS, endpoint, SHADOW_RPS)
    return PacedRpc(
        endpoint,
        role="shadow_diagnostic_only",
        requests_per_second=SHADOW_RPS,
        pacer=pacer,
        limit=limit,
        per_scope=per_scope,
        retries=retries,
    )


def public_diagnostic_rpc(*, limit=20, per_scope=20, retries=0):
    return PacedRpc(
        PUBLIC_DIAGNOSTIC_RPC_URL,
        role="robinhood_public_diagnostic_only",
        requests_per_second=2.0,
        limit=limit,
        per_scope=per_scope,
        retries=retries,
    )


def topology_metadata(*, environ=None):
    primary = primary_endpoint(environ=environ)
    dlmm, fallback = dlmm_endpoint(environ=environ)
    shadow = shadow_endpoint(environ=environ)
    return dict(
        network="robinhood-mainnet",
        chain_id=CHAIN_ID,
        directional=dict(
            discovery="official_robinhood_sequencer_feed",
            evidence_provider_kind=_provider_kind(primary),
            evidence_credential=PRIMARY_ENV,
            requests_per_second=DIRECTIONAL_RPS,
            automatic_failover=False,
            fail_closed=True,
        ),
        dlmm=dict(
            provider_kind=_provider_kind(dlmm),
            credential=(PRIMARY_ENV if fallback else DLMM_ENV),
            primary_fallback=fallback,
            requests_per_second=DLMM_RPS,
            automatic_failover=False,
        ),
        shadow=dict(
            configured=bool(shadow),
            provider_kind=(None if not shadow else _provider_kind(shadow)),
            credential=(
                None
                if not shadow
                else (
                    SHADOW_ENV
                    if _env(SHADOW_ENV, environ)
                    else QUICKNODE_ENV
                )
            ),
            authority="diagnostic_only",
        ),
        public_rpc=dict(
            role="diagnostic_only",
            url_kind="official_robinhood_public",
        ),
        signing=False,
        submission=False,
    )