"""Integer, append-only paper accounting, isolated by run and strategy namespace.

No signer, transport, strategy thresholds or trade authority. Reservations enforce
one caller-supplied genesis across concurrent lifecycles instead of minting capital
for each trial. Runtime evidence belongs in the run artifact, never in git.
"""
from contextlib import contextmanager,nullcontext
import hashlib
import json
import sqlite3
import threading
from pathlib import Path


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _integer(value):
    if type(value) is not int or value < 0:
        raise ValueError('nonnegative_native_integer_required')
    return value


class PaperBook:
    def __init__(self, path, *, run_id, lane, policy_hash, initial):
        _integer(initial)
        self.identity = dict(run_id=run_id, lane=lane, policy_hash=policy_hash, initial=initial)
        self.lock = threading.RLock()
        from certification.preserved_checkpoint import snapshot
        native_lane={'pumpswap-survivor-momentum-v1':'pump','pons-postgrad-survivor-momentum-v1':'pons'}.get(lane)
        folder='pump-survivor' if native_lane=='pump' else 'pons-selective-continuation-v1-cohort/pons-survivor'
        preserved=snapshot(path,name=native_lane+'/'+folder+'/paper.sqlite',lane=native_lane) if native_lane else nullcontext(None)
        with preserved as source:
            try:
                self._open(path)
                if source:self._compact_preserved(*source)
            except BaseException:
                if hasattr(self,'db'):self.db.close()
                raise

    def _open(self,path):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=30, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS runtime_state(identity TEXT NOT NULL,key TEXT NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL,PRIMARY KEY(identity,key));
          CREATE TABLE IF NOT EXISTS genesis(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS positions(id TEXT PRIMARY KEY,body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS journal(seq INTEGER PRIMARY KEY,body TEXT NOT NULL,
            previous TEXT NOT NULL,hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS journal_archive(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,hash TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal
            BEGIN SELECT RAISE(ABORT,'append_only'); END;
          CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal
            BEGIN SELECT RAISE(ABORT,'append_only'); END;
          CREATE TRIGGER IF NOT EXISTS genesis_no_update BEFORE UPDATE ON genesis
            BEGIN SELECT RAISE(ABORT,'immutable_genesis'); END;
          CREATE TRIGGER IF NOT EXISTS genesis_no_delete BEFORE DELETE ON genesis
            BEGIN SELECT RAISE(ABORT,'immutable_genesis'); END;
        ''')
        self.db.execute('INSERT OR IGNORE INTO genesis VALUES(1,?)', (_json(self.identity),))
        if json.loads(self.db.execute('SELECT body FROM genesis').fetchone()[0]) != self.identity:
            raise ValueError('paper_book_namespace_or_genesis_mismatch')
        self.replay()

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

    def _load(self, identity):
        row = self.db.execute('SELECT body FROM positions WHERE id=?', (identity,)).fetchone()
        if not row:
            raise ValueError('paper_position_missing')
        return json.loads(row[0])

    def _record(self, position, action, at, evidence):
        _integer(at)
        old_at = position.get('last_at', at)
        if at < old_at:
            raise ValueError('paper_accounting_time_regression')
        position['last_at'] = at
        body = dict(identity=self.identity, action=action, at=at, position=position,
                    evidence=evidence, evidence_hash=_hash(evidence))
        row = self.db.execute('SELECT seq,hash FROM journal ORDER BY seq DESC LIMIT 1').fetchone()
        if row:seq,previous=row[0]+1,row[1]
        else:
            anchor=self._archive()
            seq,previous=(anchor['seq']+1,anchor['final_hash']) if anchor else (1,'0'*64)
        self.db.execute('INSERT INTO journal VALUES(?,?,?,?)',
                        (seq, _json(body), previous, _hash([seq, previous, body])))
        self.db.execute('INSERT OR REPLACE INTO positions VALUES(?,?)',
                        (position['id'], _json(position)))

    def reserve(self, identity, amount, at, evidence):
        _integer(amount)
        if amount == 0 or not identity.startswith(self.identity['run_id'] + ':'):
            raise ValueError('paper_lifecycle_identity_or_amount')
        with self.transaction():
            if self.db.execute('SELECT 1 FROM positions WHERE id=?', (identity,)).fetchone():
                raise ValueError('duplicate_paper_lifecycle')
            from certification.lifecycle_identity import validate_new
            anchor=self._archive()
            validate_new(identity,archived=anchor.get('archived_entry_scope') if anchor else None)
            if amount > self.reconcile()['cash']:
                raise ValueError('paper_capital_exhausted')
            position = dict(id=identity, status='reserved', reserved=amount, basis=0,
                            mark=0, tokens=0, realized=0, capital_unit_seconds=0,
                            capital_at_risk=amount, risk_at=at, last_at=at)
            if 'candidate' in evidence:position['candidate']=evidence['candidate']
            self._record(position, 'reserved', at, evidence)

    def transition(self, identity, action, at, *, amount=0, tokens=0, evidence=None):
        _integer(amount); _integer(tokens); _integer(at)
        with self.transaction():
            p = self._load(identity)
            if at < p['last_at']:
                raise ValueError('paper_accounting_time_regression')
            p['capital_unit_seconds'] += p['capital_at_risk'] * (at - p['risk_at'])
            p['risk_at'] = at
            if action == 'filled':
                if p['status'] != 'reserved' or amount > p['reserved'] or not amount or not tokens:
                    raise ValueError('invalid_paper_fill')
                p.update(status='open', reserved=0, basis=amount, mark=amount,
                         tokens=tokens, capital_at_risk=amount)
            elif action == 'cancelled':
                if p['status'] != 'reserved':
                    raise ValueError('invalid_paper_cancel')
                p.update(status='cancelled', reserved=0, capital_at_risk=0)
            elif action == 'strategy_graduation':
                if p['status'] != 'open' or (evidence or {}).get('authenticated') is not True:
                    raise ValueError('invalid_paper_graduation')
                # This is strategy-state lineage, not a fill or a cash flow.
            elif action == 'mark':
                if p['status'] != 'open':
                    raise ValueError('invalid_paper_mark')
                p['mark'] = amount
            elif action == 'partial_harvest':
                if p['status'] != 'open' or not tokens or tokens >= p['tokens']:
                    raise ValueError('invalid_paper_partial_harvest')
                old_tokens=p['tokens'];old_basis=p['basis']
                basis_removed=old_basis*tokens//old_tokens
                if basis_removed <= 0:
                    raise ValueError('paper_partial_harvest_basis_zero')
                p.update(
                    basis=old_basis-basis_removed,
                    mark=old_basis-basis_removed,
                    tokens=old_tokens-tokens,
                    realized=p['realized']+amount-basis_removed,
                    capital_at_risk=old_basis-basis_removed,
                )
            elif action == 'settled':
                if p['status'] != 'open':
                    raise ValueError('duplicate_or_invalid_paper_settlement')
                p.update(
                    status='settled',
                    realized=p['realized']+amount-p['basis'],
                    proceeds=amount,basis=0,mark=0,tokens=0,capital_at_risk=0,
                )
            else:
                raise ValueError('unknown_paper_transition')
            self._record(p, action, at, evidence or {})
            return self.reconcile()

    def reconcile(self):
        with self.lock:
            anchor=self._archive();folded=anchor.get('folded',{}) if anchor else {}
            positions = [json.loads(x[0]) for x in self.db.execute('SELECT body FROM positions')]
            realized = folded.get('realized',0)+sum(x['realized'] for x in positions)
            reserved = sum(x['reserved'] for x in positions)
            basis = sum(x['basis'] for x in positions)
            marks = sum(x['mark'] for x in positions)
            cash = self.identity['initial'] + realized - reserved - basis
            if cash < 0:
                raise ValueError('paper_capital_conservation')
            return dict(**self.identity, cash=cash, reserved=reserved, basis=basis,
                        realized=realized, unrealized=marks-basis,
                        marked_equity=cash+reserved+marks,
                        capital_unit_seconds=folded.get('capital_unit_seconds',0)+sum(x['capital_unit_seconds'] for x in positions),
                        capital_hour_denominator=3600,
                        open_positions=sum(x['status']=='open' for x in positions),
                        pending=sum(x['status']=='reserved' for x in positions),
                        settled=folded.get('settled',0)+sum(x['status']=='settled' for x in positions),
                        reconciled=True)

    def replay(self):
        """Verify immutable chain, then independently rebuild cash and occupations."""
        with self.lock:
            anchor=self._archive()
            positions,previous,count,cash=({},'0'*64,0,self.identity['initial']) if anchor is None else (
                anchor['positions'],anchor['final_hash'],anchor['seq'],anchor['cash'])
            for seq, raw, prior, checksum in self.db.execute('SELECT * FROM journal ORDER BY seq'):
                count += 1; body = json.loads(raw); p = body['position']; identity = p['id']
                if (seq != count or prior != previous or body['identity'] != self.identity
                        or checksum != _hash([seq, prior, body])
                        or body['evidence_hash'] != _hash(body['evidence'])):
                    raise ValueError('paper_journal_corruption')
                old = positions.get(identity); action = body['action']
                if action == 'reserved':
                    if old is not None or p['reserved'] > cash:
                        raise ValueError('paper_replay_duplicate_or_overdraw')
                    cash -= p['reserved']
                elif action == 'filled':
                    if not old or old['status'] != 'reserved':
                        raise ValueError('paper_replay_fill')
                    cash += old['reserved'] - p['basis']
                elif action == 'cancelled':
                    if not old or old['status'] != 'reserved':
                        raise ValueError('paper_replay_cancel')
                    cash += old['reserved']
                elif action == 'partial_harvest':
                    if not old or old['status'] != 'open':
                        raise ValueError('paper_replay_partial_harvest')
                    sold=old['tokens']-p['tokens']
                    if sold <= 0 or sold >= old['tokens']:
                        raise ValueError('paper_replay_partial_harvest_tokens')
                    basis_removed=old['basis']*sold//old['tokens']
                    proceeds=(p['realized']-old['realized'])+basis_removed
                    if (basis_removed <= 0
                            or p['basis'] != old['basis']-basis_removed
                            or p['capital_at_risk'] != p['basis']
                            or p['mark'] != p['basis']
                            or proceeds < 0):
                        raise ValueError('paper_replay_partial_harvest')
                    cash += proceeds
                elif action == 'settled':
                    if (not old or old['status'] != 'open'
                            or p['realized'] != old['realized']+p['proceeds']-old['basis']):
                        raise ValueError('paper_replay_settlement')
                    cash += p['proceeds']
                elif action == 'strategy_graduation':
                    if (not old or old['status'] != 'open'
                            or body['evidence'].get('authenticated') is not True
                            or any(p[k] != old[k] for k in
                                   ('status','reserved','basis','mark','tokens','realized'))):
                        raise ValueError('paper_replay_graduation')
                elif action != 'mark' or not old or old['status'] != 'open':
                    raise ValueError('paper_replay_transition')
                if cash < 0:
                    raise ValueError('paper_replay_negative_cash')
                positions[identity] = p; previous = checksum
            actual = {identity: json.loads(raw) for identity, raw in self.db.execute('SELECT * FROM positions')}
            if positions != actual or cash != self.reconcile()['cash']:
                raise ValueError('paper_projection_differs_from_replay')
            return dict(verified=True, events=count, final_hash=previous, cash=cash)

    def _archive(self):
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='journal_archive'").fetchone():return None
        row=self.db.execute('SELECT body,hash FROM journal_archive WHERE id=1').fetchone()
        if row is None:return None
        value=json.loads(row[0])
        if _hash(value)!=row[1] or value.get('identity')!=self.identity:
            raise ValueError('paper_archive_integrity')
        return value

    def _compact_preserved(self,path,authority,*,cost_reader=None,risk_reader=None):
        """Checkpoint only replayed bytes already in the exact native artifact."""
        with Path(path).open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=authority['snapshot_sha256']:
                raise ValueError('paper_archive_snapshot_identity')
        source=object.__new__(PaperBook);source.identity=self.identity;source.lock=threading.RLock()
        source.db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
        try:
            source.db.execute('BEGIN');proof=source.replay();prior=source._archive()
            positions={i:json.loads(b) for i,b in source.db.execute('SELECT * FROM positions')}
            from certification.survivor_commit import risk_record
            from certification.directional_accounting import execution_cost
            from certification.journal_proof import extend
            risk={} if prior is None else json.loads(_json(prior['risk_states']))
            summaries={} if prior is None else json.loads(_json(prior['journal_proofs']))
            for raw, in source.db.execute('SELECT body FROM journal ORDER BY seq'):
                event=json.loads(raw);identity=event['position']['id']
                summaries[identity]=extend([event],summaries.get(identity))
                state=(risk_reader or risk_record)(risk.get(identity),event)
                if state is not None:risk[identity]=state
            anchor=dict(identity=self.identity,seq=proof['events'],final_hash=proof['final_hash'],
                cash=proof['cash'],positions=positions,risk_states=risk,journal_proofs=summaries,
                execution_cost=(cost_reader or execution_cost)(source),authority=authority,
                previous_archive_hash=_hash(prior) if prior else None)
            if prior:
                for key in ('folded','archived_entry_scope'):
                    if key in prior:anchor[key]=prior[key]
        finally:source.db.close()
        with self.transaction():
            old=self._archive();seq=anchor['seq']
            if old and old['seq']>=seq:
                if old['seq']==seq and old['final_hash']!=anchor['final_hash']:
                    raise ValueError('paper_archive_prefix_conflict')
                if (old['seq']>seq or old['authority']['state_hash']==authority['state_hash']
                        or old.get('retirement_pending')):return False
            before=self.replay();accounting=self.reconcile()
            row=self.db.execute('SELECT hash FROM journal WHERE seq=?',(seq,)).fetchone()
            if not ((row and row[0]==anchor['final_hash'])
                    or (old and old['seq']==seq and old['final_hash']==anchor['final_hash'])
                    or (seq==0 and anchor['final_hash']=='0'*64)):
                raise ValueError('paper_archive_prefix_conflict')
            self.db.execute('INSERT OR REPLACE INTO journal_archive VALUES(1,?,?)',(_json(anchor),_hash(anchor)))
            self.db.execute('DROP TRIGGER journal_no_delete')
            self.db.execute('DELETE FROM journal WHERE seq<=?',(seq,))
            self.db.execute("CREATE TRIGGER journal_no_delete BEFORE DELETE ON journal BEGIN SELECT RAISE(ABORT,'append_only'); END")
            if self.replay()!=before or self.reconcile()!=accounting:raise ValueError('paper_archive_state_changed')
        return True

    def runtime_state(self,identity,key):
        with self.lock:
            row=self.db.execute('SELECT body,hash FROM runtime_state WHERE identity=? AND key=?',(identity,key)).fetchone()
            if row is None:return None
            value=json.loads(row[0])
            if _hash(value)!=row[1]:raise ValueError('pump_runtime_state_hash')
            return value

    def checkpoint_runtime(self,identity,key,value,*,claim=False):
        with self.transaction():
            self._load(identity)
            command='INSERT OR IGNORE' if claim else 'INSERT OR REPLACE'
            return bool(self.db.execute(command+' INTO runtime_state VALUES(?,?,?,?)',
                (identity,key,_json(value),_hash(value))).rowcount)

    def close(self):
        self.replay()
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        self.db.close()
