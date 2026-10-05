"""systemd-owned acceptance records and logs; never PAPER economic authority."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from .observation import atomic_json, read_json, stamp, SAMPLE_BOUND

DURATIONS = {'CAPACITY':3600, 'RECOVERY':None, 'AUTONOMY':129600}
OUTPUT = Path('/var/lib/meme-machine-acceptance')
OBSERVER = Path('/var/lib/meme-machine-observer')
LOG_BOUND = 8*1024**2
OBSERVATION_BOUND = 512*1024**2

def retain_completed(output,keep=8):
    """Bound old attempt storage; never remove an active run or latest result."""
    output=Path(output)
    referenced=set()
    for pointer in output.glob('latest-*.json'):
        try:referenced.add(read_json(pointer)['directory'])
        except (OSError,ValueError,KeyError):continue
    complete=[]
    for folder in output.iterdir():
        if not folder.is_dir() or folder.is_symlink():continue
        try:row=read_json(folder/'status.json')
        except (OSError,ValueError):continue
        if row.get('status') in ('PASS','FAIL') and str(folder) not in referenced:
            complete.append(folder)
    import shutil
    for folder in sorted(complete,reverse=True)[keep:]:shutil.rmtree(folder)


def source_identity(source):
    from .configuration import capture
    return capture(source)


def observed(observer, epoch, now=None):
    row=read_json(Path(observer)/'latest.json',limit=SAMPLE_BOUND)
    age=(time.time() if now is None else now)-row['timestamp']
    if not 0<=age<=45 or row.get('portfolio',{}).get('epoch_id')!=epoch:
        raise ValueError('observation_stale_or_wrong_epoch')
    return row


def run_child(command, folder, record, observer=None, pointer=None):
    from .storage_measurement import Trend
    trend=Trend()
    """Persist interrupted/failed children as failures, without stopping PAPER."""
    folder=Path(folder)
    started=time.monotonic();samples=0;observation_bytes=0;issues=[]
    record.update(status='RUNNING',start_time=stamp(),start_timestamp=time.time(),
        end_time=None,exit_code=None,full_duration_completed=False)
    atomic_json(folder/'status.json',record)
    if pointer is not None:atomic_json(pointer,record)
    with (folder/'stdout.log').open('ab') as stdout, (folder/'stderr.log').open('ab') as stderr, \
            (folder/'observations.jsonl').open('ab') as observation_log:
        child=subprocess.Popen(command,stdout=stdout,stderr=stderr)
        def terminate(*_):
            if child.poll() is None:child.terminate()
            raise InterruptedError('acceptance_interrupted')
        previous={sig:signal.signal(sig,terminate) for sig in (signal.SIGTERM,signal.SIGINT)}
        try:
            while True:
                if observer is not None:
                    try:
                        sample=observed(observer,record['epoch_id'])
                        trend.add(sample)
                        body=json.dumps(sample,sort_keys=True,allow_nan=False).encode()+b'\n'
                        observation_bytes+=len(body)
                        if observation_bytes>OBSERVATION_BOUND:
                            raise ValueError('acceptance_observation_storage_bound')
                        observation_log.write(body);observation_log.flush();os.fsync(observation_log.fileno())
                        samples+=1
                    except (OSError,ValueError,KeyError,TypeError):
                        issues.append('observation_unavailable');issues=issues[-32:]
                for stream in (stdout,stderr):
                    if os.fstat(stream.fileno()).st_size>LOG_BOUND:
                        issues.append('acceptance_log_bound');child.terminate()
                code=child.poll()
                if code is not None:
                    break
                time.sleep(10)
        except BaseException:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=15)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
            record.update(status='FAIL',interrupted=True)
            raise
        finally:
            for sig,handler in previous.items():signal.signal(sig,handler)
            elapsed=time.monotonic()-started
            duration=record.get('required_seconds')
            full=duration is None or elapsed>=duration
            record.update(end_time=stamp(),end_timestamp=time.time(),elapsed_seconds=elapsed,
                exit_code=child.poll(),observation_samples=samples,observation_errors=issues,
                full_duration_completed=full)
            record['storage_growth']=trend.result()
            if record['status']!='FAIL':
                record['status']='PASS' if child.poll()==0 and not issues and full else 'FAIL'
            atomic_json(folder/'status.json',record)
    return record


def execute(phase, output=OUTPUT, observer=OBSERVER):
    if phase not in DURATIONS:raise ValueError('unknown_acceptance_phase')
    output=Path(output);output.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=(output/'run.lock').open('a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close();raise RuntimeError('acceptance_already_running') from None
    try:
        retain_completed(output)
        from .storage_guard import verify_storage
        # This unit deliberately bind-mounts economic storage read-only. The
        # runtime's default guard still requires a writable original volume.
        root=Path(os.environ['MM_STATE_ROOT']).resolve();storage=verify_storage(root,require_writable=False)
        source=Path(__file__).resolve().parents[2]
        identity=source_identity(source)
        expected=dict(commit=os.environ['MM_ACCEPTANCE_COMMIT'],tree=os.environ['MM_ACCEPTANCE_TREE'])
        if any(identity[k]!=v for k,v in expected.items()) or storage['epoch_id']!=os.environ['MM_ACCEPTANCE_EPOCH']:
            raise ValueError('acceptance_candidate_identity_mismatch')
        if phase!='CAPACITY':
            previous='CAPACITY' if phase=='RECOVERY' else 'RECOVERY'
            prior=read_json(output/f'latest-{previous}.json')
            if prior['status']!='PASS' or prior['identity']!=identity or prior['epoch_id']!=storage['epoch_id']:
                raise ValueError('same_candidate_preceding_phase_required')
        observed(observer,storage['epoch_id'])
        folder=output/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+phase+'-'+uuid.uuid4().hex[:8])
        folder.mkdir(mode=0o700)
        record=dict(phase=phase,identity=identity,epoch_id=storage['epoch_id'],unit=f'meme-machine-acceptance@{phase}.service',
            required_seconds=DURATIONS[phase],directory=str(folder),purpose='PAPER operational mechanics',
            expected_end_timestamp=time.time()+DURATIONS[phase] if DURATIONS[phase] is not None else None)
        pointer=output/f'latest-{phase}.json'
        record.update(status='STARTING');atomic_json(pointer,record)
        command=[sys.executable,'-m','meme_machine.operational.acceptance',phase,
                 '--state-root',str(root),'--result-path',str(folder/'result.json')]
        if DURATIONS[phase] is not None:command+=['--seconds',str(DURATIONS[phase])]
        try:
            record=run_child(command,folder,record,observer,pointer)
            result=read_json(folder/'result.json')
            if result.get('passed') is not True or source_identity(source)!=identity:
                record['status']='FAIL';record['candidate_or_result_failure']=True
        except BaseException:
            record.update(status='FAIL',end_time=stamp(),end_timestamp=time.time())
            raise
        finally:
            # run_child mutates this ordinary status record even on interruption.
            atomic_json(folder/'status.json',record);atomic_json(pointer,record)
        return 0 if record['status']=='PASS' else 1
    finally:
        lock.close()


def finalize(phase, output=OUTPUT):
    pointer=Path(output)/f'latest-{phase}.json'
    if not pointer.exists():return
    row=read_json(pointer)
    if row.get('status') in ('STARTING','RUNNING'):
        row.update(status='FAIL',end_time=stamp(),end_timestamp=time.time(),
                   interrupted=True,systemd_result=os.environ.get('SERVICE_RESULT','unknown'),
                   systemd_exit_code=os.environ.get('EXIT_CODE'),systemd_exit_status=os.environ.get('EXIT_STATUS'))
        atomic_json(Path(row['directory'])/'status.json',row);atomic_json(pointer,row)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('run','finalize'))
    parser.add_argument('phase',choices=tuple(DURATIONS))
    args=parser.parse_args()
    if args.command=='finalize':finalize(args.phase);return 0
    try:return execute(args.phase)
    except Exception as error:
        record=dict(status='FAIL',phase=args.phase,error_type=type(error).__name__,
            end_time=stamp(),exit_code=1,full_duration_completed=False,
            commit=os.environ.get('MM_ACCEPTANCE_COMMIT'),tree=os.environ.get('MM_ACCEPTANCE_TREE'),
            epoch_id=os.environ.get('MM_ACCEPTANCE_EPOCH'))
        OUTPUT.mkdir(parents=True,exist_ok=True,mode=0o700)
        atomic_json(OUTPUT/('last-start-failure-'+args.phase+'.json'),record)
        print(json.dumps(record))
        return 1


if __name__=='__main__':raise SystemExit(main())
