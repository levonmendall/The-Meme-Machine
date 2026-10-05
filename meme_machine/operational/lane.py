"""The committed native lane entrypoints; recovery precedes discovery."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import time

from meme_machine.portfolio_accounting import _atomic_json
from meme_machine.runtime.usd_valuation import utc,ValuationUnavailable


def health(root,lane,phase,**fields):
    try:
        _atomic_json(Path(root)/lane/'health.json',dict(lane=lane,phase=phase,paper_only=True,at=utc(time.time()),
            pid=os.getpid(),process_instance=os.environ.get('MM_LANE_PROCESS_INSTANCE'),**fields))
    except OSError as error:
        print('health publication failed:',type(error).__name__,flush=True)


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


def run_native(root,lane):
    # Shared USD delivery recovery is attached by each native book constructor.
    # Native restoration below is the existing recovery path, before discovery.
    health(root,lane,'RECONCILING')
    import threading
    from meme_machine.runtime import status
    from meme_machine.runtime.stop import requested
    def heartbeat():
        while not requested.wait(2):
            value=status.snapshot();phase=value.pop('phase')
            health(root,lane,phase,**value)
    threading.Thread(target=heartbeat,daemon=True,name='health').start()
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
                    empty_native_reconciliation(root,lane)
                    status.update('FAIL_CLOSED',reconciled=True,restored_positions=0,
                        discovery_enabled=False,valuation_available=False,
                        regimes=dict(current='FAIL_CLOSED',survivor='FAIL_CLOSED'))
                    if requested.wait(15):return
            with localcontext() as context:
                context.prec=80
                capital=int(Decimal('125')*(Decimal(10)**value.decimals)/value.usd_per_unit)
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
        install_ramses(ramses_extended_test)
        ramses_extended_test.main(campaign=True)
    health(root,lane,'STOPPED',reconciled=True)


def empty_native_reconciliation(root,lane):
    from .observation import database
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
    proof=database(Path(root)/'portfolio.sqlite',check)
    if proof.get('state')!='CURRENT' or proof.get('reconciled') is not True:
        raise RuntimeError('empty_native_state_not_reconciled')
    return proof


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--lane',required=True,choices=('pump','pons','meteora','ramses'))
    parser.add_argument('--state-root',required=True)
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    stop=[False]
    from meme_machine.runtime.stop import requested,Shutdown
    def shutdown(*_):
        stop[0]=True
        requested.set()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,shutdown)
    lock=(Path(args.state_root)/args.lane/'lane.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        if args.offline:run_offline(args.state_root,args.lane,stop)
        else:
            try:run_native(args.state_root,args.lane)
            except Shutdown:health(args.state_root,args.lane,'STOPPED',reconciled=True)
            except ValuationUnavailable as error:
                health(args.state_root,args.lane,'VALUATION_UNAVAILABLE',reason=str(error))
                raise
    finally:lock.close()


if __name__=='__main__':main()
