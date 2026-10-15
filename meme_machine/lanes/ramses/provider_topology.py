"""Robinhood provider roles. One canonical Alchemy endpoint serves both lanes.

Public/sequencer paths only observe. Shadow endpoints are explicit diagnostics.
Canonical HTTP uses the mandatory shared endpoint governor and exact-state cache.
Lane pacers can slow traffic further; they cannot multiply the aggregate ceiling.
No signing, submission, or automatic alternate canonical provider exists.
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
    value = _env(DISCOVERY_ENV, environ)
    if value:
        endpoint = _require_https(value, 'MM_ROBINHOOD_DISCOVERY_RPC_URL_requires_full_https_url')
        if _provider_kind(endpoint) != 'alchemy':return endpoint, False
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
            except (OSError,ValueError,KeyError,TypeError,AttributeError):pass
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
            endpoint_fingerprint=_endpoint_fingerprint(self._endpoint),
            credential_role=getattr(self, "credential_role", None),
            primary_shared=bool(getattr(self, "primary_shared", False)),
            pacing=self.pacer.telemetry(),
            automatic_failover=False,
            canonical_authority=self.canonical_authority,
            chain_verified=self.chain_verified,
            shared_provider=self.shared_admission.telemetry() if self.shared_admission else None,
            immutable_reuse=self.evidence_reuse.telemetry() if self.evidence_reuse else None,
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
        rps = 2.0 if _provider_kind(endpoint)=="robinhood_public" else DISCOVERY_RPS
        pacer = _pacer_for(_DISCOVERY_PACERS, endpoint, rps)
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
        else "official_public_rpc"
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
            else "official_public_rpc"
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
                else (2.0 if discovery and _provider_kind(discovery)=="robinhood_public" else DISCOVERY_RPS)
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
            credential=(PRIMARY_ENV if dlmm else None),
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
        canonical_credential=PRIMARY_ENV,
        aggregate_requests_per_second=2.0,
        authenticated_streaming=False,
        endpoint_isolation_complete=False,
        bulk_primary_shared=bulk_primary_shared,
        bulk_primary_fallback=False,
        signing=False,
        submission=False,
    )
