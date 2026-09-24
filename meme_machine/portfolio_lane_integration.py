"""Epoch-bound adapters from native paper lifecycles to shared USD accounting.

The integration is deliberately dormant unless an already initialized canonical
portfolio database, exact epoch, and exact inception hash are supplied.  It does
not initialize a portfolio, acquire a price, convert a native unit, select a
strategy, or mutate a native lane book.

Native journals remain the source evidence.  Their events are delivered through
lane-specific adapters after the native boundary has produced an authoritative USD
fact.  A deterministic event identity and a payload hash make ambiguous retries
idempotent; a conflicting redelivery, sequence gap/regression, wrong epoch, or
missing USD evidence fails closed.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import sqlite3
import threading

from .portfolio_accounting import (
    LANES,
    PortfolioAccounting,
    PortfolioIntegrityError,
    digest,
)


SCHEMA_LANE_EVENT = "meme-machine-portfolio-lane-event-v1"
KINDS = {
    "reserve", "release", "enter", "realize", "harvest",
    "rebalance_reserve", "rebalance", "mark", "settle",
}
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,120}")
_STRATEGY_ID = re.compile(r"[A-Za-z0-9_.:/-]{1,180}")
_HASH = re.compile(r"[a-f0-9]{40}|[a-f0-9]{64}")
_MONEY = re.compile(r"-?\d{1,40}(?:\.\d{1,24})?")


def _id(value, name="identity"):
    if not isinstance(value, str) or "//" in value or not _ID.fullmatch(value):
        raise ValueError(f"invalid_{name}")
    return value


def _hash(value, name="hash"):
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(f"invalid_{name}")
    return value


def _strategy_id(value):
    if not isinstance(value, str) or "://" in value or not _STRATEGY_ID.fullmatch(value):
        raise ValueError("invalid_strategy_id")
    return value


def _money(value, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("exact_decimal_required")
    text = format(value, "f") if isinstance(value, Decimal) else str(value)
    if not _MONEY.fullmatch(text):
        raise ValueError("invalid_decimal")
    amount = Decimal(text)
    if positive and amount <= 0 or nonnegative and amount < 0:
        raise ValueError("invalid_monetary_sign")
    return format(amount, "f")


def _no_float(value):
    if isinstance(value, float):
        raise ValueError("binary_float_forbidden")
    if isinstance(value, dict):
        for child in value.values():
            _no_float(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _no_float(child)


def usd_evidence(evidence_id, evidence_sha256, as_of, valid_until):
    """Construct explicit source-bounded USD evidence; never acquire or extend it."""
    return {
        "evidence_id": _id(evidence_id, "evidence_id"),
        "evidence_sha256": _hash(evidence_sha256, "evidence_sha256"),
        "currency": "USD",
        "as_of": as_of,
        "valid_until": valid_until,
    }


@dataclass(frozen=True)
class LaneEvent:
    """One normalized fact emitted at a native lane lifecycle boundary."""

    epoch_id: str
    lane: str
    native_lifecycle_id: str
    native_event_id: str
    native_sequence: int
    native_journal_hash: str
    kind: str
    at: str
    data: dict
    value_evidence: dict | None = None
    schema: str = SCHEMA_LANE_EVENT

    def canonical_value(self):
        value = {
            "schema": self.schema,
            "epoch_id": self.epoch_id,
            "lane": self.lane,
            "native_lifecycle_id": self.native_lifecycle_id,
            "native_event_id": self.native_event_id,
            "native_sequence": self.native_sequence,
            "native_journal_hash": self.native_journal_hash,
            "kind": self.kind,
            "at": self.at,
            "data": deepcopy(self.data),
            "value_evidence": deepcopy(self.value_evidence),
        }
        _no_float(value)
        return value


class DormantPortfolioLaneProducer:
    """No-I/O integration used until a real inception is separately authorized."""

    def status(self):
        return {"state": "NOT_INITIALIZED", "paper_only": True, "accepted": False}

    def lane(self, lane):
        if lane not in LANES:
            raise ValueError("unknown_lane")
        return DormantLaneAdapter(lane)

    def deliver(self, event):
        return self.status()

    def close(self):
        return None


class DormantLaneAdapter:
    def __init__(self, lane):
        self.lane = lane

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def inactive(*args, **kwargs):
            return {"state": "NOT_INITIALIZED", "paper_only": True, "accepted": False}
        return inactive


class PortfolioLaneProducer:
    """Single-process coordinator for all four lane adapters and one accountant."""

    def __init__(self, account, *, epoch_id, inception_sha256, owns_account=False):
        if not isinstance(account, PortfolioAccounting):
            raise TypeError("portfolio_accounting_required")
        binding = account.binding()
        if binding is None:
            raise PortfolioIntegrityError("portfolio_not_initialized")
        if binding["receipt"]["epoch_id"] != epoch_id:
            raise PortfolioIntegrityError("cross_epoch_integration")
        if binding["inception_sha256"] != inception_sha256:
            raise PortfolioIntegrityError("inception_identity_mismatch")
        self.account = account
        self.epoch_id = epoch_id
        self.inception_sha256 = inception_sha256
        self.identities = binding["identities"]["lanes"]
        self._owns_account = owns_account
        self._lock = threading.RLock()
        self._native_cursors = {}
        self._recover_native_cursors()

    @classmethod
    def open_existing(
        cls, database, *, epoch_id, inception_sha256, receipt_path=None, export_path=None
    ):
        """Open only a pre-existing, initialized database with the exact binding."""
        path = Path(database).resolve()
        if not path.is_file():
            raise PortfolioIntegrityError("initialized_portfolio_database_required")
        uri = "file:" + str(path) + "?mode=ro"
        probe = sqlite3.connect(uri, uri=True)
        try:
            row = probe.execute(
                "SELECT body,sha256 FROM portfolio_inception WHERE id=1"
            ).fetchone()
        except sqlite3.Error as error:
            raise PortfolioIntegrityError("initialized_portfolio_database_required") from error
        finally:
            probe.close()
        if row is None:
            raise PortfolioIntegrityError("portfolio_not_initialized")
        if row[1] != inception_sha256:
            raise PortfolioIntegrityError("inception_identity_mismatch")
        try:
            receipt = json.loads(row[0])
        except (TypeError, ValueError) as error:
            raise PortfolioIntegrityError("invalid_inception_receipt") from error
        if receipt.get("epoch_id") != epoch_id:
            raise PortfolioIntegrityError("cross_epoch_integration")
        account = PortfolioAccounting(
            path, receipt_path=receipt_path, export_path=export_path
        )
        try:
            return cls(
                account, epoch_id=epoch_id, inception_sha256=inception_sha256,
                owns_account=True,
            )
        except BaseException:
            account.close()
            raise

    def close(self):
        if self._owns_account:
            self.account.close()
            self._owns_account = False

    def status(self):
        result = self.account.status()
        return dict(result, integration="ACTIVE", inception_sha256=self.inception_sha256)

    def lane(self, lane):
        classes = {
            "pump": PumpPortfolioAdapter,
            "pons": PonsPortfolioAdapter,
            "ramses": RamsesPortfolioAdapter,
            "meteora": MeteoraPortfolioAdapter,
        }
        try:
            return classes[lane](self)
        except KeyError as error:
            raise ValueError("unknown_lane") from error

    def _recover_native_cursors(self):
        cursors = {}
        for row in self.account.canonical_events():
            body = row["body"]
            provenance = body.get("data", {}).get("provenance") or {}
            native = provenance.get("native_lifecycle_id")
            sequence = provenance.get("native_sequence")
            if native is None and sequence is None:
                continue
            if native is None or type(sequence) is not int or sequence < 1:
                raise PortfolioIntegrityError("incomplete_native_event_binding")
            lane = body.get("data", {}).get("lane")
            if lane is None:
                lifecycle = body.get("data", {}).get("lifecycle_id")
                if isinstance(lifecycle, str) and ":" in lifecycle:
                    lane = lifecycle.split(":", 1)[0]
                elif body.get("action") == "release_reservation":
                    reservation = body.get("data", {}).get("reservation_id", "")
                    lane = reservation.split(":", 2)[1] if reservation.startswith("reservation:") else None
            if lane not in LANES:
                raise PortfolioIntegrityError("native_event_lane_binding")
            key = (lane, native)
            expected = cursors.get(key, 0) + 1
            if sequence != expected:
                raise PortfolioIntegrityError("native_sequence_gap_or_regression")
            cursors[key] = sequence
        self._native_cursors = cursors

    @staticmethod
    def _canonical_lifecycle(lane, native_lifecycle_id):
        native = _id(native_lifecycle_id, "native_lifecycle_id")
        value = f"{lane}:{native}"
        if not _ID.fullmatch(value):
            raise ValueError("native_lifecycle_identity_too_long")
        return value

    def _event_id(self, event):
        identity = [
            event.epoch_id, event.lane, event.native_lifecycle_id,
            event.native_event_id, event.kind,
        ]
        return f"portfolio:{event.lane}:{digest(identity)}"

    def _reservation_id(self, lane, native_reservation_id):
        native = _id(native_reservation_id, "native_reservation_id")
        return f"reservation:{lane}:{digest([self.epoch_id, lane, native])}"

    def _provenance(self, event, fingerprint):
        identities = self.identities[event.lane]
        result = {
            "source_event_id": _id(event.native_event_id, "native_event_id"),
            "source_kind": f"native_{event.lane}_{event.kind}",
            "source_sha": identities["source_sha"],
            "policy_hash": identities["policy_hash"],
            "config_hash": identities["config_hash"],
            "native_lifecycle_id": _id(
                event.native_lifecycle_id, "native_lifecycle_id"
            ),
            "native_journal_hash": _hash(
                event.native_journal_hash, "native_journal_hash"
            ),
            "native_event_sha256": fingerprint,
            "native_sequence": event.native_sequence,
        }
        if identities.get("source_diff_sha256") is not None:
            result["source_diff_sha256"] = identities["source_diff_sha256"]
        if event.value_evidence is not None:
            result["value_evidence"] = deepcopy(event.value_evidence)
        return result

    @staticmethod
    def _stored_fingerprint(canonical_event):
        if canonical_event is None:
            return None
        return (
            canonical_event.get("body", {}).get("data", {})
            .get("provenance", {}).get("native_event_sha256")
        )

    def deliver(self, event):
        if not isinstance(event, LaneEvent):
            raise TypeError("lane_event_required")
        value = event.canonical_value()
        if event.schema != SCHEMA_LANE_EVENT or event.kind not in KINDS:
            raise ValueError("lane_event_contract")
        if event.lane not in LANES:
            raise ValueError("unknown_lane")
        if event.epoch_id != self.epoch_id:
            raise PortfolioIntegrityError("cross_epoch_fact")
        if type(event.native_sequence) is not int or event.native_sequence < 1:
            raise PortfolioIntegrityError("native_sequence_required")
        _id(event.native_lifecycle_id, "native_lifecycle_id")
        _id(event.native_event_id, "native_event_id")
        _hash(event.native_journal_hash, "native_journal_hash")
        fingerprint = digest(value)
        event_id = self._event_id(event)
        lifecycle_id = self._canonical_lifecycle(
            event.lane, event.native_lifecycle_id
        )
        with self._lock:
            existing = self.account.canonical_event(event_id)
            if existing is not None:
                if self._stored_fingerprint(existing) != fingerprint:
                    raise PortfolioIntegrityError("conflicting_duplicate_native_event")
                return {
                    "accepted": True,
                    "idempotent": True,
                    "event_id": event_id,
                    "sequence": existing["sequence"],
                    "state": self.account.snapshot(),
                }
            key = (event.lane, event.native_lifecycle_id)
            if event.native_sequence != self._native_cursors.get(key, 0) + 1:
                raise PortfolioIntegrityError("native_sequence_gap_or_regression")
            provenance = self._provenance(event, fingerprint)
            data = value["data"]
            state = self._dispatch(
                event, event_id, lifecycle_id, data, provenance
            )
            self._native_cursors[key] = event.native_sequence
            canonical_event = self.account.canonical_event(event_id)
            return {
                "accepted": True,
                "idempotent": False,
                "event_id": event_id,
                "sequence": canonical_event["sequence"],
                "state": state,
            }

    def _dispatch(self, event, event_id, lifecycle_id, data, provenance):
        common = dict(epoch_id=self.epoch_id, event_id=event_id, at=event.at)
        reservation_native = data.get("native_reservation_id", event.native_lifecycle_id)
        reservation_id = self._reservation_id(event.lane, reservation_native)
        if event.kind in ("reserve", "rebalance_reserve"):
            return self.account.reserve(
                **common, reservation_id=reservation_id, lane=event.lane,
                lifecycle_id=lifecycle_id, amount=_money(data.get("amount"), positive=True),
                provenance=provenance,
            )
        if event.kind == "release":
            return self.account.release_reservation(
                **common, reservation_id=reservation_id, provenance=provenance
            )
        if event.kind == "enter":
            self._require_value_evidence(event)
            return self.account.enter(
                **common, reservation_id=reservation_id, lifecycle_id=lifecycle_id,
                lane=event.lane, asset=_id(data.get("asset"), "asset"),
                basis=_money(data.get("basis"), positive=True),
                fee=_money(data.get("fee", "0"), nonnegative=True),
                strategy_id=_strategy_id(data.get("strategy_id")),
                provenance=provenance,
                prior_stages=tuple(data.get("prior_stages") or ()),
                lane_state=deepcopy(data.get("lane_state")),
            )
        if event.kind in ("realize", "harvest"):
            self._require_value_evidence(event)
            return self.account.realize(
                **common, lifecycle_id=lifecycle_id,
                basis_released=_money(data.get("basis_released"), positive=True),
                gross_proceeds=_money(data.get("gross_proceeds"), nonnegative=True),
                fee=_money(data.get("fee", "0"), nonnegative=True),
                provenance=provenance, harvest=event.kind == "harvest",
            )
        if event.kind == "rebalance":
            self._require_value_evidence(event)
            return self.account.rebalance(
                **common, lifecycle_id=lifecycle_id, reservation_id=reservation_id,
                basis_released=_money(data.get("basis_released", "0"), nonnegative=True),
                gross_proceeds=_money(data.get("gross_proceeds", "0"), nonnegative=True),
                basis_added=_money(data.get("basis_added", "0"), nonnegative=True),
                fee=_money(data.get("fee", "0"), nonnegative=True),
                provenance=provenance, lane_state=deepcopy(data.get("lane_state")),
            )
        if event.kind == "mark":
            mark_state = data.get("state")
            if mark_state == "CURRENT":
                self._require_value_evidence(event)
                evidence = event.value_evidence
                return self.account.mark(
                    **common, lifecycle_id=lifecycle_id, state="CURRENT",
                    net_liquidation_value=_money(
                        data.get("net_liquidation_value"), nonnegative=True
                    ),
                    as_of=evidence["as_of"], valid_until=evidence["valid_until"],
                    provenance=provenance,
                    lane_state=deepcopy(data.get("lane_state")),
                )
            if mark_state not in ("STALE", "UNAVAILABLE", "FAIL_CLOSED", "UNKNOWN"):
                raise ValueError("invalid_mark_state")
            if event.value_evidence is not None:
                raise ValueError("unavailable_mark_must_not_claim_value_evidence")
            return self.account.mark(
                **common, lifecycle_id=lifecycle_id, state=mark_state,
                provenance=provenance,
                lane_state=deepcopy(data.get("lane_state")),
            )
        if event.kind == "settle":
            self._require_value_evidence(event)
            return self.account.settle(
                **common, lifecycle_id=lifecycle_id,
                gross_proceeds=_money(data.get("gross_proceeds"), nonnegative=True),
                fee=_money(data.get("fee", "0"), nonnegative=True),
                exit_reason=_id(data.get("exit_reason"), "exit_reason"),
                provenance=provenance,
            )
        raise ValueError("unsupported_lane_event")

    @staticmethod
    def _require_value_evidence(event):
        evidence = event.value_evidence
        if not isinstance(evidence, dict) or evidence.get("currency") != "USD":
            raise PortfolioIntegrityError("authoritative_usd_value_evidence_required")


class LanePortfolioAdapter:
    """Common exact-event API; subclasses only name native lifecycle boundaries."""

    def __init__(self, producer, lane):
        self.producer = producer
        self.lane = lane

    def event(
        self, kind, *, native_lifecycle_id, native_event_id, native_sequence,
        native_journal_hash, at, data, value_evidence=None, epoch_id=None,
    ):
        return self.producer.deliver(LaneEvent(
            epoch_id=epoch_id or self.producer.epoch_id,
            lane=self.lane,
            native_lifecycle_id=native_lifecycle_id,
            native_event_id=native_event_id,
            native_sequence=native_sequence,
            native_journal_hash=native_journal_hash,
            kind=kind,
            at=at,
            data=deepcopy(data),
            value_evidence=deepcopy(value_evidence),
        ))

    def reserve(self, *, amount, native_reservation_id=None, **event):
        data={"amount": _money(amount, positive=True)}
        if native_reservation_id is not None:
            data["native_reservation_id"] = native_reservation_id
        return self.event("reserve", data=data, **event)

    def release(self, *, native_reservation_id=None, **event):
        data={}
        if native_reservation_id is not None:
            data["native_reservation_id"] = native_reservation_id
        return self.event("release", data=data, **event)

    def enter(
        self, *, asset, basis, fee, strategy_id, value_evidence,
        native_reservation_id=None, prior_stages=(), lane_state=None, **event,
    ):
        data = {
            "asset": asset,
            "basis": _money(basis, positive=True),
            "fee": _money(fee, nonnegative=True),
            "strategy_id": strategy_id,
            "prior_stages": list(prior_stages),
            "lane_state": deepcopy(lane_state),
        }
        if native_reservation_id is not None:
            data["native_reservation_id"] = native_reservation_id
        return self.event("enter", data=data, value_evidence=value_evidence, **event)

    def realize(
        self, *, basis_released, gross_proceeds, fee, value_evidence,
        harvest=False, **event,
    ):
        return self.event(
            "harvest" if harvest else "realize",
            data={
                "basis_released": _money(basis_released, positive=True),
                "gross_proceeds": _money(gross_proceeds, nonnegative=True),
                "fee": _money(fee, nonnegative=True),
            },
            value_evidence=value_evidence,
            **event,
        )

    def reserve_rebalance(self, *, native_reservation_id, amount, **event):
        return self.event(
            "rebalance_reserve",
            data={
                "native_reservation_id": native_reservation_id,
                "amount": _money(amount, positive=True),
            },
            **event,
        )

    def rebalance(
        self, *, native_reservation_id, basis_released, gross_proceeds,
        basis_added, fee, value_evidence, lane_state=None, **event,
    ):
        return self.event(
            "rebalance",
            data={
                "native_reservation_id": native_reservation_id,
                "basis_released": _money(basis_released, nonnegative=True),
                "gross_proceeds": _money(gross_proceeds, nonnegative=True),
                "basis_added": _money(basis_added, nonnegative=True),
                "fee": _money(fee, nonnegative=True),
                "lane_state": deepcopy(lane_state),
            },
            value_evidence=value_evidence,
            **event,
        )

    def mark(
        self, *, state, net_liquidation_value=None, value_evidence=None,
        lane_state=None, **event,
    ):
        data={"state": state, "lane_state": deepcopy(lane_state)}
        if net_liquidation_value is not None:
            data["net_liquidation_value"] = _money(
                net_liquidation_value, nonnegative=True
            )
        return self.event("mark", data=data, value_evidence=value_evidence, **event)

    def settle(
        self, *, gross_proceeds, fee, exit_reason, value_evidence, **event,
    ):
        return self.event(
            "settle",
            data={
                "gross_proceeds": _money(gross_proceeds, nonnegative=True),
                "fee": _money(fee, nonnegative=True),
                "exit_reason": exit_reason,
            },
            value_evidence=value_evidence,
            **event,
        )


class PumpPortfolioAdapter(LanePortfolioAdapter):
    """Pump PaperBook hooks: reserve/fill/partial-harvest/mark/settle."""
    def __init__(self, producer): super().__init__(producer, "pump")
    reserve_before_fill = LanePortfolioAdapter.reserve
    release_failed_fill = LanePortfolioAdapter.release
    fill_committed = LanePortfolioAdapter.enter

    def partial_harvest(self, **kwargs):
        kwargs["harvest"] = True
        return self.realize(**kwargs)

    settlement = LanePortfolioAdapter.settle


class PonsPortfolioAdapter(LanePortfolioAdapter):
    """Pons SelectivePaper hooks: reserve/entry/partial-exit/runner/settle."""
    def __init__(self, producer): super().__init__(producer, "pons")
    reserve_before_entry = LanePortfolioAdapter.reserve
    release_cancelled_entry = LanePortfolioAdapter.release
    entry_committed = LanePortfolioAdapter.enter

    def partial_exit(self, **kwargs):
        kwargs["harvest"] = True
        return self.realize(**kwargs)

    runner_mark = LanePortfolioAdapter.mark
    settlement = LanePortfolioAdapter.settle


class RamsesPortfolioAdapter(LanePortfolioAdapter):
    """RamsesStrategyLedger hooks: reserve/open/rebalance/mark/settle."""
    def __init__(self, producer): super().__init__(producer, "ramses")
    reserve_before_open = LanePortfolioAdapter.reserve
    release_failed_open = LanePortfolioAdapter.release
    open_committed = LanePortfolioAdapter.enter
    checkpoint_rebalance = LanePortfolioAdapter.rebalance
    settlement = LanePortfolioAdapter.settle


class MeteoraPortfolioAdapter(LanePortfolioAdapter):
    """Meteora Replay hooks: reserve/deposit/rebalance/mark/withdraw/settle."""
    def __init__(self, producer): super().__init__(producer, "meteora")
    reserve_before_deposit = LanePortfolioAdapter.reserve
    release_cancelled_deposit = LanePortfolioAdapter.release
    deposit_committed = LanePortfolioAdapter.enter
    range_rebalance = LanePortfolioAdapter.rebalance
    settlement = LanePortfolioAdapter.settle


def producer_from_environment(environ=None):
    """Return dormant integration unless a complete existing binding is explicit."""
    env = os.environ if environ is None else environ
    names = {
        "database": "MM_PORTFOLIO_ACCOUNTING_DB",
        "epoch_id": "MM_PORTFOLIO_EPOCH_ID",
        "inception_sha256": "MM_PORTFOLIO_INCEPTION_SHA256",
    }
    configured = {key: env.get(name) for key, name in names.items()}
    present = {key for key, value in configured.items() if value}
    if not present:
        return DormantPortfolioLaneProducer()
    if present != set(names):
        raise PortfolioIntegrityError("incomplete_portfolio_integration_binding")
    return PortfolioLaneProducer.open_existing(
        configured["database"],
        epoch_id=configured["epoch_id"],
        inception_sha256=configured["inception_sha256"],
        receipt_path=env.get("MM_PORTFOLIO_INCEPTION_RECEIPT"),
        export_path=env.get("MM_PORTFOLIO_EXPORT"),
    )
