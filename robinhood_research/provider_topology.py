"""Multi-source Robinhood read topology for Meme Machine observability.

Authority boundary:
- the existing authenticated endpoint remains primary;
- QuickNode is an independent secondary for standard read-only Ethereum JSON-RPC;
- the official Robinhood public RPC is diagnostic-only and is never an automatic
  decision/evidence fallback;
- the Robinhood sequencer feed is observation-only and cannot authorize a trade;
- provider-specific methods (currently Alchemy asset transfers) stay pinned to the
  primary provider.

This module changes acquisition resilience/observability only. It does not modify any
strategy threshold, freshness rule, finality predicate, allocation authority or exit.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
import json
import os

from . import BoundaryError, CHAIN_ID
from .provider import Rpc


PRIMARY_ENV = "MM_ROBINHOOD_READ_RPC_URL"
QUICKNODE_ENV = "MM_ROBINHOOD_QUICKNODE_RPC_URL"
PUBLIC_DIAGNOSTIC_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
SEQUENCER_FEED_URL = "wss://feed.mainnet.chain.robinhood.com"

PRIMARY_PROVIDER = "authenticated_primary"
SECONDARY_PROVIDER = "quicknode_secondary"
PUBLIC_PROVIDER = "robinhood_public_diagnostic"

# Never send provider-specific methods to a different provider.
PRIMARY_ONLY_METHODS = frozenset({"alchemy_getAssetTransfers"})

_PROVIDER_FAILURES = (
    "provider_http_",
    "provider_rpc_",
    "provider_transport_failure",
    "provider_missing_result",
    "provider_invalid_envelope",
    "provider_invalid_json",
    "provider_invalid_batch_envelope",
    "provider_invalid_batch_ids",
    "provider_response_capacity",
    "provider_log_block_range_limit",
)


def _provider_failure(exc: BoundaryError) -> bool:
    text = str(exc)
    return any(text == item or text.startswith(item) for item in _PROVIDER_FAILURES)


def _merge_counter(*rows):
    out = Counter()
    for row in rows:
        out.update(row or {})
    return dict(out)


class MultiSourceRpc:
    """Primary-first read client with bounded independent QuickNode rescue.

    Application logical budgets remain governed by the primary Rpc object. A rescue
    request consumes the secondary provider's independent budget and is exposed in
    telemetry, but it cannot widen the caller's requested evidence scope.
    """

    def __init__(
        self,
        primary_endpoint,
        *,
        secondary_endpoint=None,
        limit=80,
        per_scope=40,
        retries=1,
        timeout=10,
        max_response=2_000_000,
        primary_transport=None,
        secondary_transport=None,
    ):
        if not primary_endpoint:
            raise BoundaryError("MM_ROBINHOOD_READ_RPC_URL_requires_full_https_url")
        secondary = (secondary_endpoint or "").strip()
        if secondary == str(primary_endpoint).strip():
            secondary = ""
        self.primary = Rpc(
            primary_endpoint,
            limit=limit,
            per_scope=per_scope,
            retries=retries,
            timeout=timeout,
            max_response=max_response,
            transport=primary_transport,
        )
        self.secondary = (
            Rpc(
                secondary,
                limit=limit,
                per_scope=per_scope,
                retries=retries,
                timeout=timeout,
                max_response=max_response,
                transport=secondary_transport,
            )
            if secondary
            else None
        )
        self.logical = 0
        self.logical_methods = Counter()
        self.scopes = Counter()
        self.failovers = Counter()
        self.failover_successes = 0
        self.failover_failures = 0
        self.receipt_cache = OrderedDict()

    @property
    def used(self):
        # Existing session-rotation logic is intentionally still governed by the
        # primary session's bounded budget.
        return self.primary.used

    @property
    def limit(self):
        return self.primary.limit

    @property
    def per_scope(self):
        return self.primary.per_scope

    @property
    def transport_used(self):
        return self.primary.transport_used + (
            self.secondary.transport_used if self.secondary else 0
        )

    @property
    def retry_count(self):
        return self.primary.retry_count + (
            self.secondary.retry_count if self.secondary else 0
        )

    @property
    def failures(self):
        rows = [self.primary.failures]
        if self.secondary:
            rows.append(self.secondary.failures)
        return Counter(_merge_counter(*rows))

    def _record_logical(self, method, scope):
        self.logical += 1
        self.logical_methods[method] += 1
        self.scopes[scope] += 1

    def _can_failover(self, methods):
        return bool(
            self.secondary
            and all(method not in PRIMARY_ONLY_METHODS for method in methods)
        )

    def call(self, method, params, *, scope="connectivity"):
        self._record_logical(method, scope)
        try:
            return self.primary.call(method, params, scope=scope)
        except BoundaryError as exc:
            if not self._can_failover((method,)) or not _provider_failure(exc):
                raise
            reason = str(exc)
            self.failovers[reason] += 1
            try:
                value = self.secondary.call(method, params, scope=scope)
            except BoundaryError:
                self.failover_failures += 1
                raise
            self.failover_successes += 1
            return value

    def batch(self, calls, *, scope="connectivity"):
        if not isinstance(calls, list) or not calls:
            raise BoundaryError("provider_batch_shape")
        methods = [row[0] for row in calls if isinstance(row, (list, tuple)) and row]
        if len(methods) != len(calls):
            raise BoundaryError("provider_batch_shape")
        for method in methods:
            self._record_logical(method, scope)
        try:
            return self.primary.batch(calls, scope=scope)
        except BoundaryError as exc:
            if not self._can_failover(methods) or not _provider_failure(exc):
                raise
            reason = str(exc)
            self.failovers[reason] += 1
            try:
                value = self.secondary.batch(calls, scope=scope)
            except BoundaryError:
                self.failover_failures += 1
                raise
            self.failover_successes += 1
            return value

    def verify_chain(self):
        result = self.call("eth_chainId", [], scope="connectivity")
        if int(result, 16) != CHAIN_ID:
            raise BoundaryError("wrong_chain")
        return CHAIN_ID

    def receipt(self, tx_hash, block_hash, *, scope):
        key = "receipt:" + tx_hash + ":" + block_hash
        if key in self.receipt_cache:
            self._record_logical("eth_getTransactionReceipt", scope)
            return json.loads(self.receipt_cache[key])
        result = self.call("eth_getTransactionReceipt", [tx_hash], scope=scope)
        if result["transactionHash"] != tx_hash or result["blockHash"] != block_hash:
            raise BoundaryError("receipt_block_disagreement")
        self.receipt_cache[key] = json.dumps(result)
        while len(self.receipt_cache) > 128:
            self.receipt_cache.popitem(last=False)
        return result

    def telemetry(self):
        primary = self.primary.telemetry()
        secondary = self.secondary.telemetry() if self.secondary else None
        provider_rows = [primary] + ([secondary] if secondary else [])
        return dict(
            requests=sum(int(row.get("requests", 0)) for row in provider_rows),
            transport_requests=sum(
                int(row.get("transport_requests", 0)) for row in provider_rows
            ),
            logical_requests=self.logical,
            retries=sum(int(row.get("retries", 0)) for row in provider_rows),
            methods=dict(self.logical_methods),
            logical_methods=dict(self.logical_methods),
            scopes=dict(self.scopes),
            failures=_merge_counter(
                primary.get("failures", {}),
                (secondary or {}).get("failures", {}),
            ),
            topology="primary_quicknode_secondary",
            primary_provider=PRIMARY_PROVIDER,
            secondary_provider=SECONDARY_PROVIDER,
            secondary_configured=self.secondary is not None,
            failovers=dict(self.failovers),
            failover_successes=self.failover_successes,
            failover_failures=self.failover_failures,
            providers=dict(primary=primary, secondary=secondary),
            authority="read_acquisition_only",
        )


def configured_rpc(primary_endpoint=None, **kwargs):
    primary = (
        str(primary_endpoint or "").strip()
        or str(os.environ.get(PRIMARY_ENV, "") or "").strip()
    )
    secondary = str(os.environ.get(QUICKNODE_ENV, "") or "").strip()
    return MultiSourceRpc(
        primary,
        secondary_endpoint=secondary,
        **kwargs,
    )


def public_diagnostic_rpc(*, limit=20, per_scope=20, retries=0):
    """Keyless Robinhood public RPC for diagnostic comparison only."""
    return Rpc(
        PUBLIC_DIAGNOSTIC_RPC_URL,
        limit=limit,
        per_scope=per_scope,
        retries=retries,
    )
