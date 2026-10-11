"""Future integration boundary: preserve native decisions and request economics.

This module is not imported by any current operational lane. The future owner
must wire native observation/qualification independently of capital decisions.
Meteora/Ramses always supply their existing strategy-native requested USD amount.
"""
from decimal import Decimal

from meme_machine.exact_money import exact, money
from .authority import _size_equity
from .model import CapitalError, FAMILIES, REGIMES, ZERO, scaled, regime, wire


@exact
def sizing_comparison(ledger, regime_name):
    r = regime(regime_name)
    if FAMILIES[r] not in ("pump", "pons"):
        raise CapitalError("lp_sizing_remains_strategy_native")
    from .authority import realized_equity
    family = FAMILIES[r]
    if ledger['policy']['sizing_basis']=='shared_realized_equity' and not ledger['family_sizing_genesis']:
        equity=realized_equity(ledger)
        return wire(dict(default='shared_realized_equity',portfolio_realized_sizing_base=equity,
            shared_equity_request=scaled(max(ZERO,equity),500),shared_add_ceiling=scaled(max(ZERO,equity),250),
            shared_position_ceiling=scaled(max(ZERO,equity),750)))
    equivalent = money(ledger["family_sizing_genesis"][family]) + sum(
        (money(ledger["realized"][other]) for other in REGIMES if FAMILIES[other] == family), ZERO)
    equity = realized_equity(ledger)
    current, shared = scaled(max(ZERO, equivalent), 500), scaled(max(ZERO, equity), 500)
    return wire(dict(default="effective_family_equivalence", family_realized_sizing_base=equivalent,
        portfolio_realized_sizing_base=equity, effective_request=current,
        shared_equity_request=shared, incremental_per_trade_risk=shared - current,
        effective_add_ceiling=scaled(max(ZERO, equivalent), 250), shared_add_ceiling=scaled(max(ZERO, equity), 250),
        effective_position_ceiling=scaled(max(ZERO, equivalent), 750), shared_position_ceiling=scaled(max(ZERO, equity), 750)))


@exact
def directional_target(ledger, regime_name, *, native_units_per_usd, legacy_native_realized_equity=None):
    """Explicit realized base, then existing integer native-unit sizing floor.

    Conversion is caller-supplied authoritative evidence, never provider I/O.
    Funding is a separate central request; this function grants no money.
    """
    r = regime(regime_name)
    if FAMILIES[r] not in ("pump", "pons"):
        raise CapitalError("lp_sizing_remains_strategy_native")
    rate = money(native_units_per_usd, positive=True)
    if ledger["policy"]["sizing_basis"] == "effective_family_equivalence":
        if type(legacy_native_realized_equity) is not int or legacy_native_realized_equity < 0:
            raise CapitalError("verified_native_sizing_base_required")
        native_equity = legacy_native_realized_equity
    else:
        equity = max(ZERO, _size_equity(ledger, r))
        native_equity = int(equity * rate)
    return dict(sizing_basis=ledger["policy"]["sizing_basis"], native_equity=native_equity,
                requested_native_units=native_equity * 500 // 10000)
