"""One durable reservation authority per existing directional sleeve.

Native ledgers remain accounting truth. Reservations are held until a verified
native terminal is supplied. A crash between native commit and observation leaves
capital held, never available twice. There is no cross-sleeve borrowing.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading

from certification.journal import canonical, digest


class SleeveReservations:
    def __init__(self,path,*,lane,capital,policies,cohort):
        if lane not in ('pump','pons') or type(capital) is not int or capital <= 0 or len(policies) != 2:
            raise ValueError('sleeve_identity')
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,timeout=30,isolation_level=None,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.identity=dict(lane=lane,capital=capital,policies=policies,cohort=cohort,paper_only=True)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS sleeve_genesis(id INTEGER PRIMARY KEY,body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sleeve_positions(id TEXT PRIMARY KEY,body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sleeve_candidates(id TEXT PRIMARY KEY,generation INTEGER NOT NULL,body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sleeve_journal(seq INTEGER PRIMARY KEY,body TEXT NOT NULL,previous TEXT NOT NULL,hash TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS sleeve_journal_no_update BEFORE UPDATE ON sleeve_journal BEGIN SELECT RAISE(ABORT,'append_only'); END;
          CREATE TRIGGER IF NOT EXISTS sleeve_journal_no_delete BEFORE DELETE ON sleeve_journal BEGIN SELECT RAISE(ABORT,'append_only'); END;
          CREATE TRIGGER IF NOT EXISTS sleeve_genesis_no_update BEFORE UPDATE ON sleeve_genesis BEGIN SELECT RAISE(ABORT,'immutable_genesis'); END;
          CREATE TRIGGER IF NOT EXISTS sleeve_genesis_no_delete BEFORE DELETE ON sleeve_genesis BEGIN SELECT RAISE(ABORT,'immutable_genesis'); END;
        ''')
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO sleeve_genesis VALUES(1,?)',(canonical(self.identity),))
            if self.db.execute('SELECT body FROM sleeve_genesis').fetchone()[0]!=canonical(self.identity):
                raise ValueError('sleeve_genesis_drift')
            self.reconcile()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def _event(self,kind,row):
        old=self.db.execute('SELECT seq,hash FROM sleeve_journal ORDER BY seq DESC LIMIT 1').fetchone()
        seq,prev=(old[0]+1,old[1]) if old else (1,'0'*64)
        body=dict(kind=kind,row=row,identity=self.identity)
        self.db.execute('INSERT INTO sleeve_journal VALUES(?,?,?,?)',(seq,canonical(body),prev,digest([seq,prev,body])))
        if kind=='candidate':
            self.db.execute('INSERT OR REPLACE INTO sleeve_candidates VALUES(?,?,?)',(row['id'],row['generation'],canonical(row)))
        else:
            self.db.execute('INSERT OR REPLACE INTO sleeve_positions VALUES(?,?)',(row['id'],canonical(row)))

    def get(self,identity):
        row=self.db.execute('SELECT body FROM sleeve_positions WHERE id=?',(identity,)).fetchone()
        return json.loads(row[0]) if row else None

    def candidate(self,identity):
        row=self.db.execute('SELECT body FROM sleeve_candidates WHERE id=?',(identity,)).fetchone()
        return json.loads(row[0]) if row else None

    def observe(self,identity,*,strategy,at,state,evidence,regime):
        if strategy not in self.identity['policies']:
            raise ValueError('foreign_sleeve_strategy')
        with self.transaction():
            old=self.candidate(identity)
            if old and at<old['at']:
                raise ValueError('candidate_time_regression')
            payload=dict(strategy=strategy,at=at,state=state,evidence=evidence,regime=regime)
            if old and all(old[k]==v for k,v in payload.items()):
                return old
            row=dict(id=identity,generation=1 if old is None else old['generation']+1,**payload)
            self._event('candidate',row)
            return row

    def reserve(self,identity,*,strategy,amount,at,candidate=None,generation=None,regime=None):
        if strategy not in self.identity['policies'] or type(amount) is not int or amount<=0:
            raise ValueError('sleeve_reservation')
        with self.transaction():
            old=self.get(identity)
            if old:
                if old['status']=='settled':raise ValueError('terminal_reservation_reused')
                if all(old[k]==v for k,v in dict(strategy=strategy,amount=amount,candidate=candidate,generation=generation).items()):
                    return old
                raise ValueError('sleeve_reservation_conflict')
            if candidate is not None:
                current=self.candidate(candidate)
                if not current or current['generation']!=generation or current['state']!='qualified':
                    raise ValueError('superseded_reservation')
                from certification.survivor_risk import new_regime
                prior=[json.loads(raw) for raw, in self.db.execute('SELECT body FROM sleeve_positions')]
                for p in prior:
                    if p['strategy']==strategy and p['candidate']==candidate:
                        if p.get('cancelled'):continue
                        if p['status']!='settled' or not new_regime(p['regime'],regime):
                            raise ValueError('same_survivor_regime')
            if amount>self.reconcile()['available']:
                raise ValueError('sleeve_capital_exhausted')
            row=dict(id=identity,strategy=strategy,amount=amount,held=amount,at=at,
                     candidate=candidate,generation=generation,regime=regime,status='reserved',pnl=0)
            self._event('reserve',row)
            return row

    @contextmanager
    def commit_fence(self,identity):
        """Serialize supersession with the native atomic commit; no network here."""
        with self.transaction():
            row=self.get(identity)
            if row is None or row['status']!='reserved':
                raise ValueError('sleeve_reservation_missing')
            if row['candidate'] is not None:
                current=self.candidate(row['candidate'])
                if current['generation']!=row['generation'] or current['state']!='qualified':
                    raise ValueError('superseded_commit')
            yield row
            row=dict(row,status='filled')
            self._event('filled',row)

    def release(self,identity,*,pnl,at,terminal_hash,native_verified,cancelled=False):
        if native_verified is not True or type(pnl) is not int or not terminal_hash:
            raise ValueError('native_terminal_required')
        with self.transaction():
            row=self.get(identity)
            if row is None:raise ValueError('sleeve_reservation_missing')
            if row['status']=='settled':
                if row['terminal_hash']!=terminal_hash or row['pnl']!=pnl:
                    raise ValueError('duplicate_settlement_conflict')
                return row
            if pnl < -row['amount'] or at<row['at']:
                raise ValueError('sleeve_terminal_invariant')
            row=dict(row,status='settled',held=0,pnl=pnl,terminal_at=at,terminal_hash=terminal_hash,cancelled=cancelled)
            self._event('settle',row)
            return row

    def reconcile(self):
        positions,candidates,previous={}, {},'0'*64
        for expected,(seq,raw,prev,checksum) in enumerate(self.db.execute('SELECT * FROM sleeve_journal ORDER BY seq'),1):
            body=json.loads(raw);row=body['row'];kind=body['kind']
            if seq!=expected or prev!=previous or checksum!=digest([seq,prev,body]) or body['identity']!=self.identity:
                raise ValueError('sleeve_journal_corruption')
            target=candidates if kind=='candidate' else positions
            old=target.get(row['id'])
            if kind=='reserve' and old is not None:raise ValueError('sleeve_replay_duplicate')
            if kind in ('filled','settle') and (not old or old['status']=='settled'):
                raise ValueError('sleeve_replay_transition')
            if kind=='candidate' and row['generation']!=(1 if old is None else old['generation']+1):
                raise ValueError('sleeve_replay_generation')
            target[row['id']]=row;previous=checksum
        if positions!={i:json.loads(b) for i,b in self.db.execute('SELECT * FROM sleeve_positions')}:
            raise ValueError('sleeve_projection_corruption')
        if candidates!={i:json.loads(b) for i,_,b in self.db.execute('SELECT * FROM sleeve_candidates')}:
            raise ValueError('sleeve_candidate_corruption')
        held=sum(p['held'] for p in positions.values());realized=sum(p['pnl'] for p in positions.values())
        available=self.identity['capital']+realized-held
        if available<0:raise ValueError('sleeve_capital_invariant')
        return dict(capital=self.identity['capital'],available=available,reserved=held,realized=realized,
                    positions=len(positions),reconciled=True,final_hash=previous)

    def close(self):
        self.reconcile();self.db.close()
