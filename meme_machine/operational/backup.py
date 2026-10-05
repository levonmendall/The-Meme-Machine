"""Coherent PAPER state copies and isolated verification; no new inception."""
import argparse
from contextlib import closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

from .observation import atomic_json, read_json, stamp

PAPER_UNIT='meme-machine-paper.service'
PRODUCTION_ROOT=Path('/mnt/volume_nyc1_1790918115030/meme-machine-paper-v1')


def classification(relative):
    path=Path(relative);name=path.name
    if name.endswith(('-wal','-shm','.lock','.sock')) or name in ('supervisor.lock',):
        return 'EPHEMERAL'
    if name=='health.json' or name in ('inception.json','portfolio.json','dashboard-snapshot.json') or name.startswith('acceptance-') or name=='deployment-defects.json':
        return 'READ_ONLY_PROJECTION'
    if relative=='shared/robinhood-evidence.sqlite':
        return 'REBUILDABLE_CACHE'
    # Includes every native journal, pending delivery, checkpoint, Survivor
    # history, pipeline, sleeve, genesis and shared evidence/recovery database.
    return 'AUTHORITATIVE'


def sqlite_file(path):
    with Path(path).open('rb') as stream:
        return stream.read(16)==b'SQLite format 3\0'


def snapshot_database(source, target, deadline):
    with closing(sqlite3.connect(Path(source).absolute().as_uri()+'?mode=ro',uri=True,timeout=.2)) as src, \
            closing(sqlite3.connect(target)) as dst:
        src.execute('PRAGMA query_only=ON')
        def progress(*_):
            if time.monotonic()>deadline:raise TimeoutError('coherent_backup_deadline')
        src.backup(dst,pages=256,progress=progress,sleep=.05)
        dst.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
        if dst.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:
            raise RuntimeError('backup_database_integrity')


def state_identity(root):
    with closing(sqlite3.connect((Path(root)/'portfolio.sqlite').absolute().as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        from meme_machine.portfolio_accounting import PortfolioAccounting,_encode_checkpoint,digest
        reader=object.__new__(PortfolioAccounting);reader.db=db
        state=reader._replay()
        if state is None:raise RuntimeError('existing_backup_epoch_required')
        totals=reader._reconcile(state)
        encoded=_encode_checkpoint(state)
        return dict(epoch_id=state['receipt']['epoch_id'],inception_sha256=state['receipt_hash'],
            sequence=state['sequence'],journal_hash=state['journal_hash'],
            reconciliation='PASS',checks=totals['checks'],replayed_state=encoded,
            replayed_sha256=digest(encoded),
            pending_deliveries=[dict(lane=l,native=n,body=json.loads(b)) for l,n,b in
                db.execute('SELECT lane,native,body FROM portfolio_native_pending ORDER BY lane,native')],
            native_ids=[list(row) for row in db.execute('SELECT * FROM portfolio_native_ids ORDER BY id')],
            sleeves=[list(row) for row in db.execute('SELECT * FROM portfolio_sleeves ORDER BY lane')])


def copy_state(root, target, *, seconds=60):
    """Call only with all application writers stopped or the cgroup frozen."""
    root=Path(root).resolve();target=Path(target).resolve()
    if root==target or root in target.parents or target.exists():
        raise ValueError('new_isolated_backup_target_required')
    target.mkdir(parents=True,mode=0o700)
    # A process killed mid-copy leaves an identifiable disposable partial point.
    atomic_json(target/'backup-incomplete.json',dict(at=stamp(),usable=False))
    deadline=time.monotonic()+seconds;inventory={}
    baseline=state_identity(root)
    try:
        for source in sorted(root.rglob('*')):
            if source.is_symlink():raise ValueError('backup_state_symlink_forbidden')
            if not source.is_file():continue
            relative=str(source.relative_to(root));kind=classification(relative)
            if kind=='EPHEMERAL':continue
            if time.monotonic()>deadline:raise TimeoutError('coherent_backup_deadline')
            dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            is_sqlite=sqlite_file(source)
            if is_sqlite:snapshot_database(source,dest,deadline)
            else:shutil.copy2(source,dest)
            dest.chmod(0o600)
            inventory[relative]=dict(classification=kind,sqlite=is_sqlite,bytes=dest.stat().st_size,
                sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
        restored=state_identity(target)
        if baseline!=restored or state_identity(root)!=baseline:
            raise RuntimeError('backup_application_point_changed')
        atomic_json(target/'backup.json',dict(at=stamp(),epoch_id=baseline['epoch_id'],portfolio=baseline,
            inventory=inventory,sqlite_consistent=True,application_writers_quiesced=True,
            required_restore='new isolated target; never production root'))
        (target/'backup-incomplete.json').unlink()
        subprocess.run(['sync','-f',str(target)],check=True,timeout=5)
        return dict(epoch_id=baseline['epoch_id'],files=len(inventory),sqlite_databases=sum(r['sqlite'] for r in inventory.values()),directory=str(target))
    except BaseException:
        # A failed disposable copy has no restore authority; keep it for diagnosis.
        atomic_json(target/'backup-failed.json',dict(at=stamp(),usable=False))
        raise


def require_isolated(root):
    root=Path(root).resolve()
    authoritative=Path(os.environ.get('MM_STATE_ROOT',PRODUCTION_ROOT)).resolve()
    if root==authoritative or authoritative in root.parents:
        raise ValueError('restore_verification_requires_isolated_target')
    return root


def verify_copy(root):
    root=require_isolated(root);index=read_json(root/'backup.json')
    for relative,row in index['inventory'].items():
        p=root/relative
        if p.is_symlink() or root not in p.resolve().parents:
            raise ValueError('restore_path_escape')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:
            raise RuntimeError('restored_state_hash_mismatch')
        if row['sqlite']:
            with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as db:
                if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:
                    raise RuntimeError('restored_database_integrity')
    if state_identity(root)!=index['portfolio']:
        raise RuntimeError('restored_portfolio_identity_mismatch')
    return dict(passed=True,epoch_id=index['epoch_id'],files=len(index['inventory']),reconciliation='PASS')


def prove_replay(root):
    """Open only an isolated restored writer, replay twice, and test its fence."""
    root=require_isolated(root)
    from meme_machine.portfolio_accounting import PortfolioAccounting
    before=state_identity(root)
    with closing(PortfolioAccounting(root/'portfolio.sqlite')) as account:
        account._reconcile(account.snapshot())
        try:
            other=PortfolioAccounting(root/'portfolio.sqlite')
        except RuntimeError as error:
            if str(error)!='portfolio_writer_already_running':raise
        else:
            other.close();raise RuntimeError('restored_single_writer_fence_missing')
    with closing(PortfolioAccounting(root/'portfolio.sqlite')) as account:
        account._reconcile(account.snapshot())
    if state_identity(root)!=before:raise RuntimeError('restored_replay_changed_economic_state')
    return dict(passed=True,epoch_id=before['epoch_id'],reconciliation='PASS',
                replay_idempotent=True,single_writer_fencing=True)


def prepare(root,target,*,freeze_seconds=5):
    from .storage_guard import verify_storage
    verify_storage(Path(root).resolve())
    target=Path(target).resolve()
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (target.parent/'backup.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        props=subprocess.check_output(['systemctl','show',PAPER_UNIT,'-p','ActiveState','-p','MainPID','-p','ControlGroup'],text=True,timeout=5)
        service=dict(line.split('=',1) for line in props.splitlines() if '=' in line)
        active=service['ActiveState']=='active' and int(service['MainPID'])>0
        if not active and (service['ActiveState'] not in ('inactive','failed') or int(service['MainPID'])!=0):
            raise RuntimeError('backup_runtime_not_quiescent')
        group=service.get('ControlGroup','')
        if not active and group:
            processes=Path('/sys/fs/cgroup')/group.lstrip('/')/'cgroup.procs'
            if processes.exists() and processes.read_text().strip():
                raise RuntimeError('backup_runtime_children_not_quiescent')
        supervisor_lock=None
        frozen=False
        try:
            if active:
                # A bounded systemd service also thaws in ExecStopPost if this
                # process dies. Never freeze from an interactive invocation.
                if not os.environ.get('MM_BACKUP_SYSTEMD'):
                    raise RuntimeError('active_backup_requires_systemd_thaw_cleanup')
                subprocess.run(['systemctl','freeze',PAPER_UNIT],check=True,timeout=5)
                frozen=True
            else:
                supervisor_lock=(Path(root)/'supervisor.lock').open('r')
                fcntl.flock(supervisor_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                # A manual supervisor cannot start while this existing lock is
                # held; no new economic lock file or epoch is created here.
            return copy_state(root,target,seconds=freeze_seconds if active else 60)
        finally:
            if frozen:subprocess.run(['systemctl','thaw',PAPER_UNIT],check=True,timeout=5)
            if supervisor_lock is not None:supervisor_lock.close()


def thaw_if_needed(unit=PAPER_UNIT):
    """Cleanup after process loss without failing for an already running freezer."""
    state=subprocess.check_output(['systemctl','show',unit,'-p','FreezerState','--value'],
        text=True,timeout=5).strip()
    if not state:
        raise RuntimeError('backup_freezer_state_unavailable')
    if state!='running':
        subprocess.run(['systemctl','thaw',unit],check=True,timeout=5)
    return dict(thawed=state!='running',unit=unit)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','verify','replay','thaw'))
    parser.add_argument('target',nargs='?')
    parser.add_argument('--state-root',default=os.environ.get('MM_STATE_ROOT'))
    args=parser.parse_args()
    if args.command=='thaw' and args.target is not None:
        parser.error('thaw has no target override')
    if args.command!='thaw' and args.target is None:
        parser.error('backup target is required')
    try:
        result=thaw_if_needed() if args.command=='thaw' else verify_copy(args.target) if args.command=='verify' else prove_replay(args.target) if args.command=='replay' else prepare(args.state_root,args.target)
    except Exception as error:
        print(json.dumps(dict(passed=False,error_type=type(error).__name__)))
        return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
