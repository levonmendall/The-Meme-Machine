"""Read-only token-account concentration retrieval without policy changes.

The existing continuation-v1 input is still top-five token-account concentration.
This module first asks the already-authorized RPC for a compact finalized token-account
scan (mint filter + eight-byte amount slice), then falls back to the standard
getTokenLargestAccounts method. An optional secondary endpoint can be configured, but
there is no paid/default external dependency. Every returned context must satisfy the
same slot-freshness boundary used before this module existed.
"""
import base64
from collections import Counter

from . import pump
from .provider import RPC, Unavailable

# Retained only as an explicit opt-in known-free endpoint. It is not the default:
# hosted CI observed HTTP 403 during network verification, so repeated automatic
# use would waste requests without improving evidence.
FREE_PUBLIC_CONCENTRATION_RPC = 'https://solana-rpc.publicnode.com'
PROGRAM_SCAN_DISABLE_AFTER_IDENTICAL_PROVIDER_ERRORS = 2


class ProgramScanRPC(RPC):
    """RPC client with one additional read-only method used only for concentration."""
    ALLOWED = RPC.ALLOWED | {'getProgramAccounts'}


class ConcentrationReader:
    """Retrieve unchanged concentration evidence through bounded read-only paths."""
    def __init__(self, primary_rpc, secondary_url='', secondary_rpc=None,
                 program_rpc=None, secondary_limit=40):
        self.primary = primary_rpc
        self.secondary = secondary_rpc
        self.secondary_url = (secondary_url or '').strip()
        if self.secondary is None and self.secondary_url and self.secondary_url != getattr(primary_rpc, 'url', None):
            self.secondary = RPC(self.secondary_url, limit=secondary_limit)
        elif self.secondary_url == getattr(primary_rpc, 'url', None):
            self.secondary = None
        # For real HTTP, isolate the compact program scan in its own 40-request
        # evidence budget. Custom transports must inject program_rpc explicitly so
        # tests never escape to the network.
        self.program_rpc = program_rpc
        if self.program_rpc is None and getattr(primary_rpc, 'transport', None) == getattr(primary_rpc, '_http', None):
            if hasattr(primary_rpc, 'read_pacer') and hasattr(primary_rpc, 'provider_telemetry'):
                # Preserve concentration's isolated logical budget while using
                # the same OnFinality-primary / Alchemy-rescue transport and pace.
                from .solana_read_rpc import new_pool_scan_rpc
                self.program_rpc = new_pool_scan_rpc(
                    limit=40,
                    pacer=primary_rpc.read_pacer,
                )
            else:
                self.program_rpc = ProgramScanRPC(primary_rpc.url, limit=40)
        self.program_verified = False
        self.program_disabled_reason = None
        self.program_disabled_fingerprint = None
        self.program_first_path_attempts = 0
        self.program_first_path_failures = 0
        self.program_first_path_skips = 0
        self.program_first_path_failure_fingerprints = Counter()
        self.secondary_verified = False
        self.secondary_disabled_reason = None
        self.source_counts = {'program_scan': 0, 'secondary': 0, 'primary_largest': 0}
        self.failures = 0

    @staticmethod
    def _snapshot_context(mint, snapshot):
        c = pump.curve(snapshot['accounts'][0])
        supply, decimals = pump.mint_info(snapshot['accounts'][1])
        pump.validate_mint_supply(snapshot['accounts'][0], c, supply, decimals)
        custody = pump.pda([
            pump.un58(snapshot['pool']),
            pump.un58(snapshot['accounts'][1]['owner']),
            pump.un58(mint),
        ], 'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
        return supply, custody

    @staticmethod
    def _fresh_slot(result, snapshot):
        if not isinstance(result, dict) or 'context' not in result or 'value' not in result:
            raise Unavailable('invalid_concentration_response')
        slot = int(result['context'].get('slot', -1))
        if slot < int(snapshot['slot']) - 32:
            raise Unavailable('stale_concentration')
        return slot

    @classmethod
    def _decode_largest(cls, result, mint, snapshot):
        slot = cls._fresh_slot(result, snapshot)
        supply, custody = cls._snapshot_context(mint, snapshot)
        amounts = sorted((int(x['amount']) for x in result['value'] if x['address'] != custody), reverse=True)
        return sum(amounts[:5]) * 10000 // supply, slot

    @classmethod
    def _decode_program_scan(cls, result, mint, snapshot):
        slot = cls._fresh_slot(result, snapshot)
        supply, custody = cls._snapshot_context(mint, snapshot)
        amounts=[]
        for row in result['value']:
            if not isinstance(row, dict) or row.get('pubkey') == custody:
                continue
            account=row.get('account') or {}
            data=account.get('data')
            if not isinstance(data, list) or len(data) < 2 or data[1] != 'base64':
                raise Unavailable('invalid_concentration_response')
            try:
                raw=base64.b64decode(data[0], validate=True)
            except Exception:
                raise Unavailable('invalid_concentration_response') from None
            if len(raw) != 8:
                raise Unavailable('invalid_concentration_response')
            amounts.append(int.from_bytes(raw, 'little'))
        amounts.sort(reverse=True)
        return sum(amounts[:5]) * 10000 // supply, slot

    def _verify_program(self):
        if self.program_rpc is None or self.program_verified or self.program_disabled_reason:
            return self.program_verified
        try:
            if self.program_rpc.call('getGenesisHash', priority=True) != pump.MAINNET:
                self.program_disabled_reason='wrong_network'
                return False
            self.program_verified=True
            return True
        except (Unavailable, ValueError, KeyError, TypeError):
            self.program_disabled_reason='verification_failed'
            self.failures += 1
            return False

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

    def _program_scan(self, mint, snapshot, priority):
        if not self._verify_program():
            raise Unavailable('program_scan_unavailable')
        token_program=snapshot['accounts'][1]['owner']
        min_slot=max(0,int(snapshot['slot'])-32)
        params=[token_program, {
            'commitment':'finalized',
            'minContextSlot':min_slot,
            'withContext':True,
            'encoding':'base64',
            'dataSlice':{'offset':64,'length':8},
            'filters':[{'memcmp':{'offset':0,'bytes':mint}}],
        }]
        return self._decode_program_scan(
            self.program_rpc.call('getProgramAccounts', params, True), mint, snapshot)

    @staticmethod
    def _provider_error_counts(rpc):
        values = getattr(rpc, 'provider_error_fingerprints', None)
        return Counter(values or {})

    def _record_program_first_path_failure(self, before):
        after = self._provider_error_counts(self.program_rpc)
        for fingerprint, count in after.items():
            delta = int(count) - int(before.get(fingerprint, 0))
            if delta <= 0 or '|getProgramAccounts|' not in fingerprint:
                continue
            # Only structured provider failures open the mechanism circuit. Local
            # decoding/staleness failures remain mint-specific and keep being tested.
            if '|http:' not in fingerprint and '|jsonrpc:' not in fingerprint:
                continue
            self.program_first_path_failure_fingerprints[fingerprint] += delta
        proven = [
            fingerprint
            for fingerprint, count in self.program_first_path_failure_fingerprints.items()
            if count >= PROGRAM_SCAN_DISABLE_AFTER_IDENTICAL_PROVIDER_ERRORS
        ]
        if proven:
            # Deterministic ordering keeps restart/report behavior stable.
            fingerprint = sorted(proven)[0]
            self.program_disabled_reason = 'repeated_identical_provider_error'
            self.program_disabled_fingerprint = fingerprint

    def read(self, mint, snapshot, priority=True):
        # First choice: same authorized provider, one compact account scan. This
        # avoids the getTokenLargestAccounts method-specific pressure observed on
        # the public endpoint while preserving exact finalized account state.
        if self.program_rpc is not None:
            if self.program_disabled_reason:
                self.program_first_path_skips += 1
            else:
                self.program_first_path_attempts += 1
                before = self._provider_error_counts(self.program_rpc)
                try:
                    value,slot=self._program_scan(mint,snapshot,priority)
                    self.source_counts['program_scan'] += 1
                    return value,dict(source='program_scan',slot=slot)
                except (Unavailable, ValueError, KeyError, TypeError):
                    self.program_first_path_failures += 1
                    self.failures += 1
                    self._record_program_first_path_failure(before)

        params = [mint, {'commitment': 'finalized'}]
        # Optional secondary is strictly opt-in. A wrong/stale/unavailable response
        # is never accepted and falls through to the original primary method.
        if self._verify_secondary():
            try:
                value, slot = self._decode_largest(
                    self.secondary.call('getTokenLargestAccounts', params, priority),
                    mint, snapshot)
                self.source_counts['secondary'] += 1
                return value, dict(source='secondary', slot=slot)
            except (Unavailable, ValueError, KeyError, TypeError):
                self.failures += 1
        try:
            value, slot = self._decode_largest(
                self.primary.call('getTokenLargestAccounts', params, priority),
                mint, snapshot)
            self.source_counts['primary_largest'] += 1
            return value, dict(source='primary_largest', slot=slot)
        except (Unavailable, ValueError, KeyError, TypeError):
            self.failures += 1
            raise Unavailable('concentration_unavailable') from None

    def status(self):
        secondary = self.secondary
        program=self.program_rpc
        program_provider = (
            program.provider_telemetry()
            if program is not None and hasattr(program, 'provider_telemetry')
            else {}
        )
        known_free = self.secondary_url == FREE_PUBLIC_CONCENTRATION_RPC
        return dict(
            program_scan_configured=program is not None,
            program_scan_verified=self.program_verified,
            program_scan_disabled_reason=self.program_disabled_reason,
            program_scan_disabled_fingerprint=self.program_disabled_fingerprint,
            program_scan_circuit_open=bool(self.program_disabled_reason),
            program_scan_first_path_attempts=self.program_first_path_attempts,
            program_scan_first_path_failures=self.program_first_path_failures,
            program_scan_first_path_skips=self.program_first_path_skips,
            program_scan_first_path_failure_fingerprints=dict(
                sorted(self.program_first_path_failure_fingerprints.items())),
            program_scan_logical_requests=getattr(program,'calls',0),
            program_scan_transport_requests=getattr(program,'http_requests',0),
            program_scan_failures=getattr(program,'failures',0),
            program_scan_retries=getattr(program,'retries',0),
            program_scan_failure_kinds=dict(getattr(program,'failure_kinds',{})),
            program_scan_method_failures=dict(
                program_provider.get('provider_method_failures') or {}),
            program_scan_http_status_errors=dict(
                program_provider.get('provider_http_status_errors') or {}),
            program_scan_jsonrpc_error_codes=dict(
                program_provider.get('provider_jsonrpc_error_codes') or {}),
            program_scan_last_provider_error=program_provider.get('last_provider_error'),
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
            provider_spend_usd=0 if (not secondary or known_free) else None,
        )
