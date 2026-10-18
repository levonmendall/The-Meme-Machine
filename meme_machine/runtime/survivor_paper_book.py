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

_HELD_PAPER_ISSUER = object()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _integer(value):
    if type(value) is not int or value < 0:
        raise ValueError('nonnegative_native_integer_required')
    return value


class PaperBook:
    def __init__(self, path, *, run_id, lane, policy_hash, initial, held_population=None):
        _integer(initial)
        self.identity = dict(run_id=run_id, lane=lane, policy_hash=policy_hash, initial=initial)
        self.lock = threading.RLock()
        if held_population is not None:
            from .native_held_population import _NativePaperCapture
            if type(held_population) is not _NativePaperCapture:raise TypeError('native_held_capture_required')
            self._held_population = held_population
        from meme_machine.runtime.preserved_checkpoint import snapshot
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
        from meme_machine.runtime.operation_costs import connect
        self.db = connect(path, isolation_level=None, timeout=30, check_same_thread=False,
                          diagnostic_role='survivor_paper_book')
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
        requested=dict(self.identity)
        stored=json.loads(self.db.execute('SELECT body FROM genesis').fetchone()[0])
        self.decision_policy_hash=requested['policy_hash']
        if stored!=requested:
            from meme_machine.runtime.policy_compatibility import (regime_for,compatible_identity,
                selection,runtime_selection,save_runtime_selection,require_flat_rows,require_external_flat)
            if not compatible_identity(stored,requested,regime=regime_for(requested['lane'])):
                raise ValueError('paper_book_namespace_or_genesis_mismatch')
            self.identity=stored
            expected=selection(stored,requested)
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.replay()
                if not runtime_selection(self.db,expected):
                    require_flat_rows([json.loads(raw) for raw, in self.db.execute('SELECT body FROM positions')],kind='pump')
                    require_external_flat()
                    save_runtime_selection(self.db,expected)
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK');self.db.close();raise
        held=getattr(self,'_held_population',None)
        if held is not None:held._attach(self,path,self.identity,_HELD_PAPER_ISSUER)
        self.replay()
        from meme_machine.runtime.native_boundary import attach
        self.portfolio=attach(self,'pump' if 'pump' in self.identity['lane'] else 'pons')

    @contextmanager
    def transaction(self):
        with self.lock:
            held=getattr(self,'_held_population',None)
            self.db.execute('BEGIN IMMEDIATE')
            committed=False
            try:
                yield
                self.db.execute('COMMIT')
                committed=True
                if held is not None:held._commit(self,_HELD_PAPER_ISSUER)
                if getattr(self,'portfolio',None):self.portfolio.flush()
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute('ROLLBACK')
                    if held is not None:held._rollback(self,_HELD_PAPER_ISSUER)
                elif not committed and held is not None:held._uncertain(self,_HELD_PAPER_ISSUER)
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
        if hasattr(self,'decision_policy_hash'):
            body['decision_policy_hash']=self.decision_policy_hash
            from meme_machine.paper_policy_revision import revision_for_hash
            revision=revision_for_hash(self.decision_policy_hash)
            if revision is not None:body['policy_revision']=revision
        row = self.db.execute('SELECT seq,hash FROM journal ORDER BY seq DESC LIMIT 1').fetchone()
        if row:seq,previous=row[0]+1,row[1]
        else:
            anchor=self._archive()
            seq,previous=(anchor['seq']+1,anchor['final_hash']) if anchor else (1,'0'*64)
        boundary=getattr(self,'portfolio',None)
        if boundary:
            row=self.db.execute('SELECT body FROM positions WHERE id=?',(position['id'],)).fetchone()
            boundary.record(position['id'],action,position,json.loads(row[0]) if row else None,at=at,checksum=_hash([seq,previous,body]),data=evidence)
        self.db.execute('INSERT INTO journal VALUES(?,?,?,?)',
                        (seq, _json(body), previous, _hash([seq, previous, body])))
        self.db.execute('INSERT OR REPLACE INTO positions VALUES(?,?)',
                        (position['id'], _json(position)))
        held=getattr(self,'_held_population',None)
        if held is not None:held._stage(self,position,seq,previous,_hash([seq,previous,body]),_HELD_PAPER_ISSUER)

    def reserve(self, identity, amount, at, evidence):
        _integer(amount)
        if amount == 0 or not identity.startswith(self.identity['run_id'] + ':'):
            raise ValueError('paper_lifecycle_identity_or_amount')
        with self.transaction():
            if self.db.execute('SELECT 1 FROM positions WHERE id=?', (identity,)).fetchone():
                raise ValueError('duplicate_paper_lifecycle')
            from meme_machine.runtime.lifecycle_identity import validate_new
            anchor=self._archive()
            validate_new(identity,archived=anchor.get('archived_entry_scope') if anchor else None)
            from meme_machine.shared_capital.native_sleeve import funded
            funding=funded(self,identity,amount)
            if amount > self.reconcile()['cash'] and not funding:
                raise ValueError('paper_capital_exhausted')
            position = dict(id=identity, status='reserved', reserved=amount, basis=0,
                            mark=0, tokens=0, realized=0, capital_unit_seconds=0,
                            capital_at_risk=amount, risk_at=at, last_at=at)
            if funding:position['shared_funding']=funding
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
                         tokens=tokens, capital_at_risk=amount, entry_fill_at=at, entry_basis=amount)
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
            elif action == 'scale_add':
                request=(evidence or {}).get('request')
                if p.get('scale_request')==request and request:
                    if p['scale_cost']!=amount or p['scale_tokens']!=tokens:
                        raise ValueError('scale_duplicate_conflict')
                    return self.reconcile()
                from meme_machine.shared_capital.native_sleeve import funded
                funding=funded(self,identity,amount,scale=True)
                if (p['status']!='open' or p.get('scale_request') or not request
                        or not amount or not tokens or amount>self.reconcile()['cash'] and not funding):
                    raise ValueError('invalid_paper_scale_add')
                p.update(basis=p['basis']+amount,mark=p['mark']+amount,
                    tokens=p['tokens']+tokens,capital_at_risk=p['capital_at_risk']+amount,
                    scale_request=request,scale_cost=amount,scale_tokens=tokens)
                if funding:p['shared_scale_funding']=funding
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
            if cash < 0 and not self._shared_backing(positions):
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
            held=getattr(self,'_held_population',None)
            capture=held._replay_start(self,_HELD_PAPER_ISSUER) if held is not None else None
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
                    funding=p.get('shared_funding')
                    if funding:
                        from meme_machine.shared_capital.native_sleeve import verify_receipt
                        verify_receipt(self,funding,p['reserved'])
                    if old is not None or p['reserved'] > cash and not funding:
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
                elif action == 'scale_add':
                    e=body['evidence'];cost=p.get('scale_cost');quantity=p.get('scale_tokens')
                    if (not old or old['status']!='open' or old.get('scale_request')
                            or not cost or not quantity or p.get('scale_request')!=e.get('request')
                            or p['basis']!=old['basis']+cost or p['tokens']!=old['tokens']+quantity
                            or p['realized']!=old['realized']):
                        raise ValueError('paper_replay_scale_add')
                    cash-=cost
                    if p.get('shared_scale_funding'):
                        from meme_machine.shared_capital.native_sleeve import verify_receipt
                        verify_receipt(self,p['shared_scale_funding'],cost)
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
                if cash < 0 and not self._shared_backing([*positions.values(),p]):
                    raise ValueError('paper_replay_negative_cash')
                positions[identity] = p; previous = checksum
                if capture is not None:held._replay_row(self,capture,p,seq,prior,checksum)
            actual = {identity: json.loads(raw) for identity, raw in self.db.execute('SELECT * FROM positions')}
            if positions != actual or cash != self.reconcile()['cash']:
                raise ValueError('paper_projection_differs_from_replay')
            if capture is not None:held._replay_done(self,capture,positions,(count,previous))
            return dict(verified=True, events=count, final_hash=previous, cash=cash)

    def _shared_backing(self,positions):
        # Signed native cash is family attribution after shared funding, never
        # spendable cash. Every overdrawn native step needs a durable grant.
        from meme_machine.shared_capital.native_sleeve import verify_receipt,legacy_backing
        active=[p for p in positions if p['status'] in ('reserved','open')]
        if not active:return False
        for p in active:
            value=p.get('shared_funding')
            if value is None:
                if not legacy_backing(self,p['id'],p['reserved']+p['basis']):return False
                continue
            verify_receipt(self,value,value['maximum_native_units'])
            maximum=value['maximum_native_units']
            scale=p.get('shared_scale_funding')
            if scale:
                verify_receipt(self,scale,scale['maximum_native_units']);maximum+=scale['maximum_native_units']
            if p['reserved']+p['basis']>maximum:raise ValueError('native_shared_funding_overdraw')
        return True

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
            from meme_machine.runtime.survivor_commit import risk_record
            from meme_machine.runtime.directional_accounting import execution_cost
            from meme_machine.runtime.journal_proof import extend
            risk={} if prior is None else json.loads(_json(prior['risk_states']))
            summaries={} if prior is None else json.loads(_json(prior['journal_proofs']))
            from meme_machine.runtime.component_performance import extend_native,unavailable
            components={} if prior is None else json.loads(_json(prior.get('component_performance',{})))
            from meme_machine.lanes.pump.pump_acceleration_strategy import STRATEGY_ID as pump_current
            frontiers={} if prior is None else json.loads(_json(prior.get('current_attempt_frontiers',{})))
            if prior:
                for identity in prior['positions']:
                    components.setdefault(identity,unavailable(identity,'retired_component_detail'))
            for raw,event_hash in source.db.execute('SELECT body,hash FROM journal ORDER BY seq'):
                event=json.loads(raw);identity=event['position']['id']
                summaries[identity]=extend([event],summaries.get(identity))
                components[identity]=extend_native([event],components.get(identity),adapter='paper',lifecycle_id=identity)
                if self.identity['lane']==pump_current:
                    from meme_machine.lanes.pump.pump_attempt_reference import fold_terminal_attempt
                    fold_terminal_attempt(frontiers,event,event_hash,summaries[identity],components[identity],self.identity)
                state=(risk_reader or risk_record)(risk.get(identity),event)
                if state is not None:risk[identity]=state
            anchor=dict(identity=self.identity,seq=proof['events'],final_hash=proof['final_hash'],
                cash=proof['cash'],positions=positions,risk_states=risk,journal_proofs=summaries,
                component_performance=components,
                execution_cost=(cost_reader or execution_cost)(source),authority=authority,
                previous_archive_hash=_hash(prior) if prior else None)
            if self.identity['lane']==pump_current:anchor['current_attempt_frontiers']=frontiers
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
            from meme_machine.runtime.learning import lifecycle
            import time
            for identity,position in positions.items():
                lifecycle(self.db,identity,self.identity['lane'],time.time(),
                          dict(position,risk_state=risk.get(identity),component_performance=components.get(identity)),
                          (json.loads(raw) for raw, in self.db.execute(
                           "SELECT body FROM journal WHERE seq<=? AND json_extract(body,'$.position.id')=? ORDER BY seq",(seq,identity))))
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
