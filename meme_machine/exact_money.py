"""One exact canonical USD contract; no process-global Decimal changes.

Fixed point: at most 40 integer digits and 29 fractional digits. SOL uses
lamports(9) + the conservative oracle's micros(6) = 15 places. USDG uses
token(6) + oracle(8) = 14. Pons composes an integer executable USDG quote
for 10**15 ETH raw units with the 8-place USDG oracle: USD = ETH_raw *
USDG_quote_raw * oracle_answer / 10**(15+6+8), hence 29 places.
There is no normalization or rounding at that boundary. Excess magnitude
or scale fails explicitly. Journal text keeps its original exact scale.
"""
from contextlib import contextmanager
from decimal import (Context, Decimal, Inexact, Rounded, InvalidOperation,
                     DivisionByZero, Overflow, ROUND_HALF_EVEN, localcontext)
from functools import wraps
import re

INTEGER_DIGITS = 40
FRACTIONAL_PLACES = 29
# Enough for two full-envelope operands and bounded aggregation carry. Traps
# also reject unexpected inexact arithmetic instead of silently rounding it.
PRECISION = 2 * (INTEGER_DIGITS + FRACTIONAL_PLACES) + 16
_FIXED = re.compile(rf'-?[0-9]{{1,{INTEGER_DIGITS}}}(?:\.[0-9]{{1,{FRACTIONAL_PLACES}}})?')


def money(value, *, nonnegative=False, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('exact_decimal_required')
    if isinstance(value, Decimal):
        if (not value.is_finite() or value.adjusted() >= INTEGER_DIGITS
                or value.as_tuple().exponent < -FRACTIONAL_PLACES
                or value.as_tuple().exponent > INTEGER_DIGITS):
            raise ValueError('invalid_decimal')
        text = format(value, 'f')
    else:
        text = str(value)
    if len(text) > INTEGER_DIGITS + FRACTIONAL_PLACES + 2 or not _FIXED.fullmatch(text):
        raise ValueError('invalid_decimal')
    result = Decimal(text)
    if nonnegative and result < 0 or positive and result <= 0:
        raise ValueError('invalid_monetary_sign')
    return result


def amount(value, **sign):
    return format(money(value, **sign), 'f')


def proportional_basis_release(remaining, released_raw, total_raw):
    """One conservative boundary for a possibly recurring native fraction.

    Exact integer arithmetic computes ceiling(USD basis * native fraction) in
    10^-29 USD units. It can only reduce realized P&L/sleeve capital relative
    to the exact rational allocation; it never increases available cash. The
    resulting fixed-point fact is persisted once, not re-rounded on replay.
    """
    remaining = money(remaining, positive=True)
    if (type(released_raw) is not int or type(total_raw) is not int
            or not 0 < released_raw <= total_raw):
        raise ValueError('invalid_native_basis_fraction')
    with arithmetic():
        units = int(remaining * Decimal(10**FRACTIONAL_PLACES))
        quotient, remainder = divmod(units * released_raw, total_raw)
        result = money(Decimal(quotient + bool(remainder)) * Decimal('1e-29'))
    if released_raw < total_raw and result >= remaining:
        raise ValueError('native_fraction_below_money_resolution')
    return result


@contextmanager
def arithmetic(*, exact=True):
    # Construct independently of the caller's context (precision, rounding,
    # flags, traps and exponent bounds); never mutate shared/global state.
    traps = [InvalidOperation, DivisionByZero, Overflow]
    if exact:
        traps += [Inexact, Rounded]
    context = Context(prec=PRECISION, rounding=ROUND_HALF_EVEN,
                      Emin=-999999, Emax=999999, capitals=1, clamp=0,
                      flags=[], traps=traps)
    with localcontext(context) as active:
        yield active


def exact(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with arithmetic():
            return function(*args, **kwargs)
    return wrapped


def validate_decimals(value):
    """Check computed/checkpoint monetary components before a durable commit."""
    if isinstance(value, Decimal):
        money(value)
    elif isinstance(value, dict):
        for child in value.values():
            validate_decimals(child)
    elif isinstance(value, list):
        for child in value:
            validate_decimals(child)
