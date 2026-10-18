"""Private Pump owner provenance from the existing sealed Supervisor launch.

This identifies an actual Pump process, not a canonical chain/source generation,
pool universe, financial protection result, allocation grant or readiness proof.
The one-shot anonymous handoff finishes before provider/native constructors.
"""
from copy import deepcopy
import math
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import threading
import time
import uuid

from .normal_boot_record import UNIT, _read_record, digest, hex_value, positive, require, uuid_value
from .normal_source_boot import _channel, _send, _receive, _launch_identity, _process_start, _clock_sha256

_ISSUER=object()
_ISSUED_CONTEXT=None
_CURRENT=None
_ACCEPTED=False
_KEYS=set('schema launch owner owner_generation native_clock_sha256 root issued_monotonic not_after_monotonic'.split())
_SUPPORT_KEYS=_KEYS|{'boot_support'}
_LAUNCH_KEYS=set('instance request_id stop_generation record_sha256 certificate_sha256 application_commit '
    'application_tree epoch_id inception_sha256 boot_id supervisor'.split())


def _packet(value):
    require(type(value) is dict and ((set(value)==_KEYS and value['schema']=='normal-pump-owner-subcap-v1')
        or (set(value)==_SUPPORT_KEYS and value['schema']=='normal-pump-owner-subcap-v2')),
        'pump_owner_fields')
    launch=value['launch'];owner=value['owner']
    require(type(launch) is dict and set(launch)==_LAUNCH_KEYS and type(owner) is dict
        and set(owner)=={'pid','start_ticks','process_instance'} and type(owner['pid']) is int
        and owner['pid']>1 and positive(owner['start_ticks']) and hex_value(owner['process_instance'],32),
        'pump_owner_identity')
    require(hex_value(launch['instance'],32) and type(launch['request_id']) is str
        and re.fullmatch('[a-z0-9-]{1,48}',launch['request_id']) is not None
        and (launch['stop_generation']=='INITIAL' or positive(launch['stop_generation']))
        and all(hex_value(launch[key],64) for key in ('record_sha256','certificate_sha256','inception_sha256'))
        and all(hex_value(launch[key],40) for key in ('application_commit','application_tree'))
        and uuid_value(launch['boot_id']) and type(launch['epoch_id']) is str
        and 0<len(launch['epoch_id'].encode())<=256,'pump_owner_launch')
    parent=launch['supervisor']
    require(type(parent) is dict and set(parent)=={'pid','start_ticks','invocation_id'}
        and type(parent['pid']) is int and parent['pid']>1 and positive(parent['start_ticks'])
        and hex_value(parent['invocation_id'],32),'pump_owner_supervisor')
    require(hex_value(value['owner_generation'],32) and hex_value(value['native_clock_sha256'],64)
        and type(value['root']) is str and Path(value['root']).is_absolute()
        and '..' not in Path(value['root']).parts,'pump_owner_scope')
    require(all(type(value[key]) in (int,float) and math.isfinite(value[key])
        for key in ('issued_monotonic','not_after_monotonic'))
        and 0<=value['issued_monotonic']<value['not_after_monotonic']<=value['issued_monotonic']+60,
        'pump_owner_interval')
    if 'boot_support' in value:
        from .normal_boot_support import validate_support_association
        validate_support_association(value['boot_support'],launch)
    return value


def _environment(value):
    root=Path(value['root']);launch=value['launch'];owner=value['owner']
    require(os.environ.get('MM_STATE_ROOT')==str(root) and os.environ.get('MM_RUNTIME_LANE')=='pump'
        and os.environ.get('MM_LANE_PROCESS_INSTANCE')==owner['process_instance']
        and os.environ.get('MM_PAPER_EPOCH')==launch['epoch_id']
        and Path(os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB',''))==root/'shared/solana-evidence.sqlite'
        and Path(os.environ.get('MM_SOLANA_CANDIDATE_HISTORY_DB',''))==root/'shared/solana-candidate-history.sqlite'
        and Path(os.environ.get('MM_SOLANA_EVIDENCE_BROKER_DB',''))==root/'pump/solana-evidence-broker.sqlite3',
        'pump_owner_environment')


def _validate_instance(value,locator,record):
    owner=record['supervisor']
    require(locator['state']=='SEALED' and record['state']=='SEALED'
        and value['launch']==_launch_identity(record,locator['record_sha256']),
        'pump_owner_launch_changed')
    require(os.getppid()==owner['pid'] and _process_start(owner['pid'])==owner['start_ticks']
        and value['owner']['pid']==os.getpid()
        and _process_start(os.getpid())==value['owner']['start_ticks'],
        'pump_owner_process_changed')
    _environment(value)
    if 'boot_support' in value:
        from .normal_boot_support import validate_support_record
        validate_support_record(value['boot_support'],value['launch'],record['boot_eligibility'])
    require(Path('/proc/sys/kernel/random/boot_id').read_text().strip()==record['boot_id'],
        'pump_owner_boot_changed')
    row=subprocess.run(['/usr/bin/systemctl','show',UNIT,'--property=MainPID,InvocationID,ActiveState'],
        check=True,capture_output=True,text=True,timeout=2)
    require(len(row.stdout.encode())<=2048,'pump_owner_unit_bound')
    fields=dict(line.split('=',1) for line in row.stdout.splitlines() if '=' in line)
    require(fields.get('MainPID')==str(owner['pid']) and fields.get('InvocationID')==owner['invocation_id']
        and fields.get('ActiveState') in ('active','activating'),'pump_owner_unit_changed')
    from .normal_boot import _source_identity
    require(_source_identity()==(record['application_commit'],record['application_tree']),
        'pump_owner_source_changed')
    require(_clock_sha256()==value['native_clock_sha256'],'pump_owner_clock_changed')


class PumpOwnerLaunch:
    """The actual Supervisor may issue one Pump owner under this boot context."""
    def __init__(self,context):
        global _ISSUED_CONTEXT
        from .normal_boot import require_boot_context
        self.context=require_boot_context(context)
        require(_ISSUED_CONTEXT is None,'pump_owner_already_issued')
        self.owner=(os.getpid(),threading.get_ident());self.process=None;self.closed=False
        self.parent,self.child=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
        self.parent.set_inheritable(False);self.child.set_inheritable(False)
        self.identity=None;_ISSUED_CONTEXT=context

    @property
    def child_fd(self):
        require(not self.closed and self.process is None,'pump_owner_channel_state')
        return self.child.fileno()

    def bind(self,process,*,deadline,process_instance):
        try:return self._bind(process,deadline=deadline,process_instance=process_instance)
        finally:self.close()

    def _bind(self,process,*,deadline,process_instance):
        require(self.owner==(os.getpid(),threading.get_ident()) and not self.closed
            and self.process is None and type(process) is subprocess.Popen,'pump_owner_issuer')
        require(hex_value(process_instance,32),'pump_owner_process_instance')
        now=time.monotonic()
        require(type(deadline) in (int,float) and math.isfinite(deadline)
            and now<deadline<=now+15,'pump_owner_handoff_deadline')
        record=self.context._launch.require_current();self.context.require_current()
        require(record['issued_monotonic']<=time.monotonic()<min(deadline,record['not_after_monotonic']),
            'pump_owner_launch_expired')
        self.process=process
        require(process.poll() is None and os.getsid(process.pid)==process.pid,'pump_owner_child_lifetime')
        value=dict(schema='normal-pump-owner-subcap-v2',
            launch=_launch_identity(record,self.context._launch._locator['record_sha256']),
            owner=dict(pid=process.pid,start_ticks=_process_start(process.pid),process_instance=process_instance),
            owner_generation=uuid.uuid4().hex,native_clock_sha256=_clock_sha256(),root=str(self.context._root),
            issued_monotonic=time.monotonic(),not_after_monotonic=record['not_after_monotonic'],
            boot_support=self.context.boot_support().value())
        _packet(value)
        self.child.close()
        self.parent.settimeout(max(.001,min(deadline,record['not_after_monotonic'])-time.monotonic()))
        _send(self.parent,value)
        ack=_receive(self.parent,deadline=min(deadline,record['not_after_monotonic']))
        require(ack==dict(schema='normal-pump-owner-accepted-v1',identity_sha256=digest(value)),
            'pump_owner_ack')
        require(process.poll() is None and _process_start(process.pid)==value['owner']['start_ticks']
            and time.monotonic()<min(deadline,record['not_after_monotonic']),
            'pump_owner_handoff_expired')
        self.identity=deepcopy(value);return deepcopy(value)

    def close(self):
        self.closed=True;self.parent.close();self.child.close()


class NativePumpOwnerContext:
    """Process-private owner identity; no serialized authority or source proof."""
    __slots__=('_value','_identity_sha256','_pid','_owner_thread','_closed')
    def __init__(self,value,*,_issuer=None):
        require(_issuer is _ISSUER,'pump_owner_private_issuer')
        self._value=deepcopy(_packet(value));self._identity_sha256=digest(self._value)
        self._pid=os.getpid();self._owner_thread=threading.get_ident();self._closed=False

    @property
    def identity_sha256(self):return self._identity_sha256

    @property
    def owner_generation(self):return self._value['owner_generation']

    def identity(self):return deepcopy(self._value)

    def boot_support(self):
        from .normal_boot_support import _for_child
        return _for_child(self)

    def require_current(self,*,initial=False):return require_pump_owner_context(self,initial=initial)

    def __reduce__(self):raise TypeError('native_pump_owner_context_is_process_private')

    def close(self):
        global _CURRENT
        require(self._pid==os.getpid() and self._owner_thread==threading.get_ident(),
            'pump_owner_close_owner')
        self._closed=True
        if _CURRENT is self:_CURRENT=None


def require_pump_owner_context(value,*,initial=False):
    require(type(value) is NativePumpOwnerContext and value is _CURRENT
        and not value._closed and value._pid==os.getpid(),'pump_owner_context_required')
    require(type(initial) is bool,'pump_owner_check_kind')
    if initial:
        require(value._owner_thread==threading.get_ident(),'pump_owner_entry_thread')
        locator,record=_read_record();_validate_instance(value._value,locator,record)
        # These checks are after all fallible Git/unit/clock work. This is the
        # original boot acquisition window, not a renewable runtime lifetime.
        after_locator,after_record=_read_record()
        require(after_locator==locator and after_record==record,'pump_owner_entry_replaced')
        require(record['issued_monotonic']<=time.monotonic()<record['not_after_monotonic'],
            'pump_owner_entry_expired')
    return value


def require_pump_entry_context(value):return require_pump_owner_context(value,initial=True)


def current_pump_owner_context():
    return None if _CURRENT is None else require_pump_owner_context(_CURRENT)


def accept_pump_owner_launch(fd):
    global _CURRENT,_ACCEPTED
    require(not _ACCEPTED and _CURRENT is None,'pump_owner_already_accepted')
    connected=_channel(fd)
    try:
        locator,record=_read_record()
        require(locator['state']=='SEALED','pump_owner_not_sealed')
        deadline=min(time.monotonic()+15,record['not_after_monotonic'])
        peer=struct.unpack('3i',connected.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        parent=record['supervisor']
        require(peer==(parent['pid'],os.getuid(),os.getgid()),'pump_owner_parent_peer')
        value=_packet(_receive(connected,deadline=deadline))
        require(value['not_after_monotonic']==record['not_after_monotonic']
            and record['issued_monotonic']<=value['issued_monotonic']<value['not_after_monotonic'],
            'pump_owner_issued_interval')
        _validate_instance(value,locator,record)
        current_locator,current_record=_read_record()
        require(current_locator==locator and current_record==record
            and record['issued_monotonic']<=time.monotonic()<min(deadline,record['not_after_monotonic']),
            'pump_owner_acceptance_expired_or_replaced')
        capability=NativePumpOwnerContext(value,_issuer=_ISSUER)
        connected.settimeout(max(.001,min(deadline,record['not_after_monotonic'])-time.monotonic()))
        _send(connected,dict(schema='normal-pump-owner-accepted-v1',identity_sha256=capability.identity_sha256))
        require(record['issued_monotonic']<=time.monotonic()<min(deadline,record['not_after_monotonic']),
            'pump_owner_acceptance_expired_after_ack')
        _CURRENT=capability;_ACCEPTED=True
        return capability
    finally:connected.close()
