"""Read-only native ledger replay after workers stop, including cancellation.

Never creates a book, posts a settlement, releases a reserve, or uses market I/O.
Missing or inconsistent evidence is an explicit failure, never a zero balance.
"""
import argparse
from contextlib import closing,chdir
import json
from pathlib import Path
import sqlite3
import sys
import threading

# Direct script execution from an isolated native worktree still needs the
# certified neutral accounting helpers, after the native import root.
sys.path.append(str(Path(__file__).resolve().parents[1]))


def connect(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,
                           isolation_level=None,timeout=10)


def meteora_handoff(events,accounting,replay):
    """Prove that one open Meteora journal can resume without inventing state."""
    if accounting.get('unsettled')!=1 or replay.get('verified') is not True:
        return None
    last={};entries={}
    for event in events:
        identity=event.get('identity')
        if not identity:continue
        last[identity]=event.get('action')
        if event.get('action')=='entry':entries[identity]=event
    open_ids=[identity for identity,action in last.items()
              if action not in ('cancel','settle','writeoff')]
    if len(open_ids)!=1 or open_ids[0] not in entries:
        return None
    identity=open_ids[0];entry=entries[identity]
    data=entry.get('data') or {}
    required=('policy','features','entry_state','position','mark')
    if any(not isinstance(data.get(key),dict) for key in required):
        return None
    marks=[event for event in events
           if event.get('identity')==identity and event.get('action')=='mark']
    for event in marks:
        body=event.get('data') or {}
        tape=body.get('tape');progress=body.get('strategy_progress')
        if (not isinstance(tape,dict) or not tape.get('lineage')
                or not isinstance(tape.get('terminal'),dict)
                or not isinstance(progress,dict)
                or type(progress.get('observed_seconds')) is not int
                or type(progress.get('elapsed_seconds')) is not int
                or not isinstance(progress.get('collapse_streaks'),dict)
                or not isinstance(progress.get('raw_exit_reasons'),list)
                or not isinstance(progress.get('eligible_exit_reasons'),list)
                or not isinstance(progress.get('effective_start_hash'),str)):
            return None
    return dict(
        schema='meteora-durable-position-handoff-v1',
        lane='meteora',lifecycle_id=identity,
        mark_count=len(marks),
        verified_hold_seconds=(0 if not marks else
            int(marks[-1]['data']['strategy_progress']['elapsed_seconds'])),
        accounting_reconciled=True,
        economic_replay_verified=True,
        append_only_journal=True,
        policy_hash=accounting.get('genesis',{}).get('policy_hash'),
    )


def ramses_handoff(root,positions):
    """Read-only binding of the existing native position to its durable controller."""
    from certification.journal import digest
    if len(positions)!=1:return None
    native=positions[0];position=native['position']
    path=Path(root)/'robinhood-ramses-continuation.json'
    if not path.is_file() or path.is_symlink():return None
    state=json.loads(path.read_text())
    if (state.get('schema')!='ramses-position-continuation-v1'
            or state.get('lifecycle_id')!=position['id']
            or Path(state.get('ledger_path','')).name!=native['book_name']
            or state.get('paper_capital')!=native['paper_capital']
            or state.get('quote_asset')!=native['quote_asset']
            or state.get('entry_at')!=native['reserved_at']
            or str(state.get('pool','')).lower()!=position['pool']
            or type(state.get('entry_block')) is not int or state['entry_block']<=0):
        return None
    effective=state;proposal=position['proposal_hash'];intent=state.get('pending_native_checkpoint')
    if intent:
        previous=intent.get('previous_version');detail=intent.get('detail') or {}
        if (intent.get('identity')!=position['id'] or type(previous) is not int
                or position['version'] not in (previous,previous+1)
                or (position['version']==previous+1 and
                    (position.get('last_controller')!=detail or position.get('at')!=intent.get('at')))):
            return None
        effective=intent.get('next_state') or {}
        if (effective.get('lifecycle_id')!=position['id']
                or effective.get('entry_at')!=native['reserved_at']):return None
        if intent.get('action')=='rebalance':proposal=detail.get('proposal_hash')
    elif state.get('last_native_version') is not None and state['last_native_version']!=position['version']:
        return None
    elif state.get('last_native_version') is None and position.get('last_controller') is not None:
        return None
    pending=effective.get('pending_rebalance') or {}
    decisions=(effective.get('decision'),pending.get('old_decision'),pending.get('new_decision'))
    if (not proposal or not any(isinstance(d,dict) and (d.get('freeze') or {}).get('proposal_hash')==proposal for d in decisions)
            or effective.get('position_phase') not in ('deployed','flat_quote')
            or type(effective.get('segment_start')) is not int or effective['segment_start']<=0
            or type(effective.get('current_capital')) is not int or effective['current_capital']<=0
            or not isinstance(effective.get('segments',[]),list)):
        return None
    return dict(schema='ramses-durable-position-handoff-v1',lane='ramses',
        lifecycle_id=position['id'],native_version=position['version'],entry_at=native['reserved_at'],
        ledger_name=native['book_name'],quote_asset=native['quote_asset'],controller_hash=digest(state),
        recoverable_checkpoint_intent=bool(intent),entry_authority=False)


def pump_current_handoff(book):
    """Use the native startup reconstruction without issuing provider or pin writes."""
    from types import SimpleNamespace
    from tests import pump_acceleration_natural_prospective as strategy
    from meme_machine.pump_acceleration_confirmations import ConfirmationBook
    from certification.decision_conformance import restoring_recorded_state
    plane=SimpleNamespace(interest=lambda *args,**kwargs:None)
    with restoring_recorded_state():
        _,_,pending,active,_=strategy.restore_runtime(book,plane,ConfirmationBook({},60),bind_allocation=False)
    if pending or not active:return None
    return dict(schema='pump-current-controller-handoff-v1',entry_authority=False,
        positions=[dict(id=row['lifecycle'].lifecycle_id,opened_at=row['opened'])
                   for row in active.values()],accounting_reconciled=True)


def pons_current_handoff(root,capital_path):
    """Read-only proof that every filled current-Pons position has its controller."""
    from robinhood_research.evidence import Store
    from robinhood_research.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
    from robinhood_research.pons_selective_recovery import LifecycleState
    positions=[]
    with closing(connect(capital_path)) as db:
        rows=[json.loads(raw) for raw, in db.execute('SELECT body FROM capital_positions')]
    for row in rows:
        if row['status']=='settled':continue
        path=Path(row['trial_path'])
        if not path.is_absolute():path=Path(root)/path
        if path.resolve().parent!=Path(capital_path).resolve().parent:
            raise ValueError('pons_handoff_trial_path_identity')
        with closing(connect(path)) as db:
            store=Store.__new__(Store);store.db=db
            paper=SelectivePaper.__new__(SelectivePaper)
            paper.store=store;paper.experiment=STRATEGY_NAMESPACE
            position=paper._get(row['id'])
            if position['status'] not in ('open','exit_pending') or position['tokens']<=0:
                return None
            state=LifecycleState.restore(paper,row['id'])
            positions.append(dict(id=row['id'],version=position['version'],
                trial_path=row['trial_path'],opened_at=state.opened_at,
                policy_hash=position['controller_state']['policy_hash']))
    return (dict(schema='pons-current-controller-handoff-v1',positions=positions,
        entry_authority=False,accounting_reconciled=True) if positions else None)


def reconcile(lane,root):
    root=Path(root).resolve()
    if lane=='pump':
        from meme_machine.paper_accounting import PaperBook
        from meme_machine.pump_acceleration_strategy import policy_hash
        with closing(connect(root/'pump-acceleration-natural-prospective.accounting.sqlite3')) as db:
            book=PaperBook.__new__(PaperBook);book.db=db;book.lock=threading.RLock()
            book.identity=json.loads(db.execute('SELECT body FROM genesis WHERE id=1').fetchone()[0])
            if book.identity['policy_hash']!=policy_hash():raise ValueError('terminal_policy_identity')
            replay=book.replay();accounting=book.reconcile()
            handoff=pump_current_handoff(book) if accounting['open_positions'] else None
        from certification.directional_accounting import terminal
        return terminal(lane,root,dict(verified=True,accounting=accounting,accounting_replay=replay,
                    open_positions=accounting['open_positions']+accounting['pending'],
                    durable_handoff=handoff is not None,continuation_state=handoff))
    if lane=='pons':
        from robinhood_research.pons_selective_capital import CohortCapital
        from robinhood_research.pons_selective_continuation import POLICY_HASH
        path=root/'pons-selective-continuation-v1-cohort/pons-selective-cohort-capital.sqlite'
        with closing(connect(path)) as db:
            genesis=json.loads(db.execute('SELECT body FROM capital_genesis WHERE id=1').fetchone()[0])
        if genesis['policy_hash']!=POLICY_HASH:raise ValueError('terminal_policy_identity')
        book=CohortCapital.__new__(CohortCapital);book.path=str(path);book.capital=genesis['capital']
        book._connect=lambda:connect(path)
        # Native trial paths are relative to the lane directory. A downloaded
        # artifact retains those journal bytes and must use that same base.
        with chdir(root):accounting=book.reconcile()
        verified=(accounting.get('conservation') is True
                  and accounting.get('cash_basis_conservation') is True
                  and accounting.get('native_observation_complete') is True)
        from certification.directional_accounting import terminal
        handoff=pons_current_handoff(root,path) if verified and accounting['unsettled'] else None
        return terminal(lane,root,dict(verified=verified,accounting=accounting,
            open_positions=accounting['unsettled'],durable_handoff=handoff is not None,
            continuation_state=handoff))
    if lane=='meteora':
        from meme_machine.dlmm_independent_accounting import PaperBook
        from tests import solana_dlmm_independent_v1 as strategy
        path=root/'solana-dlmm-independent-v1-live.accounting.sqlite3'
        with closing(connect(path)) as db:
            event=json.loads(db.execute('SELECT body FROM events ORDER BY seq LIMIT 1').fetchone()[0])
        if event['action']!='genesis':raise ValueError('terminal_genesis_missing')
        book=PaperBook.__new__(PaperBook);book.path=path;book.genesis=event['data']
        book.run_id=book.genesis['run_id'];book.policy_hash=book.genesis['policy_hash']
        # Native policy paths are relative to the lane source, not the supervisor.
        with chdir(Path(strategy.__file__).resolve().parents[1]):
            expected_policy=strategy.digest(strategy.load_policy())
        if book.policy_hash!=expected_policy:raise ValueError('terminal_policy_identity')
        book.connect=lambda:connect(path)
        accounting=book.reconcile()
        with chdir(Path(strategy.__file__).resolve().parents[1]):
            replay=book.replay_economics(
                strategy._build_position,strategy._advance_position,strategy._mark)
        with closing(connect(path)) as db:
            events=[json.loads(raw) for raw, in db.execute(
                'SELECT body FROM events ORDER BY seq')]
        handoff=meteora_handoff(events,accounting,replay)
        return dict(verified=accounting['reconciled'] and replay.get('verified') is True,
                    accounting=accounting,accounting_replay=replay,
                    open_positions=accounting['unsettled'],
                    durable_handoff=handoff is not None,
                    continuation_state=handoff,
                    economic_replay_claimed=True)
    if lane=='ramses':
        from robinhood_research.ramses_strategy_ledger import RamsesStrategyLedger,_digest
        from robinhood_research.ramses_strategy import POLICY_HASH
        folder=root/'robinhood-ramses-extended-market.sqlite.campaign'
        manifest=folder/'capital-manifest.json'
        if not manifest.exists():
            report=json.loads((root/'robinhood-ramses-extended-market-report.json').read_text())
            accounting=report.get('campaign_accounting') or {}
            if (accounting.get('funding_state')!='awaiting_first_qualified_pinned_screen'
                    or accounting.get('policy_hash')!=POLICY_HASH or folder.exists()
                    or list(root.glob('robinhood-ramses-continuation*.sqlite'))):
                raise ValueError('ramses_unfunded_state_unproven')
            return dict(verified=True,accounting=accounting,open_positions=0)
        frozen=json.loads(manifest.read_text());rows={};positions=[]
        if frozen['policy_hash']!=POLICY_HASH:raise ValueError('terminal_policy_identity')
        for asset,amount in frozen['genesis_by_quote_asset'].items():
            with closing(connect(folder/(asset+'.sqlite'))) as db:
                raw,checksum=db.execute("SELECT body,hash FROM ramses_strategy_meta WHERE id='genesis'").fetchone()
                genesis=json.loads(raw)
                if (_digest(genesis)!=checksum or genesis['paper_capital']!=amount
                        or genesis['quote_asset']!=asset or genesis['policy_hash']!=POLICY_HASH):
                    raise ValueError('ramses_terminal_genesis_identity')
                book=RamsesStrategyLedger.__new__(RamsesStrategyLedger)
                book.db=db;book.paper_capital=amount;book.quote_asset=asset
                rows[asset]=book.reconcile()
                for identity, in db.execute('SELECT id FROM ramses_strategy_position'):
                    position=book.position(identity)
                    if position['status']=='settled':continue
                    first=db.execute('SELECT body FROM ramses_strategy_journal WHERE id=? AND action=\'reserve\' ORDER BY seq LIMIT 1',(identity,)).fetchone()
                    if first is None:raise ValueError('ramses_original_reservation_missing')
                    positions.append(dict(position=position,book_name=asset+'.sqlite',paper_capital=amount,
                        quote_asset=asset,reserved_at=json.loads(first[0])['at']))
        verified=all(r['paper_capital']+r['realized']==r['available']+r['committed'] for r in rows.values())
        accounting=dict(manifest=frozen,by_quote_asset=rows,conservation=verified,
            unlike_quote_units_summed=False,open_positions=sum(r['open_positions'] for r in rows.values()))
        handoff=ramses_handoff(root,positions)
        return dict(verified=verified,accounting=accounting,open_positions=accounting['open_positions'],
                    durable_handoff=handoff is not None,continuation_state=handoff)
    raise ValueError('unknown_lane')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--lane',required=True)
    parser.add_argument('--root',required=True);parser.add_argument('--source-root');args=parser.parse_args()
    sys.path.insert(0,str(Path(args.source_root or args.root).resolve()))
    try:result=reconcile(args.lane,args.root)
    except Exception as exc:result=dict(verified=False,error_type=type(exc).__name__)
    result.update(lane=args.lane,read_only=True,settlement_inferred=False)
    print(json.dumps(result,sort_keys=True))
    raise SystemExit(0 if result['verified'] else 1)


if __name__=='__main__':main()
