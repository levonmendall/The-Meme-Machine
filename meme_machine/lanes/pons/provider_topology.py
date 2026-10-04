"""Robinhood provider roles. One canonical Alchemy endpoint serves both lanes.

Public/sequencer paths only observe. Shadow endpoints are explicit diagnostics.
Canonical HTTP uses the mandatory shared endpoint governor and exact-state cache.
Lane pacers can slow traffic further; they cannot multiply the aggregate ceiling.
No signing, submission, or automatic alternate canonical provider exists.
"""
from __future__ import annotations

from collections import Counter
import os
import threading
import time
from urllib.parse import urlsplit

from . import BoundaryError, CHAIN_ID
from .provider import Rpc
from meme_machine.runtime.robinhood import provider_authority as authority


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
    if host == "alchemy.com" or host.endswith(".alchemy.com"):
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
    try:return authority.endpoint(primary_endpoint, environ=environ)
    except ValueError as exc:raise BoundaryError(str(exc)) from None


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
    # Legacy DLMM configuration is an equivalent alias, never another authority.
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
        self.maximum_requests_per_second = rps
        self.requests_per_second = rps
        self.minimum_interval_seconds = 1.0 / rps
        self.clock = clock
        self.sleep = sleeper
        self._lock = threading.Lock()
        self.next_at = -float("inf")
        self.paced_requests = 0
        self.sleep_seconds = 0.0
        self.backpressure_events = 0
        self.recovery_events = 0

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

    def recover_to(self, requests_per_second):
        """Cautiously recover toward the constructor ceiling, never above it."""
        rps=min(float(requests_per_second),self.maximum_requests_per_second)
        if not 0.2 <= rps <= 25.0:
            raise BoundaryError("invalid_provider_rps")
        with self._lock:
            if rps <= self.requests_per_second:
                return False
            self.requests_per_second=rps
            self.minimum_interval_seconds=1.0/rps
            now=float(self.clock())
            self.next_at=max(self.next_at,now+self.minimum_interval_seconds)
            self.recovery_events+=1
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
            recovery_events=self.recovery_events,
            ceiling_requests_per_second=self.maximum_requests_per_second,
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
        self.canonical_authority = authority.is_canonical_role(self.role)
        self.chain_verified = False
        if self.canonical_authority:
            endpoint = primary_endpoint(endpoint)
        self.provider_fingerprint = authority.fingerprint(endpoint) if self.canonical_authority else None
        from .provider_admission import configured
        self.shared_admission = configured(endpoint, mandatory=self.canonical_authority)
        self.admission_scope = threading.local()
        self.provider_kind = _provider_kind(endpoint)
        from .immutable_rpc import configured as evidence_store, Reuse
        store=evidence_store(authority.paths()['cache']) if self.canonical_authority else None
        self.evidence_reuse=Reuse(endpoint,store,os.environ.get('MM_RUNTIME_LANE','unknown')) if store else None
        self.hash_state_supported=set()
        capability_path=os.environ.get('MM_RPC_CAPABILITIES')
        if capability_path and self.evidence_reuse:
            import json
            from pathlib import Path
            try:
                methods=json.loads(Path(capability_path).read_text())['endpoints'][self.evidence_reuse.domain]['methods']
                self.hash_state_supported={m for m in ('eth_call','eth_getCode') if methods.get('eip1898_'+m,{}).get('supported') is True}
            except (OSError,ValueError,KeyError):pass
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
        paced=self.pacer.pace()
        timing=getattr(self,"evidence_timing",None)
        if timing is not None:timing["local_pacer_wait_seconds"]=timing.get("local_pacer_wait_seconds",0)+paced
        if self.shared_admission is not None:
            parent=super()
            return self.shared_admission.invoke(
                lambda: parent._http(method,params),[method],
                getattr(self.admission_scope,"value","connectivity"),getattr(self,"retry_attempt",0),
                deadline=getattr(self,"evidence_deadline",None),timing=timing)
        return super()._http(method, params)

    def _http_batch(self, calls):
        paced=self.pacer.pace()
        timing=getattr(self,"evidence_timing",None)
        if timing is not None:timing["local_pacer_wait_seconds"]=timing.get("local_pacer_wait_seconds",0)+paced
        if self.shared_admission is not None:
            parent=super()
            return self.shared_admission.invoke(
                lambda: parent._http_batch(calls),[x[0] for x in calls],
                getattr(self.admission_scope,"value","connectivity"),getattr(self,"retry_attempt",0),
                deadline=getattr(self,"evidence_deadline",None),timing=timing,batch=True)
        return super()._http_batch(calls)

    def _record_demand(self, methods):
        if self.canonical_authority:
            from meme_machine.runtime.robinhood.provider_usage import demand
            from .provider import READ_METHODS
            demand(self.shared_admission.path,self.provider_fingerprint,[m for m in methods if m in READ_METHODS])

    def _authority_guard(self, method):
        if not self.canonical_authority:return
        try:
            if authority.fingerprint(authority.endpoint(self._endpoint)) != self.provider_fingerprint:
                raise ValueError('provider_identity_changed')
        except ValueError as exc:raise BoundaryError(str(exc)) from None
        if method != 'eth_chainId' and not self.chain_verified:
            self.verify_chain()

    def verify_chain(self):
        self.chain_verified = False
        result = super().verify_chain()
        self.chain_verified = True
        return result

    def _method_allowed_for_provider(self, method):
        if method in ALCHEMY_ONLY_METHODS and self.provider_kind != "alchemy":
            raise BoundaryError("provider_specific_method_wrong_provider")

    def _reuse_lookup(self,method,params):
        reuse=self.evidence_reuse
        if reuse is None:return False,None,None
        pins=getattr(self,'evidence_pins',{})
        # A number-to-hash hint alone cannot bind a response across a reorg.
        # State misses actually use EIP-1898 on the wire, after capability proof.
        if method in ('eth_call','eth_getCode','eth_getBalance','eth_getStorageAt'):
            index=2 if method=='eth_getStorageAt' else 1
            if len(params)>index and not isinstance(params[index],dict) and method not in self.hash_state_supported:
                pins={}
        result=reuse.lookup(method,params,pins,getattr(self,'evidence_receipts',{}),getattr(self,'evidence_cost_epoch',None))
        if method=='eth_gasPrice' and result[0] and getattr(self,'evidence_timing',None) is not None:
            self.evidence_timing['gas_quote_origin']=dict(reuse.gas_quote_origin)
        return result

    @staticmethod
    def _wire_params(method,params,key):
        if key and method in ('eth_call','eth_getCode','eth_getBalance','eth_getStorageAt'):
            import json
            return json.loads(key)[1]
        if key and method=='eth_getLogs':
            import json
            return json.loads(key)[1]
        return params

    def call(self, method, params, *, scope="connectivity"):
        scope=authority.safe_label(scope)
        self._record_demand([method])
        self._authority_guard(method)
        self._method_allowed_for_provider(method)
        self.admission_scope.value=scope
        hit,value,key=self._reuse_lookup(method,params)
        if hit:return value
        if not self.evidence_reuse:return super().call(method,params,scope=scope)
        reuse=self.evidence_reuse
        with reuse.store.lease(reuse.domain,[key],getattr(self,'evidence_deadline',None)):
            cached=reuse.store.get(reuse.domain,key) if key else None
            if cached:
                reuse.store.event(reuse.lane,reuse.domain,method,'coalesced',key,cached[1])
                return cached[0]
            value=super().call(method,self._wire_params(method,params,key),scope=scope)
            reuse.remember(method,params,value,key)
            return value

    def batch(self, calls, *, scope="connectivity"):
        scope=authority.safe_label(scope)
        self._authority_guard("batch")
        if isinstance(calls,list):self._record_demand([r[0] for r in calls if isinstance(r,(list,tuple)) and r])
        if not self.evidence_reuse:
            for row in calls or []:
                if isinstance(row,(list,tuple)) and row:self._method_allowed_for_provider(row[0])
            self.admission_scope.value=scope
            return super().batch(calls,scope=scope)
        from .provider import READ_METHODS
        if not isinstance(calls,list) or not calls or len(calls)>50:raise BoundaryError('provider_batch_capacity')
        if any(not isinstance(r,(list,tuple)) or len(r)!=2 for r in calls):raise BoundaryError('provider_batch_shape')
        if any(r[0] not in READ_METHODS for r in calls):raise BoundaryError('rpc_method_not_read_only')
        out=[None]*len(calls);missing=[];followers={};keys={}
        for index,(method,params) in enumerate(calls):
            self._method_allowed_for_provider(method)
            hit,value,key=self._reuse_lookup(method,params)
            if hit:out[index]=value;continue
            if key and key in keys:
                followers[index]=keys[key];continue
            if key:keys[key]=index
            missing.append((index,method,params,key))
        if missing:
            deadline=getattr(self,'evidence_deadline',None)
            if deadline is not None and time.monotonic()>=deadline:raise BoundaryError('evidence_deadline_before_transport')
            self.admission_scope.value=scope
            reuse=self.evidence_reuse
            with reuse.store.lease(reuse.domain,[k for _,_,_,k in missing],deadline):
                pending=[]
                for item in missing:
                    index,method,params,key=item
                    cached=reuse.store.get(reuse.domain,key) if key else None
                    if cached:
                        out[index]=cached[0]
                        reuse.store.event(reuse.lane,reuse.domain,method,'coalesced',key,cached[1])
                    else:pending.append(item)
                if pending:
                    if deadline is not None and time.monotonic()>=deadline:raise BoundaryError('evidence_deadline_before_transport')
                    values=super().batch([(m,self._wire_params(m,p,k)) for _,m,p,k in pending],scope=scope)
                    for (index,method,params,key),value in zip(pending,values):
                        reuse.remember(method,params,value,key);out[index]=value
        for index,source in followers.items():out[index]=out[source]
        return out

    def telemetry(self):
        from meme_machine.runtime.robinhood.provider_usage import cache_snapshot
        data = super().telemetry()
        if self.evidence_reuse:
            data['shared_evidence']=cache_snapshot(authority.paths()['cache'],self.evidence_reuse.domain)
        data.update(
            role=self.role,
            provider_kind=self.provider_kind,
            pacing=self.pacer.telemetry(),
            automatic_failover=False,
            canonical_authority=self.canonical_authority,
            chain_verified=self.chain_verified,
            shared_provider=self.shared_admission.telemetry() if self.shared_admission else None,
            immutable_reuse=self.evidence_reuse.telemetry() if self.evidence_reuse else None,
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
        self.public_log_429s = 0
        self.public_log_retry_successes = 0
        self.public_log_retry_failures = 0
        self.public_log_retry_skipped_deadline = 0
        self.public_log_cooldown_seconds = 0.0
        self.public_log_success_streak = 0
        self.alchemy_exact_log_recoveries = 0
        self.unrecovered_log_ranges = 0
        super().__init__(*args, **kwargs)

    @staticmethod
    def _recoverable(exc):
        return str(exc) in RECOVERABLE_OBSERVATION_BOUNDARIES

    def _public_log_429(self, method, exc):
        return (
            self.provider_kind == "robinhood_public"
            and method == "eth_getLogs"
            and str(exc) in ("provider_http_429","provider_rpc_429")
        )

    def _public_log_success(self):
        if self.provider_kind != "robinhood_public":
            return
        self.public_log_success_streak += 1
        if self.public_log_success_streak < 20:
            return
        self.public_log_success_streak = 0
        current=float(self.pacer.requests_per_second)
        self.pacer.recover_to(min(PUBLIC_DISCOVERY_RPS,current+0.1))

    def _public_log_cooldown(self):
        self.public_log_success_streak = 0
        current=float(self.pacer.requests_per_second)
        self.pacer.slow_to(max(1.0,current*0.75))
        delay=getattr(self,"last_retry_after_seconds",None)
        if delay is None or not 0.0 <= float(delay) <= 1.0:
            delay=0.6
        delay=float(delay)
        deadline=getattr(self,"evidence_deadline",None)
        if deadline is not None:
            delay=min(delay,max(0.0,float(deadline)-time.monotonic()-0.05))
        if delay <= 0:
            self.public_log_retry_skipped_deadline += 1
            return False
        self.pacer.sleep(delay)
        self.public_log_cooldown_seconds += delay
        return True

    def call(self, method, params, *, scope="connectivity"):
        try:
            result=super().call(method, params, scope=scope)
            if self.provider_kind=="robinhood_public" and method=="eth_getLogs":
                self._public_log_success()
            return result
        except BoundaryError as exc:
            if self._public_log_429(method,exc):
                self.public_log_429s += 1
                if self._public_log_cooldown():
                    try:
                        result=super().call(method,params,scope=scope)
                        self.public_log_retry_successes += 1
                        self._public_log_success()
                        return result
                    except BoundaryError as retry_exc:
                        self.public_log_retry_failures += 1
                        exc=retry_exc
            if self.recovery_rpc is None or not self._recoverable(exc):
                raise
            self.recovery_requests += 1
            exact_log=(
                self.provider_kind=="robinhood_public"
                and method=="eth_getLogs"
            )
            if exact_log:
                self.alchemy_exact_log_recoveries += 1
            try:
                return self.recovery_rpc.call(method, params, scope=scope)
            except BoundaryError:
                self.recovery_failures += 1
                if exact_log:
                    self.unrecovered_log_ranges += 1
                raise

    def batch(self, calls, *, scope="connectivity"):
        scope=authority.safe_label(scope)
        self._authority_guard("batch")
        if isinstance(calls,list):self._record_demand([r[0] for r in calls if isinstance(r,(list,tuple)) and r])
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
        from meme_machine.runtime.robinhood.provider_usage import cache_snapshot
        data = super().telemetry()
        if self.evidence_reuse:
            data['shared_evidence']=cache_snapshot(authority.paths()['cache'],self.evidence_reuse.domain)
        data.update(
            alchemy_gap_recovery_requests=int(self.recovery_requests),
            alchemy_gap_recovery_failures=int(self.recovery_failures),
            alchemy_gap_recovery=(
                None if self.recovery_rpc is None else self.recovery_rpc.telemetry()
            ),
            public_eth_getLogs_429_control=dict(
                public_429s=int(self.public_log_429s),
                same_endpoint_retry_successes=int(self.public_log_retry_successes),
                same_endpoint_retry_failures=int(self.public_log_retry_failures),
                retry_skipped_deadline=int(self.public_log_retry_skipped_deadline),
                cooldown_seconds=float(self.public_log_cooldown_seconds),
                effective_requests_per_second=float(self.pacer.requests_per_second),
                success_streak=int(self.public_log_success_streak),
                alchemy_exact_range_recoveries=int(self.alchemy_exact_log_recoveries),
                unrecovered_ranges=int(self.unrecovered_log_ranges),
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
    """Canonical Ramses HTTP, sharing the endpoint ceiling with Pons."""
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
    rpc.primary_fallback = False
    rpc.credential_role = PRIMARY_ENV
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
            primary_fallback=False,
            primary_shared=True,
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
        canonical_credential=PRIMARY_ENV,
        aggregate_requests_per_second=2.0,
        authenticated_streaming=False,
        signing=False,
        submission=False,
    )