"""Append-only, integer SOL paper accounting for independent Meteora lifecycles.

The journal is the state. Failed evidence leaves inventory and capital occupied.
Captured tapes support deterministic economic replay; capture itself is not proof
of chain authentication. Only the existing authenticated lifecycle writes them.
"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time
import uuid
from .store import digest,encode

NAMESPACE='solana_meteora_independent_v1'


def integer(value):
    if type(value) is not int or value<0:raise ValueError('dlmm_accounting_native_integer')
    return value


class PaperBook:
    def __init__(self,path,*,run_id,policy_hash,capital):
        self.path=Path(path);self.run_id=run_id;self.policy_hash=policy_hash
        self.genesis=dict(namespace=NAMESPACE,asset='SOL_lamports',run_id=run_id,
                          policy_hash=policy_hash,capital=integer(capital),paper_only=True)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self.connect()) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append_only'); END;''')
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM events LIMIT 1').fetchone():
                body=dict(action='genesis',data=self.genesis,previous='0'*64,at_ns=0,identity=None)
                db.execute('INSERT INTO events VALUES(1,?,?)',(encode(body),digest(body)))
            self._replay(db);db.commit()

    def connect(self):
        db=sqlite3.connect(self.path,timeout=30,isolation_level=None)
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
        return db

    def identity(self):return NAMESPACE+':'+self.run_id+':'+str(uuid.uuid4())

    def _replay(self,db):
        state=dict(cash=self.genesis['capital'],positions={},realized=0,net_cash_flows=0,
                   capital_unit_nanoseconds=0,last_at_ns=0,hash='0'*64,events=0)
        for seq,raw,checksum in db.execute('SELECT seq,body,hash FROM events ORDER BY seq'):
            body=json.loads(raw)
            if seq!=state['events']+1 or digest(body)!=checksum or body['previous']!=state['hash']:
                raise ValueError('dlmm_accounting_journal_integrity')
            if seq==1:
                if body['action']!='genesis' or body['data']!=self.genesis:raise ValueError('dlmm_accounting_genesis_mismatch')
            else:self._apply(state,body)
            state.update(hash=checksum,events=seq)
        return state

    def _apply(self,state,event):
        action=event['action'];data=event['data'];identity=event['identity'];at=integer(event['at_ns'])
        if not identity.startswith(NAMESPACE+':'+self.run_id+':'):raise ValueError('dlmm_accounting_foreign_lifecycle')
        if at<state['last_at_ns']:raise ValueError('dlmm_accounting_clock_regression')
        positions=state['positions'];risk=sum(p['reserved']+p.get('basis',0) for p in positions.values())
        state['capital_unit_nanoseconds']+=risk*(at-state['last_at_ns']);state['last_at_ns']=at
        if action=='reserve':
            amount=integer(data['amount'])
            if identity in positions or amount<=0:raise ValueError('dlmm_accounting_duplicate_reservation')
            if amount>state['cash']-sum(p['reserved'] for p in positions.values()):raise ValueError('dlmm_accounting_capital_exhausted')
            positions[identity]=dict(status='reserved',reserved=amount,basis=0,entry_cost=0,mark=None,entry=None)
            return
        if identity not in positions:raise ValueError('dlmm_accounting_reservation_missing')
        p=positions[identity]
        if action=='cancel':
            if p['status']!='reserved':raise ValueError('dlmm_accounting_cancel_after_fill')
            p.update(status='cancelled',reserved=0);return
        if action=='entry':
            capital=integer(data['capital']);entry_cost=integer(data['entry_cost']);exit_cost=integer(data['exit_cost'])
            if p['status']!='reserved' or p['reserved']!=capital+entry_cost+exit_cost:raise ValueError('dlmm_accounting_entry_reservation')
            if digest(data['policy'])!=self.policy_hash:raise ValueError('dlmm_accounting_policy_drift')
            if not isinstance(data.get('position'),dict) or not isinstance(data.get('entry_state'),dict):raise ValueError('dlmm_accounting_entry_evidence')
            state['cash']-=capital+entry_cost;state['net_cash_flows']-=capital+entry_cost
            if type(data['mark']['pnl_lamports']) is not int or data['mark']['pnl_lamports']!=integer(data['mark']['ending_sol_lamports'])-capital-entry_cost-exit_cost:raise ValueError('dlmm_accounting_entry_mark')
            p.update(status='open',reserved=exit_cost,basis=capital,entry_cost=entry_cost,exit_cost=exit_cost,entry=data,mark=data['mark'])
        elif action in ('mark','unresolved','settle'):
            if p['status'] not in ('open','unresolved'):raise ValueError('dlmm_accounting_position_not_open')
            if action=='unresolved':p['status']='unresolved';p['reason']=data['reason'];return
            mark=data['mark'];ending=integer(mark['ending_sol_lamports'])
            if mark['pnl_lamports']!=ending-p['basis']-p['entry_cost']-p['exit_cost']:raise ValueError('dlmm_accounting_mark_cost_disagreement')
            p['mark']=mark
            if action=='mark':
                if not isinstance(data.get('tape'),dict) or not data['tape'].get('lineage'):raise ValueError('dlmm_accounting_tape_missing')
                p['status']='open'
            else:
                proceeds=ending-p['exit_cost'];state['cash']+=proceeds;state['net_cash_flows']+=proceeds
                state['realized']+=mark['pnl_lamports'];p.update(status='settled',reserved=0,basis=0)
        else:raise ValueError('dlmm_accounting_unknown_action')
        if state['cash']<sum(p['reserved'] for p in positions.values()):raise ValueError('dlmm_accounting_negative_available')

    def append(self,identity,action,data,*,at_ns=None):
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE');state=self._replay(db)
            event=dict(action=action,identity=identity,data=data,previous=state['hash'],at_ns=time.time_ns() if at_ns is None else at_ns)
            self._apply(state,event)
            db.execute('INSERT INTO events VALUES(?,?,?)',(state['events']+1,encode(event),digest(event)));db.commit()
        return self.reconcile()

    def fail(self,identity,reason):
        with closing(self.connect()) as db:
            db.execute('BEGIN');state=self._replay(db)
        row=state['positions'].get(identity)
        if row and row['status'] in ('reserved','open','unresolved'):
            self.append(identity,'cancel' if row['status']=='reserved' else 'unresolved',dict(reason=reason))

    def reconcile(self):
        with closing(self.connect()) as db:
            db.execute('BEGIN');s=self._replay(db)
        open_rows=[p for p in s['positions'].values() if p['status'] in ('open','unresolved')]
        marked=sum(p['mark']['ending_sol_lamports']-p['exit_cost'] for p in open_rows)
        unrealized=sum(p['mark']['pnl_lamports'] for p in open_rows)
        reserved=sum(p['reserved'] for p in s['positions'].values())
        equity=s['cash']+marked
        if self.genesis['capital']+s['net_cash_flows']!=s['cash'] or self.genesis['capital']+s['realized']+unrealized!=equity:
            raise ValueError('dlmm_accounting_conservation')
        return dict(genesis=self.genesis,cash=s['cash'],reserved=reserved,available=s['cash']-reserved,
                    open_positions=len(open_rows),pending=sum(p['status']=='reserved' for p in s['positions'].values()),
                    unsettled=sum(p['status'] in ('open','unresolved','reserved') for p in s['positions'].values()),
                    settled=sum(p['status']=='settled' for p in s['positions'].values()),
                    realized_pnl_lamports=s['realized'],unrealized_pnl_lamports=unrealized,marked_equity=equity,
                    capital_unit_nanoseconds=s['capital_unit_nanoseconds'],capital_time_through_ns=s['last_at_ns'],
                    net_cash_flows=s['net_cash_flows'],journal_hash=s['hash'],journal_events=s['events'],reconciled=True,
                    stale_marks=sum(p['status']=='unresolved' for p in open_rows),economic_replay_verified=False)

    def replay_economics(self,build,advance,mark):
        from .dlmm_tape import VerifiedTape
        positions={};real_hashes={};checked=0
        with closing(self.connect()) as db:
            db.execute('BEGIN');self._replay(db)
            for (raw,) in db.execute('SELECT body FROM events ORDER BY seq'):
                event=json.loads(raw);data=event['data'];identity=event['identity']
                if event['action']=='entry':
                    position=build(data['entry_state'],data['features'],data['policy'])
                    if digest(position)!=digest(data['position']) or digest(mark(position))!=digest(data['mark']):raise ValueError('dlmm_accounting_entry_replay')
                    positions[identity]=position;real_hashes[identity]=digest(data['entry_state']);checked+=1
                elif event['action']=='mark':
                    t=data['tape'];tape=VerifiedTape(t['start_hash'],t['end_hash'],tuple(t['events']),t['terminal'],t['lineage'],tuple(t.get('terminal_adjustments',())))
                    if tape.start_hash!=real_hashes[identity] or tape.end_hash!=digest(tape.terminal):raise ValueError('dlmm_accounting_tape_chain_gap')
                    real_hashes[identity]=tape.end_hash
                    positions[identity]=advance(positions[identity],tape)
                    if digest(positions[identity])!=data['position_hash'] or digest(mark(positions[identity]))!=digest(data['mark']):raise ValueError('dlmm_accounting_monitor_replay')
                    checked+=1
                elif event['action']=='settle':
                    if digest(mark(positions[identity]))!=digest(data['mark']):raise ValueError('dlmm_accounting_settlement_replay')
                    checked+=1
        return dict(verified=True,checked_economic_events=checked,authentication='existing_lane_verified_tapes',raw_chain_reauthentication=False)
