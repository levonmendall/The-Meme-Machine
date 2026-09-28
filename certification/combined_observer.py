"""Versioned correction of overlap observation, with unchanged pressure inputs.

The original driver, pauses, delays and every acceptance limit remain intact.
Durable counter deltas are sampled while the actual read transaction is held;
a batch's start-phase token is not proof of when its commit became visible.
An empty eligibility window is classified explicitly, never converted to a pass.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch
from certification import combined_pressure as legacy

REVISION='durable-window-v3'
legacy_verified=legacy.verified


def eligible(db):
    """A positive, bounded lower-bound witness using the durable safe floor."""
    for scope in ('program:meteora','program:pump','program:pumpswap'):
        row=db.execute('SELECT value FROM meta WHERE key=?',('retention_floor:'+scope,)).fetchone()
        if row and db.execute(
                'SELECT 1 FROM records WHERE scope=? AND slot<? AND body IS NULL LIMIT 1',
                (scope,int(row[0]))).fetchone():
            return True
    return False


def read_current(path):
    with closing(sqlite3.connect(path,isolation_level=None)) as db:
        db.execute('BEGIN')
        try:
            return dict(db.execute('SELECT key,value FROM counters')),eligible(db)
        finally:
            db.execute('ROLLBACK')


def observe_window(reader,path,before,sample):
    """Must run before ROLLBACK. Reject use after the observed snapshot closes."""
    if not reader.in_transaction:
        raise AssertionError('overlap_reader_not_held')
    after=dict(reader.execute('SELECT key,value FROM counters'))
    if before!=after:
        raise AssertionError('combined_reader_snapshot_changed')
    current,available=read_current(path)
    source=current.get('stream_accepted_messages',0)-before.get('stream_accepted_messages',0)
    cleanup=current.get('compacted_records',0)-before.get('compacted_records',0)
    if source<0 or cleanup<0:
        raise AssertionError('overlap_counters_regressed')
    sample['legacy_start_phase_frames']=sample.get('source_frames_while_reader',0)
    sample.update(source_frames_while_reader=source,reader_source_advance=source,
        reader_compaction_advance=cleanup,reader_snapshot_preserved=True,
        eligible_at_reader_end=available,observation_revision=REVISION)
    sample['cleanup_window_status']=(
        'serviced' if cleanup else 'eligible_not_serviced'
        if sample['eligible_at_reader_start'] or available else 'no_eligible_witness')
    return sample


class Interaction(legacy.Interaction):
    def __init__(self):
        super().__init__()
        self.metrics['observation_revision']=REVISION

    def checkpoint(self,path,native):
        self.path=Path(path)
        with self.lock:
            phase=self.batching_phase;exercise=phase>self.checkpoint_phase
            if exercise:self.checkpoint_phase=phase
        if exercise:
            sample=self.metrics['burst_evidence'][phase-1]
            with closing(sqlite3.connect(path,isolation_level=None)) as reader:
                reader.execute('BEGIN')
                before=dict(reader.execute('SELECT key,value FROM counters'))
                sample['eligible_at_reader_start']=eligible(reader)
                with self.lock:self.reader_phase=phase
                try:
                    time.sleep(1.25)
                    native(path)
                    time.sleep(.1)
                    # Lock only the instrumentation while taking the final
                    # observation; source/cleanup SQLite mutations are unaffected.
                    with self.lock:
                        observe_window(reader,path,before,sample)
                finally:
                    with self.lock:self.reader_phase=0
                    reader.execute('ROLLBACK')
            with self.lock:
                self.metrics['held_reader_cycles']+=1;self.tail_pending=phase
        result=native(path)
        with self.lock:tail=self.tail_pending
        if tail and result[0]==0 and result[1]==result[2]:
            time.sleep(.75)
            with self.lock:
                self.metrics['tail_delay_cycles']+=1
                self.metrics['burst_evidence'][tail-1]['completed_tail_delayed']=True
                self.tail_pending=0
        return result


def observation_verified(row):
    joint=row.get('combined_load') or {}
    samples=joint.get('burst_evidence') or []
    return bool(joint.get('observation_revision')==REVISION and len(samples)==2 and all(
        s.get('observation_revision')==REVISION and s.get('cleanup_window_status')=='serviced'
        and type(s.get('eligible_at_reader_start')) is bool
        and type(s.get('eligible_at_reader_end')) is bool
        and s.get('source_frames_while_reader')==s.get('reader_source_advance')
        for s in samples))


def verified(row,sha):
    return legacy_verified(row,sha) and observation_verified(row)


async def run(output):
    with patch.object(legacy,'Interaction',Interaction),patch.object(legacy,'verified',verified):
        return await legacy.run(output)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args().output)))
