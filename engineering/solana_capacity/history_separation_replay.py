"""Offline shared-owner replay of retained economics and historical proof work.

Not a mainnet throughput/qualification or funded protection acceptance. No
provider methods. Live-slot figures describe this explicit event-store subset,
not program-wide completeness. Authority is read-only; fixtures use Scratch.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import asyncio
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import statistics
import time
from types import SimpleNamespace
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.solana_evidence_plane import EvidenceWriter,FinalizedRecord,canonical,digest,decode_body
from meme_machine.solana_evidence_service import FinalizedFence
from meme_machine.solana_evidence_control import PriorityOwner,admit
from meme_machine.solana_selective_source import install,source_work
from meme_machine.solana_rolling_history import RollingHistory,program_scope
from meme_machine.solana_history_work import HistoricalTasks,HistoryExecutor,prepare_history
from meme_machine.solana_history_delivery import capture,deliver,acknowledge


def collect(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        records=[]
        raw=db.execute("""SELECT body,hash,first_seen FROM rolling_economic_events
            WHERE scope IN ('program:pump','program:pumpswap') AND body IS NOT NULL
            ORDER BY slot DESC,transaction_index DESC,event_index DESC LIMIT 1024""").fetchall()
        for body,checksum,seen in raw:
            if hashlib.sha256(body.encode()).hexdigest()!=checksum:raise ValueError('retained_record_corrupt')
            value=decode_body(body,db)
            records.append(FinalizedRecord(**value,source='alchemy_finalized_stream',
                endpoint_identity='a'*64,observed_at=seen))
        records.sort(key=lambda r:(r.slot,r.transaction_index or 0,r.event_index,r.identity))
        proofs=[]
        for family in ('pump','pumpswap'):
            rows=db.execute('SELECT * FROM candidate_coverage WHERE scope=? ORDER BY lo LIMIT 2048',
                (program_scope(family),)).fetchall()
            proofs.extend(rows)
        live_addresses={a for r in records for a in r.addresses}
        waits=[]
        for family in ('pump','pumpswap'):
            rows=db.execute("SELECT family,address,lo,hi FROM rolling_publication_waits WHERE family=? AND lo>0 ORDER BY created DESC LIMIT 256",(family,)).fetchall()
            waits.extend([r for r in rows if r[1] not in live_addresses][:8])
        waits=waits[:16]
        bindings={}
        addresses=sorted(live_addresses)
        for index in range(0,len(addresses),128):
            values=addresses[index:index+128]
            for row in db.execute("SELECT * FROM evidence_bindings WHERE family IN ('pump','pumpswap') AND market_address IN ("+','.join('?' for _ in values)+')',values):
                bindings[row[:2]]=row
        population={}
        for family,address in {*bindings.keys(),*((r[0],r[1]) for r in waits)}:
            row=db.execute('SELECT * FROM candidate_lifecycle WHERE family=? AND address=?',(family,address)).fetchone()
            if row:population[(family,address)]=row
        db.execute('ROLLBACK')
    if not records or not proofs or not waits:raise ValueError('retained_workload_required')
    return records,proofs,waits,list(bindings.values()),list(population.values())


def percentile(xs,p):return sorted(xs)[min(len(xs)-1,int((len(xs)-1)*p))]


def obligations(rows):
    """Exact coverage/deadlines, including contained original duplicate jobs."""
    from meme_machine.solana_rolling_history import _subtract_intervals
    groups={}
    for identity,family,address,lo,hi,priority,deadline in rows:
        groups.setdefault((family,address,priority,deadline),[]).append((lo,hi))
    return [(key,_subtract_intervals(values,())) for key,values in sorted(groups.items())]


def calculation_replay(root):
    """Separate deterministic seven-day regression, not authentic price data."""
    from meme_machine.runtime.survivor_history import History
    from meme_machine.lanes.pump.pumpswap_survivor import POLICY_HASH,reduce_reset_history
    with closing(History(root/'calculation.sqlite',policy=POLICY_HASH)) as history:
        history.graduate('late',dict(at=0,pool='offline-regression-pool'))
        points=[(t,dict(price=str(100+t//60%37),low=str(95+t//60%37),high=str(105+t//60%37))) for t in range(0,7*86400+1,60)]
        now=points[-1][0]
        history.append('late',through=now,events=[],points=points,complete=True)
        measurements=[]
        expected=reduce_reset_history(history.facts('late',now)[0])
        for mode in ('original','incremental'):
            statements=[0];decoded=0
            history.db.set_trace_callback(lambda sql:statements.__setitem__(0,statements[0]+1))
            cpu=time.thread_time();wall=time.monotonic()
            for turn in range(20):
                if mode=='original':
                    prices,events=history.facts('late',now);actual=reduce_reset_history(prices);decoded+=len(prices)+len(events)
                else:
                    prices,events,prefix=history.calculation_facts('late',now,reducer=reduce_reset_history,policy=POLICY_HASH)
                    actual=reduce_reset_history([p for p in prices if p['at']>prefix['through']],prefix)
                    decoded+=history.calculation_metrics['prefix_records_decoded']+len(prices)+len(events)
                if actual!=expected:raise AssertionError('reset_summary_not_equivalent')
            measurements.append(dict(mode=mode,turns=20,cpu_seconds=time.thread_time()-cpu,
                wall_seconds=time.monotonic()-wall,sql_statements=statements[0],records_decoded=decoded))
        history.db.set_trace_callback(None)
        assert len(history.facts('late',now)[0])==len(points),'historical_retention_changed'
        return dict(scope='Synthetic 7-day minute-price regression; includes first summary build and exact subsequent reset decisions. Not a market or portfolio return claim.',
            retained_points=len(points),provider_requests=0,measurements=measurements)


async def replay(folder,records,proofs,waits,bindings,population,legacy,*,separated):
    logical=max([r.observed_at for r in records]+[r[5] for r in proofs])+1;clock_started=time.monotonic()
    clock=lambda:logical+time.monotonic()-clock_started
    def factory():
        writer=EvidenceWriter(folder/'canonical.sqlite',clock=clock)
        state=SimpleNamespace(writer=writer,fence=FinalizedFence(writer,endpoint_identity='a'*64))
        h=install(state);h.clock=clock;h.lifecycle.clock=h.clock
        h.rolling=RollingHistory(h) if separated else legacy.RollingHistory(h)
        with writer.transaction():
            h.db.executemany('INSERT OR REPLACE INTO candidate_coverage VALUES(?,?,?,?,?,?,?,?,?,?)',proofs)
            h.db.executemany('INSERT OR REPLACE INTO evidence_bindings VALUES(?,?,?,?,?,?)',bindings)
            if population:h.db.executemany('INSERT OR REPLACE INTO candidate_lifecycle VALUES('+','.join('?' for _ in population[0])+')',population)
            for family,address,lo,hi in waits:h.bind(family,address)
        if separated:
            h.historical_tasks=HistoricalTasks(h);h.lifecycle.delivery_separated=True
        state.h=h;state.close=writer.close
        return state
    owner=PriorityOwner(factory);await asyncio.wrap_future(owner.ready)
    process=HistoryExecutor() if separated else None
    delivery=ThreadPoolExecutor(max_workers=1) if separated else None
    live=[];protection=[];history=[];timings={'live_cpu':0.,'history_owner_cpu':0.,'history_worker_cpu':0.,'history_worker_wall':0.,'delivery_worker_cpu':0.,'delivery_worker_wall':0.,'history_points_decoded':0,'history_fragments_read':0}
    tasks_reused=0;sql_statements={'live':0,'historical':0,'other':0};stage=['other']
    def trace(sql):sql_statements[stage[0]]+=1
    await asyncio.wrap_future(owner.submit(lambda s:s.writer.db.set_trace_callback(trace),priority=2))
    original_points=legacy.coverage_points
    def counted(packed,checksum):
        points=original_points(packed,checksum);timings['history_points_decoded']+=len(points);return points
    if not separated:legacy.coverage_points=counted
    stop=asyncio.Event()
    async def submitted(fn,priority):
        future=await admit(owner,fn,priority=priority)
        return await asyncio.wrap_future(future)
    call=source_work(submitted,stop)
    async def background():
        while True:
            job=await call(lambda s:s.h.historical_tasks.claim(),4)
            if job is None:
                pending=await call(lambda s:s.writer.db.execute("SELECT COUNT(*) FROM rolling_preparation_jobs WHERE status IN ('pending','active')").fetchone()[0],4)
                if done and not pending:return
                await asyncio.sleep(.01);continue
            result=await asyncio.wrap_future(process.submit(prepare_history,folder/'canonical.sqlite',job))
            def apply(state):
                cpu=time.thread_time();stage[0]='historical';answer=state.h.historical_tasks.apply(job,result)
                timings['history_owner_cpu']+=time.thread_time()-cpu;stage[0]='other'
                return answer
            answer=await call(apply,4)
            timings['history_worker_cpu']+=result['metrics']['cpu_seconds']
            timings['history_worker_wall']+=result['metrics']['wall_seconds']
            timings['history_points_decoded']+=result['metrics']['proof_points_decoded']
            timings['history_fragments_read']+=result['metrics']['proof_fragments_read']
            if answer:history.append(digest(answer))
    async def consumer():
        while True:
            snapshot=await call(lambda s:capture(s.h.lifecycle),2)
            if snapshot is None:
                if done:return
                await asyncio.sleep(.005);continue
            try:result=await asyncio.wrap_future(delivery.submit(deliver,snapshot))
            except sqlite3.OperationalError as exc:
                if getattr(exc,'sqlite_errorcode',0)&255 not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):raise
                await asyncio.sleep(.01);continue
            timings['delivery_worker_cpu']+=result['metrics']['cpu_seconds']
            timings['delivery_worker_wall']+=result['metrics']['wall_seconds']
            await call(lambda s:acknowledge(s.h.lifecycle,snapshot,result),2)
    grouped={}
    for r in records:grouped.setdefault(r.slot,[]).append(r)
    done=False;bg=asyncio.create_task(background()) if separated else None
    consume=asyncio.create_task(consumer()) if separated else None
    started=time.monotonic();cpu_start=time.process_time()
    try:
        for slot,rows in grouped.items():
            def plan(state):
                nonlocal tasks_reused
                cpu=time.thread_time();stage[0]='historical'
                with state.writer.transaction():
                    for family,address,lo,hi in waits:
                        value=state.h.rolling.prepare(family,address,lo,hi,deadline=logical+150,priority=3)
                        if not separated or value.get('boundary_state')!='HISTORICAL_PLANNING_PENDING':
                            history.append(digest(value))
                            if separated:tasks_reused+=1
                timings['history_owner_cpu']+=time.thread_time()-cpu;stage[0]='other'
            planning=await admit(owner,plan,priority=4)
            arrival=time.monotonic()
            def commit(state):
                begin=time.monotonic();cpu=time.thread_time();stage[0]='live'
                state.h.ingest(rows);state.h.lifecycle.publish()
                timings['live_cpu']+=time.thread_time()-cpu;stage[0]='other'
                return time.monotonic()-begin
            executed=await call(commit,2)
            live.append({'end_to_end':time.monotonic()-arrival,'execution':executed})
            urgent=time.monotonic()
            await call(lambda s:s.writer.db.execute('SELECT MAX(slot) FROM cursors').fetchone(),0)
            protection.append(time.monotonic()-urgent)
            await asyncio.wrap_future(planning)
        live_finished=time.monotonic();done=True
        if bg:await asyncio.wait_for(bg,90)
        if consume:await asyncio.wait_for(consume,90)
        # Original delivery also drains bounded outbox batches before comparison.
        while time.monotonic()-started<180:
            remaining=await call(lambda s:s.writer.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],2)
            if not remaining:break
            await call(lambda s:s.h.lifecycle.publish(),2)
        if remaining:raise RuntimeError('offline_consumer_not_drained')
        elapsed=time.monotonic()-started
        result=await call(lambda s:{'events':s.writer.db.execute('SELECT identity,slot,signature,transaction_index,event_index,hash FROM rolling_economic_events ORDER BY slot,transaction_index,event_index,identity').fetchall(),
            'jobs':s.writer.db.execute('SELECT id,family,address,lo,hi,priority,deadline FROM acquisition_jobs ORDER BY id').fetchall(),
            'population':s.writer.db.execute('SELECT family,address,state,epoch FROM candidate_lifecycle ORDER BY family,address').fetchall(),
            'pending_outbox':s.writer.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0]},0)
        raw_job_count=len(result['jobs']);result['jobs']=obligations(result['jobs'])
        final_windows=await call(lambda s:[(family,address,lo,hi,s.h.rolling.missing(family,s.h.scope_for(family,address),lo,hi))
            for family,address,lo,hi in waits],0)
        return dict(mode='separated' if separated else 'original',replayed_events=len(records),event_bearing_slots=len(grouped),
            live_seconds=live_finished-started,total_drain_seconds=elapsed,
            completed_event_bearing_slots_per_second=len(grouped)/(live_finished-started),
            parent_cpu_seconds=time.process_time()-cpu_start,verified_history_requests_reused=tasks_reused,sql_statements=sql_statements,**timings,
            live_publication_latency=dict(median=statistics.median(x['end_to_end'] for x in live),p95=percentile([x['end_to_end'] for x in live],.95),maximum=max(x['end_to_end'] for x in live)),
            urgent_owner_read_latency=dict(median=statistics.median(protection),p95=percentile(protection,.95),maximum=max(protection)),
            owner=owner.telemetry(),evidence_sha256=digest(result),raw_acquisition_jobs=raw_job_count,
            historical_coverage_verdicts=final_windows,state=result)
    finally:
        stop.set()
        for task in (bg,consume):
            if task and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
        if delivery:await asyncio.to_thread(delivery.shutdown,wait=True,cancel_futures=True)
        if process:await asyncio.to_thread(process.close)
        await asyncio.to_thread(owner.close)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canonical',required=True);parser.add_argument('--baseline',required=True)
    parser.add_argument('--output',required=True);args=parser.parse_args()
    from operational.tests import network_guard
    network_guard()
    module=importlib.util.spec_from_file_location('meme_machine._history_replay_baseline',Path(args.baseline)/'meme_machine/solana_rolling_history.py')
    legacy=importlib.util.module_from_spec(module);module.loader.exec_module(legacy)
    os.environ['MM_SOLANA_HISTORY_SEPARATED']='0'
    records,proofs,waits,bindings,population=collect(args.canonical)
    with Scratch() as scratch:
        root=Path(scratch.path);results=[]
        for separated in (False,True):
            folder=root/('separated' if separated else 'original');folder.mkdir()
            async def guarded():
                task=asyncio.create_task(replay(folder,records,proofs,waits,bindings,population,legacy,separated=separated))
                try:
                    while not task.done():
                        await asyncio.sleep(.25);scratch.check()
                    return await task
                finally:
                    if not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
            results.append(asyncio.run(asyncio.wait_for(guarded(),180)))
            scratch.check()
        assert results[0]['state']==results[1]['state'],'canonical_economic_or_candidate_difference'
        assert results[0]['historical_coverage_verdicts']==results[1]['historical_coverage_verdicts'],'history_plan_difference'
        for result in results:result.pop('state')
        output=dict(status='OFFLINE_RETAINED_OWNER_PIPELINE_PARITY',provider_requests=0,funding=False,
            workload=dict(events=len(records),event_identity_digest=digest([r.identity for r in records]),
                source_slots=[records[0].slot,records[-1].slot],historical_fragments=len(proofs),history_requests=len(waits),live_bindings=len(bindings),retained_candidates=len(population)),
            scope='Retained event-store, durable candidate outbox, history planning and shared-owner scheduling replay. Excludes native transport/join, broad census, actual protective quotes, Pons and full machine acceptance. Imported historical proofs retain their original bytes, hashes, availability and lineage. No new live interval coverage is claimed.',
            measurements=results,calculation_regression=calculation_replay(root))
        Path(args.output).write_text(json.dumps(output,indent=2)+'\n');scratch.success=True
        print(json.dumps(output,indent=2))


if __name__=='__main__':main()
