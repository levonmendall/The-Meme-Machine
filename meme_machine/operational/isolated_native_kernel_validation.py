"""Fixed full-main synthetic kernel validation, without PAPER/market authority.

The public route always uses the reviewed Landlock launcher. Its source-owned
offline parent replaces physical providers, never native consumers, decoding,
SQLite publication, FULL/ACK or shutdown. Missing coverage remains BLOCKED.
"""
import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import stat
import time

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


def _json_file(path,maximum=MAX_RESULT):
    path=Path(path);info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>maximum:raise ValueError('kernel_validation_file_bound')
    return json.loads(path.read_bytes())


def _readonly(path):
    path=Path(path);info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('kernel_validation_database_inode')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=1,isolation_level=None)
    db.execute('PRAGMA query_only=ON')
    return db


def native_outputs(root):
    """Read only after the actual native process/owners have stopped."""
    root=Path(root);result=dict(financial_tables_absent=True,database_count=0,
        candidate_references=0,canonical_full_ack=0,source_receipts=0,
        unexercised=['Pons_economic_candidates','held_positions','fills','settlement',
            'retained_production_restoration','sustained_market_capacity'])
    databases=list(root.rglob('*.sqlite'))
    if len(databases)>64:raise ValueError('kernel_validation_database_count')
    for path in databases:
        with closing(_readonly(path)) as db:
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables&_FINANCIAL_TABLES:result['financial_tables_absent']=False
        result['database_count']+=1
    source=root/'solana-evidence.sqlite';history=root/'candidate-history.sqlite'
    with closing(_readonly(source)) as db,closing(_readonly(history)) as consumer:
        db.execute('BEGIN');consumer.execute('BEGIN')
        try:
            result['candidate_references']=consumer.execute('SELECT COUNT(*) FROM canonical_event_refs').fetchone()[0]
            tables={row[0] for row in consumer.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'source_receipts' in tables:
                result['source_receipts']=consumer.execute('SELECT COUNT(*) FROM source_receipts').fetchone()[0]
                rows=db.execute("SELECT id,body,hash FROM candidate_history_outbox WHERE kind='canonical' AND consumed IS NOT NULL ORDER BY id LIMIT 1025").fetchall()
                if len(rows)>1024:raise ValueError('kernel_validation_ack_bound')
                for identity,raw,checksum in rows:
                    if hashlib.sha256(raw.encode()).hexdigest()!=checksum:raise ValueError('kernel_validation_source_ack_hash')
                    compact=json.loads(raw)
                    receipt=consumer.execute('SELECT body,hash FROM source_receipts WHERE id=?',(identity,)).fetchone()
                    if receipt is None or hashlib.sha256(receipt[0].encode()).hexdigest()!=receipt[1]:
                        raise ValueError('kernel_validation_consumer_ack_hash')
                    proof=json.loads(receipt[0])
                    if (proof.get('source_hash')!=compact.get('source_hash')
                            or proof.get('canonical_identity')!=compact.get('record',{}).get('identity')):
                        raise ValueError('kernel_validation_ack_binding')
                    result['canonical_full_ack']+=1
        finally:
            consumer.execute('ROLLBACK');db.execute('ROLLBACK')
    pump=_json_file(root/'pump-current/report.json',1024*1024)
    with closing(_readonly(root/'pons-candidates.sqlite')) as db:
        row=db.execute("SELECT body FROM runtime WHERE key='pons_cohort'").fetchone()
        if row is None:raise ValueError('kernel_validation_pons_checkpoint')
        pons=json.loads(row[0])['result']
    result['regimes']={
        'pump_current':pump.get('strategy_id')=='pump-acceleration-v1',
        'pump_survivor':'pumpswap-survivor-momentum-v1' in pump.get('active_regimes',[]) and
            (pump.get('survivor') or {}).get('accounting',{}).get('financial_book_constructed') is False,
        'pons_current':'pons-selective-continuation-v1' in pons.get('active_regimes',[]),
        'pons_survivor':'pons-postgrad-survivor-momentum-v1' in pons.get('active_regimes',[]) and
            (pons.get('survivor') or {}).get('accounting',{}).get('financial_book_constructed') is False}
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
    observation=value.get('child',{}).get('observation',{})
    workers=observation.get('workers',{})
    lifecycle=value.get('child',{}).get('native_kernel_lifecycle',{})
    executors=lifecycle.get('executors',{})
    outputs=value.get('native_outputs',{})
    return (value.get('schema')=='synthetic-native-kernel-validation-v1'
        and value.get('kernel_applied') is True and value.get('landlock_abi',0)>=6
        and value.get('owned_process_reaped') is True and value.get('parent_cleanup_joined') is True
        and value.get('external_provider_calls')==0 and value.get('financial_authority') is False
        and value.get('production_state_writes')==0 and value.get('parent_cwd_unchanged') is True
        and value.get('child',{}).get('status')=='COMPLETED'
        and observation.get('graceful_shutdown') is True and observation.get('all_workers_joined') is True
        and observation.get('source_joined') is True
        and all(workers.get(name,{}).get('started') is True and workers[name].get('completed') is True
            for name in ('pump','pons','sizing'))
        and lifecycle.get('tracker_spawned') is True and lifecycle.get('tracker_joined') is True
        and lifecycle.get('spawn_owner_joined') is True
        and all(executors.get(role,{}).get('state')=='JOINED'
            and executors[role].get('spawned')==number and executors[role].get('joined')==number
            and executors[role].get('zero_exit')==number and executors[role].get('successful',0)>0
            and executors[role].get('broken') is False for role,number in (('decoder',2),('history',1)))
        and outputs.get('financial_tables_absent') is True
        and outputs.get('canonical_full_ack',0)>0 and outputs.get('candidate_references',0)>0
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
        stage='native_window';deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if sizing.done():sizing.result();raise RuntimeError('kernel_validation_sizing_ended')
            if serving.done():serving.result();break
            if os.waitid(os.P_PID,owner.child.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT) is not None:break
            await asyncio.sleep(.05)
        stage='native_shutdown'
        child=await asyncio.to_thread(owner.stop)
        result['child']=child;result['owned_process_reaped']=owner._reaped
        policy=_policy_record(bytes(owner.output['stderr']))
        if policy is not None:
            result['landlock_abi']=policy['landlock_abi']
            result['kernel_applied']=launcher is _REAL_LAUNCH
        if owner._reaped and child.get('observation',{}).get('all_workers_joined') is True:
            stage='native_outputs'
            result['native_outputs']=native_outputs(Path(scope)/'native-work/native/state')
    except BaseException as error:
        if isinstance(error,(KeyboardInterrupt,SystemExit)):raise
        result['failure']=dict(stage=stage,error_class=type(error).__name__)
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
