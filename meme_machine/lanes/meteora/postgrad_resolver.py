"""Fail-closed read-only resolver for post-graduation surfaces.

Canonical PumpSwap is deterministic and always checked first. Historical Raydium-v4
has no current deterministic migration PDA, and a mint may have multiple valid WSOL
pools, so the fallback accepts only a checked explicit provenance record and revalidates
that pool on chain. Generic Raydium scanning remains diagnostic only.

This resolver has no allocation, order, signing, submission, or live-money authority.
"""
import json
from pathlib import Path

from .legacy_raydium import LegacyRaydiumProvenance, read_explicit_pool
from .provider import Unavailable

REGISTRY_SCHEMA = 'legacy-raydium-pool-provenance-v1'
REGISTRY_AUTHORITY = 'read-only research only; never selects or authorizes a trade'


def load_legacy_raydium_registry(path):
    """Load a small explicit research registry without turning it into authority."""
    doc = json.loads(Path(path).read_text())
    if doc.get('schema') != REGISTRY_SCHEMA or doc.get('authority') != REGISTRY_AUTHORITY:
        raise ValueError('legacy_raydium_registry_identity')
    records = doc.get('records')
    if not isinstance(records, list) or len(records) > 32:
        raise ValueError('legacy_raydium_registry_bound')
    out = {}
    pools = set()
    for row in records:
        try:
            mint = row['mint']
            pool = row['pool']
            if row.get('surface') != 'raydium-v4':
                raise ValueError('legacy_raydium_registry_surface')
            if row.get('allocation_eligible'):
                raise ValueError('legacy_raydium_registry_allocation')
            if not row.get('current_pair_identity_verified'):
                raise ValueError('legacy_raydium_registry_unverified_pair')
            if mint in out or pool in pools:
                raise ValueError('legacy_raydium_registry_duplicate')
            provenance = LegacyRaydiumProvenance(
                mint=mint,
                pool=pool,
                current_pair_identity_verified=True,
                direct_pump_withdraw_lineage_verified=bool(
                    row.get('direct_pump_withdraw_lineage_verified')),
                source_label=REGISTRY_SCHEMA,
            )
        except (KeyError, TypeError) as exc:
            raise ValueError('legacy_raydium_registry_record') from exc
        out[mint] = provenance
        pools.add(pool)
    return out


class VerifiedPostGraduationResolver:
    """Resolve a completed Pump handoff without guessing among legacy pools."""
    def __init__(self, adapter, legacy_provenance=None):
        self.adapter = adapter
        self.legacy_provenance = dict(legacy_provenance or {})

    def resolve(self, handoff, now, priority=True):
        try:
            snapshot = self.adapter.pumpswap_snapshot(handoff, now, priority)
            snapshot.setdefault('source', {})['resolution_path'] = 'canonical_pumpswap'
            snapshot['source']['allocation_eligible'] = False
            return snapshot
        except Unavailable as exc:
            # Only a proved missing canonical PumpSwap pool permits a legacy lookup.
            # Malformed/stale/provider-failed PumpSwap evidence must never silently
            # fall through to another venue.
            if str(exc) != 'pumpswap_pool_missing':
                raise
        provenance = self.legacy_provenance.get(handoff.mint)
        if provenance is None:
            raise Unavailable('legacy_raydium_provenance_missing')
        snapshot = read_explicit_pool(
            self.adapter, handoff, provenance, now, priority=priority)
        snapshot.setdefault('source', {})['resolution_path'] = 'explicit_legacy_raydium'
        snapshot['source']['allocation_eligible'] = False
        return snapshot
