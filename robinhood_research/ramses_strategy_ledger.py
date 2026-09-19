"""Independent durable ledger for the Robinhood Ramses DLMM strategy family.

No shared allocator, no cross-strategy positions and no order authority.
The ledger accepts only decisions produced by the frozen Ramses strategy domain.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from . import BoundaryError
from .ramses_strategy import POLICY_HASH, STRATEGY_DOMAIN, STRATEGY_VERSION


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


class RamsesStrategyLedger:
    def __init__(self, path, *, paper_capital, quote_asset):
        if type(paper_capital) is not int or paper_capital <= 0:
            raise BoundaryError("invalid_ramses_strategy_capital")
        if not isinstance(quote_asset, str) or not quote_asset:
            raise BoundaryError("invalid_ramses_strategy_quote_asset")
        self.path = path
        self.paper_capital = paper_capital
        self.quote_asset = quote_asset.lower()
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA cache_size=-1024")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS ramses_strategy_meta(
                id TEXT PRIMARY KEY, body TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ramses_strategy_position(
                id TEXT PRIMARY KEY, body TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ramses_strategy_journal(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL, action TEXT NOT NULL,
                body TEXT NOT NULL, hash TEXT NOT NULL);
        """)
        genesis = dict(
            strategy_domain=STRATEGY_DOMAIN,
            strategy_version=STRATEGY_VERSION,
            policy_hash=POLICY_HASH,
            paper_capital=paper_capital,
            quote_asset=self.quote_asset,
            paper_only=True,
            allocation_authority=False,
            shared_allocator=False,
            cross_strategy_state=False,
        )
        row = self.db.execute(
            "SELECT body,hash FROM ramses_strategy_meta WHERE id='genesis'"
        ).fetchone()
        if row:
            body = json.loads(row[0])
            if body != genesis or _digest(body) != row[1]:
                raise BoundaryError("ramses_strategy_ledger_genesis_mismatch")
        else:
            self.db.execute(
                "INSERT INTO ramses_strategy_meta VALUES(?,?,?)",
                ("genesis", _canonical(genesis), _digest(genesis)),
            )

    def close(self):
        self.db.close()

    def _load(self, identity):
        row = self.db.execute(
            "SELECT body,hash FROM ramses_strategy_position WHERE id=?",
            (identity,),
        ).fetchone()
        if not row:
            raise BoundaryError("ramses_strategy_position_missing")
        body = json.loads(row[0])
        if _digest(body) != row[1]:
            raise BoundaryError("ramses_strategy_ledger_checksum")
        return body

    def _save(self, body, action):
        encoded = _canonical(body)
        checksum = _digest(body)
        self.db.execute(
            "INSERT OR REPLACE INTO ramses_strategy_position VALUES(?,?,?)",
            (body["id"], encoded, checksum),
        )
        self.db.execute(
            "INSERT INTO ramses_strategy_journal(id,action,body,hash) VALUES(?,?,?,?)",
            (body["id"], action, encoded, checksum),
        )

    def reserve(self, identity, *, pool, decision, at):
        if self.db.execute(
            "SELECT 1 FROM ramses_strategy_position WHERE id=?", (identity,)
        ).fetchone():
            raise BoundaryError("duplicate_ramses_strategy_reservation")
        if (
            not isinstance(decision, dict)
            or decision.get("strategy_domain") != STRATEGY_DOMAIN
            or decision.get("strategy_version") != STRATEGY_VERSION
            or decision.get("policy_hash") != POLICY_HASH
            or decision.get("allocation_authority") is not False
            or decision.get("qualified") is not True
            or not decision.get("freeze")
        ):
            raise BoundaryError("foreign_or_unqualified_strategy_decision")
        proposal = decision["freeze"]["proposals"][0]
        reserved = proposal.get("capital_employed")
        if type(reserved) is not int or reserved <= 0:
            raise BoundaryError("invalid_ramses_strategy_reservation")
        rec = self.reconcile()
        if rec["committed"] + reserved > self.paper_capital:
            raise BoundaryError("ramses_strategy_capital_exhausted")
        body = dict(
            id=identity,
            strategy_domain=STRATEGY_DOMAIN,
            strategy_version=STRATEGY_VERSION,
            policy_hash=POLICY_HASH,
            status="reserved",
            version=0,
            paper_only=True,
            allocation_authority=False,
            shared_allocator=False,
            pool=pool.lower(),
            mode=decision["mode"],
            proposal_hash=decision["freeze"]["proposal_hash"],
            reserved=reserved,
            realized=0,
            after_cost_result=None,
            at=at,
            outcome=None,
            rebalances=0,
            segments_closed=0,
            last_controller=None,
        )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._save(body, "reserve")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return body

    def reserve_forced_machinery(self, identity, *, pool, decision, at):
        """Reserve a mechanics-only position without converting it into strategy evidence."""
        if self.db.execute(
            "SELECT 1 FROM ramses_strategy_position WHERE id=?", (identity,)
        ).fetchone():
            raise BoundaryError("duplicate_ramses_strategy_reservation")
        if (
            not isinstance(decision, dict)
            or decision.get("strategy_domain") != STRATEGY_DOMAIN
            or decision.get("strategy_version") != STRATEGY_VERSION
            or decision.get("policy_hash") != POLICY_HASH
            or decision.get("allocation_authority") is not False
            or not decision.get("freeze")
        ):
            raise BoundaryError("foreign_forced_machinery_decision")
        proposal = decision["freeze"]["proposals"][0]
        reserved = proposal.get("capital_employed")
        if type(reserved) is not int or reserved <= 0:
            raise BoundaryError("invalid_ramses_strategy_reservation")
        rec = self.reconcile()
        if rec["committed"] + reserved > self.paper_capital:
            raise BoundaryError("ramses_strategy_capital_exhausted")
        body = dict(
            id=identity,
            strategy_domain=STRATEGY_DOMAIN,
            strategy_version=STRATEGY_VERSION,
            policy_hash=POLICY_HASH,
            status="reserved",
            version=0,
            paper_only=True,
            allocation_authority=False,
            shared_allocator=False,
            pool=pool.lower(),
            mode=decision.get("mode"),
            proposal_hash=decision["freeze"]["proposal_hash"],
            reserved=reserved,
            realized=0,
            after_cost_result=None,
            at=at,
            outcome=None,
            rebalances=0,
            segments_closed=0,
            last_controller=None,
            forced_machinery_test=True,
            strategy_evidence_eligible=False,
        )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._save(body, "forced_machinery_reserve")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return body

    def open(self, identity, *, at):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            body = self._load(identity)
            if body["status"] != "reserved":
                raise BoundaryError("ramses_strategy_open_state")
            if at < body["at"]:
                raise BoundaryError("ramses_strategy_time_regression")
            body.update(status="open", version=body["version"] + 1, at=at)
            self._save(body, "open")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return body

    def checkpoint(self, identity, *, action, detail, at):
        if action not in ("monitor", "segment_close", "rebalance"):
            raise BoundaryError("ramses_strategy_checkpoint_action")
        if not isinstance(detail, dict):
            raise BoundaryError("ramses_strategy_checkpoint_detail")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            body = self._load(identity)
            if body["status"] != "open":
                raise BoundaryError("ramses_strategy_checkpoint_state")
            if at < body["at"]:
                raise BoundaryError("ramses_strategy_time_regression")
            body.update(
                version=body["version"]+1,
                at=at,
                last_controller=detail,
            )
            if action=="segment_close":
                body["segments_closed"]=int(body.get("segments_closed",0))+1
            elif action=="rebalance":
                proposal_hash=detail.get("proposal_hash")
                if not isinstance(proposal_hash,str) or len(proposal_hash)!=64:
                    raise BoundaryError("ramses_strategy_rebalance_proposal")
                body["proposal_hash"]=proposal_hash
                body["rebalances"]=int(body.get("rebalances",0))+1
            self._save(body,action)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return body

    def settle(self, identity, *, pnl, at):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            body = self._load(identity)
            if body["status"] != "open":
                raise BoundaryError("ramses_strategy_settle_state")
            if at < body["at"]:
                raise BoundaryError("ramses_strategy_time_regression")
            if not isinstance(pnl, dict) or pnl.get("strategy_domain") != STRATEGY_DOMAIN:
                raise BoundaryError("foreign_strategy_outcome")
            result = pnl.get("net_result_quote")
            if pnl.get("unresolved_inventory") or type(result) is not int:
                body.update(
                    status="unresolved",
                    version=body["version"] + 1,
                    at=at,
                    outcome=pnl,
                )
                action = "unresolved"
            else:
                body.update(
                    status="settled",
                    version=body["version"] + 1,
                    at=at,
                    reserved=0,
                    realized=result,
                    after_cost_result=result,
                    outcome=pnl,
                )
                action = "settle"
            self._save(body, action)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return body

    def reconcile(self):
        rows = self.db.execute(
            "SELECT body,hash FROM ramses_strategy_position ORDER BY id"
        ).fetchall()
        positions = []
        for encoded, checksum in rows:
            body = json.loads(encoded)
            if _digest(body) != checksum:
                raise BoundaryError("ramses_strategy_ledger_checksum")
            if (
                body.get("strategy_domain") != STRATEGY_DOMAIN
                or body.get("shared_allocator") is not False
                or body.get("allocation_authority") is not False
            ):
                raise BoundaryError("ramses_strategy_ledger_domain_drift")
            positions.append(body)
        realized = sum(p["realized"] for p in positions if p["status"] == "settled")
        committed = sum(p["reserved"] for p in positions if p["status"] != "settled")
        available = self.paper_capital + realized - committed
        if available < 0:
            raise BoundaryError("ramses_strategy_capital_invariant")
        return dict(
            strategy_domain=STRATEGY_DOMAIN,
            strategy_version=STRATEGY_VERSION,
            policy_hash=POLICY_HASH,
            quote_asset=self.quote_asset,
            paper_capital=self.paper_capital,
            realized=realized,
            committed=committed,
            available=available,
            open_positions=sum(p["status"] != "settled" for p in positions),
            positions=len(positions),
            shared_allocator=False,
            allocation_authority=False,
        )

    def position(self, identity):
        return self._load(identity)
