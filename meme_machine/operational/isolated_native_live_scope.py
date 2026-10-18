"""Explicit disposable LIVE observation scope; never an offline Scratch label.

The protected caller supplies original authenticated diagnostic identity and its
live validation callback. The original engineering admission/growth/retention
policy still owns this new private /tmp allocation. No authority, paths, image,
request selector or provider work is accepted from child wire data.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import shutil
import sys
import tempfile
import threading

from .artifact_storage import Scratch
from .isolated_native_image import NativeImageApproval
from . import namespace_canary as boundary

SCHEMA='disposable-live-native-scope-v1'
CLASSIFICATION='DISPOSABLE_LIVE_NATIVE_OBSERVATION'
REQUEST_FIELDS=frozenset(('action','request_id','application_commit','application_tree',
    'administration_commit','output'))


def _encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _require(condition,code):
    if not condition:raise ValueError(code)


def _process(pid):
    raw=Path('/proc/'+str(pid)+'/stat').read_bytes()
    _require(len(raw)<=4096,'live_scope_process_identity')
    head,tail=raw.decode('ascii').rsplit(')',1)
    _require(int(head.split('(',1)[0])==pid,'live_scope_process_identity')
    ticks=int(tail.split()[19]);_require(ticks>0,'live_scope_process_identity')
    return ticks


def _marker(path):
    path=Path(path);info=path.lstat()
    _require(stat.S_ISREG(info.st_mode) and info.st_uid==os.geteuid() and info.st_nlink==1
        and stat.S_IMODE(info.st_mode)==0o600 and info.st_size<=4096,'live_scope_marker_inode')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        current=os.fstat(fd)
        _require((current.st_dev,current.st_ino)==(info.st_dev,info.st_ino),'live_scope_marker_changed')
        raw=os.read(fd,4097)
        _require(len(raw)==info.st_size and len(raw)<=4096,'live_scope_marker_bound')
        return raw,(info.st_dev,info.st_ino)
    finally:os.close(fd)


def verify_live_scope(path,statement,*,parent_pid,approval):
    """Verify a protected setup-pipe statement, not a self-authenticating hash."""
    path=boundary._private(path)
    keys={'schema','marker_sha256','marker_device','marker_inode','parent_pid','parent_start',
        'source_commit','source_tree','request_sha256','invocation_id'}
    _require(type(statement) is dict and set(statement)==keys and statement['schema']==SCHEMA
        and type(statement['parent_pid']) is int and statement['parent_pid']==parent_pid
        and type(statement['parent_start']) is int and statement['parent_start']==_process(parent_pid),
        'live_scope_setup_identity')
    _require(all(type(statement[name]) is str and re.fullmatch('[0-9a-f]{'+str(length)+'}',statement[name])
        for name,length in (('marker_sha256',64),('source_commit',40),('source_tree',40),
                            ('request_sha256',64),('invocation_id',32))), 'live_scope_setup_binding')
    _require(all(statement[name]==approval[name] for name in ('source_commit','source_tree')),
        'live_scope_source_binding')
    raw,identity=_marker(path/'engineering-artifact.json')
    _require(identity==(statement['marker_device'],statement['marker_inode'])
        and hashlib.sha256(raw).hexdigest()==statement['marker_sha256'],'live_scope_marker_changed')
    value=json.loads(raw)
    _require(raw==_encoded(value) and value.get('schema')==SCHEMA and value.get('status')=='RUNNING'
        and value.get('classification')==CLASSIFICATION and value.get('financial_authority') is False
        and value.get('production_state_writes')==0
        and all(value.get(name)==statement[name] for name in
            ('parent_pid','parent_start','source_commit','source_tree','request_sha256','invocation_id')),
        'live_scope_marker_binding')
    return path


class LiveNativeScope(Scratch):
    """Exact diagnose/source/unit scope, sharing original scratch accounting.

    The marker's hashes bind original protected-caller facts; they do not prove
    a caller supplied an authentic request or service identity. The caller must
    hold its separately reviewed diagnostic fence for the whole scope lifetime.
    """
    def __init__(self,request,approval,*,unit_identity,validate_scope):
        _require(type(approval) is NativeImageApproval and type(request) is dict
            and set(request)==REQUEST_FIELDS and request['action']=='diagnose'
            and type(request['request_id']) is str
            and re.fullmatch('[a-z0-9][a-z0-9-]{0,31}',request['request_id'])
            and callable(validate_scope),'live_scope_protected_caller_required')
        source=approval.value()
        _require(all(request['application_'+part]==source['source_'+part] for part in ('commit','tree')),
            'live_scope_source_binding')
        _require(type(request['administration_commit']) is str
            and re.fullmatch('[0-9a-f]{40}',request['administration_commit']), 'live_scope_request_binding')
        _require(type(unit_identity) is dict and set(unit_identity)=={
            'invocation_id','MainPID','ExecMainStartTimestampMonotonic','NRestarts'}
            and type(unit_identity['MainPID']) is int and unit_identity['MainPID']==os.getpid()
            and type(unit_identity['ExecMainStartTimestampMonotonic']) is int
            and unit_identity['ExecMainStartTimestampMonotonic']>0
            and unit_identity['NRestarts']==0 and type(unit_identity['NRestarts']) is int
            and type(unit_identity['invocation_id']) is str
            and re.fullmatch('[0-9a-f]{32}',unit_identity['invocation_id']), 'live_scope_unit_binding')
        self._approval=approval;self._validate_scope=validate_scope
        self._owner=(os.getpid(),threading.get_ident());self._started=_process(os.getpid())
        self._binding=dict(parent_pid=os.getpid(),parent_start=self._started,
            source_commit=source['source_commit'],source_tree=source['source_tree'],
            request_sha256=hashlib.sha256(_encoded(request)).hexdigest(),
            invocation_id=unit_identity['invocation_id'])
        self._statement=None;self._finished=False;self._parent_owner=None
        # PrivateTmp /tmp is explicit; no environment-selectable production
        # root or root-owned operations output becomes a child image scope.
        super().__init__(parent=Path('/tmp'))

    def _owner_current(self):
        _require(not self._finished and self._owner==(os.getpid(),threading.get_ident())
            and _process(os.getpid())==self._started,'live_scope_owner')
        _require(self._validate_scope() is True,'live_scope_host_fence_unverified')

    def __enter__(self):
        self._owner_current()
        try:
            super().__enter__();self.check()
        except BaseException as error:
            if hasattr(self,'previous_tempdir'):
                try:self.__exit__(type(error),error,error.__traceback__)
                except BaseException as cleanup:raise error from cleanup
            raise
        return self

    def register_parent_owner(self,parent):
        from .isolated_native_live_parent import LiveNativeParent
        self._owner_current()
        _require(self._parent_owner is None and type(parent) is LiveNativeParent,
            'live_scope_parent_owner')
        self._parent_owner=parent

    def mark(self,status):
        _require(status in ('RUNNING','VERIFIED_DISPOSABLE','FAILED_EVIDENCE_RETAINED'),
            'live_scope_terminal_state')
        value=dict(schema=SCHEMA,classification=CLASSIFICATION,status=status,
            financial_authority=False,production_state_writes=0,max_bytes=self.policy.scratch_max_bytes,
            **self._binding)
        raw=_encoded(value);path=self.path/'engineering-artifact.json'
        if path.exists():
            previous,identity=_marker(path)
            _require(self._statement is not None and hashlib.sha256(previous).hexdigest()==
                self._statement['marker_sha256'] and identity==(
                    self._statement['marker_device'],self._statement['marker_inode']),'live_scope_marker_changed')
        temporary=path.with_name('engineering-artifact.new')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        info=path.lstat()
        self._statement=dict(schema=SCHEMA,marker_sha256=hashlib.sha256(raw).hexdigest(),
            marker_device=info.st_dev,marker_inode=info.st_ino,**self._binding)

    def require_launch(self,approval):
        self._owner_current()
        return self._bound_path(approval)

    def _bound_path(self,approval):
        _require(approval is self._approval and self.path is not None,'live_scope_approval_owner')
        _require(not self._finished and self._owner==(os.getpid(),threading.get_ident()),'live_scope_owner')
        return verify_live_scope(self.path,self._statement,parent_pid=os.getpid(),approval=approval.value())

    def statement(self,approval):
        self.require_launch(approval)
        return json.loads(_encoded(self._statement))

    def check(self):
        # Original .25s growth checks need only the retained exact scope binding;
        # provider/publication and main-loop boundaries validate the actual host
        # fence independently. Avoid spawning host/Git probes on every byte scan.
        self._bound_path(self._approval)
        super().check()

    def __exit__(self,kind,value,traceback):
        # Success is an explicit caller disposition, after curated evidence and
        # all real owners join. A lost fence can never authorize tree deletion.
        try:
            if kind is None and self.success:
                try:
                    self._owner_current();self.require_launch(self._approval)
                    _require(self._parent_owner is None or self._parent_owner.parent_owners_joined() is True,
                        'live_scope_parent_not_joined')
                except BaseException as primary:
                    try:self.mark('FAILED_EVIDENCE_RETAINED')
                    except BaseException as cleanup:raise primary from cleanup
                    print('Live native observation evidence retained at '+str(self.path),file=sys.stderr)
                    raise
                self.mark('VERIFIED_DISPOSABLE');shutil.rmtree(self.path)
            else:
                self.mark('FAILED_EVIDENCE_RETAINED')
                print('Live native observation evidence retained at '+str(self.path),file=sys.stderr)
        finally:
            tempfile.tempdir=self.previous_tempdir
            if self.previous_env is None:os.environ.pop('TMPDIR',None)
            else:os.environ['TMPDIR']=self.previous_env
            self._finished=True
