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


def file_sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(4*1024**2),b''):h.update(chunk)
    return h.hexdigest()


def snapshot_database(source, target, deadline, check_space=None):
    with closing(sqlite3.connect(Path(source).absolute().as_uri()+'?mode=ro',uri=True,timeout=.2)) as src, \
            closing(sqlite3.connect(target)) as dst:
        src.execute('PRAGMA query_only=ON')
        def progress(*_):
            if time.monotonic()>deadline:raise TimeoutError('coherent_backup_deadline')
            if check_space is not None:check_space()
        src.backup(dst,pages=256,progress=progress,sleep=.05)
        dst.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
        if dst.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:
            raise RuntimeError('backup_database_integrity')


def state_identity(root, *, immutable=False):
    uri=(Path(root)/'portfolio.sqlite').absolute().as_uri()+'?mode=ro'
    if immutable:
        for suffix in ('-wal','-journal'):
            sidecar=Path(root)/('portfolio.sqlite'+suffix)
            if sidecar.is_file() and sidecar.stat().st_size:
                raise ValueError('immutable_reader_requires_quiescent_database')
        uri+='&immutable=1'
    with closing(sqlite3.connect(uri,uri=True)) as db:
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


def reusable_point(root, point):
    """Strict byte equality to a complete coherent point; no copies or SQLite writes."""
    root=Path(root).resolve();point=require_isolated(point)
    if any(p.stat().st_size for base in (root,point) for pattern in ('*-wal','*-journal')
           for p in base.rglob(pattern) if p.is_file()):
        return None
    if any((point/name).exists() for name in ('backup-incomplete.json','backup-failed.json')):
        return None
    index=read_json(point/'backup.json')
    if not index.get('sqlite_consistent') or not index.get('application_writers_quiesced'):
        return None
    sources={str(p.relative_to(root)):p for p in root.rglob('*')
             if p.is_file() and classification(str(p.relative_to(root)))!='EPHEMERAL'}
    if set(sources)!=set(index['inventory']):return None
    original={relative:(p.stat().st_size,p.stat().st_mtime_ns) for relative,p in sources.items()}
    for relative,source in sources.items():
        dest=point/relative;row=index['inventory'][relative]
        if source.is_symlink() or dest.is_symlink() or point not in dest.resolve().parents:
            return None
        before=source.stat()
        # SQLite backup rewrites bookkeeping headers. New engineering points
        # record the exact quiescent source digest as well as the backup digest.
        expected_source=row.get('source_sha256') or row['sha256']
        if file_sha256(source)!=expected_source or file_sha256(dest)!=row['sha256']:return None
        after=source.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):return None
    if any((p.stat().st_size,p.stat().st_mtime_ns)!=original[relative] for relative,p in sources.items()):return None
    if any(p.stat().st_size for pattern in ('*-wal','*-journal') for p in root.rglob(pattern) if p.is_file()):return None
    if state_identity(root,immutable=True)!=index['portfolio'] or state_identity(point,immutable=True)!=index['portfolio']:
        return None
    return dict(epoch_id=index['epoch_id'],files=len(index['inventory']),
        sqlite_databases=sum(row['sqlite'] for row in index['inventory'].values()),
        directory=str(point),reused=True,verification='exact source and recovery point hashes')


def copy_state(root, target, *, seconds=60, nonessential=True, reuse=None):
    """Call only with all application writers stopped or the cgroup frozen."""
    root=Path(root).resolve();target=Path(target).resolve()
    if root==target or root in target.parents or target.exists():
        raise ValueError('new_isolated_backup_target_required')
    if reuse is not None:
        result=reusable_point(root,reuse)
        if result is not None:return result
    from .artifact_storage import admit_snapshot, headroom
    remaining=admit_snapshot(root,target.parent,nonessential=nonessential)
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
            headroom(target,remaining,nonessential=nonessential,warn=False)
            is_sqlite=sqlite_file(source)
            source_before=source.stat()
            def check_space():
                allocated=max(dest.stat().st_size,dest.stat().st_blocks*512) if dest.exists() else 0
                headroom(target,max(0,remaining-allocated),nonessential=nonessential,warn=False)
            if is_sqlite:snapshot_database(source,dest,deadline,check_space)
            else:shutil.copy2(source,dest)
            remaining=max(0,remaining-max(source.stat().st_size,source.stat().st_blocks*512))
            headroom(target,remaining,nonessential=nonessential,warn=False)
            dest.chmod(0o600)
            inventory[relative]=dict(classification=kind,sqlite=is_sqlite,bytes=dest.stat().st_size,
                sha256=file_sha256(dest))
            # Optional engineering reuse evidence must not extend the bounded
            # runtime backup's frozen window or ignore WAL/rollback contents.
            if nonessential and not any(Path(str(source)+suffix).is_file() and
                    Path(str(source)+suffix).stat().st_size for suffix in ('-wal','-journal')):
                inventory[relative]['source_sha256']=file_sha256(source)
                source_after=source.stat()
                if (source_before.st_size,source_before.st_mtime_ns)!=(source_after.st_size,source_after.st_mtime_ns):
                    raise RuntimeError('backup_source_changed_during_copy')
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
        if file_sha256(p)!=row['sha256']:
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


def prepare(root,target,*,freeze_seconds=5,nonessential=True):
    from .storage_guard import verify_storage
    verify_storage(Path(root).resolve())
    target=Path(target).resolve()
    from .artifact_storage import admit_snapshot
    admit_snapshot(root,target.parent,nonessential=nonessential)
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
            return copy_state(root,target,seconds=freeze_seconds if active else 60,nonessential=nonessential)
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
