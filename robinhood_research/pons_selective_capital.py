"""One Pons-only capital guard across independently persisted paper trials.

Reserve before a native trial can reserve. Release only after its native ledger
proves settlement. Failed/ambiguous trials retain their reservation and remain
visible; they cannot silently reset the lane's capital. No allocation authority.
"""
from contextlib import closing
import json
import sqlite3
from pathlib import Path
from . import BoundaryError
from .evidence import canonical,digest
from .pons_selective_continuation import POLICY_HASH
from .pons_selective_ledger import STRATEGY_NAMESPACE

class CohortCapital:
    def __init__(self,path,capital):
        if type(capital) is not int or capital<=0:raise BoundaryError('selective_cohort_capital_invalid')
        self.path=str(path);self.capital=capital
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS capital_genesis(id INTEGER PRIMARY KEY,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS capital_positions(id TEXT PRIMARY KEY,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS capital_journal(seq INTEGER PRIMARY KEY,id TEXT NOT NULL,action TEXT NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON capital_journal BEGIN SELECT RAISE(ABORT,'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON capital_journal BEGIN SELECT RAISE(ABORT,'append_only'); END;''')
            genesis=canonical(dict(capital=capital,policy_hash=POLICY_HASH,namespace=STRATEGY_NAMESPACE,asset='robinhood_native_quote',paper_only=True))
            db.execute('INSERT OR IGNORE INTO capital_genesis VALUES(1,?)',(genesis,))
            if db.execute('SELECT body FROM capital_genesis WHERE id=1').fetchone()[0]!=genesis:
                raise BoundaryError('selective_cohort_genesis_mismatch')

    def _connect(self):
        db=sqlite3.connect(self.path,timeout=30,isolation_level=None)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def _reconcile(self,db):
        replay={}
        for identity,action,raw,checksum in db.execute('SELECT id,action,body,hash FROM capital_journal ORDER BY seq'):
            row=json.loads(raw);previous=replay.get(identity)
            if row.get('id')!=identity or checksum!=digest(row) or row.get('policy_hash')!=POLICY_HASH:
                raise BoundaryError('selective_cohort_journal_mismatch')
            if action=='reserve':
                if previous is not None or row.get('status')!='reserved' or row.get('reserved')!=row.get('initial_reserved') or row.get('pnl')!=0:
                    raise BoundaryError('selective_cohort_journal_transition')
            elif action=='settle':
                if previous is None or previous['status']!='reserved' or row.get('status')!='settled' or row.get('reserved')!=0 or row['at']<previous['at']:
                    raise BoundaryError('selective_cohort_journal_transition')
                if any(row.get(k)!=previous.get(k) for k in ('initial_reserved','decision_hash','trial_path','policy_hash')):
                    raise BoundaryError('selective_cohort_journal_transition')
            else:raise BoundaryError('selective_cohort_journal_transition')
            replay[identity]=row
        projection={identity:json.loads(raw) for identity,raw in db.execute('SELECT id,body FROM capital_positions')}
        if projection!=replay:raise BoundaryError('selective_cohort_projection_mismatch')
        rows=list(replay.values())
        reserved=sum(x['reserved'] for x in rows)
        realized=sum(x['pnl'] for x in rows if x['status']=='settled')
        available=self.capital+realized-reserved
        if available<0:raise BoundaryError('selective_cohort_capital_invariant')
        return dict(genesis=self.capital,available=available,reserved=reserved,realized=realized,
                    unsettled=sum(x['status']!='settled' for x in rows),positions=len(rows),
                    policy_hash=POLICY_HASH,namespace=STRATEGY_NAMESPACE,
                    conservation=self.capital+realized==available+reserved)

    def reconcile(self):
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            return self._reconcile(db)

    def _write(self,db,row,action):
        raw=canonical(row)
        db.execute('INSERT OR REPLACE INTO capital_positions VALUES(?,?)',(row['id'],raw))
        db.execute('INSERT INTO capital_journal(id,action,body,hash) VALUES(?,?,?,?)',(row['id'],action,raw,digest(row)))

    def reserve(self,identity,amount,*,at,decision_hash,trial_path):
        if type(amount) is not int or amount<=0:raise BoundaryError('selective_cohort_reservation_invalid')
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                if db.execute('SELECT 1 FROM capital_positions WHERE id=?',(identity,)).fetchone():
                    raise BoundaryError('selective_cohort_duplicate_reservation')
                if amount>self._reconcile(db)['available']:
                    raise BoundaryError('selective_cohort_capital_exhausted')
                row=dict(id=identity,status='reserved',reserved=amount,initial_reserved=amount,pnl=0,
                         at=int(at),decision_hash=decision_hash,trial_path=str(trial_path),policy_hash=POLICY_HASH)
                self._write(db,row,'reserve');db.execute('COMMIT');return row
            except BaseException:db.execute('ROLLBACK');raise

    def settle(self,identity,position,*,at):
        if position.get('id')!=identity or position.get('experiment')!=STRATEGY_NAMESPACE or position.get('status')!='settled' or position.get('tokens')!=0 or position.get('reserved')!=0:
            raise BoundaryError('selective_cohort_native_settlement_required')
        pnl=position.get('pnl')
        if type(pnl) is not int:raise BoundaryError('selective_cohort_pnl_integer_required')
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                raw=db.execute('SELECT body FROM capital_positions WHERE id=?',(identity,)).fetchone()
                if not raw:raise BoundaryError('selective_cohort_reservation_missing')
                row=json.loads(raw[0])
                if row['status']=='settled':raise BoundaryError('selective_cohort_duplicate_settlement')
                if int(at)<row['at']:raise BoundaryError('selective_cohort_time_regression')
                if pnl < -row['initial_reserved']:raise BoundaryError('selective_cohort_loss_exceeds_reservation')
                row.update(status='settled',reserved=0,pnl=pnl,at=int(at),native_settlement_hash=digest(position))
                self._write(db,row,'settle');rec=self._reconcile(db);db.execute('COMMIT');return rec
            except BaseException:db.execute('ROLLBACK');raise
