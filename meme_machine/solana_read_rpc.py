"""Canonical read-only Solana RPC topology for Meme Machine.

Provider policy:
- Public Solana WebSocket is Pump discovery-only, never decision evidence.
- MM_SOLANA_READ_RPC_URL (Alchemy) is the Pump HTTP evidence primary.
- Authenticated OnFinality is retained only for isolated diagnostics and is not part
  of Pump evidence acquisition after repeated sustained 429 failures.
- Pump HTTP evidence has no automatic rescue provider: failures are explicit/fail-closed.
- One shared 0.5-second primary pacer bounds Alchemy HTTP evidence at 2 RPS.
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
from .solana_provider_config import AlchemyEndpoint


PRIMARY_PROVIDER = "alchemy_solana_mainnet"
PUBLIC_HTTP_PROVIDER = "solana_public_mainnet_fallback"
PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"
PUBLIC_RPC_HOST = "api.mainnet-beta.solana.com"

ONFINALITY_PROVIDER = "onfinality_solana_mainnet_diagnostic_only"
ONFINALITY_RPC_URL = "https://solana.api.onfinality.io/public"
ONFINALITY_RPC_HOST = "solana.api.onfinality.io"
AUTHENTICATED_PRIMARY_ENV_NAME = "MM_ONFINALITY_SOLANA_RPC_URL"  # compatibility alias; no longer Pump primary
AUTHENTICATED_WS_ENV_NAME = "MM_ONFINALITY_SOLANA_WS_URL"
PUBLIC_OVERRIDE_ENV_NAME = "MM_SOLANA_PUBLIC_RPC_URL"

DISCOVERY_WS_PROVIDER = "solana_public_mainnet"
DISCOVERY_WS_URL = "wss://api.mainnet-beta.solana.com"

ALCHEMY_ENV_NAME = "MM_SOLANA_READ_RPC_URL"
ALCHEMY_SOLANA_MAINNET_HOST = "solana-mainnet.g.alchemy.com"
PRIMARY_RPC_URL = PUBLIC_RPC_URL  # compatibility: no-secret local fallback only
PRIMARY_RPC_HOST = ALCHEMY_SOLANA_MAINNET_HOST
SECONDARY_PROVIDER = "none"

TOPOLOGY_LABEL = "alchemy_primary_no_rescue_public_ws_discovery"
SOLANA_MIN_REQUEST_INTERVAL_SECONDS = 0.5
PROVIDER_429_MIN_BACKOFF_SECONDS = 2.0


def _source(environ=None):
    return os.environ if environ is None else environ


def _validate_onfinality_url(value, *, websocket=False, public_only=False):
    parsed = urlparse(value)
    expected_scheme = "wss" if websocket else "https"
    if (
        parsed.scheme != expected_scheme
        or parsed.hostname != ONFINALITY_RPC_HOST
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise Unavailable("onfinality_rpc_endpoint_required")
    if public_only and (
        parsed.query
        or parsed.path.rstrip("/") != ("/public-ws" if websocket else "/public")
    ):
        raise Unavailable("onfinality_public_rpc_endpoint_required")
    if not parsed.path or parsed.path == "/":
        raise Unavailable("onfinality_rpc_endpoint_required")
    return value


def _validate_alchemy_url(value):
    try:return AlchemyEndpoint.parse(value).http_url
    except ValueError:raise Unavailable("alchemy_rpc_endpoint_required") from None


def onfinality_rpc_url(environ=None, *, required=False):
    source=_source(environ)
    authenticated=str(source.get(AUTHENTICATED_PRIMARY_ENV_NAME,"") or "").strip()
    if authenticated:
        return _validate_onfinality_url(authenticated)
    if required:
        raise Unavailable("onfinality_authenticated_rpc_missing")
    return ONFINALITY_RPC_URL


def primary_rpc_url(environ=None, *, required=False):
    """Pump HTTP evidence primary: Alchemy when configured, public Solana only as local fallback."""
    source=_source(environ)
    value=str(source.get(ALCHEMY_ENV_NAME,"") or "").strip()
    if value:
        return _validate_alchemy_url(value)
    if required or _source(environ).get("MM_SOLANA_EVIDENCE_PLANE_DB"):
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


def primary_ws_url(environ=None):
    """Diagnostic-only OnFinality WebSocket helper; never Pump discovery authority."""
    source = _source(environ)
    authenticated = str(source.get(AUTHENTICATED_WS_ENV_NAME, "") or "").strip()
    if authenticated:
        return _validate_onfinality_url(authenticated, websocket=True)
    return "wss://solana.api.onfinality.io/public-ws"


def discovery_ws_url(environ=None):
    """Canonical Pump discovery stream, intentionally separate from HTTP evidence."""
    return DISCOVERY_WS_URL


def secondary_rpc_url(environ=None, *, required=False):
    if required:
        raise Unavailable("pump_http_secondary_disabled")
    return None


class SolanaReadPacer:
    """One conservative request clock shared across bounded RPC objects.

    Alchemy is governed at two physical requests per second. The pacer is
    shared across bounded RPC objects so provider rotations and concentration reads do
    not multiply the aggregate primary cadence. No rescue provider is configured.
    """

    def __init__(self, minimum_interval=SOLANA_MIN_REQUEST_INTERVAL_SECONDS):
        if minimum_interval < 0.2 or minimum_interval > 5.0:
            raise ValueError("solana_read_pace_bound")
        self.minimum_interval = float(minimum_interval)
        self.next_request_at = -float("inf")
        self.paced_requests = 0
        self.sleep_seconds = 0.0
        # Shared across bounded RPC rotations so 429 pressure adaptations survive
        # session replacement instead of immediately returning to a hot batch size.
        self.gettransaction_batch_size = 16
        self.gettransaction_429_streak = 0
        self.gettransaction_success_streak = 0
        self.gettransaction_429_events = 0
        self.gettransaction_batch_reductions = 0
        self.gettransaction_batch_recoveries = 0
        self.gettransaction_cooldown_seconds = 0.0

    def pace(self, rpc, requested_interval=0.2):
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
            gettransaction_batch_size=int(self.gettransaction_batch_size),
            gettransaction_429_streak=int(self.gettransaction_429_streak),
            gettransaction_429_events=int(self.gettransaction_429_events),
            gettransaction_batch_reductions=int(self.gettransaction_batch_reductions),
            gettransaction_batch_recoveries=int(self.gettransaction_batch_recoveries),
            gettransaction_cooldown_seconds=float(self.gettransaction_cooldown_seconds),
        )


class _ReadOnlyFailoverMixin:
    """HTTP transport mixin with single-provider semantics; legacy class name retained."""

    def _init_failover(self, secondary_url, pacer, primary_provider=PRIMARY_PROVIDER, secondary_provider=SECONDARY_PROVIDER):
        if secondary_url is not None:raise Unavailable("solana_secondary_provider_disabled")
        self.secondary_url = None
        self.primary_provider_label = primary_provider
        self.secondary_provider_label = secondary_provider
        self.read_pacer = pacer or SolanaReadPacer()
        # Compatibility for existing DLMM research code that still reads this name.
        self.alchemy_pacer = self.read_pacer
        self.provider_http_requests = Counter()
        self.provider_successes = Counter()
        self.provider_failures = Counter()
        self.provider_failure_reasons = Counter()
        # Safe provider diagnostics: method names/status codes only. Never retain
        # URLs, response bodies, credentials, or provider error messages.
        self.provider_method_failures = Counter()
        self.provider_http_status_errors = Counter()
        self.provider_jsonrpc_error_codes = Counter()
        self.provider_error_fingerprints = Counter()
        self.provider_error_sequence = 0
        self.last_provider_error = None
        self.failover_count = 0
        self.failover_reasons = Counter()

    def _pace(self, interval=0.5):
        if self.transport == self._http:
            # Base RPC passes legacy logical pacing hints (0.5s and batch-derived
            # intervals). Provider governance is physical-request based: respect the
            # shared 2 req/s primary cadence instead of the legacy 1-2 req/s ceiling.
            self.read_pacer.pace(self, self.read_pacer.minimum_interval)

    @staticmethod
    def _retry_delay(exc):
        delay = RPC._retry_delay(exc)
        if isinstance(exc, urllib.error.HTTPError) and int(exc.code) == 429:
            return max(float(delay), PROVIDER_429_MIN_BACKOFF_SECONDS)
        return delay

    @staticmethod
    def _request_url(url, request):
        endpoint = AlchemyEndpoint.parse(url) if 'alchemy.com' in url else None
        data = json.dumps(request).encode()
        req = urllib.request.Request(url, data, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:raise Unavailable("response_size_limit")
            value = json.loads(raw)
            if endpoint:endpoint.public(value)
            return value
        except urllib.error.HTTPError as exc:
            raise urllib.error.HTTPError('', int(exc.code), 'provider_http_error', {}, None) from None
        except Exception:
            raise Unavailable('provider_response_unavailable') from None

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
        # Bounded logical retries stay on the same provider. Production has no
        # secondary transport, even when the legacy class name is imported.
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

    @staticmethod
    def _request_methods(request):
        rows = request if isinstance(request, list) else [request]
        methods = []
        for row in rows:
            method = row.get("method") if isinstance(row, dict) else None
            methods.append(method if isinstance(method, str) and method else "unknown")
        return methods or ["unknown"]

    def _record_provider_error(
        self,
        label,
        method,
        *,
        kind,
        http_status=None,
        jsonrpc_error_code=None,
    ):
        method = method if isinstance(method, str) and method else "unknown"
        event = dict(provider=label, method=method, kind=kind)
        fingerprint_suffix = f"kind:{kind}"
        if http_status is not None:
            status = int(http_status)
            event["http_status"] = status
            self.provider_http_status_errors[f"{label}:{method}:{status}"] += 1
            fingerprint_suffix = f"http:{status}"
        if jsonrpc_error_code is not None:
            code = str(jsonrpc_error_code)
            event["jsonrpc_error_code"] = jsonrpc_error_code
            self.provider_jsonrpc_error_codes[f"{label}:{method}:{code}"] += 1
            fingerprint_suffix = f"jsonrpc:{code}"
        self.provider_method_failures[f"{label}:{method}"] += 1
        fingerprint = f"{label}|{method}|{fingerprint_suffix}"
        self.provider_error_fingerprints[fingerprint] += 1
        self.provider_error_sequence += 1
        event["fingerprint"] = fingerprint
        event["sequence"] = self.provider_error_sequence
        self.last_provider_error = event

    def _record_jsonrpc_errors(self, label, request, response):
        requests = request if isinstance(request, list) else [request]
        if isinstance(response, list):
            by_id = {
                item.get("id"): item
                for item in response
                if isinstance(item, dict)
            }
            pairs = [(row, by_id.get(row.get("id"))) for row in requests if isinstance(row, dict)]
        else:
            pairs = [(row, response) for row in requests if isinstance(row, dict)]
        for row, item in pairs:
            if not isinstance(item, dict):
                continue
            error = item.get("error")
            if not isinstance(error, dict):
                continue
            self._record_provider_error(
                label,
                row.get("method"),
                kind="jsonrpc_error",
                jsonrpc_error_code=error.get("code", "unknown"),
            )

    def _provider_attempt(self, label, url, request):
        self.provider_http_requests[label] += 1
        error_sequence_before = self.provider_error_sequence
        try:
            response = self._request_url(url, request)
            self._record_jsonrpc_errors(label, request, response)
            issue = self._response_issue(request, response)
            if issue is not None:
                raise Unavailable(issue)
            self.provider_successes[label] += 1
            return response
        except Exception as exc:
            self.provider_failures[label] += 1
            reason = self._exception_reason(exc)
            self.provider_failure_reasons[f"{label}:{reason}"] += 1
            # JSON-RPC errors are recorded from the structured response above. For
            # transport/HTTP/shape failures, attach the physical failure to each
            # distinct method in this request without retaining sensitive content.
            if self.provider_error_sequence == error_sequence_before:
                methods = list(dict.fromkeys(self._request_methods(request)))
                status = int(exc.code) if isinstance(exc, urllib.error.HTTPError) else None
                for method in methods:
                    self._record_provider_error(
                        label,
                        method,
                        kind=reason,
                        http_status=status,
                    )
            raise

    def _http(self, request):
        if os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB'):
            _validate_alchemy_url(self.url)
            calls = request if isinstance(request,list) else [request]
            if any(x.get('method') in ('getSignaturesForAddress','getTransaction','getTransactionsForAddress','getBlock') for x in calls):
                raise Unavailable('foreground_historical_rpc_forbidden')
        return self._provider_attempt(self.primary_provider_label, self.url, request)

    def provider_telemetry(self):
        return dict(
            topology=TOPOLOGY_LABEL,
            primary_provider=self.primary_provider_label,
            secondary_provider=self.secondary_provider_label,
            secondary_configured=bool(self.secondary_url),
            logical_calls=int(self.calls),
            physical_http_requests=int(self.http_requests),
            provider_http_requests=dict(sorted(self.provider_http_requests.items())),
            provider_successes=dict(sorted(self.provider_successes.items())),
            provider_failures=dict(sorted(self.provider_failures.items())),
            provider_failure_reasons=dict(sorted(self.provider_failure_reasons.items())),
            provider_method_failures=dict(sorted(self.provider_method_failures.items())),
            provider_http_status_errors=dict(sorted(self.provider_http_status_errors.items())),
            provider_jsonrpc_error_codes=dict(sorted(self.provider_jsonrpc_error_codes.items())),
            provider_error_fingerprints=dict(sorted(self.provider_error_fingerprints.items())),
            provider_error_sequence=int(self.provider_error_sequence),
            last_provider_error=(dict(self.last_provider_error) if self.last_provider_error else None),
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
        primary_provider=PRIMARY_PROVIDER,
        secondary_provider=SECONDARY_PROVIDER,
        limit=120,
        pacer=None,
        **kwargs,
    ):
        if os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB'):
            primary_url = _validate_alchemy_url(primary_url)
            if primary_provider != PRIMARY_PROVIDER:raise Unavailable('authoritative_provider_label_required')
        self._init_failover(secondary_url, pacer, primary_provider, secondary_provider)
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
        primary_provider=PRIMARY_PROVIDER,
        secondary_provider=SECONDARY_PROVIDER,
        limit=240,
        pacer=None,
        **kwargs,
    ):
        if os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB'):
            primary_url = _validate_alchemy_url(primary_url)
            if primary_provider != PRIMARY_PROVIDER:raise Unavailable('authoritative_provider_label_required')
        self._init_failover(secondary_url, pacer, primary_provider, secondary_provider)
        super().__init__(primary_url, limit=limit, **kwargs)


def new_rpc(limit=120, pacer=None, environ=None, **kwargs):
    return ReadOnlyFailoverRPC(
        primary_rpc_url(environ),
        secondary_url=None,
        primary_provider=primary_provider(environ),
        secondary_provider=SECONDARY_PROVIDER,
        limit=limit,
        pacer=pacer,
        **kwargs,
    )


def new_pool_scan_rpc(limit=240, pacer=None, environ=None, **kwargs):
    return ReadOnlyFailoverPoolScanRPC(
        primary_rpc_url(environ),
        secondary_url=None,
        primary_provider=primary_provider(environ),
        secondary_provider=SECONDARY_PROVIDER,
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
        discovery_ws_provider=DISCOVERY_WS_PROVIDER,
        discovery_ws_url=DISCOVERY_WS_URL,
        onfinality_http_role="diagnostic_only_not_pump_evidence",
        signing=False,
        submission=False,
        minimum_request_interval_seconds=SOLANA_MIN_REQUEST_INTERVAL_SECONDS,
        minimum_429_backoff_seconds=PROVIDER_429_MIN_BACKOFF_SECONDS,
    )


def validate_topology(environ=None, *, require_secondary=False):
    primary_rpc_url(environ,required=True)
    if require_secondary:
        raise Unavailable("pump_http_secondary_disabled")
    return metadata(environ)
