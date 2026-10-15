"""One offline post-selection native attachment/cancellation discriminator.

Copies only the stopped, selected monetary/native fixture through SQLite's
read-only backup API. Never copies canonical market evidence or calls providers.
This is an attachment lifecycle diagnostic, not a capacity or recovery PASS.
"""
from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import sqlite3
import subprocess
import sys
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

MAX_FIXTURE_BYTES=25*1024*1024
MAX_OUTPUT_BYTES=1024*1024
ABSOLUTE_SECONDS=120
SHUTDOWN_SECONDS=15
FILES=('portfolio.sqlite','shared-capital.sqlite',
       'pump/pump-acceleration-natural-prospective.accounting.sqlite3')


def emit(phase,**facts):
    import threading
    print(json.dumps(dict(phase=phase,at=time.time(),monotonic=time.monotonic(),
        process_cpu=time.process_time(),pid=os.getpid(),native_thread_id=threading.get_native_id(),
        **facts),sort_keys=True),flush=True)


def child(root):
    # Inherited operational paths must not escape this disposable fixture.
    for name in tuple(os.environ):
        if name.startswith('MM_'):os.environ.pop(name,None)
    from meme_machine.operational.offline import install_network_guard
    install_network_guard()
    from meme_machine.operational import lane
    from meme_machine.runtime import stop
    from meme_machine.lanes.pump import runner
    from meme_machine.lanes.pump.paper_accounting import PaperBook
    from meme_machine.shared_capital.authority import CapitalAuthority
    from meme_machine.shared_capital.runtime import RuntimeCapital
    original_connect=sqlite3.connect
    original_verify=CapitalAuthority.verify_replay
    original_apply=RuntimeCapital._apply
    count=0;apply_wall=0.;apply_cpu=0.

    class ObservedConnection(sqlite3.Connection):
        def __init__(self,database,*args,**kwargs):
            self.observed=Path(str(database).split('?')[0]).name=='shared-capital.sqlite'
            if self.observed:emit('shared.open.enter')
            super().__init__(database,*args,**kwargs)
            if self.observed:emit('shared.open.complete')
        def execute(self,sql,*args,**kwargs):
            # Fixed labels only: no expanded SQL, bodies, bindings or locals.
            tag={'PRAGMA journal_mode=WAL':'shared.journal_mode',
                 'PRAGMA synchronous=FULL':'shared.synchronous',
                 'BEGIN':'shared.read_begin','BEGIN IMMEDIATE':'shared.write_begin',
                 'COMMIT':'shared.commit','ROLLBACK':'shared.rollback'}.get(sql.strip())
            if self.observed and tag:emit(tag+'.enter')
            result=super().execute(sql,*args,**kwargs)
            if self.observed and tag:emit(tag+'.complete')
            return result
        def executescript(self,sql):
            if self.observed:emit('shared.schema.enter')
            result=super().executescript(sql)
            if self.observed:emit('shared.schema.complete')
            return result

    def connect(*args,**kwargs):
        kwargs.setdefault('factory',ObservedConnection)
        return original_connect(*args,**kwargs)
    def verify(owner):
        emit('shared.replay.enter',requested=stop.requested.is_set())
        try:return original_verify(owner)
        finally:emit('shared.replay.finish',requested=stop.requested.is_set(),
                     applied=count,apply_wall_seconds=apply_wall,apply_cpu_seconds=apply_cpu)
    def apply(owner,state,event):
        nonlocal count,apply_wall,apply_cpu
        wall=time.monotonic();cpu=time.thread_time()
        result=original_apply(owner,state,event)
        count+=1;apply_wall+=time.monotonic()-wall;apply_cpu+=time.thread_time()-cpu
        if count==1 or count%128==0 or stop.requested.is_set():
            # After TERM only the first eight completions need detail. The
            # original authenticated replay remains entirely unchanged.
            if not stop.requested.is_set() or after_term[0]<8:
                emit('shared.replay.row',applied=count,requested=stop.requested.is_set(),
                     apply_wall_seconds=apply_wall,apply_cpu_seconds=apply_cpu)
                if stop.requested.is_set():after_term[0]+=1
        return result
    after_term=[0]
    def accounting_only(**kwargs):
        identity=json.loads((root/'fixture-identity.json').read_text())
        emit('pump.accounting_restore.enter')
        book=runner._startup_work('pump.accounting_restore',PaperBook,
            str(root/'pump/pump-acceleration-natural-prospective.accounting.sqlite3'),
            run_id=identity['run_id'],lane=identity['lane'],
            policy_hash=runner.policy_hash(),initial=identity['initial'])
        try:emit('pump.accounting_restore.complete',requested=stop.requested.is_set())
        finally:book.db.close()  # Fixture connection only; no checkpoint change.

    os.environ.update(MM_MODE='PAPER',MM_RUNTIME_LANE='pump',
        MM_PAPER_EPOCH=json.loads((root/'fixture-identity.json').read_text())['run_id'],
        MM_PORTFOLIO_ACCOUNTING_DB=str(root/'portfolio.sqlite'),
        MM_PUMP_ACCELERATION_REPORT=str(root/'pump/pump-acceleration-natural-prospective.json'))
    # Imports/constants stay source-native; only unrelated work is excluded.
    with patch('sys.argv',['lane','--lane','pump','--state-root',str(root)]), \
            patch('meme_machine.operational.bounded_provider.install'), \
            patch.object(runner,'main',side_effect=accounting_only), \
            patch('sqlite3.connect',side_effect=connect), \
            patch.object(CapitalAuthority,'verify_replay',verify), \
            patch.object(RuntimeCapital,'_apply',apply):
        emit('lane.main.enter')
        try:lane.main()
        except BaseException as error:
            emit('lane.main.error',error_type=type(error).__name__,
                sqlite_errorcode=getattr(error,'sqlite_errorcode',None),
                sqlite_errorname=getattr(error,'sqlite_errorname',None))
            raise
        finally:emit('lane.main.finish',requested=stop.requested.is_set(),applied=count)


def copy_fixture(source,target,scratch,deadline):
    from meme_machine.operational.artifact_storage import Policy,headroom
    estimate=0
    for relative in FILES:
        path=source/relative
        if not path.is_file() or path.is_symlink():raise RuntimeError('fixture_source_missing_or_link')
        estimate+=path.stat().st_size
        wal=path.with_name(path.name+'-wal')
        if wal.exists():estimate+=wal.stat().st_size
    policy=Policy.environment()
    if estimate>MAX_FIXTURE_BYTES or estimate>policy.snapshot_max_bytes:
        raise RuntimeError('small_fixture_admission_exceeded')
    headroom(scratch.path,estimate,policy=policy)
    receipts=[]
    for relative in FILES:
        path=source/relative;destination=target/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=0)) as original, \
                closing(sqlite3.connect(destination)) as replica:
            original.execute('PRAGMA query_only=ON')
            def progress(*_):
                if time.monotonic()>=deadline:raise TimeoutError('fixture_copy_deadline')
                scratch.check()
            original.backup(replica,pages=256,progress=progress,sleep=.05)
        receipts.append(dict(path=relative,bytes=destination.stat().st_size,
            sha256=hashlib.sha256(destination.read_bytes()).hexdigest()))
    # Small immutable native genesis only, with its exact original values.
    genesis=source/'pump/native-genesis.json'
    if genesis.is_symlink() or genesis.stat().st_size>4096:raise RuntimeError('native_genesis_fixture_bound')
    (target/'pump/native-genesis.json').write_bytes(genesis.read_bytes())
    with closing(sqlite3.connect((target/FILES[-1]).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        identity=json.loads(db.execute('SELECT body FROM genesis WHERE id=1').fetchone()[0])
    (target/'fixture-identity.json').write_text(json.dumps(identity,sort_keys=True))
    return dict(estimated_source_and_WAL_bytes=estimate,files=receipts,
                coherent_each_database=True,coherent_cross_database='STOPPED_SOURCE_PRECONDITION')


def run(source,output):
    from meme_machine.operational.artifact_storage import Scratch
    from meme_machine.operational.offline import install_network_guard
    install_network_guard()
    started=time.monotonic();deadline=started+ABSOLUTE_SECONDS
    result=dict(started=time.time(),source_root=str(source),scope='one_authentic_monetary_attachment_lifecycle_discriminator',
        market_io='NETWORK_BLOCKED',canonical_copy=False,authoritative_writes=False,
        shutdown_seconds=SHUTDOWN_SECONDS,absolute_seconds=ABSOLUTE_SECONDS,events=[])
    with Scratch() as scratch:
        target=scratch.path/'attachment-fixture';target.mkdir()
        result['fixture']=copy_fixture(source,target,scratch,deadline)
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--child',str(target)],
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True,bufsize=0)
        selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
        buffer=b'';size=0;term_at=None;requested_after_rows=[]
        try:
            while process.poll() is None or selector.get_map():
                now=time.monotonic();scratch.check()
                if term_at is None and now>=deadline-SHUTDOWN_SECONDS-5:
                    os.killpg(process.pid,signal.SIGTERM);term_at=now
                    result['term_reason']='PRE_REPLAY_STARTUP_BOUND'
                if (term_at is not None and process.poll() is None and
                        now-term_at>=SHUTDOWN_SECONDS and not result.get('escalated')):
                    os.killpg(process.pid,signal.SIGKILL);result['escalated']=True
                if now>=deadline:
                    if process.poll() is None:os.killpg(process.pid,signal.SIGKILL)
                    raise TimeoutError('attachment_absolute_bound')
                for key,_ in selector.select(.1):
                    data=os.read(key.fileobj.fileno(),65536)
                    if not data:selector.unregister(key.fileobj);continue
                    size+=len(data)
                    if size>MAX_OUTPUT_BYTES:raise RuntimeError('attachment_recorder_capacity')
                    buffer+=data
                    while b'\n' in buffer:
                        raw,buffer=buffer.split(b'\n',1)
                        try:row=json.loads(raw)
                        except (ValueError,UnicodeDecodeError):
                            # Fixed original exception class/code only; never
                            # retain arbitrary third-party stderr or paths.
                            result['non_json_lines']=result.get('non_json_lines',0)+1;continue
                        if not isinstance(row,dict) or not isinstance(row.get('phase'),str):continue
                        result['events'].append(row)
                        if row['phase']=='shared.replay.row' and term_at is None:
                            os.killpg(process.pid,signal.SIGTERM);term_at=time.monotonic()
                            result['term_reason']='AFTER_FIRST_AUTHENTICATED_REPLAY_ROW'
                        if row['phase']=='shared.replay.row' and row.get('requested'):
                            requested_after_rows.append(row)
            result['exit_code']=process.wait(timeout=5)
            result['post_TERM_replay_progress']=requested_after_rows
            result['terminal_health']=json.loads((target/'pump/health.json').read_text())
            result['elapsed_seconds']=time.monotonic()-started
            result['recorder_bytes']=size
            cancelled=any(row.get('state')=='CANCELLED' for row in
                result['terminal_health'].get('native_recent_operations',[]))
            result['classification']=('UNCANCELLED_AUTHENTICATED_REPLAY_DEMONSTRATED'
                if requested_after_rows and result['exit_code']==-9 else
                'COOPERATIVE_STARTUP_CANCELLATION' if cancelled and result['exit_code']==0 else
                'ATTACHMENT_VERIFIED' if result['exit_code']==0 and any(
                    row['phase']=='pump.accounting_restore.complete' for row in result['events']) else
                'ATTRIBUTION_INCONCLUSIVE')
            result['limitations']=['Narrow authentic monetary/native fixture; no full-machine capacity claim.',
                'Provider installation is excluded; no market I/O, canonical intake or complete candidate startup is exercised.',
                'No causal claim about original historicalSQLite_BUSY or unseen native operations.']
            output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
            # A reproduced killed child is useful evidence but its disposable
            # fixture stays retained rather than being called a successful drain.
            scratch.success=result['exit_code']==0
        except BaseException as error:
            result.update(classification='DIAGNOSTIC_INCOMPLETE',error_type=type(error).__name__,
                sqlite_errorcode=getattr(error,'sqlite_errorcode',None),
                sqlite_errorname=getattr(error,'sqlite_errorname',None),
                elapsed_seconds=time.monotonic()-started)
            try:output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
            except Exception as recording:
                print('attachment_result_unavailable:'+type(recording).__name__,file=sys.stderr)
            raise
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                remaining=min(SHUTDOWN_SECONDS,max(0,deadline-time.monotonic()-5))
                try:process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
            selector.close()
    print(json.dumps(dict(result=str(output),classification=result['classification'],
        exit_code=result['exit_code'],elapsed_seconds=result['elapsed_seconds'])))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--child',type=Path)
    parser.add_argument('--source-root',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.child:child(args.child)
    elif args.source_root and args.output:run(args.source_root,args.output)
    else:parser.error('explicit source-root/output or isolated child required')


if __name__=='__main__':main()
