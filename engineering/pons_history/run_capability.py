"""One fixed capability comparison with offline preflight and a process deadline.

Run only under the owner's explicit finite provider authorization. No startup,
portfolio, economic reconstruction, service control or retry is performed here.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import shlex
import signal
import sqlite3
import time

from .bounded import Execution, Stop, STORAGE, FIRST, LAST, REFERENCE_TX, wall_guard
from .capability import compare
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.pons_history import PonsHistory
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
from meme_machine.lanes.pons.provider_topology import configured_rpc
from meme_machine.runtime.robinhood import provider_authority as authority

VOLUME=Path('/mnt/volume_nyc1_1790918115030')
FILE_LIMIT=8*1024*1024


def supervise(action, *, seconds=44.5, root=None):
    """One provider worker; parent independently kills it, with no second attempt."""
    started=time.monotonic()
    pid=os.fork()
    if pid==0:
        try:action(started)
        except BaseException:os._exit(1)
        os._exit(0)
    killed=False
    peak=0
    while True:
        done,status=os.waitpid(pid,os.WNOHANG)
        if done:break
        if root is not None:
            size=0
            for p in root.rglob('*'):
                try:
                    if p.is_file():size+=p.stat().st_size
                except FileNotFoundError:pass
            peak=max(peak,size)
            if size>=STORAGE:
                os.kill(pid,signal.SIGKILL)
                _,status=os.waitpid(pid,0)
                return dict(provider_window_seconds=time.monotonic()-started,
                    forced_shutdown=True,forced_reason='independent_parent_storage_ceiling',
                    worker_wait_status=status,provider_workers=1,observed_peak_temporary_bytes=peak)
        if time.monotonic()-started>=seconds:
            os.kill(pid,signal.SIGKILL)
            _,status=os.waitpid(pid,0)
            killed=True
            break
        time.sleep(min(.01,max(.0001,seconds-(time.monotonic()-started))))
    return dict(provider_window_seconds=time.monotonic()-started,
                forced_shutdown=killed,forced_reason='independent_parent_wall_deadline' if killed else None,
                worker_wait_status=status,provider_workers=1,observed_peak_temporary_bytes=peak)


def classify(error):
    if isinstance(error,Stop):return error.classification,error.reason
    reason=str(error) if isinstance(error,BoundaryError) else authority.failure_class(error)
    if reason in ('capability_nonempty_sample_required','capability_reference_sample_unavailable',
                  'provider_missing_result','provider_state_unavailable'):
        return 'INSUFFICIENT_SAMPLE',reason
    if reason in ('provider_response_capacity','capability_budget_exhausted','capability_wall_exhausted'):
        return 'BUDGET_STOP',reason
    if isinstance(error,sqlite3.Error) and getattr(error,'sqlite_errorcode',None)==sqlite3.SQLITE_FULL:
        return 'BUDGET_STOP','sqlite_storage_ceiling'
    if reason.startswith(('capability_','historical_','raw_event_','receipt_','immutable_')) or 'invalid_' in reason:
        return 'CANONICAL_COMPARISON_FAILED',reason
    return 'BLOCKED',reason


def worker(root,started, *, opener=None):
    execution=history=rpc=None
    receipt=None
    classification,reason='BLOCKED','worker_incomplete'
    resource.setrlimit(resource.RLIMIT_FSIZE,(FILE_LIMIT,FILE_LIMIT))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    def file_stop(*_):raise Stop('BUDGET_STOP','individual_file_storage_ceiling')
    signal.signal(signal.SIGXFSZ,file_stop)
    try:
        # 1 second of the owner's 45-second ceiling is reserved for shutdown.
        with wall_guard(started+44):
            rpc=configured_rpc(limit=64,per_scope=64,retries=0,timeout=10)
            history=PonsHistory(root/'history.sqlite',policy=POLICY_HASH)
            # Only these two SQLite files are disposable write destinations.
            for db in (history.db,rpc.evidence_reuse.store.db):
                db.execute('PRAGMA max_page_count=2048')
                db.execute('PRAGMA temp_store=MEMORY')
                db.execute('PRAGMA wal_autocheckpoint=256')
            execution=Execution(rpc,root,started+44,opener=opener)
            with execution.install():
                rpc.verify_chain()  # This setup request is inside every aggregate budget.
                receipt=compare(history,lambda:rpc,FIRST,required_transaction=REFERENCE_TX)
                execution.check()
                classification,reason='SUPPORTED_40_BLOCK_SAMPLE','complete_canonical_equivalence'
    except BaseException as exc:
        classification,reason=classify(exc)
    finally:
        baseline=history.get_meta('pons_capability_baseline') if history else None
        candidate=history.get_meta('pons_capability_candidate') if history else None
        data=dict(classification=classification,stop_reason=reason,first=FIRST,last=LAST,
            comparison=receipt,baseline=baseline,candidate=candidate,
            usage=execution.usage() if execution else None,
            native_telemetry=rpc.telemetry() if rpc else None,
            worker_elapsed_seconds=time.monotonic()-started)
        if history:history.close()
        if rpc and rpc.evidence_reuse:rpc.evidence_reuse.store.db.close()
        if execution:
            execution.persist()
            execution.save('worker-result.json',json.dumps(data,sort_keys=True).encode())
        else:
            (root/'worker-result.json').write_text(json.dumps(data,sort_keys=True))


def preflight(root):
    # Use the existing configured credential for transport, never emit it.
    config={}
    for line in Path('/etc/meme-machine/paper.env').read_text().splitlines():
        if line.startswith('#') or '=' not in line:continue
        key,value=line.split('=',1)
        if key in ('MM_MODE','MM_STATE_ROOT',authority.PRIMARY):
            config[key]=shlex.split(value)[0]
    if config.get('MM_MODE')!='PAPER':raise Stop('BLOCKED','paper_configuration_unavailable')
    endpoint=authority.endpoint(config.get(authority.PRIMARY),environ={authority.PRIMARY:config.get(authority.PRIMARY)})
    fingerprint=authority.fingerprint(endpoint)
    governor=Path(config['MM_STATE_ROOT'])/'shared/robinhood-provider.sqlite'
    if not governor.is_file() or governor.stat().st_size>=7*1024*1024:
        raise Stop('BLOCKED','existing_shared_governor_unavailable_or_file_bound')
    with sqlite3.connect('file:'+str(governor)+'?mode=ro',uri=True) as db:
        row=db.execute('SELECT interval FROM limits WHERE endpoint=?',(fingerprint,)).fetchone()
        if row is None or row[0]<.5:raise Stop('BLOCKED','existing_physical_pacing_unavailable')
    root=root.resolve()
    if not root.is_relative_to(VOLUME) or not os.path.ismount(VOLUME):
        raise Stop('BLOCKED','persistent_volume_required')
    if os.statvfs(VOLUME).f_bavail*os.statvfs(VOLUME).f_frsize<STORAGE:
        raise Stop('BLOCKED','temporary_storage_reserve_unavailable')
    if root.exists():raise Stop('BLOCKED','single_attempt_output_already_exists')
    root.mkdir(mode=0o700)
    # Child-only process environment; production configuration remains untouched.
    os.environ.update({authority.PRIMARY:endpoint,'MM_RUNTIME_LANE':'pons',
        'MM_PROVIDER_DB':str(governor),'MM_RPC_CACHE_DB':str(root/'evidence.sqlite'),
        'MM_ROBINHOOD_STATE_DIR':str(root),'TMPDIR':str(root)})
    (root/'preflight.json').write_text(json.dumps(dict(provider_fingerprint=fingerprint,
        governor=str(governor),interval_seconds=row[0],first=FIRST,last=LAST,
        started_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        per_file_limit_bytes=FILE_LIMIT,sqlite_page_limit_bytes=FILE_LIMIT,
        storage_structural_bound_bytes=32*2_000_000+6*FILE_LIMIT+16*1024*1024,
        wall_guard_seconds=44,parent_shutdown_seconds=44.5,owner_wall_ceiling_seconds=45,
        retry_count=0,one_shot=True),sort_keys=True))
    return root


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    root=preflight(args.output)
    supervision=supervise(lambda started:worker(root,started),root=root)
    path=root/'worker-result.json'
    result=json.loads(path.read_text()) if path.exists() else dict(
        classification='BUDGET_STOP' if supervision['forced_shutdown'] else 'BLOCKED',
        stop_reason='independent_parent_wall_deadline' if supervision['forced_shutdown'] else 'worker_result_unavailable',
        usage=json.loads((root/'usage.json').read_text()) if (root/'usage.json').exists() else None)
    if supervision['forced_shutdown']:
        result.update(classification='BUDGET_STOP',stop_reason=supervision['forced_reason'])
    stock=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    result.update(supervision=supervision,temporary_final_bytes=stock,
        provider_certified=False,seven_day_coverage_complete=False)
    for _ in range(4):
        raw=json.dumps(result,sort_keys=True,indent=2)+'\n'
        result['temporary_final_bytes']=stock+len(raw.encode())
    (root/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps(dict(classification=result['classification'],stop_reason=result['stop_reason'],
        usage={k:v for k,v in (result.get('usage') or {}).items() if k!='attempts'},
        supervision=supervision,temporary_final_bytes=result['temporary_final_bytes']),sort_keys=True))


if __name__=='__main__':main()
