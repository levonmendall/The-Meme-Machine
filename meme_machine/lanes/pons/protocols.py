"""Typed provenance and ABI-word decoders. Candidate addresses are not verification.

Pons topic/layout candidates come from predecessor code, not a verified current ABI.
Only synthetic fixtures may use them until deployment + ABI evidence is approved.
"""
from dataclasses import asdict, dataclass
from typing import Protocol
import re

from . import BoundaryError
from .evidence import Stamp, digest

ZERO = '0x' + '0'*40
PONS_LAUNCH = '0x8d4aad4953d0ca700d468f3753aa14432d1b35b43ec6409f051fb6aa43a89607'
PONS_BUY = '0xec36bf571f136799e8dc0b0b8bea4b04d8bd3d43de838aab0d5fc21d4cbfc455'
PONS_SELL = '0x8113d738abdcb6b38357e9d53a54a7157861a09031b453651f0fe7fe151f59df'


def address(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', value):
        raise BoundaryError('invalid_address')
    return value.lower()


def words(data, count):
    if not re.fullmatch(r'0x[0-9a-fA-F]*', data) or len(data) != 2 + count*64:
        raise BoundaryError('unsupported_abi_layout')
    return [int(data[i:i+64], 16) for i in range(2, len(data), 64)]


def word_address(value):
    if value < 0 or value >= 1 << 160:
        raise BoundaryError('noncanonical_abi_address')
    return f'0x{value:040x}'


@dataclass(frozen=True)
class Launch:
    token: str
    market: str
    quote: str
    creator: str
    origin: str
    factory: str
    source_event: str
    stamp: Stamp


def decode_pons_launch(log, stamp, factory):
    if stamp.kind != 'synthetic':
        raise BoundaryError('pons_current_abi_and_deployment_unverified')
    if address(log['address']) != address(factory) or log['topics'][0] != PONS_LAUNCH:
        raise BoundaryError('incorrect_factory_or_topic')
    if len(log['topics']) != 4:
        raise BoundaryError('unsupported_abi_layout')
    args = words(log['data'], 3)
    token, curve, creator = [word_address(words(x, 1)[0]) for x in log['topics'][1:]]
    return Launch(token, curve, word_address(args[0]), creator, 'pons_v2_curve',
                  factory, digest(log), stamp)


def decode_curve_trade(log, launch):
    if launch.stamp.kind != 'synthetic':
        raise BoundaryError('pons_current_abi_and_deployment_unverified')
    if address(log['address']) != launch.market:
        raise BoundaryError('incorrect_curve_identity')
    if len(log['topics']) != 3 or log['topics'][0] not in (PONS_BUY, PONS_SELL):
        raise BoundaryError('unsupported_curve_mutation')
    a, b, fee, tax = words(log['data'], 4)
    buy = log['topics'][0] == PONS_BUY
    return dict(side='buy' if buy else 'sell', quote=a if buy else b,
                tokens=b if buy else a, fee=fee, tax=tax,
                participant=word_address(words(log['topics'][1], 1)[0]),
                participant_semantics='event_actor_not_proven_independent_wallet')


@dataclass(frozen=True)
class PoolKey:
    currency0: str
    currency1: str
    fee: int
    tick_spacing: int
    hook: str

    def encoded(self):
        a, b = address(self.currency0), address(self.currency1)
        if int(a, 16) >= int(b, 16) or not 0 <= self.fee < 1 << 24 or not 0 < self.tick_spacing < 1 << 23:
            raise BoundaryError('incorrect_pool_key')
        values = (int(a, 16), int(b, 16), self.fee, self.tick_spacing, int(address(self.hook), 16))
        return b''.join(x.to_bytes(32, 'big') for x in values)

    def pool_id(self):
        from .keccak import keccak256
        return '0x' + keccak256(self.encoded()).hex()


def prove_graduation(launch, *, key, factory_state, registration, initialization, asof):
    """Three independent normalized proofs, never token appearance on Uniswap.

    Raw current Pons registration/factory ABI is not yet verified: natural input
    cannot enter this synthetic conformance implementation.
    """
    if launch.origin != 'pons_v2_curve':
        raise BoundaryError('not_pons_v2')
    if launch.stamp.kind != 'synthetic':
        raise BoundaryError('graduation_raw_abi_unverified')
    launch.stamp.check(asof, 86400)
    for proof in (factory_state, registration, initialization):
        Stamp(**proof['stamp']).check(asof, 86400)
        if proof['stamp']['kind'] != launch.stamp.kind:
            raise BoundaryError('mixed_evidence_kind')
    if factory_state['factory'] != launch.factory or factory_state['curve'] != launch.market or factory_state['token'] != launch.token or factory_state['phase'] != 2:
        raise BoundaryError('graduation_factory_state_mismatch')
    if set((key.currency0, key.currency1)) != set((launch.token, launch.quote)):
        raise BoundaryError('graduation_currency_mismatch')
    if registration['hook'] != key.hook or registration['token'] != launch.token or registration['curve'] != launch.market:
        raise BoundaryError('unrelated_v4_pool')
    if initialization['pool_manager'] != factory_state['pool_manager'] or initialization['key'] != asdict(key):
        raise BoundaryError('v4_initialization_mismatch')
    pool_id = key.pool_id()
    if any(p['pool_id'] != pool_id for p in (factory_state, registration, initialization)):
        raise BoundaryError('incorrect_pool_identity')
    return dict(origin='pons_v2_graduated_v4', token=launch.token, previous_market=launch.market,
                market=pool_id, pregraduation_source=launch.source_event,
                proof_hash=digest([factory_state, registration, initialization]))


def classify_discovery(*, origin, asset_class, provenance, executable, kind):
    if asset_class != 'speculative':
        return 'excluded_' + asset_class
    if not provenance:
        return 'unknown_provenance'
    if not executable:
        return 'unavailable_liquidity'
    if origin not in ('pons_v1_v3', 'pons_v2_curve', 'pons_v2_graduated_v4', 'non_pons_v3', 'non_pons_v4'):
        return 'unknown_origin'
    if kind != 'synthetic':
        return 'deployment_provenance_pending'
    return origin


class DiscoveryAdapter(Protocol):
    """Later Pools.trade/V3/V4 implementations must supply authentic origin proofs."""
    def discover(self, start_block: int, end_block: int) -> list[Launch]: ...


class ExecutableQuoteAdapter(Protocol):
    def quote(self, market: str, side: str, amount_in: int, asof: int): ...
