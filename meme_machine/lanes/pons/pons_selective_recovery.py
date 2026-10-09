"""Atomic current-Pons controller checkpoints; recovery grants no entry authority."""
import json
import fcntl
from functools import wraps
from pathlib import Path
from dataclasses import asdict
from types import SimpleNamespace

from . import BoundaryError
from .evidence import Store, canonical, digest
from .protocols import PoolKey
from .pons_selective_continuation import POLICY_HASH, EXIT_POLICY
from .pons_selective_ledger import SelectivePaper, GENESIS_CATEGORY, JOURNAL_CATEGORY
from .pons_selective_capital import CohortCapital

BASE='pons_selective_recovery_base'
SCHEMA='pons-selective-controller-v1'
GROUPS='pons_selective_controller_groups'


def exclusive_lifecycle(function):
    from inspect import isgeneratorfunction
    if isgeneratorfunction(function):
        @wraps(function)
        def steps(*args,db_path,**kwargs):
            path=Path(str(db_path)+'.controller.lock');path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('a+b') as handle:
                try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise BoundaryError('selective_controller_already_running') from None
                return (yield from function(*args,db_path=db_path,**kwargs))
        return steps
    @wraps(function)
    def locked(*args,db_path,**kwargs):
        # The OS releases this nonblocking ownership fence after a process crash.
        path=Path(str(db_path)+'.controller.lock');path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a+b') as handle:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise BoundaryError('selective_controller_already_running') from None
            return function(*args,db_path=db_path,**kwargs)
    return locked


class LifecycleState(SimpleNamespace):
    @classmethod
    def create(cls,store,identity,evaluation,capital,gas_units,*,opened_at,last_block):
        # Authentication identity survives; mutable acquisition reports and entry-only
        # curve snapshots cannot authorize another entry after a restart.
        candidate=evaluation['candidate']
        vector=evaluation['vector']
        saved=dict(token=evaluation['token'],curve=evaluation['curve'],
            source_transaction=evaluation['source_transaction'],
            candidate={k:candidate[k] for k in ('curve','token','auth','record') if k in candidate},
            vector={k:vector[k] for k in ('current_threshold_pass','policy_hash','trajectory','demand')})
        saved['candidate']['report']={}
        for k in ('candidate_plane_path','candidate_broker_identity','candidate_broker_generation'):
            if k in evaluation:saved[k]=evaluation[k]
        base=dict(schema=SCHEMA,identity=identity,policy_hash=POLICY_HASH,capital=capital,
            gas_units=gas_units,evaluation=saved,opened_at=opened_at)
        store.put(BASE,identity,base)
        state=cls(identity=identity,base_hash=digest(base),opened_at=opened_at,
            last_block=last_block,transition=None,v4_key=None,graduation_at=None,
            graduation_block=None,post_grad_checked=False,partial_taken=False,
            high_water=-10**9,high_at=opened_at,last_curve_reference=None,
            frozen_eta=vector['trajectory'].get('graduation_eta_seconds'),
            preholders={str(r['group']).lower() for r in evaluation['market_events']},
            entry_largest=int(vector['demand']['largest_buyer_flow_bps']),seen_v4_buyers=set(),
            pending_transition_exit_reason=None,recovery_exit_reason=None,recovery_streak=0,
            pregrad_soft_deterioration_streak=0,runner_soft_deterioration_streak=0,
            pending_action=None,bridged=False,bridged_at=None,bridge_deadline=None,
            first_tail_crossed_at=None,scale_committed=False,bridge_probe_failed=False)
        cls._table(store)
        return state

    @staticmethod
    def _table(store):
        store.db.execute(f'''CREATE TABLE IF NOT EXISTS {GROUPS}(
            identity TEXT NOT NULL,kind TEXT NOT NULL,value TEXT NOT NULL,
            PRIMARY KEY(identity,kind,value))''')

    def acknowledge(self,position):
        saved=position.get('controller_state')
        if saved is not None:
            self.partial_taken=saved['partial_taken']
            self.pending_action=saved['pending_action']

    def remember_action(self,action,position):
        if action['action'] in ('partial_exit','full_exit'):
            self.pending_action=dict(reason=action['reason'],exit_tokens=action['exit_tokens'],
                before_tokens=position['tokens'])
            self.recovery_exit_reason=action['reason']
        else:self.pending_action=None

    def checkpoint(self,paper,position,action,now):
        if not paper.store.db.in_transaction:
            raise BoundaryError('selective_controller_nonatomic_checkpoint')
        if position['id']!=self.identity:
            raise BoundaryError('selective_controller_identity')
        # Infer the completed partial from the actual atomic quantity update, not
        # from the caller receiving an acknowledgement after COMMIT.
        partial=bool(position['entry_tokens'] and 0<position['tokens']<position['entry_tokens'])
        data={k:v for k,v in vars(self).items() if k not in ('preholders','seen_v4_buyers','v4_key')}
        data.update(schema=SCHEMA,policy_hash=POLICY_HASH,partial_taken=self.partial_taken or partial,
            v4_key=asdict(self.v4_key) if self.v4_key else None,
            scale_committed=getattr(self,'scale_committed',False) or bool(position.get('scale_request')))
        if action in ('exit','liquidity_writeoff'):data['pending_action']=None
        # Exact buyer identities are normalized once rather than copied into every
        # 32KiB journal row. Their digest is bound to the native hash chain.
        for kind in ('preholders','seen_v4_buyers'):
            values=sorted(getattr(self,kind))
            paper.store.db.executemany(f'INSERT OR IGNORE INTO {GROUPS} VALUES(?,?,?)',
                ((self.identity,kind,v) for v in values))
            data[kind]=dict(count=len(values),sha256=digest(values))
        return json.loads(canonical(data))

    @classmethod
    def restore(cls,paper,identity):
        position=paper._get(identity)  # validates complete native journal/economic replay
        raw=position.get('controller_state')
        base=paper.store.get(BASE,identity)
        if (not raw or not base or raw.get('schema')!=SCHEMA
                or raw.get('identity')!=identity or base.get('identity')!=identity
                or raw.get('policy_hash')!=POLICY_HASH or base.get('policy_hash')!=POLICY_HASH
                or raw.get('base_hash')!=digest(base)):
            raise BoundaryError('selective_controller_recovery_identity')
        entries=[paper.store.get(JOURNAL_CATEGORY,key) for key, in paper.store.db.execute(
            'SELECT id FROM records WHERE category=?',(JOURNAL_CATEGORY,))]
        entries=[e for e in entries if e['position']['id']==identity and e['action']=='entry']
        from meme_machine.runtime.storage import pons_prefix
        retained=pons_prefix(paper).get(identity,{}).get('entry')
        if retained:entries=[retained]
        if len(entries)!=1 or entries[0]['at']!=raw['opened_at'] or raw['opened_at']!=base['opened_at']:
            raise BoundaryError('selective_controller_original_hold_clock')
        data=dict(raw);data.pop('schema');data.pop('policy_hash')
        for kind in ('preholders','seen_v4_buyers'):
            values=[r[0] for r in paper.store.db.execute(
                f'SELECT value FROM {GROUPS} WHERE identity=? AND kind=? ORDER BY value',(identity,kind))]
            if raw[kind]!=dict(count=len(values),sha256=digest(values)):
                raise BoundaryError('selective_controller_group_replay')
            data[kind]=set(values)
        data['v4_key']=PoolKey(**raw['v4_key']) if raw['v4_key'] else None
        if bool(data['transition'])!=bool(data['v4_key']):
            raise BoundaryError('selective_controller_transition_identity')
        if 0<position['tokens']<position['entry_tokens'] and not data['partial_taken']:
            raise BoundaryError('selective_controller_partial_replay')
        return cls(**data)


def settle_recovered(guard,paper,position,*,at):
    """Verify an acknowledged settlement; repair a lost cohort/sleeve acknowledgement."""
    from contextlib import closing
    guard.observe(paper,position)
    with closing(guard._connect()) as db:
        row=json.loads(db.execute('SELECT body FROM capital_positions WHERE id=?',(position['id'],)).fetchone()[0])
    if row['status']=='settled':
        if row.get('native_settlement_hash')!=digest(position):
            raise BoundaryError('selective_recovery_settlement_identity')
        guard.recover_shared_terminals()
        return guard.reconcile()
    return guard.settle(position['id'],position,at=at)


def recovery_evaluation(base,db_path):
    evaluation=json.loads(canonical(base['evaluation']))
    if evaluation.get('candidate_plane_path'):
        from meme_machine.runtime.robinhood.plane import plane_path
        path=plane_path(Path(db_path).parent/'candidate-evidence.sqlite')
        if not path.is_file():raise BoundaryError('selective_recovery_candidate_plane_missing')
        # Only the local artifact locator changes. Candidate, policy, ledger and
        # source identities remain bound by the original immutable base record.
        evaluation['candidate_plane_path']=str(path)
    return evaluation


@exclusive_lifecycle
def resume_lifecycle(endpoint,*,db_path,capital_path=None,slice_seconds=None,exceptional_context=None,_steps=False):
    """Reconcile and manage one existing native lifecycle; never reserve or enter."""
    from .pons_selective_paper import _run_lifecycle,STRATEGY_NAMESPACE,STRATEGY_CAPITAL_QUOTE,_cancel_proven_unfilled
    if slice_seconds is not None and not 1<=slice_seconds<=3300:
        raise BoundaryError('selective_recovery_slice_bound')
    store=Store(str(db_path),max_records=8192)
    try:
        genesis=store.get(GENESIS_CATEGORY,STRATEGY_NAMESPACE)
        if not genesis or genesis['natural_policy_hash']!=POLICY_HASH:
            raise BoundaryError('selective_recovery_genesis')
        paper=SelectivePaper(store,STRATEGY_NAMESPACE,genesis['capital'],
            delay=EXIT_POLICY['entry_delay_seconds'],natural_policy_hash=POLICY_HASH)
        positions=paper.positions()
        if not positions and capital_path:
            # Crash after cohort reserve and before native reserve. The original
            # immutable intent repairs only the missing reservation receipt;
            # the following reserved-state path cancels it without any provider.
            from contextlib import closing
            guard=CohortCapital(capital_path,STRATEGY_CAPITAL_QUOTE)
            with closing(guard._connect()) as db:
                db.execute('BEGIN');guard._reconcile(db)
                rows=[json.loads(raw) for raw, in db.execute('SELECT body FROM capital_positions')]
            rows=[r for r in rows if Path(r['trial_path']).resolve()==Path(db_path).resolve()]
            if len(rows)!=1:raise BoundaryError('selective_recovery_unfilled_cohort_identity')
            row=rows[0];intent=row.get('native_reservation_intent')
            if (row['status']!='reserved' or row.get('native_position') is not None
                    or not isinstance(intent,dict) or digest(intent.get('features'))!=row['decision_hash']
                    or intent.get('now')!=row['at']
                    or intent.get('amount',0)+intent.get('gas_budget',0)!=row['reserved']):
                raise BoundaryError('selective_recovery_unfilled_native_intent')
            paper.on_commit=lambda book,p:guard.observe(book,p)
            paper.reserve(row['id'],**intent)
            positions=paper.positions()
        if len(positions)!=1:raise BoundaryError('selective_recovery_position_identity')
        p=positions[0];identity=p['id']
        if p['status']=='settled' and not p['entry_tokens']:
            guard=CohortCapital(capital_path,STRATEGY_CAPITAL_QUOTE) if capital_path else None
            if guard:settle_recovered(guard,paper,p,at=p['last_at'])
            return dict(status='entry_failed',entry_authority=False,final_position=p,
                reconciliation=paper.reconcile())
        if p['status']=='reserved':
            guard=CohortCapital(capital_path,STRATEGY_CAPITAL_QUOTE) if capital_path else None
            if guard:paper.on_commit=lambda book,p:guard.observe(book,p)
            cancelled=_cancel_proven_unfilled(paper,identity,guard,'restart_unfilled_reservation')
            return dict(status='entry_failed',entry_authority=False,final_position=cancelled,
                reconciliation=paper.reconcile())
        LifecycleState.restore(paper,identity)
        base=store.get(BASE,identity)
        evaluation=recovery_evaluation(base,db_path)
        if p['status']=='settled':
            result=dict(status='settled',resumed=True,entry_authority=False,
                final_position=p,reconciliation=paper.reconcile(),realized_pnl_quote=p['pnl'])
            if capital_path:
                guard=CohortCapital(capital_path,STRATEGY_CAPITAL_QUOTE)
                result['cohort_reconciliation']=settle_recovered(guard,paper,p,at=p['last_at'])
            if evaluation.get('candidate_plane_path'):
                from meme_machine.runtime.robinhood.plane import project_native_position
                project_native_position(evaluation['candidate_plane_path'],'pons',
                    evaluation['candidate_broker_identity'],p,ledger_path=db_path,policy=POLICY_HASH)
            return result
    finally:store.close()
    if _steps:
        from .pons_selective_paper import _run_lifecycle_steps
        _run_lifecycle=_run_lifecycle_steps
    return _run_lifecycle(endpoint,evaluation,db_path=db_path,capital_path=capital_path,
        _recovery=base,slice_seconds=slice_seconds,exceptional_context=exceptional_context)


@exclusive_lifecycle
def resume_lifecycle_steps(endpoint,*,db_path,capital_path=None,exceptional_context=None):
    """The same recovery checks, with an idle controller yielding its worker."""
    result=resume_lifecycle.__wrapped__(endpoint,db_path=db_path,capital_path=capital_path,
        exceptional_context=exceptional_context,_steps=True)
    if isinstance(result,dict):return result
    return (yield from result)


def _pending_recoveries(root,qualifiers,lifecycles):
    """Restore native trial ownership before the cohort admits another candidate."""
    from contextlib import closing
    import re
    from meme_machine.runtime.robinhood.pons import coalesce_lifecycle_rows
    from .pons_selective_paper import STRATEGY_CAPITAL_QUOTE
    root=Path(root)
    capital_path=root/'pons-selective-cohort-capital.sqlite'
    guard=CohortCapital(capital_path,STRATEGY_CAPITAL_QUOTE)
    with closing(guard._connect()) as db:
        guard._reconcile(db)
        rows=[json.loads(raw) for raw, in db.execute('SELECT body FROM capital_positions')]
    completed={r['index']:r for r in coalesce_lifecycle_rows(lifecycles) if 'index' in r}
    qualified={r['index']:r for r in qualifiers}
    pending=[]
    for row in rows:
        path=Path(row['trial_path'])
        match=re.fullmatch(r'trial-(\d+)\.sqlite',path.name)
        if not match or path.resolve().parent!=root.resolve() or not path.is_file():
            raise BoundaryError('selective_recovery_trial_path_identity')
        index=int(match.group(1));prior=completed.get(index)
        if row['status']=='settled' and prior and prior.get('status') in ('settled','entry_failed'):
            continue
        qualifier=qualified.get(index)
        if not qualifier or qualifier.get('vector',{}).get('policy_hash')!=POLICY_HASH:
            raise BoundaryError('selective_recovery_qualifier_identity')
        pending.append((index,path,qualifier,prior))
    if len({q[2]["curve"] for q in pending})!=len(pending):
        raise BoundaryError("selective_recovery_duplicate_curve")
    return pending,guard,capital_path


def _resume_receipt(endpoint,capital_path,pending):
    index,path,qualifier,prior=pending
    life=dict(prior or {})
    life.update(resume_lifecycle(endpoint,db_path=path,capital_path=capital_path))
    life.update(index=index,curve=qualifier['curve'],token=qualifier['token'],
        source_transaction=qualifier['source_transaction'],
        recovery_replaces_index=index,entry_authority=False)
    position=life.get('final_position') or {}
    life['lifecycle_id']=position.get('id',life.get('lifecycle_id'))
    return life


def _resume_receipt_steps(endpoint,capital_path,pending):
    index,path,qualifier,prior=pending
    life=dict(prior or {})
    life.update((yield from resume_lifecycle_steps(endpoint,db_path=path,capital_path=capital_path)))
    life.update(index=index,curve=qualifier['curve'],token=qualifier['token'],
        source_transaction=qualifier['source_transaction'],
        recovery_replaces_index=index,entry_authority=False)
    position=life.get('final_position') or {}
    life['lifecycle_id']=position.get('id',life.get('lifecycle_id'))
    return life


def submit_existing_lifecycles(endpoint,root,qualifiers,lifecycles,*,pool):
    """Validate all durable ownership, then use the cohort's bounded lifecycle pool.

    Existing reservations remain authoritative while discovery continues. The
    caller collects these futures through the same terminal/checkpoint path used
    by newly admitted lifecycles. Recovery has no entry authority.
    """
    pending,_,capital_path=_pending_recoveries(root,qualifiers,lifecycles)
    return [(row[0],row[2]['curve'],pool.submit(_resume_receipt,endpoint,capital_path,row))
            for row in pending]


def recover_existing_lifecycles(endpoint,root,qualifiers,lifecycles,*,on_recovered):
    """Synchronous no-entry continuation for callers without discovery authority."""
    from .pons_current_workers import LifecyclePool
    from meme_machine.runtime.robinhood.pons import coalesce_lifecycle_rows
    pending,guard,capital_path=_pending_recoveries(root,qualifiers,lifecycles)
    receipts=[]
    with LifecyclePool(max_workers=8) as pool:
        futures=[pool.submit(_resume_receipt,endpoint,capital_path,row) for row in pending]
        for future in futures:
            life=future.result();on_recovered(life);receipts.append(life)
    merged=coalesce_lifecycle_rows(lifecycles+receipts)
    rec=guard.reconcile()
    if rec['unsettled'] or rec['reserved'] or not rec.get('cash_basis_conservation'):
        raise BoundaryError('selective_recovery_incomplete_exposure')
    return merged
