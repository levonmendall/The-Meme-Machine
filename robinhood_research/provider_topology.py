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
# Compatibility rates only when an explicitly configured bulk credential aliases
# the authoritative primary endpoint. Discovery keeps enough cadence for the
# five-second evidence window; DLMM is deliberately slower because it is screening.
SHARED_PRIMARY_DISCOVERY_RPS = 2.0
SHARED_PRIMARY_DLMM_RPS = 1.0

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


def _is_primary_endpoint(endpoint, primary):
    return bool(
        primary
        and _endpoint_fingerprint(endpoint) == _endpoint_fingerprint(primary)
    )


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
    """Return the best explicitly configured observation endpoint.

    Prefer an endpoint that is distinct from the authoritative primary. If the
    discovery credential aliases primary, an independently configured DLMM endpoint
    is preferred. When every explicitly configured observation endpoint aliases
    primary, retain observability in a clearly marked, lower-throughput shared mode
    rather than silently broadening authority or dropping the market view.
    """
    primary = _optional_primary_endpoint(
        primary_fallback_endpoint, environ=environ
    )
    primary_candidate = None

    value = _env(DISCOVERY_ENV, environ)
    if value:
        endpoint = _require_https(
            value,
            "MM_ROBINHOOD_DISCOVERY_RPC_URL_requires_full_https_url",
        )
        if not _is_primary_endpoint(endpoint, primary):
            return endpoint, False
        primary_candidate = endpoint

    shared = _env(DLMM_ENV, environ)
    if shared:
        endpoint = _require_https(
            shared,
            "MM_ROBINHOOD_DLMM_RPC_URL_requires_full_https_url",
        )
        if not _is_primary_endpoint(endpoint, primary):
            return endpoint, False
        if primary_candidate is None:
            primary_candidate = endpoint

    if primary_candidate is not None:
        return primary_candidate, True
    raise BoundaryError("robinhood_discovery_provider_required")


def dlmm_endpoint(primary_fallback_endpoint=None, *, environ=None):
    """Return the explicitly configured Ramses transport and whether it aliases primary."""
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
    return endpoint, _is_primary_endpoint(endpoint, primary)


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
            primary_shared=bool(getattr(self, "primary_shared", False)),
            pacing=self.pacer.telemetry(),
            automatic_failover=False,
        )
        return data


# Shared clocks prevent session rotation or concurrent candidate evaluation from
# multiplying provider throughput.
_DIRECTIONAL_PACER = ProviderPacer(DIRECTIONAL_RPS)
_SHARED_PRIMARY_DISCOVERY_PACER = ProviderPacer(SHARED_PRIMARY_DISCOVERY_RPS)
_SHARED_PRIMARY_DLMM_PACER = ProviderPacer(SHARED_PRIMARY_DLMM_RPS)
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
    """Pons discovery/log RPC with explicit shared-primary compatibility."""
    endpoint, primary_shared = discovery_endpoint(
        primary_fallback_endpoint, environ=environ
    )
    if primary_shared:
        rps = SHARED_PRIMARY_DISCOVERY_RPS
        pacer = _SHARED_PRIMARY_DISCOVERY_PACER
        role = "pons_discovery_primary_shared_observation"
    else:
        rps = DISCOVERY_RPS
        pacer = _pacer_for(_DISCOVERY_PACERS, endpoint, DISCOVERY_RPS)
        role = "pons_discovery_primary"
    rpc = PacedRpc(
        endpoint,
        role=role,
        requests_per_second=rps,
        pacer=pacer,
        **kwargs,
    )
    rpc.primary_fallback = False
    rpc.primary_shared = bool(primary_shared)
    dedicated = _env(DISCOVERY_ENV, environ)
    rpc.credential_role = (
        DISCOVERY_ENV
        if dedicated and _endpoint_fingerprint(dedicated) == _endpoint_fingerprint(endpoint)
        else DLMM_ENV
    )
    return rpc


def configured_dlmm_rpc(primary_fallback_endpoint=None, *, environ=None, **kwargs):
    """Ramses reconstruction RPC with low-rate explicit shared-primary compatibility."""
    endpoint, primary_shared = dlmm_endpoint(
        primary_fallback_endpoint, environ=environ
    )
    if primary_shared:
        rps = SHARED_PRIMARY_DLMM_RPS
        pacer = _SHARED_PRIMARY_DLMM_PACER
        role = "dlmm_reconstruction_primary_shared_observation"
    else:
        rps = DLMM_RPS
        pacer = _pacer_for(_DLMM_PACERS, endpoint, DLMM_RPS)
        role = "dlmm_reconstruction_primary"
    rpc = PacedRpc(
        endpoint,
        role=role,
        requests_per_second=rps,
        pacer=pacer,
        **kwargs,
    )
    rpc.primary_fallback = False
    rpc.primary_shared = bool(primary_shared)
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
    discovery_shared = False
    discovery_error = None
    try:
        discovery, discovery_shared = discovery_endpoint(environ=environ)
    except BoundaryError as exc:
        discovery_error = str(exc)

    dlmm = None
    dlmm_shared = False
    dlmm_error = None
    try:
        dlmm, dlmm_shared = dlmm_endpoint(environ=environ)
    except BoundaryError as exc:
        dlmm_error = str(exc)

    discovery_credential = None
    if discovery:
        configured_discovery = _env(DISCOVERY_ENV, environ)
        discovery_credential = (
            DISCOVERY_ENV
            if (
                configured_discovery
                and _endpoint_fingerprint(configured_discovery)
                == _endpoint_fingerprint(discovery)
            )
            else DLMM_ENV
        )

    bulk_primary_shared = bool(discovery_shared or dlmm_shared)
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
            discovery_credential=discovery_credential,
            discovery_primary_candidate_bypassed=bool(
                discovery
                and _env(DISCOVERY_ENV, environ)
                and _is_primary_endpoint(_env(DISCOVERY_ENV, environ), primary)
                and not discovery_shared
                and _endpoint_fingerprint(_env(DISCOVERY_ENV, environ))
                != _endpoint_fingerprint(discovery)
            ),
            discovery_primary_shared=bool(discovery_shared),
            discovery_primary_fallback=False,
            discovery_requests_per_second=(
                SHARED_PRIMARY_DISCOVERY_RPS
                if discovery_shared
                else DISCOVERY_RPS
            ),
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
            primary_shared=bool(dlmm_shared),
            primary_fallback=False,
            requests_per_second=(
                SHARED_PRIMARY_DLMM_RPS if dlmm_shared else DLMM_RPS
            ),
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
        endpoint_isolation_complete=not bulk_primary_shared,
        bulk_primary_shared=bulk_primary_shared,
        bulk_primary_fallback=False,
        signing=False,
        submission=False,
    )
