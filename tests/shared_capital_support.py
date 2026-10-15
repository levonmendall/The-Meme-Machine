"""Offline capital fixtures, always temporary and never a runtime epoch."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from fractions import Fraction

from meme_machine.portfolio_accounting import PortfolioAccounting, inception_receipt, LANES
from meme_machine.shared_capital import CapitalAuthority, CapitalRequest, REGIMES, RiskPolicy, Valuation
from meme_machine.shared_capital.model import FAMILIES, digest, money, amount, UNIT
from meme_machine.shared_capital.authority import _size_equity
from meme_machine.exact_money import exact, arithmetic
from meme_machine.shared_capital.migration import plan_migration

EPOCH = "synthetic-shared-capital-fixture"
CONTRACTS = {r: dict(strategy_id=r, policy_hash=digest(["offline-policy", r])) for r in REGIMES}
CAPITAL_FIELDS = ("requested_basis", "minimum_basis", "liquidity_capacity", "execution_capacity",
    "strategy_capacity", "cost_headroom", "settlement_headroom", "kind", "lifecycle_id",
    "native_quality_bps", "expected_holding_seconds", "scale_state", "scale_facts", "native_sizing")


def utc(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def legacy_identities(family=None):
    return dict(source_sha="a" * 40, policy_hash=CONTRACTS.get(family + "_current" if family in ("pump", "pons") else family, CONTRACTS["pump_current"])["policy_hash"], config_hash="c" * 64)


def legacy_proof(family, at):
    return dict(source_event_id="legacy:" + family + ":" + str(at), source_kind="offline_fixture",
        **legacy_identities(family), value_evidence=dict(evidence_id="legacy-value", evidence_sha256="e" * 64,
            currency="USD", as_of=utc(at), valid_until=utc(at + 100000)))


def legacy_fixture(path):
    old = PortfolioAccounting(path)
    old.establish_inception(inception_receipt(EPOCH, utc(0), "synthetic-fixture-inception"),
        portfolio_identities=legacy_identities(), lane_identities={f: legacy_identities(f) for f in LANES})
    old.configure_family_sleeves()
    return old


def empty_mapping():
    return dict(contracts=deepcopy(CONTRACTS), position_meta={}, reservation_meta={},
        retired={r: dict(pnl="0", costs="0", count=0) for r in REGIMES},
        pending={}, cursor_mapping={}, obligations={})


class Harness:
    def __init__(self, root, policy=RiskPolicy(), *, plan=None):
        self.root = Path(root)
        self.path = self.root / "isolated-shared.sqlite"
        if plan is None:
            old = legacy_fixture(self.root / "synthetic-legacy.sqlite")
            old.close()
            plan = plan_migration(self.root / "synthetic-legacy.sqlite", empty_mapping(), policy)
        self.plan = plan
        self.authority = CapitalAuthority(self.path)
        self.authority.install_migration(plan)
        self.counter = 0
        self.at = plan["seed"]["at"]
        self.generations = {}

    def close(self):
        self.authority.close()

    def restart(self):
        before = self.authority.snapshot()
        self.authority.close()
        self.authority = CapitalAuthority(self.path)
        assert self.authority.snapshot() == before

    def valuation(self):
        return Valuation("offline-usd-value", "e" * 64, self.at, self.at + 100000)

    def native(self, r, life, event=None):
        state = self.authority.snapshot()["ledger"]
        seq = state["native_cursors"].get(r + ":" + life, 0) + 1
        return dict(epoch_id=EPOCH, regime=r, lifecycle_id=life, sequence=seq,
                    event_id=event or "native-" + str(seq), journal_sha256=digest([r, life, seq]))

    def prepare(self, r, *, round_id, request_id=None, asset=None, requested=None,
                generation=None, candidate=None, **changes):
        self.counter += 1
        req_id = request_id or "req-" + str(self.counter)
        asset = asset or "asset:" + req_id
        candidate = candidate or asset
        generation = generation or self.generations.get((r, candidate), 0) + 1
        self.generations[(r, candidate)] = generation
        requested = requested or ("6.25" if "_" in r else "25")
        request = CapitalRequest(req_id, EPOCH, round_id, r, candidate, generation, "0" * 64,
            requested, requested, requested, requested, requested, "0", "0", self.valuation())
        if "_" in r:
            with arithmetic():
                state = self.authority.snapshot()["ledger"]
                request = replace(request, native_sizing=dict(realized_equity_units=int(max(money("0"), _size_equity(state, r)) / UNIT),
                    usd_per_native_unit=amount(UNIT), journal_sha256=digest([r, "realized-native-fixture"])))
        request = replace(request, **changes)
        if request.kind == "scale":
            p = self.authority.snapshot()["ledger"]["positions"][request.lifecycle_id]
            request = replace(request, scale_state=dict(request.scale_state, original_basis=p["original_native_basis"]))
        evidence = dict(existing_strategy_evidence=True,
            capital_request={k: request.value(self.at)[k] for k in CAPITAL_FIELDS})
        if request.kind == "scale":
            evidence.update(scale_state=request.scale_state, scale_facts=request.scale_facts)
        receipt = self.authority.observe(operation_id="observe:" + req_id, at=self.at, regime_name=r,
            candidate_id=candidate, generation=generation, status="QUALIFIED", economic_keys=[asset],
            evidence=evidence, policy_hash=CONTRACTS[r]["policy_hash"])
        return replace(request, qualification_sha256=receipt["qualification_sha256"])

    def allocate(self, specs, *, round_id=None):
        self.counter += 1
        round_id = round_id or "round-" + str(self.counter)
        requests = [self.prepare(r, round_id=round_id, **kwargs) for r, kwargs in specs]
        self.authority.open_round(operation_id="open:" + round_id, round_id=round_id, at=self.at, cutoff=self.at)
        for request in requests:
            self.authority.submit(request, at=self.at)
        self.finish_round(round_id, requests)
        result = self.authority.allocate(round_id=round_id, at=self.at)
        return requests, result

    def finish_round(self, round_id, requests):
        for r in REGIMES:
            self.authority.seal(operation_id="seal:" + round_id + ":" + r, round_id=round_id,
                regime_name=r, request_ids=[q.request_id for q in requests if q.regime == r], at=self.at)

    def fill(self, request, *, cost="0", included_cost="0", mark=True):
        decision = self.authority.snapshot()["ledger"]["requests"][request.request_id]["decision"]
        life = request.lifecycle_id or "life:" + request.request_id
        result = self.authority.consume(operation_id="consume:" + request.request_id, request_id=request.request_id,
            lifecycle_id=life, basis=decision["basis"], cost=cost, included_cost=included_cost, at=self.at,
            native=self.native(request.regime, life), valuation=self.valuation(),
            native_basis_units=int(Fraction(money(decision["basis"])) / Fraction(money(request.native_sizing["usd_per_native_unit"]))) if "_" in request.regime else None)
        if mark:
            self.mark(request.regime, life)
        return life, result

    def mark(self, r, life, value=None):
        native = self.native(r, life)
        p = self.authority.snapshot()["ledger"]["positions"][life]
        return self.authority.mark(operation_id="mark:" + life + ":" + str(native["sequence"]),
            lifecycle_id=life, net_value=value or p["basis"], at=self.at, native=native, valuation=self.valuation())

    def realize(self, r, life, proceeds, *, released=None, terminal=True, cost="0", included_cost="0"):
        native = self.native(r, life)
        p = self.authority.snapshot()["ledger"]["positions"][life]
        return self.authority.realize(operation_id="realize:" + life + ":" + str(native["sequence"]),
            lifecycle_id=life, basis_released=released or p["basis"], gross_proceeds=proceeds,
            cost=cost, included_cost=included_cost, at=self.at, native=native, valuation=self.valuation(), terminal=terminal)

    @exact
    def check(self):
        snap = self.authority.snapshot()
        c = {k: money(v) for k, v in snap["capital"].items() if k != "conservation"}
        assert c["free_cash"] >= 0
        assert c["deployed_basis"] + c["active_reservations"] + c["pending_authoritative_commitments"] + c["required_funding_obligations"] <= c["authoritative_fundable_capital"]
        assert c["actual_cash"] + c["deployed_basis"] == c["realized_equity"]
        assert sum((money(row["realized_pnl"]) for row in snap["lanes"].values()), money("0")) - money(snap["ledger"]["shared_costs"]) + money(snap["ledger"]["initial_capital"]) == c["realized_equity"]
        return snap
