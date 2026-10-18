"""Fixed full-main synthetic kernel validation, without PAPER/market authority.

The public route always uses the reviewed Landlock launcher. Its source-owned
offline parent replaces physical providers, never native consumers, decoding,
SQLite publication, FULL/ACK or shutdown. Missing coverage remains BLOCKED.
"""
import asyncio
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import socket
import sqlite3
import stat
import time
import zlib

from .isolated_native_landlock_launcher import launch_native,PROFILE
from .isolated_native_image import NativeImageApproval
from .isolated_native_kernel_parent import SyntheticParent,sizing_receipt,encoded,PROVENANCE
from .parent_channel import serve_connected

_REAL_LAUNCH=launch_native
WINDOW_SECONDS=40
MAX_RESULT=65536
_FINANCIAL_TABLES=frozenset(('genesis','positions','journal','sleeve_genesis','sleeve_positions',
    'sleeve_journal','capital_genesis','capital_positions','capital_journal',
    'portfolio_genesis','portfolio_events','shared_capital_events','shared_capital_projection'))
_OUTPUT_FAILURE_CODES=frozenset((
    'kernel_validation_ack_binding','kernel_validation_ack_bound',
    'kernel_validation_canonical_lineage','kernel_validation_canonical_reference',
    'kernel_validation_canonical_reference_binding','kernel_validation_canonical_source',
    'kernel_validation_consumer_ack_hash','kernel_validation_database_count',
    'kernel_validation_database_inode','kernel_validation_database_sidecar',
    'kernel_validation_endpoint_identity','kernel_validation_file_bound',
    'kernel_validation_original_ack_identity','kernel_validation_output_root',
    'kernel_validation_pons_checkpoint','kernel_validation_reference_candidate',
    'kernel_validation_reference_event','kernel_validation_source_ack_hash',
    'kernel_validation_source_ack_shape'))


def _output_failure_code(error):
    # Exact local guard literals only. No arbitrary ValueError text or paths.
    if (type(error) is ValueError and len(error.args)==1 and type(error.args[0]) is str
            and len(error.args[0])<=100 and error.args[0] in _OUTPUT_FAILURE_CODES):
        return error.args[0]
    return None



def _json_file(path,maximum=MAX_RESULT):
    path=Path(path);info=path.lstat()
    if (path.resolve(strict=True)!=path.absolute() or not stat.S_ISREG(info.st_mode)
            or info.st_nlink!=1 or info.st_size>maximum):raise ValueError('kernel_validation_file_bound')
    return json.loads(path.read_bytes())


def _readonly(path):
    path=Path(path);info=path.lstat()
    if (path.resolve(strict=True)!=path.absolute() or not stat.S_ISREG(info.st_mode)
            or info.st_nlink!=1 or info.st_uid!=os.geteuid()):raise ValueError('kernel_validation_database_inode')
    # SQLite opens these names itself, including SHM even on a read-only DB.
    # The stopped child must not redirect those opens outside disposable state.
    # Keep WAL visible; immutable=1 would conceal valid committed WAL content.
    for suffix in ('-wal','-shm','-journal'):
        sidecar=path.with_name(path.name+suffix)
        try:info=sidecar.lstat()
        except FileNotFoundError:continue
        if (sidecar.resolve(strict=True)!=sidecar.absolute() or not stat.S_ISREG(info.st_mode)
                or info.st_nlink!=1 or info.st_uid!=os.geteuid()):
            raise ValueError('kernel_validation_database_sidecar')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=1,isolation_level=None)
    db.execute('PRAGMA query_only=ON')
    return db


def _hash(value):
    return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def _cold_canonical(db,source,identity,archive,cache):
    """Read the original scoped archive after join, never a reference alone.

    The native writer publishes this content-addressed file before clearing its
    hot pointer. Preserve its 32 MiB decoded limit and complete compressed hash;
    additionally contain this parent read to the disposable source's own file.
    One archive may be cached, with fresh descriptor/path fences on every use.
    """
    def refuse():raise ValueError('kernel_validation_canonical_source')
    def fingerprint(info):
        return tuple(getattr(info,key) for key in
            ('st_dev','st_ino','st_mode','st_uid','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))
    if not _hash(archive):refuse()
    manifest=db.execute('SELECT path,hash,records,hot_bytes,cold_bytes FROM scoped_cold_manifests WHERE id=?',
        (archive,)).fetchone()
    directory=Path(source).with_suffix('.scoped-cold');path=directory/(archive+'.zlib')
    if (manifest is None or manifest[:2]!=(str(path),archive)
            or type(manifest[2]) is not int or not 0<manifest[2]<=1000
            or type(manifest[3]) is not int or not 0<manifest[3]<=16*1024*1024
            or type(manifest[4]) is not int or not 0<manifest[4]<=33*1024*1024):refuse()
    before=directory.lstat()
    if (directory.resolve(strict=True)!=directory.absolute() or not stat.S_ISDIR(before.st_mode)
            or before.st_uid!=os.geteuid()):refuse()
    parent=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        if fingerprint(os.fstat(parent))!=fingerprint(before):refuse()
        descriptor=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        try:
            info=os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid()
                    or info.st_nlink!=1 or info.st_size!=manifest[4]):refuse()
            key=(archive,manifest,fingerprint(info));entry=cache.get('entry')
            if entry is not None and entry[0]==key:records=entry[1]
            else:
                cache.clear();parts=[];remaining=info.st_size
                while remaining:
                    part=os.read(descriptor,min(65536,remaining))
                    if not part:refuse()
                    parts.append(part);remaining-=len(part)
                if os.read(descriptor,1):refuse()
                packed=b''.join(parts)
                if hashlib.sha256(packed).hexdigest()!=manifest[1]:refuse()
                decoder=zlib.decompressobj();raw=decoder.decompress(packed,32*1024*1024+1)
                if len(raw)>32*1024*1024 or not decoder.eof or decoder.unused_data:refuse()
                records=json.loads(raw)
                if type(records) is not list or len(records)!=manifest[2]:refuse()
            if (fingerprint(os.fstat(descriptor))!=fingerprint(info)
                    or fingerprint(os.stat(path.name,dir_fd=parent,follow_symlinks=False))!=fingerprint(info)
                    or fingerprint(os.fstat(parent))!=fingerprint(before)
                    or fingerprint(directory.lstat())!=fingerprint(before)):refuse()
        finally:os.close(descriptor)
    finally:os.close(parent)
    # Retain the original first matching sequence lookup, not a dict that could
    # silently select a later duplicate. Its complete body is verified below.
    item=next((item for item in records if item['record']['identity']==identity),None)
    if type(item) is not dict or set(item)!={'record','available'}:refuse()
    cache['entry']=(key,records)
    return item


def _canonical_acks(db,consumer,source,*,endpoint_identity):
    """Bind counted ACKs to their exact native record, lineage and reference."""
    from meme_machine.runtime.journal import canonical,digest
    from meme_machine.solana_evidence_plane import decode_body
    if not _hash(endpoint_identity):raise ValueError('kernel_validation_endpoint_identity')
    rows=db.execute("SELECT id,family,address,body,hash FROM candidate_history_outbox WHERE kind='canonical' AND consumed IS NOT NULL ORDER BY id LIMIT 1025").fetchall()
    if len(rows)>1024:raise ValueError('kernel_validation_ack_bound')
    archives={}
    for identity,family,address,raw,checksum in rows:
        if (not _hash(identity) or family not in ('pump','pumpswap') or type(address) is not str
                or not 0<len(address)<=128 or type(raw) is not str or len(raw.encode())>4096
                or not _hash(checksum) or hashlib.sha256(raw.encode()).hexdigest()!=checksum):
            raise ValueError('kernel_validation_source_ack_hash')
        compact=json.loads(raw)
        if (type(compact) is not dict or set(compact)!={'source_hash','record','available'}
                or not _hash(compact['source_hash']) or type(compact['record']) is not dict
                or set(compact['record'])!={'identity','slot'}
                or type(compact['record']['identity']) is not str or not 0<len(compact['record']['identity'])<=256
                or type(compact['record']['slot']) is not int or compact['record']['slot']<0
                or type(compact['available']) not in (int,float) or not math.isfinite(compact['available'])
                or compact['available']<=0):raise ValueError('kernel_validation_source_ack_shape')
        record_id=compact['record']['identity'];slot=compact['record']['slot']
        receipt=consumer.execute('SELECT family,address,kind,body,hash FROM source_receipts WHERE id=?',(identity,)).fetchone()
        if (receipt is None or receipt[:3]!=(family,address,'canonical') or type(receipt[3]) is not str
                or not _hash(receipt[4]) or hashlib.sha256(receipt[3].encode()).hexdigest()!=receipt[4]):
            raise ValueError('kernel_validation_consumer_ack_hash')
        expected=dict(source_hash=compact['source_hash'],scope='candidate:'+family+':'+address,
            canonical_identity=record_id)
        if json.loads(receipt[3])!=expected:raise ValueError('kernel_validation_ack_binding')
        stored=db.execute('SELECT body,hash,slot,scope,archive,first_seen FROM canonical_evidence WHERE identity=?',(record_id,)).fetchone()
        if (stored is None or not _hash(stored[1]) or stored[2]!=slot
                or stored[3]!='program:'+family):raise ValueError('kernel_validation_canonical_source')
        if stored[0] is None:
            item=_cold_canonical(db,source,record_id,stored[4],archives)
            if item['available']!=stored[5]:raise ValueError('kernel_validation_canonical_source')
            record=item['record']
        else:record=decode_body(stored[0],db)
        if (type(record) is not dict or record.get('identity')!=record_id or record.get('slot')!=slot
                or record.get('scope')!='program:'+family or digest(record)!=stored[1]
                or stored[5]!=compact['available']):
            raise ValueError('kernel_validation_canonical_source')
        original=dict(record=record,available=compact['available'])
        if digest(original)!=compact['source_hash'] or digest([family,address,'canonical',original])!=identity:
            raise ValueError('kernel_validation_original_ack_identity')
        lineage=db.execute('''SELECT source FROM lineage WHERE identity=? AND endpoint=?
            UNION ALL SELECT source FROM rolling_event_lineage WHERE identity=? AND endpoint=?''',
            (record_id,endpoint_identity,record_id,endpoint_identity)).fetchall()
        if not lineage or any(row[0] not in ('alchemy_finalized_stream','alchemy_finalized_repair') for row in lineage):
            raise ValueError('kernel_validation_canonical_lineage')
        event=record.get('payload',{}).get('event')
        if type(event) is not dict:raise ValueError('kernel_validation_reference_event')
        if family=='pump':
            candidate=event.get('mint');reference_id='pump-source:'+record_id
            event_type=event.get('event_type')
            if type(event_type) is not str or not event_type:raise ValueError('kernel_validation_reference_event')
            kind='pump_'+event_type
            fields=dict(_economic_order=record['transaction_index'],available_time=int(compact['available']))
        else:
            binding=db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
            candidate=address if binding is None else binding[0]
            reference_id=str(event.get('id') or record_id);kind='pumpswap_trade'
            fields=dict(_economic_order=record['transaction_index'])
        if type(candidate) is not str or not candidate:raise ValueError('kernel_validation_reference_candidate')
        reference=consumer.execute('SELECT slot,transaction_index,event_index,market_time,kind,body,hash FROM canonical_event_refs WHERE lane=? AND candidate=? AND identity=?',
            ('pump',candidate,reference_id)).fetchone()
        expected_order=(slot,record['transaction_index'],record['event_index'],record['market_time'],kind)
        if (reference is None or reference[:5]!=expected_order or type(reference[5]) is not str
                or not _hash(reference[6]) or hashlib.sha256(reference[5].encode()).hexdigest()!=reference[6]):
            raise ValueError('kernel_validation_canonical_reference')
        expected_ref=dict(path=str(source),canonical_identity=record_id,canonical_hash=stored[1],fields=fields)
        if json.loads(reference[5])!=expected_ref:raise ValueError('kernel_validation_canonical_reference_binding')
    return len(rows)


def native_outputs(root,*,endpoint_identity,_observation=None):
    """Read only after the actual native process/owners have stopped."""
    if _observation is not None:
        if type(_observation) is not dict:raise TypeError('native_output_observation')
        _observation.clear()
        _observation.update(schema='native-output-checks-v1',status='PARTIAL',
            authoritative_readiness=False,historical_projection_eligible=False,
            current_stage='ROOT',completed_stages=[],database_count=None,financial_tables_absent=None,
            candidate_references=None,source_receipts=None,canonical_full_ack=None,
            pump_report_read=None,pons_checkpoint_found=None)
    def attempting(stage):
        if _observation is not None:_observation['current_stage']=stage
    def observed(stage,**values):
        if _observation is not None:
            _observation.update(values)
            _observation['completed_stages'].append(stage)
    root=Path(root)
    info=root.lstat()
    if (root.resolve(strict=True)!=root.absolute() or not stat.S_ISDIR(info.st_mode)
            or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700):
        raise ValueError('kernel_validation_output_root')
    observed('ROOT')
    result=dict(financial_tables_absent=True,database_count=0,
        candidate_references=0,canonical_full_ack=0,source_receipts=0,
        unexercised=['Pons_economic_candidates','held_positions','fills','settlement',
            'retained_production_restoration','sustained_market_capacity'])
    attempting('DATABASE_INVENTORY')
    databases=list(root.rglob('*.sqlite'))
    if len(databases)>64:raise ValueError('kernel_validation_database_count')
    for path in databases:
        with closing(_readonly(path)) as db:
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables&_FINANCIAL_TABLES:result['financial_tables_absent']=False
        result['database_count']+=1
    observed('DATABASE_INVENTORY',database_count=result['database_count'],
        financial_tables_absent=result['financial_tables_absent'])
    attempting('HISTORY_COUNTS')
    source=root/'solana-evidence.sqlite';history=root/'candidate-history.sqlite'
    with closing(_readonly(source)) as db,closing(_readonly(history)) as consumer:
        db.execute('BEGIN');consumer.execute('BEGIN')
        try:
            result['candidate_references']=consumer.execute('SELECT COUNT(*) FROM canonical_event_refs').fetchone()[0]
            tables={row[0] for row in consumer.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'source_receipts' in tables:
                result['source_receipts']=consumer.execute('SELECT COUNT(*) FROM source_receipts').fetchone()[0]
            observed('HISTORY_COUNTS',candidate_references=result['candidate_references'],
                source_receipts=result['source_receipts'])
            if 'source_receipts' in tables:
                attempting('FULL_ACK_BINDING')
                result['canonical_full_ack']=_canonical_acks(db,consumer,source,endpoint_identity=endpoint_identity)
                observed('FULL_ACK_BINDING',canonical_full_ack=result['canonical_full_ack'])
        finally:
            consumer.execute('ROLLBACK');db.execute('ROLLBACK')
    attempting('PUMP_REPORT')
    pump=_json_file(root/'pump-current/report.json',1024*1024)
    observed('PUMP_REPORT',pump_report_read=True)
    attempting('PONS_CHECKPOINT')
    with closing(_readonly(root/'pons-candidates.sqlite')) as db:
        row=db.execute("SELECT body FROM runtime WHERE key='pons_cohort'").fetchone()
        if _observation is not None:_observation['pons_checkpoint_found']=row is not None
        if row is None:raise ValueError('kernel_validation_pons_checkpoint')
        pons=json.loads(row[0])['result']
    observed('PONS_CHECKPOINT',pons_checkpoint_found=True)
    attempting('REGIME_READ')
    result['regimes']={
        'pump_current':pump.get('strategy_id')=='pump-acceleration-independent-v1',
        'pump_survivor':'pumpswap-survivor-momentum-v1' in pump.get('active_regimes',[]) and
            (pump.get('survivor') or {}).get('accounting',{}).get('financial_book_constructed') is False,
        'pons_current':'pons-selective-continuation-v1' in pons.get('active_regimes',[]),
        'pons_survivor':'pons-postgrad-survivor-momentum-v1' in pons.get('active_regimes',[]) and
            (pons.get('survivor') or {}).get('accounting',{}).get('financial_book_constructed') is False}
    observed('REGIME_READ',status='COMPLETE')
    return result


def _policy_record(stderr):
    lines=[line.removeprefix(b'NATIVE_POLICY_INSTALLED ') for line in stderr.splitlines()
        if line.startswith(b'NATIVE_POLICY_INSTALLED ')]
    if len(lines)!=1 or len(lines[0])>256:return None
    try:row=json.loads(lines[0])
    except (ValueError,UnicodeError):return None
    if (type(row) is dict and set(row)=={'profile','landlock_abi','installed'}
            and row['profile']==PROFILE and type(row['landlock_abi']) is int
            and 6<=row['landlock_abi']<=65535 and row['installed'] is True):return row
    return None


def verified(value):
    """Synthetic kernel/component acceptance only, never market readiness."""
    if type(value) is not dict:return False
    child=value.get('child')
    outputs=value.get('native_outputs')
    if type(child) is not dict or type(outputs) is not dict:return False
    observation=child.get('observation')
    lifecycle=child.get('native_kernel_lifecycle')
    if type(observation) is not dict or type(lifecycle) is not dict:return False
    workers=observation.get('workers',{})
    executors=lifecycle.get('executors',{})
    if (type(workers) is not dict or type(executors) is not dict
            or any(type(workers.get(name)) is not dict for name in ('pump','pons','sizing'))
            or any(type(executors.get(role)) is not dict for role in ('decoder','history'))):return False
    def integer(row,key,minimum=0,maximum=2**63-1):
        part=row.get(key)
        return type(part) is int and minimum<=part<=maximum
    return (value.get('schema')=='synthetic-native-kernel-validation-v1'
        and value.get('kernel_applied') is True and integer(value,'landlock_abi',6,65535)
        and value.get('owned_process_reaped') is True and value.get('parent_cleanup_joined') is True
        and integer(value,'external_provider_calls',0,0) and value.get('financial_authority') is False
        and integer(value,'production_state_writes',0,0) and value.get('parent_cwd_unchanged') is True
        and child.get('status')=='COMPLETED'
        and observation.get('graceful_shutdown') is True and observation.get('all_workers_joined') is True
        and observation.get('source_joined') is True
        and all(workers[name].get('started') is True and workers[name].get('completed') is True
            for name in ('pump','pons','sizing'))
        and lifecycle.get('tracker_spawned') is True and lifecycle.get('tracker_joined') is True
        and lifecycle.get('spawn_owner_joined') is True
        and type(lifecycle.get('workers_spawned')) is dict
        and set(lifecycle['workers_spawned'])=={'decoder','history'}
        and all(integer(lifecycle['workers_spawned'],role,number,number) for role,number in (('decoder',2),('history',1)))
        and all(executors[role].get('state')=='JOINED'
            and integer(executors[role],'spawned',number,number) and integer(executors[role],'joined',number,number)
            and integer(executors[role],'zero_exit',number,number) and integer(executors[role],'successful',1)
            and integer(executors[role],'probe_successful',0,executors[role]['successful'])
            and integer(executors[role],'nonprobe_successful',1)
            and executors[role]['nonprobe_successful']==executors[role]['successful']-executors[role]['probe_successful']
            and executors[role].get('broken') is False for role,number in (('decoder',2),('history',1)))
        and outputs.get('financial_tables_absent') is True
        and integer(outputs,'canonical_full_ack',1) and integer(outputs,'candidate_references',1)
        and type(outputs.get('regimes')) is dict and set(outputs['regimes'])==
            {'pump_current','pump_survivor','pons_current','pons_survivor'}
        and all(part is True for part in outputs['regimes'].values()))


async def _sizing(writer,approval,session,stopped):
    os.set_blocking(writer,False);sequence=0
    try:
        while not stopped.is_set():
            raw=encoded(sizing_receipt(approval,session=session,at=int(time.time()),sequence=sequence))+b'\n'
            if len(raw)>16384:raise ValueError('kernel_validation_sizing_bound')
            position=0;deadline=time.monotonic()+2
            while position<len(raw):
                if time.monotonic()>=deadline:raise TimeoutError('kernel_validation_sizing_timeout')
                try:position+=os.write(writer,raw[position:])
                except BlockingIOError:await asyncio.sleep(.01)
            sequence+=1
            try:await asyncio.wait_for(stopped.wait(),1)
            except TimeoutError:pass
    finally:os.close(writer)


async def _exercise(scope,approval,*,launcher=_REAL_LAUNCH,seconds=WINDOW_SECONDS):
    # A private test may inject an unconfined copied launcher. Identity forces
    # kernel_applied=False for it regardless of a forged child policy record.
    from .isolated_native_kernel_corpus import SolanaKernelCorpus
    result=dict(schema='synthetic-native-kernel-validation-v1',status='BLOCKED',
        provenance=PROVENANCE,synthetic=True,economic_capacity=False,financial_authority=False,
        external_provider_calls=0,production_state_writes=0,authoritative_historical_recovery=False,
        normal_readiness=False,production_equivalent=False,full_market_speed_proven=False,
        actual_service_restrictions_verified=False,kernel_applied=False,
        owned_process_reaped=False,parent_cleanup_joined=False)
    value=approval.value();result.update(source_commit=value['source_commit'],source_tree=value['source_tree'])
    cwd=Path.cwd();parent=None;owner=None;serving=None;sizing=None;child_socket=None;facts_read=None
    stopped=asyncio.Event();stage='parent_fixture'
    try:
        parent=SyntheticParent(Path(scope),SolanaKernelCorpus(int(time.time())))
        data_socket,child_socket=socket.socketpair()
        reader,writer=await asyncio.open_connection(sock=data_socket)
        serving=asyncio.create_task(serve_connected(reader,writer,parent.channel))
        facts_read,facts_write=os.pipe2(os.O_CLOEXEC)
        sizing=asyncio.create_task(_sizing(facts_write,approval,parent.channel.session,stopped))
        stage='kernel_launch'
        owner=launcher(scope,approval,child_socket,facts_read)
        child_socket.close();child_socket=None;os.close(facts_read);facts_read=None
        stage='native_window';window_started=time.monotonic();deadline=window_started+seconds
        termination_reason='WINDOW_ELAPSED'
        while time.monotonic()<deadline:
            if sizing.done():sizing.result();raise RuntimeError('kernel_validation_sizing_ended')
            if serving.done():
                serving.result();termination_reason='CONTROL_ENDED';break
            if os.waitid(os.P_PID,owner.child.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT) is not None:
                termination_reason='CHILD_EXIT';break
            await asyncio.sleep(.05)
        result['parent_termination']=dict(reason=termination_reason,elapsed_seconds=time.monotonic()-window_started,window_seconds=seconds)
        stage='native_shutdown'
        child=await asyncio.to_thread(owner.stop)
        result['child']=child;result['owned_process_reaped']=owner._reaped
        policy=_policy_record(bytes(owner.output['stderr']))
        if policy is not None:
            result['landlock_abi']=policy['landlock_abi']
            result['kernel_applied']=launcher is _REAL_LAUNCH
        if owner._reaped and child.get('observation',{}).get('all_workers_joined') is True:
            stage='native_outputs'
            result['output_checks']={}
            result['native_outputs']=native_outputs(Path(scope)/'native-work/native/state',
                endpoint_identity=parent.http.sources['pump-discovery'].identity,_observation=result['output_checks'])
    except BaseException as error:
        if isinstance(error,(KeyboardInterrupt,SystemExit)):raise
        result['failure']=dict(stage=stage,error_class=type(error).__name__)
        if stage=='native_outputs':
            code=_output_failure_code(error)
            if code is not None:result['failure']['boundary_code']=code
        number=getattr(error,'errno',None)
        if type(number) is int and 0<number<4096:result['failure']['error_number']=number
    finally:
        # Keep facts available through the original child drain, then join the
        # parent transport and each accepted physical fixture operation.
        if owner is not None and not owner._reaped:
            result['child']=await asyncio.to_thread(owner.stop)
            result['owned_process_reaped']=owner._reaped
        stopped.set()
        if sizing is not None:
            try:await sizing
            except (BrokenPipeError,ConnectionResetError):pass
            except Exception:result['parent_sizing_cleanup_failed']=True
        if child_socket is not None:child_socket.close()
        if facts_read is not None:os.close(facts_read)
        if parent is not None:
            try:
                await parent.close()
                if serving is not None:await serving
                result['parent_cleanup_joined']=True
            except Exception:result['parent_cleanup_failed']=True
            result['fixture_counters']=parent.counters()
            result['parent_first_fault']=parent.channel.first_fault()
            state=parent.budget.snapshot()
            result['budget_counters']={key:int(state[key]) for key in ('http_attempts','rpc_elements',
                'http_bytes','http_reserved','http_uncertain_bytes','native_bytes','native_reserved','native_uncertain_bytes','native_opens')}
        result['parent_cwd_unchanged']=Path.cwd()==cwd
    result['status']='SYNTHETIC_NATIVE_KERNEL_VALIDATED' if verified(result) else 'BLOCKED'
    if len(encoded(result))>MAX_RESULT:raise ValueError('kernel_validation_result_bound')
    return result


def validate(scope,approval):
    """Only actual kernel confinement may satisfy the public positive predicate."""
    if type(approval) is not NativeImageApproval:raise ValueError('kernel_validation_source_approval')
    if os.geteuid()==0:raise ValueError('kernel_validation_unprivileged_required')
    return asyncio.run(_exercise(scope,approval))
