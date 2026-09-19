"""Isolated Pump Alpha v1 protocol bridge and paper executor.

This module deliberately does not use Engine, Store, Allocator, continuation-v1,
market-native priority, or any other strategy.  It reuses only protocol decoders and
quote math.  The paper book has a completely isolated bankroll so prospective
research cannot contend with or silently authorize the canonical $500 portfolio.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import json
import struct

from . import pump
from .postgrad import (buy_quote, graduation_handoff, sell_quote,\n                       validate_postgrad_snapshot)
from .pump_alpha import (
    POLICY,
    POLICY_HASH,
    STRATEGY_ID,
    evaluate_late_curve,
    evaluate_postgrad_continuation,
    evaluate_second_leg,
)

PAPER_GAS = 50_000
PAPER_RENT = 2_100_000
ENTRY_DELAY_SECONDS = 2
EXIT_DELAY_SECONDS = 2
POSITION_BPS = 500
MAX_ENTRY_SLIPPAGE_BPS = 100
MAX_SNAPSHOT_AGE_SECONDS = 20
GLOBAL_PDA = pump.pda([b"global"])


def _json_safe(value):
    if isinstance(value, Fraction):
        return {"numerator": int(value.numerator), "denominator": int(value.denominator)}
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def decode_global_curve_params(account):
    """Decode only immutable/current curve parameters needed by this strategy.

    Layout follows Pump's published Global IDL.  Keeping the decoder here avoids
    changing the shared Pump adapter merely to support this independent strategy.
    """
    raw = pump.raw_account(account, pump.PROGRAM, "Global")
    # discriminator(8), initialized(1), authority(32), fee_recipient(32)
    if len(raw) < 113:
        raise ValueError("short_global_account")
    (virtual_token, virtual_quote, real_token, total_supply, fee_bps) = struct.unpack_from(
        "<QQQQQ", raw, 73
    )
    if min(virtual_token, virtual_quote, real_token, total_supply) <= 0:
        raise ValueError("invalid_global_curve_params")
    if real_token > total_supply or fee_bps >= 10_000:
        raise ValueError("invalid_global_curve_params")
    return {
        "initial_virtual_token_reserves": int(virtual_token),
        "initial_virtual_quote_reserves": int(virtual_quote),
        "initial_real_token_reserves": int(real_token),
        "token_total_supply": int(total_supply),
        "fee_basis_points": int(fee_bps),
    }


def curve_progress_bps(real_token_reserves, initial_real_token_reserves):
    initial = int(initial_real_token_reserves)
    remaining = int(real_token_reserves)
    if initial <= 0 or remaining < 0:
        raise ValueError("invalid_curve_progress_inputs")
    sold = initial - remaining
    if sold <= 0:
        return 0
    if sold >= initial:
        return 10_000
    return sold * 10_000 // initial


def curve_points_from_snapshot(snapshot, events, global_params, now=None):
    """Reconstruct the recent curve trajectory without historical RPC calls.

    A current finalized curve reserve anchors the reconstruction.  Walking finalized
    Pump trade events backward exactly undoes their token deltas.  This gives the
    trajectory shape that matters to pump-alpha-v1 while keeping provider use bounded.
    """
    now = int(snapshot["market_time"] if now is None else now)
    c = pump.curve(snapshot["accounts"][0])
    initial = int(global_params["initial_real_token_reserves"])
    rows = sorted(
        (
            e for e in events
            if e.get("mint") == snapshot.get("mint")
            and int(e.get("market_time", 0)) <= now
            and int(e.get("slot", 0)) <= int(snapshot["slot"])
            and int(e.get("tokens", e.get("token_amount", 0))) > 0
        ),
        key=lambda e: (
            int(e.get("market_time", 0)),
            int(e.get("slot", 0)),
            int(e.get("index", 0)),
        ),
    )
    remaining = int(c.real_token)
    reverse_points = []
    for e in reversed(rows):
        reverse_points.append(
            {
                "market_time": int(e["market_time"]),
                "progress_bps": curve_progress_bps(remaining, initial),
            }
        )
        tokens = int(e.get("tokens", e.get("token_amount", 0)))
        remaining += tokens if bool(e.get("buy")) else -tokens
        if remaining < 0 or remaining > initial:
            raise ValueError("inconsistent_curve_event_reconstruction")
    points = list(reversed(reverse_points))
    points.append(
        {
            "market_time": now,
            "progress_bps": curve_progress_bps(c.real_token, initial),
        }
    )
    # Multiple trades can share a block timestamp; keep the last economic state at
    # each timestamp so velocity never divides by a synthetic zero-time interval.
    by_time = {}
    for point in points:
        by_time[int(point["market_time"])] = point
    return [by_time[t] for t in sorted(by_time)]


def graduation_quote_target(snapshot):
    """Estimate total curve quote reserves at completion from the current state.

    This is a scale denominator for net-demand features, not an executable quote.
    Fees are deliberately excluded because the curve reserve target and the trade
    event's economic flow are compared on the reserve side.
    """
    c = pump.curve(snapshot["accounts"][0])
    if c.complete or c.real_token <= 0:
        return max(1, int(c.real_sol))
    if c.token <= c.real_token:
        raise ValueError("invalid_curve_reserve_geometry")
    gross_remaining = c.sol * c.real_token // (c.token - c.real_token) + 1
    return max(1, int(c.real_sol) + int(gross_remaining))


def quote_price_from_pump_snapshot(snapshot):
    c = pump.curve(snapshot["accounts"][0])
    if c.token <= 0 or c.sol <= 0:
        raise ValueError("invalid_curve_price")
    return Fraction(int(c.sol), int(c.token))


def quote_price_from_postgrad_snapshot(snapshot):
    validate_postgrad_snapshot(
        snapshot, int(snapshot["available_time"]),
        "prospective" if snapshot.get("kind") == "real" else snapshot.get("kind"),
    )
    state = snapshot["state"]
    return Fraction(int(state["quote_reserve"]), int(state["base_reserve"]))


def normalize_events(events):
    return [
        {
            **dict(e),
            "quote_amount": int(e.get("quote_amount", e.get("amount", 0))),
            "token_amount": int(e.get("token_amount", e.get("tokens", 0))),
        }
        for e in events
    ]


def _validate_pump_snapshot(snapshot, now):
    if snapshot.get("network") != "solana-mainnet" or snapshot.get("protocol") != "pump.fun":
        raise ValueError("unsupported_pump_snapshot")
    if not int(snapshot["market_time"]) <= int(snapshot["available_time"]) <= int(now):
        raise ValueError("future_pump_snapshot")
    if int(now) - int(snapshot["market_time"]) > MAX_SNAPSHOT_AGE_SECONDS:
        raise ValueError("stale_pump_snapshot")
    mint = snapshot["mint"]
    if snapshot.get("pool") != pump.pda([b"bonding-curve", pump.un58(mint)]):
        raise ValueError("pump_pool_identity")
    c = pump.curve(snapshot["accounts"][0])
    supply, decimals = pump.mint_info(snapshot["accounts"][1])
    pump.validate_mint_supply(snapshot["accounts"][0], c, supply, decimals)
    rates = pump.fees(snapshot["accounts"][2], c, supply)
    return c, rates


class PumpAlphaPaperBook:
    """One isolated, restart-serializable paper bankroll for pump-alpha-v1."""

    def __init__(self, initial_quote, state=None):
        if int(initial_quote) <= PAPER_GAS + PAPER_RENT:
            raise ValueError("paper_bankroll_too_small")
        self.initial = int(initial_quote)
        self.state = deepcopy(state) if state is not None else {
            "strategy_id": STRATEGY_ID,
            "policy_hash": POLICY_HASH,
            "initial": self.initial,
            "cash": self.initial,
            "reserved": 0,
            "rent": 0,
            "realized": 0,
            "fees": 0,
            "orders": {},
            "positions": {},
            "decisions": [],
            "counts": {},
        }
        if int(self.state.get("initial", 0)) != self.initial:
            raise ValueError("paper_bankroll_identity")
        self.reconcile()

    def reconcile(self):
        s = self.state
        reserved = sum(
            int(o["reservation"]) for o in s["orders"].values()
            if o.get("status") == "reserved"
        )
        basis = sum(int(p["basis"]) for p in s["positions"].values())
        rents = sum(int(p["rent"]) for p in s["positions"].values())
        if reserved != int(s["reserved"]) or rents != int(s["rent"]):
            raise ValueError("paper_accounting_mismatch")
        if int(s["cash"]) + reserved + rents + basis != self.initial + int(s["realized"]):
            raise ValueError("paper_capital_conservation")
        if min(int(s["cash"]), reserved, rents) < 0:
            raise ValueError("negative_paper_balance")
        return True

    def snapshot_state(self):
        self.reconcile()
        return json.loads(json.dumps(self.state, sort_keys=True))

    def _note(self, reason, mint, now):
        counts = self.state["counts"]
        counts[reason] = int(counts.get(reason, 0)) + 1
        self.state["decisions"].append(
            {"reason": str(reason), "mint": str(mint), "time": int(now)}
        )
        self.state["decisions"] = self.state["decisions"][-100:]

    def _budget(self):
        return self.initial * POSITION_BPS // 10_000

    def _can_enter(self, mint):
        if self.state["positions"] or any(
            o.get("status") == "reserved" for o in self.state["orders"].values()
        ):
            return "isolated_single_position_limit"
        if any(o.get("mint") == mint and o.get("status") == "settled"
               for o in self.state["orders"].values()):
            return "isolated_reentry_deferred"
        reservation = self._budget() + PAPER_GAS + PAPER_RENT
        if self.state["cash"] < reservation:
            return "paper_capital_or_gas_reserve"
        return None

    def reserve_pump(self, decision, snapshot, now):
        if not decision.get("eligible") or decision.get("entry_mode") != "late_curve_acceleration":
            return "strategy_rejected"
        c, rates = _validate_pump_snapshot(snapshot, now)
        if c.complete:
            return "curve_complete"
        mint = snapshot["mint"]
        blocked = self._can_enter(mint)
        if blocked:
            return blocked
        budget = self._budget()
        tokens, _cost, _fee = pump.buy(c, budget, rates)
        oid = f"{STRATEGY_ID}:curve:{mint}:{int(now)}"
        reservation = budget + PAPER_GAS + PAPER_RENT
        self.state["cash"] -= reservation
        self.state["reserved"] += reservation
        self.state["orders"][oid] = {
            "status": "reserved", "entry_mode": "late_curve_acceleration",
            "surface": "pump.fun", "mint": mint, "budget": budget,
            "reservation": reservation, "min_tokens": tokens * (10_000-MAX_ENTRY_SLIPPAGE_BPS)//10_000,
            "created": int(now), "due": int(now)+ENTRY_DELAY_SECONDS,
            "slot": int(snapshot["slot"]), "decision": _json_safe(decision),
        }
        self._note("paper_reserved", mint, now)
        self.reconcile()
        return oid

    def fill_pump(self, oid, snapshot, now, failed=False):
        order = self.state["orders"][oid]
        if order.get("status") != "reserved":
            return order.get("status")
        if int(now) < int(order["due"]):
            return "waiting"
        error = None
        quote = None
        try:
            c, rates = _validate_pump_snapshot(snapshot, now)
            if snapshot["mint"] != order["mint"] or c.complete:
                raise ValueError("entry_identity_or_curve_state")
            if int(snapshot["market_time"]) < int(order["due"]) or int(snapshot["slot"]) <= int(order["slot"]):
                raise ValueError("no_post_delay_quote")
            tokens, cost, fee = pump.buy(c, int(order["budget"]), rates)
            if tokens < int(order["min_tokens"]) or failed:
                raise ValueError("simulated_attempt_failed")
            quote = (tokens, cost, fee)
        except (ValueError, KeyError, TypeError) as exc:
            error = str(exc)
        self.state["reserved"] -= int(order["reservation"])
        if error:
            charge = PAPER_GAS if failed else 0
            self.state["cash"] += int(order["reservation"]) - charge
            self.state["realized"] -= charge
            self.state["fees"] += charge
            order.update(status="cancelled", reason=error)
            self._note("paper_entry_cancelled", order["mint"], now)
            self.reconcile()
            return "cancelled"
        tokens, cost, fee = quote
        self.state["cash"] += int(order["reservation"]) - cost - PAPER_GAS - PAPER_RENT
        self.state["rent"] += PAPER_RENT
        self.state["fees"] += fee + PAPER_GAS
        self.state["positions"][order["mint"]] = {
            "surface": "pump.fun", "entry_mode": order["entry_mode"],
            "tokens": int(tokens), "basis": int(cost)+PAPER_GAS, "rent": PAPER_RENT,
            "opened": int(now), "entry_slot": int(snapshot["slot"]),
            "entry_price_num": int(cost), "entry_price_den": int(tokens),
            "peak_mark": int(cost), "exit_due": None, "exit_reason": None,
        }
        order.update(
            status="settled",
            fill={"tokens": int(tokens), "cost": int(cost), "fee": int(fee),
                  "gas": PAPER_GAS, "time": int(now), "slot": int(snapshot["slot"])},
        )
        self._note("paper_entry_filled", order["mint"], now)
        self.reconcile()
        return "settled"

    def reserve_postgrad(self, decision, snapshot, now):
        if not decision.get("eligible") or decision.get("entry_mode") not in {
            "postgrad_continuation", "second_leg_breakout"
        }:
            return "strategy_rejected"
        mode = "prospective" if snapshot.get("kind") == "real" else snapshot.get("kind")
        validate_postgrad_snapshot(snapshot, now, mode)
        mint = snapshot["mint"]
        blocked = self._can_enter(mint)
        if blocked:
            return blocked
        budget = self._budget()
        quote = buy_quote(snapshot, budget)
        oid = f"{STRATEGY_ID}:{decision['entry_mode']}:{mint}:{int(now)}"
        reservation = budget + PAPER_GAS + PAPER_RENT
        self.state["cash"] -= reservation
        self.state["reserved"] += reservation
        self.state["orders"][oid] = {
            "status": "reserved", "entry_mode": decision["entry_mode"],
            "surface": snapshot["surface"], "mint": mint, "budget": budget,
            "reservation": reservation,
            "min_tokens": int(quote.output_amount)*(10_000-MAX_ENTRY_SLIPPAGE_BPS)//10_000,
            "created": int(now), "due": int(now)+ENTRY_DELAY_SECONDS,
            "slot": int(snapshot["slot"]), "decision": deepcopy(decision),
        }
        self._note("paper_reserved", mint, now)
        self.reconcile()
        return oid

    def fill_postgrad(self, oid, snapshot, now, failed=False):
        order = self.state["orders"][oid]
        if order.get("status") != "reserved":
            return order.get("status")
        if int(now) < int(order["due"]):
            return "waiting"
        error = None
        quote = None
        try:
            mode = "prospective" if snapshot.get("kind") == "real" else snapshot.get("kind")
            validate_postgrad_snapshot(snapshot, now, mode)
            if snapshot["mint"] != order["mint"] or snapshot["surface"] != order["surface"]:
                raise ValueError("postgrad_entry_identity")
            if int(snapshot["market_time"]) < int(order["due"]) or int(snapshot["slot"]) <= int(order["slot"]):
                raise ValueError("no_post_delay_quote")
            quote = buy_quote(snapshot, int(order["budget"]))
            if int(quote.output_amount) < int(order["min_tokens"]) or failed:
                raise ValueError("simulated_attempt_failed")
        except (ValueError, KeyError, TypeError) as exc:
            error = str(exc)
        self.state["reserved"] -= int(order["reservation"])
        if error:
            charge = PAPER_GAS if failed else 0
            self.state["cash"] += int(order["reservation"]) - charge
            self.state["realized"] -= charge
            self.state["fees"] += charge
            order.update(status="cancelled", reason=error)
            self._note("paper_entry_cancelled", order["mint"], now)
            self.reconcile()
            return "cancelled"
        cost = int(quote.input_amount)
        self.state["cash"] += int(order["reservation"]) - cost - PAPER_GAS - PAPER_RENT
        self.state["rent"] += PAPER_RENT
        self.state["fees"] += int(quote.fee_amount) + PAPER_GAS
        self.state["positions"][order["mint"]] = {
            "surface": snapshot["surface"], "entry_mode": order["entry_mode"],
            "tokens": int(quote.output_amount), "basis": cost+PAPER_GAS, "rent": PAPER_RENT,
            "opened": int(now), "entry_slot": int(snapshot["slot"]),
            "entry_price_num": cost, "entry_price_den": int(quote.output_amount),
            "peak_mark": cost, "exit_due": None, "exit_reason": None,
        }
        order.update(
            status="settled",
            fill={"tokens": int(quote.output_amount), "cost": cost,
                  "fee": int(quote.fee_amount), "gas": PAPER_GAS,
                  "time": int(now), "slot": int(snapshot["slot"])},
        )
        self._note("paper_entry_filled", order["mint"], now)
        self.reconcile()
        return "settled"

    def handoff_to_postgrad(self, mint, completed_pump_snapshot, snapshot, decision, now):
        p = self.state["positions"].get(mint)
        if p is None or p.get("surface") != "pump.fun":
            return "no_curve_position"
        # The position cannot jump surfaces merely because a PumpSwap-shaped snapshot
        # exists. First prove the source bonding curve completed, then bind the
        # canonical post-graduation snapshot to the same mint/creator lineage.
        handoff = graduation_handoff(completed_pump_snapshot, int(now))
        mode = "prospective" if snapshot.get("kind") == "real" else snapshot.get("kind")
        validate_postgrad_snapshot(snapshot, now, mode)
        if (
            handoff.mint != mint
            or snapshot["mint"] != mint
            or snapshot.get("creator") != handoff.creator
        ):
            return "handoff_identity"
        p["surface"] = snapshot["surface"]
        p["entry_slot"] = int(snapshot["slot"])
        p["graduated_at"] = int(decision.get("graduated_at", handoff.source_market_time))
        p["graduation_source_slot"] = int(handoff.source_slot)
        if not decision.get("eligible"):
            p["exit_due"] = int(now) + EXIT_DELAY_SECONDS
            p["exit_slot"] = int(snapshot["slot"])
            p["exit_reason"] = "failed_postgrad_continuation"
            self._note("paper_graduation_exit_intended", mint, now)
            return "exit_intended"
        self._note("paper_graduation_carried", mint, now)
        return "carried"

    def monitor_pump(self, mint, snapshot, now, exit_decision):
        p = self.state["positions"].get(mint)
        if p is None:
            return "closed"
        c, rates = _validate_pump_snapshot(snapshot, now)
        if c.complete:
            return "graduated"
        proceeds, fee = pump.sell(c, int(p["tokens"]), rates)
        return self._monitor_quote(mint, snapshot, now, proceeds, fee, exit_decision)

    def monitor_postgrad(self, mint, snapshot, now, exit_decision):
        p = self.state["positions"].get(mint)
        if p is None:
            return "closed"
        mode = "prospective" if snapshot.get("kind") == "real" else snapshot.get("kind")
        validate_postgrad_snapshot(snapshot, now, mode)
        if snapshot["mint"] != mint or snapshot["surface"] != p.get("surface"):
            return "position_quote_identity"
        q = sell_quote(snapshot, int(p["tokens"]))
        return self._monitor_quote(
            mint, snapshot, now, int(q.output_amount), int(q.fee_amount), exit_decision
        )

    def _monitor_quote(self, mint, snapshot, now, proceeds, fee, exit_decision):
        p = self.state["positions"][mint]
        p["peak_mark"] = max(int(p.get("peak_mark", 0)), int(proceeds))
        if p.get("exit_due") is None and exit_decision.get("exit"):
            p["exit_due"] = int(now) + EXIT_DELAY_SECONDS
            p["exit_slot"] = int(snapshot["slot"])
            p["exit_reason"] = ",".join(exit_decision.get("reasons") or ["strategy_exit"])
            self._note("paper_exit_intended", mint, now)
            return "exit_intended"
        if p.get("exit_due") is None:
            return "holding"
        if (
            int(now) < int(p["exit_due"])
            or int(snapshot["market_time"]) < int(p["exit_due"])
            or int(snapshot["slot"]) <= int(p.get("exit_slot", -1))
        ):
            return "waiting_exit"
        self.state["cash"] += int(proceeds) - PAPER_GAS + int(p["rent"])
        self.state["rent"] -= int(p["rent"])
        realized = int(proceeds) - PAPER_GAS - int(p["basis"])
        self.state["realized"] += realized
        self.state["fees"] += int(fee) + PAPER_GAS
        for order in self.state["orders"].values():
            if order.get("mint") == mint and order.get("status") == "settled" and "exit" not in order:
                order["exit"] = {
                    "reason": p.get("exit_reason"), "proceeds": int(proceeds),
                    "fee": int(fee), "gas": PAPER_GAS, "realized": realized,
                    "time": int(now), "surface": p.get("surface"),
                }
                break
        del self.state["positions"][mint]
        self._note("paper_exit_settled", mint, now)
        self.reconcile()
        return "settled"


class PumpAlphaProspectiveRuntime:
    """Stateless signal bridge plus isolated paper-book telemetry."""

    def __init__(self, global_params, initial_quote):
        self.global_params = dict(global_params)
        self.book = PumpAlphaPaperBook(initial_quote)
        self.evaluations = 0
        self.qualifiers = 0
        self.by_mode = {}

    def evaluate_curve(self, *, snapshot, events, concentration_bps, now,
                       wallet_profiles=None, creator_profile=None, quote_asset="SOL"):
        points = curve_points_from_snapshot(snapshot, events, self.global_params, now)
        decision = evaluate_late_curve(
            curve_points=points,
            events=normalize_events(events),
            now=int(now),
            graduation_quote_target=graduation_quote_target(snapshot),
            concentration_bps=int(concentration_bps),
            quote_asset=quote_asset,
            wallet_profiles=wallet_profiles,
            creator_profile=creator_profile,
            curve_complete=bool(pump.curve(snapshot["accounts"][0]).complete),
            observed_at=int(snapshot["available_time"]),
        )
        return self._record(decision)

    def evaluate_postgrad(self, *, events, now, graduated_at, graduation_price,
                          graduation_quote_target_value, concentration_bps,
                          wallet_profiles=None, quote_asset="SOL"):
        decision = evaluate_postgrad_continuation(
            events=normalize_events(events), now=int(now), graduated_at=int(graduated_at),
            graduation_price=graduation_price,
            graduation_quote_target=int(graduation_quote_target_value),
            concentration_bps=int(concentration_bps), quote_asset=quote_asset,
            wallet_profiles=wallet_profiles,
        )
        return self._record(decision)

    def evaluate_second_leg(self, *, events, now, graduated_at,
                            graduation_quote_target_value, wallet_profiles=None,
                            quote_asset="SOL"):
        decision = evaluate_second_leg(
            events=normalize_events(events), now=int(now), graduated_at=int(graduated_at),
            graduation_quote_target=int(graduation_quote_target_value),
            wallet_profiles=wallet_profiles, quote_asset=quote_asset,
        )
        return self._record(decision)

    def _record(self, decision):
        self.evaluations += 1
        mode = decision["entry_mode"]
        self.by_mode[mode] = int(self.by_mode.get(mode, 0)) + 1
        if decision.get("eligible"):
            self.qualifiers += 1
        return decision

    def status(self):
        return {
            "strategy_id": STRATEGY_ID,
            "policy_hash": POLICY_HASH,
            "evaluations": self.evaluations,
            "qualifiers": self.qualifiers,
            "by_mode": dict(self.by_mode),
            "paper": self.book.snapshot_state(),
            "independent_from_existing_strategy_authority": True,
            "live_money_authority": False,
        }
