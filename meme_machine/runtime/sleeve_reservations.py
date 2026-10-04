"""One durable reservation authority per existing directional sleeve.

Native ledgers remain accounting truth. Reservations are held until a verified
native terminal is supplied. A crash between native commit and observation leaves
capital held, never available twice. There is no cross-sleeve borrowing.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import threading

from meme_machine.runtime.journal import canonical, digest


class SleeveReservations:
    def __init__(self,path,*,lane,capital,policies,cohort):
        if lane not in ('pump','pons') or type(capital) is not int or capital <= 0 or len(policies) != 2:
            raise ValueError('sleeve_identity')
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.identity=dict(lane=lane,capital=capital,policies=policies,cohort=cohort,paper_only=True)
        from meme_machine.runtime.preserved_checkpoint import snapshot
        with snapshot(path,name=lane+'/directional-sleeve.sqlite',lane=lane) as preserved:
            try:
                self._open(path)
                if preserved:self._compact_preserved(*preserved)
            except BaseException:
                if hasattr(self,'db'):self.db.close()
                raise

    def _open(self,path):
        self.db=sqlite3.connect(path,timeout=30,isolation_level=None,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS sleeve_genesis(id INTEGER PRIMARY KEY,body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sleeve_positions(id TEXT PRIMARY KEY,body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sleeve_candidates(id TEXT PRIMARY KEY,generation INTEGER NOT NULL,body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sleeve_journal(seq INTEGER PRIMARY KEY,body TEXT NOT NULL,previous TEXT NOT NULL,hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sleeve_archive(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS opportunity_links(asset TEXT PRIMARY KEY,body TEXT NOT NULL,at INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS opportunity_receipts(id TEXT PRIMARY KEY,asset TEXT NOT NULL,at INTEGER NOT NULL,body TEXT NOT NULL);
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
        if old:seq,prev=old[0]+1,old[1]
        else:
            anchor=self._archive()
            seq,prev=(anchor['seq']+1,anchor['final_hash']) if anchor else (1,'0'*64)
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

    def opportunity(self,asset,*,identity,regime,status,at,decision=None):
        """Observation-only links. No Current outcome retires Survivor eligibility."""
        key=self.asset_key(asset)
        if key is None or regime not in ('current','survivor'):raise ValueError('opportunity_identity')
        with self.transaction():
            old=self.db.execute('SELECT body FROM opportunity_links WHERE asset=?',(key,)).fetchone()
            link=json.loads(old[0]) if old else dict(asset=key,current={},survivor={})
            link[regime]=dict(identity=identity,status=status,at=at)
            self.db.execute('INSERT OR REPLACE INTO opportunity_links VALUES(?,?,?)',(key,canonical(link),at))
            if decision is not None:
                receipt=canonical(dict(asset=key,identity=identity,regime=regime,status=status,at=at,decision=decision))
                receipt_id=canonical([key,identity,regime,status,at])
                prior=self.db.execute('SELECT body FROM opportunity_receipts WHERE id=?',(receipt_id,)).fetchone()
                if prior and prior[0]!=receipt:raise ValueError('opportunity_receipt_conflict')
                self.db.execute('INSERT OR IGNORE INTO opportunity_receipts VALUES(?,?,?,?)',(receipt_id,key,at,receipt))
            self.db.execute('DELETE FROM opportunity_receipts WHERE id IN (SELECT id FROM opportunity_receipts ORDER BY at DESC,id DESC LIMIT -1 OFFSET 10000)')
            protected={self.asset_key(json.loads(r).get('asset')) for r, in self.db.execute('SELECT body FROM sleeve_positions') if json.loads(r)['status']!='settled'}
            excess=self.db.execute('SELECT asset FROM opportunity_links ORDER BY at DESC,asset DESC LIMIT -1 OFFSET 10000').fetchall()
            self.db.executemany('DELETE FROM opportunity_links WHERE asset=?',((a,) for a, in excess if a not in protected))
            return link

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

    def sizing_basis(self,target_bps,*,minimum_bps=0):
        if (type(target_bps) is not int or not 0<target_bps<=10000
                or type(minimum_bps) is not int or not 0<=minimum_bps<=target_bps):
            raise ValueError('directional_sizing_bps')
        state=self.reconcile();equity=state['capital']+state['realized']
        database=os.environ.get('MM_PORTFOLIO_ACCOUNTING_DB')
        if database:
            from meme_machine.runtime.portfolio import NativePortfolio
            from meme_machine.runtime.usd_valuation import native_reader
            from decimal import Decimal,localcontext
            import time
            value=native_reader(self.identity['lane'])(int(time.time()))
            with localcontext() as context:
                context.prec=80
                usd=NativePortfolio(database,self.identity['lane']).equity()
                equity=int(usd*(Decimal(10)**value.decimals)/value.usd_per_unit)
        target=max(0,equity)*target_bps//10000
        return dict(genesis_capital=state['capital'],realized_pnl=state['realized'],
            realized_equity=equity,reserved=state['reserved'],available=state['available'],
            target_bps=target_bps,minimum_bps=minimum_bps,target=target,
            minimum=max(0,equity)*minimum_bps//10000,
            allocatable_target=min(target,state['available']))

    def asset_key(self,asset):
        if not asset:return None
        asset=str(asset).removeprefix(self.identity['lane']+':')
        if self.identity['lane']=='pons':asset=asset.lower()
        return self.identity['lane']+':'+asset

    def fill_blocker(self,asset,*,except_identity=None):
        key=self.asset_key(asset)
        if key is None:return None
        for raw, in self.db.execute('SELECT body FROM sleeve_positions'):
            row=json.loads(raw)
            if (row['id']!=except_identity and row['status']!='settled'
                    and self.asset_key(row.get('asset') or row.get('candidate'))==key):
                return row['id']
        return None

    def reserve(self,identity,*,strategy,amount,at,candidate=None,generation=None,regime=None,asset=None):
        if strategy not in self.identity['policies'] or type(amount) is not int or amount<=0:
            raise ValueError('sleeve_reservation')
        with self.transaction():
            old=self.get(identity)
            if old:
                if old['status']=='settled':raise ValueError('terminal_reservation_reused')
                if all(old[k]==v for k,v in dict(strategy=strategy,amount=amount,candidate=candidate,generation=generation).items()):
                    return old
                raise ValueError('sleeve_reservation_conflict')
            from meme_machine.runtime.lifecycle_identity import validate_new
            archive=self._archive()
            validate_new(identity,archived=(archive or {}).get('archived_entry_scopes',{}).get(strategy))
            if candidate is not None:
                current=self.candidate(candidate)
                if not current or current['generation']!=generation or current['state']!='qualified':
                    raise ValueError('superseded_reservation')
                from meme_machine.runtime.survivor_risk import new_regime
                prior=[json.loads(raw) for raw, in self.db.execute('SELECT body FROM sleeve_positions')]
                for p in prior:
                    if p['strategy']==strategy and p['candidate']==candidate:
                        if p.get('cancelled'):continue
                        if p['status']!='settled' or not new_regime(p['regime'],regime):
                            raise ValueError('same_survivor_regime')
            if amount>self.reconcile()['available']:
                raise ValueError('sleeve_capital_exhausted')
            key=self.asset_key(asset or candidate)
            if self.fill_blocker(key,except_identity=identity):
                raise ValueError('same_asset_exposure')
            row=dict(id=identity,strategy=strategy,amount=amount,held=amount,at=at,
                     candidate=candidate,generation=generation,regime=regime,status='reserved',pnl=0,
                     asset=key,scale_committed=False)
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
            if self.fill_blocker(row.get('asset'),except_identity=identity):
                raise ValueError('same_asset_exposure')
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

    def acknowledge_native(self,identity,*,basis,pnl,at,native_hash,native_verified):
        """Only replayed native cash flows release basis or compound realized P&L."""
        if (native_verified is not True or type(basis) is not int or basis<0
                or type(pnl) is not int or not native_hash):
            raise ValueError('native_cash_flow_required')
        with self.transaction():
            row=self.get(identity)
            if not row or row['status']=='settled' or at<row['at']:
                raise ValueError('native_cash_flow_state')
            pending=row.get('scale_reservation') or {}
            held=basis+(pending.get('amount',0) if pending.get('status')=='reserved' else 0)
            if basis>row['amount'] or pnl < -row['amount']:
                raise ValueError('native_cash_flow_invariant')
            if row.get('native_hash')==native_hash:return row
            row=dict(row,status='filled',held=held,pnl=pnl,native_hash=native_hash,native_at=at)
            self._event('native_sync',row)
            self.reconcile()
            return row

    def reserve_scale(self,identity,*,amount,original_basis,at,request):
        if type(amount) is not int or amount<=0 or not request:
            raise ValueError('scale_reservation')
        with self.transaction():
            row=self.get(identity)
            if not row or row['status']!='filled' or row.get('scale_committed'):
                raise ValueError('scale_lifecycle_state')
            prior=row.get('scale_reservation')
            if prior and prior['status']=='reserved':
                if (prior['amount'],prior['request'])==(amount,request):return prior
                raise ValueError('scale_reservation_conflict')
            state=self.sizing_basis(250)
            if (amount>state['target'] or amount>original_basis//2
                    or amount>state['available']
                    or original_basis+amount>max(0,state['realized_equity'])*750//10000):
                raise ValueError('scale_capital_limit')
            reservation=dict(amount=amount,original_basis=original_basis,at=at,request=request,status='reserved')
            row=dict(row,held=row['held']+amount,scale_reservation=reservation)
            self._event('scale_reserve',row)
            return reservation

    @contextmanager
    def scale_fence(self,identity,request):
        with self.transaction():
            row=self.get(identity);reservation=(row or {}).get('scale_reservation') or {}
            if (reservation.get('status')!='reserved' or reservation.get('request')!=request
                    or row.get('scale_committed')):
                raise ValueError('scale_reservation_missing')
            yield reservation
            row=dict(row,amount=row['amount']+reservation['amount'],scale_committed=True,
                scale_reservation=dict(reservation,status='committed'))
            self._event('scale_commit',row)

    def recover_scale(self,identity,*,request,committed,native_verified):
        """A native replay proves whether only the incremental hold may be released."""
        if native_verified is not True:raise ValueError('scale_recovery_proof')
        with self.transaction():
            row=self.get(identity);reservation=(row or {}).get('scale_reservation') or {}
            if reservation.get('request')!=request:raise ValueError('scale_recovery_identity')
            if reservation['status']!='reserved':
                if (reservation['status']=='committed')!=committed:raise ValueError('scale_recovery_conflict')
                return row
            if committed:
                row=dict(row,amount=row['amount']+reservation['amount'],scale_committed=True,
                    scale_reservation=dict(reservation,status='committed'))
            else:
                row=dict(row,held=row['held']-reservation['amount'],
                    scale_reservation=dict(reservation,status='cancelled'))
            self._event('scale_recover',row)
            return row

    def _archive(self):
        # Pre-upgrade preserved snapshots have no prefix table.
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='sleeve_archive'").fetchone():return None
        row=self.db.execute('SELECT body,hash FROM sleeve_archive WHERE id=1').fetchone()
        if row is None:return None
        value=json.loads(row[0])
        if digest(value)!=row[1] or value.get('identity')!=self.identity:
            raise ValueError('sleeve_archive_integrity')
        return value

    def _compact_preserved(self,path,authority):
        """Replace only the already-preserved prefix; concurrent new rows stay."""
        import hashlib
        with Path(path).open('rb') as source:
            if hashlib.file_digest(source,'sha256').hexdigest()!=authority['snapshot_sha256']:
                raise ValueError('sleeve_archive_snapshot_identity')
        source=object.__new__(SleeveReservations);source.identity=self.identity
        source.db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
        try:
            source.db.execute('BEGIN')
            proof=source.reconcile();prior=source._archive()
            last=source.db.execute('SELECT MAX(seq) FROM sleeve_journal').fetchone()[0]
            seq=last if last is not None else prior['seq'] if prior else 0
            if not seq:return False
            anchor=dict(identity=self.identity,seq=seq,final_hash=proof['final_hash'],
                positions={i:json.loads(b) for i,b in source.db.execute('SELECT * FROM sleeve_positions')},
                candidates={i:json.loads(b) for i,_,b in source.db.execute('SELECT * FROM sleeve_candidates')},
                authority=authority,previous_archive_hash=digest(prior) if prior else None)
            if prior:
                for key in ('folded','archived_entry_scopes'):
                    if key in prior:anchor[key]=prior[key]
        finally:source.db.close()
        with self.transaction():
            old=self._archive()
            if old and old['seq']>=seq:
                if old['seq']==seq and old['final_hash']!=anchor['final_hash']:
                    raise ValueError('sleeve_archive_prefix_conflict')
                if old['seq']>seq or old['authority']['state_hash']==authority['state_hash']:return False
            before=self.reconcile()
            row=self.db.execute('SELECT hash FROM sleeve_journal WHERE seq=?',(seq,)).fetchone()
            if not ((row and row[0]==anchor['final_hash'])
                    or (old and old['seq']==seq and old['final_hash']==anchor['final_hash'])):
                raise ValueError('sleeve_archive_prefix_conflict')
            self.db.execute('INSERT OR REPLACE INTO sleeve_archive VALUES(1,?,?)',(canonical(anchor),digest(anchor)))
            # DDL is transactional here; never use executescript (implicit commit).
            self.db.execute('DROP TRIGGER sleeve_journal_no_delete')
            self.db.execute('DELETE FROM sleeve_journal WHERE seq<=?',(seq,))
            self.db.execute("CREATE TRIGGER sleeve_journal_no_delete BEFORE DELETE ON sleeve_journal BEGIN SELECT RAISE(ABORT,'append_only'); END")
            if self.reconcile()!=before:raise ValueError('sleeve_archive_state_changed')
        return True

    def reconcile(self):
        archive=self._archive()
        positions,candidates,previous,offset=({}, {},'0'*64,0) if archive is None else (
            archive['positions'],archive['candidates'],archive['final_hash'],archive['seq'])
        for expected,(seq,raw,prev,checksum) in enumerate(self.db.execute('SELECT * FROM sleeve_journal ORDER BY seq'),offset+1):
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
        folded=archive.get('folded',{}) if archive else {}
        held=sum(p['held'] for p in positions.values());realized=folded.get('realized',0)+sum(p['pnl'] for p in positions.values())
        available=self.identity['capital']+realized-held
        if available<0:raise ValueError('sleeve_capital_invariant')
        return dict(capital=self.identity['capital'],available=available,reserved=held,realized=realized,
                    positions=folded.get('positions',0)+len(positions),reconciled=True,final_hash=previous)

    def close(self):
        self.reconcile();self.db.close()
