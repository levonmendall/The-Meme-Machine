"""Read-only token-account concentration with a bounded free fallback.

This module does not alter continuation-v1. It only retrieves the existing top-five
account-concentration input. Every provider must prove Solana mainnet identity and a
returned concentration context must be close enough to the candidate snapshot slot.
"""
from . import pump
from .provider import RPC, Unavailable

FREE_PUBLIC_CONCENTRATION_RPC = 'https://solana-rpc.publicnode.com'


class ConcentrationReader:
    """Prefer a dedicated free read endpoint, then fail over to the primary RPC.

    The secondary is isolated to the expensive getTokenLargestAccounts call so the
    Pump stream/snapshot provider does not spend its public per-method quota on it.
    A bad, stale, wrong-network, or unavailable secondary is never trusted; the same
    finalized-slot freshness check is applied to both sources.
    """
    def __init__(self, primary_rpc, secondary_url=FREE_PUBLIC_CONCENTRATION_RPC,
                 secondary_rpc=None, secondary_limit=40):
        self.primary = primary_rpc
        self.secondary = secondary_rpc
        self.secondary_url = (secondary_url or '').strip()
        if self.secondary is None and self.secondary_url and self.secondary_url != getattr(primary_rpc, 'url', None):
            self.secondary = RPC(self.secondary_url, limit=secondary_limit)
        elif self.secondary_url == getattr(primary_rpc, 'url', None):
            self.secondary = None
        self.secondary_verified = False
        self.secondary_disabled_reason = None
        self.source_counts = {'secondary': 0, 'primary': 0}
        self.failures = 0

    @staticmethod
    def _decode(result, mint, snapshot):
        if not isinstance(result, dict) or 'context' not in result or 'value' not in result:
            raise Unavailable('invalid_concentration_response')
        slot = int(result['context'].get('slot', -1))
        if slot < int(snapshot['slot']) - 32:
            raise Unavailable('stale_concentration')
        c = pump.curve(snapshot['accounts'][0])
        supply, decimals = pump.mint_info(snapshot['accounts'][1])
        pump.validate_mint_supply(snapshot['accounts'][0], c, supply, decimals)
        custody = pump.pda([
            pump.un58(snapshot['pool']),
            pump.un58(snapshot['accounts'][1]['owner']),
            pump.un58(mint),
        ], 'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
        amounts = sorted((int(x['amount']) for x in result['value'] if x['address'] != custody), reverse=True)
        return sum(amounts[:5]) * 10000 // supply, slot

    def _verify_secondary(self):
        if self.secondary is None or self.secondary_verified or self.secondary_disabled_reason:
            return self.secondary_verified
        try:
            if self.secondary.call('getGenesisHash', priority=True) != pump.MAINNET:
                self.secondary_disabled_reason = 'wrong_network'
                return False
            self.secondary_verified = True
            return True
        except (Unavailable, ValueError, KeyError, TypeError):
            self.secondary_disabled_reason = 'verification_failed'
            self.failures += 1
            return False

    def read(self, mint, snapshot, priority=True):
        params = [mint, {'commitment': 'finalized'}]
        if self._verify_secondary():
            try:
                value, slot = self._decode(
                    self.secondary.call('getTokenLargestAccounts', params, priority),
                    mint, snapshot)
                self.source_counts['secondary'] += 1
                return value, dict(source='secondary', slot=slot)
            except (Unavailable, ValueError, KeyError, TypeError):
                self.failures += 1
        try:
            value, slot = self._decode(
                self.primary.call('getTokenLargestAccounts', params, priority),
                mint, snapshot)
            self.source_counts['primary'] += 1
            return value, dict(source='primary', slot=slot)
        except (Unavailable, ValueError, KeyError, TypeError):
            self.failures += 1
            raise Unavailable('concentration_unavailable') from None

    def status(self):
        secondary = self.secondary
        known_free = self.secondary_url == FREE_PUBLIC_CONCENTRATION_RPC
        return dict(
            secondary_configured=secondary is not None,
            secondary_kind='publicnode_free' if known_free else ('configured' if secondary is not None else 'none'),
            secondary_verified=self.secondary_verified,
            secondary_disabled_reason=self.secondary_disabled_reason,
            source_counts=dict(self.source_counts),
            retrieval_failures=self.failures,
            secondary_logical_requests=getattr(secondary, 'calls', 0),
            secondary_transport_requests=getattr(secondary, 'http_requests', 0),
            secondary_failures=getattr(secondary, 'failures', 0),
            secondary_retries=getattr(secondary, 'retries', 0),
            secondary_failure_kinds=dict(getattr(secondary, 'failure_kinds', {})),
            provider_spend_usd=0 if known_free else None,
        )
