"""Append-only certification evidence, integer accounting and deterministic replay.

An observer never grants lane allocation authority. Unknown amounts stay unknown.
Balances in different native assets are never added without a valuation proof.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

LANES = ('pump', 'meteora', 'pons', 'ramses')

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def integer(value, name):
    if type(value) is not int:
        raise ValueError('integer_required:' + name)
    return value

class Journal:
    """Durable observer journal. SQL rejects update/delete of committed evidence."""
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY, lane TEXT NOT NULL, identity TEXT NOT NULL,
              kind TEXT NOT NULL, at_ns INTEGER NOT NULL, body TEXT NOT NULL,
              previous TEXT NOT NULL, hash TEXT NOT NULL, UNIQUE(lane,identity));
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
              BEGIN SELECT RAISE(ABORT,'append_only'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
              BEGIN SELECT RAISE(ABORT,'append_only'); END;
        ''')

    def append(self, lane, identity, kind, body, *, at_ns=None):
        if lane not in (*LANES, 'supervisor'):
            raise ValueError('foreign_lane')
        at_ns = time.time_ns() if at_ns is None else integer(at_ns, 'at_ns')
        raw = canonical(body)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            existing = self.db.execute('SELECT kind,body,hash FROM events WHERE lane=? AND identity=?', (lane,identity)).fetchone()
            if existing:
                if existing[:2] != (kind,raw):
                    raise ValueError('conflicting_duplicate_event')
                self.db.execute('COMMIT')
                return existing[2]
            row = self.db.execute('SELECT hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            previous = row[0] if row else '0'*64
            hash_ = digest([lane,identity,kind,at_ns,body,previous])
            self.db.execute('INSERT INTO events(lane,identity,kind,at_ns,body,previous,hash) VALUES(?,?,?,?,?,?,?)', (lane,identity,kind,at_ns,raw,previous,hash_))
            self.db.execute('COMMIT')
            return hash_
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def records(self):
        previous = '0'*64
        for seq,lane,identity,kind,at_ns,raw,anchor,hash_ in self.db.execute('SELECT * FROM events ORDER BY seq'):
            body = json.loads(raw)
            if anchor != previous or hash_ != digest([lane,identity,kind,at_ns,body,anchor]):
                raise ValueError('journal_chain_corruption')
            previous = hash_
            yield dict(seq=seq,lane=lane,identity=identity,kind=kind,at_ns=at_ns,body=body,hash=hash_)

    def close(self):
        self.db.close()

class Accounting:
    """Replay explicit cash/reservation/inventory postings, never infer a cost as zero.

    Postings are lane-local observations, not executable orders. Partial exits
    consume a stated integer cost basis; capital time integrates reserved basis,
    not repeated entry turnover. Every state transition remains in the journal.
    """
    def __init__(self, run_id, lane, asset, genesis, policy_hash):
        if lane not in LANES or not asset or len(policy_hash) != 64:
            raise ValueError('accounting_namespace')
        self.run_id,self.lane,self.asset,self.policy_hash = run_id,lane,asset,policy_hash
        self.genesis = integer(genesis,'genesis')
        if genesis <= 0: raise ValueError('positive_genesis_required')
        self.cash,self.realized = genesis,0
        self.positions = {}
        self.events = []
        self.capital_unit_nanoseconds = 0
        self.last_ns = None

    def lifecycle_id(self, source_identity):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, canonical([self.run_id,self.lane,source_identity])))

    def apply(self, event):
        e = json.loads(canonical(event))
        if e.get('lane') != self.lane or e.get('policy_hash') != self.policy_hash or e.get('asset') != self.asset:
            raise ValueError('accounting_cross_lane_or_policy')
        at = integer(e['at_ns'],'at_ns')
        if self.last_ns is not None and at < self.last_ns:
            raise ValueError('accounting_time_regression')
        identity=e['lifecycle_id']; action=e['action']
        if not isinstance(e.get('evidence_hash'), str) or len(e['evidence_hash']) != 64:
            raise ValueError('accounting_evidence_required')
        # Validate on a copy: rejected postings must not alter balances or clocks.
        state=json.loads(canonical(self.positions));cash=self.cash;realized=self.realized
        p=state.get(identity)
        if action=='reserve':
            if p is not None: raise ValueError('duplicate_lifecycle')
            amount=integer(e['amount'],'amount')
            if amount<=0 or amount>cash: raise ValueError('capital_unavailable')
            cash-=amount;state[identity]=dict(status='reserved',reserved=amount,basis=0,tokens=0,net_proceeds=0)
        elif action=='fill':
            if not p or p['status']!='reserved': raise ValueError('fill_state')
            cost=integer(e['cost'],'cost');tokens=integer(e['tokens'],'tokens')
            if not 0<cost<=p['reserved'] or tokens<=0: raise ValueError('fill_amount')
            cash+=p['reserved']-cost;p.update(status='open',reserved=0,basis=cost,tokens=tokens)
        elif action=='cancel':
            if not p or p['status']!='reserved': raise ValueError('cancel_state')
            cash+=p['reserved'];p.update(status='cancelled',reserved=0)
        elif action=='exit':
            if not p or p['status']!='open': raise ValueError('exit_state')
            tokens=integer(e['tokens'],'tokens');basis=integer(e['basis'],'basis')
            gross=integer(e['gross_proceeds'],'gross_proceeds')
            # Each cost class must be explicit; unavailable costs forbid settlement.
            costs=e['costs']
            required={'network','protocol','unwind'}
            if set(costs)!=required or any(integer(v,k)<0 for k,v in costs.items()):
                raise ValueError('cost_evidence_incomplete')
            expected=p['basis'] if tokens==p['tokens'] else p['basis']*tokens//p['tokens']
            if not 0<tokens<=p['tokens'] or basis!=expected or gross<sum(costs.values()):
                raise ValueError('exit_amount_or_basis')
            net=gross-sum(costs.values());cash+=net;realized+=net-basis
            p['basis']-=basis;p['tokens']-=tokens;p['net_proceeds']+=net
            if p['tokens']==0:p['status']='settled'
        else:
            raise ValueError('unknown_accounting_action')
        reserved=sum(p['reserved'] for p in state.values());basis=sum(p['basis'] for p in state.values())
        if self.genesis+realized != cash+reserved+basis: raise ValueError('cash_conservation')
        if self.last_ns is not None:
            occupied=sum(p['reserved']+p['basis'] for p in self.positions.values())
            self.capital_unit_nanoseconds+=occupied*(at-self.last_ns)
        self.last_ns=at;self.positions=state;self.cash=cash;self.realized=realized;self.events.append(e)
        return self.reconcile()

    def reconcile(self):
        reserved=sum(p['reserved'] for p in self.positions.values())
        basis=sum(p['basis'] for p in self.positions.values())
        return dict(lane=self.lane,asset=self.asset,genesis=self.genesis,cash=self.cash,
                    reserved=reserved,position_basis=basis,realized=self.realized,
                    capital_unit_nanoseconds=self.capital_unit_nanoseconds,
                    capital_hours_denominator=3_600_000_000_000,
                    balanced=self.genesis+self.realized==self.cash+reserved+basis,
                    open_positions=sum(p['status'] in ('reserved','open') for p in self.positions.values()),
                    settled=sum(p['status']=='settled' for p in self.positions.values()))
