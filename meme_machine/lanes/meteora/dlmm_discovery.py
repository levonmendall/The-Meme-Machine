"""Independent frozen-source census with an on-disk first-sighting spool.

This module supplies public discovery context only. It has no entry authority.
"""
import json
import sqlite3
import threading
import time
import uuid


class CampaignDiscovery:
    def __init__(self, path, *, api, candidate, eligible, sorts, pages, page_size,
                 deadline, on_discovered=None, clock=None, wall_clock=None, wait=None, repeat=True):
        self.api=api;self.candidate=candidate;self.eligible=eligible
        self.sorts=tuple(sorts);self.pages=pages;self.page_size=page_size
        self.deadline=deadline;self.on_discovered=on_discovered
        self.repeat=repeat
        self.clock=clock or time.monotonic;self.wall_clock=wall_clock or time.time
        self.stop=threading.Event();self.done=threading.Event();self.changed=threading.Event()
        self.wait=wait or self.stop.wait
        self.deadline_wall=self.wall_clock()+max(0.,self.deadline-self.clock())
        self.lock=threading.RLock();self.invocation=str(uuid.uuid4())
        self.fatal=None;self.cycles=0;self.started=False;self.closed=False
        self.db=sqlite3.connect(str(path),check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS candidates(
                sequence INTEGER PRIMARY KEY, invocation TEXT NOT NULL,
                pool TEXT NOT NULL, observed_at REAL NOT NULL, observed_mono REAL NOT NULL,
                body TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0,
                UNIQUE(invocation,pool));
            CREATE TABLE IF NOT EXISTS segments(
                sequence INTEGER PRIMARY KEY, invocation TEXT NOT NULL,
                cycle INTEGER NOT NULL, sort TEXT NOT NULL, page INTEGER NOT NULL,
                status TEXT NOT NULL, at REAL NOT NULL, details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS shutdown(invocation TEXT PRIMARY KEY, snapshot TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS candidate_fifo ON candidates(invocation,consumed,sequence);
        ''')
        self.thread=threading.Thread(target=self._produce,name='meteora-public-census',daemon=True)

    def start(self):
        if not self.started:self.started=True;self.thread.start()
        return self

    def _segment(self,cycle,sort,page,status,**details):
        with self.lock,self.db:
            self.db.execute('INSERT INTO segments(invocation,cycle,sort,page,status,at,details) VALUES(?,?,?,?,?,?,?)',
                (self.invocation,cycle,sort,page,status,self.wall_clock(),json.dumps(details,sort_keys=True)))
        self.changed.set()

    def _produce(self):
        try:
            while not self.stop.is_set() and self.clock()<self.deadline:
                cycle_started=self.clock();cycle=self.cycles+1
                for sort in self.sorts:
                    exhausted=False
                    for page in range(1,self.pages+1):
                        if self.stop.is_set() or self.clock()>=self.deadline:
                            self._segment(cycle,sort,page,'not_observed',reason='observation_window_closed')
                            continue
                        if exhausted:
                            self._segment(cycle,sort,page,'exhausted',reason='prior_short_page')
                            continue
                        try:
                            payload=self.api('/pools',dict(page=page,page_size=self.page_size,
                                sort_by=sort,filter_by='is_blacklisted=false'))
                        except Exception as exc:
                            self._segment(cycle,sort,page,'failed',reason=type(exc).__name__)
                            continue
                        rows=payload.get('data') if isinstance(payload,dict) else None
                        if not isinstance(rows,list):
                            self._segment(cycle,sort,page,'failed',reason='api_shape')
                            continue
                        observed_at=self.wall_clock();observed_mono=self.clock()
                        if self.stop.is_set() or observed_mono>=self.deadline:
                            self._segment(cycle,sort,page,'late_response',raw_rows=len(rows))
                            continue
                        self._segment(cycle,sort,page,'acquired',raw_rows=len(rows),
                                      global_total_is_strategy_denominator=False)
                        for rank,row in enumerate(rows,1):
                            if not isinstance(row,dict) or not self.eligible(row):continue
                            pool=row.get('address')
                            if not isinstance(pool,str) or not pool:continue
                            item=self.candidate(row)
                            item.update(sources=[dict(sort=sort,rank=(page-1)*self.page_size+rank)],
                                signal_observed_at=int(observed_at),source_observed_at=observed_at,
                                discovery_sort=sort,discovery_page=page,discovery_raw_rank=rank)
                            with self.lock,self.db:
                                inserted=self.db.execute('INSERT OR IGNORE INTO candidates(invocation,pool,observed_at,observed_mono,body) VALUES(?,?,?,?,?)',
                                    (self.invocation,pool,observed_at,observed_mono,json.dumps(item,sort_keys=True))).rowcount
                                if inserted and self.on_discovered:
                                    self.on_discovered(pool,observed_at,sort,page,rank)
                            self.changed.set()
                        exhausted=len(rows)<self.page_size
                with self.lock:self.cycles=cycle
                self.changed.set()
                if not self.repeat:break
                delay=min(max(0.,60-(self.clock()-cycle_started)),max(0.,self.deadline-self.clock()))
                if delay:self.wait(delay)
        except BaseException as exc:
            with self.lock:self.fatal=type(exc).__name__
        finally:self.done.set();self.changed.set()

    def next_candidate(self):
        while True:
            self.changed.clear()
            if self.fatal:raise RuntimeError('solana_dlmm_discovery_producer:'+self.fatal)
            if self.stop.is_set() or self.clock()>=self.deadline:return None
            with self.lock,self.db:
                row=self.db.execute('SELECT sequence,body,observed_mono FROM candidates WHERE invocation=? AND consumed=0 ORDER BY sequence LIMIT 1',(self.invocation,)).fetchone()
                if row:
                    self.db.execute('UPDATE candidates SET consumed=1 WHERE sequence=?',(row[0],))
                    item=json.loads(row[1]);item['discovery_queue_wait_seconds']=max(0.,self.clock()-row[2])
                    return item
            if self.done.is_set():return None
            self.changed.wait(min(.1,max(0.,self.deadline-self.clock())))

    def snapshot(self):
        with self.lock:
            count,pending,oldest=self.db.execute('SELECT count(*),sum(consumed=0),min(CASE WHEN consumed=0 THEN observed_mono END) FROM candidates WHERE invocation=?',(self.invocation,)).fetchone()
            states=dict(self.db.execute('SELECT status,count(*) FROM segments WHERE invocation=? GROUP BY status',(self.invocation,)))
            last_cycle=[dict(sort=s,page=p,status=t,details=json.loads(d)) for s,p,t,d in self.db.execute('SELECT sort,page,status,details FROM segments WHERE invocation=? AND cycle=(SELECT max(cycle) FROM segments WHERE invocation=?) ORDER BY sequence',(self.invocation,self.invocation))]
            return dict(invocation=self.invocation,census_cycles=self.cycles,first_seen=count,pending=pending or 0,
                oldest_pending_wait_seconds=None if oldest is None else max(0.,self.clock()-oldest),
                planned_segments_per_cycle=len(self.sorts)*self.pages,segment_status_counts=states,
                latest_cycle_segments=last_cycle,producer_running=self.thread.is_alive(),producer_done=self.done.is_set(),
                fatal_error=self.fatal,spool='solana-dlmm-independent-v1-live.discovery.sqlite',
                target_universe_count=None,coverage='coverage_unknown',census_interval_seconds=60 if self.repeat else None,
                observation_deadline_at=self.deadline_wall)

    def close(self):
        if self.closed:return
        self.stop.set();self.changed.set()
        if self.started:self.thread.join(timeout=25)
        if self.thread.is_alive():raise RuntimeError('solana_dlmm_discovery_shutdown_incomplete')
        self.final_snapshot=self.snapshot()
        with self.lock,self.db:
            self.db.execute('INSERT OR REPLACE INTO shutdown VALUES(?,?)',(self.invocation,json.dumps(self.final_snapshot,sort_keys=True)))
        with self.lock:self.db.close();self.closed=True
        if self.fatal:raise RuntimeError('solana_dlmm_discovery_producer:'+self.fatal)
