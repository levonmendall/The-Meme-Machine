"""Once-only material start and raw preservation; no result interpretation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tarfile
import time

ROOT=Path('/workspace/The-Meme-Machine')
HERE=ROOT/'diagnostics/stage-e-final-capacity-screen'
WORK=Path('/workspace/stage-e-screen-work')
def sha(data):return hashlib.sha256(data).hexdigest()
def write(path,row):
    with path.open('w') as stream:
        json.dump(row,stream,indent=2,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--arm',required=True,choices=('control','treatment'))
    a=parser.parse_args();arm=a.arm
    pre=HERE/'PREDECLARATION.json';p=json.loads(pre.read_bytes())
    receipt=json.loads((HERE/('EXECUTION_RECEIPT_'+arm.upper()+'.json')).read_bytes())
    assert receipt['predeclaration_sha256']==sha(pre.read_bytes())
    assert receipt['arm']==arm and receipt['no_tuning_since_predeclaration'] is True
    readback=json.loads((HERE/'PREDECLARATION_READBACK.json').read_bytes())
    assert readback['independent_remote_readback'] is True
    assert readback['predeclaration_json_sha256']==sha(pre.read_bytes())
    for name,want in p['screen_files'].items():assert sha((HERE/name).read_bytes())==want,name
    number=1 if arm=='control' else 2
    if number==2:
        previous=json.loads((HERE/'AFTER_CONTROL.json').read_bytes())
        assert previous['budget_consumed']==1 and previous['raw_preserved'] is True
    root=WORK/'runs'/p['execution_key']/arm
    root.mkdir(parents=True,exist_ok=False)
    temp=root/'temp';temp.mkdir()
    assembly=WORK/(arm+'-assembly')
    child_env={'PATH':'/workspace/stage-e-runtime/bin:/usr/bin:/bin','LANG':'C.UTF-8','TZ':'UTC',
        'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','TMPDIR':str(temp),
        'MM_SCREEN_PREDECLARATION':str(pre),'MM_SCREEN_ARM':arm,'MM_SCREEN_ATTEMPT':'1',
        'MM_SCREEN_SOURCE':str(assembly/'source'),'MM_SCREEN_ASSEMBLY':str(assembly),
        'MM_SCREEN_FIREWALL_DIR':str(temp/'firewall')}
    launch={'arm':arm,'attempt':1,'run_id':p['execution_key'],'budget_id':p['budget']['capacity_screen']['id'],
        'budget_consumed':number,'budget_remaining':2-number,'historical_budget_consumed':6,
        'identity':p['arms'][arm],'predeclaration_sha256':sha(pre.read_bytes()),
        'utc_start':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'hostname':socket.gethostname(),
        'no_tuning_since_predeclaration':True,'material_start_requested':True}
    # Durable before Popen. A failed launch still cannot be replaced.
    write(root/'STARTED.json',launch)
    write(HERE/'BUDGET_CURRENT.json',{'capacity_consumed':number,'capacity_ceiling':2,
        'historical_consumed':6,'historical_ceiling':6,'started_arm':arm,'no_retry':True})
    proc=None;forced=False;interrupted=False;start=time.monotonic();code=None
    def interrupted_handler(signum,frame):
        raise InterruptedError('execution_controller_signal:'+str(signum))
    signal.signal(signal.SIGTERM,interrupted_handler);signal.signal(signal.SIGINT,interrupted_handler)
    try:
        with (root/'process.log').open('w') as log:
            proc=subprocess.Popen(['/workspace/stage-e-runtime/bin/python','-I','-B',str(HERE/'harness.py'),
                '--output',str(root/'raw')],cwd=root,env=child_env,stdout=log,stderr=subprocess.STDOUT,
                start_new_session=True)
            launch['pid']=proc.pid;write(root/'STARTED.json',launch)
            try:code=proc.wait(timeout=660)
            except subprocess.TimeoutExpired:
                forced=True;os.killpg(proc.pid,signal.SIGTERM)
                try:code=proc.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);code=proc.wait(timeout=10)
    except BaseException as exc:
        interrupted=True
        write(root/'CONTROLLER_ERROR.json',{'type':type(exc).__name__,'message':str(exc)})
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid,signal.SIGKILL);code=proc.wait(timeout=10)
    residual=False
    if proc is not None:
        try:os.killpg(proc.pid,0)
        except ProcessLookupError:pass
        else:residual=True;os.killpg(proc.pid,signal.SIGKILL)
    finished=dict(launch,returncode=code,elapsed=time.monotonic()-start,forced=forced,
        controller_interrupted=interrupted,residual_process_group=residual,
        utc_end=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    write(root/'FINISHED.json',finished)
    inventory={}
    for path in sorted(root.rglob('*')):
        if path.is_file() and not path.is_symlink():
            inventory[str(path.relative_to(root))]={'sha256':sha(path.read_bytes()),'bytes':path.stat().st_size}
    write(root/'RAW_FILE_DIGESTS.json',inventory)
    # Runtime SQLite databases and raw payload archives remain outside Git per AGENTS.md.
    # All read-only telemetry, raw logs, worker receipts and digests are published.
    archive=HERE/(arm.upper()+'_RAW_EVIDENCE.tar.gz')
    with tarfile.open(archive,'x:gz') as tar:
        for path in sorted(root.rglob('*')):
            if path.is_file() and not path.is_symlink() and 'runtime' not in path.relative_to(root).parts:
                tar.add(path,arcname=str(path.relative_to(root)),recursive=False)
    after={'arm':arm,'budget_consumed':number,'budget_ceiling':2,'historical_budget_consumed':6,
        'raw_preserved':True,'raw_archive':archive.name,'raw_archive_sha256':sha(archive.read_bytes()),
        'raw_local_directory':str(root),'raw_inventory_sha256':sha((root/'RAW_FILE_DIGESTS.json').read_bytes()),
        'runtime_database_and_payload_archives_retained_locally':True,'execution':finished,
        'result_interpreted':False,'retry_authorized':False}
    write(HERE/('AFTER_'+arm.upper()+'.json'),after)
    print(json.dumps(after,sort_keys=True))

if __name__=='__main__':main()
