"""Bounded attribution at explicitly selected SQLite boundaries.

This is diagnostic information, never evidence or a retry policy. No SQL text,
arguments, exception message or frame locals are retained. The first failure is
attached to its original exception before rollback/close or optional probes.
"""
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
from urllib.parse import unquote, urlsplit

MAX_TERMINAL_BYTES=64*1024
MAX_RING_BYTES=1024*1024
_ring=deque(maxlen=128)
_ring_lock=threading.Lock()
_coverage_valid=True
_scope=ContextVar('sqlite_failure_scope',default=None)
_run=str(os.getpid())+'-'+str(time.time_ns())
_fixed=re.compile(r'[a-zA-Z_][a-zA-Z0-9_.:-]{0,127}\Z')


def _path(database):
    value=os.fsdecode(database)
    if value==':memory:':return value
    if value.startswith('file:'):
        value=unquote(urlsplit(value).path)
    return str(Path(value).absolute())


def _origin(exc):
    result=None;trace=exc.__traceback__
    for _ in range(64):
        if trace is None:break
        module=trace.tb_frame.f_globals.get('__name__','')
        function=trace.tb_frame.f_code.co_name
        if (isinstance(module,str) and re.fullmatch(r'meme_machine\.[A-Za-z0-9_.]{1,180}',module)
                and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',function)):
            result=dict(module=module,function=function,line=trace.tb_lineno)
        trace=trace.tb_next
    if result is not None and result['module']!=__name__:return result
    # An exception is caught before its caller has been added to traceback.
    # Preserve that owned call site without retaining any frame or locals.
    frame=sys._getframe(1)
    for _ in range(32):
        if frame is None:break
        module=frame.f_globals.get('__name__','');function=frame.f_code.co_name
        if (module!=__name__ and isinstance(module,str) and
                re.fullmatch(r'meme_machine\.[A-Za-z0-9_.]{1,180}',module) and
                re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',function)):
            return dict(module=module,function=function,line=frame.f_lineno)
        frame=frame.f_back
    return result


def _breadcrumb(row):
    # Fixed-size entries, no statements/parameters or data-dependent strings.
    global _coverage_valid
    try:
        # At most 128 entries of at most 4096 encoded bytes, below the 1-MiB
        # bound even when a fixed identifier uses multibyte characters.
        if len(json.dumps(row,separators=(',',':')).encode())>4096:
            raise ValueError('sqlite_diagnostic_ring_entry_bound')
        with _ring_lock:_ring.append(row)
        return True
    except BaseException:
        _coverage_valid=False
        return False


def _facts(exc,metadata,phase,started,db=None):
    now=time.monotonic()
    facts=dict(version=1,run_identity=_run,operation=phase,
        scope=_scope.get(),database=metadata['database'],opening_mode=metadata['opening_mode'],
        configured_database_identity_sha256=metadata.get('database_identity'),
        database_identity_truncated=metadata.get('database_identity_truncated',False),
        connection_role=metadata.get('role'),
        connection_identity=metadata.get('connection_identity'),
        timeout_seconds=metadata.get('timeout_seconds'),
        opened_monotonic=metadata.get('opened_monotonic'),
        operation_started_monotonic=started,failed_monotonic=now,
        operation_seconds=max(0,now-started),pid=os.getpid(),native_thread_id=threading.get_native_id(),
        sqlite_errorcode=getattr(exc,'sqlite_errorcode',None),
        sqlite_errorname=getattr(exc,'sqlite_errorname',None),origin=_origin(exc),
        transaction_started_monotonic=metadata.get('transaction_started_monotonic'),
        journal_mode_requested=metadata.get('journal_mode_requested'),
        busy_timeout_milliseconds=metadata.get('busy_timeout_milliseconds'),
        database_device=metadata.get('database_device'),database_inode=metadata.get('database_inode'),
        recorder_valid=_coverage_valid)
    # Capture essential facts before anything that could itself fail.
    exc.sqlite_failure=facts
    try:facts['in_transaction']=None if db is None else bool(db.in_transaction)
    except BaseException:facts['in_transaction']=None
    if not _breadcrumb(dict(operation=phase,pid=facts['pid'],native_thread_id=facts['native_thread_id'],
        connection_identity=facts['connection_identity'],at=now,failed=True)):
        facts['recorder_valid']=False
    with _ring_lock:facts['recent_operations']=[dict(row) for row in list(_ring)[-32:]]
    return facts


def annotate(exc,metadata,phase,started,db=None):
    """Never replace an error or its first attribution, including on cleanup."""
    if not isinstance(exc,sqlite3.Error) or hasattr(exc,'sqlite_failure'):return
    try:_facts(exc,metadata,phase,started,db)
    except BaseException:
        try:exc.sqlite_failure=dict(recorder_valid=False,operation=phase,pid=os.getpid(),
            native_thread_id=threading.get_native_id(),run_identity=_run)
        except BaseException:pass


def payload(exc):
    """A separately bounded terminal record; no dependence on a capped trace."""
    value=getattr(exc,'sqlite_failure',None)
    if not isinstance(value,dict):return None
    try:
        encoded=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
        # Four errors (original plus three causes) share one terminal channel.
        if len(encoded.encode())>(MAX_TERMINAL_BYTES-4096)//4:
            value={k:v for k,v in value.items() if k!='recent_operations'}
            value=dict(value,recorder_valid=False,ring_truncated=True)
        return value
    except BaseException:return dict(recorder_valid=False,terminal_encoding_failed=True)


def coverage_status():
    """Cheap local health for an explicitly required diagnostic recorder."""
    with _ring_lock:entries=len(_ring)
    return dict(recorder_valid=_coverage_valid,run_identity=_run,pid=os.getpid(),
        retained_operation_entries=entries,ring_upper_bound_bytes=entries*4096,
        ring_limit_bytes=MAX_RING_BYTES,terminal_limit_bytes=MAX_TERMINAL_BYTES)


def carry(source,target):
    """Retain only owned facts through an existing redacting error wrapper."""
    diagnostic=payload(source)
    if diagnostic is not None and not hasattr(target,'sqlite_failure'):
        target.sqlite_failure=dict(diagnostic)
    return target


def write_terminal_record(path,report):
    """Publish one new durable terminal record, independently of a capped trace.

    Explicit diagnostic configuration only. No directory creation, existing-file
    replacement, database access or general log persistence is performed.
    """
    data=report.encode()
    if len(data)>MAX_TERMINAL_BYTES:raise ValueError('sqlite_terminal_record_bound')
    destination=Path(path)
    if not destination.is_absolute() or not destination.name:
        raise ValueError('sqlite_terminal_record_path')
    parent=destination.parent
    if parent.resolve(strict=True)!=parent:raise ValueError('sqlite_terminal_record_parent_symlink')
    directory=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    temporary='.sqlite-terminal-'+str(os.getpid())+'-'+str(time.time_ns())+'.tmp'
    descriptor=None
    try:
        info=os.fstat(directory)
        if info.st_uid!=os.geteuid() or info.st_mode & 0o022:
            raise ValueError('sqlite_terminal_record_parent_ownership')
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
        view=memoryview(data)
        while view:
            written=os.write(descriptor,view)
            if written<=0:raise OSError('sqlite_terminal_record_short_write')
            view=view[written:]
        os.fsync(descriptor);os.close(descriptor);descriptor=None
        # A hard-link publishes the complete same-directory file atomically and
        # fails if the final record already exists. It cannot overwrite evidence.
        os.link(temporary,destination.name,src_dir_fd=directory,dst_dir_fd=directory,follow_symlinks=False)
        os.fsync(directory)
    finally:
        try:
            if descriptor is not None:os.close(descriptor)
        finally:
            try:os.unlink(temporary,dir_fd=directory)
            except FileNotFoundError:pass
            finally:os.close(directory)


class Connection(sqlite3.Connection):
    def _call(self,method,phase,*args,**kwargs):
        started=time.monotonic()
        try:result=method(*args,**kwargs)
        except sqlite3.Error as exc:
            annotate(exc,self._failure_metadata,phase,started,self);raise
        if phase in ('BEGIN','COMMIT','ROLLBACK','SAVEPOINT','RELEASE','checkpoint','close'):
            _breadcrumb(dict(operation=phase,pid=os.getpid(),native_thread_id=threading.get_native_id(),
                connection_identity=self._failure_metadata['connection_identity'],
                database_identity=self._failure_metadata['database_identity'],database_device=self._failure_metadata.get('database_device'),
                database_inode=self._failure_metadata.get('database_inode'),
                started=started,at=time.monotonic(),failed=False))
        if phase=='BEGIN':self._failure_metadata['transaction_started_monotonic']=started
        elif phase in ('COMMIT','ROLLBACK'):self._failure_metadata['transaction_started_monotonic']=None
        return result

    @staticmethod
    def _phase(sql):
        # Inspect only a fixed leading verb. Never retain/hashes expanded SQL.
        words=sql[:64].lstrip().split(None,1)
        verb=words[0].upper() if words else 'statement'
        if verb=='PRAGMA' and sql[:64].lstrip().upper().startswith('PRAGMA WAL_CHECKPOINT'):
            return 'checkpoint'
        return verb if verb in ('SELECT','INSERT','UPDATE','DELETE','BEGIN','COMMIT','ROLLBACK',
            'SAVEPOINT','RELEASE','PRAGMA','CREATE','DROP','ALTER','WITH') else 'statement'

    def execute(self,sql,parameters=(),/):
        result=self.cursor().execute(sql,parameters)
        if sql[:6].upper()=='PRAGMA':
            fixed=sql[:96].strip().upper()
            if fixed=='PRAGMA JOURNAL_MODE=WAL':self._failure_metadata['journal_mode_requested']='wal'
            match=re.fullmatch(r'PRAGMA BUSY_TIMEOUT\s*=\s*([0-9]{1,8})',fixed)
            if match:self._failure_metadata['busy_timeout_milliseconds']=int(match[1])
        return result

    def executemany(self,sql,parameters,/):
        return self.cursor().executemany(sql,parameters)

    def executescript(self,sql_script,/):
        return self.cursor().executescript(sql_script)

    def cursor(self,factory=None):
        # sqlite3.Connection.execute otherwise creates an uninstrumented native
        # cursor. Preserve the Cursor API and caller-provided factories.
        return self._call(super().cursor,'cursor_open',factory=Cursor if factory is None else factory)

    def commit(self):return self._call(super().commit,'COMMIT')
    def rollback(self):return self._call(super().rollback,'ROLLBACK')
    def close(self):
        with preserving_cleanup():return self._call(super().close,'close')

    def __exit__(self,kind,error,trace):
        try:return self._call(super().__exit__,'context_exit',kind,error,trace)
        except BaseException:
            if error is None:raise
            # Return False so the original body error propagates unchanged.
            return False


class Cursor(sqlite3.Cursor):
    def execute(self,sql,parameters=(),/):
        self._failure_phase=self.connection._phase(sql)
        return self.connection._call(super().execute,self._failure_phase,sql,parameters)

    def executemany(self,sql,parameters,/):
        self._failure_phase=self.connection._phase(sql)
        return self.connection._call(super().executemany,self._failure_phase,sql,parameters)

    def executescript(self,script,/):
        self._failure_phase='schema_script'
        return self.connection._call(super().executescript,self._failure_phase,script)

    def fetchone(self):
        return self.connection._call(super().fetchone,getattr(self,'_failure_phase','read')+'.fetchone')

    def fetchall(self):
        return self.connection._call(super().fetchall,getattr(self,'_failure_phase','read')+'.fetchall')

    def fetchmany(self,size=None):
        args=() if size is None else (size,)
        return self.connection._call(super().fetchmany,getattr(self,'_failure_phase','read')+'.fetchmany',*args)

    def __next__(self):
        # Avoid a clock/read-result wrapper for every successful row. The
        # operation timer remains the query's original execution start.
        try:return super().__next__()
        except sqlite3.Error as exc:
            now=time.monotonic()
            annotate(exc,self.connection._failure_metadata,
                getattr(self,'_failure_phase','read')+'.iterate',now,self.connection)
            raise


def connect(database,*args,diagnostic_role,**kwargs):
    """Explicit factory for reached paths; never monkeypatch sqlite globally."""
    if not _fixed.fullmatch(diagnostic_role):raise ValueError('sqlite_diagnostic_role')
    mode='ro' if kwargs.get('uri') and 'mode=ro' in os.fsdecode(database) else \
        'rw' if kwargs.get('uri') and 'mode=rw' in os.fsdecode(database) else 'rwc'
    started=time.monotonic()
    global _coverage_valid
    try:identity=_path(database)
    except BaseException:
        identity='UNAVAILABLE';_coverage_valid=False
    identity_bytes=os.fsencode(identity)
    identity_hash=hashlib.sha256(identity_bytes).hexdigest()
    truncated=len(identity_bytes)>4096
    if truncated:
        identity=identity_bytes[:1024].decode('utf-8',errors='ignore');_coverage_valid=False
    metadata=dict(database=identity,database_identity_truncated=truncated,opening_mode=mode,role=diagnostic_role,
        timeout_seconds=kwargs.get('timeout',args[0] if args else 5),opened_monotonic=started)
    metadata['busy_timeout_milliseconds']=int(metadata['timeout_seconds']*1000)
    metadata['database_identity']=identity_hash
    try:db=sqlite3.connect(database,*args,factory=Connection,**kwargs)
    except sqlite3.Error as exc:
        annotate(exc,metadata,diagnostic_role+'.open',started);raise
    metadata['connection_identity']=str(os.getpid())+':'+format(id(db),'x')
    db._failure_metadata=metadata
    # Optional file identity follows initialized essential metadata. No SQL probe.
    try:
        stat=Path(metadata['database']).stat()
        metadata.update(database_device=stat.st_dev,database_inode=stat.st_ino)
    except Exception:pass
    _breadcrumb(dict(operation=diagnostic_role+'.open',pid=os.getpid(),native_thread_id=threading.get_native_id(),
        connection_identity=metadata['connection_identity'],database_identity=metadata['database_identity'],
        database_device=metadata.get('database_device'),database_inode=metadata.get('database_inode'),
        at=started,failed=False))
    return db


def boundary(phase,path):
    """Catch read/fetch errors at existing capture/deliver/ACK boundaries."""
    if not _fixed.fullmatch(phase):raise ValueError('sqlite_diagnostic_phase')
    def decorate(function):
        @wraps(function)
        def wrapped(*args,**kwargs):
            token=_scope.set(phase);started=time.monotonic()
            try:return function(*args,**kwargs)
            except sqlite3.Error as exc:
                # The selected connection normally already recorded the actual
                # executor. This fallback explicitly reports no connection.
                try:
                    metadata=dict(database=_path(path(*args,**kwargs)),opening_mode='unknown')
                    annotate(exc,metadata,phase,started)
                except BaseException:pass
                raise
            finally:_scope.reset(token)
        return wrapped
    return decorate


def checkpoint_result(db,result):
    """Record an already acquired busy-return tuple, never another SQL read."""
    try:
        metadata=getattr(db,'_failure_metadata',None)
        if not isinstance(metadata,dict):return result
        if (isinstance(result,tuple) and len(result)==3 and
                all(type(value) is int for value in result)):
            _breadcrumb(dict(operation='checkpoint_return',connection_identity=metadata['connection_identity'],
                database_identity=metadata['database_identity'],database_device=metadata.get('database_device'),
                database_inode=metadata.get('database_inode'),pid=os.getpid(),native_thread_id=threading.get_native_id(),
                at=time.monotonic(),busy=result[0],wal_frames=result[1],checkpointed_frames=result[2]))
    except BaseException:
        global _coverage_valid
        _coverage_valid=False
    return result


@contextmanager
def preserving_cleanup():
    """A failure in rollback/close must not replace the error being unwound."""
    original=sys.exception()
    try:yield
    except BaseException:
        if original is None:raise
        # The original object already owns its first facts. Cleanup errors have
        # their own facts when SQLite was responsible, but are not the terminal
        # failure. Never format either error's text.
