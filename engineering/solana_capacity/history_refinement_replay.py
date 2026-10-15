"""Identical retained raw messages through join, owner and durable consumer.

Run separately in each exact source tree. This is an offline prefix replay, not
provider latency, full host capacity, funded protection or market acceptance.
The capture's missing tail remains missing. No provider calls or fabricated
transaction, finality, coverage or observation timestamps are supplied.
"""
import argparse
import asyncio
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,ThreadPoolExecutor
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import resource
import sqlite3
import statistics
import time
from types import SimpleNamespace


def percentile(rows,p):
    return None if not rows else sorted(rows)[min(len(rows)-1,int((len(rows)-1)*p))]


async def replay(capture,root,*,refined,workers,limit,scratch):
    from engineering.solana_capacity.offline_replay import frames
    from meme_machine.solana_evidence_plane import EvidenceWriter,canonical,digest
    from meme_machine.solana_evidence_service import FinalizedFence,source_decoder_probe
    from meme_machine.solana_evidence_control import PriorityOwner,admit
    from meme_machine.solana_candidate_join import CandidateTransactionJoin
    from meme_machine.solana_selective_history import PROGRAMS
    from meme_machine.solana_selective_source import SelectiveSource,install,commit_scout,CandidateCommitQueue
    from meme_machine.solana_rolling_history import program_scope
    from meme_machine.solana_history_work import HistoryExecutor,prepare_history
    from meme_machine.yellowstone import geyser_pb2 as pb
    result=json.loads((capture/'result.json').read_text());wall=[result['measurement_started']]
    os.environ['MM_SOLANA_HISTORY_SEPARATED']='1'
    # Use the supported default Path on BOTH comparison sources. The published
    # environment-string boundary defect has its own production-path regression.
    os.environ.pop('MM_SOLANA_CANDIDATE_HISTORY_DB',None)
    endpoint=result['endpoint_identity'];metrics=defaultdict(list);counts=Counter();sql=Counter()
    from meme_machine import solana_selective_source as source_module
    source_root=Path(source_module.__file__).resolve().parent.parent
    source_files=('solana_selective_source','solana_selective_history','solana_rolling_history',
        'solana_history_delivery','solana_history_work','solana_economic_preparation',
        'solana_history_notifications','solana_candidate_lifecycle','solana_evidence_plane')
    source_hashes={name:hashlib.sha256((source_root/'meme_machine'/f'{name}.py').read_bytes()).hexdigest()
        for name in source_files if (source_root/'meme_machine'/f'{name}.py').exists()}
    def factory():
        writer=EvidenceWriter(root/'canonical.sqlite',clock=lambda:wall[0])
        state=SimpleNamespace(writer=writer,fence=FinalizedFence(writer,endpoint_identity=endpoint))
        state.close=writer.close;h=install(state);h.clock=lambda:wall[0];h.lifecycle.clock=h.clock
        writer.db.set_trace_callback(lambda statement:sql.update(('statements',)))
        return state
    owner=PriorityOwner(factory);await asyncio.wrap_future(owner.ready)
    async def work(fn,priority=2,**options):
        submitted=time.monotonic();kind=options.get('label') or fn.__name__
        def execute(state):
            start=time.monotonic();cpu=time.thread_time();before=state.writer.db.total_changes
            try:return fn(state)
            finally:
                metrics[kind+'.owner_wait'].append(start-submitted)
                metrics[kind+'.owner_wall'].append(time.monotonic()-start)
                metrics[kind+'.owner_cpu'].append(time.thread_time()-cpu)
                if kind=='source_commit':metrics[kind+'.'+fn.__name__+'.owner_cpu'].append(time.thread_time()-cpu)
                counts[kind+'.db_changes']+=state.writer.db.total_changes-before
        # Match serve(): cancellation of a waiter cannot cancel accepted owner
        # work. Otherwise harness shutdown itself kills the authoritative actor.
        wrapped=asyncio.wrap_future(await admit(owner,execute,priority=priority))
        try:return await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            wrapped.add_done_callback(lambda f:f.exception() if not f.cancelled() else None)
            raise
    source=SelectiveSource(SimpleNamespace(identity=endpoint),None,token='offline')
    source.work=work;source.stop=asyncio.Event();source.batched=True;source.canonical_path=str(root/'canonical.sqlite')
    source.history_separated=refined
    decoder=ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'))
    await asyncio.gather(*(asyncio.wrap_future(decoder.submit(source_decoder_probe)) for _ in range(workers)))
    historian=HistoryExecutor();consumer=ThreadPoolExecutor(max_workers=1)
    source.preparation_executor=decoder;source.historical_executor=historian;source.delivery_executor=consumer
    if refined:
        from meme_machine.solana_history_notifications import install as notifications
        loop=asyncio.get_running_loop()
        await work(lambda s:notifications(install(s),loop,source.history_changed),0)
    def observe(kind,values):
        counts[kind]+=1
        if kind in ('evidence_timing','publication_timing'):
            for key in ('join_ready_monotonic','owner_claim_monotonic','durable_finished_monotonic',
                        'publication_started_monotonic','publication_finished_monotonic'):
                if key in values:metrics[kind+'.'+key].append(values[key])
            if kind=='evidence_timing':
                metrics['join_to_durable'].append(values['durable_finished_monotonic']-values['join_ready_monotonic'])
                preparation=values.get('preparation') or {}
                for key in ('cpu_seconds','wall_seconds','transfer_and_wait_seconds'):
                    if key in preparation:metrics['preparation.'+key].append(preparation[key]/values['durable_batch_frames'])
    source.observer=observe
    tasks=[asyncio.create_task(source.publish_history()),asyncio.create_task(source.candidate_history_delivery())]
    if refined:tasks.append(asyncio.create_task(source.source_reporting()))
    control=asyncio.Queue(maxsize=64);tasks.append(asyncio.create_task(source.control_commits(control)))
    subscriptions={};joins={};queues={};ws_ids={};early_logs=[];incoming_slots=set();raw_digest=hashlib.sha256()
    historical_metrics=[];demand_times={};peak_rss=0;probes=[];preparation_cpu=0
    async def history():
        nonlocal preparation_cpu
        while not source.stop.is_set():
            job=await work(lambda s:install(s).historical_tasks.claim(),4,label='history_dispatch')
            if job is None:await asyncio.sleep(.1);continue
            value=await asyncio.wrap_future(historian.submit(prepare_history,source.canonical_path,job))
            preparation_cpu+=value['metrics']['cpu_seconds']
            result=await work(lambda s:install(s).historical_tasks.apply(job,value),4,label='history_apply')
            if result is not False:
                historical_metrics.append(result)
                if job['id'] in demand_times:metrics['required_history_latency'].append(time.monotonic()-demand_times[job['id']])
    tasks.append(asyncio.create_task(history()))
    async def monitor():
        nonlocal peak_rss
        while not source.stop.is_set():
            start=time.monotonic();await work(lambda s:s.writer.db.execute('SELECT 1').fetchone(),0,label='urgent_probe')
            probes.append(time.monotonic()-start)
            pids=[os.getpid()]+list(decoder._processes or {})
            if historian.pool is not None:pids+=list(historian.pool._processes or {})
            rss=0
            for pid in pids:
                try:
                    for row in Path(f'/proc/{pid}/status').read_text().splitlines():
                        if row.startswith('VmRSS:'):rss+=int(row.split()[1])*1024
                except FileNotFoundError:pass
            peak_rss=max(peak_rss,rss);scratch.check();await asyncio.sleep(.25)
    tasks.append(asyncio.create_task(monitor()))
    async def commit(frame,sid):
        if frame is None:return
        if subscriptions[sid]['addresses']:
            incoming_slots.add(frame.update.block.slot);await queues[sid].put(frame)
        else:await control.put(frame)
    begun=time.monotonic();cpu=time.process_time();child0=resource.getrusage(resource.RUSAGE_CHILDREN)
    raw_decode=join_cpu=0.;obligation_start=None
    try:
        for ordinal,(meta,raw) in enumerate(frames(capture/'provider.frames.zlib')):
            if ordinal>=limit:break
            raw_digest.update(canonical(meta).encode());raw_digest.update(raw);counts['capture_records']+=1
            if meta['kind']=='subscribe':
                req=pb.SubscribeRequest.FromString(raw);sid=meta['id']
                addresses={a:program_scope(f) for f in ('pump','pumpswap') for a in meta['addresses'] if a==PROGRAMS[f]}
                subscriptions[sid]=dict(scout=bool(req.accounts),addresses=addresses)
                if not req.accounts:
                    joins[sid]=CandidateTransactionJoin(addresses,set(),clock=lambda:0.,filtered_from_slot=req.from_slot,max_join_seconds=120)
                    if addresses:
                        queues[sid]=CandidateCommitQueue()
                        tasks.append(asyncio.create_task(source.candidate_commits(queues[sid],addresses,sid,rolling=True)))
                        for slot,sig,logs,seen in early_logs:await commit(joins[sid].feed_log(slot,sig,logs,None,seen),sid)
                continue
            if meta['kind']=='websocket_open':continue
            if meta['kind']!='delivery':continue
            wall[0]=meta['seen'];counts['delivered_bytes']+=len(raw)
            await source.delivered(meta.get('family','shared'),meta['transport'],len(raw),wall[0])
            parse=time.thread_time()
            if meta['transport']=='yellowstone':update=pb.SubscribeUpdate.FromString(raw)
            else:value=json.loads(raw)
            raw_decode+=time.thread_time()-parse
            if meta['transport']=='yellowstone':
                sid=meta['id']
                if subscriptions[sid]['scout']:await work(lambda s,u=update:commit_scout(s,u,wall[0]),5,label='scout')
                else:
                    start=time.thread_time();frame=joins[sid].feed(update,len(raw),wall[0]);join_cpu+=time.thread_time()-start
                    await commit(frame,sid)
            elif 'params' in value:
                v=value['params']['result'];event=v['value']
                if event['err'] is not None:continue
                fact=(v['context']['slot'],event['signature'],event['logs'],wall[0])
                if not any(r['addresses'] for r in subscriptions.values()):early_logs.append(fact)
                for sid,join in joins.items():
                    if subscriptions[sid]['addresses']:
                        start=time.thread_time();frame=join.feed_log(fact[0],fact[1],fact[2],None,fact[3]);join_cpu+=time.thread_time()-start
                        await commit(frame,sid)
            await asyncio.sleep(0)
            for task in tasks:
                if task.done():task.result();raise RuntimeError('offline_worker_stopped')
        await asyncio.wait_for(asyncio.gather(control.join(),*(q.join() for q in queues.values())),60)
        # Identical explicit decision demands from candidates actually discovered
        # in this tape. They do not imply a qualified trade or new coverage.
        def demands(state):
            h=install(state);hi=h.db.execute('SELECT MAX(slot) FROM rolling_economic_events').fetchone()[0];ids=[]
            if hi is None:return ids
            for family,address,lo in h.db.execute('SELECT family,address,lower_slot FROM rolling_origins ORDER BY family,address LIMIT 4').fetchall():
                h.rolling.prepare(family,address,lo,hi,deadline=wall[0]+120,priority=3,reason='offline-identical-history-demand')
                ids.extend(r[0] for r in h.db.execute("SELECT id FROM rolling_preparation_jobs WHERE status='pending'"))
            return ids
        obligation_start=time.monotonic()
        for identity in await work(demands,3):demand_times[identity]=obligation_start
        last=None;unchanged=0
        for _ in range(240):
            state=await work(lambda s:(s.writer.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],
                s.writer.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0],
                s.writer.db.execute("SELECT COUNT(*) FROM rolling_preparation_jobs WHERE status IN ('pending','active')").fetchone()[0]),2)
            unchanged=unchanged+1 if last==state else 0;last=state
            if state==(0,0,0) or state[0]==state[2]==0 and unchanged>=4:break
            for task in tasks:
                if task.done():task.result();raise RuntimeError('offline_worker_stopped')
            await asyncio.sleep(.1)
        source.stop.set();source_end=time.monotonic()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        # Paths differ, canonical receipts and first availability must not.
        def final(state):
            h=install(state);tables={}
            for table,order,cols in [('rolling_economic_events','identity','identity,slot,signature,event_index,transaction_index,body,hash,first_seen'),
                ('candidate_lifecycle','family,address','family,address,state,epoch,first_slot,last_slot'),
                ('candidate_checkpoints','scope','scope,slot,receipt'),('candidate_coverage','scope,lo','scope,lo,hi,count,first_available,last_available,points,hash,lineage,source'),
                ('candidate_gaps','scope,lo,hi','scope,lo,hi,created,reason,repaired')]:
                tables[table]=h.db.execute('SELECT '+cols+' FROM '+table+' ORDER BY '+order).fetchall()
            obligations=h.db.execute("SELECT MIN(created),MIN(deadline),COUNT(*) FROM rolling_preparation_jobs WHERE status IN ('pending','active')").fetchone()
            def public(row):return [value.hex() if isinstance(value,bytes) else value for value in row]
            return {name:digest([public(row) for row in rows]) for name,rows in tables.items()},obligations,len(tables['rolling_economic_events'])
        projection,oldest,economic_count=await work(final,0)
        checkpoint_times=await work(lambda s:s.writer.db.execute(
            'SELECT scope,slot,receipt,updated FROM candidate_checkpoints ORDER BY scope').fetchall(),0)
        with sqlite3.connect(root/'solana-candidate-history.sqlite') as db:
            consumer_counts={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('source_receipts','canonical_event_refs','candidate_history_readiness')
                if db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone()}
        pending={sid:join.diagnostic() for sid,join in joins.items()}
    finally:
        source.stop.set()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await asyncio.to_thread(owner.close);await asyncio.to_thread(consumer.shutdown,wait=True)
        await asyncio.to_thread(historian.close);await asyncio.to_thread(decoder.shutdown,wait=True)
    child=resource.getrusage(resource.RUSAGE_CHILDREN)
    return dict(mode='refined' if refined else 'published_baseline',decoder_workers=workers,active_preparation_batches=1,
        source_files_sha256=source_hashes,checkpoint_update_times=checkpoint_times,
        raw_input_digest=raw_digest.hexdigest(),provider_calls=0,counts=dict(counts),economic_records=economic_count,
        projection=projection,consumer_counts=consumer_counts,pending_input_joins=pending,final_obligations=oldest,
        history_verdict_digest=digest(sorted(historical_metrics,key=canonical)),
        incoming_joined_slots=len(incoming_slots),full_path_seconds=source_end-begun,
        completed_slot_rate=len(incoming_slots)/(source_end-begun),parent_cpu=time.process_time()-cpu,
        child_cpu=(child.ru_utime+child.ru_stime)-(child0.ru_utime+child0.ru_stime),raw_parse_cpu=raw_decode,
        raw_join_cpu=join_cpu,historical_worker_cpu=preparation_cpu,group_rss_peak_bytes=peak_rss,
        sql_statements=sql['statements'],owner=owner.telemetry(),
        measurements={k:dict(count=len(v),total=sum(v),median=statistics.median(v),p95=percentile(v,.95),maximum=max(v)) for k,v in metrics.items()},
        urgent_probe_max_seconds=max(probes,default=None),limitations=[
            'Offline bounded prefix of retained October 8 raw delivery; missing joins remain missing.',
            'Deadline probes are owner scheduling checks, not native Pons/Pump protective quotations.',
            'Explicit four-candidate history demands compare the same retained obligations, not observed financial entries.',
            'Incoming slot rate is replay speed; it is not a new authenticated market capacity measurement.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--capture',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--refined',action='store_true')
    parser.add_argument('--workers',type=int,choices=(1,2),default=2);parser.add_argument('--limit',type=int,default=8000)
    args=parser.parse_args()
    from operational.tests import network_guard
    from meme_machine.operational.artifact_storage import Scratch
    network_guard()
    with Scratch() as scratch:
        root=scratch.path/'replay';root.mkdir()
        result=asyncio.run(asyncio.wait_for(replay(Path(args.capture),root,refined=args.refined,
            workers=args.workers,limit=args.limit,scratch=scratch),180))
        Path(args.output).write_text(json.dumps(result,indent=2)+'\n');scratch.success=True
        print(json.dumps({k:result[k] for k in ('mode','economic_records','incoming_joined_slots','completed_slot_rate','full_path_seconds','parent_cpu','child_cpu','group_rss_peak_bytes')}))


if __name__=='__main__':main()
