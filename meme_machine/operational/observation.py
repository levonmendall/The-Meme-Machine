"""Bounded read-only PAPER observations; no runtime controls or provider access."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import time

INTERVAL = 15
SAMPLE_BOUND = 32768
RETENTION_BYTES = 512 * 1024**2
STATES = frozenset(('CURRENT', 'UNAVAILABLE', 'STALE', 'FAIL_CLOSED', 'DEGRADED',
    'ACTIVE', 'WARMING', 'STARTING', 'RECONCILING', 'MANAGING', 'DISCOVERING',
    'STOPPED', 'VALUATION_UNAVAILABLE', 'OWNER_ACTION_REQUIRED', 'SELF_HEALING_EVENT'))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    body = json.dumps(value, sort_keys=True, allow_nan=False)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as stream:
        stream.write(body + '\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, path)


def read_json(path, limit=16*1024**2):
    with Path(path).open('rb') as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError('observation_input_bound')
    return json.loads(body)


def numeric(value, depth=0):
    """Never copy provider URLs, credentials, payloads, or arbitrary error text."""
    if depth > 5:
        return None
    if isinstance(value, (bool, int)) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value if value in STATES else None
    if isinstance(value, dict):
        result = {}
        for k,v in list(value.items())[:128]:
            if not isinstance(k,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',k):
                continue
            if isinstance(v,(dict,bool,int,float)) or isinstance(v,str) and v in STATES:
                result[k] = numeric(v,depth+1)
        return result
    return None


def database(path, callback, seconds=1):
    if not Path(path).is_file():
        return {'state': 'UNAVAILABLE'}
    try:
        with closing(sqlite3.connect(Path(path).absolute().as_uri()+'?mode=ro',
                uri=True, timeout=.2, isolation_level=None)) as db:
            db.execute('PRAGMA query_only=ON')
            deadline = time.monotonic() + seconds
            db.set_progress_handler(lambda: int(time.monotonic()>deadline), 1000)
            db.execute('BEGIN')
            return dict(state='CURRENT', **callback(db))
    except sqlite3.Error as error:
        code = getattr(error, 'sqlite_errorcode', 0) & 255
        return dict(state='FAIL_CLOSED' if code in (11,26) else 'UNAVAILABLE',
                    integrity_failure=code in (11,26), sqlite_code=code)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        failure=type(error).__name__=='PortfolioIntegrityError'
        return dict(state='FAIL_CLOSED' if failure else 'UNAVAILABLE',
                    reconciliation_failure=failure)


def portfolio(db):
    # Allocate only the pure replay reader. Never call the writer constructor,
    # configure schemas, acquire its lock, checkpoint, or publish a projection.
    from meme_machine.portfolio_accounting import PortfolioAccounting
    reader = object.__new__(PortfolioAccounting); reader.db = db
    state = reader._replay()
    if state is None:
        raise ValueError('missing_portfolio_inception')
    totals = reader._reconcile(state)
    pending = db.execute('SELECT COUNT(*) FROM portfolio_native_pending').fetchone()[0]
    equity, _, unrealized = reader._values_at(state, stamp())
    return dict(epoch_id=state['receipt']['epoch_id'],
        inception_sha256=state['receipt_hash'], sequence=state['sequence'],
        journal_hash=state['journal_hash'], reconciliation='PASS',
        checks=totals['checks'], reservations=len(state['reservations']),
        pending_deliveries=pending,
        open_positions=sum(p['state']=='OPEN' for p in state['positions'].values()),
        positions_by_lane={lane:sum(p['lane']==lane and p['state']=='OPEN'
            for p in state['positions'].values()) for lane in ('pump','pons','meteora','ramses')},
        realized_pnl=str(totals['realized']), marked_equity=str(equity) if equity is not None else None,
        unrealized_pnl=str(unrealized) if unrealized is not None else None)


def evidence(db):
    health = {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM service_health LIMIT 128')}
    result = {key:numeric(health.get(key)) for key in
        ('heartbeat', 'phase', 'pid', 'repair_http', 'ipc', 'owner_scheduler',
         'storage', 'storage_maintenance', 'subscriptions')}
    result['stream'] = numeric({k:v for k,v in health.get('ipc',{}).items() if k.startswith('stream.')})
    result['frontiers'] = [dict(scope=s, slot=slot, updated=at)
        for s,slot,at in db.execute("SELECT scope,slot,updated FROM cursors WHERE scope IN ('program:pump','program:pumpswap','program:meteora')")]
    result['all_frontiers'] = dict(zip(('scopes','lowest_slot','highest_slot','oldest_update','newest_update'),
        db.execute('SELECT COUNT(*),MIN(slot),MAX(slot),MIN(updated),MAX(updated) FROM cursors').fetchone()))
    result['counters'] = {k:v for k,v in db.execute('SELECT key,value FROM counters LIMIT 128')}
    count,created,pages,attempts = db.execute('SELECT COUNT(*),MIN(created),SUM(pages),SUM(attempts) FROM gaps WHERE repaired IS NULL').fetchone()
    result['repair_backlog'] = dict(open_gaps=count, oldest_created=created, pages=pages, attempts=attempts)
    result['maintenance_progress'] = [dict(scope=s,side=side,at=at,units=units,record_at=record_at,records=records)
        for s,side,at,units,record_at,records in db.execute("SELECT * FROM maintenance_progress WHERE scope IN ('program:pump','program:pumpswap','program:meteora')")]
    result['all_maintenance_progress'] = [dict(side=side,scopes=scopes,units=units,records=records,last_progress=at)
        for side,scopes,units,records,at in db.execute('SELECT side,COUNT(*),SUM(units),SUM(records),MAX(at) FROM maintenance_progress GROUP BY side')]
    result['archive'] = dict(zip(('files', 'bytes', 'records'), db.execute('SELECT COUNT(*),SUM(bytes),SUM(records) FROM archives').fetchone()))
    return result


def provider(db, solana):
    depth,oldest = db.execute('SELECT COUNT(*),MIN(created) FROM queue').fetchone()
    value = dict(queue_depth=depth, oldest_wait_seconds=max(0,time.monotonic()-oldest) if oldest is not None else 0)
    if solana:
        value['pressure'] = [dict(provider=p,grants=g,rate_errors=e,cooldown_seconds=max(0,c-time.monotonic()))
            for p,_,c,g,e in db.execute('SELECT * FROM pressure LIMIT 8')]
    else:
        value['usage'] = [dict(lane=l,metric=m,value=v)
            for l,m,v in db.execute('SELECT lane,metric,SUM(value) FROM provider_usage GROUP BY lane,metric LIMIT 128')]
        value['cooldown_seconds'] = max([0]+[max(0,c-time.monotonic()) for (c,) in db.execute('SELECT cooldown FROM limits LIMIT 8')])
    return value


def host(root):
    memory = {r.split(':',1)[0]:int(r.split()[1])*1024
        for r in Path('/proc/meminfo').read_text().splitlines() if r.startswith(('MemTotal:', 'MemAvailable:', 'SwapTotal:', 'SwapFree:'))}
    cpu = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:]]
    mounts = {}
    for path in ('/', str(root)):
        fs = os.statvfs(path)
        total=fs.f_blocks*fs.f_frsize;used=(fs.f_blocks-fs.f_bfree)*fs.f_frsize
        mounts[path] = dict(free_bytes=fs.f_bavail*fs.f_frsize, total_bytes=total,
                            used_bytes=used,percent_used=100*used/total if total else 100)
    properties = subprocess.run(['systemctl','show','meme-machine-paper.service',
        '-p','ActiveState','-p','SubState','-p','MainPID','-p','NRestarts','-p','ControlGroup'],
        capture_output=True, text=True, check=True, timeout=3).stdout
    service = dict(line.split('=',1) for line in properties.splitlines() if '=' in line)
    processes = []
    group = Path('/sys/fs/cgroup')/service.get('ControlGroup','').lstrip('/')/'cgroup.procs'
    if service.get('ControlGroup') and group.exists():
        for pid in group.read_text().split()[:64]:
            try:
                rows = Path('/proc/'+pid+'/status').read_text().splitlines()
                fields = {r.split(':',1)[0]:r.split(':',1)[1].strip() for r in rows}
                processes.append(dict(pid=int(pid),state=fields['State'].split()[0],
                    rss_bytes=int(fields.get('VmRSS','0').split()[0])*1024,
                    threads=int(fields.get('Threads',0))))
            except (OSError, ValueError, KeyError):
                continue
    observers={}
    for name in ('meme-machine-observer','meme-machine-monitor','meme-machine-metrics','meme-machine-uptime-health','do-agent'):
        folder=Path('/sys/fs/cgroup/system.slice')/(name+'.service')
        try:
            stats=dict(line.split() for line in (folder/'cpu.stat').read_text().splitlines())
            observers[name]=dict(cpu_usage_ns=int(stats['usage_usec'])*1000,
                                 memory_bytes=int((folder/'memory.current').read_text()))
        except (OSError,ValueError,KeyError):observers[name]=dict(unavailable=True)
    return dict(memory=memory,cpu_ticks=cpu,load=os.getloadavg(),disks=mounts,
                service=service,processes=processes,observation_stack=observers,cpu_count=os.cpu_count())


def directional_reports(root, regimes, now=None):
    """Read the existing bounded native projections, including each Survivor."""
    now=time.time() if now is None else now
    paths={'pump':'pump/pump-acceleration-natural-prospective.json',
        'pons':'pons/pons-selective-continuation-v1-cohort/cohort-progress.json'}
    for lane,path in paths.items():
        current=regimes.setdefault(lane.title()+' Current',dict(lane=lane))
        survivor=regimes.setdefault(lane.title()+' Survivor',dict(lane=lane))
        try:
            p=Path(root)/path
            if p.is_symlink():raise ValueError('observation_report_symlink')
            report=read_json(p)
            age=max(0,now-p.stat().st_mtime)
            if not isinstance(report,dict):raise ValueError('observation_report_shape')
            status='CURRENT' if age<=60 else 'STALE'
            current.update(report_state=status,report_age_seconds=age,
                machinery=numeric({key:report.get(key) for key in
                    ('counts','summary','sequencer_discovery','evidence_queue',
                     'evidence_acquisition','active_provider','active_discovery_provider',
                     'publication','full_evidence_attempts','canonical_discovery_cursor',
                     'persisted_candidate_rows','persisted_qualifiers','capacity_censored')}))
            details=report.get('survivor')
            survivor.update(report_state=status,report_age_seconds=age,
                observation_state='CURRENT' if isinstance(details,dict) and details else 'UNAVAILABLE',
                boundary_present=bool(details.get('last_boundary')) if isinstance(details,dict) else False,
                machinery=numeric(details) if isinstance(details,dict) else {})
        except (OSError,ValueError,KeyError,TypeError):
            current.update(report_state='UNAVAILABLE')
            survivor.update(report_state='UNAVAILABLE',observation_state='UNAVAILABLE')


def collect(root):
    root = Path(root)
    value = dict(at=stamp(), timestamp=time.time(), host=host(root), storage={}, lanes={})
    total=0;state_bytes=0;archive_bytes=0;learning_bytes=0;learning_rows=0
    learning_deadline=time.monotonic()+2
    learning_complete=True
    for p in root.rglob('*'):
        if not p.is_file() or p.is_symlink():
            continue
        total += 1
        if total > 10000:
            raise ValueError('state_file_observation_bound')
        size=p.stat().st_size;state_bytes+=size
        if any(part.endswith('.archive') for part in p.relative_to(root).parts[:-1]):archive_bytes+=size
        if '.sqlite' in p.name:
            value['storage'][str(p.relative_to(root))] = size
        if p.name.endswith(('.sqlite','.sqlite3')):
            if time.monotonic()>=learning_deadline:
                learning_complete=False;continue
            def learning(db):
                if not db.execute("SELECT 1 FROM sqlite_master WHERE name='learning_usage_v1'").fetchone():
                    return dict(bytes=0,rows=0)
                rows,body_bytes=db.execute('SELECT records,bytes FROM learning_usage_v1 WHERE id=1').fetchone()
                return dict(bytes=body_bytes,rows=rows)
            facts=database(p,learning,seconds=max(.01,learning_deadline-time.monotonic()))
            learning_complete &= facts.get('state')=='CURRENT'
            learning_bytes+=facts.get('bytes',0);learning_rows+=facts.get('rows',0)
    value['storage_totals']=dict(state_root_bytes=state_bytes,archive_bytes=archive_bytes,
        learning_store_bytes=learning_bytes,learning_rows=learning_rows,
        learning_measurement_complete=learning_complete,files=total)
    try:
        health = read_json(root/'health.json')
        value['health_at'] = health['at']; value['epoch_id'] = health['epoch_id']
        for lane,row in health['lanes'].items():
            value['lanes'][lane] = numeric(row)
        value['six_regimes'] = {name:dict(lane=lane,phase=value['lanes'].get(lane,{}).get('phase'),
            reconciled=value['lanes'].get(lane,{}).get('reconciled')) for name,lane in
            (('Pump Current','pump'),('Pump Survivor','pump'),('Pons Current','pons'),
             ('Pons Survivor','pons'),('Meteora','meteora'),('Ramses','ramses'))}
    except (OSError, ValueError, KeyError, TypeError):
        value['health_unavailable'] = True
    directional_reports(root,value.setdefault('six_regimes',{}))
    value['portfolio'] = database(root/'portfolio.sqlite', portfolio)
    value['solana'] = database(root/'shared/solana-evidence.sqlite', evidence)
    for name in ('solana','robinhood'):
        value[name+'_provider'] = database(root/'shared'/f'{name}-provider.sqlite', lambda db:provider(db,name=='solana'))
    return value


def check_next_database(root,folder,value):
    """Rotate bounded read-only quick checks across every SQLite file."""
    path=Path(folder)/'database-integrity.json'
    try:previous=read_json(path,limit=SAMPLE_BOUND)
    except (OSError,ValueError):previous={}
    names=sorted(name for name in value['storage'] if name.endswith(('.sqlite','.sqlite3')))
    if not names:return
    key=min(names,key=lambda name:previous.get(name,{}).get('timestamp',0))
    def check(db):
        rows=db.execute('PRAGMA quick_check(1)').fetchall()
        return dict(integrity_failure=rows!=[('ok',)])
    row=database(Path(root)/key,check)
    row['timestamp']=time.time();previous[key]=row
    previous={key:previous[key] for key in names if key in previous}
    atomic_json(path,previous);value['database_integrity']=previous


def append_sample(folder, value):
    body = json.dumps(value,sort_keys=True,allow_nan=False).encode()+b'\n'
    if len(body)>SAMPLE_BOUND:
        raise ValueError('observation_sample_bound')
    folder = Path(folder)
    with (folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H')+'.jsonl')).open('ab') as stream:
        stream.write(body);stream.flush();os.fsync(stream.fileno())
    atomic_json(folder/'latest.json',value)
    files = sorted(folder.glob('*.jsonl'), reverse=True); retained=0
    for p in files:
        retained += p.stat().st_size
        if retained>RETENTION_BYTES or time.time()-p.stat().st_mtime>7*86400:
            p.unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root', required=True)
    parser.add_argument('--output', default='/var/lib/meme-machine-observer')
    parser.add_argument('--once', action='store_true')
    args=parser.parse_args();folder=Path(args.output)
    root=Path(args.state_root).resolve()
    if folder.resolve()==root or root in folder.resolve().parents:
        parser.error('observations must be outside economic state')
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)
    while not stopping:
        try:
            value=collect(root);check_next_database(root,folder,value);append_sample(folder,value)
            (folder/'observer-error.json').unlink(missing_ok=True)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            atomic_json(folder/'observer-error.json',dict(at=stamp(),state='UNAVAILABLE',observation_failure=True))
        if args.once:
            return 0 if not (folder/'observer-error.json').exists() else 1
        deadline=time.monotonic()+INTERVAL
        while not stopping and time.monotonic()<deadline:time.sleep(min(.5,max(0,deadline-time.monotonic())))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
