"""Authoritative shared USD paper-portfolio accounting.

The portfolio starts only after an explicitly supplied immutable inception receipt.
This module never creates an epoch identity or timestamp, never acquires market data,
and has no strategy or execution authority.  Existing lane books remain native
evidence; canonical USD facts enter this journal only with explicit provenance and,
where a value depends on a mark or conversion, bounded USD value evidence.

The SQLite journal is authoritative.  The JSON receipt and dashboard export are
recoverable projections written atomically from the verified journal.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, localcontext
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading


SCHEMA_INCEPTION = "meme-machine-portfolio-inception-v1"
SCHEMA_EXPORT = "meme-machine-portfolio-export-v1"
LANES = ("pump", "pons", "ramses", "meteora")
STARTING_CAPITAL = Decimal("500.00")
ZERO_HASH = "0" * 64
MAX_POSITIONS = 5000
MAX_HISTORY_POINTS = 2000
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,120}")
_STRATEGY_ID = re.compile(r"[A-Za-z0-9_.:/-]{1,180}")
_MONEY = re.compile(r"-?\d{1,40}(?:\.\d{1,24})?")
_HASH = re.compile(r"[a-f0-9]{40}|[a-f0-9]{64}")


class PortfolioIntegrityError(RuntimeError):
    """A canonical portfolio fact is inconsistent, missing, or mutable."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _identity(value, *, strategy=False):
    pattern = _STRATEGY_ID if strategy else _ID
    if not isinstance(value, str) or "://" in value or not pattern.fullmatch(value):
        raise ValueError("invalid_identity")
    return value


def _hash(value, *, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError("invalid_hash_identity")
    return value


def _stamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("utc_timestamp_required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("utc_timestamp_required")
    return parsed.timestamp()


def _money(value, *, nonnegative=False, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("exact_decimal_required")
    text = format(value, "f") if isinstance(value, Decimal) else str(value)
    if len(text) > 70 or not _MONEY.fullmatch(text):
        raise ValueError("invalid_decimal")
    result = Decimal(text)
    if nonnegative and result < 0 or positive and result <= 0:
        raise ValueError("invalid_monetary_sign")
    return result


def _amount(value):
    return format(value, "f") if isinstance(value, Decimal) else format(_money(value), "f")


def inception_receipt(epoch_id, inception_at, canonical_event_id):
    """Validate caller-supplied inception facts without persisting them."""
    _stamp(inception_at)
    return {
        "schema": SCHEMA_INCEPTION,
        "epoch_id": _identity(epoch_id),
        "inception_at": inception_at,
        "canonical_event_id": _identity(canonical_event_id),
        "starting_capital": "500.00",
        "currency": "USD",
        "paper_only": True,
    }


def validate_inception(value):
    if not isinstance(value, dict):
        raise ValueError("inception_contract")
    try:
        expected = inception_receipt(
            value["epoch_id"], value["inception_at"], value["canonical_event_id"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("inception_contract") from error
    if value != expected:
        raise ValueError("inception_contract")
    return expected


def _safe_identities(values, *, require_source=True, require_policy=True, require_config=True):
    if not isinstance(values, dict):
        raise ValueError("identity_mapping_required")
    allowed = {"source_sha", "policy_hash", "config_hash", "source_diff_sha256", "strategy_id"}
    if set(values) - allowed:
        raise ValueError("unsafe_identity_field")
    result = {
        "source_sha": _hash(values.get("source_sha"), required=require_source),
        "policy_hash": _hash(values.get("policy_hash"), required=require_policy),
        "config_hash": _hash(values.get("config_hash"), required=require_config),
        "source_diff_sha256": _hash(values.get("source_diff_sha256"), required=False),
    }
    if values.get("strategy_id") is not None:
        result["strategy_id"] = _identity(values["strategy_id"], strategy=True)
    return {key: value for key, value in result.items() if value is not None}


def _provenance(value, at, *, valued):
    if not isinstance(value, dict):
        raise ValueError("canonical_provenance_required")
    allowed = {
        "source_event_id", "source_kind", "source_sha", "policy_hash", "config_hash",
        "source_diff_sha256", "native_lifecycle_id", "native_journal_hash",
        "native_event_sha256", "native_sequence", "value_evidence",
    }
    if set(value) - allowed:
        raise ValueError("unsafe_provenance_field")
    result = {
        "source_event_id": _identity(value.get("source_event_id")),
        "source_kind": _identity(value.get("source_kind")),
        "source_sha": _hash(value.get("source_sha")),
        "policy_hash": _hash(value.get("policy_hash")),
        "config_hash": _hash(value.get("config_hash")),
    }
    for key in ("source_diff_sha256", "native_journal_hash"):
        if value.get(key) is not None:
            result[key] = _hash(value[key])
    if value.get("native_event_sha256") is not None:
        result["native_event_sha256"] = _hash(value["native_event_sha256"])
    if value.get("native_sequence") is not None:
        sequence = value["native_sequence"]
        if type(sequence) is not int or sequence < 1:
            raise ValueError("native_sequence_required")
        result["native_sequence"] = sequence
    if value.get("native_lifecycle_id") is not None:
        result["native_lifecycle_id"] = _identity(value["native_lifecycle_id"])
    evidence = value.get("value_evidence")
    if valued and not isinstance(evidence, dict):
        raise ValueError("authoritative_usd_value_evidence_required")
    if evidence is not None:
        if not isinstance(evidence, dict) or set(evidence) != {
            "evidence_id", "evidence_sha256", "currency", "as_of", "valid_until"
        }:
            raise ValueError("usd_value_evidence_contract")
        observed, valid_until = _stamp(evidence["as_of"]), _stamp(evidence["valid_until"])
        if evidence["currency"] != "USD" or valid_until < observed or not observed <= _stamp(at) <= valid_until:
            raise ValueError("usd_value_evidence_stale_or_wrong_currency")
        result["value_evidence"] = {
            "evidence_id": _identity(evidence["evidence_id"]),
            "evidence_sha256": _hash(evidence["evidence_sha256"]),
            "currency": "USD",
            "as_of": evidence["as_of"],
            "valid_until": evidence["valid_until"],
        }
    return result


def _lane_state(lane, value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("lane_state_mapping_required")
    allowed = (
        {"harvest_state", "runner_state", "remaining_runner_exposure"}
        if lane == "pons" else
        {"range_id", "lp_state", "in_range", "rebalance_state"}
        if lane in ("ramses", "meteora") else set()
    )
    if set(value) - allowed:
        raise ValueError("unsupported_lane_state")
    result = {}
    for key in ("harvest_state", "runner_state", "range_id", "lp_state", "rebalance_state"):
        if value.get(key) is not None:
            result[key] = _identity(value[key])
    if "in_range" in value:
        if type(value["in_range"]) is not bool:
            raise ValueError("in_range_boolean_required")
        result["in_range"] = value["in_range"]
    if value.get("remaining_runner_exposure") is not None:
        result["remaining_runner_exposure"] = _amount(
            _money(value["remaining_runner_exposure"], nonnegative=True)
        )
    return result


def _atomic_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    raw = (canonical(value) + "\n").encode()
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


class PortfolioAccounting:
    """Single writer for one optional shared paper-portfolio epoch.

    Construction creates only the durable schema.  ``establish_inception`` is the
    separately authorized activation boundary and requires all real inception facts.
    """

    def __init__(self, database, *, receipt_path=None, export_path=None):
        self.path = Path(database)
        self.receipt_path = Path(receipt_path) if receipt_path is not None else None
        self.export_path = Path(export_path) if export_path is not None else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file = open(str(self.path) + ".lock", "a")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock_file.close()
            raise RuntimeError("portfolio_writer_already_running") from None
        try:
            self.db = sqlite3.connect(
                self.path, isolation_level=None, timeout=30, check_same_thread=False
            )
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS portfolio_inception(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    body TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    identities TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portfolio_events(
                    sequence INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    epoch_id TEXT NOT NULL,
                    at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    body TEXT NOT NULL,
                    previous TEXT NOT NULL,
                    hash TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS portfolio_inception_no_update
                    BEFORE UPDATE ON portfolio_inception BEGIN SELECT RAISE(ABORT,'immutable_inception'); END;
                CREATE TRIGGER IF NOT EXISTS portfolio_inception_no_delete
                    BEFORE DELETE ON portfolio_inception BEGIN SELECT RAISE(ABORT,'immutable_inception'); END;
                CREATE TRIGGER IF NOT EXISTS portfolio_events_no_update
                    BEFORE UPDATE ON portfolio_events BEGIN SELECT RAISE(ABORT,'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS portfolio_events_no_delete
                    BEFORE DELETE ON portfolio_events BEGIN SELECT RAISE(ABORT,'append_only'); END;
            """)
            self._mutex = threading.RLock()
            self.projection_error = None
            self._state = self._replay()
            try:
                self.recover_projections()
            except (OSError, ValueError, PortfolioIntegrityError) as error:
                # A dashboard projection cannot prevent canonical paper accounting.
                self.projection_error = str(error)
        except BaseException:
            if hasattr(self, "db"):
                self.db.close()
            self._lock_file.close()
            raise

    def close(self):
        self._replay()
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.close()
        self._lock_file.close()

    @contextmanager
    def transaction(self):
        with self._mutex:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def _inception(self):
        row = self.db.execute(
            "SELECT body,sha256,identities FROM portfolio_inception WHERE id=1"
        ).fetchone()
        if row is None:
            return None
        receipt = validate_inception(json.loads(row[0]))
        if digest(receipt) != row[1]:
            raise PortfolioIntegrityError("inception_hash_mismatch")
        identities = json.loads(row[2])
        portfolio = _safe_identities(identities["portfolio"])
        lanes = identities["lanes"]
        if set(lanes) != set(LANES):
            raise PortfolioIntegrityError("lane_identity_coverage")
        lanes = {lane: _safe_identities(lanes[lane], require_policy=True) for lane in LANES}
        return receipt, row[1], {"portfolio": portfolio, "lanes": lanes}

    def status(self):
        value = self._inception()
        if value is None:
            return {"state": "NOT_INITIALIZED", "paper_only": True, "starting_capital": "500.00"}
        state = deepcopy(self._state)
        projection_state = (
            "FAIL_CLOSED" if self.projection_error is not None
            else "CURRENT" if state["last_publish"] is not None
            else "UNAVAILABLE"
        )
        return {
            "state": "CURRENT",
            "projection_state": projection_state,
            "projection_error": self.projection_error,
            "paper_only": True,
            "epoch_id": value[0]["epoch_id"],
            "inception_sha256": value[1],
            "sequence": state["sequence"],
        }

    def binding(self):
        """Return the immutable epoch/source binding without exposing writer state."""
        value = self._inception()
        if value is None:
            return None
        receipt, receipt_hash, identities = value
        return {
            "receipt": deepcopy(receipt),
            "inception_sha256": receipt_hash,
            "identities": deepcopy(identities),
        }

    def canonical_event(self, event_id):
        """Return one immutable journal event for delivery-idempotency checks."""
        event_id = _identity(event_id)
        row = self.db.execute(
            "SELECT sequence,body,hash FROM portfolio_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            body = json.loads(row[1], parse_float=Decimal)
        except (ValueError, TypeError) as error:
            raise PortfolioIntegrityError("portfolio_journal_json") from error
        return {"sequence": row[0], "body": body, "hash": row[2]}

    def canonical_events(self):
        """Return immutable journal events in canonical order for adapter recovery."""
        rows = []
        for sequence, raw, checksum in self.db.execute(
            "SELECT sequence,body,hash FROM portfolio_events ORDER BY sequence"
        ):
            try:
                body = json.loads(raw, parse_float=Decimal)
            except (ValueError, TypeError) as error:
                raise PortfolioIntegrityError("portfolio_journal_json") from error
            rows.append({"sequence": sequence, "body": body, "hash": checksum})
        return rows

    def snapshot(self):
        """Return a defensive copy of replayed canonical state for integration receipts."""
        return deepcopy(self._state)

    def establish_inception(self, receipt, *, portfolio_identities, lane_identities):
        """Persist the one immutable inception. Never called automatically."""
        value = validate_inception(receipt)
        if self._inception() is not None:
            current = self._inception()[0]
            reason = "duplicate_inception" if current == value else "conflicting_inception"
            raise PortfolioIntegrityError(reason)
        if self.db.execute("SELECT 1 FROM portfolio_events LIMIT 1").fetchone():
            raise PortfolioIntegrityError("events_without_inception")
        for path in (self.receipt_path, self.export_path):
            if path is not None and path.exists():
                raise PortfolioIntegrityError("orphan_projection_refused")
        portfolio = _safe_identities(portfolio_identities)
        if set(lane_identities) != set(LANES):
            raise ValueError("all_lane_identities_required")
        lanes = {lane: _safe_identities(lane_identities[lane], require_policy=True) for lane in LANES}
        identities = {"portfolio": portfolio, "lanes": lanes}
        receipt_hash = digest(value)
        body = {
            "action": "inception",
            "event_id": value["canonical_event_id"],
            "epoch_id": value["epoch_id"],
            "at": value["inception_at"],
            "data": {"inception_sha256": receipt_hash},
        }
        checksum = hashlib.sha256((ZERO_HASH + canonical(body)).encode()).hexdigest()
        established = None
        with self.transaction():
            self.db.execute(
                "INSERT INTO portfolio_inception VALUES(1,?,?,?)",
                (canonical(value), receipt_hash, canonical(identities)),
            )
            self.db.execute(
                "INSERT INTO portfolio_events VALUES(?,?,?,?,?,?,?,?)",
                (1, body["event_id"], body["epoch_id"], body["at"], body["action"],
                 canonical(body), ZERO_HASH, checksum),
            )
            established = self._replay()
        self._state = established
        self.recover_projections()
        return receipt_hash

    def _blank_state(self, receipt, receipt_hash, identities):
        initial_history = [
            {"epoch_id": receipt["epoch_id"], "series": "portfolio", "at": receipt["inception_at"], "value": "500.00"},
            *({"epoch_id": receipt["epoch_id"], "series": lane, "at": receipt["inception_at"], "value": "0"}
              for lane in LANES),
        ]
        return {
            "receipt": receipt,
            "receipt_hash": receipt_hash,
            "identities": identities,
            "available": STARTING_CAPITAL,
            "reservations": {},
            "positions": {},
            "shared_costs": Decimal(0),
            "history": initial_history,
            "history_coverage_through": None,
            "last_at": receipt["inception_at"],
            "last_publish": None,
            "sequence": 0,
            "journal_hash": ZERO_HASH,
        }

    def _replay(self):
        inception = self._inception()
        count = self.db.execute("SELECT COUNT(*) FROM portfolio_events").fetchone()[0]
        if inception is None:
            if count:
                raise PortfolioIntegrityError("events_without_inception")
            return None
        state = self._blank_state(*inception)
        previous = ZERO_HASH
        for sequence, event_id, epoch_id, at, action, raw, parent, checksum in self.db.execute(
            "SELECT sequence,event_id,epoch_id,at,action,body,previous,hash "
            "FROM portfolio_events ORDER BY sequence"
        ):
            try:
                body = json.loads(raw, parse_float=Decimal)
            except (ValueError, TypeError) as error:
                raise PortfolioIntegrityError("portfolio_journal_json") from error
            if (
                sequence != state["sequence"] + 1
                or parent != previous
                or checksum != hashlib.sha256((parent + canonical(body)).encode()).hexdigest()
                or body.get("event_id") != event_id
                or body.get("epoch_id") != epoch_id
                or body.get("at") != at
                or body.get("action") != action
            ):
                raise PortfolioIntegrityError("portfolio_journal_integrity")
            self._apply(state, body)
            state["sequence"], state["journal_hash"] = sequence, checksum
            previous = checksum
            self._reconcile(state)
        if state["sequence"] != count:
            raise PortfolioIntegrityError("portfolio_sequence_gap")
        return state

    def _require_epoch(self, state, epoch_id, at):
        if epoch_id != state["receipt"]["epoch_id"]:
            raise PortfolioIntegrityError("cross_epoch_fact")
        when = _stamp(at)
        if when < _stamp(state["receipt"]["inception_at"]):
            raise PortfolioIntegrityError("pre_inception_fact")
        if when < _stamp(state["last_at"]):
            raise PortfolioIntegrityError("portfolio_time_regression")

    @staticmethod
    def _event_provenance(state, data, at, *, valued, lane=None):
        supplied = data.get("provenance")
        checked = _provenance(supplied, at, valued=valued)
        if checked != supplied:
            raise PortfolioIntegrityError("noncanonical_provenance")
        expected = state["identities"]["lanes"].get(lane) if lane else state["identities"]["portfolio"]
        for key in ("source_sha", "policy_hash", "config_hash", "source_diff_sha256"):
            if expected.get(key) is not None and checked.get(key) != expected[key]:
                raise PortfolioIntegrityError("canonical_source_or_config_mismatch")
        return checked

    def _apply(self, state, event):
        action, data = event["action"], event["data"]
        self._require_epoch(state, event["epoch_id"], event["at"])
        if action not in ("inception", "publish"):
            # A prior file remains a valid historical snapshot, but it is no
            # longer the projection of the journal head.
            state["last_publish"] = None
        if action == "inception":
            if state["sequence"] != 0 or event["event_id"] != state["receipt"]["canonical_event_id"]:
                raise PortfolioIntegrityError("inception_event_position")
            if data != {"inception_sha256": state["receipt_hash"]}:
                raise PortfolioIntegrityError("inception_event_binding")
        elif action == "reserve":
            reservation_id = _identity(data["reservation_id"])
            if reservation_id in state["reservations"]:
                raise PortfolioIntegrityError("duplicate_reservation")
            amount = _money(data["amount"], positive=True)
            if amount > state["available"]:
                raise PortfolioIntegrityError("portfolio_capital_exhausted")
            lane = data["lane"]
            if lane not in LANES:
                raise ValueError("unknown_lane")
            self._event_provenance(state, data, event["at"], valued=False, lane=lane)
            state["available"] -= amount
            state["reservations"][reservation_id] = {
                "id": reservation_id, "lane": lane, "amount": amount,
                "lifecycle_id": data.get("lifecycle_id"), "at": event["at"],
            }
        elif action == "release_reservation":
            reservation = self._reservation(state, data["reservation_id"])
            self._event_provenance(
                state, data, event["at"], valued=False, lane=reservation["lane"]
            )
            state["available"] += reservation["amount"]
            del state["reservations"][reservation["id"]]
        elif action == "enter":
            self._apply_enter(state, event)
        elif action in ("partial_realization", "harvest", "settle"):
            self._apply_realization(state, event)
        elif action == "rebalance":
            self._apply_rebalance(state, event)
        elif action == "mark":
            position = self._open_position(state, data["lifecycle_id"])
            mark = data["mark"]
            provenance = self._event_provenance(
                state, data, event["at"], valued=mark["state"] == "CURRENT", lane=position["lane"]
            )
            if mark["state"] == "CURRENT":
                value = _money(mark["net_liquidation_value"], nonnegative=True)
                observed, valid_until = _stamp(mark["as_of"]), _stamp(mark["valid_until"])
                if not _stamp(position["entered_at"]) <= observed <= _stamp(event["at"]) <= valid_until:
                    raise PortfolioIntegrityError("mark_time_or_freshness")
                position["mark"] = {
                    "state": "CURRENT", "net_liquidation_value": _amount(value),
                    "as_of": mark["as_of"], "valid_until": mark["valid_until"],
                }
            elif mark["state"] in ("STALE", "UNAVAILABLE", "FAIL_CLOSED", "UNKNOWN"):
                position["mark"] = {"state": mark["state"]}
            else:
                raise ValueError("invalid_mark_state")
            position.update(_lane_state(position["lane"], data.get("lane_state")))
            position["provenance"].append(provenance)
            position["lifecycle"].append({"stage": "monitoring", "at": event["at"]})
        elif action == "shared_cost":
            self._event_provenance(state, data, event["at"], valued=True)
            amount = _money(data["amount"], positive=True)
            if amount > state["available"]:
                raise PortfolioIntegrityError("shared_cost_exceeds_available_cash")
            state["available"] -= amount
            state["shared_costs"] += amount
        elif action == "history_sample":
            expected = self._history_rows(state, event["at"])
            if data.get("rows") != expected:
                raise PortfolioIntegrityError("history_sample_not_derived")
            existing = {(row["series"], row["at"]) for row in state["history"]}
            if any((row["series"], row["at"]) in existing for row in expected):
                raise PortfolioIntegrityError("duplicate_history_sample")
            if len(state["history"]) + len(expected) > MAX_HISTORY_POINTS:
                raise PortfolioIntegrityError("history_capacity")
            state["history"].extend(expected)
            if data.get("complete") is True:
                if any(row["value"] is None for row in expected):
                    raise PortfolioIntegrityError("incomplete_history_declared_complete")
                state["history_coverage_through"] = event["at"]
        elif action == "publish":
            if _stamp(data["valid_until"]) < _stamp(event["at"]):
                raise PortfolioIntegrityError("export_validity_regression")
            state["last_publish"] = {"as_of": event["at"], "valid_until": data["valid_until"]}
        else:
            raise PortfolioIntegrityError("unknown_portfolio_action")
        state["last_at"] = event["at"]

    @staticmethod
    def _reservation(state, reservation_id):
        reservation_id = _identity(reservation_id)
        try:
            return state["reservations"][reservation_id]
        except KeyError as error:
            raise PortfolioIntegrityError("reservation_missing") from error

    @staticmethod
    def _position(state, lifecycle_id):
        lifecycle_id = _identity(lifecycle_id)
        try:
            return state["positions"][lifecycle_id]
        except KeyError as error:
            raise PortfolioIntegrityError("lifecycle_missing") from error

    def _open_position(self, state, lifecycle_id):
        position = self._position(state, lifecycle_id)
        if position["state"] != "OPEN":
            raise PortfolioIntegrityError("terminal_lifecycle_immutable")
        return position

    def _apply_enter(self, state, event):
        data = event["data"]
        lifecycle_id = _identity(data["lifecycle_id"])
        if lifecycle_id in state["positions"]:
            raise PortfolioIntegrityError("duplicate_entered_lifecycle")
        if len(state["positions"]) >= MAX_POSITIONS:
            raise PortfolioIntegrityError("position_capacity")
        reservation = self._reservation(state, data["reservation_id"])
        if reservation["lane"] != data["lane"] or reservation.get("lifecycle_id") not in (None, lifecycle_id):
            raise PortfolioIntegrityError("reservation_lifecycle_mismatch")
        basis = _money(data["basis"], positive=True)
        fee = _money(data["fee"], nonnegative=True)
        if reservation["amount"] < basis + fee:
            raise PortfolioIntegrityError("entry_reservation_underfunded")
        state["available"] += reservation["amount"] - basis - fee
        del state["reservations"][reservation["id"]]
        stages = []
        for stage in data.get("prior_stages", []):
            if stage["stage"] not in ("qualification", "authorization"):
                raise ValueError("unsupported_prior_stage")
            if not _stamp(state["receipt"]["inception_at"]) <= _stamp(stage["at"]) <= _stamp(event["at"]):
                raise PortfolioIntegrityError("prior_stage_outside_epoch")
            stages.append({"stage": stage["stage"], "at": stage["at"]})
        stages.append({"stage": "paper_entry", "at": event["at"]})
        provenance = data["provenance"]
        lane = data["lane"]
        provenance = self._event_provenance(
            state, data, event["at"], valued=True, lane=lane
        )
        state["positions"][lifecycle_id] = {
            "epoch_id": state["receipt"]["epoch_id"],
            "id": lifecycle_id,
            "lane": lane,
            "asset": _identity(data["asset"]),
            "exposure_entered": True,
            "state": "OPEN",
            "entered_at": event["at"],
            "settled_at": None,
            "capital": basis,
            "remaining_basis": basis,
            "realized_pnl": -fee,
            "fees": fee,
            "gross_result": Decimal(0),
            "entry_value": basis,
            "exit_value": None,
            "gross_proceeds": Decimal(0),
            "strategy_id": data["strategy_id"],
            "source_sha": provenance["source_sha"],
            "policy_hash": provenance["policy_hash"],
            "config_hash": provenance["config_hash"],
            "source_diff_sha256": provenance.get("source_diff_sha256"),
            "mark": {"state": "UNAVAILABLE"},
            "lifecycle": stages,
            "rebalance_count": 0,
            "provenance": [provenance],
            **_lane_state(lane, data.get("lane_state")),
        }

    def _apply_realization(self, state, event):
        data, action = event["data"], event["action"]
        position = self._open_position(state, data["lifecycle_id"])
        provenance = self._event_provenance(
            state, data, event["at"], valued=True, lane=position["lane"]
        )
        released = _money(data["basis_released"], positive=True)
        gross_proceeds = _money(data["gross_proceeds"], nonnegative=True)
        fee = _money(data["fee"], nonnegative=True)
        if released > position["remaining_basis"]:
            raise PortfolioIntegrityError("basis_release_exceeds_position")
        if action == "settle" and released != position["remaining_basis"]:
            raise PortfolioIntegrityError("terminal_settlement_requires_all_basis")
        if action != "settle" and released == position["remaining_basis"]:
            raise PortfolioIntegrityError("nonterminal_realization_removed_all_exposure")
        net_proceeds = gross_proceeds - fee
        if net_proceeds < 0:
            raise PortfolioIntegrityError("fees_exceed_proceeds")
        state["available"] += net_proceeds
        position["remaining_basis"] -= released
        position["gross_proceeds"] += gross_proceeds
        position["gross_result"] += gross_proceeds - released
        position["fees"] += fee
        position["realized_pnl"] += gross_proceeds - released - fee
        position["provenance"].append(provenance)
        position["lifecycle"].append({
            "stage": "partial_realization" if action in ("partial_realization", "harvest") else "exit",
            "at": event["at"],
        })
        if action == "harvest":
            position["harvest_state"] = "HARVESTED"
            position["runner_state"] = "ACTIVE"
            position["remaining_runner_exposure"] = position["remaining_basis"]
            position["lifecycle"].append({"stage": "runner", "at": event["at"]})
        if action == "settle":
            position.update(
                state="SETTLED", settled_at=event["at"], mark=None,
                exit_value=position["gross_proceeds"], exit_reason=_identity(data["exit_reason"]),
            )
            position.pop("remaining_runner_exposure", None)
            if position.get("runner_state"):
                position["runner_state"] = "SETTLED"
            position["lifecycle"].append({"stage": "settlement", "at": event["at"]})

    def _apply_rebalance(self, state, event):
        data = event["data"]
        position = self._open_position(state, data["lifecycle_id"])
        provenance = self._event_provenance(
            state, data, event["at"], valued=True, lane=position["lane"]
        )
        reservation = self._reservation(state, data["reservation_id"])
        if reservation["lane"] != position["lane"] or reservation.get("lifecycle_id") not in (None, position["id"]):
            raise PortfolioIntegrityError("rebalance_reservation_mismatch")
        released = _money(data["basis_released"], nonnegative=True)
        gross_proceeds = _money(data["gross_proceeds"], nonnegative=True)
        added = _money(data["basis_added"], nonnegative=True)
        fee = _money(data["fee"], nonnegative=True)
        if released > position["remaining_basis"] or added <= 0 and released <= 0:
            raise PortfolioIntegrityError("invalid_rebalance_basis")
        if reservation["amount"] < added + fee:
            raise PortfolioIntegrityError("rebalance_reservation_underfunded")
        if gross_proceeds < fee:
            # The reserved fee pays the fee; proceeds may be zero. Keep this branch
            # explicit to prevent subtracting the same fee from both pools of cash.
            pass
        state["available"] += reservation["amount"] - added - fee + gross_proceeds
        del state["reservations"][reservation["id"]]
        position["remaining_basis"] += added - released
        if position["remaining_basis"] <= 0:
            raise PortfolioIntegrityError("rebalance_cannot_terminally_remove_exposure")
        position["capital"] += added
        position["gross_proceeds"] += gross_proceeds
        position["gross_result"] += gross_proceeds - released
        position["fees"] += fee
        position["realized_pnl"] += gross_proceeds - released - fee
        position["rebalance_count"] += 1
        position["rebalance_state"] = "MONITORING"
        position.update(_lane_state(position["lane"], data.get("lane_state")))
        position["provenance"].append(provenance)
        position["lifecycle"].append({"stage": "rebalance", "at": event["at"]})

    def _reconcile(self, state):
        with localcontext() as context:
            context.prec = 80
            positions = list(state["positions"].values())
            lane_realized = sum((row["realized_pnl"] for row in positions), Decimal(0))
            realized = lane_realized - state["shared_costs"]
            reserved = sum((row["amount"] for row in state["reservations"].values()), Decimal(0))
            deployed = sum((row["remaining_basis"] for row in positions if row["state"] == "OPEN"), Decimal(0))
            attributable_fees = sum((row["fees"] for row in positions), Decimal(0))
            if min(state["available"], reserved, deployed, attributable_fees, state["shared_costs"]) < 0:
                raise PortfolioIntegrityError("negative_portfolio_component")
            checks = {
                "lane_realized_less_shared_costs": lane_realized - state["shared_costs"] == realized,
                "remaining_basis": deployed == sum(
                    (row["remaining_basis"] for row in positions if row["state"] == "OPEN"), Decimal(0)
                ),
                "cash_basis_conservation": state["available"] + reserved + deployed == STARTING_CAPITAL + realized,
                "cost_attribution": attributable_fees + state["shared_costs"] == attributable_fees + state["shared_costs"],
            }
            if not all(checks.values()):
                raise PortfolioIntegrityError("portfolio_reconciliation_failure")
            for row in positions:
                if row["gross_result"] - row["fees"] != row["realized_pnl"]:
                    raise PortfolioIntegrityError("position_gross_net_cost_mismatch")
                if row["state"] == "SETTLED" and row["remaining_basis"] != 0:
                    raise PortfolioIntegrityError("terminal_remaining_basis")
                if row["state"] == "OPEN" and row["remaining_basis"] <= 0:
                    raise PortfolioIntegrityError("open_without_basis")
            return {
                "lane_realized": lane_realized,
                "realized": realized,
                "reserved": reserved,
                "deployed": deployed,
                "attributable_fees": attributable_fees,
                "total_fees": attributable_fees + state["shared_costs"],
                "checks": checks,
            }

    def _append(self, *, epoch_id, event_id, at, action, data):
        event_id = _identity(event_id)
        _stamp(at)
        with self.transaction():
            state = deepcopy(self._state)
            if state is None:
                raise PortfolioIntegrityError("portfolio_not_initialized")
            if self.db.execute("SELECT 1 FROM portfolio_events WHERE event_id=?", (event_id,)).fetchone():
                raise PortfolioIntegrityError("duplicate_canonical_event")
            body = {"action": action, "event_id": event_id, "epoch_id": epoch_id, "at": at, "data": data}
            self._apply(state, body)
            self._reconcile(state)
            sequence = state["sequence"] + 1
            checksum = hashlib.sha256((state["journal_hash"] + canonical(body)).encode()).hexdigest()
            self.db.execute(
                "INSERT INTO portfolio_events VALUES(?,?,?,?,?,?,?,?)",
                (sequence, event_id, epoch_id, at, action, canonical(body), state["journal_hash"], checksum),
            )
            state["sequence"], state["journal_hash"] = sequence, checksum
        self._state = state
        return state

    def reserve(self, *, epoch_id, event_id, reservation_id, lane, amount, at, provenance, lifecycle_id=None):
        data = {
            "reservation_id": _identity(reservation_id),
            "lane": lane,
            "amount": _amount(_money(amount, positive=True)),
            "lifecycle_id": _identity(lifecycle_id) if lifecycle_id is not None else None,
            "provenance": _provenance(provenance, at, valued=False),
        }
        return self._append(epoch_id=epoch_id, event_id=event_id, at=at, action="reserve", data=data)

    def release_reservation(self, *, epoch_id, event_id, reservation_id, at, provenance):
        data = {
            "reservation_id": _identity(reservation_id),
            "provenance": _provenance(provenance, at, valued=False),
        }
        return self._append(epoch_id=epoch_id, event_id=event_id, at=at, action="release_reservation", data=data)

    def enter(self, *, epoch_id, event_id, reservation_id, lifecycle_id, lane, asset, basis,
              fee, at, strategy_id, provenance, prior_stages=(), lane_state=None):
        if lane not in LANES:
            raise ValueError("unknown_lane")
        data = {
            "reservation_id": _identity(reservation_id),
            "lifecycle_id": _identity(lifecycle_id),
            "lane": lane,
            "asset": _identity(asset),
            "basis": _amount(_money(basis, positive=True)),
            "fee": _amount(_money(fee, nonnegative=True)),
            "strategy_id": _identity(strategy_id, strategy=True),
            "prior_stages": list(prior_stages),
            "lane_state": _lane_state(lane, lane_state),
            "provenance": _provenance(provenance, at, valued=True),
        }
        return self._append(epoch_id=epoch_id, event_id=event_id, at=at, action="enter", data=data)

    def realize(self, *, epoch_id, event_id, lifecycle_id, basis_released, gross_proceeds,
                fee, at, provenance, harvest=False):
        action = "harvest" if harvest else "partial_realization"
        data = {
            "lifecycle_id": _identity(lifecycle_id),
            "basis_released": _amount(_money(basis_released, positive=True)),
            "gross_proceeds": _amount(_money(gross_proceeds, nonnegative=True)),
            "fee": _amount(_money(fee, nonnegative=True)),
            "provenance": _provenance(provenance, at, valued=True),
        }
        return self._append(epoch_id=epoch_id, event_id=event_id, at=at, action=action, data=data)

    def rebalance(self, *, epoch_id, event_id, lifecycle_id, reservation_id, basis_released,
                  gross_proceeds, basis_added, fee, at, provenance, lane_state=None):
        current = deepcopy(self._state)
        if current is None:
            raise PortfolioIntegrityError("portfolio_not_initialized")
        lane = self._open_position(current, lifecycle_id)["lane"]
        data = {
            "lifecycle_id": _identity(lifecycle_id),
            "reservation_id": _identity(reservation_id),
            "basis_released": _amount(_money(basis_released, nonnegative=True)),
            "gross_proceeds": _amount(_money(gross_proceeds, nonnegative=True)),
            "basis_added": _amount(_money(basis_added, nonnegative=True)),
            "fee": _amount(_money(fee, nonnegative=True)),
            "lane_state": _lane_state(lane, lane_state),
            "provenance": _provenance(provenance, at, valued=True),
        }
        return self._append(epoch_id=epoch_id, event_id=event_id, at=at, action="rebalance", data=data)

    def settle(self, *, epoch_id, event_id, lifecycle_id, gross_proceeds, fee, exit_reason, at, provenance):
        state = deepcopy(self._state)
        if state is None:
            raise PortfolioIntegrityError("portfolio_not_initialized")
        position = self._open_position(state, lifecycle_id)
        data = {
            "lifecycle_id": _identity(lifecycle_id),
            "basis_released": _amount(position["remaining_basis"]),
            "gross_proceeds": _amount(_money(gross_proceeds, nonnegative=True)),
            "fee": _amount(_money(fee, nonnegative=True)),
            "exit_reason": _identity(exit_reason),
            "provenance": _provenance(provenance, at, valued=True),
        }
        return self._append(epoch_id=epoch_id, event_id=event_id, at=at, action="settle", data=data)

    def mark(self, *, epoch_id, event_id, lifecycle_id, at, provenance, state,
             net_liquidation_value=None, as_of=None, valid_until=None, lane_state=None):
        if state == "CURRENT":
            mark = {
                "state": "CURRENT",
                "net_liquidation_value": _amount(_money(net_liquidation_value, nonnegative=True)),
                "as_of": as_of,
                "valid_until": valid_until,
            }
            if provenance.get("value_evidence") != {
                "evidence_id": provenance.get("value_evidence", {}).get("evidence_id"),
                "evidence_sha256": provenance.get("value_evidence", {}).get("evidence_sha256"),
                "currency": "USD", "as_of": as_of, "valid_until": valid_until,
            }:
                raise ValueError("mark_and_value_evidence_disagree")
            source = _provenance(provenance, at, valued=True)
        elif state in ("STALE", "UNAVAILABLE", "FAIL_CLOSED", "UNKNOWN"):
            mark = {"state": state}
            source = _provenance(provenance, at, valued=False)
        else:
            raise ValueError("invalid_mark_state")
        current = deepcopy(self._state)
        if current is None:
            raise PortfolioIntegrityError("portfolio_not_initialized")
        lane = self._open_position(current, lifecycle_id)["lane"]
        data = {
            "lifecycle_id": _identity(lifecycle_id), "mark": mark,
            "lane_state": _lane_state(lane, lane_state), "provenance": source,
        }
        return self._append(epoch_id=epoch_id, event_id=event_id, at=at, action="mark", data=data)

    def charge_shared_cost(self, *, epoch_id, event_id, amount, at, provenance):
        data = {
            "amount": _amount(_money(amount, positive=True)),
            "provenance": _provenance(provenance, at, valued=True),
        }
        return self._append(epoch_id=epoch_id, event_id=event_id, at=at, action="shared_cost", data=data)

    def _values_at(self, state, at):
        reconciliation = self._reconcile(state)
        unrealized = Decimal(0)
        lane_values = {lane: Decimal(0) for lane in LANES}
        available = True
        for row in state["positions"].values():
            lane_values[row["lane"]] += row["realized_pnl"]
            if row["state"] != "OPEN":
                continue
            mark = row.get("mark") or {"state": "UNAVAILABLE"}
            if mark.get("state") != "CURRENT" or _stamp(at) > _stamp(mark["valid_until"]):
                available = False
                continue
            delta = _money(mark["net_liquidation_value"]) - row["remaining_basis"]
            unrealized += delta
            lane_values[row["lane"]] += delta
        equity = STARTING_CAPITAL + reconciliation["realized"] + unrealized if available else None
        return equity, lane_values if available else None, unrealized if available else None

    def _history_rows(self, state, at):
        equity, lanes, _ = self._values_at(state, at)
        rows = [{
            "epoch_id": state["receipt"]["epoch_id"], "series": "portfolio", "at": at,
            "value": _amount(equity) if equity is not None else None,
        }]
        for lane in LANES:
            rows.append({
                "epoch_id": state["receipt"]["epoch_id"], "series": lane, "at": at,
                "value": _amount(lanes[lane]) if lanes is not None else None,
            })
        return rows

    def record_history_sample(self, *, epoch_id, event_id, at, complete=False):
        state = deepcopy(self._state)
        if state is None:
            raise PortfolioIntegrityError("portfolio_not_initialized")
        self._require_epoch(state, epoch_id, at)
        data = {"rows": self._history_rows(state, at), "complete": complete is True}
        return self._append(epoch_id=epoch_id, event_id=event_id, at=at, action="history_sample", data=data)

    def publish(self, *, epoch_id, event_id, as_of, valid_until):
        _stamp(as_of)
        _stamp(valid_until)
        state = self._append(
            epoch_id=epoch_id, event_id=event_id, at=as_of, action="publish",
            data={"valid_until": valid_until},
        )
        export = self._export(state)
        if self.export_path is not None:
            try:
                _atomic_json(self.export_path, export)
            except OSError as error:
                self.projection_error = str(error)
                raise
        self.projection_error = None
        return export

    def _export_position(self, row, as_of):
        mark = row.get("mark")
        if row["state"] == "SETTLED":
            mark = None
        elif mark and mark.get("state") == "CURRENT" and _stamp(as_of) > _stamp(mark["valid_until"]):
            mark = {"state": "STALE"}
        result = {
            key: (_amount(value) if isinstance(value, Decimal) else deepcopy(value))
            for key, value in row.items()
            if key not in ("gross_proceeds", "provenance") and value is not None
        }
        result["mark"] = deepcopy(mark)
        return result

    def _export(self, state):
        published = state["last_publish"]
        if published is None:
            raise PortfolioIntegrityError("portfolio_not_published")
        as_of, requested_until = published["as_of"], published["valid_until"]
        effective_until = requested_until
        for row in state["positions"].values():
            mark = row.get("mark")
            if row["state"] == "OPEN" and mark and mark.get("state") == "CURRENT" and _stamp(mark["valid_until"]) >= _stamp(as_of):
                if _stamp(mark["valid_until"]) < _stamp(effective_until):
                    effective_until = mark["valid_until"]
        reconciliation = self._reconcile(state)
        equity, _, unrealized = self._values_at(state, as_of)
        positions = [self._export_position(row, as_of) for _, row in sorted(state["positions"].items())]
        checks = dict(reconciliation["checks"])
        checks["equity_equals_inception_plus_net"] = (
            equity == STARTING_CAPITAL + reconciliation["realized"] + unrealized
            if equity is not None else None
        )
        complete_through = state["history_coverage_through"]
        history_complete = complete_through is not None and _stamp(complete_through) >= _stamp(as_of)
        portfolio_ids = state["identities"]["portfolio"]
        result = {
            "schema": SCHEMA_EXPORT,
            "mode": "canonical",
            "epoch_id": state["receipt"]["epoch_id"],
            "inception_sha256": state["receipt_hash"],
            "sequence": state["sequence"],
            "as_of": as_of,
            "valid_until": effective_until,
            "complete_lifecycle_coverage": True,
            "balances": {
                "equity": _amount(equity) if equity is not None else None,
                "available_cash": _amount(state["available"]),
                "reserved_cash": _amount(reconciliation["reserved"]),
                "deployed_capital": _amount(reconciliation["deployed"]),
                "realized_pnl": _amount(reconciliation["realized"]),
                "unrealized_pnl": _amount(unrealized) if unrealized is not None else None,
                "fees": _amount(reconciliation["total_fees"]),
                "shared_costs": _amount(state["shared_costs"]),
            },
            "positions": positions,
            "history": deepcopy(state["history"]),
            "history_complete": history_complete,
            "reconciliation": {
                "state": "CURRENT" if all(value is True for value in checks.values()) else "UNAVAILABLE" if None in checks.values() else "FAIL_CLOSED",
                "checks": checks,
            },
            "journal": {"sequence": state["sequence"], "hash": state["journal_hash"]},
            "lane_identities": deepcopy(state["identities"]["lanes"]),
            "external_adjustments": [],
            **portfolio_ids,
        }
        return result

    def recover_projections(self):
        inception = self._inception()
        if inception is None:
            return {"state": "NOT_INITIALIZED"}
        receipt, _, _ = inception
        if self.receipt_path is not None:
            if self.receipt_path.exists():
                current = json.loads(self.receipt_path.read_text())
                if validate_inception(current) != receipt:
                    raise PortfolioIntegrityError("conflicting_inception_projection")
            else:
                _atomic_json(self.receipt_path, receipt)
        state = deepcopy(self._state)
        if self.export_path is not None and state["last_publish"] is not None:
            expected = self._export(state)
            if self.export_path.exists():
                try:
                    current = json.loads(self.export_path.read_text(), parse_float=Decimal)
                except (OSError, ValueError, TypeError) as error:
                    raise PortfolioIntegrityError("invalid_export_projection") from error
                if current.get("epoch_id") != receipt["epoch_id"] or current.get("inception_sha256") != state["receipt_hash"]:
                    raise PortfolioIntegrityError("foreign_export_projection")
                sequence = current.get("sequence")
                if type(sequence) is not int or sequence > state["sequence"]:
                    raise PortfolioIntegrityError("export_projection_ahead_of_journal")
                if sequence == state["sequence"] and canonical(current) != canonical(expected):
                    raise PortfolioIntegrityError("equivocal_export_projection")
            _atomic_json(self.export_path, expected)
        self.projection_error = None
        return {"state": "CURRENT", "sequence": state["sequence"]}

    def verify_archive(self):
        state = self._replay()
        return {
            "verified": True,
            "initialized": state is not None,
            "sequence": state["sequence"] if state else 0,
            "journal_hash": state["journal_hash"] if state else ZERO_HASH,
            "complete_lifecycle_coverage": state is not None,
        }
