"""Read-only planning and atomic import of a preserved hard-sleeve PAPER epoch.

There is deliberately no runtime migration CLI. Call plan_migration only on a
verified isolated backup after the future operational candidate is accepted.
The source snapshot, mappings and pending delivery bodies are retained verbatim.
"""
from contextlib import closing
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import sqlite3

from meme_machine.exact_money import amount, exact, money
from meme_machine.portfolio_accounting import (PortfolioAccounting, _decode_checkpoint,
    _encode_checkpoint, validate_inception, digest as legacy_digest)
from .model import (CapitalError, FAMILIES, REGIMES, RiskPolicy, ZERO, checksum,
                    digest, identity, regime, second, wire)


def _seconds(utc):
    value = datetime.fromisoformat(utc.replace("Z", "+00:00"))
    if value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
        raise CapitalError("migration_utc_required")
    return int(value.timestamp())


def _keys(meta):
    keys = meta["economic_keys"]
    if not keys or len(set(keys)) != len(keys):
        raise CapitalError("migration_canonical_asset_mapping_required")
    return sorted(identity(k) for k in keys)


@exact
def plan_migration(database, mapping, policy=RiskPolicy()):
    """Replay a supplied backup through the existing accountant in a read snapshot.

    Does not construct a writer, checkpoint WAL, change a source table, establish
    an inception, acquire valuation, or recover delivery into the old accountant.
    """
    path = Path(database).resolve()
    if not path.is_file():
        raise CapitalError("existing_preserved_epoch_backup_required")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)) as db:
        db.execute("PRAGMA query_only=ON"); db.execute("BEGIN")
        reader = object.__new__(PortfolioAccounting)
        reader.db = db
        state = reader._replay()
        if state is None:
            raise CapitalError("existing_preserved_epoch_required")
        reader._reconcile(state)
        encoded = _encode_checkpoint(state)
        source = dict(replayed_state=encoded, replayed_sha256=legacy_digest(encoded),
            sequence=state["sequence"], journal_hash=state["journal_hash"],
            pending_deliveries=[dict(lane=l, native=n, body=json.loads(b)) for l, n, b in
                db.execute("SELECT lane,native,body FROM portfolio_native_pending ORDER BY lane,native")],
            native_ids=[list(row) for row in db.execute("SELECT * FROM portfolio_native_ids ORDER BY id")],
            native_alias_sequence=(db.execute("SELECT seq FROM sqlite_sequence WHERE name='portfolio_native_ids'").fetchone() or (0,))[0],
            sleeves=[list(row) for row in db.execute("SELECT * FROM portfolio_sleeves ORDER BY lane")])
    return make_plan(source, mapping, policy)


@exact
def make_plan(source, mapping, policy=RiskPolicy()):
    v = policy.value() if isinstance(policy, RiskPolicy) else RiskPolicy(**policy).value()
    source, mapping = wire(deepcopy(source)), wire(deepcopy(mapping))
    seed = _build_seed(source, mapping, v)
    body = dict(schema="meme-machine-shared-capital-migration-v1", paper_only=True,
                source=source, mapping=mapping, policy=v, seed=seed)
    return dict(body, migration_sha256=digest(body))


@exact
def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != {"schema", "paper_only", "source", "mapping", "policy", "seed", "migration_sha256"}:
        raise CapitalError("migration_plan_contract")
    if plan["schema"] != "meme-machine-shared-capital-migration-v1" or plan["paper_only"] is not True:
        raise CapitalError("paper_migration_plan_required")
    body = {k: v for k, v in plan.items() if k != "migration_sha256"}
    if digest(body) != checksum(plan["migration_sha256"]):
        raise CapitalError("migration_plan_checksum")
    policy = RiskPolicy(**plan["policy"]).value()
    # Existing journals predate these optional, zero-default new-risk floors.
    # Validate their original policy/hash verbatim; never rewrite a seed on replay.
    for key in ("cash_floor_bps", "transaction_cost_floor"):
        if key not in plan["policy"] and money(policy[key]) == ZERO:
            del policy[key]
    if policy != plan["policy"] or _build_seed(plan["source"], plan["mapping"], policy) != plan["seed"]:
        raise CapitalError("migration_seed_reconciliation_failure")
    return deepcopy(plan)


@exact
def _build_seed(source, mapping, policy):
    encoded = source["replayed_state"]
    if legacy_digest(encoded) != source["replayed_sha256"]:
        raise CapitalError("legacy_snapshot_checksum")
    old = _decode_checkpoint(encoded)
    validate_inception(old["receipt"])
    if legacy_digest(old["receipt"]) != old["receipt_hash"]:
        raise CapitalError("legacy_epoch_binding")
    if source["sequence"] != old["sequence"] or source["journal_hash"] != old["journal_hash"]:
        raise CapitalError("legacy_snapshot_frontier")
    reader = object.__new__(PortfolioAccounting)
    reader._reconcile(old)
    sleeves = {lane: money(genesis, positive=True) for lane, genesis in source["sleeves"]}
    if set(sleeves) != set(FAMILIES.values()) or sum(sleeves.values(), ZERO) != money(old["receipt"]["starting_capital"]):
        raise CapitalError("hard_sleeve_genesis_reconciliation")
    if set(mapping["contracts"]) != set(REGIMES):
        raise CapitalError("all_six_strategy_contracts_required")
    for r, contract in mapping["contracts"].items():
        identity(contract["strategy_id"]); checksum(contract["policy_hash"])
    if set(mapping["position_meta"]) != set(old["positions"]) or set(mapping["reservation_meta"]) != set(old["reservations"]):
        raise CapitalError("complete_position_and_reservation_inventory_required")
    at = _seconds(old["last_at"])
    seed = dict(epoch_id=old["receipt"]["epoch_id"], inception=deepcopy(old["receipt"]),
        inception_sha256=old["receipt_hash"], initial_capital=old["receipt"]["starting_capital"],
        at=at, policy=policy, contracts=mapping["contracts"], family_sizing_genesis=wire(sleeves),
        cash="0", realized={r: "0" for r in REGIMES}, costs={r: "0" for r in REGIMES},
        management_costs={r: "0" for r in REGIMES}, retired=deepcopy(mapping["retired"]),
        shared_costs=amount(old["shared_costs"]), capital_seconds={r: "0" for r in REGIMES},
        positions={}, reservations={}, commitments={}, obligations={}, discharged_obligations={},
        requests={}, request_identities={}, observations={}, rounds={}, native_cursors={}, native_deliveries={},
        pending_deliveries=deepcopy(source["pending_deliveries"]), pending_backing={},
        native_aliases={lane + ":" + native: lane + ":n" + str(alias) for alias, lane, native in source["native_ids"]},
        native_alias_sequence=source["native_alias_sequence"],
        retired_native_through=deepcopy(old["retired_native_through"]),
        samples={r: [] for r in REGIMES}, risk_high_water=old["receipt"]["starting_capital"],
        allocation=dict(multipliers={r: 10000 for r in REGIMES}, updated_at={r: at for r in REGIMES},
                        changes=[], change_count=0, scores={}),
        opportunity_totals={r: dict(observed=0, qualified=0, strategy_rejected=0, granted=0,
            qualified_but_unfunded=0, capital_granted="0", capital_denied="0", denials={}) for r in REGIMES},
        migration_source=deepcopy(source), migration_mapping=deepcopy(mapping))
    if set(seed["retired"]) != set(REGIMES):
        raise CapitalError("retired_regime_attribution_required")
    if (type(seed["native_alias_sequence"]) is not int or seed["native_alias_sequence"] < 0
            or any(alias > seed["native_alias_sequence"] for alias, _, _ in source["native_ids"])
            or len(seed["native_aliases"]) != len(source["native_ids"])):
        raise CapitalError("native_alias_identity_frontier")
    for family in sleeves:
        rows = [seed["retired"][r] for r in REGIMES if FAMILIES[r] == family]
        if (sum((money(row["pnl"]) for row in rows), ZERO) != old["retired"][family]["realized_pnl"]
                or sum((money(row["costs"], nonnegative=True) for row in rows), ZERO) != old["retired"][family]["fees"]
                or sum(row["count"] for row in rows) != old["retired"][family]["count"]):
            raise CapitalError("retired_history_cannot_be_rewritten")
    for r in REGIMES:
        seed["realized"][r] = amount(money(seed["retired"][r]["pnl"]))
        seed["costs"][r] = amount(money(seed["retired"][r]["costs"], nonnegative=True))
    for life, p in old["positions"].items():
        meta = mapping["position_meta"][life]
        r = regime(meta["regime"])
        if FAMILIES[r] != p["lane"] or mapping["contracts"][r]["strategy_id"] != p["strategy_id"]:
            raise CapitalError("position_strategy_or_family_mismatch")
        original = amount(meta["original_basis"], positive=True)
        if money(original) > p["capital"]:
            raise CapitalError("original_basis_exceeds_entered_capital")
        if type(meta["scale_committed"]) is not bool or type(meta["partials"]) is not int or meta["partials"] < 0:
            raise CapitalError("native_scaling_and_partial_inventory_required")
        capital_seconds = amount(meta["capital_seconds"], nonnegative=True)
        normalized = dict(id=life, regime=r, economic_keys=_keys(meta),
            status="OPEN" if p["state"] == "OPEN" else "SETTLED", basis=amount(p["remaining_basis"]),
            original_basis=original, capital_deployed=amount(p["capital"]), realized_pnl=amount(p["realized_pnl"]),
            gross_result=amount(p["gross_result"]), costs=amount(p["fees"]), capital_seconds=capital_seconds,
            accrued_at=at, opened_at=_seconds(p["entered_at"]), partials=meta["partials"],
            scale_committed=meta["scale_committed"], mark=None, strategy_id=p["strategy_id"],
            legacy_position=_encode_checkpoint(p))
        if "_" in r:
            original_native = meta["original_native_basis"]
            if type(original_native) is not int or original_native < 1:
                raise CapitalError("original_native_basis_inventory_required")
            normalized["original_native_basis"] = original_native
        mark = p.get("mark") or {}
        if mark.get("state") == "CURRENT":
            evidence = p["provenance"][-1]["value_evidence"]
            normalized["mark"] = dict(net_value=amount(mark["net_liquidation_value"]), valuation=dict(
                evidence_id=evidence["evidence_id"], evidence_sha256=evidence["evidence_sha256"], currency=evidence["currency"],
                as_of=_seconds(evidence["as_of"]), valid_until=_seconds(evidence["valid_until"])))
        if p["state"] == "SETTLED":
            normalized["settled_at"] = _seconds(p["settled_at"])
            # Unknown historical capital-time is not invented as confidence.
            if money(capital_seconds) > 0:
                seed["samples"][r].append(dict(at=normalized["settled_at"], pnl=normalized["realized_pnl"],
                    capital_deployed=normalized["capital_deployed"], capital_seconds=capital_seconds,
                    costs=normalized["costs"], lifecycle_id=life))
        seed["positions"][life] = normalized
        seed["realized"][r] = amount(money(seed["realized"][r]) + p["realized_pnl"])
        seed["costs"][r] = amount(money(seed["costs"][r]) + p["fees"])
        seed["capital_seconds"][r] = amount(money(seed["capital_seconds"][r]) + money(capital_seconds))
    cursor_mapping = mapping["cursor_mapping"]
    if set(cursor_mapping) != set(old["native_cursors"]):
        raise CapitalError("complete_native_cursor_inventory_required")
    for key, seq in old["native_cursors"].items():
        meta = cursor_mapping[key]
        r, life = regime(meta["regime"]), identity(meta["lifecycle_id"])
        if FAMILIES[r] != key.split(":", 1)[0] or r + ":" + life in seed["native_cursors"]:
            raise CapitalError("native_cursor_mapping_conflict")
        seed["native_cursors"][r + ":" + life] = seq
    def add_hold(req_id, meta, total, bucket):
        r = regime(meta["regime"])
        basis = amount(meta["basis"], nonnegative=True)
        cost = amount(meta["cost_headroom"], nonnegative=True)
        settlement = amount(meta["settlement_headroom"], nonnegative=True)
        if money(basis) + money(cost) + money(settlement) != money(total):
            raise CapitalError("migration_commitment_amount_mismatch")
        if req_id in seed["requests"]:
            raise CapitalError("duplicate_migrated_hold")
        hold = dict(regime=r, basis=basis, total=amount(total, positive=True), cost_headroom=cost,
                    settlement_headroom=settlement, economic_keys=_keys(meta),
                    lifecycle_id=meta.get("lifecycle_id"), created_at=at, migration=True)
        if hold["lifecycle_id"] is not None:
            identity(hold["lifecycle_id"])
        seed[bucket][req_id] = hold
        kind = meta["kind"]
        if kind not in ("new", "scale", "continuation", "safety"):
            raise CapitalError("migration_request_kind_required")
        native_sizing = meta.get("native_sizing")
        if "_" in r:
            if not isinstance(native_sizing, dict) or set(native_sizing) != {"realized_equity_units", "usd_per_native_unit", "journal_sha256"}:
                raise CapitalError("native_sizing_for_existing_commitment_required")
            if type(native_sizing["realized_equity_units"]) is not int or native_sizing["realized_equity_units"] < 0:
                raise CapitalError("native_sizing_for_existing_commitment_required")
            money(native_sizing["usd_per_native_unit"], positive=True); checksum(native_sizing["journal_sha256"])
        seed["requests"][req_id] = dict(status="RESERVED" if bucket == "reservations" else "COMMITTED",
            reason="PRESERVED_AUTHORITATIVE_COMMITMENT", value=dict(kind=kind, regime=r,
            candidate_id="legacy:" + req_id, generation=1, lifecycle_id=hold["lifecycle_id"], round_id="legacy", native_sizing=native_sizing))
    for req_id, hold in old["reservations"].items():
        meta = mapping["reservation_meta"][req_id]
        if FAMILIES[regime(meta["regime"])] != hold["lane"] or meta.get("lifecycle_id") != hold.get("lifecycle_id"):
            raise CapitalError("reservation_identity_cannot_change")
        add_hold(req_id, meta, hold["amount"], "reservations")
    pending_ids = {p["lane"] + ":" + p["native"] for p in source["pending_deliveries"]}
    if set(mapping["pending"]) != pending_ids:
        raise CapitalError("complete_pending_authority_inventory_required")
    for pending in source["pending_deliveries"]:
        key = pending["lane"] + ":" + pending["native"]
        meta = mapping["pending"][key]
        if FAMILIES[regime(meta["regime"])] != pending["lane"]:
            raise CapitalError("pending_regime_attribution_mismatch")
        backing = meta["backing"]
        if backing in ("reservation", "position"):
            bucket = seed["reservations"] if backing == "reservation" else seed["positions"]
            row = bucket.get(meta["backing_id"])
            if not row or row["regime"] != meta["regime"] or (backing == "position" and row["status"] != "OPEN"):
                raise CapitalError("pending_backing_missing_or_conflicting")
            if money(meta["additional_total"]) != 0:
                raise CapitalError("backed_pending_cannot_be_counted_twice")
        elif backing == "incremental":
            add_hold("legacy-pending:" + key, meta, meta["additional_total"], "commitments")
        else:
            raise CapitalError("unknown_pending_commitment_fails_closed")
        seed["pending_backing"][key] = deepcopy(meta)
    for obligation_id, obligation in mapping["obligations"].items():
        identity(obligation_id); regime(obligation["regime"]); checksum(obligation["proof_sha256"])
        obligation = dict(deepcopy(obligation), amount=amount(obligation["amount"], positive=True))
        seed["obligations"][obligation_id] = obligation
    seed["cash"] = amount(old["available"] + sum((h["amount"] for h in old["reservations"].values()), ZERO))
    from .authority import capital_view, risk_view
    capital_view(seed)
    risk = risk_view(seed, at)
    seed["risk_high_water"] = amount(max(money(seed["initial_capital"]), risk["marked_equity"] or ZERO))
    for r in REGIMES:
        seed["samples"][r] = sorted(seed["samples"][r], key=lambda s: (s["at"], s["lifecycle_id"]))[-policy["max_samples"]:]
    # Dollar-for-dollar and identity-for-identity reconciliation against source.
    if (sum((money(p["basis"]) for p in seed["positions"].values()), ZERO)
            != sum((p["remaining_basis"] for p in old["positions"].values()), ZERO)):
        raise CapitalError("migration_basis_mismatch")
    return wire(seed)
