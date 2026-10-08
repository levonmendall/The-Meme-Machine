"""Central durable PAPER cash/risk authority, with replayable sealed allocation rounds.

Every mutation reads the current SQLite state under BEGIN IMMEDIATE. Connections
may be owned by different processes; none may grant from a cached cash balance.
Commands, results and resulting state hashes share one FULL-synchronous commit.
"""
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import hashlib
import json
import re
import sqlite3
import threading

from meme_machine.exact_money import amount, exact, money
from .model import (CapitalError, CapitalRequest, FAMILIES, PRIORITY, REGIMES, UNIT,
                    ZERO, canonical, checksum, digest, identity, regime, scaled,
                    second, wire, ratio_bps, Valuation)
from .performance import update_budgets, request_score


def _sum(values):
    return sum((money(v) for v in values), ZERO)


def _bump(mapping, key, delta):
    mapping[key] = amount(money(mapping.get(key, "0")) + delta)


def _valuation(value, at):
    if not isinstance(value, dict):
        raise CapitalError("required_valuation_unavailable_or_invalid")
    return Valuation(**value).value(at)


def _size_equity(state, r):
    if state["policy"]["sizing_basis"] == "shared_realized_equity":
        return realized_equity(state)
    family = FAMILIES[r]
    return money(state["family_sizing_genesis"][family]) + _sum(
        state["realized"][other] for other in REGIMES if FAMILIES[other] == family)


@exact
def realized_equity(state):
    return money(state["initial_capital"]) + _sum(state["realized"].values()) - money(state["shared_costs"])


@exact
def capital_view(state):
    deployed = _sum(p["basis"] for p in state["positions"].values() if p["status"] == "OPEN")
    reserved = _sum(r["total"] for r in state["reservations"].values())
    pending = _sum(c["total"] for c in state["commitments"].values())
    obligations = _sum(o["amount"] for o in state["obligations"].values())
    cash = money(state["cash"])
    equity = realized_equity(state)
    free = cash - reserved - pending - obligations
    if min(cash, deployed, reserved, pending, obligations, free, equity) < 0:
        raise CapitalError("negative_capital_component")
    if cash + deployed != equity or deployed + reserved + pending + obligations > equity:
        raise CapitalError("capital_conservation_failure")
    return wire(dict(realized_equity=equity, actual_cash=cash, free_cash=free,
        deployed_basis=deployed, active_reservations=reserved,
        pending_authoritative_commitments=pending, required_funding_obligations=obligations,
        authoritative_fundable_capital=equity, conservation=True))


@exact
def risk_view(state, at):
    policy = state["policy"]
    exposure = dict(regime={r: ZERO for r in REGIMES}, family={f: ZERO for f in FAMILIES.values()},
                    asset={}, group={g: ZERO for g in policy["group_bps"]}, portfolio=ZERO)
    marked = ZERO
    complete = True
    def add(r, value, keys):
        exposure["regime"][r] += value
        exposure["family"][FAMILIES[r]] += value
        exposure["portfolio"] += value
        for key in keys:
            exposure["asset"][key] = exposure["asset"].get(key, ZERO) + value
        for group in policy["groups"][r]:
            exposure["group"][group] += value
    for p in state["positions"].values():
        if p["status"] != "OPEN":
            continue
        basis = money(p["basis"])
        mark = p.get("mark")
        valid = bool(mark and mark["valuation"]["as_of"] <= at <= mark["valuation"]["valid_until"])
        complete = complete and valid
        value = money(mark["net_value"]) if valid else basis
        marked += value
        # Losses lower the risk base; gains increase gross exposure but never the
        # realized sizing/funding base. Missing marks cannot authorize new risk.
        add(p["regime"], max(basis, value), p["economic_keys"])
    for bucket in (state["reservations"], state["commitments"]):
        for hold in bucket.values():
            # Native entry fees can be capitalized into basis. Reserve their
            # possible gross exposure as well as their cash and equity effect.
            add(hold["regime"], money(hold["basis"]) + money(hold["cost_headroom"]), hold["economic_keys"])
    equity = realized_equity(state)
    nav = money(state["cash"]) + marked
    risk_base = max(ZERO, min(equity, nav))
    drawdown = ratio_bps(max(ZERO, money(state["risk_high_water"]) - nav), money(state["risk_high_water"]))
    return dict(exposure=exposure, marked_exposure=marked,
                marked_equity=nav if complete else None, valuation_ready=complete,
                risk_base=risk_base, drawdown_bps=drawdown)


def _compatible(state, r, keys, target=None):
    # Existing Current/Survivor same-asset semantics apply across the canonical
    # asset and Pump/PumpSwap lineage keys. LP overlap is still counted in risk.
    family = FAMILIES[r]
    if family not in ("pump", "pons"):
        return True
    exposures = [p for p in state["positions"].values() if p["status"] == "OPEN"]
    exposures += list(state["reservations"].values()) + list(state["commitments"].values())
    for row in exposures:
        if target is not None and row.get("lifecycle_id", row.get("id")) == target:
            continue
        if FAMILIES[row["regime"]] == family and set(row["economic_keys"]) & set(keys):
            return False
    return True


def _scale_limit(state, request, at):
    from meme_machine.runtime.directional_continuation import scale_budget
    p = state["positions"].get(request["lifecycle_id"])
    if not p or p["status"] != "OPEN" or p["scale_committed"] or not p["partials"]:
        return ZERO
    # Invoke the approved native contract on preserved integer native units. Neither
    # the original reference nor any gate is weakened by sharing capital.
    control = deepcopy(request.get("scale_state") or {})
    facts = request.get("scale_facts") or {}
    if control.get("original_basis") != p.get("original_native_basis"):
        return ZERO
    control["scale_committed"] = p["scale_committed"]
    control["realization_taken"] = bool(p["partials"])
    native = request["native_sizing"]
    unit_value = money(native["usd_per_native_unit"])
    size_units = native["realized_equity_units"]
    if state["policy"]["sizing_basis"] == "shared_realized_equity":
        size_units = int(Fraction(realized_equity(state)) / Fraction(unit_value))
    class NativeSizing:
        def sizing_basis(self, target_bps):
            return dict(realized_equity=size_units, target=size_units * target_bps // 10000,
                        available=int(Fraction(money(capital_view(state)["free_cash"])) / Fraction(unit_value)))
    allowance = int(Fraction(min(money(request["execution_capacity"]), money(request["liquidity_capacity"]))) / Fraction(unit_value))
    return Decimal(scale_budget(control, facts, now=at, sleeve=NativeSizing(), execution_allowance=allowance)) * unit_value


@exact
def funding_decision(state, request, at):
    observation = state["observations"].get(request["regime"] + ":" + request["candidate_id"])
    deny = lambda reason: dict(status="QUALIFIED_BUT_CAPITAL_UNAVAILABLE", reason=reason, basis="0", total="0")
    if not observation or observation["generation"] != request["generation"]:
        return deny("STALE_OR_SUPERSEDED_GENERATION")
    if observation["status"] != "QUALIFIED" or observation["qualification_sha256"] != request["qualification_sha256"]:
        return deny("QUALIFICATION_CHANGED")
    try:
        _valuation(request["valuation"], at)
    except (CapitalError, ValueError, TypeError):
        return deny("VALUATION_UNAVAILABLE_OR_INVALID")
    keys, r = observation["economic_keys"], request["regime"]
    target = request["lifecycle_id"]
    if not _compatible(state, r, keys, target):
        return deny("SAME_ASSET_RESERVATION_OR_POSITION_CONFLICT")
    risk = risk_view(state, at)
    if not risk["valuation_ready"]:
        return deny("PORTFOLIO_VALUATION_UNAVAILABLE_OR_INVALID")
    if risk["drawdown_bps"] >= state["policy"]["drawdown_stop_bps"] and request["kind"] != "safety":
        return deny("PORTFOLIO_DRAWDOWN_LIMIT")
    policy, exposure, base = state["policy"], risk["exposure"], risk["risk_base"]
    # Reserve risk headroom for the equity reduction if all held costs are paid.
    held_costs = _sum(h["cost_headroom"] for bucket in (state["reservations"], state["commitments"]) for h in bucket.values())
    base = max(ZERO, base - held_costs - money(request["cost_headroom"])
               - _sum(o["amount"] for o in state["obligations"].values()))
    overhead = money(request["cost_headroom"]) + money(request["settlement_headroom"])
    regime_bps = min(policy["regime_max_bps"][r],
        policy["regime_base_bps"][r] * state["allocation"]["multipliers"][r] // 10000)
    limits = {
        "STRATEGY_REQUEST": money(request["requested_basis"]),
        "FREE_CAPITAL_AND_COST_HEADROOM": max(ZERO, money(capital_view(state)["free_cash"]) - overhead),
        "PORTFOLIO_EXPOSURE_HEADROOM": max(ZERO, scaled(base, policy["portfolio_bps"]) - exposure["portfolio"]),
        "REGIME_EXPOSURE_HEADROOM": max(ZERO, scaled(base, regime_bps) - exposure["regime"][r]),
        "FAMILY_EXPOSURE_HEADROOM": max(ZERO, scaled(base, policy["family_max_bps"][FAMILIES[r]]) - exposure["family"][FAMILIES[r]]),
        "LIQUIDITY_CAPACITY": money(request["liquidity_capacity"]),
        "EXECUTION_CAPACITY": money(request["execution_capacity"]),
        "STRATEGY_CAPACITY": money(request["strategy_capacity"]),
    }
    # An uncommitted floor is a new-risk ceiling, never a reservation or a
    # fabricated funding obligation. Existing settlement remains independent.
    floor = scaled(base, policy.get("cash_floor_bps", 0)) + money(policy.get("transaction_cost_floor", "0"))
    if floor:
        limits["CASH_AND_TRANSACTION_COST_FLOOR"] = max(ZERO,
            money(capital_view(state)["free_cash"]) - overhead - floor)
    for key in keys:
        limits["ASSET_CONCENTRATION:" + key] = max(ZERO, scaled(base, policy["asset_bps"]) - exposure["asset"].get(key, ZERO))
    for group in policy["groups"][r]:
        limits["CORRELATED_EXPOSURE:" + group] = max(ZERO, scaled(base, policy["group_bps"][group]) - exposure["group"][group])
    for constraint in list(limits):
        if "EXPOSURE_HEADROOM" in constraint or constraint.startswith(("ASSET_CONCENTRATION:", "CORRELATED_EXPOSURE:")):
            limits[constraint] = max(ZERO, limits[constraint] - money(request["cost_headroom"]))
    if request["kind"] == "scale":
        limits["STAGED_SCALE_CONTRACT"] = _scale_limit(state, request, at)
    elif request["kind"] == "new" and FAMILIES[r] in ("pump", "pons"):
        native = request["native_sizing"]
        unit_value = money(native["usd_per_native_unit"])
        size_units = native["realized_equity_units"]
        if state["policy"]["sizing_basis"] == "shared_realized_equity":
            size_units = int(Fraction(realized_equity(state)) / Fraction(unit_value))
        limits["POSITION_SIZING_BASIS"] = Decimal(size_units * 500 // 10000) * unit_value
    fundable = min(limits.values())
    binding = sorted(name for name, value in limits.items() if value == fundable)
    if fundable < money(request["minimum_basis"]):
        return dict(deny(binding[0]), limits=wire(limits), binding_constraints=binding)
    return wire(dict(status="RESERVED", reason="GRANTED", basis=fundable,
                     total=fundable + overhead, limits=limits, binding_constraints=binding))


class CapitalAuthority:
    """Only capital-granting API of the feature; inert until migration is installed."""

    def __init__(self, database, *, fault=None):
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS shared_capital_projection(
                id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS shared_capital_events(
                sequence INTEGER PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE,
                body TEXT NOT NULL, result TEXT NOT NULL, state_hash TEXT NOT NULL,
                previous TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS shared_capital_no_update
                BEFORE UPDATE ON shared_capital_events BEGIN SELECT RAISE(ABORT,'append_only'); END;
            CREATE TRIGGER IF NOT EXISTS shared_capital_no_delete
                BEFORE DELETE ON shared_capital_events BEGIN SELECT RAISE(ABORT,'append_only'); END;
        """)
        self._mutex = threading.RLock()
        self._replaying = False
        self.fault = fault
        try:
            self.verify_replay()
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    @contextmanager
    def _transaction(self, *, write):
        with self._mutex:
            self.db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def _fault(self, stage):
        if self.fault and not self._replaying:
            self.fault(stage)

    def _read(self):
        row = self.db.execute("SELECT body,hash FROM shared_capital_projection WHERE id=1").fetchone()
        head = self.db.execute("SELECT state_hash FROM shared_capital_events ORDER BY sequence DESC LIMIT 1").fetchone()
        if row is None:
            if head:
                raise CapitalError("missing_authoritative_projection")
            return None
        state = json.loads(row[0])
        if digest(state) != row[1] or not head or head[0] != row[1]:
            raise CapitalError("authoritative_projection_mismatch")
        self._reconcile(state)
        return state

    @exact
    def snapshot(self, *, at=None):
        with self._transaction(write=False):
            state = self._read()
            if state is None:
                return dict(state="NOT_INITIALIZED", paper_only=True)
            when = state["at"] if at is None else second(at)
            risk = risk_view(state, when)
            lanes = {}
            for r in REGIMES:
                lane_positions = [p for p in state["positions"].values() if p["regime"] == r]
                lanes[r] = wire(dict(deployed_basis=_sum(p["basis"] for p in lane_positions if p["status"] == "OPEN"),
                    aggregate_exposure=risk["exposure"]["regime"][r], realized_pnl=state["realized"][r],
                    costs=state["costs"][r], capital_seconds=state["capital_seconds"][r],
                    reservations=_sum(h["total"] for h in state["reservations"].values() if h["regime"] == r),
                    pending_commitments=_sum(h["total"] for h in state["commitments"].values() if h["regime"] == r),
                    unrealized_pnl=_sum(money(p["mark"]["net_value"]) - money(p["basis"])
                        for p in lane_positions if p["status"] == "OPEN" and p.get("mark")) if risk["valuation_ready"] else None,
                    contribution_bps=ratio_bps(money(state["realized"][r]), money(state["initial_capital"]), limit=1000000),
                    **state["opportunity_totals"][r]))
            return wire(dict(state="CURRENT", paper_only=True, epoch_id=state["epoch_id"],
                capital=capital_view(state), risk=risk, lanes=lanes, ledger=state))

    @exact
    def verify_replay(self):
        self._replaying = True
        try:
            return self._verify_replay()
        finally:
            self._replaying = False

    def _verify_replay(self):
        with self._transaction(write=False):
            state = None
            previous = "0" * 64
            count = 0
            for seq, op, raw, result_raw, state_hash, parent, hash_value in self.db.execute(
                    "SELECT * FROM shared_capital_events ORDER BY sequence"):
                event, result = json.loads(raw), json.loads(result_raw)
                expected = hashlib.sha256((parent + raw + result_raw + state_hash).encode()).hexdigest()
                if seq != count + 1 or previous != parent or hash_value != expected or event.get("operation_id") != op:
                    raise CapitalError("capital_journal_integrity")
                state, actual = self._apply(state, event)
                if wire(actual) != result or digest(state) != state_hash:
                    raise CapitalError("nondeterministic_capital_replay")
                self._reconcile(state)
                previous, count = hash_value, seq
            projection = self._read()
            if projection != state:
                raise CapitalError("replayed_projection_mismatch")
            return dict(events=count, journal_hash=previous, state_sha256=digest(state), conservation=True)

    @exact
    def _write(self, operation_id, action, at, data):
        identity(operation_id); second(at)
        event = wire(dict(operation_id=operation_id, action=action, at=at, data=data))
        raw = canonical(event)
        with self._transaction(write=True):
            duplicate = self.db.execute("SELECT body,result FROM shared_capital_events WHERE operation_id=?", (operation_id,)).fetchone()
            if duplicate:
                if not self._duplicate_matches(duplicate[0], raw):
                    raise CapitalError("conflicting_operation_identity")
                return json.loads(duplicate[1])
            state = self._read()
            self._fault("before_apply")
            state, result = self._apply(state, event)
            self._reconcile(state)
            self._fault("after_apply")
            result = wire(result)
            state_hash = digest(state)
            row = self.db.execute("SELECT sequence,hash FROM shared_capital_events ORDER BY sequence DESC LIMIT 1").fetchone()
            seq, previous = (row[0] + 1, row[1]) if row else (1, "0" * 64)
            result_raw = canonical(result)
            hash_value = hashlib.sha256((previous + raw + result_raw + state_hash).encode()).hexdigest()
            self.db.execute("INSERT INTO shared_capital_events VALUES(?,?,?,?,?,?,?)",
                (seq, operation_id, raw, result_raw, state_hash, previous, hash_value))
            self.db.execute("INSERT INTO shared_capital_projection VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,hash=excluded.hash",
                (canonical(state), state_hash))
            self._fault("before_commit")
        self._fault("after_commit")
        return result

    def _duplicate_matches(self, previous, current):
        return previous == current

    def install_migration(self, plan, *, operation_id="install-preserved-epoch"):
        from .migration import validate_plan
        checked = validate_plan(plan)
        return self._write(operation_id, "install", checked["seed"]["at"], checked)

    def observe(self, *, operation_id, at, regime_name, candidate_id, generation,
                status, economic_keys, evidence, policy_hash):
        r = regime(regime_name); identity(candidate_id); checksum(policy_hash)
        if type(generation) is not int or generation < 1 or status not in ("OBSERVED", "QUALIFIED", "STRATEGY_REJECTED"):
            raise ValueError("observation_contract")
        if not economic_keys or len(set(economic_keys)) != len(economic_keys):
            raise ValueError("unique_economic_asset_keys_required")
        keys = sorted(identity(k) for k in economic_keys)
        evidence = wire(deepcopy(evidence))
        if not isinstance(evidence, dict):
            raise ValueError("strategy_evidence_mapping_required")
        return self._write(operation_id, "observe", at, dict(regime=r, candidate_id=candidate_id,
            generation=generation, status=status, economic_keys=keys, evidence=evidence,
            qualification_sha256=digest(evidence), policy_hash=policy_hash))

    def open_round(self, *, operation_id, round_id, at, cutoff):
        identity(round_id); second(cutoff)
        if cutoff < at:
            raise ValueError("round_cutoff_precedes_open")
        return self._write(operation_id, "open_round", at, dict(round_id=round_id, cutoff=cutoff))

    def submit(self, request, *, at):
        if not isinstance(request, CapitalRequest):
            raise TypeError("capital_request_required")
        return self._write("request:" + identity(request.request_id), "submit", at, request.value(at))

    def seal(self, *, operation_id, round_id, regime_name, request_ids, at):
        ids = sorted(identity(i) for i in request_ids)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_manifest_identity")
        return self._write(operation_id, "seal", at, dict(round_id=identity(round_id),
            regime=regime(regime_name), request_ids=ids))

    def allocate(self, *, round_id, at):
        return self._write("allocate:" + identity(round_id), "allocate", at, dict(round_id=round_id))

    def commit(self, *, operation_id, request_id, commitment_id, at, intent_sha256, lifecycle_id=None):
        return self._write(operation_id, "commit", at, dict(request_id=identity(request_id),
            commitment_id=identity(commitment_id), intent_sha256=checksum(intent_sha256),
            lifecycle_id=identity(lifecycle_id) if lifecycle_id is not None else None))

    def cancel(self, *, operation_id, request_id, at, proof_sha256, proof_kind):
        if proof_kind not in ("DEFINITIVELY_CANCELLED", "VERIFIED_NATIVE_ABSENCE"):
            raise ValueError("definitive_cancellation_proof_required")
        return self._write(operation_id, "cancel", at, dict(request_id=identity(request_id),
            proof_sha256=checksum(proof_sha256), proof_kind=proof_kind))

    def consume(self, *, operation_id, request_id, lifecycle_id, basis, cost, at, native,
                valuation, included_cost="0", native_basis_units=None):
        return self._write(operation_id, "consume", at, dict(request_id=identity(request_id),
            lifecycle_id=identity(lifecycle_id), basis=amount(basis, positive=True),
            cost=amount(cost, nonnegative=True), included_cost=amount(included_cost, nonnegative=True),
            native=wire(native), valuation=valuation.value(at), native_basis_units=native_basis_units))

    def realize(self, *, operation_id, lifecycle_id, basis_released, gross_proceeds,
                cost, at, native, valuation, terminal=False, included_cost="0"):
        if type(terminal) is not bool:
            raise ValueError("terminal_boolean_required")
        return self._write(operation_id, "realize", at, dict(lifecycle_id=identity(lifecycle_id),
            basis_released=amount(basis_released, positive=True), gross_proceeds=amount(gross_proceeds, nonnegative=True),
            cost=amount(cost, nonnegative=True), included_cost=amount(included_cost, nonnegative=True),
            native=wire(native), valuation=valuation.value(at), terminal=terminal))

    def mark(self, *, operation_id, lifecycle_id, net_value, at, native, valuation):
        return self._write(operation_id, "mark", at, dict(lifecycle_id=identity(lifecycle_id),
            net_value=amount(net_value, nonnegative=True), native=wire(native), valuation=valuation.value(at)))

    def require_obligation(self, *, operation_id, obligation_id, regime_name, amount_usd, at, proof_sha256):
        return self._write(operation_id, "obligation", at, dict(obligation_id=identity(obligation_id),
            regime=regime(regime_name), amount=amount(amount_usd, positive=True), proof_sha256=checksum(proof_sha256)))

    def discharge_obligation(self, *, operation_id, obligation_id, paid, at, proof_sha256):
        return self._write(operation_id, "discharge", at, dict(obligation_id=identity(obligation_id),
            paid=amount(paid, nonnegative=True), proof_sha256=checksum(proof_sha256)))

    def acknowledge_native(self, *, operation_id, lifecycle_id, request_id, at, native):
        """Sequence a native reservation/intent receipt without another cash claim."""
        return self._write(operation_id, "native_ack", at, dict(lifecycle_id=identity(lifecycle_id),
            request_id=identity(request_id), native=wire(native)))

    def bind_native_identity(self, *, operation_id, family, native_lifecycle_id, at):
        if family not in FAMILIES.values():
            raise ValueError("native_family_required")
        return self._write(operation_id, "native_identity", at, dict(family=family,
            native_lifecycle_id=identity(native_lifecycle_id)))

    def acknowledge_migrated_delivery(self, *, operation_id, pending_key, at, body_sha256):
        return self._write(operation_id, "pending_ack", at, dict(pending_key=identity(pending_key),
            body_sha256=checksum(body_sha256)))

    def _native(self, state, life, native):
        if not isinstance(native, dict) or set(native) != {"epoch_id", "regime", "lifecycle_id", "event_id", "sequence", "journal_sha256"}:
            raise CapitalError("native_delivery_contract")
        identity(native["event_id"]); checksum(native["journal_sha256"])
        if native["epoch_id"] != state["epoch_id"] or native["lifecycle_id"] != life:
            raise CapitalError("native_epoch_or_lifecycle_mismatch")
        r = regime(native["regime"])
        alias = re.fullmatch(r"(pump|pons|meteora|ramses):n([0-9]+)", life)
        if alias and (alias.group(1) != FAMILIES[r] or life not in state["native_aliases"].values()):
            raise CapitalError("retired_or_unbound_native_alias")
        key = r + ":" + life
        if type(native["sequence"]) is not int or native["sequence"] != state["native_cursors"].get(key, 0) + 1:
            raise CapitalError("native_sequence_gap_or_replay")
        delivery = r + ":" + life + ":" + native["event_id"]
        if delivery in state["native_deliveries"]:
            raise CapitalError("duplicate_native_delivery_identity")
        state["native_deliveries"][delivery] = digest(native)
        state["native_cursors"][key] = native["sequence"]
        return r

    def _accrue(self, state, p, at):
        if at < p["accrued_at"]:
            raise CapitalError("position_time_regression")
        capital_seconds = money(p["basis"]) * (at - p["accrued_at"])
        _bump(p, "capital_seconds", capital_seconds)
        _bump(state["capital_seconds"], p["regime"], capital_seconds)
        p["accrued_at"] = at

    def _decision(self, state, request, at):
        return funding_decision(state, request, at)

    def _reconcile(self, state):
        if state is None:
            return
        capital_view(state)
        for life, p in state["positions"].items():
            if life != p["id"] or p["status"] not in ("OPEN", "SETTLED"):
                raise CapitalError("position_identity_or_state")
            if money(p["gross_result"]) - money(p["costs"]) != money(p["realized_pnl"]):
                raise CapitalError("position_cost_attribution_failure")
            if (p["status"] == "OPEN") != (money(p["basis"]) > 0):
                raise CapitalError("position_basis_state_failure")
        for r in REGIMES:
            if _sum(p["realized_pnl"] for p in state["positions"].values() if p["regime"] == r) + money(state["retired"][r]["pnl"]) != money(state["realized"][r]):
                raise CapitalError("lane_realized_attribution_failure")
            if (_sum(p["costs"] for p in state["positions"].values() if p["regime"] == r)
                    + money(state["retired"][r]["costs"]) + money(state["management_costs"][r]) != money(state["costs"][r])):
                raise CapitalError("lane_cost_attribution_failure")
        if set(state["reservations"]) & set(state["commitments"]):
            raise CapitalError("reservation_and_commitment_double_count")
        for key, hold in state["reservations"].items():
            if state["requests"][key]["status"] != "RESERVED":
                raise CapitalError("orphan_reservation")
        for key, hold in state["commitments"].items():
            if key in state["requests"] and state["requests"][key]["status"] != "COMMITTED":
                raise CapitalError("orphan_commitment")

    @exact
    def _apply(self, state, event):
        action, at, data = event["action"], event["at"], event["data"]
        if action == "install":
            from .migration import validate_plan
            plan = validate_plan(data)
            if state is not None:
                raise CapitalError("preserved_epoch_already_installed")
            return deepcopy(plan["seed"]), dict(migration_sha256=plan["migration_sha256"], epoch_id=plan["seed"]["epoch_id"])
        if state is None:
            raise CapitalError("preserved_epoch_migration_required")
        if at < state["at"]:
            raise CapitalError("authority_time_regression")
        state["at"] = at
        result = dict(accepted=True)
        if action == "observe":
            r = data["regime"]
            if data["policy_hash"] != state["contracts"][r]["policy_hash"]:
                raise CapitalError("strategy_policy_binding_mismatch")
            key = r + ":" + data["candidate_id"]
            old = state["observations"].get(key)
            if old and data["generation"] <= old["generation"]:
                raise CapitalError("stale_or_conflicting_observation_generation")
            state["observations"][key] = dict(deepcopy(data), at=at)
            for req_id, req in state["requests"].items():
                if req["value"]["regime"] == r and req["value"]["candidate_id"] == data["candidate_id"] and req["status"] in ("SUBMITTED", "RESERVED"):
                    state["reservations"].pop(req_id, None)
                    req["status"] = "SUPERSEDED"
                    req["reason"] = "NEW_AUTHORITATIVE_GENERATION"
            state["opportunity_totals"][r]["observed"] += 1
            if data["status"] == "QUALIFIED":
                state["opportunity_totals"][r]["qualified"] += 1
            elif data["status"] == "STRATEGY_REJECTED":
                state["opportunity_totals"][r]["strategy_rejected"] += 1
            result = dict(qualification_sha256=data["qualification_sha256"], generation=data["generation"])
        elif action == "open_round":
            if data["round_id"] in state["rounds"] or any(r["status"] == "OPEN" for r in state["rounds"].values()):
                raise CapitalError("duplicate_or_overlapping_round")
            state["rounds"][data["round_id"]] = dict(status="OPEN", cutoff=data["cutoff"], manifests={})
        elif action == "submit":
            if data["epoch_id"] != state["epoch_id"]:
                raise CapitalError("cross_epoch_request")
            round_value = state["rounds"].get(data["round_id"])
            if not round_value or round_value["status"] != "OPEN" or at > round_value["cutoff"] or data["regime"] in round_value["manifests"]:
                raise CapitalError("late_or_unsealed_round_required")
            r = data["regime"]
            observation = state["observations"].get(r + ":" + data["candidate_id"])
            if not observation or observation["status"] != "QUALIFIED" or observation["generation"] != data["generation"] or observation["qualification_sha256"] != data["qualification_sha256"]:
                raise CapitalError("fresh_authoritative_qualification_required")
            bound_fields = ("requested_basis", "minimum_basis", "liquidity_capacity", "execution_capacity",
                "strategy_capacity", "cost_headroom", "settlement_headroom", "kind", "lifecycle_id",
                "native_quality_bps", "expected_holding_seconds", "scale_state", "scale_facts", "native_sizing")
            if observation["evidence"].get("capital_request") != {k: data[k] for k in bound_fields}:
                raise CapitalError("strategy_request_economics_or_evidence_changed")
            key = digest([data[k] for k in ("epoch_id", "regime", "candidate_id", "generation", "kind", "lifecycle_id")])
            if data["request_id"] in state["requests"] or key in state["request_identities"]:
                raise CapitalError("duplicate_or_conflicting_request_identity")
            if data["kind"] != "new":
                p = state["positions"].get(data["lifecycle_id"])
                if not p or p["status"] != "OPEN" or p["regime"] != r or p["economic_keys"] != observation["economic_keys"]:
                    raise CapitalError("existing_position_authority_required")
                if data["kind"] == "scale" and ("_" not in r or data["scale_state"] != observation["evidence"].get("scale_state") or data["scale_facts"] != observation["evidence"].get("scale_facts")):
                    raise CapitalError("verified_scale_evidence_required")
                if "_" in r and data["kind"] != "scale":
                    raise CapitalError("directional_add_requires_approved_scale_contract")
                if any(req["value"]["lifecycle_id"] == data["lifecycle_id"] and req["status"] in ("SUBMITTED", "RESERVED", "COMMITTED") for req in state["requests"].values()):
                    raise CapitalError("existing_position_request_conflict")
            state["requests"][data["request_id"]] = dict(value=deepcopy(data), status="SUBMITTED", reason=None)
            state["request_identities"][key] = data["request_id"]
            result = dict(status="SUBMITTED", request_id=data["request_id"])
        elif action == "seal":
            round_value = state["rounds"].get(data["round_id"])
            if not round_value or round_value["status"] != "OPEN" or at > round_value["cutoff"]:
                raise CapitalError("open_round_required")
            actual = sorted(req_id for req_id, req in state["requests"].items()
                if req["value"]["round_id"] == data["round_id"] and req["value"]["regime"] == data["regime"])
            if data["request_ids"] != actual or data["regime"] in round_value["manifests"]:
                raise CapitalError("incomplete_or_conflicting_lane_manifest")
            round_value["manifests"][data["regime"]] = data["request_ids"]
        elif action == "allocate":
            round_value = state["rounds"].get(data["round_id"])
            if not round_value or round_value["status"] != "OPEN" or set(round_value["manifests"]) != set(REGIMES):
                raise CapitalError("all_six_lane_watermarks_required")
            if at != round_value["cutoff"]:
                raise CapitalError("deterministic_cutoff_required")
            update_budgets(state, at)
            requests = [(req_id, req["value"]) for req_id, req in state["requests"].items()
                if req["value"]["round_id"] == data["round_id"] and req["status"] == "SUBMITTED"]
            flow = {r: sum(v["regime"] == r for _, v in requests) for r in REGIMES}
            risk = risk_view(state, at)
            scores = {req_id: request_score(state, v, flow[v["regime"]], risk["exposure"], risk["risk_base"]) for req_id, v in requests}
            requests.sort(key=lambda pair: (PRIORITY[pair[1]["kind"]], -scores[pair[0]],
                digest([state["epoch_id"], data["round_id"], pair[1]["regime"], pair[1]["candidate_id"], pair[1]["generation"], pair[0]])))
            decisions = {}
            for req_id, request in requests:
                decision = self._decision(state, request, at)
                decision["priority_score"] = scores[req_id]
                decisions[req_id] = decision
                state["requests"][req_id].update(status=decision["status"], reason=decision["reason"], decision=decision)
                stats = state["opportunity_totals"][request["regime"]]
                if decision["status"] == "RESERVED":
                    observation = state["observations"][request["regime"] + ":" + request["candidate_id"]]
                    state["reservations"][req_id] = dict(regime=request["regime"], economic_keys=observation["economic_keys"],
                        basis=decision["basis"], total=decision["total"], cost_headroom=request["cost_headroom"],
                        settlement_headroom=request["settlement_headroom"], lifecycle_id=request["lifecycle_id"], created_at=at)
                    if "_" in request["regime"]:
                        state["reservations"][req_id]["native_basis_units"] = int(Fraction(money(decision["basis"])) / Fraction(money(request["native_sizing"]["usd_per_native_unit"])))
                    stats["granted"] += 1
                    stats["capital_granted"] = amount(money(stats["capital_granted"]) + money(decision["basis"]))
                else:
                    stats["qualified_but_unfunded"] += 1
                    stats["capital_denied"] = amount(money(stats["capital_denied"]) + money(request["requested_basis"]))
                    stats["denials"][decision["reason"]] = stats["denials"].get(decision["reason"], 0) + 1
                self._fault("during_allocation")
            round_value["status"] = "ALLOCATED"
            round_value["decisions"] = decisions
            round_value["order"] = [req_id for req_id, _ in requests]
            result = dict(decisions=decisions, order=round_value["order"])
        elif action == "commit":
            req_id = data["request_id"]
            req = state["requests"].get(req_id)
            if not req or req["status"] != "RESERVED":
                raise CapitalError("active_reservation_required")
            if any(c.get("commitment_id") == data["commitment_id"] for c in state["commitments"].values()):
                raise CapitalError("duplicate_commitment_identity")
            hold = state["reservations"][req_id]
            life = data["lifecycle_id"] or hold["lifecycle_id"]
            if life is None:
                raise CapitalError("commitment_lifecycle_identity_required")
            if hold["lifecycle_id"] not in (None, life) or req.get("bound_lifecycle_id") not in (None, life):
                raise CapitalError("commitment_lifecycle_identity_conflict")
            hold["lifecycle_id"] = life
            req["bound_lifecycle_id"] = life
            state["commitments"][req_id] = dict(state["reservations"].pop(req_id), **data)
            state["commitments"][req_id]["lifecycle_id"] = life
            req["status"] = "COMMITTED"
        elif action == "native_identity":
            from meme_machine.runtime.lifecycle_identity import parsed
            family, native = data["family"], data["native_lifecycle_id"]
            key = family + ":" + native
            alias = state["native_aliases"].get(key)
            if alias is None:
                issued = parsed(native)
                floor = state["retired_native_through"].get(family, 0)
                if (issued and (issued["epoch"] != state["epoch_id"] or issued["index"] <= floor)) or (floor and issued is None):
                    raise CapitalError("retired_or_cross_epoch_native_identity")
                state["native_alias_sequence"] += 1
                alias = family + ":n" + str(state["native_alias_sequence"])
                state["native_aliases"][key] = alias
            result = dict(lifecycle_id=alias)
        elif action == "pending_ack":
            key = data["pending_key"]
            pending = next((p for p in state["pending_deliveries"] if p["lane"] + ":" + p["native"] == key), None)
            if not pending or digest(pending["body"]) != data["body_sha256"]:
                raise CapitalError("pending_delivery_missing_or_conflicting")
            meta = state["pending_backing"][key]
            hold_id = "legacy-pending:" + key if meta["backing"] == "incremental" else meta.get("backing_id")
            if meta["backing"] != "position":
                req = state["requests"].get(hold_id)
                if not req or req["status"] not in ("CONSUMED", "CANCELLED"):
                    raise CapitalError("pending_delivery_still_authoritatively_committed")
            else:
                body = pending["body"]
                life = meta["backing_id"]
                if state["native_cursors"].get(meta["regime"] + ":" + life, 0) < body.get("native_sequence", 1):
                    raise CapitalError("pending_position_delivery_not_acknowledged")
            state["pending_deliveries"].remove(pending)
            del state["pending_backing"][key]
        elif action == "native_ack":
            req = state["requests"].get(data["request_id"])
            if not req or req["status"] not in ("RESERVED", "COMMITTED", "CONSUMED"):
                raise CapitalError("native_ack_requires_authoritative_request")
            r = self._native(state, data["lifecycle_id"], data["native"])
            if (req["value"]["regime"] != r or req["value"]["lifecycle_id"] not in (None, data["lifecycle_id"])
                    or req.get("bound_lifecycle_id") not in (None, data["lifecycle_id"])):
                raise CapitalError("native_ack_identity_mismatch")
            req["bound_lifecycle_id"] = data["lifecycle_id"]
            hold = state["reservations"].get(data["request_id"]) or state["commitments"].get(data["request_id"])
            if hold:
                if hold["lifecycle_id"] not in (None, data["lifecycle_id"]):
                    raise CapitalError("native_ack_identity_mismatch")
                hold["lifecycle_id"] = data["lifecycle_id"]
        elif action == "cancel":
            req = state["requests"].get(data["request_id"])
            if not req or req["status"] not in ("SUBMITTED", "RESERVED", "COMMITTED", "CANCELLED", "SUPERSEDED", "QUALIFIED_BUT_CAPITAL_UNAVAILABLE"):
                raise CapitalError("cancellation_lifecycle_invalid")
            state["reservations"].pop(data["request_id"], None)
            state["commitments"].pop(data["request_id"], None)
            if req["status"] not in ("CANCELLED", "SUPERSEDED"):
                req["status"] = "CANCELLED"
            req["cancellation"] = data
        elif action == "consume":
            req_id = data["request_id"]
            req = state["requests"].get(req_id)
            if not req or req["status"] not in ("RESERVED", "COMMITTED"):
                raise CapitalError("active_capital_hold_required")
            hold = state["reservations"].get(req_id) or state["commitments"].get(req_id)
            r = self._native(state, data["lifecycle_id"], data["native"])
            if r != hold["regime"] or hold["lifecycle_id"] not in (None, data["lifecycle_id"]):
                raise CapitalError("consumption_identity_mismatch")
            basis, cost, included = money(data["basis"]), money(data["cost"]), money(data["included_cost"])
            principal, buffer = money(hold["basis"]), money(hold["cost_headroom"])
            if (included > basis or basis - included > principal or cost > buffer
                    or basis + cost > principal + buffer
                    or req["value"]["kind"] == "scale" and basis > principal):
                raise CapitalError("consumption_exceeds_authority")
            if "_" in r:
                units = data["native_basis_units"]
                unit_value = Fraction(money(req["value"]["native_sizing"]["usd_per_native_unit"]))
                maximum = hold.get("native_basis_units", int(Fraction(principal) / unit_value))
                extra = 0 if req["value"]["kind"] == "scale" else int(Fraction(buffer - cost) / unit_value)
                if (type(units) is not int or units <= 0 or units > maximum + extra
                        or Fraction(units) - Fraction(included) / unit_value > maximum):
                    raise CapitalError("native_consumption_exceeds_authority")
            _valuation(data["valuation"], at)
            p = state["positions"].get(data["lifecycle_id"])
            if req["value"]["kind"] == "new":
                if p:
                    raise CapitalError("duplicate_position_identity")
                p = dict(id=data["lifecycle_id"], regime=r, economic_keys=hold["economic_keys"],
                    status="OPEN", basis="0", original_basis=data["basis"], capital_deployed="0",
                    realized_pnl="0", gross_result="0", costs="0", capital_seconds="0",
                    accrued_at=at, opened_at=at, partials=0, scale_committed=False, mark=None,
                    strategy_id=state["contracts"][r]["strategy_id"])
                state["positions"][p["id"]] = p
                if "_" in r:
                    p["original_native_basis"] = data["native_basis_units"]
            elif not p or p["status"] != "OPEN" or p["regime"] != r:
                raise CapitalError("existing_position_authority_required")
            else:
                self._accrue(state, p, at)
                if req["value"]["kind"] == "scale":
                    if p["scale_committed"]:
                        raise CapitalError("one_add_rule")
                    p["scale_committed"] = True
            _bump(p, "basis", basis); _bump(p, "capital_deployed", basis)
            _bump(p, "realized_pnl", -cost); _bump(p, "costs", cost + included)
            _bump(p, "gross_result", included)
            _bump(state["realized"], r, -cost); _bump(state["costs"], r, cost + included)
            state["cash"] = amount(money(state["cash"]) - basis - cost)
            p["mark"] = None
            state["reservations"].pop(req_id, None); state["commitments"].pop(req_id, None)
            settlement = money(hold["settlement_headroom"])
            if settlement:
                state["obligations"]["settlement:" + req_id] = dict(amount=amount(settlement), regime=r,
                    lifecycle_id=p["id"], proof_sha256=digest(data), request_id=req_id, kind="settlement_buffer")
            req["status"] = "CONSUMED"
            req["bound_lifecycle_id"] = data["lifecycle_id"]
            result = dict(status="CONSUMED", lifecycle_id=p["id"], basis=p["basis"])
            self._fault("during_position_creation")
        elif action in ("realize", "mark"):
            p = state["positions"].get(data["lifecycle_id"])
            if not p or p["status"] != "OPEN":
                raise CapitalError("open_position_required")
            if self._native(state, p["id"], data["native"]) != p["regime"]:
                raise CapitalError("native_regime_mismatch")
            _valuation(data["valuation"], at)
            self._accrue(state, p, at)
            if action == "mark":
                p["mark"] = dict(net_value=data["net_value"], valuation=data["valuation"])
            else:
                released, gross, cost = (money(data[k]) for k in ("basis_released", "gross_proceeds", "cost"))
                included = money(data["included_cost"])
                if released > money(p["basis"]) or data["terminal"] != (released == money(p["basis"])) or cost > gross:
                    raise CapitalError("realization_basis_or_cost_invalid")
                net = gross - cost
                pnl = net - released
                _bump(p, "basis", -released); _bump(p, "realized_pnl", pnl)
                _bump(p, "gross_result", gross - released + included); _bump(p, "costs", cost + included)
                _bump(state["realized"], p["regime"], pnl); _bump(state["costs"], p["regime"], cost + included)
                state["cash"] = amount(money(state["cash"]) + net)
                p["mark"] = None
                if data["terminal"]:
                    p["status"] = "SETTLED"; p["settled_at"] = at
                    # An ordered, authoritative terminal receipt proves that a
                    # future add to this immutable lifecycle cannot execute.
                    for req_id, req in state["requests"].items():
                        if req["value"].get("lifecycle_id") == p["id"] and req["status"] in ("SUBMITTED", "RESERVED", "COMMITTED"):
                            state["reservations"].pop(req_id, None)
                            state["commitments"].pop(req_id, None)
                            req.update(status="CANCELLED", reason="AUTHORITATIVE_POSITION_TERMINAL", cancellation=dict(proof_sha256=digest(data)))
                    for key in [key for key, o in state["obligations"].items()
                                if o.get("lifecycle_id") == p["id"] and o.get("kind") == "settlement_buffer"]:
                        del state["obligations"][key]
                    sample = dict(at=at, pnl=p["realized_pnl"], capital_deployed=p["capital_deployed"],
                                  capital_seconds=p["capital_seconds"], costs=p["costs"], lifecycle_id=p["id"])
                    state["samples"][p["regime"]].append(sample)
                    state["samples"][p["regime"]] = state["samples"][p["regime"]][-state["policy"]["max_samples"]:]
                else:
                    p["partials"] += 1
                result = dict(status=p["status"], realized_pnl=p["realized_pnl"], basis=p["basis"])
                self._fault("during_settlement" if data["terminal"] else "during_partial_realization")
            risk = risk_view(state, at)
            if risk["valuation_ready"]:
                state["risk_high_water"] = amount(max(money(state["risk_high_water"]), risk["marked_equity"]))
        elif action == "obligation":
            key = data["obligation_id"]
            if key in state["obligations"] or key in state["discharged_obligations"]:
                raise CapitalError("duplicate_obligation_identity")
            state["obligations"][key] = data
        elif action == "discharge":
            obligation = state["obligations"].pop(data["obligation_id"], None)
            if not obligation or money(data["paid"]) > money(obligation["amount"]):
                raise CapitalError("obligation_missing_or_underfunded")
            paid = money(data["paid"])
            r = obligation["regime"]
            state["cash"] = amount(money(state["cash"]) - paid)
            _bump(state["realized"], r, -paid)
            _bump(state["retired"][r], "pnl", -paid)
            _bump(state["costs"], r, paid); _bump(state["management_costs"], r, paid)
            state["discharged_obligations"][data["obligation_id"]] = data
        else:
            raise CapitalError("unknown_capital_command")
        return state, result
