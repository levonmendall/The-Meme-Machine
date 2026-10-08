"""Explicit money, identity, risk and request contracts; no alpha rules."""
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import re

from meme_machine.exact_money import amount, exact, money

REGIMES = ("pump_current", "pump_survivor", "pons_current", "pons_survivor",
           "meteora", "ramses")
FAMILIES = {r: r.split("_")[0] for r in REGIMES}
GROUPS = {r: ["crypto_beta", "solana" if r.startswith("pump") or r == "meteora"
              else "robinhood", "directional" if "_" in r else "lp"] for r in REGIMES}
PRIORITY = {"safety": 0, "continuation": 2, "scale": 2, "new": 3}
ZERO = Decimal(0)
UNIT = Decimal("0.00000000000000000000000000001")


class CapitalError(RuntimeError):
    """Invalid authority, conflicting delivery, or failed reconciliation."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def wire(value):
    if isinstance(value, Decimal):
        return amount(value)
    if isinstance(value, dict):
        return {str(k): wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(v) for v in value]
    if isinstance(value, float):
        raise ValueError("binary_float_forbidden")
    return value


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,240}", value) or "://" in value:
        raise ValueError("invalid_capital_identity")
    return value


def checksum(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("sha256_required")
    return value


def regime(value):
    if value not in REGIMES:
        raise ValueError("unknown_regime")
    return value


def second(value):
    if type(value) is not int or value < 0:
        raise ValueError("nonnegative_integer_second_required")
    return value


def bps(value, low=0, high=10000):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("basis_points_out_of_bounds")
    return value


@exact
def scaled(value, multiplier):
    """Floor a risk/sizing ceiling conservatively to the canonical USD resolution.

    Native execution still floors to its original integer-unit boundary. Scores
    use rational arithmetic and never affect ledger precision.
    """
    units = int(money(value, nonnegative=True) / UNIT)
    return Decimal(units * multiplier // 10000) * UNIT


def ratio_bps(numerator, denominator, *, limit=10000):
    if denominator <= 0:
        return 0
    ratio = Fraction(numerator) / Fraction(denominator)
    return max(-limit, min(limit, int(ratio * 10000)))


@dataclass(frozen=True)
class RiskPolicy:
    # Aggregate ceilings only. These percentages NEVER size a position.
    portfolio_bps: int = 9000
    regime_base_bps: dict = field(default_factory=lambda: {r: 5000 for r in REGIMES})
    regime_max_bps: dict = field(default_factory=lambda: {r: 6000 for r in REGIMES})
    family_max_bps: dict = field(default_factory=lambda: {f: 6500 for f in set(FAMILIES.values())})
    asset_bps: int = 1500
    group_bps: dict = field(default_factory=lambda: {"crypto_beta": 8500, "solana": 7000,
        "robinhood": 7000, "directional": 8000, "lp": 7000})
    groups: dict = field(default_factory=lambda: {r: list(GROUPS[r]) for r in REGIMES})
    multiplier_min_bps: int = 8000
    multiplier_max_bps: int = 12000
    cooldown_seconds: int = 3600
    hysteresis_bps: int = 250
    maximum_step_bps: int = 500
    confidence_trades: int = 20
    confidence_capital_days: int = 500
    recent_seconds: int = 7 * 86400
    reference_seconds: int = 30 * 86400
    max_samples: int = 512
    drawdown_stop_bps: int = 2000
    cash_floor_bps: int = 0
    transaction_cost_floor: str = "0"
    sizing_basis: str = "effective_family_equivalence"
    adaptive: bool = False

    def value(self):
        v = asdict(self)
        if set(v["regime_base_bps"]) != set(REGIMES) or set(v["regime_max_bps"]) != set(REGIMES):
            raise ValueError("all_six_regime_budgets_required")
        if set(v["family_max_bps"]) != set(FAMILIES.values()) or set(v["groups"]) != set(REGIMES):
            raise ValueError("family_and_correlation_coverage_required")
        for key in ("portfolio_bps", "asset_bps", "drawdown_stop_bps", "hysteresis_bps", "maximum_step_bps", "cash_floor_bps"):
            bps(v[key])
        v["transaction_cost_floor"] = amount(v["transaction_cost_floor"], nonnegative=True)
        for mapping in (v["regime_base_bps"], v["regime_max_bps"], v["family_max_bps"], v["group_bps"]):
            for value in mapping.values():
                bps(value, 1)
        for r in REGIMES:
            if v["regime_base_bps"][r] > v["regime_max_bps"][r]:
                raise ValueError("base_exceeds_maximum")
            if not v["groups"][r] or len(set(v["groups"][r])) != len(v["groups"][r]):
                raise ValueError("nonempty_unique_correlation_groups_required")
            if set(v["groups"][r]) - set(v["group_bps"]):
                raise ValueError("unknown_correlation_group")
        bps(v["multiplier_min_bps"], 1, 10000)
        bps(v["multiplier_max_bps"], 10000, 15000)
        for key in ("cooldown_seconds", "confidence_trades", "confidence_capital_days",
                    "recent_seconds", "reference_seconds", "max_samples"):
            if type(v[key]) is not int or v[key] < 1:
                raise ValueError("positive_policy_integer_required")
        if v["recent_seconds"] >= v["reference_seconds"] or type(v["adaptive"]) is not bool:
            raise ValueError("allocation_window_contract")
        if v["sizing_basis"] not in ("effective_family_equivalence", "shared_realized_equity"):
            raise ValueError("explicit_sizing_basis_required")
        return wire(v)


@dataclass(frozen=True)
class Valuation:
    evidence_id: str
    evidence_sha256: str
    as_of: int
    valid_until: int
    currency: str = "USD"

    def value(self, at):
        v = asdict(self)
        identity(self.evidence_id)
        checksum(self.evidence_sha256)
        second(self.as_of); second(self.valid_until)
        if self.currency != "USD" or not self.as_of <= at <= self.valid_until:
            raise CapitalError("required_valuation_unavailable_or_invalid")
        return v


@dataclass(frozen=True)
class CapitalRequest:
    request_id: str
    epoch_id: str
    round_id: str
    regime: str
    candidate_id: str
    generation: int
    qualification_sha256: str
    requested_basis: str
    minimum_basis: str
    liquidity_capacity: str
    execution_capacity: str
    strategy_capacity: str
    cost_headroom: str
    settlement_headroom: str
    valuation: Valuation
    native_sizing: dict | None = None
    kind: str = "new"
    lifecycle_id: str | None = None
    native_quality_bps: int | None = None
    expected_holding_seconds: int | None = None
    scale_state: dict | None = None
    scale_facts: dict | None = None

    def value(self, at):
        v = asdict(self)
        for name in ("request_id", "epoch_id", "round_id", "candidate_id"):
            identity(v[name])
        regime(self.regime)
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("positive_generation_required")
        checksum(self.qualification_sha256)
        if self.kind not in PRIORITY:
            raise ValueError("invalid_funding_kind")
        if self.lifecycle_id is not None:
            identity(self.lifecycle_id)
        if self.kind != "new" and self.lifecycle_id is None:
            raise ValueError("existing_lifecycle_required")
        if self.kind == "new" and self.lifecycle_id is not None:
            raise ValueError("new_request_cannot_bypass_existing_asset_fence")
        for name in ("requested_basis", "minimum_basis"):
            v[name] = amount(v[name], positive=True)
        for name in ("liquidity_capacity", "execution_capacity", "strategy_capacity",
                     "cost_headroom", "settlement_headroom"):
            v[name] = amount(v[name], nonnegative=True)
        if money(self.minimum_basis) > money(self.requested_basis):
            raise ValueError("minimum_exceeds_strategy_request")
        v["valuation"] = self.valuation.value(at)
        if "_" in self.regime:
            sizing = self.native_sizing
            if not isinstance(sizing, dict) or set(sizing) != {"realized_equity_units", "usd_per_native_unit", "journal_sha256"}:
                raise CapitalError("verified_realized_native_sizing_required")
            if type(sizing["realized_equity_units"]) is not int or sizing["realized_equity_units"] < 0:
                raise CapitalError("realized_native_equity_units_required")
            v["native_sizing"] = dict(sizing, usd_per_native_unit=amount(sizing["usd_per_native_unit"], positive=True))
            checksum(sizing["journal_sha256"])
        if self.native_quality_bps is not None:
            bps(self.native_quality_bps)
        if self.expected_holding_seconds is not None:
            if second(self.expected_holding_seconds) < 1:
                raise ValueError("positive_holding_duration_required")
        return wire(v)
