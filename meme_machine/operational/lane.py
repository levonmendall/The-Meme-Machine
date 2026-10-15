"""The committed native lane entrypoints; recovery precedes discovery."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import threading
import time

from meme_machine.portfolio_accounting import _atomic_json
from meme_machine.runtime.usd_valuation import utc,ValuationUnavailable


class NativeReconciliationUnavailable(RuntimeError):
    """A bounded read can retry without restarting or authorizing discovery."""


def native_reconciliation(root,check,reason):
    from .observation import database
    # Native recovery gets its own durable-state read budget. The independent
    # low-priority observer's one-second budget is not an economic recovery SLA.
    proof=database(Path(root)/'portfolio.sqlite',check,seconds=5)
    if proof.get('state')=='CURRENT' and proof.get('reconciled') is True:return proof
    if (proof.get('sqlite_code') in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_CANTOPEN) or
            proof.get('sqlite_code')==sqlite3.SQLITE_INTERRUPT and
            proof.get('observation_deadline_exhausted') is True):
        raise NativeReconciliationUnavailable(reason)
    raise RuntimeError(reason)


def health(root,lane,phase,**fields):
    try:
        _atomic_json(Path(root)/lane/'health.json',dict(lane=lane,phase=phase,paper_only=True,at=utc(time.time()),
            pid=os.getpid(),process_instance=os.environ.get('MM_LANE_PROCESS_INSTANCE'),**fields))
    except OSError as error:
        print('health publication failed:',type(error).__name__,flush=True)


class NativeHealthPublisher:
    """Serialize only this lane's descriptive health, including its final wake."""
    def __init__(self,root,lane):
        self.root=root;self.lane=lane
        self.lock=threading.Lock();self.terminal=threading.Event()
        self.cancellation_stack=None;self.cancellation_stack_attempted=False

    def __call__(self,phase,**fields):
        terminal=phase=='STOPPED'
        if terminal:self.terminal.set()
        # Optional recording must not add an unbounded shutdown lock wait.
        if not self.lock.acquire(timeout=.05):
            print('health publication unavailable:publication_busy',flush=True)
            return
        try:
            if not terminal and self.terminal.is_set():return
            if self.cancellation_stack is not None:
                fields['cancellation_stack']=self.cancellation_stack
            try:health(self.root,self.lane,phase,**fields)
            except Exception as error:
                print('health publication unavailable:'+type(error).__name__,flush=True)
        finally:self.lock.release()

    def heartbeat(self,requested,status):
        stopping=False
        while not self.terminal.is_set():
            if stopping:
                # A requested stop can still be draining accepted work. Keep
                # the original cadence without spinning on the set signal.
                if self.terminal.wait(2):return
            else:stopping=requested.wait(2)
            if self.terminal.is_set():return
            if stopping and not self.cancellation_stack_attempted:
                # Only this existing health thread probes the main executor.
                # Failure is descriptive and must not obstruct cancellation.
                self.cancellation_stack_attempted=True
                try:self.cancellation_stack=status.cancellation_stack()
                except Exception:
                    self.cancellation_stack=dict(state='UNAVAILABLE',reason='probe_failed',frames=[])
            # TERM can precede the first periodic sample. Preserve the active
            # executor/operation and original signal immediately, then retain
            # changes until terminal publication fences further health writes.
            value=status.snapshot();phase=value.pop('phase')
            self(phase,**value)


def run_offline(root,lane,stop):
    from .offline import open_native,open_position,manage,close,install_network_guard
    install_network_guard()
    epoch=os.environ['MM_PAPER_EPOCH']
    health(root,lane,'RECONCILING',offline=True)
    book,rows,provider=open_native(root,lane,epoch)
    try:
        native=rows[0]['id'] if rows else None
        health(root,lane,'MANAGING',offline=True,reconciled=True,restored_positions=len(rows))
        if native is not None:manage(book,lane,native,int(time.time()))
        health(root,lane,'DISCOVERING',offline=True,reconciled=True,restored_positions=len(rows))
        if native is None:native=open_position(book,lane,epoch,int(time.time()))
        while not stop[0]:
            manage(book,lane,native,int(time.time()))
            health(root,lane,'MANAGING',offline=True,reconciled=True,native_lifecycle=native,mock_value_reads=provider.calls,market_calls=0)
            time.sleep(.2)
    finally:
        close(book,lane)
        health(root,lane,'STOPPED',offline=True,reconciled=True,market_calls=0)


def run_native(root,lane,publish=None):
    from meme_machine.runtime.operating_families import require_active
    require_active(lane,production=True)
    # Shared USD delivery recovery is attached by each native book constructor.
    # Native restoration below is the existing recovery path, before discovery.
    publish=publish or NativeHealthPublisher(root,lane)
    publish('RECONCILING')
    from meme_machine.runtime import status
    from meme_machine.runtime.stop import requested
    threading.Thread(target=publish.heartbeat,args=(requested,status),daemon=True,name='health').start()
    if lane=='pons':
        from meme_machine.shared_capital.runtime import selected,connection,native_startup_replay
        shared=selected(Path(root)/'portfolio.sqlite')
        if shared is not None:
            # Only the initial read-only verification observes startup TERM.
            # Native recovery and later writes reuse this verified connection.
            with status.operation('pons.shared_capital_restore'):
                with native_startup_replay(requested.is_set):connection(shared)
    capital=None
    if lane in ('pump','pons','meteora'):
        from meme_machine.runtime.usd_valuation import native_reader
        from decimal import Decimal,localcontext
        path=Path(root)/lane/'native-genesis.json'
        if path.exists():capital=json.loads(path.read_text())['capital']
        else:
            while True:
                try:
                    value=native_reader(lane)(int(time.time()))
                    break
                except ValuationUnavailable:
                    # Do not mint native capital at an invented price or crash
                    # repeatedly during legitimate unavailable market liquidity.
                    # Empty native state is reconciled against the shared epoch;
                    # existing exposure without native genesis fails closed.
                    reconciled=False
                    try:
                        empty_native_reconciliation(root,lane);reconciled=True
                    except NativeReconciliationUnavailable:pass
                    status.update('FAIL_CLOSED',reconciled=reconciled,restored_positions=0,
                        discovery_enabled=False,valuation_available=False,
                        regimes=dict(current='FAIL_CLOSED',survivor='FAIL_CLOSED'))
                    if requested.wait(15):return
            with localcontext() as context:
                context.prec=80
                from meme_machine.shared_capital.runtime import selected,connection
                shared=selected(Path(root)/'portfolio.sqlite')
                # Native journal genesis is attribution, never a second cash
                # authority. Preserve old genesis and bind a new shared book to
                # its immutable total inception; live sizing compounds elsewhere.
                ledger=connection(shared).ledger() if shared else None
                equity=Decimal(ledger['initial_capital']) if ledger and ledger['policy']['sizing_basis']=='shared_realized_equity' else Decimal('125')
                capital=int(equity*(Decimal(10)**value.decimals)/value.usd_per_unit)
            _atomic_json(path,dict(capital=capital,valuation=value.evidence(int(time.time()))))
    if lane=='pump':
        from meme_machine.lanes.pump import runner
        runner.INITIAL_LAMPORTS=capital
        runner.ENTRY_BUDGET=capital*runner.POLICY.entry_fraction_bps//10000
        runner.main(campaign=True,discovery_seconds=3300)
    elif lane=='pons':
        from meme_machine.lanes.pons import pons_selective_cohort,pons_selective_paper
        # The USD gate is mandatory at every native reservation; historical
        # per-trial conservation parameters never create shared USD capital.
        pons_selective_cohort.STRATEGY_CAPITAL_QUOTE=capital
        pons_selective_paper.STRATEGY_CAPITAL_QUOTE=capital
        pons_selective_cohort.run(os.environ['MM_ROBINHOOD_READ_RPC_URL'],campaign=True)
    elif lane=='meteora':
        from meme_machine.runtime.lifecycle_timing import install_meteora
        from meme_machine.lanes.meteora import runner
        runner.NATIVE_GENESIS_CAPITAL=capital
        install_meteora(runner)
        runner.run_live(target=6,max_attempted=48,max_runtime_seconds=3600,campaign=True)
    else:
        from meme_machine.runtime.lifecycle_timing import install_ramses
        from meme_machine.lanes.ramses import ramses_extended_test
        while True:
            try:
                if unfunded_ramses_reconciliation(root):
                    status.update('DISCOVERING',reconciled=True,restored_positions=0)
                break
            except NativeReconciliationUnavailable:
                status.update('FAIL_CLOSED',reconciled=False,discovery_enabled=False)
                if requested.wait(15):return
        install_ramses(ramses_extended_test)
        ramses_extended_test.main(campaign=True)
    value=status.snapshot();value.pop('phase',None)
    publish('STOPPED',**value)


def empty_native_reconciliation(root,lane):
    from meme_machine.portfolio_accounting import PortfolioAccounting
    folder=Path(root)/lane
    if any(p.is_file() for p in folder.rglob('*.sqlite*')):
        raise RuntimeError('native_genesis_missing_with_existing_native_store')
    def check(db):
        reader=object.__new__(PortfolioAccounting);reader.db=db
        state=reader._replay();reader._reconcile(state)
        if state['receipt']['epoch_id']!=os.environ['MM_PAPER_EPOCH']:
            raise RuntimeError('native_wait_epoch_mismatch')
        if (any(p['lane']==lane for p in state['positions'].values()) or
                any(p['lane']==lane for p in state['reservations'].values()) or
                state['retired'][lane]['count'] or
                db.execute('SELECT 1 FROM portfolio_native_pending WHERE lane=? LIMIT 1',(lane,)).fetchone()):
            raise RuntimeError('native_genesis_missing_with_shared_economic_state')
        return dict(reconciled=True)
    return native_reconciliation(root,check,'empty_native_state_not_reconciled')


def unfunded_ramses_reconciliation(root):
    """No qualifier/funding is a reconciled empty state, not a stalled restart.

    Existing funded books still use their native startup/recovery before new
    discovery. Never infer empty state from a no-trade report alone.
    """
    from meme_machine.portfolio_accounting import PortfolioAccounting
    folder=Path(root)/'ramses'
    if (folder/'robinhood-ramses-extended-market.sqlite.campaign').exists():return False
    allowed='robinhood-ramses-extended-market.sqlite.pipeline.sqlite'
    if any(p.is_file() and p.name not in (allowed,allowed+'-wal',allowed+'-shm')
           for p in folder.rglob('*.sqlite*')):
        raise RuntimeError('unfunded_ramses_unknown_native_store')
    continuation=folder/'robinhood-ramses-continuation.json'
    if continuation.exists():
        value=json.loads(continuation.read_text())
        if value.get('active') or value.get('ledger_path'):
            raise RuntimeError('unfunded_ramses_native_continuation_present')
    def check(db):
        reader=object.__new__(PortfolioAccounting);reader.db=db
        state=reader._replay();reader._reconcile(state)
        if state['receipt']['epoch_id']!=os.environ['MM_PAPER_EPOCH']:
            raise RuntimeError('unfunded_ramses_epoch_mismatch')
        if (any(p['lane']=='ramses' for p in state['positions'].values()) or
                any(p['lane']=='ramses' for p in state['reservations'].values()) or
                state['retired']['ramses']['count'] or
                db.execute("SELECT 1 FROM portfolio_native_pending WHERE lane='ramses' LIMIT 1").fetchone()):
            raise RuntimeError('unfunded_ramses_shared_economic_state_present')
        return dict(reconciled=True)
    native_reconciliation(root,check,'unfunded_ramses_not_reconciled')
    return True


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--lane',required=True,choices=('pump','pons','meteora','ramses'))
    parser.add_argument('--state-root',required=True)
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    from meme_machine.runtime.operating_families import require_active
    require_active(args.lane,production=True)
    stop=[False]
    from meme_machine.runtime.stop import requested,Shutdown
    from meme_machine.runtime import status
    def shutdown(*_):
        status.cancellation_signal(_[0])
        stop[0]=True
        requested.set()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,shutdown)
    lock=(Path(args.state_root)/args.lane/'lane.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        if args.offline:run_offline(args.state_root,args.lane,stop)
        else:
            from .bounded_provider import install
            install()
            publish=NativeHealthPublisher(args.state_root,args.lane)
            try:run_native(args.state_root,args.lane,publish)
            except Shutdown:
                from meme_machine.runtime import status
                facts=status.snapshot();facts.pop('phase',None)
                # Cooperative cancellation can arrive before native restoration.
                # A stopped process is not proof that its reconciliation finished.
                publish('STOPPED',**facts)
            except ValuationUnavailable as error:
                publish('VALUATION_UNAVAILABLE',reason=str(error))
                raise
    finally:lock.close()


if __name__=='__main__':main()
