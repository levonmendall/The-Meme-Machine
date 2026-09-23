"""Lane-specific Robinhood RPC governance modeled on current Solana behavior.

Roles:
- directional/Pons: authenticated primary evidence RPC, 2 RPS, fail closed, no
  automatic alternate-provider evidence;
- Pons broad discovery: official Robinhood public RPC plus the official sequencer
  feed; neither is trade authority. Alchemy is not used for routine discovery.
- Pons discovery gap recovery: the authenticated primary may be used only after
  public observation cannot recover an exact sequencer-discovered range.
- Ramses/DLMM: dedicated bulk/reconstruction RPC, 5 RPS, bounded sessions.
- shadow: optional independent provider for disagreement/diagnostic reads only.

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
DISCOVERY_ENV = "MM_ROBINHOOD_DISCOVERY_RPC_URL"
DLMM_ENV = "MM_ROBINHOOD_DLMM_RPC_URL"
SHADOW_ENV = "MM_ROBINHOOD_SHADOW_RPC_URL"
QUICKNODE_ENV = "MM_ROBINHOOD_QUICKNODE_RPC_URL"  # compatibility-only alias

PUBLIC_DIAGNOSTIC_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
SEQUENCER_FEED_URL = "wss://feed.mainnet.chain.robinhood.com"

DIRECTIONAL_RPS = 2.0
DISCOVERY_RPS = 5.0
PUBLIC_DISCOVERY_RPS = 2.0
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


def discovery_endpoint(primary_fallback_endpoint=None, *, environ=None):
    """Observation-only Pons discovery without routine Alchemy consumption.

    A specifically configured non-Alchemy discovery endpoint may be used. Alchemy
    endpoints, including a DLMM endpoint, are intentionally bypassed for routine
    discovery because the official public RPC plus sequencer feed preserve the broad
    market view without consuming scarce authoritative capacity.
    """
    value = _env(DISCOVERY_ENV, environ)
    if value:
        endpoint = _require_https(
            value,
            "MM_ROBINHOOD_DISCOVERY_RPC_URL_requires_full_https_url",
        )
        if _provider_kind(endpoint) != "alchemy":
            return endpoint, False
    return PUBLIC_DIAGNOSTIC_RPC_URL, False


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
        self.backpressure_events = 0

    def slow_to(self, requests_per_second):
        """Apply run-time provider backpressure without ever increasing rate."""
        rps=float(requests_per_second)
        if not 0.2 <= rps <= 25.0:
            raise BoundaryError("invalid_provider_rps")
        with self._lock:
            if rps >= self.requests_per_second:
                return False
            self.requests_per_second=rps
            self.minimum_interval_seconds=1.0/rps
            now=float(self.clock())
            self.next_at=max(self.next_at,now+self.minimum_interval_seconds)
            self.backpressure_events+=1
            return True

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
            backpressure_events=self.backpressure_events,
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
            pacing=self.pacer.telemetry(),
            automatic_failover=False,
        )
        return data



RECOVERABLE_OBSERVATION_BOUNDARIES = frozenset({
    "provider_transport_failure",
    "provider_http_403",
    "provider_http_429",
    "provider_http_500",
    "provider_http_502",
    "provider_http_503",
    "provider_http_504",
    "provider_rpc_429",
})


class ObservationFallbackRpc(PacedRpc):
    """Public observation first; exact failed reads may recover through Alchemy."""

    def __init__(self, *args, recovery_rpc=None, **kwargs):
        self.recovery_rpc = recovery_rpc
        self.recovery_requests = 0
        self.recovery_failures = 0
        super().__init__(*args, **kwargs)

    @staticmethod
    def _recoverable(exc):
        return str(exc) in RECOVERABLE_OBSERVATION_BOUNDARIES

    def call(self, method, params, *, scope="connectivity"):
        try:
            return super().call(method, params, scope=scope)
        except BoundaryError as exc:
            if self.recovery_rpc is None or not self._recoverable(exc):
                raise
            self.recovery_requests += 1
            try:
                return self.recovery_rpc.call(method, params, scope=scope)
            except BoundaryError:
                self.recovery_failures += 1
                raise

    def batch(self, calls, *, scope="connectivity"):
        try:
            return super().batch(calls, scope=scope)
        except BoundaryError as exc:
            if self.recovery_rpc is None or not self._recoverable(exc):
                raise
            self.recovery_requests += 1
            try:
                return self.recovery_rpc.batch(calls, scope=scope)
            except BoundaryError:
                self.recovery_failures += 1
                raise

    def telemetry(self):
        data = super().telemetry()
        data.update(
            alchemy_gap_recovery_requests=int(self.recovery_requests),
            alchemy_gap_recovery_failures=int(self.recovery_failures),
            alchemy_gap_recovery=(
                None if self.recovery_rpc is None else self.recovery_rpc.telemetry()
            ),
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
    return PacedRpc(
        endpoint,
        role="directional_evidence_primary",
        requests_per_second=DIRECTIONAL_RPS,
        pacer=_DIRECTIONAL_PACER,
        **kwargs,
    )


def configured_discovery_rpc(primary_fallback_endpoint=None, *, environ=None, **kwargs):
    """Observation-only Pons discovery; public by default and never routine Alchemy."""
    endpoint, _ = discovery_endpoint(
        primary_fallback_endpoint, environ=environ
    )
    public = _provider_kind(endpoint) == "robinhood_public"
    rps = PUBLIC_DISCOVERY_RPS if public else DISCOVERY_RPS
    recovery = (
        configured_discovery_recovery_rpc(
            primary_fallback_endpoint, environ=environ,
            limit=kwargs.get("limit",80), per_scope=kwargs.get("per_scope",40),
            retries=kwargs.get("retries",1), transport=kwargs.get("transport"),
        )
        if public else None
    )
    rpc = ObservationFallbackRpc(
        endpoint,
        role=("pons_discovery_public_observation" if public else "pons_discovery_observation"),
        requests_per_second=rps,
        pacer=_pacer_for(_DISCOVERY_PACERS, endpoint, rps),
        recovery_rpc=recovery,
        **kwargs,
    )
    rpc.primary_fallback = False
    rpc.gap_recovery = False
    return rpc


def configured_discovery_recovery_rpc(primary_endpoint_value=None, *, environ=None, **kwargs):
    """Exact-gap recovery on the authenticated primary; never routine discovery."""
    endpoint = primary_endpoint(primary_endpoint_value, environ=environ)
    rpc = PacedRpc(
        endpoint,
        role="pons_discovery_gap_recovery_primary",
        requests_per_second=DIRECTIONAL_RPS,
        pacer=_DIRECTIONAL_PACER,
        **kwargs,
    )
    rpc.primary_fallback = True
    rpc.gap_recovery = True
    return rpc


def configured_dlmm_rpc(primary_fallback_endpoint=None, *, environ=None, **kwargs):
    """Ramses reconstruction RPC: dedicated 5 RPS lane, no automatic rescue."""
    endpoint, primary_fallback = dlmm_endpoint(
        primary_fallback_endpoint, environ=environ
    )
    effective_rps = DIRECTIONAL_RPS if primary_fallback else DLMM_RPS
    pacer = (
        _DIRECTIONAL_PACER
        if primary_fallback
        else _pacer_for(_DLMM_PACERS, endpoint, DLMM_RPS)
    )
    rpc = PacedRpc(
        endpoint,
        role=(
            "dlmm_reconstruction_primary_fallback"
            if primary_fallback
            else "dlmm_reconstruction_primary"
        ),
        requests_per_second=effective_rps,
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
    discovery, discovery_fallback = discovery_endpoint(environ=environ)
    dlmm, fallback = dlmm_endpoint(environ=environ)
    shadow = shadow_endpoint(environ=environ)
    return dict(
        network="robinhood-mainnet",
        chain_id=CHAIN_ID,
        directional=dict(
            discovery="official_robinhood_sequencer_feed_plus_discovery_rpc",
            discovery_provider_kind=_provider_kind(discovery),
            discovery_credential=(DISCOVERY_ENV if _provider_kind(discovery)!="robinhood_public" else None),
            discovery_primary_fallback=False,
            discovery_requests_per_second=(
                PUBLIC_DISCOVERY_RPS if _provider_kind(discovery)=="robinhood_public" else DISCOVERY_RPS
            ),
            gap_recovery_provider_kind=_provider_kind(primary),
            gap_recovery_credential=PRIMARY_ENV,
            gap_recovery_policy="only_after_public_observation_recovery_exhausted",
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
            requests_per_second=(
                DIRECTIONAL_RPS if fallback else DLMM_RPS
            ),
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