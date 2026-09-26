"""SIGKILL/reopen checks of the four native books, using synthetic ledger inputs.

This proves transactional ledger durability only. It deliberately does not call
an accepted fixture decision a real strategy qualification or runner recovery.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import sys


def kill():os.kill(os.getpid(),signal.SIGKILL)


def arm(db):
    def trace(sql):
        if sql.strip().upper()=='COMMIT':kill()
    db.set_trace_callback(trace)


def exercise(lane,path,step,before_commit=False,inspect=False):
    if lane=='pump':
        from meme_machine.paper_accounting import PaperBook
        from meme_machine.pump_acceleration_strategy import policy_hash,STRATEGY_ID
        book=PaperBook(path,run_id='crash',lane=STRATEGY_ID,policy_hash=policy_hash(),initial=1000)
        if before_commit:arm(book.db)
        actions=[lambda:None,
            lambda:book.reserve('crash:one',400,10,{'fixture_kind':'synthetic_ledger_input'}),
            lambda:book.transition('crash:one','filled',12,amount=390,tokens=10),
            lambda:book.transition('crash:one','mark',14,amount=420),
            lambda:book.transition('crash:one','settled',16,amount=420)]
        reconcile=book.reconcile
    elif lane=='pons':
        from robinhood_research.evidence import Store
        from robinhood_research.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from robinhood_research.pons_selective_continuation import POLICY_HASH
        from robinhood_tests.test_pons_partial_accounting import PartialAccountingTests
        fixture=PartialAccountingTests();store=Store(path)
        paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=POLICY_HASH,
            clock_ns=lambda:(10+step)*10**9)
        if before_commit:arm(store.db)
        actions=[lambda:None,
            lambda:paper.reserve('one',market='m',amount=100,gas_budget=20,now=10,features=fixture.features(10)),
            lambda:paper.advance('one',now=11,action='entry',quote=fixture.quote(11,'buy',100,1000)),
            lambda:paper.advance('one',now=12,action='exit_intent'),
            lambda:paper.advance('one',now=13,action='exit',quote=fixture.quote(13,'sell',1000,130))]
        reconcile=paper.reconcile
    elif lane=='ramses':
        from robinhood_research.ramses_strategy_ledger import RamsesStrategyLedger
        from robinhood_research.ramses_strategy import STRATEGY_DOMAIN
        from robinhood_tests.test_ramses_capital_replay import decision
        book=RamsesStrategyLedger(path,paper_capital=1000,quote_asset='synthetic_quote')
        if before_commit:arm(book.db)
        actions=[lambda:None,
            lambda:book.reserve('one',pool='synthetic_pool',decision=decision(400),at=10),
            lambda:book.open('one',at=11),
            lambda:book.checkpoint('one',action='monitor',detail={'action':'hold'},at=12),
            lambda:book.settle('one',pnl={'strategy_domain':STRATEGY_DOMAIN,'net_result_quote':30,'unresolved_inventory':None},at=13)]
        reconcile=book.reconcile
    else:
        from meme_machine.dlmm_independent_accounting import PaperBook,NAMESPACE
        from meme_machine import dlmm
        from meme_machine.store import digest
        from tests.dlmm_support import snapshot
        from tests import solana_dlmm_independent_v1 as strategy
        policy=strategy.load_policy();entry=dlmm.validate(snapshot(),100)
        features=dict(half_width_bins=4,lower=-4,upper=4,volume_rate_sol_lamports_per_second=1,fee_density=1)
        position=strategy._build_position(entry,features,policy);mark=strategy._mark(position)
        book=PaperBook(Path(path),run_id='crash',policy_hash=digest(policy),capital=1_000_000_000)
        if before_commit:
            original=book.connect
            def connect():
                db=original();arm(db);return db
            book.connect=connect
        identity=NAMESPACE+':crash:one'
        actions=[lambda:None,
            lambda:book.append(identity,'reserve',dict(amount=strategy.CAPITAL+strategy.ROUND_TRIP_NETWORK_COST),at_ns=10),
            lambda:book.append(identity,'entry',dict(capital=strategy.CAPITAL,entry_cost=strategy.ENTRY_NETWORK_COST,
                exit_cost=strategy.EXIT_NETWORK_COST,entry_state=entry,position=position,features=features,policy=policy,mark=mark),at_ns=11),
            lambda:book.append(identity,'unresolved',dict(reason='synthetic_monitor_failure'),at_ns=12),
            lambda:book.append(identity,'settle',dict(mark=mark),at_ns=13)]
        reconcile=book.reconcile
    if inspect:
        value=reconcile();print(json.dumps(value,sort_keys=True),flush=True);return
    actions[step]()
    kill()  # No close(), no finally, no application-level drain.


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--lane',required=True,choices=('pump','pons','meteora','ramses'))
    parser.add_argument('--db',required=True);parser.add_argument('--step',type=int,default=0)
    parser.add_argument('--before-commit',action='store_true');parser.add_argument('--inspect',action='store_true')
    args=parser.parse_args();sys.path.insert(0,os.getcwd())
    # Native strategies reuse certified neutral capacity/accounting helpers.
    # Match worker import precedence when invoked directly from a lane worktree.
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    exercise(args.lane,args.db,args.step,args.before_commit,args.inspect)
