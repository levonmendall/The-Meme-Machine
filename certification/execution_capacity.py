"""Integer, point-in-time execution controls shared by directional PAPER regimes.

No provider access and no alpha authority. Quotes must describe the same pinned
authoritative state; callers own freshness, provenance, fees and minimum size.
"""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Capacity:
    original_size: int
    final_size: int
    ordinary_loss_bps: int | None
    double_loss_bps: int | None
    marginal_deterioration_bps: int | None
    binding_reason: str
    evaluated_sizes: tuple

    def telemetry(self):
        return asdict(self)


def resize(intended, minimum, quote_loss, *, ordinary_limit, stress_limit=None,
           max_steps=32):
    """Find a valid size without ever increasing intended capital.

    Always test exactly 2*n, including at the final returned size. The minimum
    is explicitly tested so gas-dominated small sizes are not assumed feasible.
    Bisection only improves a known feasible lower bound. The returned answer
    does not assert that a non-monotone market's maximum capacity was found.
    """
    if any(type(x) is not int for x in (intended, minimum, ordinary_limit, max_steps)):
        raise ValueError('capacity_integer_required')
    if minimum <= 0 or intended < 0 or not 1 <= max_steps <= 64:
        raise ValueError('capacity_bounds')
    stress_limit = ordinary_limit if stress_limit is None else stress_limit
    probes = {}

    def check(n):
        if n not in probes:
            one, two = quote_loss(n), quote_loss(2*n)
            for value in (one, two):
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError('invalid_execution_loss')
            reason = ('unavailable_quote' if one is None or two is None else
                      'ordinary_execution' if one > ordinary_limit else
                      'double_size_stress' if two > stress_limit else 'intended_size')
            probes[n] = (reason == 'intended_size', one, two, reason)
        return probes[n]

    def result(n, reason):
        _, one, two, _ = probes[n] if n else (False, None, None, reason)
        return Capacity(intended, n, one, two,
                        None if one is None or two is None else two-one,
                        reason, tuple(probes))

    if intended < minimum:
        return result(0, 'below_minimum')
    good, _, _, binding = check(intended)
    if good:
        return result(intended, binding)
    # Both endpoints may be invalid (liquidity at the top, fixed fees at bottom).
    # Geometric probes search the interior without assuming monotone loss.
    upper, feasible = intended, None
    for i in range(max_steps):
        n = max(minimum, intended // (2**(i+1)))
        if check(n)[0]:
            feasible = n
            break
        upper = n
        if n == minimum:
            break
    if feasible is None and check(minimum)[0]:
        feasible, upper = minimum, intended
    if feasible is None:
        return result(0, binding)
    # Refinement has its own explicit bound; every accepted point is quoted.
    lo, hi = feasible, max(feasible, upper-1)
    for _ in range(max_steps):
        if lo >= hi:
            break
        mid = (lo+hi+1)//2
        if check(mid)[0]:
            lo = mid
        else:
            hi = mid-1
    return result(lo, binding)


def turnover_capacity(turnover, *, authenticated):
    if authenticated is not True or type(turnover) is not int or turnover < 0:
        raise ValueError('authenticated_turnover_required')
    return turnover//40


def breadth_retained(decision, fill, threshold_bps):
    return (type(decision) is int and type(fill) is int and decision > 0
            and fill >= 0 and fill*10_000 >= decision*threshold_bps)


def buyer_persistence(events, *, now, window_seconds, excluded_groups=()):
    """Two adjacent windows; excludes future events and known nonorganic groups.

    Identity and authentication are supplied by the native evidence decoder. No
    address lowercasing: Solana addresses are case sensitive. EVM normalization
    belongs to its decoder. Duplicate event identities cannot inflate turnover.
    """
    excluded = set(excluded_groups)
    rows, seen = [], {}
    for event in events:
        at = int(event['at'])
        if not now-2*window_seconds <= at <= now:
            continue
        if event.get('authenticated') is not True:
            raise ValueError('unauthenticated_buyer_event')
        key = event['id']
        if key in seen:
            if seen[key] != event:
                raise ValueError('conflicting_buyer_event')
            continue
        seen[key] = event
        group = str(event['group'])
        amount = event['quote']
        if not group or type(amount) is not int or amount < 0:
            raise ValueError('invalid_buyer_event')
        if group not in excluded:
            rows.append((at, group, amount, event['buy'] is True))
    prior = {g for at,g,_,buy in rows if buy and at < now-window_seconds}
    current = [(g,q,buy) for at,g,q,buy in rows if at >= now-window_seconds]
    buyers = {g for g,_,buy in current if buy}
    repeat = buyers & prior
    buy = sum(q for _,q,b in current if b)
    sell = sum(q for _,q,b in current if not b)
    repeat_quote = sum(q for g,q,b in current if b and g in repeat)
    groups = {g:sum(q for h,q,b in current if b and g == h) for g in buyers}
    return dict(independent_buyers=len(buyers), new_buyers=len(buyers-prior),
                repeat_buyers=len(repeat), persistent_buyer_groups=sorted(repeat),
                buyer_groups=sorted(buyers), previous_buyer_groups=sorted(prior),
                repeat_buyer_share_bps=0 if buy == 0 else repeat_quote*10_000//buy,
                buy_flow=buy, sell_flow=sell, turnover=buy+sell,
                concentration_bps=0 if buy == 0 else max(groups.values(),default=0)*10_000//buy)
