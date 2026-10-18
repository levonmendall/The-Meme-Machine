"""Private pre-write cuts, not an inherited population or completion proof.

The original sealed, exclusive pre-write replay supplies the association and
held inodes. Indexed metadata reads add fixed cuts only. A consumer must still
census every required inherited key through the fixed-cut EOF and join the
original native retention, publication and protection results.
"""
from copy import deepcopy
import math
import os
import time

from .normal_boot_record import canonical,digest,hex_value,require

SOURCE_PATH='shared/solana-evidence.sqlite'
PROGRAMS=('program:meteora','program:pump','program:pumpswap')
SOURCE_SCHEMA=('candidate_outbox','candidate_outbox_scope')
MAX_BYTES=6144
_ISSUER=object()
_ASSOCIATION=set('instance record_sha256 certificate_sha256 application_commit application_tree '
    'epoch_id inception_sha256 native_input_sha256 physical_generation_sha256'.split())
_DATABASE={'relative_path','device','inode','schema_sha256'}
_WORK={
    'source':(SOURCE_PATH,('candidate_history_outbox','candidate_pending_proofs')),
    'candidate_history':('shared/solana-candidate-history.sqlite',('work','work_observations','state_checkpoints')),
    'pump_history':('pump/pump-survivor/history.sqlite',('candidates','events','points')),
    'pons_history':('pons/pons-selective-continuation-v1-cohort/pons-survivor/history.sqlite',
        ('candidates','events','points')),
    'pons_plane':('shared/robinhood-evidence.candidates.sqlite',
        ('candidates','pons_current_watch','result_consumption','runtime'))}


def source_schema_sha256(db):
    """Fixed table/index definition only; new unrelated tables do not invalidate it."""
    rows=db.execute("SELECT type,name,length(CAST(sql AS BLOB)),CASE WHEN "
        "length(CAST(sql AS BLOB))<=8192 THEN sql END FROM sqlite_master "
        "WHERE name IN ('candidate_outbox','candidate_outbox_scope') ORDER BY name").fetchall()
    require(len(rows)==2 and [(row[0],row[1]) for row in rows]==
        [('table','candidate_outbox'),('index','candidate_outbox_scope')], 'support_source_schema')
    require(all(type(row[2]) is int and 0<row[2]<=8192 and type(row[3]) is str
        and len(row[3].encode())==row[2] for row in rows),'support_source_schema_bound')
    return digest([[kind,name,sql] for kind,name,_length,sql in rows])


def _number(value):return type(value) is int and 0<=value<2**63


def validate_support_value(value):
    """Pure bounded shape validation, never an issuer or census attestation."""
    require(type(value) is dict and set(value)=={'schema','association','visibility_wall','database',
        'programs','retained_work'} and value['schema']=='normal-native-boot-support-v1',
        'support_fields')
    association=value['association'];database=value['database']
    require(type(association) is dict and set(association)==_ASSOCIATION
        and hex_value(association['instance'],32)
        and all(hex_value(association[key],40) for key in ('application_commit','application_tree'))
        and all(hex_value(association[key],64) for key in ('record_sha256','certificate_sha256',
            'inception_sha256','native_input_sha256','physical_generation_sha256'))
        and type(association['epoch_id']) is str and 0<len(association['epoch_id'].encode())<=256,
        'support_association')
    require(type(value['visibility_wall']) is float and math.isfinite(value['visibility_wall'])
        and value['visibility_wall']>=0,'support_visibility')
    require(type(database) is dict and set(database)==_DATABASE
        and database['relative_path']==SOURCE_PATH and _number(database['device'])
        and _number(database['inode']) and database['inode']>0
        and hex_value(database['schema_sha256'],64),'support_database')
    require(type(value['programs']) is dict and set(value['programs'])==set(PROGRAMS)
        and all(cut is None or _number(cut) for cut in value['programs'].values()),'support_programs')
    work=value['retained_work']
    require(type(work) is dict and set(work)==set(_WORK),'support_work_roles')
    for role,row in work.items():
        require(type(row) is dict and set(row)=={'relative_path','device','inode','rowid_heads'}
            and row['relative_path']==_WORK[role][0]
            and _number(row['device']) and _number(row['inode']) and row['inode']>0
            and type(row['rowid_heads']) is dict and set(row['rowid_heads'])==set(_WORK[role][1])
            and all((head is None or type(head) is int and -(2**63)<=head<2**63)
                for name,head in row['rowid_heads'].items()),'support_work_heads')
    require(len(canonical(value))<=MAX_BYTES,'support_bound')
    return deepcopy(value)


def validate_support_association(value,launch):
    """Bind an already-authenticated IPC payload to that exact root launch."""
    value=validate_support_value(value)
    require(all(value['association'][key]==launch[key] for key in
        ('instance','record_sha256','certificate_sha256','application_commit','application_tree',
         'epoch_id','inception_sha256')),'support_launch_changed')
    return value


def _descriptor(reads,relative):
    path=reads.root/relative
    require(path in reads.databases and path in reads.files,'support_database_missing')
    _fd,identity,sqlite=reads.files[path]
    require(sqlite and reads.databases[path].in_transaction,'support_snapshot_required')
    return dict(relative_path=relative,device=identity[0],inode=identity[1])


def _capture(reads,record,record_sha256):
    """Called only within consume's verified scope, before its final fence check.

    Rowid heads describe mutable native work stores; they do not identify all
    queued jobs, prove absence or support append-only classification there.
    """
    from .normal_boot import _OwnedPrewriteReads
    require(type(reads) is _OwnedPrewriteReads,'support_owned_reads_required')
    reads.check()
    certificate=record['boot_eligibility']
    association={key:record[key] for key in ('instance','application_commit','application_tree')}
    association.update(record_sha256=record_sha256,**{key:certificate[key] for key in
        ('certificate_sha256','epoch_id','inception_sha256','native_input_sha256','physical_generation_sha256')})
    source=reads.databases[reads.root/SOURCE_PATH]
    database=_descriptor(reads,SOURCE_PATH)
    database['schema_sha256']=source_schema_sha256(source)
    programs={}
    for scope in PROGRAMS:
        reads.check()
        row=source.execute('SELECT sequence FROM candidate_outbox INDEXED BY candidate_outbox_scope '
            'WHERE scope=? ORDER BY sequence DESC LIMIT 1',(scope,)).fetchone()
        programs[scope]=None if row is None else row[0]
    work={}
    for role,(relative,tables) in _WORK.items():
        reads.check();row=_descriptor(reads,relative);db=reads.databases[reads.root/relative]
        row['rowid_heads']={}
        for table in tables:
            # All names are source constants. Reverse rowid seeks visit at most
            # one row, without decoding bodies or counting a retained table.
            result=db.execute('SELECT rowid FROM '+table+' ORDER BY rowid DESC LIMIT 1').fetchone()
            row['rowid_heads'][table]=None if result is None else result[0]
        work[role]=row
    value=dict(schema='normal-native-boot-support-v1',association=association,
        visibility_wall=float(time.time()),database=database,programs=programs,retained_work=work)
    reads.check()
    return validate_support_value(value)


class NativeBootSupportBoundary:
    """Private immutable association, issued only under the actual live owner."""
    __slots__=('_value','_identity_sha256','_pid','_require_owner')
    def __init__(self,value,require_owner,*,_issuer=None):
        require(_issuer is _ISSUER and callable(require_owner),'support_private_issuer')
        object.__setattr__(self,'_value',validate_support_value(value))
        object.__setattr__(self,'_identity_sha256',digest(self._value))
        object.__setattr__(self,'_pid',os.getpid())
        object.__setattr__(self,'_require_owner',require_owner)

    def __setattr__(self,*args):raise AttributeError('immutable_native_boot_support')
    def __reduce__(self):raise TypeError('native_boot_support_is_process_private')

    def _check(self):
        require(self._pid==os.getpid(),'support_process')
        self._require_owner()

    @property
    def identity_sha256(self):self._check();return self._identity_sha256

    def value(self):self._check();return deepcopy(self._value)

    def outbox_support(self,scope):
        self._check();require(scope in PROGRAMS,'support_program')
        return dict(schema='normal-native-outbox-support-v1',support_identity_sha256=self._identity_sha256,
            association=deepcopy(self._value['association']),visibility_wall=self._value['visibility_wall'],
            database=deepcopy(self._value['database']),upper_sequence=self._value['programs'][scope])


def _for_boot(context):
    from .normal_boot import require_boot_context
    require_boot_context(context)
    require(context._support is not None,'support_not_captured')
    return NativeBootSupportBoundary(context._support,
        lambda:require_boot_context(context),_issuer=_ISSUER)


def _for_child(owner):
    from .normal_pump_boot import NativePumpOwnerContext,require_pump_owner_context
    from .normal_source_boot import NativeSourceGeneration,require_native_generation
    if type(owner) is NativePumpOwnerContext:check=lambda:require_pump_owner_context(owner)
    elif type(owner) is NativeSourceGeneration:check=lambda:require_native_generation(owner)
    else:require(False,'support_child_owner_type')
    check();identity=owner.identity()
    require('boot_support' in identity,'support_not_issued')
    value=validate_support_association(identity['boot_support'],identity['launch'])
    return NativeBootSupportBoundary(value,check,_issuer=_ISSUER)
