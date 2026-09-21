"""Freeze explicit public campaign evidence before upload; never copy credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import time

PATTERNS={
    'pump':['pump-acceleration-natural-prospective*'],
    'meteora':['solana-dlmm-independent-v1-live*'],
    'pons':['pons-selective-continuation-v1-cohort.json','pons-selective-continuation-v1-cohort'],
    'ramses':['robinhood-ramses-extended-market-report.json','robinhood-ramses-extended-market.sqlite*',
              'robinhood-ramses-all-pool-inventory-cache.json','robinhood-ramses-extended-market.sqlite.pipeline.sqlite*'],
}


def _sqlite(path):
    try:
        with path.open('rb') as file:return file.read(16)==b'SQLite format 3\x00'
    except FileNotFoundError:return False



def _raw_copy(source,target):
    with Path(source).open('rb') as origin,Path(target).open('xb') as destination:
        length=os.fstat(origin.fileno()).st_size;remaining=length
        while remaining:
            chunk=origin.read(min(1024*1024,remaining))
            if not chunk:raise EOFError('source_shortened_during_snapshot')
            destination.write(chunk);remaining-=len(chunk)
        destination.flush();os.fsync(destination.fileno())
        after=os.fstat(origin.fileno()).st_size
    return length,after


def copy_snapshot(source,target,records):
    source=Path(source);target=Path(target)
    if source.is_symlink():raise ValueError('artifact_symlink_forbidden')
    if source.is_dir():
        target.mkdir(parents=True,exist_ok=True)
        for child in sorted(source.iterdir()):copy_snapshot(child,target/child.name,records)
        return
    # The online backup contains all committed WAL pages. SHM is a transient
    # coordination file, not ledger evidence, and must never be uploaded live.
    for suffix in ('-wal','-shm'):
        if source.name.endswith(suffix):
            base=source.with_name(source.name[:-len(suffix)])
            if _sqlite(base):
                records.append(dict(source=str(source),kind='sqlite_sidecar_in_database_backup'))
                return
    target.parent.mkdir(parents=True,exist_ok=True)
    row=dict(source=str(source),target=str(target),started_at=time.time())
    try:
        if _sqlite(source):
            begun=time.monotonic()
            def progress(status,remaining,total):
                if time.monotonic()-begun>30:raise TimeoutError('sqlite_snapshot_timeout')
            with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True,timeout=10) as origin:
                with sqlite3.connect(target) as destination:
                    origin.backup(destination,pages=256,progress=progress,sleep=.01)
                    if destination.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:
                        raise ValueError('sqlite_snapshot_integrity')
            row['kind']='sqlite_online_backup';row['integrity_verified']=True
        else:
            # An open descriptor survives an atomic replacement. Bound the read
            # to the observed length so growing raw logs cannot stall collection.
            row['source_bytes_at_open'],row['source_bytes_after_copy']=_raw_copy(source,target)
            row['kind']='exact_byte_snapshot'
        row['bytes']=target.stat().st_size
        with target.open('rb') as file:row['sha256']=hashlib.file_digest(file,'sha256').hexdigest()
    except Exception as exc:
        row['error_type']=type(exc).__name__
        if _sqlite(source):
            row['unverified_sources']=[]
            for suffix in ('','-wal','-shm'):
                raw_source=source.with_name(source.name+suffix)
                if not raw_source.exists():continue
                raw_target=target.with_name(target.name+'.unverified-source'+suffix)
                try:
                    _raw_copy(raw_source,raw_target)
                    with raw_target.open('rb') as file:checksum=hashlib.file_digest(file,'sha256').hexdigest()
                    row['unverified_sources'].append(dict(path=str(raw_target),sha256=checksum,integrity_verified=False))
                except OSError as fallback:row['raw_fallback_error']=type(fallback).__name__
        # Preserve any partial copied bytes, explicitly marked incomplete.
        if target.exists():row['partial_bytes']=target.stat().st_size
    finally:
        row['ended_at']=time.time();records.append(row)


def collect(worktrees,output,records=None):
    records=[] if records is None else records
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    seen=set()
    for lane,patterns in PATTERNS.items():
        target=output/lane;target.mkdir(exist_ok=True)
        for pattern in patterns:
            for source in sorted((Path(worktrees)/lane).glob(pattern)):
                if source in seen:continue
                seen.add(source);copy_snapshot(source,target/source.name,records)
    return records


def _worker_matches(pid,lane,folder):
    try:
        words=Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\x00')
        return (os.getpgid(pid)==pid and '-m' in words and
            words[words.index('-m')+1]=='certification.worker' and
            words[words.index('--lane')+1]==lane and
            Path(words[words.index('--output')+1]).resolve()==folder.resolve())
    except (OSError,ValueError,IndexError,UnicodeError):return False


def quiesce_cancelled(run):
    """Stop only authenticated leftover workers after the workflow was cancelled."""
    run=Path(run);result=run/'result.json';events=[]
    if not result.exists():return events
    data=json.loads(result.read_text());pending=[]
    for lane,row in data.get('lanes',{}).items():
        pid=row.get('pid')
        if type(pid) is not int or lane not in PATTERNS:continue
        if not _worker_matches(pid,lane,run/lane):continue
        event=dict(lane=lane,pid=pid,reason='workflow_cancelled',settlement_inferred=False)
        try:os.killpg(pid,signal.SIGINT);event['signal']='SIGINT';pending.append((lane,pid,event))
        except ProcessLookupError:event['already_exited']=True
        events.append(event)
    deadline=time.monotonic()+10
    while pending and time.monotonic()<deadline:
        pending=[item for item in pending if _worker_matches(item[1],item[0],run/item[0])]
        if pending:time.sleep(.1)
    for lane,pid,event in pending:
        if _worker_matches(pid,lane,run/lane):
            try:os.killpg(pid,signal.SIGKILL);event['escalated']='SIGKILL'
            except ProcessLookupError:pass
    # The existing supervisor records interrupted exits and seals its own DBs.
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        data=json.loads(result.read_text())
        if data.get('status') in ('FAILED','FINISHED') and data.get('integration_sha'):break
        time.sleep(.2)
    events.append(dict(supervisor_terminal=data.get('status') in ('FAILED','FINISHED'),
                       integration_sha=data.get('integration_sha')))
    return events


def stage(worktrees,evidence_root,output,phase,*,cancelled=False):
    root=Path(evidence_root);output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    records=[];failures=[]
    try:quiescence=quiesce_cancelled(root/f'certification-{phase}') if cancelled else []
    except Exception as exc:quiescence=[dict(error_type=type(exc).__name__,supervisor_terminal=False)]
    collect(worktrees,output/'certification-native'/phase,records)
    paths=[root/f'certification-{phase}',root/'certification-gates',
           root/'certification-preflight.json',root/'certification-contention-history.jsonl',
           root/'smoke-readiness.json']
    paths.extend(sorted(root.glob('certification-*-publisher.jsonl')))
    for source in paths:
        if source.exists():copy_snapshot(source,output/source.name,records)
    failures=[row for row in records if row.get('error_type')]
    manifest=dict(phase=phase,cancelled=cancelled,captured_at=time.time(),
        native_exposure_relabelled=False,quiescence=quiescence,files=records,
        snapshot_complete=not failures,source_files_deleted=False,
        sqlite_scope='each committed database snapshot; no global cross-database transaction claimed')
    (output/'evidence-snapshot.json').write_text(json.dumps(manifest,indent=2)+'\n')
    if failures:raise RuntimeError('artifact_snapshot_incomplete; retained all captured evidence')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--worktrees',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--evidence-root',default='.')
    parser.add_argument('--phase',choices=('smoke','hourly'))
    parser.add_argument('--cancelled',choices=('true','false'),default='false')
    args=parser.parse_args()
    if args.phase:stage(args.worktrees,args.evidence_root,args.output,args.phase,cancelled=args.cancelled=='true')
    else:collect(args.worktrees,args.output)
