"""Fixed root-issued launch data, consumed before any native runtime writer.

Root filesystem ownership plus the real systemd/kernel instance authenticates
acquisition. A JSON digest authenticates no authority by itself. No caller path,
environment readiness flag, alternate unit or signing/privileged route exists.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import threading
import time

OPERATIONS=Path('/var/lib/meme-machine-operations')
UNIT='meme-machine-paper.service'
WORKERS=tuple('scripts/'+name+'.py' for name in
    ('ops_worker','ops_preflight','ops_recovery','ops_lifecycle'))
REGIMES=('pons_current','pons_survivor','pump_current','pump_survivor')
OBLIGATIONS=('reservations','commitments','obligations','pending_deliveries','pending_backing',
    'runtime_pending','runtime_inbox','positions_open','legacy_native_pending')
SOURCE_INPUTS={'source_drain':128*1024,'source_handler_recovery':48*1024,
    'source_control_recovery':128*1024,'source_drain_observation':128*1024}
LOCATOR_KEYS=set('schema state request_id instance boot_id stop_generation record_sha256 '
    'issued_monotonic not_after_monotonic'.split())
RECORD_KEYS=set('schema state request_id instance boot_id stop_generation issued_monotonic '
    'not_after_monotonic application_commit application_tree administration_commit worker_hashes '
    'boot_eligibility supervisor funding_authority safe_for_normal historical_handler_disposition_verified'.split())
CERTIFICATE_KEYS=set('schema state request_action request_id application_commit application_tree '
    'administration_commit administration_tree worker_hashes worker_identity_sha256 configuration_sha256 '
    'continuous_profile_sha256 policy_sha256 epoch_id inception_sha256 journal_hash projection_hash '
    'combined_sequence physical_generation_sha256 native_input_sha256 four_regimes obligations '
    'source_inputs unknown_historical_handlers native_books_verified native_databases_inspected '
    'held_existing_fences boot_id issued_monotonic not_after_monotonic funding_authority safe_for_normal '
    'current_native_protection_verified historical_handler_disposition_verified historical_drain_reclassified '
    'canonical_cohort_complete authoritative_writes provider_requests certificate_sha256'.split())
_ISSUER=object()


class NormalBootUnavailable(RuntimeError):pass


def require(condition,code):
    if not condition:raise NormalBootUnavailable('normal_boot_'+code)


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def hex_value(value,size):return type(value) is str and re.fullmatch('[0-9a-f]{'+str(size)+'}',value) is not None
def positive(value):return type(value) is str and re.fullmatch('[1-9][0-9]*',value) is not None
def uuid_value(value):return type(value) is str and re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',value) is not None


def _json(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'duplicate_json_key');result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=unique,
        parse_constant=lambda value:(_ for _ in ()).throw(NormalBootUnavailable('normal_boot_nonfinite_json')))


def _times(value):
    issued,expiry=value['issued_monotonic'],value['not_after_monotonic']
    require(all(type(x) in (int,float) and math.isfinite(x) for x in (issued,expiry))
        and 0<=issued<expiry<=issued+60,'acceptance_interval')
    return issued,expiry


def validate_certificate(value):
    require(type(value) is dict and set(value)==CERTIFICATE_KEYS,'certificate_fields')
    require(value['schema']=='stopped-flat-boot-eligibility-v1' and
        value['state']=='ELIGIBLE_FUNDING_CLOSED_ONLY' and value['request_action'] in ('preflight','start'),
        'certificate_kind')
    require(type(value['request_id']) is str and re.fullmatch('[a-z0-9-]{1,48}',value['request_id']),
        'request_identity')
    for key in ('application_commit','application_tree','administration_commit','administration_tree'):
        require(hex_value(value[key],40),'source_identity')
    for key in CERTIFICATE_KEYS:
        if key.endswith('_sha256') or key in ('inception_sha256','journal_hash','projection_hash'):
            require(hex_value(value[key],64),'certificate_hash_shape')
    workers=value['worker_hashes']
    require(type(workers) is dict and set(workers)==set(WORKERS)
        and all(hex_value(x,64) for x in workers.values()),'worker_identity')
    require(value['four_regimes']==list(REGIMES),'all_four_regimes')
    require(type(value['obligations']) is dict and set(value['obligations'])==set(OBLIGATIONS)
        and all(type(x) is int and x==0 for x in value['obligations'].values()),'flat_obligations')
    require(type(value['epoch_id']) is str and 0<len(value['epoch_id'].encode())<=256,'epoch_shape')
    require(type(value['combined_sequence']) is int and value['combined_sequence']>0,'head_sequence')
    require(type(value['unknown_historical_handlers']) is int and value['unknown_historical_handlers']>=0,
        'historical_count')
    require(type(value['native_books_verified']) is int and value['native_books_verified']>=6
        and type(value['native_databases_inspected']) is int
        and value['native_books_verified']<=value['native_databases_inspected']<=512
        and type(value['held_existing_fences']) is int and 4<=value['held_existing_fences']<=5,'native_population')
    require(type(value['source_inputs']) is dict and set(value['source_inputs'])==set(SOURCE_INPUTS),
        'source_input_population')
    for key,row in value['source_inputs'].items():
        require(row is None or type(row) is dict and set(row)=={'bytes','sha256'}
            and type(row['bytes']) is int and 0<row['bytes']<=SOURCE_INPUTS[key]
            and hex_value(row['sha256'],64),'source_input_shape')
    require(value['source_inputs']['source_drain'] is not None,'source_drain_missing')
    require(uuid_value(value['boot_id']),'boot_identity');_times(value)
    for key in ('funding_authority','safe_for_normal','current_native_protection_verified',
            'historical_handler_disposition_verified','historical_drain_reclassified','canonical_cohort_complete'):
        require(value[key] is False,'certificate_authority')
    require(type(value['authoritative_writes']) is int and value['authoritative_writes']==0
        and type(value['provider_requests']) is int and value['provider_requests']==0,'certificate_effects')
    require(len(json.dumps(value,sort_keys=True,allow_nan=False).encode())<=8192,'certificate_bound')
    require(digest({k:v for k,v in value.items() if k!='certificate_sha256'})==value['certificate_sha256'],
        'certificate_checksum')
    return value


def validate_envelope(locator,record):
    require(type(locator) is dict and set(locator)==LOCATOR_KEYS and
        locator['schema']=='normal-flat-launch-locator-v1','locator_fields')
    require(locator['state'] in ('PENDING','SEALED','REVOKED'),'locator_state')
    require(type(locator['request_id']) is str and re.fullmatch('[a-z0-9-]{1,48}',locator['request_id'])
        and hex_value(locator['instance'],32) and uuid_value(locator['boot_id']),'locator_identity')
    require(locator['stop_generation']=='INITIAL' or positive(locator['stop_generation']),'stop_generation')
    require(hex_value(locator['record_sha256'],64) if locator['state']!='REVOKED'
        else locator['record_sha256'] is None,'locator_hash')
    _times(locator);require(locator['state']!='REVOKED','revoked')
    require(type(record) is dict and set(record)==RECORD_KEYS and
        record['schema']=='normal-flat-launch-v1','record_fields')
    for key in ('state','request_id','instance','boot_id','stop_generation','issued_monotonic','not_after_monotonic'):
        require(record[key]==locator[key],'record_locator_crossed')
    certificate=validate_certificate(record['boot_eligibility'])
    for key in ('request_id','application_commit','application_tree','administration_commit','worker_hashes',
            'boot_id','issued_monotonic','not_after_monotonic'):
        require(record[key]==certificate[key],'record_certificate_crossed')
    require(all(record[key] is False for key in ('funding_authority','safe_for_normal',
        'historical_handler_disposition_verified')),'record_authority')
    if record['state']=='PENDING':require(record['supervisor'] is None,'pending_instance')
    else:
        owner=record['supervisor']
        require(type(owner) is dict and set(owner)=={'pid','start_ticks','invocation_id'}
            and type(owner['pid']) is int and owner['pid']>1 and positive(owner['start_ticks'])
            and hex_value(owner['invocation_id'],32),'sealed_instance')
    return certificate


def file_identity(info):
    return tuple(getattr(info,key) for key in
        ('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))


def _protected_bytes(path,maximum):
    group=pwd.getpwnam('meme-machine').pw_gid
    for parent in path.parents:
        info=parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'root_directory')
    fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_gid==group
            and stat.S_IMODE(before.st_mode)==0o640 and before.st_nlink==1 and 0<before.st_size<=maximum,
            'root_record_file')
        raw=os.read(fd,maximum+1)
        require(len(raw)==before.st_size and not os.read(fd,1),'record_bound')
        identity=file_identity(before)
        require(file_identity(os.fstat(fd))==identity==file_identity(path.lstat()),'record_changed')
        return raw,identity
    finally:os.close(fd)


def _read_record():
    raw,identity=_protected_bytes(OPERATIONS/'normal-launch.json',2048)
    locator=_json(raw)
    require(type(locator) is dict and type(locator.get('request_id')) is str
        and re.fullmatch('[a-z0-9-]{1,48}',locator['request_id']),'request_identity')
    require(locator.get('state') in ('PENDING','SEALED','REVOKED'),'locator_state')
    require(locator['state']!='REVOKED','revoked')
    filename='normal-launch.pending.json' if locator['state']=='PENDING' else 'normal-launch.json'
    body,_=_protected_bytes(OPERATIONS/locator['request_id']/filename,16384)
    require(hashlib.sha256(body).hexdigest()==locator.get('record_sha256'),'record_hash')
    record=_json(body);validate_envelope(locator,record)
    after,after_identity=_protected_bytes(OPERATIONS/'normal-launch.json',2048)
    require(raw==after and identity==after_identity,'locator_changed')
    return locator,record


def current_kernel_instance():
    pid=os.getpid();boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    start=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]
    require(uuid_value(boot) and positive(start),'kernel_identity')
    row=subprocess.run(['/usr/bin/systemctl','show',UNIT,
        '--property=MainPID,InvocationID,ActiveState'],check=True,capture_output=True,text=True,timeout=2)
    require(len(row.stdout.encode())<=2048,'unit_bound')
    values=dict(line.split('=',1) for line in row.stdout.splitlines() if '=' in line)
    require(values.get('ActiveState') in ('activating','active') and values.get('MainPID')==str(pid)
        and hex_value(values.get('InvocationID'),32),'unit_identity')
    return dict(pid=pid,start_ticks=start,invocation_id=values['InvocationID']),boot


class AuthenticatedNormalLaunch:
    __slots__=('_owner','_locator','_record','_consumed')
    def __init__(self,locator,record,*,_issuer=None):
        require(_issuer is _ISSUER,'launch_issuer')
        self._owner=(os.getpid(),threading.get_ident());self._locator=deepcopy(locator)
        self._record=deepcopy(record);self._consumed=False

    def require_current(self,*,initial=False):
        require(self._owner==(os.getpid(),threading.get_ident()),'launch_owner')
        locator,record=_read_record()
        require(locator==self._locator and record==self._record and locator['state']=='SEALED','launch_replaced')
        instance,boot=current_kernel_instance()
        require(instance==record['supervisor'] and boot==record['boot_id'],'launch_instance')
        if initial:
            require(not self._consumed and locator['issued_monotonic']<=time.monotonic()<locator['not_after_monotonic'],
                'launch_expired_or_consumed')
        return deepcopy(record)


def await_normal_launch(*,cancelled):
    require(callable(cancelled),'cancel_callback')
    began=time.monotonic()
    while True:
        require(cancelled() is False,'cancelled')
        locator,record=_read_record();now=time.monotonic()
        require(locator['issued_monotonic']<=now<min(began+60,locator['not_after_monotonic']),'launch_expired')
        if locator['state']=='SEALED':
            value=AuthenticatedNormalLaunch(locator,record,_issuer=_ISSUER)
            value.require_current(initial=True);return value
        time.sleep(min(.05,max(0,locator['not_after_monotonic']-now)))
