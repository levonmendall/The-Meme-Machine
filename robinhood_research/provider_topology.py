"""Lane-specific Robinhood RPC governance modeled on current Solana behavior.

Roles:
- directional/Pons evidence: authenticated primary RPC, 2 RPS, fail closed, no
  automatic alternate-provider evidence;
- Pons discovery: dedicated discovery RPC (or the dedicated DLMM RPC when the
  discovery credential is absent), 5 RPS, observation-only, never primary fallback;
- Ramses/DLMM: dedicated bulk/reconstruction RPC, 5 RPS, bounded sessions, never
  primary fallback;
- shadow: optional independent provider for disagreement/diagnostic reads only;
- official Robinhood public RPC: diagnostic-only;
- official sequencer feed: discovery/observation plane, never trade authority.

Broad observation can degrade or pause when its dedicated transport is unavailable,
but bulk discovery/research never silently spills onto the authoritative primary.
This module never signs or submits transactions and never changes strategy rules.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import os
import threading
import time
from urllib.parse import urlsplit

from . import BoundaryError, CHAIN_ID
from .provider import Rpc


PRIMARY_ENV = "MM_ROBINHOOD_READ_RPC_URL"
DISCOVERY_ENV = "MM_ROBINHOOD_DISCOVERY_RPC_URL"
DLMM_ENV = "MM_ROBINHOOD_DLMM_RPC_URL"
SHADOW_ENV = "MM_ROBINHOOD_SHADOW_RPC_URL"
QUICKNODE_ENV = "MM_ROBINHOOD_QUICKNODE_RPC_URL"  # compatibility-only alias

PUBLIC_DIAGNOSTIC_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
SEQUENCER_FEED_URL = "wss://feed.mainnet.chain.robinhood.com"

DIRECTIONAL_RPS = 2.0
DISCOVERY_RPS = 5.0
DLMM_RPS = 5.0
SHADOW_RPS = 5.0

ALCHEMY_ONLY_METHODS = frozenset({"alchemy_getAssetTransfers"})


def _env(name, environ=None):
    source = os.environ if environ is None else environ
    return str(source.get(name, "") or "").strip()


def _normalized_endpoint(endpoint):
    value = str(endpoint or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    port = "" if parsed.port is None else f":{parsed.port}"
    path = parsed.path.rstrip("/")
    query = "" if not parsed.query else "?" + parsed.query
    return f"{parsed.scheme.lower()}://{host}{port}{path}{query}"


def _endpoint_fingerprint(endpoint):
    normalized = _normalized_endpoint(endpoint)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _optional_primary_endpoint(primary_endpoint_value=None, *, environ=None):
    value = str(primary_endpoint_value or "").strip() or _env(PRIMARY_ENV, environ)
    if not value:
        return None
    return _require_https(
        value,
        "MM_ROBINHOOD_READ_RPC_URL_requires_full_https_url",
    )


def _require_bulk_isolation(endpoint, primary, *, lane):
    if _provider_kind(endpoint) == "alchemy":
        raise BoundaryError(f"{lane}_alchemy_endpoint_forbidden")
    if (
        primary
        and _endpoint_fingerprint(endpoint) == _endpoint_fingerprint(primary)
    ):
        raise BoundaryError(f"{lane}_primary_endpoint_reuse_forbidden")
    return endpoint


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


def discovery_endpoint(primary_fallback_endpoint=None, *, environ=None):
    """Return a non-primary observation endpoint or fail closed.

    A configured discovery endpoint that resolves to Alchemy/the authoritative
    primary is treated as unsuitable for bulk observation. When the dedicated
    DLMM endpoint is independently isolated, discovery transparently shares that
    provider instead of either losing observability or spilling onto Alchemy.
    """
    primary = _optional_primary_endpoint(
        primary_fallback_endpoint, environ=environ
    )
    rejected = None
    value = _env(DISCOVERY_ENV, environ)
    if value:
        endpoint = _require_https(
            value,
            "MM_ROBINHOOD_DISCOVERY_RPC_URL_requires_full_https_url",
        )
        try:
            return _require_bulk_isolation(
                endpoint, primary, lane="robinhood_discovery"
            ), False
        except BoundaryError as exc:
            rejected = exc

    # Discovery may share the dedicated DLMM provider because it has no allocation
    # authority. It must never consume the authoritative primary as a capacity rescue.
    shared = _env(DLMM_ENV, environ)
    if shared:
        endpoint = _require_https(
            shared,
            "MM_ROBINHOOD_DLMM_RPC_URL_requires_full_https_url",
        )
        return _require_bulk_isolation(
            endpoint, primary, lane="robinhood_discovery"
        ), False

    if rejected is not None:
        raise rejected
    raise BoundaryError("robinhood_discovery_provider_required")


def dlmm_endpoint(primary_fallback_endpoint=None, *, environ=None):
    """Return the dedicated non-primary Ramses transport or fail closed."""
    primary = _optional_primary_endpoint(
        primary_fallback_endpoint, environ=environ
    )
    value = _env(DLMM_ENV, environ)
    if not value:
        raise BoundaryError("robinhood_dlmm_provider_required")
    endpoint = _require_https(
        value,
        "MM_ROBINHOOD_DLMM_RPC_URL_requires_full_https_url",
    )
    return _require_bulk_isolation(
        endpoint, primary, lane="robinhood_dlmm"
    ), False


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
        pace_injected_transport=False,
        **kwargs,
    ):
        self.role = str(role)
        self.provider_kind = _provider_kind(endpoint)
        self.pacer = pacer or ProviderPacer(requests_per_second)
        self._injected_transport = transport
        if transport is None:
            super().__init__(endpoint, transport=None, **kwargs)
        elif pace_injected_transport:
            def paced_transport(method, params):
                self.pacer.pace()
                return transport(method, params)
            super().__init__(endpoint, transport=paced_transport, **kwargs)
        else:
            # Deterministic tests/captured transports retain their original timing.
            super().__init__(endpoint, transport=transport, **kwargs)

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
            endpoint_fingerprint=_endpoint_fingerprint(self._endpoint),
            credential_role=getattr(self, "credential_role", None),
            pacing=self.pacer.telemetry(),
            automatic_failover=False,
        )
        return data


# Shared clocks prevent session rotation or concurrent candidate evaluation from
# multiplying provider throughput.
_DIRECTIONAL_PACER = ProviderPacer(DIRECTIONAL_RPS)
_DISCOVERY_PACERS = {}
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
    rpc = PacedRpc(
        endpoint,
        role="directional_evidence_primary",
        requests_per_second=DIRECTIONAL_RPS,
        pacer=_DIRECTIONAL_PACER,
        **kwargs,
    )
    rpc.credential_role = PRIMARY_ENV
    return rpc


def configured_discovery_rpc(primary_fallback_endpoint=None, *, environ=None, **kwargs):
    """Pons discovery/log RPC: 5 RPS, sequencer-triggered, no decision authority."""
    endpoint, _ = discovery_endpoint(
        primary_fallback_endpoint, environ=environ
    )
    pacer = _pacer_for(_DISCOVERY_PACERS, endpoint, DISCOVERY_RPS)
    rpc = PacedRpc(
        endpoint,
        role="pons_discovery_primary",
        requests_per_second=DISCOVERY_RPS,
        pacer=pacer,
        **kwargs,
    )
    rpc.primary_fallback = False
    dedicated = _env(DISCOVERY_ENV, environ)
    rpc.credential_role = (
        DISCOVERY_ENV
        if dedicated and _endpoint_fingerprint(dedicated) == _endpoint_fingerprint(endpoint)
        else DLMM_ENV
    )
    return rpc


def configured_dlmm_rpc(primary_fallback_endpoint=None, *, environ=None, **kwargs):
    """Ramses reconstruction RPC: dedicated 5 RPS lane, no primary rescue."""
    endpoint, _ = dlmm_endpoint(
        primary_fallback_endpoint, environ=environ
    )
    pacer = _pacer_for(_DLMM_PACERS, endpoint, DLMM_RPS)
    rpc = PacedRpc(
        endpoint,
        role="dlmm_reconstruction_primary",
        requests_per_second=DLMM_RPS,
        pacer=pacer,
        **kwargs,
    )
    rpc.primary_fallback = False
    rpc.credential_role = DLMM_ENV
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
    shadow = shadow_endpoint(environ=environ)

    discovery = None
    discovery_error = None
    try:
        discovery, _ = discovery_endpoint(environ=environ)
    except BoundaryError as exc:
        discovery_error = str(exc)

    dlmm = None
    dlmm_error = None
    try:
        dlmm, _ = dlmm_endpoint(environ=environ)
    except BoundaryError as exc:
        dlmm_error = str(exc)

    return dict(
        network="robinhood-mainnet",
        chain_id=CHAIN_ID,
        directional=dict(
            discovery="official_robinhood_sequencer_feed_plus_discovery_rpc",
            discovery_configured=bool(discovery),
            discovery_provider_kind=(
                None if not discovery else _provider_kind(discovery)
            ),
            discovery_endpoint_fingerprint=(
                None if not discovery else _endpoint_fingerprint(discovery)
            ),
            discovery_credential=(
                None
                if not discovery
                else (
                    DISCOVERY_ENV
                    if (
                        _env(DISCOVERY_ENV, environ)
                        and _endpoint_fingerprint(_env(DISCOVERY_ENV, environ))
                        == _endpoint_fingerprint(discovery)
                    )
                    else DLMM_ENV
                )
            ),
            discovery_alchemy_candidate_bypassed=bool(
                discovery
                and _env(DISCOVERY_ENV, environ)
                and _provider_kind(_env(DISCOVERY_ENV, environ)) == "alchemy"
                and _endpoint_fingerprint(_env(DISCOVERY_ENV, environ))
                != _endpoint_fingerprint(discovery)
            ),
            discovery_primary_fallback=False,
            discovery_requests_per_second=DISCOVERY_RPS,
            discovery_fail_closed=True,
            discovery_error=discovery_error,
            evidence_provider_kind=_provider_kind(primary),
            evidence_endpoint_fingerprint=_endpoint_fingerprint(primary),
            evidence_credential=PRIMARY_ENV,
            requests_per_second=DIRECTIONAL_RPS,
            automatic_failover=False,
            fail_closed=True,
        ),
        dlmm=dict(
            configured=bool(dlmm),
            provider_kind=(None if not dlmm else _provider_kind(dlmm)),
            endpoint_fingerprint=(
                None if not dlmm else _endpoint_fingerprint(dlmm)
            ),
            credential=(DLMM_ENV if dlmm else None),
            primary_fallback=False,
            requests_per_second=DLMM_RPS,
            automatic_failover=False,
            fail_closed=True,
            error=dlmm_error,
        ),
        shadow=dict(
            configured=bool(shadow),
            provider_kind=(None if not shadow else _provider_kind(shadow)),
            endpoint_fingerprint=(
                None if not shadow else _endpoint_fingerprint(shadow)
            ),
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
        provider_role_isolation=True,
        bulk_primary_fallback=False,
        signing=False,
        submission=False,
    )
