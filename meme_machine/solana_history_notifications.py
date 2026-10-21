"""Volatile wakeups for the existing durable history obligations.

An epoch closes the clear/wait race. It grants no evidence authority; startup
always visits the durable outbox. Committed changes wake publication/delivery,
while diagnostics and unrelated accounting deliberately do not.
"""
import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class DeliveryHint:
    revision:int
    refresh_token:int
    refresh_requested:bool


def delivery_hint(history):
    """Copy owner scheduling state; none of these fields authorizes evidence."""
    life=getattr(history,'lifecycle',None)
    return DeliveryHint(getattr(history,'_history_delivery_revision',0),
        getattr(life,'_consumer_refresh_token',0),
        bool(getattr(life,'_consumer_refresh_requested',False)))


class WorkPulse:
    def __init__(self):self.epoch=0;self.event=asyncio.Event()
    def notify(self):self.epoch+=1;self.event.set()
    async def wait(self,seen,stop,*,delay=None):
        if self.epoch!=seen or stop.is_set():return self.epoch
        self.event.clear()
        # No await between clear and the second epoch check. A thread queues its
        # notification on this same event loop, never mutates the Event directly.
        if self.epoch!=seen:return self.epoch
        work=asyncio.create_task(self.event.wait());end=asyncio.create_task(stop.wait())
        try:await asyncio.wait((work,end),timeout=delay,return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (work,end):task.cancel()
            await asyncio.gather(work,end,return_exceptions=True)
        return self.epoch


def changed(history,*,publication=True,delivery=True,urgent_delivery=True):
    if publication:history._history_publication_revision=getattr(history,'_history_publication_revision',0)+1
    if delivery:history._history_delivery_revision=getattr(history,'_history_delivery_revision',0)+1
    if delivery and urgent_delivery:history._history_urgent_revision=getattr(history,'_history_urgent_revision',0)+1
    if not history.db.in_transaction:
        callback=getattr(history.writer,'_history_committed',None)
        if callback is not None:callback()


def install(history,loop,wakeup,*,capture_hints=False):
    def current():return (getattr(history,'_history_publication_revision',0),
        getattr(history,'_history_delivery_revision',0),getattr(history,'_history_urgent_revision',0))
    committed=[current()]
    def notify():
        revision=current()
        if not history.db.in_transaction and revision!=committed[0]:
            publication=revision[0]!=committed[0][0];delivery=revision[1]!=committed[0][1]
            urgent=revision[2]!=committed[0][2]
            committed[0]=revision
            # Freeze values on the owner before queueing. A reader may observe
            # this commit before its callback arrives; the later pulse must
            # still reopen its completed scheduling horizon.
            options=dict(publication=publication,delivery=delivery,urgent_delivery=urgent)
            if capture_hints:options['delivery_hint']=delivery_hint(history)
            if not loop.is_closed():loop.call_soon_threadsafe(lambda:wakeup(**options))
    history.writer._history_committed=notify
