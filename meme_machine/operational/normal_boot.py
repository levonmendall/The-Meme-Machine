"""Owned pre-write native replay and a private NORMAL boot instance.

This is separate from the stopped mount compatibility helper. The sealed root
instance, original existing writer locks, pinned complete support-file census,
absent/empty-WAL requirement and unchanged original reducers jointly bound the
immutable read. No constructor runs until this scope has closed successfully.
Boot permission is not economic-source or allocation readiness.
"""
from contextlib import ExitStack
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import threading
import time

from .normal_boot_record import (AuthenticatedNormalLaunch,NormalBootUnavailable,await_normal_launch,
    canonical,digest,file_identity,require,REGIMES,SOURCE_INPUTS)

LOCKS=('supervisor.lock','portfolio.sqlite.lock','shared/solana-evidence.sqlite.writer.lock',
    'pump/lane.lock','pons/lane.lock')
_ISSUER=object()
_ACTIVE=None


def _source_identity():
    source=Path(__file__).resolve().parents[2]
    command=['git','-c','safe.directory='+str(source),'-c','core.fsmonitor=false',
        '-c','core.hooksPath=/dev/null','-c','protocol.allow=never','--no-optional-locks','-C',str(source)]
    env=dict(os.environ,GIT_NO_LAZY_FETCH='1',GIT_OPTIONAL_LOCKS='0')
    def git(*args):
        raw=subprocess.check_output(command+list(args),env=env,text=True,timeout=5)
        require(len(raw.encode())<=8192,'source_output_bound');return raw.strip()
    require(not git('status','--porcelain'),'source_dirty')
    return git('rev-parse','HEAD'),git('rev-parse','HEAD^{tree}')


def _owner_dead(identity):
    from .normal_boot_record import positive,uuid_value
    if type(identity) is not str or len(identity)>128:return False
    parts=identity.split(':')
    if len(parts)!=3 or not uuid_value(parts[0]) or not all(positive(x) for x in parts[1:]):return False
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=parts[0]:return False
    try:raw=Path('/proc/'+str(int(parts[1]))+'/stat').read_text()
    except FileNotFoundError:return True
    except OSError:return False
    return raw.rsplit(')',1)[1].split()[19]!=parts[2]


class _OwnedPrewriteReads:
    """Same-instance exclusive pre-write scope, not a generic readonly option.

    SQLite immutable reads are admissible here only with all original writer
    locks and a SEALED current instance held, every main/support inode pinned,
    WAL absent or exactly empty and no rollback journal. SHM is never opened
    for writing. Any concurrent physical mutation invalidates the whole proof.
    """
    def __init__(self,supervisor,launch,*,cancelled):
        require(type(launch) is AuthenticatedNormalLaunch,'authenticated_launch_required')
        self.supervisor=supervisor;self.launch=launch;self.cancelled=cancelled
        self.root=Path(supervisor.root);self.owner=(os.getpid(),threading.get_ident())
        require(self.root.is_absolute() and '..' not in self.root.parts,'prewrite_root')
        require(callable(cancelled) and not supervisor.processes
            and not any(hasattr(supervisor,name) for name in ('shared_capital','normal_budget')),
            'prewrite_before_runtime')
        from meme_machine.shared_capital import runtime
        require(not any(Path(name).is_relative_to(self.root)
            for name in getattr(runtime._LOCAL,'pool',{})),'prewrite_existing_shared_owner')
        self.deadline=launch.require_current(initial=True)['not_after_monotonic']
        self.stack=ExitStack();self.files={};self.directories={};self.databases={};self.artifacts={}
        self.entries=0;self.held=[]

    def check(self):
        require(self.owner==(os.getpid(),threading.get_ident()),'prewrite_owner')
        require(self.cancelled() is False and time.monotonic()<self.deadline,'prewrite_cancelled_or_expired')

    def validate(self):
        self.check();self.launch.require_current(initial=True)
        for path,before in self.directories.items():
            require(file_identity(path.lstat())==before,'prewrite_directory_changed')
        for path,(fd,before,_sql) in self.files.items():
            require(file_identity(path.lstat())==before==file_identity(os.fstat(fd)),'prewrite_file_changed')
        for path,fd,before in self.held:
            require(file_identity(path.lstat())==before==file_identity(os.fstat(fd)),'prewrite_lock_changed')
        return True

    def _locks(self):
        handle=getattr(self.supervisor,'lock',None)
        require(handle is not None and not handle.closed,'supervisor_lock_required')
        fd=handle.fileno();path=self.root/'supervisor.lock';before=file_identity(os.fstat(fd))
        require(stat.S_ISREG(before[2]) and before[5]==1 and before==file_identity(path.lstat()),
            'supervisor_lock_identity')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.held.append((path,fd,before))
        for name in LOCKS[1:]:
            path=self.root/name
            for parent in (path.parent,*path.parent.parents):
                require(stat.S_ISDIR(parent.lstat().st_mode),'prewrite_lock_ancestor')
                if parent==self.root:break
            if name=='portfolio.sqlite.lock' and not path.exists():continue
            require(not path.is_symlink(),'prewrite_lock_symlink')
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
            self.stack.callback(os.close,fd);info=os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,'prewrite_lock_type')
            before=file_identity(info)
            require(before==file_identity(path.lstat()),'prewrite_lock_changed')
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);self.held.append((path,fd,before))
        expected=self.launch.require_current(initial=True)['boot_eligibility']['held_existing_fences']
        require(len(self.held)==expected,'prewrite_fence_population')

    def _walk(self,path,depth=0):
        self.check();require(depth<=16,'prewrite_depth')
        fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        self.stack.callback(os.close,fd);info=os.fstat(fd)
        require(stat.S_ISDIR(info.st_mode) and file_identity(info)==file_identity(path.lstat()),
            'prewrite_directory_type')
        self.directories[path]=file_identity(info)
        with os.scandir(fd) as entries:
            for entry in entries:
                self.check();self.entries+=1;require(self.entries<=16384,'prewrite_entry_bound')
                child=path/entry.name;info=os.stat(entry.name,dir_fd=fd,follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):self._walk(child,depth+1)
                elif stat.S_ISREG(info.st_mode):
                    require(info.st_nlink==1 and len(self.files)<4096,'prewrite_file_bound')
                    child_fd=os.open(entry.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=fd)
                    self.stack.callback(os.close,child_fd);before=file_identity(info)
                    require(file_identity(os.fstat(child_fd))==before,'prewrite_file_changed')
                    sqlite=os.pread(child_fd,16,0)==b'SQLite format 3\x00'
                    require(sqlite or child.suffix not in ('.sqlite','.sqlite3'),'prewrite_named_database')
                    self.files[child]=(child_fd,before,sqlite)
                    if not sqlite:self.artifacts[child]=child_fd
                else:
                    require(stat.S_ISSOCK(info.st_mode) and info.st_uid==os.geteuid()
                        and stat.S_IMODE(info.st_mode)==0o600 and info.st_nlink==1
                        and child==self.root/'shared/solana-evidence.sqlite.sock','prewrite_entry_type')

    def metadata_sha256(self):
        self.validate()
        rows=[[str(path.relative_to(self.root)),before] for path,(_fd,before,_sql) in self.files.items()]
        rows += [[str(path.relative_to(self.root)),before] for path,before in self.directories.items()]
        return hashlib.sha256(json.dumps(sorted(rows),separators=(',',':')).encode()).hexdigest()

    def __enter__(self):
        try:
            self._locks();self._walk(self.root)
            certificate=self.launch.require_current(initial=True)['boot_eligibility']
            require(self.metadata_sha256()==certificate['physical_generation_sha256'],'prewrite_physical_generation')
            for path,(fd,_before,sqlite) in self.files.items():
                if not sqlite:continue
                require(len(self.databases)<512,'prewrite_database_bound')
                # No WAL header/frames may be ignored. Exactly zero bytes has
                # no committed frames; the pinned empty support file and the
                # held sole-writer fences must remain unchanged through replay.
                wal=self.files.get(Path(str(path)+'-wal'))
                require(wal is None or wal[1][6]==0,'prewrite_nonempty_wal')
                require(Path(str(path)+'-journal') not in self.files,'prewrite_rollback_journal')
                # SQLite opens the held main inode, never a second pathname
                # lookup that could follow a replaced database between checks.
                db=sqlite3.connect('file:/proc/self/fd/'+str(fd)+'?mode=ro&immutable=1',
                    uri=True,timeout=0,isolation_level=None)
                self.stack.callback(db.close)
                db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF')
                db.set_progress_handler(lambda:int(self.cancelled() is not False
                    or time.monotonic()>=self.deadline),1000)
                db.execute('BEGIN');self.databases[path]=db
            self.validate();return self
        except BaseException:self.stack.close();raise

    def __exit__(self,kind,value,trace):
        try:
            if kind is None:self.validate()
        finally:self.stack.close()


def _configured_databases(root):
    from meme_machine.runtime.native_flat_boot import configured_flat_boot_dependencies
    required=configured_flat_boot_dependencies(root)|{root/'shared'/name for name in
        ('solana-evidence.sqlite','solana-candidate-history.sqlite','provider-usage.continuous.sqlite')}
    names=('pump/pump-acceleration-natural-prospective.pipeline.sqlite','pump/solana-evidence-broker.sqlite3',
        'shared/solana-provider.sqlite','shared/robinhood-provider.sqlite','shared/robinhood-evidence.sqlite',
        'pons/pons-selective-continuation-v1-cohort/opportunity-pipeline.sqlite',
        'pons/pons-selective-continuation-v1-cohort/pons-selective-wallet-skill.sqlite',
        'ramses/robinhood-ramses-extended-market.sqlite.pipeline.sqlite')
    return required,required|{root/name for name in names}


def _source_inputs(db):
    from meme_machine.solana_source_drain import _retained_census,_retained_handlers,_committed_census
    values={};census=None
    for key,maximum in SOURCE_INPUTS.items():
        row=db.execute('SELECT length(CAST(value AS BLOB)),CASE WHEN length(CAST(value AS BLOB))<=? '
            'THEN CAST(value AS BLOB) END FROM service_health WHERE key=?',(maximum,key)).fetchone()
        if row is None:values[key]=None;continue
        require(type(row[0]) is int and type(row[1]) is bytes and 0<len(row[1])==row[0]<=maximum,
            'prewrite_source_input_bound')
        values[key]=dict(bytes=row[0],sha256=hashlib.sha256(row[1]).hexdigest())
        if key=='source_drain':census=_retained_census(row[1].decode())
        elif key=='source_handler_recovery':_retained_handlers(row[1].decode())
    require(census is not None,'prewrite_source_drain_missing')
    require(_committed_census(census),'prewrite_source_drain_uncommitted')
    return values,census


class BootContext:
    """Private same-instance boot result; never a positive source/readiness claim."""
    __slots__=('_launch','_root','_owner','_identity','_closed','_support')
    def __init__(self,launch,root,identity,*,_issuer=None,_support=None):
        require(_issuer is _ISSUER,'context_issuer')
        self._launch=launch;self._root=root;self._owner=(os.getpid(),threading.get_ident())
        self._identity=deepcopy(identity);self._closed=False;self._support=deepcopy(_support)

    def require_current(self):
        require(not self._closed and self._owner==(os.getpid(),threading.get_ident()),'context_owner')
        self._launch.require_current()
        require(_source_identity()==(self._identity['application_commit'],self._identity['application_tree']),
            'context_source_changed')
        return deepcopy(self._identity)

    def close(self):self._closed=True

    def boot_support(self):
        from .normal_boot_support import _for_boot
        return _for_boot(self)


def consume_normal_boot(supervisor,*,cancelled):
    """The only issuer: exact sealed root instance plus actual original replays."""
    global _ACTIVE
    require(_ACTIVE is None,'context_already_consumed')
    launch=await_normal_launch(cancelled=cancelled);record=launch.require_current(initial=True)
    certificate=record['boot_eligibility'];root=Path(supervisor.root)
    require(_source_identity()==(record['application_commit'],record['application_tree']),'source_identity')
    from .position_continuation import load_continuous
    profile=load_continuous()
    require(sorted(profile['funding_regimes'])==list(REGIMES)
        and digest(profile)==certificate['continuous_profile_sha256'],'profile_identity')
    with _OwnedPrewriteReads(supervisor,launch,cancelled=cancelled) as reads:
        required,allowed=_configured_databases(root)
        require(required<=reads.databases.keys(),'configured_database_missing')
        cohort=root/'pons/pons-selective-continuation-v1-cohort'
        for path,db in reads.databases.items():
            trial=path.parent==cohort and re.fullmatch(r'trial-\d+\.sqlite',path.name) is not None
            require(path in allowed or trial,'unmapped_database')
            if path not in required and not trial:
                tables=db.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 257").fetchall()
                require(len(tables)<=256 and not any(any(word in table.lower() for word in
                    ('position','reservation','obligation','intent')) and table not in
                    ('position_service','receipt_obligations') for table, in tables),'ancillary_economics')
        from meme_machine.runtime.native_restore_context import StoppedNativeReadContext
        from meme_machine.runtime.native_flat_boot import validate_stopped_flat_boot_inputs
        context=StoppedNativeReadContext(root,reads.databases,validate_snapshot=reads.validate,
            validate_owner=_owner_dead,artifacts=reads.artifacts,deadline=reads.deadline)
        try:
            value=validate_stopped_flat_boot_inputs(context,cancelled=cancelled).value()
            state=context.ledger()
            require(reads.databases[root/'portfolio.sqlite'].execute(
                'SELECT count(*) FROM portfolio_native_pending').fetchone()==(0,),'legacy_pending')
            for key in ('epoch_id','inception_sha256','journal_hash','projection_hash','combined_sequence',
                    'native_input_sha256','policy_sha256'):
                require(value[key]==certificate[key],'native_or_financial_generation')
            source,census=_source_inputs(reads.databases[root/'shared/solana-evidence.sqlite'])
            require(source==certificate['source_inputs'] and census['pending_handlers']==
                certificate['unknown_historical_handlers'],'retained_source_inputs')
            from .normal_source_boot import validate_prewrite_generation
            validate_prewrite_generation(reads.databases[root/'shared/solana-evidence.sqlite'],
                root=root,source_inputs=source,unknown_historical_handlers=certificate['unknown_historical_handlers'])
            from .current_provider_history import current_provider_book
            provider=current_provider_book(reads.databases[root/'shared/provider-usage.continuous.sqlite'],state,
                profile=profile,configured_path=os.environ.get('MM_PROVIDER_USAGE_DB'),
                expected_path=root/'shared/provider-usage.continuous.sqlite')
            require(provider['ledger_funding_closed'] and not provider['ledger_failure_recorded']
                and provider['readiness_owner_matches_previous_run']
                and time.time()>=provider['backoff_until'] and all(provider['counters'][name]==0
                    for name in ('http_reserved','native_reserved'))
                and all(row['open_rows']==0 for row in provider['transports'].values()),'provider_controls')
            from .normal_boot_support import _capture
            support=_capture(reads,record,launch._locator['record_sha256'])
            require(reads.metadata_sha256()==certificate['physical_generation_sha256'],'prewrite_physical_generation')
        finally:context.close()
    launch.require_current(initial=True)
    require(_source_identity()==(record['application_commit'],record['application_tree']),'source_changed_after_replay')
    identity=dict(schema='normal-private-boot-v1',instance=record['instance'],boot_id=record['boot_id'],
        certificate_sha256=certificate['certificate_sha256'],application_commit=record['application_commit'],
        application_tree=record['application_tree'],supervisor=deepcopy(record['supervisor']),
        epoch_id=value['epoch_id'],inception_sha256=value['inception_sha256'],
        preserved_source_inputs=source,unknown_historical_handlers=certificate['unknown_historical_handlers'])
    context=BootContext(launch,root,identity,_issuer=_ISSUER,_support=support)
    # Final Git/unit checks are fallible work, not an acceptance-time snapshot.
    # Recheck their original window and cancellation after they finish and
    # immediately before the private context becomes reachable by any caller.
    launch.require_current(initial=True)
    require(cancelled() is False,'cancelled_before_context')
    require(record['issued_monotonic']<=time.monotonic()<record['not_after_monotonic'],
        'expired_before_context')
    launch._consumed=True
    _ACTIVE=context
    return _ACTIVE


def require_boot_context(value):
    require(type(value) is BootContext and value is _ACTIVE,'private_context_required')
    value.require_current();return value
