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
    expired=False
    try:
        with closing(sqlite3.connect(Path(path).absolute().as_uri()+'?mode=ro',
                uri=True, timeout=.2, isolation_level=None)) as db:
            db.execute('PRAGMA query_only=ON')
            deadline = time.monotonic() + seconds
            def bounded():
                nonlocal expired
                expired=time.monotonic()>deadline
                return int(expired)
            db.set_progress_handler(bounded, 1000)
            db.execute('BEGIN')
            return dict(state='CURRENT', **callback(db))
    except sqlite3.Error as error:
        code = getattr(error, 'sqlite_errorcode', 0) & 255
        return dict(state='FAIL_CLOSED' if code in (11,26) else 'UNAVAILABLE',
                    integrity_failure=code in (11,26), sqlite_code=code,
                    observation_deadline_exhausted=code==sqlite3.SQLITE_INTERRUPT and expired)
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
    return portfolio_summary(reader,state,stamp())


def portfolio_summary(reader,state,as_of):
    """The same compact facts from a read-only replay or the existing writer."""
    if state is None:
        raise ValueError('missing_portfolio_inception')
    totals = reader._reconcile(state)
    pending = reader.db.execute('SELECT COUNT(*) FROM portfolio_native_pending').fetchone()[0]
    equity, _, unrealized = reader._values_at(state, as_of)
    from meme_machine.exact_money import amount
    return dict(epoch_id=state['receipt']['epoch_id'],
        inception_sha256=state['receipt_hash'], sequence=state['sequence'],
        journal_hash=state['journal_hash'], reconciliation='PASS',
        checks=totals['checks'], reservations=len(state['reservations']),
        pending_deliveries=pending,
        open_positions=sum(p['state']=='OPEN' for p in state['positions'].values()),
        positions_by_lane={lane:sum(p['lane']==lane and p['state']=='OPEN'
            for p in state['positions'].values()) for lane in ('pump','pons','meteora','ramses')},
        reservations_by_lane={lane:sum(r['lane']==lane for r in state['reservations'].values())
            for lane in ('pump','pons','meteora','ramses')},
        pending_by_lane={lane:reader.db.execute('SELECT COUNT(*) FROM portfolio_native_pending WHERE lane=?',(lane,)).fetchone()[0]
            for lane in ('pump','pons','meteora','ramses')},
        realized_pnl=amount(totals['realized']), marked_equity=amount(equity) if equity is not None else None,
        unrealized_pnl=amount(unrealized) if unrealized is not None else None)


def projection_allowed(result):
    return (result.get('sqlite_code')==sqlite3.SQLITE_CANTOPEN or
        result.get('sqlite_code')==sqlite3.SQLITE_INTERRUPT and result.get('observation_deadline_exhausted') is True)


def fresh_health(root,health):
    """Refresh only a bounded read-only projection from the same epoch."""
    try:
        latest=read_json(Path(root)/'health.json')
        return latest if isinstance(latest,dict) and latest.get('epoch_id')==health.get('epoch_id') else {}
    except (OSError,ValueError,TypeError):return health


def observed_portfolio(root,health,now=None):
    from meme_machine.shared_capital.runtime import selected
    from meme_machine.shared_capital.reporting import observe
    try:shared=selected(Path(root)/'portfolio.sqlite')
    except (OSError,ValueError,RuntimeError,sqlite3.Error) as error:
        return dict(state='FAIL_CLOSED',reason=str(error))
    if shared:return database(shared,observe)
    result=database(Path(root)/'portfolio.sqlite',portfolio)
    if not projection_allowed(result):return result
    if now is None:
        # Diagnostic collection and the bounded SQL attempt can age the copy
        # captured at sample start. Re-read the existing owner's atomic facts;
        # neither the projection TTL nor its validity window is extended.
        health=fresh_health(root,health);now=time.time()
    # A genuinely read-only mount cannot create missing WAL support files
    # between short-lived writer connections. Use the existing owner's bounded
    # atomic health projection; never mark the live database immutable, write
    # support files, acquire its economic lock, or suppress an integrity error.
    # The same fallback covers only this observer's own bounded-read timeout.
    try:
        row=health['portfolio_observation']
        from meme_machine.portfolio_accounting import _stamp
        from meme_machine.exact_money import money
        if (row['state']!='CURRENT' or row['epoch_id']!=health['epoch_id'] or
                not 0<=now-row['timestamp']<=15 or
                not now<=_stamp(row['valid_until']) or
                row['reconciliation']!='PASS' or set(row['checks'])!={
                    'lane_realized_less_shared_costs','remaining_basis','cash_basis_conservation','cost_attribution'} or
                any(v is not True for v in row['checks'].values())):
            return result
        for key in ('realized_pnl','marked_equity','unrealized_pnl'):
            if row[key] is not None:money(row[key])
        for key in ('sequence','reservations','pending_deliveries','open_positions'):
            if type(row[key]) is not int or row[key]<0:return result
        if (set(row['positions_by_lane'])!={'pump','pons','meteora','ramses'} or
                any(type(n) is not int or n<0 for n in row['positions_by_lane'].values()) or
                sum(row['positions_by_lane'].values())!=row['open_positions']):return result
        keys=('state','timestamp','valid_until','epoch_id','inception_sha256','sequence',
            'journal_hash','reconciliation','checks','reservations','pending_deliveries',
            'open_positions','positions_by_lane','realized_pnl','marked_equity','unrealized_pnl')
        keys=keys+('reservations_by_lane','pending_by_lane') if all(k in row for k in ('reservations_by_lane','pending_by_lane')) else keys
        if any(not re.fullmatch('[a-z_]{1,64}',key) for key in row['checks']):return result
        for key in ('inception_sha256','journal_hash'):
            if not isinstance(row[key],str) or not re.fullmatch('[0-9a-f]{64}',row[key]):return result
        return dict({key:row[key] for key in keys},
            observation_source='canonical_health_projection',live_sqlite_code=result['sqlite_code'])
    except (KeyError,TypeError,ValueError):return result


def observed_provider(root,health,provider_name,now=None):
    result=database(Path(root)/'shared'/f'{provider_name}-provider.sqlite',
        lambda db:provider(db,provider_name=='solana'))
    if not projection_allowed(result):return result
    if now is None:health=fresh_health(root,health);now=time.time()
    try:
        from meme_machine.portfolio_accounting import _stamp
        row=health['providers'][provider_name]
        if not 0<=now-_stamp(health['at'])<=15 or row['state']!='CURRENT':return result
        if type(row['queue_depth']) is not int or row['queue_depth']<0:return result
        wait=row['oldest_wait_seconds']
        if type(wait) not in (int,float) or not math.isfinite(wait) or wait<0:return result
        projected=dict(state='CURRENT',queue_depth=row['queue_depth'],oldest_wait_seconds=wait,
            observation_source='canonical_health_projection',live_sqlite_code=result['sqlite_code'])
        if provider_name=='solana':
            projected['pressure']=[]
            for entry in (row.get('pressure') or [])[:8]:
                if all(type(entry.get(k)) in (int,float) and math.isfinite(entry[k]) and entry[k]>=0
                       for k in ('grants','rate_errors','cooldown_seconds')):
                    projected['pressure'].append(dict(provider='solana',**{k:entry[k] for k in
                        ('grants','rate_errors','cooldown_seconds')}))
        else:
            projected['usage']=[]
            metrics={'batch_members','batch_transports','completed_transport_attempts','logical_rpc_calls',
                'physical_http_requests','provider_queue_wait_seconds','responses_429','retries','transport_latency_seconds'}
            methods={'eth_call','eth_chainId','eth_getBlockByNumber','eth_getCode','eth_getLogs',
                'eth_getTransactionReceipt','eth_gasPrice','eth_getStorageAt','eth_getBalance'}
            for entry in (row.get('usage') or [])[:128]:
                metric=entry.get('metric','');value=entry.get('value')
                if (entry.get('lane') in ('pump','pons','meteora','ramses') and isinstance(metric,str) and
                        (metric in metrics or metric.removeprefix('method:') in methods or
                         re.fullmatch('failure:provider_rpc_-?[0-9]{1,10}',metric)) and
                        type(value) in (int,float) and math.isfinite(value) and value>=0):
                    projected['usage'].append({k:entry[k] for k in ('lane','metric','value')})
        return projected
    except (KeyError,TypeError,ValueError):return result


def learning_usage(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='learning_usage_v1'").fetchone():
        return dict(bytes=0,rows=0)
    rows,body_bytes=db.execute('SELECT records,bytes FROM learning_usage_v1 WHERE id=1').fetchone()
    return dict(bytes=body_bytes,rows=rows)


def owner_learning_observation(root):
    """Bounded read-only metadata on the existing runtime's writable mount.

    It may create ordinary SQLite WAL support files, which the independent
    observer's read-only mount cannot create. Economic tables stay query-only.
    No provider call, economic lock, or separate writer is involved.
    """
    deadline=time.monotonic()+.25;rows=body_bytes=files=0;complete=True
    for p in Path(root).rglob('*.sqlite*'):
        from meme_machine.runtime.operating_families import PAUSED_LANES
        if p.relative_to(root).parts[0] in PAUSED_LANES:continue
        if time.monotonic()>=deadline:complete=False;break
        if p.suffix not in ('.sqlite','.sqlite3'):continue
        files+=1
        if files>64 or time.monotonic()>=deadline:complete=False;break
        if p.is_symlink():complete=False;continue
        value=database(p,learning_usage,seconds=max(.001,deadline-time.monotonic()))
        complete &= value.get('state')=='CURRENT'
        rows+=value.get('rows',0);body_bytes+=value.get('bytes',0)
    return dict(timestamp=time.time(),learning_rows=rows,learning_store_bytes=body_bytes,
        learning_measurement_complete=complete)


def evidence(db):
    from meme_machine.runtime.operating_families import active_scope_sql
    health = {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM service_health LIMIT 128')}
    result = {key:numeric(health.get(key)) for key in
        ('heartbeat', 'phase', 'pid', 'repair_http', 'ipc', 'owner_scheduler',
         'storage', 'storage_maintenance', 'subscriptions','native_streams')}
    result['stream'] = numeric({k:v for k,v in health.get('ipc',{}).items() if k.startswith('stream.')})
    result['frontiers'] = [dict(scope=s, slot=slot, updated=at)
        for s,slot,at in db.execute("SELECT scope,slot,updated FROM cursors WHERE scope IN ('program:pump','program:pumpswap')")]
    result['all_frontiers'] = dict(zip(('scopes','lowest_slot','highest_slot','oldest_update','newest_update'),
        db.execute('SELECT COUNT(*),MIN(slot),MAX(slot),MIN(updated),MAX(updated) FROM cursors').fetchone()))
    result['counters'] = {k:v for k,v in db.execute('SELECT key,value FROM counters LIMIT 128')}
    count,created,pages,attempts = db.execute('SELECT COUNT(*),MIN(created),SUM(pages),SUM(attempts) FROM gaps WHERE repaired IS NULL').fetchone()
    result['repair_backlog'] = dict(open_gaps=count, oldest_created=created, pages=pages, attempts=attempts)
    # A sealed historical gap remains unavailable; it is not a failure of the
    # current stream unless active work or fresh coverage still references it.
    required,oldest=db.execute('''SELECT COUNT(*),MIN(g.created) FROM gaps g
        WHERE '''+active_scope_sql('g.scope',production=True)+''' AND g.repaired IS NULL AND (g.hi IS NULL
        OR EXISTS(SELECT 1 FROM interests i WHERE i.scope=g.scope AND i.active=1 AND i.lower_slot<=g.hi)
        OR EXISTS(SELECT 1 FROM coverage c WHERE c.scope=g.scope AND c.available>=? AND c.lo<=g.hi AND c.hi>=g.lo))''',
        (time.time()-180,)).fetchone()
    result['repair_backlog'].update(required_gaps=required,oldest_required_created=oldest)
    result['maintenance_progress'] = [dict(scope=s,side=side,at=at,units=units,record_at=record_at,records=records)
        for s,side,at,units,record_at,records in db.execute("SELECT * FROM maintenance_progress WHERE scope IN ('program:pump','program:pumpswap')")]
    result['all_maintenance_progress'] = [dict(side=side,scopes=scopes,units=units,records=records,last_progress=at)
        for side,scopes,units,records,at in db.execute('SELECT side,COUNT(*),SUM(units),SUM(records),MAX(at) FROM maintenance_progress GROUP BY side')]
    result['archive'] = dict(zip(('files', 'bytes', 'records'), db.execute('SELECT COUNT(*),SUM(bytes),SUM(records) FROM archives').fetchone()))
    return result


def provider_queue(db,solana):
    """Operational readers do not inherit the producer's phase environment."""
    from meme_machine.runtime.operating_families import active_scope_sql
    if solana and 'lane' in {r[1] for r in db.execute('PRAGMA table_info(queue)')}:
        where=active_scope_sql('lane',production=True)
    elif not solana and db.execute("SELECT 1 FROM sqlite_master WHERE name='queue_meta'").fetchone():
        where="id IN (SELECT q.id FROM queue q LEFT JOIN queue_meta m ON m.id=q.id WHERE "+active_scope_sql("COALESCE(m.lane,'shared')",production=True)+")"
    else:where='1=1'
    return db.execute('SELECT COUNT(*),MIN(created) FROM queue WHERE '+where).fetchone()


def provider(db, solana):
    depth,oldest = provider_queue(db,solana)
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
            from meme_machine.runtime.operating_families import PAUSED_LANES
            if p.relative_to(root).parts[0] in PAUSED_LANES:continue
            if time.monotonic()>=learning_deadline:
                learning_complete=False;continue
            facts=database(p,learning_usage,seconds=max(.01,learning_deadline-time.monotonic()))
            learning_complete &= facts.get('state')=='CURRENT'
            learning_bytes+=facts.get('bytes',0);learning_rows+=facts.get('rows',0)
    value['storage_totals']=dict(state_root_bytes=state_bytes,archive_bytes=archive_bytes,
        learning_store_bytes=learning_bytes,learning_rows=learning_rows,
        learning_measurement_complete=learning_complete,files=total)
    health={}
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
    cached=health.get('learning_observation') or {}
    if (not learning_complete and cached.get('learning_measurement_complete') is True and
            type(cached.get('timestamp')) in (int,float) and math.isfinite(cached['timestamp']) and
            0<=time.time()-cached.get('timestamp',0)<=15 and
            all(type(cached.get(key)) is int and cached[key]>=0
                for key in ('learning_rows','learning_store_bytes'))):
        value['storage_totals'].update({key:cached[key] for key in
            ('learning_rows','learning_store_bytes','learning_measurement_complete')})
        value['storage_totals']['learning_observation_source']='canonical_health_projection'
    directional_reports(root,value.setdefault('six_regimes',{}))
    value['portfolio'] = observed_portfolio(root,health)
    value['solana'] = database(root/'shared/solana-evidence.sqlite', evidence)
    for name in ('solana','robinhood'):
        value[name+'_provider'] = observed_provider(root,health,name)
    return value


def check_next_database(root,folder,value):
    """Rotate bounded read-only quick checks across every SQLite file."""
    path=Path(folder)/'database-integrity.json'
    try:previous=read_json(path,limit=SAMPLE_BOUND)
    except (OSError,ValueError):previous={}
    from meme_machine.runtime.operating_families import PAUSED_LANES
    names=sorted(name for name in value['storage'] if name.endswith(('.sqlite','.sqlite3')) and Path(name).parts[0] not in PAUSED_LANES)
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
