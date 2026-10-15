"""Ownership helpers for the existing bounded source queues, not a second spool.

Closing admission and finishing a queue are separate events.  A received handler
may still be putting its last frame after the stop event has been set.
"""
import asyncio
import json

CONTROL_RECOVERY_KEY='source_control_recovery'


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
