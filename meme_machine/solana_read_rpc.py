"""Canonical read-only Solana RPC topology for Meme Machine.

Provider policy:
- Public Solana WebSocket is authoritative Pump discovery.
- MM_SOLANA_READ_RPC_URL (Alchemy) is the only authenticated Solana HTTP evidence endpoint.
- Pump HTTP evidence has no automatic rescue provider: failures are explicit/fail-closed.
- Public HTTP exists only as an uncredentialed local-development fallback when Alchemy
  is not required; production certification requires the Alchemy endpoint explicitly.
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


PRIMARY_PROVIDER = "alchemy_solana_mainnet"
PUBLIC_HTTP_PROVIDER = "solana_public_mainnet_fallback"
PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"
PUBLIC_RPC_HOST = "api.mainnet-beta.solana.com"

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
    """Pump HTTP evidence primary: Alchemy when configured, public Solana only as local fallback."""
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



def discovery_ws_url(environ=None):
    """Canonical Pump discovery stream, intentionally separate from HTTP evidence."""
    return DISCOVERY_WS_URL


def secondary_rpc_url(environ=None, *, required=False):
    if required:
        raise Unavailable("pump_http_secondary_disabled")
    return None


class SolanaReadPacer:
    """One conservative request clock shared across bounded RPC objects.

    Alchemy is governed by one shared physical-request clock. The pacer is shared
    across bounded RPC objects so provider rotations and concentration reads do not
    multiply the aggregate HTTP cadence.
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
        # Method-aware pressure complements the transaction-body controller.
        # Heavy reads can hit provider throughput limits even below the physical
        # request-count ceiling, so a 429 must cool the exact method across every
        # bounded RPC object sharing this pacer.
        self.method_rate_events = Counter()
        self.method_rate_streaks = Counter()
        self.method_success_streaks = Counter()
        self.method_cooldown_until = {}
        self.method_cooldown_seconds = Counter()

    @staticmethod
    def _method_backoff(method, streak):
        streak=max(1,int(streak))
        # Live certification proved that retrying the identical compact program
        # scan after the old eight-second global cooldown still returned 429.
        # Keep this method conservative; lighter reads use the ordinary bounded
        # adaptive cooldown.
        if str(method)=="getProgramAccounts":
            return min(60.0,30.0*(2**min(streak-1,1)))
        return min(30.0,8.0*(2**min(streak-1,2)))

    def note_method_rate_limit(self, rpc, methods):
        now=float(rpc.clock())
        methods=tuple(dict.fromkeys(str(x) for x in methods if x))
        for method in methods:
            self.method_rate_events[method]+=1
            self.method_rate_streaks[method]+=1
            self.method_success_streaks[method]=0
            delay=self._method_backoff(method,self.method_rate_streaks[method])
            self.method_cooldown_until[method]=max(
                float(self.method_cooldown_until.get(method,-float("inf"))),
                now+delay,
            )
            self.method_cooldown_seconds[method]+=delay
        # Preserve the existing endpoint-wide recovery floor as well.
        self.next_request_at=max(float(self.next_request_at),now+8.0)

    def note_method_success(self, methods):
        for method in dict.fromkeys(str(x) for x in methods if x):
            if self.method_rate_streaks.get(method,0)<=0:
                continue
            self.method_success_streaks[method]+=1
            if self.method_success_streaks[method]>=4:
                self.method_rate_streaks[method]=max(
                    0,int(self.method_rate_streaks[method])-1)
                self.method_success_streaks[method]=0

    def method_cooldown_remaining(self, rpc, method):
        if not method:
            return 0.0
        return max(0.0,float(self.method_cooldown_until.get(
            str(method),-float("inf")))-float(rpc.clock()))

    def pace(self, rpc, requested_interval=0.2, method=None):
        interval = max(float(requested_interval), self.minimum_interval)
        now = float(rpc.clock())
        ready=max(
            float(self.next_request_at),
            float(self.method_cooldown_until.get(str(method),-float("inf")))
            if method else -float("inf"),
        )
        wait = max(0.0, ready - now)
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
            method_rate_events=dict(sorted(self.method_rate_events.items())),
            method_rate_streaks=dict(sorted(
                (k,int(v)) for k,v in self.method_rate_streaks.items())),
            method_cooldown_seconds=dict(sorted(
                (k,float(v)) for k,v in self.method_cooldown_seconds.items())),
        )


class _ReadOnlyFailoverMixin:
    """Single-provider Alchemy HTTP transport; legacy class name is import-compatible."""

    def _init_failover(self, secondary_url, pacer, primary_provider=PRIMARY_PROVIDER, secondary_provider=SECONDARY_PROVIDER):
        self.secondary_url = secondary_url
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
            method=getattr(self,"_active_rpc_method",None)
            # Compact program scans have a proven safe fallback.  During a
            # method-specific cooldown, fail this path before transport so the
            # concentration reader can use the unchanged largest-account path
            # instead of retrying the same expensive request into another 429.
            if (method=="getProgramAccounts"
                    and self.read_pacer.method_cooldown_remaining(self,method)>0):
                raise Unavailable("provider_method_cooldown")
            self.read_pacer.pace(
                self,self.read_pacer.minimum_interval,method=method)

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
        methods=self._request_methods(request)
        try:
            response = self._request_url(url, request)
            self._record_jsonrpc_errors(label, request, response)
            issue = self._response_issue(request, response)
            if issue is not None:
                raise Unavailable(issue)
            self.provider_successes[label] += 1
            if self.provider_error_sequence==error_sequence_before:
                self.read_pacer.note_method_success(methods)
            return response
        except Exception as exc:
            self.provider_failures[label] += 1
            reason = self._exception_reason(exc)
            if isinstance(exc, urllib.error.HTTPError) and int(exc.code)==429:
                self.read_pacer.note_method_rate_limit(self,methods)
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

    def call(self, method, params=None, priority=False):
        previous=getattr(self,"_active_rpc_method",None)
        self._active_rpc_method=str(method)
        try:
            return super().call(method,params,priority)
        finally:
            if previous is None:
                try:del self._active_rpc_method
                except AttributeError:pass
            else:self._active_rpc_method=previous

    def call_many(self, method, params_list, priority=False, batch_size=8):
        previous=getattr(self,"_active_rpc_method",None)
        self._active_rpc_method=str(method)
        try:
            return super().call_many(
                method,params_list,priority,batch_size=batch_size)
        finally:
            if previous is None:
                try:del self._active_rpc_method
                except AttributeError:pass
            else:self._active_rpc_method=previous

    def _http(self, request):
        try:
            return self._provider_attempt(self.primary_provider_label, self.url, request)
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
                self.secondary_provider_label,
                self.secondary_url,
                request,
            )

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
