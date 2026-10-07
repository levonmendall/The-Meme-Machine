"""Off-owner physical WAL reclamation at an explicit SQLite mutation boundary.

A completed PASSIVE snapshot can already be obsolete when its callback runs.
The fast path may reject that stale generation, but the fallback must not wait
forever for idle time. This module obtains one FIFO owner handoff, checkpoints
its remaining tail off-owner, and releases the handoff on every terminal path.

No busy wait for readers, no durability change, no queue/storage-limit change.
The handoff does delay database mutations by its actual I/O cost; production
telemetry measures that latency rather than describing it as a zero-cost reset.
"""
from __future__ import annotations
import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3


def checkpoint_and_reclaim(path):
    """Caller holds the logical owner boundary; this connection owns no records."""
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=rw',
                                 uri=True,isolation_level=None,timeout=0)) as db:
        # The fresh PASSIVE includes every write preceding the handoff. It must
        # complete before TRUNCATE; a pinned old reader releases us immediately.
        result=db.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
        if result[0]!=0 or result[1]!=result[2]:return result
        # No new source, metadata, or retention transaction can append a tail
        # while the handoff is held. New readers remain valid; a reader that
        # prevents reset yields BUSY rather than being waited out or invalidated.
        return db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()


async def reclaim_at_boundary(owner,path):
    """One accepted handoff and one worker, fully joined even on cancellation."""
    from .solana_evidence_control import admit
    accepted=asyncio.wrap_future(await admit(owner,
        lambda state:owner.checkpoint_handoff_after_current(),priority=2))
    cancelled=False;token=None;pending=None
    try:
        # Cancellation cannot abandon a queued handoff after it is accepted.
        while token is None:
            try:token=await asyncio.shield(accepted)
            except asyncio.CancelledError:cancelled=True
        if not cancelled:
            pending=asyncio.create_task(asyncio.to_thread(checkpoint_and_reclaim,path))
            while True:
                try:
                    result=await asyncio.shield(pending)
                    break
                except asyncio.CancelledError:cancelled=True
        if cancelled:raise asyncio.CancelledError()
        return result
    finally:
        # Every cancellation has joined accepted admission and accepted I/O.
        # Never let later mutations race a checkpoint thread still in flight.
        if token is not None:owner.release_checkpoint_handoff(token)
