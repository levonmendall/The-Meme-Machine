"""Durable proof-only Ramses LP paper lifecycle.

This state machine is intentionally incapable of granting strategy/allocation
authority. It exists only to prove reserve -> paper entry -> restart -> exit
intent -> removal/unwind -> settlement/reconciliation mechanics.
"""
import json
import sqlite3

from . import BoundaryError
from .evidence import canonical, digest
from .ramses import paper_position, verify_proposal_hash


AUTHORITY="forced_ramses_machinery_test"


class RamsesPaper:
    def __init__(self,path,capital):
        if type(capital) is not int or capital<=0:
            raise BoundaryError("invalid_ramses_paper_capital")
        self.path=path;self.capital=capital
        self.db=sqlite3.connect(path,isolation_level=None)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA cache_size=-1024")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS ramses_meta(
                id TEXT PRIMARY KEY, body TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ramses_position(
                id TEXT PRIMARY KEY, body TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ramses_journal(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL, action TEXT NOT NULL,
                body TEXT NOT NULL, hash TEXT NOT NULL);
        """)
        genesis=dict(capital=capital,authority=AUTHORITY,paper_only=True,
                     allocation_authority=False,natural_proof=False,
                     strategy_evidence_eligible=False)
        row=self.db.execute("SELECT body,hash FROM ramses_meta WHERE id='genesis'").fetchone()
        if row:
            if json.loads(row[0])!=genesis or digest(genesis)!=row[1]:
                raise BoundaryError("ramses_paper_genesis_mismatch")
        else:
            encoded=canonical(genesis)
            self.db.execute("INSERT INTO ramses_meta VALUES(?,?,?)",("genesis",encoded,digest(genesis)))

    def close(self):
        self.db.close()

    def _load(self,identity):
        row=self.db.execute("SELECT body,hash FROM ramses_position WHERE id=?",(identity,)).fetchone()
        if not row: raise BoundaryError("ramses_paper_position_missing")
        body=json.loads(row[0])
        if digest(body)!=row[1]: raise BoundaryError("ramses_paper_checksum_mismatch")
        return body

    def _save(self,body,action):
        encoded=canonical(body);checksum=digest(body)
        self.db.execute("INSERT OR REPLACE INTO ramses_position VALUES(?,?,?)",
                        (body["id"],encoded,checksum))
        self.db.execute("INSERT INTO ramses_journal(id,action,body,hash) VALUES(?,?,?,?)",
                        (body["id"],action,encoded,checksum))

    def reserve(self,identity,*,pool,freeze,proposal_index,block,block_hash,at):
        if self.db.execute("SELECT 1 FROM ramses_position WHERE id=?",(identity,)).fetchone():
            raise BoundaryError("duplicate_ramses_paper_reservation")
        verify_proposal_hash(freeze)
        position=paper_position(freeze,proposal_index)
        body=dict(
            id=identity,status="reserved",version=0,authority=AUTHORITY,
            paper_only=True,allocation_authority=False,natural_proof=False,
            strategy_evidence_eligible=False,pool=pool,proposal_index=proposal_index,
            proposal_hash=freeze["proposal_hash"],frozen_range=position["frozen_range"],
            owned_shares=position["owned_shares"],deposits=position["deposits"],
            quote_side=position["quote_side"],initial_cost_basis=position["initial_cost_basis"],
            initial_token_inventory=position["initial_token_inventory"],
            pre_entry_block=block,pre_entry_hash=block_hash,reserved=position["initial_cost_basis"],
            realized_before_costs=0,after_cost_result=None,last_at=at,
            outcome=None,reason=None,
        )
        if body["reserved"]>self.capital:
            raise BoundaryError("ramses_paper_capital_exhausted")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._save(body,"reserve");self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK");raise
        return body

    def enter(self,identity,*,at):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            body=self._load(identity)
            if body["status"]!="reserved": raise BoundaryError("ramses_paper_entry_state")
            if at<body["last_at"]: raise BoundaryError("ramses_paper_time_regression")
            body.update(status="open",version=body["version"]+1,last_at=at)
            self._save(body,"forced_paper_entry");self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK");raise
        return body

    def exit_intent(self,identity,*,at,reason="forced_test_horizon"):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            body=self._load(identity)
            if body["status"]!="open": raise BoundaryError("ramses_paper_exit_state")
            if at<body["last_at"]: raise BoundaryError("ramses_paper_time_regression")
            body.update(status="exit_pending",version=body["version"]+1,last_at=at,reason=reason)
            self._save(body,"exit_intent");self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK");raise
        return body

    def finish(self,identity,*,outcome,at):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            body=self._load(identity)
            if body["status"]!="exit_pending": raise BoundaryError("ramses_paper_finish_state")
            if at<body["last_at"]: raise BoundaryError("ramses_paper_time_regression")
            if outcome.get("unresolved_inventory"):
                body.update(status="unresolved",version=body["version"]+1,last_at=at,
                            outcome=outcome,reason=outcome["unresolved_inventory"])
                action="unresolved"
            else:
                gross=outcome.get("gross_result")
                if type(gross) is not int: raise BoundaryError("ramses_paper_missing_gross_result")
                body.update(status="settled",version=body["version"]+1,last_at=at,
                            reserved=0,realized_before_costs=gross,
                            after_cost_result=outcome.get("after_cost_result"),
                            outcome=outcome,reason=None)
                action="settle"
            self._save(body,action);self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK");raise
        return body

    def reconcile(self):
        rows=self.db.execute("SELECT body,hash FROM ramses_position ORDER BY id").fetchall()
        positions=[]
        for encoded,checksum in rows:
            body=json.loads(encoded)
            if digest(body)!=checksum: raise BoundaryError("ramses_paper_checksum_mismatch")
            if body.get("authority")!=AUTHORITY or body.get("strategy_evidence_eligible") is not False:
                raise BoundaryError("ramses_paper_authority_drift")
            positions.append(body)
        realized=sum(p["realized_before_costs"] for p in positions if p["status"]=="settled")
        committed=sum(p["reserved"] for p in positions if p["status"]!="settled")
        available=self.capital+realized-committed
        if available<0: raise BoundaryError("ramses_paper_capital_invariant")
        return dict(capital=self.capital,realized_before_costs=realized,committed=committed,
                    available=available,open_positions=sum(p["status"]!="settled" for p in positions),
                    positions=len(positions),strategy_evidence_eligible=False)

    def position(self,identity):
        return self._load(identity)
