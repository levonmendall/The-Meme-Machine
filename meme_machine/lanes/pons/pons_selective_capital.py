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
from .pons_selective_ledger import STRATEGY_NAMESPACE, DECISION_CATEGORY, JOURNAL_CATEGORY

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
        self.recover_shared_terminals()

    def recover_shared_terminals(self,*,release_absent=False):
        from meme_machine.runtime.directional_sleeve import open_sleeve,native_terminal
        sleeve=open_sleeve('pons',self.capital)
        if sleeve is None:return
        with closing(sleeve),closing(self._connect()) as db:
            db.execute('BEGIN')
            verified=self._reconcile(db)
            native_ids=set()
            for raw, in db.execute('SELECT body FROM capital_positions'):
                row=json.loads(raw);held=sleeve.get(row['id'])
                native_ids.add(row['id'])
                if row['status']=='settled' and held and held['held']:
                    position=row.get('native_position',row.get('shared_terminal_position'))
                    if position is None or digest(position)!=row.get('native_settlement_hash'):
                        raise BoundaryError('selective_terminal_recovery_proof')
                    native_terminal(sleeve,row['id'],position,row['at'],verified=True)
            if release_absent:
                if hasattr(sleeve,'recover_unmaterialized'):
                    sleeve.recover_unmaterialized(native_ids,strategy=STRATEGY_NAMESPACE,verified=True)
                # Only the cohort startup, before lifecycle workers, can prove
                # no current reservation is concurrently being materialized.
                for raw, in sleeve.db.execute('SELECT body FROM sleeve_positions'):
                    held=json.loads(raw)
                    if held['strategy']==STRATEGY_NAMESPACE and held['held'] and held['id'] not in native_ids:
                        sleeve.release(held['id'],pnl=0,at=held['at'],native_verified=True,
                            terminal_hash=digest(dict(native_absent=held['id'],cohort_replay=verified)),cancelled=True)

    def _connect(self):
        db=sqlite3.connect(self.path,timeout=30,isolation_level=None)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def _reconcile(self,db):
        from meme_machine.runtime.pons_terminal_archive import anchor
        prefix=anchor(db)
        replay=json.loads(canonical((prefix or {}).get('positions',{})))
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
                if any(row.get(k)!=previous.get(k) for k in ('initial_reserved','decision_hash','trial_path','policy_hash','native_reservation_intent')):
                    raise BoundaryError('selective_cohort_journal_transition')
            elif action=='observe':
                if previous is None or previous['status']!='reserved' or any(
                    row.get(k)!=previous.get(k) for k in ('status','initial_reserved','at','decision_hash','trial_path','policy_hash','native_reservation_intent')
                ):
                    raise BoundaryError('selective_cohort_journal_transition')
                native=row.get('native_position',{})
                old=previous.get('native_position')
                if native.get('id')!=identity or native.get('experiment')!=STRATEGY_NAMESPACE or (old and native['version']<=old['version']):
                    raise BoundaryError('selective_cohort_native_sequence')
                expected_held=native['reserved'] if native['status']=='reserved' else native['remaining_cost']
                if row['reserved']!=expected_held or row['pnl']!=native['realized_pnl']:
                    raise BoundaryError('selective_cohort_native_cash_flow')
            else:raise BoundaryError('selective_cohort_journal_transition')
            replay[identity]=row
        projection={identity:json.loads(raw) for identity,raw in db.execute('SELECT id,body FROM capital_positions')}
        if projection!=replay:raise BoundaryError('selective_cohort_projection_mismatch')
        from meme_machine.runtime.pons_terminal_archive import anchor
        prefix=anchor(db);folded=(prefix or {}).get('folded',{})
        rows=list(replay.values())
        reserved=sum(x['reserved'] for x in rows)
        realized=folded.get('realized',0)+sum(x['pnl'] for x in rows)
        available=self.capital+realized-reserved
        from meme_machine.shared_capital.native_sleeve import cohort_backing
        shared=cohort_backing(db,rows)
        if available<0 and not shared:raise BoundaryError('selective_cohort_capital_invariant')
        observed=[x for x in rows if 'native_position' in x]
        complete=len(observed)==len(rows) and all(x['native_accounting']['replay_verified'] for x in observed)
        cash=self.capital+folded.get('realized',0)-sum(x['native_position']['cost'] for x in observed)+sum(x['native_position']['realized_proceeds'] for x in observed)
        basis=sum(x['native_position']['remaining_cost'] for x in observed)
        booked=folded.get('realized',0)+sum(x['native_position']['realized_pnl'] for x in observed)
        if complete and (cash<0 and not shared or self.capital+booked!=cash+basis):
            raise BoundaryError('selective_cohort_cash_basis_invariant')
        return dict(genesis=self.capital,available=available,reserved=reserved,realized=realized,
                    unsettled=sum(x['status']!='settled' for x in rows),positions=folded.get('positions',0)+len(rows),
                    policy_hash=POLICY_HASH,namespace=STRATEGY_NAMESPACE,
                    conservation=self.capital+realized==available+reserved,
                    native_observation_complete=complete,
                    cash=cash if complete else None,remaining_cost_basis=basis if complete else None,
                    booked_realized=booked if complete else None,
                    cash_basis_conservation=self.capital+booked==cash+basis if complete else None,
                    native_execution_cost=folded.get('native_execution_cost',0)+sum(x['native_accounting']['native_execution_cost'] for x in observed) if complete else None,
                    capital_at_risk_unit_nanoseconds=folded.get('capital_at_risk_unit_nanoseconds',0)+sum(x['native_accounting']['capital_at_risk_unit_nanoseconds'] for x in observed) if complete else None,
                    capital_integral_complete=complete and all(x['native_accounting']['integral_complete'] for x in observed))

    def observe(self,paper,position):
        """Post-commit observer. Never releases or increases allocation authority.

        The native transaction commits first. An observer failure propagates;
        the cohort reservation remains held, including ambiguous native exits.
        """
        identity=position['id']
        paper.positions()  # Verify immutable native replay against projection.
        event=paper.store.get(JOURNAL_CATEGORY,f'{identity}:{position["version"]}')
        decision=paper.store.get(DECISION_CATEGORY,identity)
        if event['position']!=position or position.get('experiment')!=STRATEGY_NAMESPACE or decision.get('policy_hash')!=POLICY_HASH:
            raise BoundaryError('selective_cohort_native_observation_mismatch')
        accounting=paper.accounting(identity)
        if not accounting['replay_verified']:
            raise BoundaryError('selective_cohort_native_replay_required')
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                self._reconcile(db)
                raw=db.execute('SELECT body FROM capital_positions WHERE id=?',(identity,)).fetchone()
                if not raw:raise BoundaryError('selective_cohort_reservation_missing')
                row=json.loads(raw[0])
                if row['decision_hash']!=digest(decision):raise BoundaryError('selective_cohort_decision_mismatch')
                if row.get('native_position')!=position:
                    row.update(native_position=position,native_journal_hash=digest(event),native_accounting=accounting,
                        reserved=position['reserved'] if position['status']=='reserved' else position['remaining_cost'],
                        pnl=position['realized_pnl'])
                    self._write(db,row,'observe');self._reconcile(db)
                db.execute('COMMIT')
            except BaseException:db.execute('ROLLBACK');raise
        from meme_machine.runtime.directional_sleeve import open_sleeve
        sleeve=open_sleeve('pons',self.capital)
        if sleeve is not None:
            with closing(sleeve):
                held=sleeve.get(identity);reservation=(held or {}).get('scale_reservation') or {}
                if reservation.get('status')=='reserved':
                    sleeve.recover_scale(identity,request=reservation['request'],native_verified=True,
                        committed=position.get('scale_request')==reservation['request'])
                if position['status'] in ('open','exit_pending'):
                    sleeve.acknowledge_native(identity,basis=position['remaining_cost'],pnl=position['realized_pnl'],
                        at=position['last_at'],native_hash=digest(position),native_verified=True)

        from meme_machine.runtime.pons_terminal_archive import checkpoint_capital
        checkpoint_capital(self)

    def reconcile(self):
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            result=self._reconcile(db)
            rows=[json.loads(raw) for raw, in db.execute('SELECT body FROM capital_positions')]
        stale=[]
        for row in rows:
            position=row.get('native_position')
            if position is None:
                stale.append(row['id']);continue
            # A crash between the native commit and its observer must not
            # leave a falsely reconciled consolidated snapshot. This check is
            # read-only and never creates missing native databases.
            try:
                uri=Path(row['trial_path']).resolve().as_uri()+'?mode=ro'
                with closing(sqlite3.connect(uri,uri=True,timeout=30)) as native:
                    value=native.execute('SELECT body FROM pons_selective_paper WHERE id=?',(row['id'],)).fetchone()
                    event=native.execute('SELECT body,hash FROM records WHERE category=? AND id=?',
                        (JOURNAL_CATEGORY,f'{row["id"]}:{position["version"]}')).fetchone()
                    if (not value or json.loads(value[0])!=position or not event
                            or digest(json.loads(event[0]))!=event[1] or event[1]!=row['native_journal_hash']):
                        stale.append(row['id'])
            except (OSError,sqlite3.Error,ValueError):stale.append(row['id'])
        result['unobserved_native_positions']=stale
        if stale:
            result.update(native_observation_complete=False,cash_basis_conservation=None,
                cash=None,remaining_cost_basis=None,booked_realized=None,native_execution_cost=None,
                capital_at_risk_unit_nanoseconds=None,capital_integral_complete=False)
        return result

    def _write(self,db,row,action):
        raw=canonical(row)
        db.execute('INSERT OR REPLACE INTO capital_positions VALUES(?,?)',(row['id'],raw))
        from meme_machine.runtime.pons_terminal_archive import anchor
        prefix=anchor(db)
        seq=max((prefix or {}).get('sequence',0),db.execute('SELECT COALESCE(MAX(seq),0) FROM capital_journal').fetchone()[0])+1
        db.execute('INSERT INTO capital_journal(seq,id,action,body,hash) VALUES(?,?,?,?,?)',(seq,row['id'],action,raw,digest(row)))

    def reserve(self,identity,amount,*,at,decision_hash,trial_path,native_reservation_intent=None):
        if type(amount) is not int or amount<=0:raise BoundaryError('selective_cohort_reservation_invalid')
        if native_reservation_intent is not None:
            intent=native_reservation_intent
            if (set(intent)!={'market','amount','gas_budget','now','features','kind'}
                    or intent['kind']!='natural' or intent['now']!=at
                    or type(intent['amount']) is not int or intent['amount']<=0
                    or type(intent['gas_budget']) is not int or intent['gas_budget']<0
                    or intent['amount']+intent['gas_budget']!=amount
                    or digest(intent['features'])!=decision_hash):
                raise BoundaryError('selective_cohort_native_intent_identity')
        from meme_machine.runtime.lifecycle_identity import validate_new
        from meme_machine.runtime.pons_terminal_archive import anchor
        with closing(self._connect()) as db:
            validate_new(identity,archived=(anchor(db) or {}).get('archived_entry_scope'))
        from meme_machine.runtime.directional_sleeve import open_sleeve
        sleeve=open_sleeve('pons',self.capital)
        if sleeve is not None:
            try:
                with closing(sleeve):sleeve.reserve(identity,strategy=STRATEGY_NAMESPACE,amount=amount,at=int(at),
                    asset=((native_reservation_intent or {}).get('features') or {}).get('token') or (native_reservation_intent or {}).get("market"),
                    funding_evidence=dict(native_reservation_intent=native_reservation_intent,decision_hash=decision_hash))
            except ValueError as exc:raise BoundaryError(str(exc)) from None
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                if db.execute('SELECT 1 FROM capital_positions WHERE id=?',(identity,)).fetchone():
                    raise BoundaryError('selective_cohort_duplicate_reservation')
                from meme_machine.shared_capital.native_sleeve import cohort_receipt
                funding=cohort_receipt(db,identity,amount)
                if amount>self._reconcile(db)['available'] and not funding:
                    raise BoundaryError('selective_cohort_capital_exhausted')
                row=dict(id=identity,status='reserved',reserved=amount,initial_reserved=amount,pnl=0,
                         at=int(at),decision_hash=decision_hash,trial_path=str(trial_path),policy_hash=POLICY_HASH)
                if funding:row['shared_funding']=funding
                if native_reservation_intent is not None:row['native_reservation_intent']=native_reservation_intent
                self._write(db,row,'reserve');db.execute('COMMIT');return row
            except BaseException:
                db.execute('ROLLBACK')
                if not db.execute('SELECT 1 FROM capital_positions WHERE id=?',(identity,)).fetchone():
                    sleeve=open_sleeve('pons',self.capital)
                    if sleeve is not None:
                        with closing(sleeve):
                            sleeve.release(identity,pnl=0,at=int(at),native_verified=True,
                                terminal_hash=digest(dict(native_absent=identity,cohort_replay=self._reconcile(db))),cancelled=True)
                raise

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
                if pnl < -max(row['initial_reserved'],position.get('cost',0)):raise BoundaryError('selective_cohort_loss_exceeds_reservation')
                if 'native_position' in row and row['native_position']!=position:
                    raise BoundaryError('selective_cohort_unobserved_settlement')
                row.update(status='settled',reserved=0,pnl=pnl,at=int(at),native_settlement_hash=digest(position),shared_terminal_position=position)
                self._write(db,row,'settle');rec=self._reconcile(db);db.execute('COMMIT')
            except BaseException:db.execute('ROLLBACK');raise
        from meme_machine.runtime.directional_sleeve import open_sleeve,native_terminal
        sleeve=open_sleeve('pons',self.capital)
        if sleeve is not None:
            with closing(sleeve):native_terminal(sleeve,identity,position,int(at),verified=True)
        return rec
