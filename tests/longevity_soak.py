"""Storage/memory longevity soak for the bounded Pump paper runtime.

Default mode accelerates 24 logical hours so CI/developers can exercise journal
rotation, a stuck-position monitor, tape retention and RPC-cache bounds without a
24-hour wall clock. Pass --real-time to hold the process for the full wall-clock
period on a suitable durable host. This harness is synthetic plumbing evidence only;
it has no provider, order, signing or performance authority.
"""
import argparse
import json
import math
import resource
import tempfile
import time
from pathlib import Path

from meme_machine.engine import Engine
from meme_machine.provider import RPC
from meme_machine.store import JOURNAL_MAX_ROWS, Store
from meme_machine.stream import MAX_EVENTS, PumpTape
from tests.support import MINT, SCOUT, event, evidence, snapshot


def _feed_tape(tape, now, count):
    """Efficient test-only decoded-event load using PumpTape's real retention deque."""
    with tape._lock:
        tape._prune_locked(now)
        for i in range(count):
            tape.sequence += 1
            if len(tape._events) >= tape.max_events:
                tape._events.popleft()
                tape.capacity_losses += 1
                tape.loss_until=max(tape.loss_until,now+60)
            tape._events.append((tape.sequence,{
                'id':f'soak:{tape.sequence}', 'mint':MINT, 'wallet':SCOUT,
                'market_time':now, 'available_time':now, 'slot':now,
                'buy':bool(i&1), 'amount':1_000_000, 'tokens':1_000_000,
            }))
            tape.trade_events += 1
        tape.notifications += count
        tape.last_slot=now


def _avg(values):
    return sum(values)/len(values) if values else 0


def run(hours=24, events_per_minute=3600, writes_per_minute=12, real_time=False):
    if hours < 8 or events_per_minute < 1 or writes_per_minute < 1:
        raise ValueError('soak requires >=8 hours and positive load')
    logical_start=1_800_000_000
    wall_start=time.monotonic()
    samples=[]
    with tempfile.TemporaryDirectory() as td:
        path=str(Path(td)/'longevity.db')
        store=Store(path,'synthetic',100_000_000,'24h longevity soak')
        engine=Engine(store,[SCOUT])
        nomination=engine.scout([event(logical_start)],logical_start)[0]
        if engine.consider(nomination,evidence(logical_start),logical_start)!='qualified':
            raise AssertionError('fixture did not qualify')
        if engine.fill(nomination['id'],snapshot(logical_start+2),logical_start+2)!='settled':
            raise AssertionError('fixture did not enter')

        clock=[logical_start+2]
        tape=PumpTape(clock=lambda:clock[0])
        tape.begin(clock[0]-60)
        rpc=RPC('https://cache-only.invalid',limit=240,
                transport=lambda request:{'result':request['params']})
        previous_seq=store.state['journal_seq']
        minutes=hours*60
        for minute in range(1,minutes+1):
            minute_base=logical_start+2+(minute-1)*60
            now=minute_base+60
            clock[0]=now
            _feed_tape(tape,now,events_per_minute)

            # Keep the RPC cache under continuously changing keys without network I/O.
            for i in range(16):
                rpc._cache_put(f'{minute}:{i}',{'minute':minute,'payload':'x'*128})

            # Simulate the current five-second monitoring cadence for a permanently
            # unavailable exit mark. Only one unresolved record/minute should persist.
            for offset in range(5,61,5):
                engine.monitor(MINT,{},minute_base+offset)

            # Stress durable write rotation at the runtime's current 5-second cadence.
            for _ in range(writes_per_minute):
                with store.transaction('soak_heartbeat'):
                    store.state['provider']['soak_minute']=minute

            if minute % 60 == 0:
                stats=store.journal_stats()
                seq=store.state['journal_seq']
                status=tape.status(now)
                sample=dict(
                    hour=minute//60,
                    rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    tape_occupancy=status['retained_events'],
                    tape_capacity_losses=status['capacity_losses'],
                    journal_rows=stats['rows'],
                    journal_rotations=stats['rotations'],
                    db_bytes=stats['db_bytes'],wal_bytes=stats['wal_bytes'],
                    allocated_bytes=stats['db_bytes']+stats['wal_bytes'],
                    cache_entries=len(rpc.cache),cache_bytes=rpc.cache_bytes,
                    writes_this_hour=seq-previous_seq,
                )
                previous_seq=seq
                samples.append(sample)
            if real_time:
                elapsed=time.monotonic()-wall_start
                target=minute*60
                if elapsed < target:
                    time.sleep(target-elapsed)

        store.reconcile()
        store.verify_archive()
        final_stats=store.journal_stats()
        store.close()

    last=samples[-min(6,len(samples)):]
    first_half=samples[:len(samples)//2]
    second_half=samples[len(samples)//2:]
    allocated=[s['allocated_bytes'] for s in last]
    rss=[s['rss_kib'] for s in last]
    write_rates=[s['writes_this_hour'] for s in samples[1:]] or [samples[0]['writes_this_hour']]
    expected_tape=min(MAX_EVENTS,events_per_minute*2)

    assertions={
        'journal_rows_bounded': all(s['journal_rows']<=JOURNAL_MAX_ROWS for s in samples),
        'journal_rotated': final_stats['rotations']>0,
        'tape_occupancy_bounded': all(s['tape_occupancy']<=expected_tape for s in samples),
        'tape_no_capacity_loss': all(s['tape_capacity_losses']==0 for s in samples),
        'rpc_cache_entries_bounded': all(s['cache_entries']<=128 for s in samples),
        'rpc_cache_bytes_bounded': all(s['cache_bytes']<=8*1024*1024 for s in samples),
        'late_storage_plateau': max(allocated)-min(allocated)<=8*1024*1024,
        'late_rss_plateau': max(rss)-min(rss)<=32*1024,
        'write_rate_not_accelerating': (
            max(write_rates)-min(write_rates) <= max(4,math.ceil(_avg(write_rates)*0.05))
        ),
        'late_write_rate_not_higher_than_early': (
            _avg([s['writes_this_hour'] for s in second_half]) <=
            _avg([s['writes_this_hour'] for s in first_half])*1.05
        ),
    }
    failed=[name for name,ok in assertions.items() if not ok]
    result=dict(
        kind='storage_memory_longevity_soak',
        logical_hours=hours,real_time=real_time,
        events_per_minute=events_per_minute,writes_per_minute=writes_per_minute,
        samples=samples,assertions=assertions,failed_assertions=failed,
        final_journal=final_stats,
        wall_elapsed_seconds=round(time.monotonic()-wall_start,3),
        limitation=(None if real_time else
                    'accelerated logical-time soak; run with --real-time for a true 24-hour process-residency leak proof'),
    )
    if failed:
        raise AssertionError(json.dumps(result,sort_keys=True))
    print(json.dumps(result,sort_keys=True))
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--hours',type=int,default=24)
    parser.add_argument('--events-per-minute',type=int,default=3600)
    parser.add_argument('--writes-per-minute',type=int,default=12)
    parser.add_argument('--real-time',action='store_true')
    args=parser.parse_args()
    run(args.hours,args.events_per_minute,args.writes_per_minute,args.real_time)


if __name__=='__main__':
    main()
