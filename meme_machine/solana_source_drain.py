"""Ownership helpers for the existing bounded source queues, not a second spool.

Closing admission and finishing a queue are separate events.  A received handler
may still be putting its last frame after the stop event has been set.
"""
import asyncio
import json
import os
import hashlib
import threading
import time

CONTROL_RECOVERY_KEY='source_control_recovery'
HANDLER_RECOVERY_KEY='source_handler_recovery'


class HandlerLedger:
    """Only active/interrupted callbacks, not another market-event journal.

    Successful callbacks are counted and removed. Returning a callback is not
    a durable commit: queue and session fences remain independently mandatory.
    """
    maximum_records=64
    maximum_bytes=48*1024

    def __init__(self,run):
        self.run=run;self.accepted=0;self.returned=0;self.records={};self.tasks={}
        self.valid=True;self.pid=os.getpid();self.native_thread_id=threading.get_native_id()

    def accept(self,stream,session,transport,family,kind,seen,*,slot=None,identity=None,scopes=()):
        from .solana_evidence_plane import EvidenceUnavailable
        if len(self.records)>=self.maximum_records or (identity is not None and (not isinstance(identity,str) or len(identity)>128)):
            self.valid=False;raise EvidenceUnavailable('source_handler_record_bound')
        self.accepted+=1;number=self.accepted
        row=dict(id=number,stream=stream,session=session,transport=transport,
            family=family,kind=kind,slot=slot,identity=identity,seen=seen,
            scope_hash=self.scope_hash(scopes),scope_count=len(set(scopes)),
            started_monotonic=time.monotonic(),phase='HANDLER',state='ACTIVE')
        self.records[number]=row;self.tasks[asyncio.current_task()]=number
        return number

    def phase(self,phase,**facts):
        if not isinstance(phase,str) or not phase.isidentifier() or len(phase)>40 or set(facts)-{'slot','identity','scope'}:
            raise ValueError('source_handler_phase')
        if 'identity' in facts and (not isinstance(facts['identity'],str) or len(facts['identity'])>128):raise ValueError('source_handler_identity')
        if 'scope' in facts:
            scope=facts.pop('scope');facts.update(scope_hash=self.scope_hash((scope,)),scope_count=1)
        number=self.tasks.get(asyncio.current_task())
        if number is not None:self.records[number].update(phase=phase,**facts)

    @staticmethod
    def scope_hash(scopes):
        return hashlib.sha256(json.dumps(sorted(set(scopes)),separators=(',',':')).encode()).hexdigest()

    def finish(self,number):
        self.records.pop(number);self.returned+=1
        self.tasks.pop(asyncio.current_task(),None)

    def fail(self,number,error):
        # Never include third-party text, expanded SQL, raw packets or secrets.
        row=self.records[number];row['state']='INTERRUPTED' if isinstance(error,asyncio.CancelledError) else 'FAILED'
        row['failure_state']=row['state']
        row['error_type']=type(error).__name__[:64]
        self.tasks.pop(asyncio.current_task(),None)

    def pending(self,session):
        return [dict(row) for row in self.records.values() if row['session']==session and row['state']!='ACTIVE']

    def preserved(self,rows):
        for row in rows:
            current=self.records.get(row['id'])
            if current is not None:current.update(state=row['state'],recovery=row.get('recovery'))

    def snapshot(self):
        rows=[dict(r) for r in self.records.values()]
        size=len(json.dumps(rows,separators=(',',':')).encode())
        if size>self.maximum_bytes:self.valid=False
        return dict(version=1,run=self.run,pid=self.pid,native_thread_id=self.native_thread_id,
            valid=self.valid,accepted=self.accepted,returned=self.returned,
            active=sum(r['state']=='ACTIVE' for r in rows),
            recoverable=sum(r['state']=='RECOVERABLE' for r in rows),
            failed=sum(r['state']=='FAILED' for r in rows),
            unresolved=sum(r['state']=='INTERRUPTED' for r in rows),
            records=rows if size<=self.maximum_bytes else None,record_bytes=size,
            scope='RETURNED_CALLBACKS_REQUIRE_SEPARATE_QUEUE_COMMIT_AND_SESSION_RECOVERY_FENCES')


def preserve_handlers(state,ledger,rows,recovery):
    """Atomically associate interrupted identities with existing durable gaps.

    This is a bounded diagnostic/recovery locator in existing canonical health,
    never a coverage proof or a second acquisition/monetary authority. Old rows
    are retained; this function cannot clear them on a prospective head jump.
    """
    if not rows:return []
    from .solana_evidence_plane import EvidenceUnavailable,canonical
    with state.writer.transaction():
        prior=state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(HANDLER_RECOVERY_KEY,)).fetchone()
        body=json.loads(prior[0]) if prior else dict(version=1,records=[])
        if body.get('version')!=1 or not isinstance(body.get('records'),list):
            raise EvidenceUnavailable('source_handler_recovery_corrupt')
        records={(r['run'],r['id']):r for r in body['records']}
        retained=[]
        for row in rows:
            item=dict(row,run=ledger.run,source_pid=ledger.pid,native_thread_id=ledger.native_thread_id)
            valid_slot=type(row.get('slot')) is int and row['slot']>0
            if valid_slot and recovery is not None:
                verified=False
                if recovery.get('kind')=='CONTROL_REPLAY':
                    current=state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(CONTROL_RECOVERY_KEY,)).fetchone()
                    required=control_recovery(current[0]) if current else None
                    verified=(required is not None and recovery==dict(kind='CONTROL_REPLAY',**required)
                        and required['lower_slot']<=row['slot']<=required['upper_slot']
                        and row.get('scope_count')==1 and row.get('scope_hash')==ledger.scope_hash(('control:solana',)))
                elif recovery.get('kind')=='CANDIDATE_GAPS':
                    ids=recovery.get('gap_ids')
                    if isinstance(ids,list) and 0<len(ids)<=48 and all(type(i) is int and i>0 for i in ids):
                        gaps=[state.writer.db.execute('SELECT scope,lo,hi FROM candidate_gaps WHERE id=?',(i,)).fetchone() for i in ids]
                        verified=(all(g is not None and g[1]<=row['slot'] and (g[2] is None or row['slot']<=g[2]) for g in gaps)
                            and row.get('scope_count')==len({g[0] for g in gaps if g is not None})
                            and row.get('scope_hash')==ledger.scope_hash(g[0] for g in gaps if g is not None))
                if not verified:raise EvidenceUnavailable('source_handler_recovery_unverified')
                item.update(state='RECOVERABLE',recovery=recovery)
            else:item.update(recovery=None)
            key=(ledger.run,row['id']);old=records.get(key)
            if old is not None and old!=item:raise EvidenceUnavailable('source_handler_recovery_conflict')
            records[key]=item;retained.append(item)
        body=dict(version=1,records=list(records.values()))
        if len(records)>ledger.maximum_records or len(canonical(body).encode())>ledger.maximum_bytes:
            raise EvidenceUnavailable('source_handler_record_bound')
        state.fence._health(HANDLER_RECOVERY_KEY,body)
        return retained


async def finish_owned(task,deadline):
    """A repeated coordinator cancel cannot cut its one owned teardown in half.

    The existing source shutdown deadline still ends this wait. A timeout is a
    failed drain, never permission to return a successful terminal census.
    """
    while True:
        remaining=deadline-asyncio.get_running_loop().time()
        if remaining<=0:
            task.cancel()
            raise TimeoutError('source_owned_drain_deadline')
        try:return await asyncio.wait_for(asyncio.shield(task),remaining)
        except TimeoutError:
            if not task.done():task.cancel()
            raise
        except asyncio.CancelledError:
            if task.done():return task.result()


def control_recovery(raw):
    """An acquisition obligation, never a substitute for canonical coverage."""
    if raw is None:return None
    try:
        value=json.loads(raw)
        if value is None:return None
        lo,hi,after=(value[name] for name in ('lower_slot','upper_slot','coverage_after_id'))
        if (type(lo) is not int or type(hi) is not int or type(after) is not int
                or not 1<=lo<=hi or after<0):raise ValueError()
        return dict(lower_slot=lo,upper_slot=hi,coverage_after_id=after)
    except (ValueError,TypeError,KeyError):
        from .solana_evidence_plane import EvidenceUnavailable
        raise EvidenceUnavailable('control_recovery_obligation_invalid') from None


def preserve_control_recovery(state,lower,upper):
    """The existing canonical owner records the exact unfinished source range."""
    with state.writer.transaction():
        row=state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(CONTROL_RECOVERY_KEY,)).fetchone()
        prior=control_recovery(None if row is None else row[0])
        after=state.writer.db.execute('SELECT COALESCE(MAX(id),0) FROM coverage').fetchone()[0]
        value=dict(lower_slot=lower,upper_slot=upper,coverage_after_id=after)
        if prior:
            value=dict(lower_slot=min(lower,prior['lower_slot']),upper_slot=max(upper,prior['upper_slot']),
                coverage_after_id=min(after,prior['coverage_after_id']))
        state.fence._health(CONTROL_RECOVERY_KEY,value)
        return value


def complete_control_recovery(state,scope):
    """Clear only after newly authenticated coverage spans the whole obligation.

    A later newest head, an old coverage row, or a partial replay cannot clear
    this floor. The coverage writer retains its original proof validation.
    """
    row=state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(CONTROL_RECOVERY_KEY,)).fetchone()
    required=control_recovery(None if row is None else row[0])
    if required is None:return None
    cursor=required['lower_slot']
    rows=state.writer.db.execute('''SELECT lo,hi FROM coverage WHERE scope=? AND id>?
        AND lo<=? AND hi>=? ORDER BY lo,hi LIMIT 512''',
        (scope,required['coverage_after_id'],required['upper_slot'],cursor))
    for lo,hi in rows:
        if lo>cursor:break
        cursor=max(cursor,hi+1)
        if cursor>required['upper_slot']:
            state.fence._health(CONTROL_RECOVERY_KEY,None)
            return None
    if cursor>required['lower_slot']:
        # Bound one owner turn, but retain durable progress across pages. This
        # advances only the *acquisition obligation*, after real contiguous
        # coverage; it never advances a canonical checkpoint or skips a hole.
        required=dict(required,lower_slot=cursor)
        state.fence._health(CONTROL_RECOVERY_KEY,required)
    return required

INTAKE_CLOSED=object()


async def receive_until_closed(receive,stop,*,closed_task=None):
    """Wake an idle socket on stop; finish a read already delivered in the race."""
    read=asyncio.create_task(receive());closed=closed_task or asyncio.create_task(stop.wait())
    try:
        await asyncio.wait((read,closed),return_when=asyncio.FIRST_COMPLETED)
        return read.result() if read.done() else INTAKE_CLOSED
    finally:
        cleanup=(read,) if closed_task is not None else (read,closed)
        for task in cleanup:
            if not task.done():task.cancel()
        await asyncio.gather(*cleanup,return_exceptions=True)


class StopEither:
    def __init__(self,*events):self.events=events
    def is_set(self):return any(event.is_set() for event in self.events)
    async def wait(self):
        tasks=[asyncio.create_task(event.wait()) for event in self.events]
        try:await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)


async def next_owned(queue,producer_done):
    """Return an admitted item, or None only after its producer has settled."""
    if producer_done.is_set() and queue.empty():return None
    get=asyncio.create_task(queue.get());closed=asyncio.create_task(producer_done.wait())
    try:
        await asyncio.wait((get,closed),return_when=asyncio.FIRST_COMPLETED)
        # A simultaneous close cannot take an already delivered item away.
        if get.done():return get.result()
        get.cancel();await asyncio.gather(get,return_exceptions=True)
        return None if queue.empty() else queue.get_nowait()
    finally:
        for task in (get,closed):
            if not task.done():task.cancel()
        await asyncio.gather(get,closed,return_exceptions=True)


async def join_owned(queue,worker):
    """A failed consumer cannot leave an unfulfillable queue.join hanging."""
    joined=asyncio.create_task(queue.join())
    try:
        done,_=await asyncio.wait((joined,worker),return_when=asyncio.FIRST_COMPLETED)
        if worker in done:
            worker.result()
            if not joined.done():
                # task_done releases join's waiter on the next event-loop turn.
                await asyncio.sleep(0)
                if not joined.done():raise RuntimeError('source_commit_stopped_with_pending_frames')
        await joined
    finally:
        if not joined.done():joined.cancel()
        await asyncio.gather(joined,return_exceptions=True)


async def settle_owned(producers,consumers):
    """Settle handlers while watching consumers which can free their capacity.

    A consumer may fail *after* shutdown began. Waiting only on producers in
    that case would deadlock a producer's capacity-blocked final put.
    """
    pending=set(producers);watch=pending|set(consumers)
    while pending:
        done,_=await asyncio.wait(watch,return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task in consumers and (task.cancelled() or task.exception() is not None):
                for producer in pending:
                    if not producer.done():producer.cancel()
        pending.difference_update(done);watch.difference_update(done)
    return await asyncio.gather(*producers,return_exceptions=True)


class AcceptedQueue(asyncio.Queue):
    """The existing FIFO plus a census which includes its owner-held batch."""
    def __init__(self,maxsize,changed):
        super().__init__(maxsize=maxsize);self.changed=changed
    async def put(self,item):
        await super().put(item);self.changed(1,0)
    def committed(self,rows):
        for _ in rows:self.task_done()
        self.changed(0,len(rows))
