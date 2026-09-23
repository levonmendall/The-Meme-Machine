"""Compatibility shim for Meme Machine's canonical Solana read topology.

DLMM now uses the existing authenticated Alchemy endpoint directly for HTTP
reconstruction. Public Solana WebSocket remains the discovery surface. Existing
imports remain valid so ongoing research code does not need strategy-layer changes.
"""
import urllib.error
from collections import Counter

from meme_machine.provider import Unavailable
from meme_machine.solana_read_rpc import (
    ALCHEMY_ENV_NAME,
    ALCHEMY_SOLANA_MAINNET_HOST,
    PRIMARY_PROVIDER,
    PRIMARY_RPC_URL,
    PROVIDER_429_MIN_BACKOFF_SECONDS,
    ReadOnlyFailoverPoolScanRPC,
    SOLANA_MIN_REQUEST_INTERVAL_SECONDS,
    SolanaReadPacer,
    TOPOLOGY_LABEL,
    metadata as _metadata,
    primary_provider,
    primary_rpc_url,
    validate_topology,
)

ENV_NAME = ALCHEMY_ENV_NAME
PROVIDER_LABEL = TOPOLOGY_LABEL

# DLMM uses direct Alchemy HTTP reconstruction at a hard 5 requests/second ceiling.
DLMM_MIN_REQUEST_INTERVAL_SECONDS = 0.2
DLMM_PRIMARY_REQUESTS_PER_SECOND = 5
DLMM_SIGNATURE_REQUEST_INTERVAL_SECONDS = 1.0
DLMM_SIGNATURE_429_MIN_BACKOFF_SECONDS = 15.0

class AlchemyPacer(SolanaReadPacer):
    """One shared DLMM request clock plus adaptive cross-session 429 cooldown."""
    def __init__(self, minimum_interval=DLMM_MIN_REQUEST_INTERVAL_SECONDS):
        super().__init__(minimum_interval=minimum_interval)
        self.rate_limit_events=0
        self.rate_limit_streak=0
        self.rate_limit_cooldown_seconds=0.0
        self.rate_limit_successes_since_event=0
        self.method_rate_limit_events=Counter()
        self.method_successes_since_event=Counter()

    @staticmethod
    def _retry_after(exc):
        try:
            return float(exc.headers.get("Retry-After"))
        except (TypeError,ValueError,AttributeError):
            return 0.0

    def note_rate_limit(self,rpc,exc,method=None):
        self.rate_limit_events+=1
        self.rate_limit_streak=min(5,self.rate_limit_streak+1)
        self.rate_limit_successes_since_event=0
        method=str(method or "unknown")
        self.method_rate_limit_events[method]+=1
        self.method_successes_since_event[method]=0
        base=max(
            float(PROVIDER_429_MIN_BACKOFF_SECONDS),
            self._retry_after(exc),
        )
        if method=="getSignaturesForAddress":
            base=max(base,DLMM_SIGNATURE_429_MIN_BACKOFF_SECONDS)
        adaptive=min(30.0,max(base,2.0**self.rate_limit_streak))
        now=float(rpc.clock())
        self.next_request_at=max(self.next_request_at,now+adaptive)
        self.rate_limit_cooldown_seconds+=adaptive
        return adaptive

    def note_success(self,method=None):
        method=str(method or "unknown")
        self.method_successes_since_event[method]+=1
        if self.rate_limit_streak<=0:
            return
        self.rate_limit_successes_since_event+=1
        if self.rate_limit_successes_since_event>=8:
            self.rate_limit_streak=max(0,self.rate_limit_streak-1)
            self.rate_limit_successes_since_event=0

    def telemetry(self):
        data=super().telemetry()
        data.update(
            rate_limit_events=int(self.rate_limit_events),
            rate_limit_streak=int(self.rate_limit_streak),
            rate_limit_cooldown_seconds=float(
                self.rate_limit_cooldown_seconds),
            rate_limit_successes_since_event=int(
                self.rate_limit_successes_since_event),
            method_rate_limit_events=dict(sorted(self.method_rate_limit_events.items())),
            method_successes_since_event=dict(sorted(self.method_successes_since_event.items())),
            signature_request_interval_seconds=DLMM_SIGNATURE_REQUEST_INTERVAL_SECONDS,
            signature_429_min_backoff_seconds=DLMM_SIGNATURE_429_MIN_BACKOFF_SECONDS,
        )
        return data

class AlchemyPoolScanRPC(ReadOnlyFailoverPoolScanRPC):
    """DLMM direct-Alchemy client sharing rate-limit state across sessions."""
    def call(self,method,params=None,priority=False,**kwargs):
        previous=getattr(self,"_active_rpc_method",None)
        self._active_rpc_method=str(method)
        try:
            return super().call(method,params,priority,**kwargs)
        finally:
            if previous is None:
                try:del self._active_rpc_method
                except AttributeError:pass
            else:self._active_rpc_method=previous

    def call_many(self,method,params_list,priority=False,batch_size=8,**kwargs):
        previous=getattr(self,"_active_rpc_method",None)
        self._active_rpc_method=str(method)
        try:
            return super().call_many(method,params_list,priority,batch_size=batch_size,**kwargs)
        finally:
            if previous is None:
                try:del self._active_rpc_method
                except AttributeError:pass
            else:self._active_rpc_method=previous

    def _pace(self, interval=0.5):
        if self.transport == self._http:
            method=getattr(self,"_active_rpc_method",None)
            requested=(DLMM_SIGNATURE_REQUEST_INTERVAL_SECONDS
                       if method=="getSignaturesForAddress"
                       else DLMM_MIN_REQUEST_INTERVAL_SECONDS)
            self.read_pacer.pace(self, requested)

    def _provider_attempt(self,label,url,request):
        try:
            response=super()._provider_attempt(label,url,request)
        except Exception as exc:
            if (isinstance(exc,urllib.error.HTTPError)
                    and int(exc.code)==429):
                note=getattr(self.read_pacer,"note_rate_limit",None)
                if callable(note):
                    note(self,exc,getattr(self,"_active_rpc_method",None))
            raise
        success=getattr(self.read_pacer,"note_success",None)
        if callable(success):
            success(getattr(self,"_active_rpc_method",None))
        return response

    def provider_telemetry(self):
        data=super().provider_telemetry()
        data.update(
            topology="dlmm_public_ws_alchemy_http",
            primary_provider=PRIMARY_PROVIDER,
            secondary_provider=None,
            secondary_configured=False,
            failover_count=0,
            failover_reasons={},
        )
        return data


ALCHEMY_MIN_REQUEST_INTERVAL_SECONDS = DLMM_MIN_REQUEST_INTERVAL_SECONDS
ALCHEMY_429_MIN_BACKOFF_SECONDS = PROVIDER_429_MIN_BACKOFF_SECONDS


def rpc_url(environ=None):
    """Return the authenticated Alchemy endpoint used directly by DLMM."""
    return primary_rpc_url(environ, required=True)


def alchemy_rpc_url(environ=None, *, required=False):
    return primary_rpc_url(environ, required=required)


def new_rpc(limit=240, pacer=None, environ=None, **kwargs):
    # DLMM uses the authenticated Alchemy endpoint directly and preserves the same 0.2s ceiling.
    pacer = pacer or AlchemyPacer()
    return AlchemyPoolScanRPC(
        primary_rpc_url(environ,required=True),
        secondary_url=None,
        primary_provider=PRIMARY_PROVIDER,
        limit=limit,
        pacer=pacer,
        **kwargs,
    )


def metadata(environ=None):
    return dict(
        topology="dlmm_public_ws_alchemy_http",
        primary_provider=PRIMARY_PROVIDER,
        primary_credential=ALCHEMY_ENV_NAME,
        secondary_provider=None,
        secondary_configured=False,
        fallback_allowed=False,
        network="solana-mainnet",
        signing=False,
        submission=False,
        dlmm_minimum_request_interval_seconds=DLMM_MIN_REQUEST_INTERVAL_SECONDS,
        dlmm_primary_requests_per_second=DLMM_PRIMARY_REQUESTS_PER_SECOND,
    )


def main():
    primary_rpc_url(required=True)
    print(
        "DLMM Solana read topology validated: public WebSocket discovery; "
        "authenticated Alchemy HTTP reconstruction at 5 rps"
    )


if __name__ == "__main__":
    main()