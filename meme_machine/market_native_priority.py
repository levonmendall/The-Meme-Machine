"""Research-only market-native evidence prioritization.

Broad market-native discovery remains unchanged. This module only decides which
already-discovered mints deserve scarce RPC evidence first. It never authorizes an
order and never changes continuation-v1.

The hierarchy deliberately uses frozen-policy feasibility rather than historical
outcomes:

1. reject only conditions that are already impossible under the current 60-second
   market tape (evidence > 100, fewer than three possible independent buyers, or an
   optimistic independent-net-buy upper bound below 1 SOL);
2. within a time slot, prioritize the candidate with the strongest balanced margin
   above the existing independent-demand minima, then the most evidence-cap headroom;
3. use one Pump snapshot to evaluate every non-concentration continuation-v1 gate;
4. request concentration only when every other frozen gate can still pass.

No score here is an alpha or profitability score. It is an evidence-budget scheduler.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .engine import MAYHEM_AGENT_WALLET
from .research import CURRENT_THRESHOLDS, qualification_vector


@dataclass(frozen=True)
class StreamFeasibility:
    mint: str
    possible: bool
    guaranteed_rejection: str | None
    evidence_events: int
    possible_independent_buyers: int
    optimistic_independent_net_buy_lamports: int
    evidence_headroom: int
    demand_margin_milli: int
    nomination_market_time: int
    research_only: bool = True
    order_authority: bool = False

    def to_dict(self):
        return asdict(self)

    def priority_key(self):
        """Smaller is better; all terms come from current policy or signal expiry."""
        return (
            -int(self.demand_margin_milli),
            -int(self.possible_independent_buyers),
            -int(self.optimistic_independent_net_buy_lamports),
            -int(self.evidence_headroom),
            int(self.nomination_market_time),
            self.mint,
        )


def priority_slot_seconds(discovery_seconds: int, preflight_budget: int) -> int:
    """Spread a finite provider budget across the entire observation period."""
    if discovery_seconds < 1 or preflight_budget < 1:
        raise ValueError('invalid_priority_budget')
    return max(1, math.ceil(int(discovery_seconds) / int(preflight_budget)))


def stream_feasibility(candidate, tape, now) -> StreamFeasibility:
    """Compute RPC-free policy feasibility from the finalized Pump tape.

    Creator identity is not known until a snapshot exists. For net demand, therefore,
    compute the *best possible* result after removing any one non-anchor wallet as the
    unknown creator. A rejection is emitted only when even that optimistic bound
    cannot satisfy continuation-v1.
    """
    nomination = candidate['nomination']
    mint = candidate['mint']
    window = tape.window(mint, now)
    max_events = int(CURRENT_THRESHOLDS['max_evidence_events'])
    min_groups = int(CURRENT_THRESHOLDS['min_independent_groups'])
    min_net = int(CURRENT_THRESHOLDS['min_net_buy_lamports'])

    anchor = nomination['wallet']
    buyer_wallets = set()
    wallet_net = {}
    for event in window:
        wallet = event.get('wallet')
        if not wallet or wallet in (anchor, MAYHEM_AGENT_WALLET):
            continue
        amount = int(event.get('amount', 0))
        if amount <= 0:
            continue
        wallet_net[wallet] = wallet_net.get(wallet, 0) + amount * (1 if event.get('buy') else -1)
        if event.get('buy'):
            buyer_wallets.add(wallet)

    total_net = sum(wallet_net.values())
    # Removing an unknown creator can only improve net demand if that wallet was a
    # net seller. Remove the most-negative wallet to form a safe optimistic bound.
    most_negative = min([0, *wallet_net.values()])
    optimistic_net = total_net - most_negative
    evidence_events = len(window)
    evidence_headroom = max_events - evidence_events

    reason = None
    if evidence_events > max_events:
        reason = 'evidence_capacity'
    elif len(buyer_wallets) < min_groups:
        reason = 'independent_demand_impossible'
    elif optimistic_net < min_net:
        reason = 'independent_demand_impossible'

    # Balanced policy-margin index used only for scheduling candidates within one
    # time slot. 1000 == exactly at both current independent-demand minima.
    group_ratio_milli = len(buyer_wallets) * 1000 // min_groups
    net_ratio_milli = optimistic_net * 1000 // min_net if min_net else 0
    demand_margin_milli = min(group_ratio_milli, net_ratio_milli)

    return StreamFeasibility(
        mint=mint,
        possible=reason is None,
        guaranteed_rejection=reason,
        evidence_events=evidence_events,
        possible_independent_buyers=len(buyer_wallets),
        optimistic_independent_net_buy_lamports=optimistic_net,
        evidence_headroom=evidence_headroom,
        demand_margin_milli=demand_margin_milli,
        nomination_market_time=int(nomination['market_time']),
    )


def choose_slot_candidate(rows):
    """Choose one feasible candidate deterministically for a provider-budget slot."""
    feasible=[row for row in rows if row[1].possible]
    if not feasible:
        return None
    return min(feasible, key=lambda row: row[1].priority_key())


def snapshot_preflight(engine, nomination, snapshot, events, now):
    """Evaluate every continuation-v1 gate except concentration with one snapshot.

    Concentration is set to zero only inside this research-only vector so the canonical
    engine can reveal whether another existing gate would reject first. A result of
    ``passes_non_concentration`` never authorizes a reservation; it only permits the
    separate concentration request.
    """
    evidence=dict(snapshot=snapshot, events=list(events), covered=True, concentration_bps=0)
    vector=qualification_vector(engine, nomination, evidence, now)
    return dict(
        authority='research_only',
        order_authority=False,
        concentration_assumption='zero_for_prefilter_only',
        passes_non_concentration=vector.get('actual_reason') == 'qualified',
        non_concentration_reason=(None if vector.get('actual_reason') == 'qualified'
                                  else vector.get('actual_reason')),
        vector=vector,
    )
