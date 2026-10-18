"""Private one-shot source launch; neither source completeness nor allocation.

Only the sealed Supervisor's actual BootContext may issue. The child consumes
an anonymous inherited Unix channel before provider or native constructors.
Root data, actual kernel identities and the original clock authenticate the
scope; no serialized readiness Boolean is accepted.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import struct
import subprocess
import threading
import time
import uuid
import re

from .normal_boot_record import (UNIT,NormalBootUnavailable,_read_record,canonical,digest,
    hex_value,positive,require,uuid_value,SOURCE_INPUTS)

MAX_CHANNEL_BYTES=8192
KEY='source_drain_current_generation'
_ISSUER=object()
_ISSUED_CONTEXT=None
_KEYS=set('schema launch source generation native_clock_sha256 root source_inputs '
    'unknown_historical_handlers issued_monotonic not_after_monotonic'.split())
_LAUNCH_KEYS=set('instance request_id stop_generation record_sha256 certificate_sha256 application_commit '
    'application_tree epoch_id inception_sha256 boot_id supervisor'.split())


def _process_start(pid):
    require(type(pid) is int and pid>1,'source_process_pid')
    try:
        raw=Path('/proc/'+str(pid)+'/stat').read_text()
        fields=raw.rsplit(')',1)[1].split()
        require(raw.split(' ',1)[0]==str(pid) and fields[0]!='Z' and positive(fields[19]),
            'source_process_identity')
        return fields[19]
    except (OSError,ValueError,IndexError):
        raise NormalBootUnavailable('normal_boot_source_process_unavailable') from None


def _clock_sha256():
    from meme_machine.runtime.provider_clock import current_identity
    # The original provider clock includes genuine boot and native time
    # namespace identity. Unavailable identity does not turn into a default.
    return hashlib.sha256(current_identity().encode()).hexdigest()


def _channel(fd):
    require(type(fd) is int and 3<=fd<=65535,'source_channel_fd')
    connected=socket.socket(fileno=fd)
    try:
        connected.set_inheritable(False)
        require(connected.family==socket.AF_UNIX and
            connected.getsockopt(socket.SOL_SOCKET,socket.SO_TYPE)==socket.SOCK_STREAM and
            connected.getsockname() in ('',b'') and connected.getpeername() in ('',b''),
            'source_anonymous_stream_required')
        return connected
    except BaseException:connected.close();raise


def _send(connected,value):
    raw=canonical(value)
    require(0<len(raw)<=MAX_CHANNEL_BYTES,'source_channel_bound')
    connected.sendall(struct.pack('!I',len(raw))+raw)


def _receive(connected,*,deadline):
    def exact(size):
        value=bytearray()
        while len(value)<size:
            remaining=deadline-time.monotonic()
            require(remaining>0,'source_channel_deadline')
            connected.settimeout(remaining)
            chunk=connected.recv(size-len(value))
            require(bool(chunk),'source_channel_eof');value.extend(chunk)
        return bytes(value)
    size=struct.unpack('!I',exact(4))[0]
    require(0<size<=MAX_CHANNEL_BYTES,'source_channel_bound')
    from .normal_boot_record import _json
    value=_json(exact(size))
    require(type(value) is dict,'source_channel_shape')
    return value


def _launch_identity(record,record_sha256):
    certificate=record['boot_eligibility']
    return dict(instance=record['instance'],request_id=record['request_id'],
        stop_generation=record['stop_generation'],record_sha256=record_sha256,
        certificate_sha256=certificate['certificate_sha256'],
        application_commit=record['application_commit'],application_tree=record['application_tree'],
        epoch_id=certificate['epoch_id'],inception_sha256=certificate['inception_sha256'],
        boot_id=record['boot_id'],supervisor=deepcopy(record['supervisor']))


def _packet(value):
    require(type(value) is dict and set(value)==_KEYS and value['schema']=='normal-source-subcap-v1',
        'source_subcap_fields')
    launch=value['launch'];source=value['source']
    require(type(launch) is dict and set(launch)==_LAUNCH_KEYS and type(source) is dict
        and set(source)=={'pid','start_ticks'} and type(source['pid']) is int and source['pid']>1
        and positive(source['start_ticks']),'source_subcap_identity')
    require(hex_value(launch['instance'],32) and type(launch['request_id']) is str
        and re.fullmatch('[a-z0-9-]{1,48}',launch['request_id']) is not None
        and (launch['stop_generation']=='INITIAL' or positive(launch['stop_generation']))
        and all(hex_value(launch[key],64) for key in ('record_sha256','certificate_sha256','inception_sha256'))
        and all(hex_value(launch[key],40) for key in ('application_commit','application_tree'))
        and uuid_value(launch['boot_id']) and type(launch['epoch_id']) is str
        and 0<len(launch['epoch_id'].encode())<=256,'source_subcap_launch')
    owner=launch['supervisor']
    require(type(owner) is dict and set(owner)=={'pid','start_ticks','invocation_id'}
        and type(owner['pid']) is int and owner['pid']>1 and positive(owner['start_ticks'])
        and hex_value(owner['invocation_id'],32),'source_subcap_supervisor')
    require(type(value['source_inputs']) is dict and set(value['source_inputs'])==set(SOURCE_INPUTS)
        and value['source_inputs']['source_drain'] is not None,'source_subcap_retained')
    for key,row in value['source_inputs'].items():
        require(row is None or type(row) is dict and set(row)=={'bytes','sha256'}
            and type(row['bytes']) is int and 0<row['bytes']<=SOURCE_INPUTS[key]
            and hex_value(row['sha256'],64),'source_subcap_retained')
    require(type(value['unknown_historical_handlers']) is int and value['unknown_historical_handlers']>=0
        and all(type(value[key]) in (int,float) and math.isfinite(value[key])
            for key in ('issued_monotonic','not_after_monotonic'))
        and 0<=value['issued_monotonic']<value['not_after_monotonic']<=value['issued_monotonic']+60,
        'source_subcap_interval')
    require(hex_value(value['generation'],32) and hex_value(value['native_clock_sha256'],64)
        and type(value['root']) is str and Path(value['root']).is_absolute()
        and '..' not in Path(value['root']).parts,'source_subcap_scope')
    return value


def _validate_child(value,locator,record,peer):
    _packet(value)
    owner=record['supervisor'];certificate=record['boot_eligibility']
    require(record['state']=='SEALED' and peer==(owner['pid'],os.getuid(),os.getgid())
        and os.getppid()==owner['pid'] and _process_start(owner['pid'])==owner['start_ticks'],
        'source_parent_instance')
    require(value['launch']==_launch_identity(record,locator['record_sha256']) and value['source']==
        {'pid':os.getpid(),'start_ticks':_process_start(os.getpid())},'source_child_instance')
    require(value['source_inputs']==certificate['source_inputs'] and
        value['unknown_historical_handlers']==certificate['unknown_historical_handlers'] and
        value['not_after_monotonic']==record['not_after_monotonic'] and
        record['issued_monotonic']<=value['issued_monotonic']<value['not_after_monotonic'],
        'source_retained_identity')
    require(value['root']==os.environ.get('MM_STATE_ROOT') and
        Path(os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB',''))==Path(value['root'])/'shared/solana-evidence.sqlite',
        'source_fixed_state')
    require(Path('/proc/sys/kernel/random/boot_id').read_text().strip()==record['boot_id'],
        'source_boot_identity')
    row=subprocess.run(['/usr/bin/systemctl','show',UNIT,'--property=MainPID,InvocationID,ActiveState'],
        check=True,capture_output=True,text=True,timeout=2)
    require(len(row.stdout.encode())<=2048,'source_unit_bound')
    fields=dict(line.split('=',1) for line in row.stdout.splitlines() if '=' in line)
    require(fields.get('MainPID')==str(owner['pid']) and fields.get('InvocationID')==owner['invocation_id']
        and fields.get('ActiveState') in ('active','activating'),'source_unit_identity')
    from .normal_boot import _source_identity
    require(_source_identity()==(record['application_commit'],record['application_tree']),
        'source_application_identity')
    require(_clock_sha256()==value['native_clock_sha256'],'source_native_clock')
    require(record['issued_monotonic']<=time.monotonic()<record['not_after_monotonic'],
        'source_launch_expired')


def _census(body,identity):
    from meme_machine.solana_source_drain import _retained_census,_committed_census,HandlerLedger
    require(type(body) is dict,'source_generation_census_fields')
    parsed=_retained_census(json.dumps(body,allow_nan=False))
    require(parsed.get('source_pid')==identity['source']['pid'] and
        parsed.get('run_identity')==identity['generation'],'source_generation_census_identity')
    ledger=parsed.get('handler_accounting')
    require(type(ledger) is dict and ledger.get('version')==1 and ledger.get('run')==identity['generation']
        and ledger.get('pid')==identity['source']['pid'] and type(ledger.get('native_thread_id')) is int
        and ledger['native_thread_id']>0 and type(ledger.get('valid')) is bool
        and ledger.get('accepted')==parsed['accepted_handlers']
        and ledger.get('returned')==parsed['settled_handlers'],'source_generation_handler_identity')
    require(all(type(ledger.get(key)) is int and ledger[key]>=0 for key in
        ('accepted','returned','active','recoverable','failed','unresolved','record_bytes')),
        'source_generation_handler_counts')
    rows=ledger.get('records')
    require(rows is None and not ledger['valid'] or type(rows) is list and len(rows)<=HandlerLedger.maximum_records,
        'source_generation_handler_records')
    if rows is not None:
        require(ledger['record_bytes']==len(json.dumps(rows,separators=(',',':')).encode()) and
            sum(ledger[key] for key in ('active','recoverable','failed','unresolved'))==len(rows)
            ==parsed['pending_handlers'],'source_generation_handler_population')
    require(all(type(parsed.get(key)) is int and parsed[key]>=0 for key in
        ('closed_sessions','unpreserved_sessions')),'source_generation_session_counts')
    if parsed.get('terminal') is True:
        require(all(type(parsed.get(key)) is int and parsed[key]>=0 for key in
            ('pending_history','pending_proofs')),'source_generation_pending_counts')
    if parsed['state']=='DRAINED':
        require(_committed_census(parsed) and parsed['pending_handlers']==0 and ledger['valid']
            and rows==[] and not parsed.get('unexpected_cancellation',False),'source_generation_drain')
    return parsed


class SourceLaunch:
    """One actual Supervisor child; no caller supplied successful packet."""
    def __init__(self,context):
        global _ISSUED_CONTEXT
        from .normal_boot import require_boot_context
        self.context=require_boot_context(context)
        require(_ISSUED_CONTEXT is None,'source_launch_already_issued')
        self.owner=(os.getpid(),threading.get_ident());self.process=None;self.closed=False
        self.parent,self.child=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
        self.parent.set_inheritable(False);self.child.set_inheritable(False)
        self.identity=None
        _ISSUED_CONTEXT=context

    @property
    def child_fd(self):
        require(not self.closed and self.process is None,'source_launch_state')
        return self.child.fileno()

    def bind(self,process,*,deadline):
        try:return self._bind(process,deadline=deadline)
        finally:self.close()

    def _bind(self,process,*,deadline):
        require(self.owner==(os.getpid(),threading.get_ident()) and not self.closed
            and self.process is None and type(process) is subprocess.Popen,'source_launch_owner')
        record=self.context._launch.require_current()
        require(time.monotonic()<deadline<=time.monotonic()+15 and
            time.monotonic()<record['not_after_monotonic'],'source_launch_deadline')
        self.context.require_current();self.process=process
        require(process.poll() is None and os.getsid(process.pid)==process.pid,'source_child_lifetime')
        value=dict(schema='normal-source-subcap-v1',launch=_launch_identity(record,
            self.context._launch._locator['record_sha256']),
            source={'pid':process.pid,'start_ticks':_process_start(process.pid)},generation=uuid.uuid4().hex,
            native_clock_sha256=_clock_sha256(),root=str(self.context._root),
            source_inputs=deepcopy(record['boot_eligibility']['source_inputs']),
            unknown_historical_handlers=record['boot_eligibility']['unknown_historical_handlers'],
            issued_monotonic=time.monotonic(),not_after_monotonic=record['not_after_monotonic'])
        try:
            self.child.close()
            self.parent.settimeout(max(.001,min(deadline,record['not_after_monotonic'])-time.monotonic()))
            _send(self.parent,value);ack=_receive(self.parent,
                deadline=min(deadline,record['not_after_monotonic']))
            require(ack==dict(schema='normal-source-subcap-accepted-v1',
                identity_sha256=digest(value)),'source_launch_ack')
            require(process.poll() is None and _process_start(process.pid)==value['source']['start_ticks']
                and time.monotonic()<min(deadline,record['not_after_monotonic']),
                'source_launch_handoff_expired')
            self.identity=deepcopy(value);return deepcopy(value)
        finally:self.close()

    def close(self):
        self.closed=True
        self.parent.close();self.child.close()


class NativeSourceGeneration:
    """Private received scope; no completed market or allocation claim."""
    __slots__=('_value','_identity_sha256','_pid','_owner_thread','_started','_boundary','_handler_boundary','_provider_identity','_registry')
    def __init__(self,value,*,_issuer=None):
        require(_issuer is _ISSUER,'source_generation_issuer')
        self._value=deepcopy(_packet(value));self._identity_sha256=digest(self._value)
        self._pid=os.getpid();self._owner_thread=None
        self._started=None;self._boundary=None;self._handler_boundary=None
        self._provider_identity=None
        self._registry=None

    @property
    def identity_sha256(self):return self._identity_sha256

    @property
    def generation(self):return self._value['generation']

    def identity(self):return deepcopy(self._value)

    def _owner(self,state):
        owner=threading.get_ident()
        require(self._pid==os.getpid() and state.writer._owner==owner and
            state.writer.path==Path(self._value['root'])/'shared/solana-evidence.sqlite',
            'source_generation_owner')
        if self._owner_thread is None:self._owner_thread=owner
        require(owner==self._owner_thread,'source_generation_thread')
        endpoint=state.fence.endpoint_identity
        require(hex_value(endpoint,64) and (self._provider_identity is None or endpoint==self._provider_identity),
            'source_generation_provider_identity')
        self._provider_identity=endpoint

    def begin(self,state,body):
        self._owner(state);require(self._started is None,'source_generation_started')
        from .normal_boot import _source_inputs
        values,census=_source_inputs(state.writer.db)
        require(values==self._value['source_inputs'] and
            census['pending_handlers']==self._value['unknown_historical_handlers'],
            'source_generation_retained_inputs')
        from meme_machine.solana_source_drain import (_health_from_db,SOURCE_DRAIN_KEY,
            SOURCE_DRAIN_BYTES,HANDLER_RECOVERY_KEY,HandlerLedger,_preserve_drain_bytes)
        self._boundary=_health_from_db(state.writer.db,SOURCE_DRAIN_KEY,SOURCE_DRAIN_BYTES)
        self._handler_boundary=_health_from_db(state.writer.db,HANDLER_RECOVERY_KEY,HandlerLedger.maximum_bytes)
        previous=_health_from_db(state.writer.db,KEY,SOURCE_DRAIN_BYTES)
        if previous is not None:
            previous=validate_current_generation(previous)
            require(previous['census']['state']=='DRAINED' and
                previous['census']['pending_handlers']==0,'source_previous_generation_unresolved')
        self._body(body,terminal=False)
        with state.writer.transaction():
            if previous is not None:
                raw=_health_from_db(state.writer.db,KEY,SOURCE_DRAIN_BYTES)
                _preserve_drain_bytes(state,KEY,raw,SOURCE_DRAIN_BYTES)
            state.fence._health(KEY,self._record(body))
        self._started=_health_from_db(state.writer.db,KEY,SOURCE_DRAIN_BYTES)
        return self._boundary,self._handler_boundary

    def _body(self,body,*,terminal):
        parsed=_census(body,self._value)
        require(parsed.get('terminal') is terminal and
            (terminal or parsed['state']=='RUNNING'),'source_generation_census_phase')

    def _record(self,body):
        from meme_machine.solana_source_drain import SOURCE_DRAIN_BYTES
        value=dict(schema='normal-source-generation-v1',identity=self.identity(),
            identity_sha256=self.identity_sha256,provider_identity=self._provider_identity,census=body)
        require(len(canonical(value))<=SOURCE_DRAIN_BYTES,'source_generation_record_bound')
        return value

    def publish(self,state,body):
        self._owner(state);require(self._started is not None,'source_generation_not_started')
        from meme_machine.solana_source_drain import (_health_from_db,assert_source_drain_boundary,SOURCE_DRAIN_BYTES)
        self._body(body,terminal=True)
        with state.writer.transaction():
            assert_source_drain_boundary(state,self._boundary,handler_boundary=self._handler_boundary)
            require(_health_from_db(state.writer.db,KEY,SOURCE_DRAIN_BYTES)==self._started,
                'source_generation_current_changed')
            wrapper=self._record(body)
            if self._registry is not None:self._registry.terminal(state,wrapper)
            state.fence._health(KEY,wrapper)


def validate_current_generation(raw):
    from meme_machine.solana_source_drain import _retained_json,SOURCE_DRAIN_BYTES
    require(type(raw) is str and 0<len(raw.encode())<=SOURCE_DRAIN_BYTES,'source_generation_record_bound')
    value=_retained_json(raw)
    require(type(value) is dict and set(value)=={'schema','identity','identity_sha256','provider_identity','census'}
        and value['schema']=='normal-source-generation-v1' and hex_value(value['provider_identity'],64),
        'source_generation_record_fields')
    identity=_packet(value['identity'])
    require(value['identity_sha256']==digest(identity),'source_generation_record_hash')
    _census(value['census'],identity)
    return value


def validate_prewrite_generation(db,*,root,source_inputs,unknown_historical_handlers):
    """Current-generation closure is separate from old callback disposition."""
    from meme_machine.solana_source_drain import _health_from_db,SOURCE_DRAIN_BYTES
    raw=_health_from_db(db,KEY,SOURCE_DRAIN_BYTES)
    if raw is None:return None
    value=validate_current_generation(raw);identity=value['identity'];census=value['census']
    require(identity['root']==str(root) and identity['source_inputs']['source_drain']==source_inputs['source_drain']
        and identity['unknown_historical_handlers']==unknown_historical_handlers,
        'source_previous_generation_historical_boundary')
    require(census['state']=='DRAINED' and census['pending_handlers']==0,'source_previous_generation_unresolved')
    _authenticate_prior_provenance(value)
    return dict(identity_sha256=value['identity_sha256'],generation=identity['generation'],
        state='DRAINED',historical_handler_disposition_verified=False)


def _authenticate_prior_provenance(value):
    """Actual root/native-writer provenance; no drain or recovery conclusion."""
    identity=value['identity']
    # The immutable original root seal, not the mutable native body's checksum,
    # authenticates this producer's application/controller/epoch provenance.
    from .normal_boot_record import OPERATIONS,_protected_bytes,_json,validate_envelope
    launch=identity['launch']
    raw_record,_=_protected_bytes(OPERATIONS/launch['request_id']/'normal-launch.json',16384)
    require(hashlib.sha256(raw_record).hexdigest()==launch['record_sha256'],
        'source_previous_generation_root_record')
    record=_json(raw_record)
    require(type(record) is dict and record.get('schema')=='normal-flat-launch-v1'
        and record.get('state')=='SEALED','source_previous_generation_root_record')
    # This synthetic locator is only the exact shape checker for an already
    # authenticated immutable historical record, not a current launch locator.
    locator={key:record[key] for key in ('state','request_id','instance','boot_id','stop_generation',
        'issued_monotonic','not_after_monotonic')}
    locator.update(schema='normal-flat-launch-locator-v1',record_sha256=launch['record_sha256'])
    validate_envelope(locator,record)
    require(_launch_identity(record,launch['record_sha256'])==launch,'source_previous_generation_provenance')
    from .normal_boot import _owner_dead
    source=identity['source']
    require(_owner_dead(launch['boot_id']+':'+str(source['pid'])+':'+source['start_ticks']),
        'source_previous_generation_owner_unverified')


def require_native_generation(value):
    require(type(value) is NativeSourceGeneration and value._pid==os.getpid(),
        'source_generation_capability_required')
    return value


def require_source_entry_generation(value):
    """Lifecycle check immediately before provider/runtime constructors."""
    require_native_generation(value)
    locator,record=_read_record();identity=value._value
    require(locator['state']=='SEALED' and
        _launch_identity(record,locator['record_sha256'])==identity['launch'] and
        os.getppid()==identity['launch']['supervisor']['pid'] and
        _process_start(os.getppid())==identity['launch']['supervisor']['start_ticks'] and
        _process_start(os.getpid())==identity['source']['start_ticks'],'source_entry_instance_changed')
    require(_clock_sha256()==identity['native_clock_sha256'],'source_entry_clock_changed')
    require(record['issued_monotonic']<=time.monotonic()<record['not_after_monotonic'],
        'source_entry_expired')
    return value


def accept_source_launch(fd):
    """Fixed entry only, before any provider/runtime constructors."""
    connected=_channel(fd)
    try:
        locator,record=_read_record()
        require(locator['state']=='SEALED','source_launch_not_sealed')
        connected.settimeout(max(.001,min(15,record['not_after_monotonic']-time.monotonic())))
        peer=struct.unpack('3i',connected.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        value=_receive(connected,deadline=min(time.monotonic()+15,record['not_after_monotonic']))
        _validate_child(value,locator,record,peer)
        current_locator,current_record=_read_record()
        require(current_locator==locator and current_record==record and
            record['issued_monotonic']<=time.monotonic()<record['not_after_monotonic'],
            'source_launch_changed_before_acceptance')
        capability=NativeSourceGeneration(value,_issuer=_ISSUER)
        _send(connected,dict(schema='normal-source-subcap-accepted-v1',identity_sha256=capability.identity_sha256))
        return capability
    finally:connected.close()
