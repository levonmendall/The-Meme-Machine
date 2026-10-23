"""Matched normalized Pump pipeline with real owner planning and checkpoint I/O.

The market parcel remains authenticated and unmodified. A separately declared
synthetic namespace supplies planner obligations and quiet startup control; none
of the parcel's visibility-unproven context is promoted into recovery evidence.
This provider-free engineering comparison cannot certify native acquisition,
Pons, full approved strategy execution, financial readiness or live capacity.
"""
import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager, ExitStack
import hashlib
import importlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from unittest.mock import patch

from engineering.diagnostics import replay_concurrent_pump_window as pipeline
from engineering.diagnostics import replay_original_pump_window as original


SCHEMA = 'owner-pipeline-comparison-v1'
PROFILES = {
    'component': dict(retained=8, eligible=4, jobs=8),
    'representative': dict(retained=2048, eligible=128, jobs=512),
}
PREFIX = 'owner-pipeline-fixture-'
LATENCY_BUCKETS = (.001, .005, .01, .05, .1, .5, 1., 5.)


class _EvidenceClock:
    """Fixed evidence wall time; real monotonic cadence and I/O clocks remain."""
    def __init__(self, at):self.at = at
    def time(self):return self.at
    def __getattr__(self, name):return getattr(time, name)


@contextmanager
def evidence_clock(at):
    # These production modules compare absolute evidence deadlines with wall
    # time directly. Match their clock to the actual replay history/reader;
    # never accelerate the 100-ms planner or physical checkpoint scheduling.
    modules = [importlib.import_module('meme_machine.solana_selective_source')]
    try:modules.append(importlib.import_module('meme_machine.solana_candidate_development'))
    except ModuleNotFoundError as error:
        if error.name != 'meme_machine.solana_candidate_development':raise
    with ExitStack() as stack:
        for module in modules:stack.enter_context(patch.object(module,'time',_EvidenceClock(at)))
        yield


class OwnerWorkload:
    def __init__(self, *, profile, clock, seconds):
        original.need(profile in PROFILES, 'owner_pipeline_profile')
        self.profile, self.population, self.clock = profile, PROFILES[profile], clock
        self.seconds = seconds
        self.workers, self.worker, self.owner, self.source = [], None, None, None
        self.initial, self.expected = None, None
        self.last_outcome, self.intake_finished = None, False
        self.progress = asyncio.Event()
        self.counts = Counter()
        self.urgent_histogram = [0] * (len(LATENCY_BUCKETS)+1)
        self.urgent_total = self.urgent_peak = 0.
        self.physical_wall_ns = self.physical_cpu_ns = self.physical_calls = 0
        self.physical_lock = threading.Lock()

    async def bind(self, owner, source, config, loop):
        from meme_machine import solana_checkpoint
        self.owner, self.source, self.config = owner, source, config
        source.batched = True
        source.config.credential = 'offline'
        source.canonical_path = str(config.evidence)
        self.progress = asyncio.Event()
        original_work = source.work

        async def observed(fn, priority=1, **options):
            value = await original_work(fn, priority, **options)
            if options.get('label') == 'candidate_development':
                self.counts['planning_callbacks'] += 1
                if not self.intake_finished:
                    self.counts['planning_before_intake_finished'] += 1
                self.last_outcome = ('IDLE' if value is None else
                    'DISPATCH' if type(value) is tuple else getattr(value, 'state', None))
                original.need(self.last_outcome in ('IDLE', 'DEFERRED', 'DISPATCH'),
                              'owner_pipeline_planning_outcome')
                self.progress.set()
            return value
        source.work = observed

        async def refused(*args, **options):
            self.counts['refused_archive_dispatch'] += 1
            raise ValueError('original_window_owner_pipeline_unexpected_archive_dispatch')
        source.measured_rpc = refused
        worker_type = getattr(solana_checkpoint, 'CheckpointWorker', None)
        self.worker = None if worker_type is None else worker_type(owner, config.evidence)
        if self.worker is not None:
            await asyncio.shield(asyncio.wrap_future(self.worker.ready))

    async def seed(self):
        """Real disposable proofs/receipts for fixture slot100, never old ACKs."""
        from meme_machine.solana_evidence_plane import IntervalProof, digest, canonical
        from meme_machine.solana_rolling_history import program_scope
        from meme_machine.solana_selective_runtime import CONTROL
        from meme_machine.solana_history_work import HistoricalTasks
        at = self.clock

        def seed(state):
            h = state.selective
            h.startup.begin()
            for family in ('pump', 'pumpswap'):
                h.startup.feed_ack(family, 100, 100)
            h.startup.native(('pump', 'pumpswap'))
            def proof(scope):
                return IntervalProof(scope, 100, 100, 'alchemy_finalized_stream',
                    h.endpoint_identity, dict(finalized=True, complete=True, scope=scope,
                        lower_slot=100, upper_slot=100, lineage_hash=digest([scope,100,100]),
                        engineering_fixture_only=True), at)
            h.writer.ingest([], proof=proof(CONTROL))
            # Actual synchronous fixture FULL/ACK precedes the measured source.
            # No retained terminal, receipt or visibility-unproven row is used.
            separated = h.lifecycle.delivery_separated
            try:
                h.lifecycle.delivery_separated = False
                for family in ('pump', 'pumpswap'):
                    h.lifecycle.defer_proof(proof(program_scope(family)))
                h.lifecycle.publish()
            finally:
                h.lifecycle.delivery_separated = separated
            original.need(h.startup.advance()['released'], 'owner_pipeline_fixture_startup')
            h.historical_tasks = HistoricalTasks(h)
            expected = dict(eligible=[], expired=[], covered=[], local=[], deadlines={})
            with h.writer.transaction():
                for index in range(self.population['retained']):
                    address = PREFIX+'retained-'+str(index)
                    h.observe('pump', address, slot=100, signature='', seen=at-120,
                        fields=dict(development_upper_bps=9000))
                    h.bind('pump', address)
                for index in range(self.population['eligible']):
                    address = PREFIX+'eligible-'+str(index)
                    h.observe('pump', address, slot=100, signature='', seen=at-10,
                        fields=dict(development_upper_bps=9000))
                    expected['eligible'].append(address)
                for index in range(self.population['jobs']):
                    family = 'pump' if index % 2 else 'pumpswap'
                    address = PREFIX+'job-'+str(index)
                    h.observe(family, address, slot=100, signature='', seen=at-5, fields={})
                    h.bind(family, address)
                    expired, covered = index % 4 == 0, index % 4 == 3
                    lo, hi = (100,100) if covered else (101,103)
                    deadline = at-1 if expired else at+150
                    identity = h.request(family, address, lo, hi,
                        priority=1 if covered else 3, deadline=deadline)
                    expected['deadlines'][identity] = deadline
                    if expired:expected['expired'].append(identity)
                    if covered:expected['covered'].append(identity)
                    if index % 4 == 2:expected['local'].append((family,address,lo,hi))
                    if index % 4 == 1:
                        h.db.execute('UPDATE acquisition_jobs SET error=? WHERE id=?',
                            (canonical(dict(kind='archive_provider_failure',retry_after=at+60)),identity))
            self.expected = expected
            return self.snapshot(state)
        self.initial = await self.source.work(seed, 0, label='health_scheduler')

    def snapshot(self, state):
        from meme_machine.solana_evidence_plane import canonical
        h, expected = state.selective, self.expected
        jobs = h.db.execute('SELECT id,status,deadline,priority,lo,hi,token,pages FROM acquisition_jobs '
            'WHERE address LIKE ? ORDER BY id', (PREFIX+'%',)).fetchall()
        by_id = {row[0]:row for row in jobs}
        bindings = [row[0] for row in h.db.execute('SELECT address FROM evidence_bindings '
            "WHERE family='pump' AND address LIKE ? ORDER BY address",(PREFIX+'%',))]
        plans = {tuple(row) for row in h.db.execute("SELECT json_extract(body,'$.family'),"
            "json_extract(body,'$.address'),json_extract(body,'$.lo'),json_extract(body,'$.hi') "
            "FROM rolling_preparation_jobs WHERE json_extract(body,'$.address') LIKE ? "
            "AND json_extract(body,'$.kind') IS NULL",(PREFIX+'%',))}
        complete = (all(address in bindings for address in expected['eligible']) and
            all(by_id[key][1]=='deadline_missed' for key in expected['expired']) and
            all(by_id[key][1]=='complete' for key in expected['covered']) and
            all(tuple(key) in plans for key in expected['local']))
        deadlines = all(by_id[key][2]==value for key,value in expected['deadlines'].items())
        body = dict(jobs=jobs, bindings=bindings, local_plans=sorted(plans))
        return dict(complete=complete, deadlines_preserved=deadlines,
            semantic_sha256=hashlib.sha256(canonical(body).encode()).hexdigest(),
            jobs=len(jobs), bindings=len(bindings), local_plans=len(plans),
            nonexpired_pending_jobs=sum(row[1]=='pending' and row[2]>self.clock for row in jobs),
            deadline_missed_jobs=sum(row[1]=='deadline_missed' for row in jobs),
            complete_jobs=sum(row[1]=='complete' for row in jobs),
            inflight=len(getattr(state,'acquisition_inflight',())),
            preparation_tickets=len(getattr(h,'_archive_preparation_tickets',{})),
            transaction_open=h.db.in_transaction,
            synchronous=h.db.execute('PRAGMA synchronous').fetchone()[0],
            active_families=list(h.active_families))

    async def checkpoints(self):
        from meme_machine import solana_checkpoint
        while not self.source.stop.is_set():
            kwargs = {} if self.worker is None else dict(worker=self.worker)
            await solana_checkpoint.reclaim_at_boundary(self.owner,self.config.evidence,**kwargs)
            self.counts['checkpoint_calls'] += 1
            if not self.intake_finished:self.counts['checkpoint_before_intake_finished'] += 1
            try:await asyncio.wait_for(self.source.stop.wait(), 1.)
            except TimeoutError:pass

    async def urgent(self):
        while not self.source.stop.is_set():
            queued = time.monotonic()
            def probe(state):
                original.need(threading.get_ident()==self.owner.thread.ident,
                              'owner_pipeline_probe_thread')
                return time.monotonic()-queued
            latency = await self.source.work(probe, 0, label='health_scheduler')
            self.counts['urgent_probes'] += 1
            self.urgent_total += latency; self.urgent_peak = max(self.urgent_peak,latency)
            bucket = next((i for i,value in enumerate(LATENCY_BUCKETS) if latency<=value),len(LATENCY_BUCKETS))
            self.urgent_histogram[bucket] += 1
            try:await asyncio.wait_for(self.source.stop.wait(), .1)
            except TimeoutError:pass

    def start(self):
        self.workers = [asyncio.create_task(self.source.acquire()),
            asyncio.create_task(self.checkpoints()),asyncio.create_task(self.urgent())]
        return self.workers

    async def finish(self):
        # An earlier idle callback cannot certify the work admitted afterwards.
        # Require another real owner planning result after intake/reader drain.
        self.last_outcome = None
        while True:
            self.progress.clear()
            cut = await self.source.work(self.snapshot, 2, label='health_scheduler')
            if cut['complete'] and self.last_outcome=='IDLE':return
            await self.progress.wait()

    def close_worker(self):
        if self.worker is not None:
            self.worker.close(); self.worker = None

    @contextmanager
    def physical_probe(self):
        from meme_machine import solana_checkpoint
        actual = solana_checkpoint.checkpoint_and_reclaim
        def measured(path):
            started,cpu = time.perf_counter_ns(),time.thread_time_ns()
            try:return actual(path)
            finally:
                wall,used = time.perf_counter_ns()-started,time.thread_time_ns()-cpu
                with self.physical_lock:
                    self.physical_calls += 1; self.physical_wall_ns += wall; self.physical_cpu_ns += used
        with patch.object(solana_checkpoint,'checkpoint_and_reclaim',measured):yield

    async def cut(self):
        final = await self.source.work(self.snapshot,0,label='health_scheduler')
        original.need(final['complete'] and final['deadlines_preserved'] and
            final['inflight']==final['preparation_tickets']==0 and
            not final['transaction_open'] and final['synchronous']==2,'owner_pipeline_final_state')
        original.need(self.counts['refused_archive_dispatch']==0 and
            self.counts['planning_callbacks']>0 and self.counts['checkpoint_calls']>0 and
            self.counts['urgent_probes']>0,'owner_pipeline_work_not_exercised')
        telemetry = self.owner.telemetry()
        held = telemetry.get('checkpoint_handoff_total_us')
        return dict(profile=self.profile,population=dict(self.population),
            cohort_sha256=hashlib.sha256(original.canonical(self.expected)).hexdigest(),
            fixture_scope='SYNTHETIC_QUIET_STARTUP_AND_PENDING_JOBS_NOT_ORIGINAL_RECOVERY',
            initial=self.initial,final=final,counters=dict(self.counts),
            owner_telemetry=telemetry,
            urgent_latency=dict(probes=self.counts['urgent_probes'],total_seconds=self.urgent_total,
                peak_seconds=self.urgent_peak,upper_bounds_seconds=list(LATENCY_BUCKETS),
                histogram=list(self.urgent_histogram)),
            checkpoint=dict(physical_calls=self.physical_calls,
                physical_wall_seconds=self.physical_wall_ns/1e9,
                physical_thread_cpu_seconds=self.physical_cpu_ns/1e9,
                token_total_microseconds=held,
                token_peak_microseconds=telemetry.get('checkpoint_handoff_peak_us'),
                token_minus_physical_seconds=None if held is None else held/1e6-self.physical_wall_ns/1e9,
                scope='REAL_HANDOFF_AND_PHYSICAL_IO_COMPLETE_BEFORE_CUT_QUANTIZED_TOKEN_CLOCK'))


def metrics(run, measured_events):
    seconds = run['timing']['wall_nanoseconds']/1e9
    cpu = run['timing']['process_cpu_nanoseconds']/1e9
    progress = run['controlled_batch_progress']
    debt = [row['admitted']-(row['observed'] or 0) for row in progress]
    owner = run['owner_counters']
    occupied_us = sum(value for name,value in owner.items()
        if name.startswith('owner.priority') and name.endswith('.execution_total_microseconds'))
    occupied_cpu_us = sum(value for name,value in owner.items()
        if name.startswith('owner.priority') and name.endswith('.execution_cpu_total_microseconds'))
    return dict(process_cpu_seconds_per_measured_input=cpu/measured_events,
        measured_input_events=measured_events,wall_seconds=seconds,
        classified_native_observations=run['final']['durably_observed_native_events'],
        classified_native_observations_per_second=run['final']['durably_observed_native_events']/seconds,
        full_approved_strategy_evaluations=0,full_approved_strategy_scope='UNEXERCISED',
        actual_full_qualifications=run['final']['full_qualifications'],
        actual_full_qualifications_per_second=run['final']['full_qualifications']/seconds,
        owner_execution_wall_seconds=occupied_us/1e6,owner_execution_wall_fraction=occupied_us/1e6/seconds,
        owner_execution_cpu_seconds=occupied_cpu_us/1e6,
        owner_execution_cpu_seconds_per_measured_input=occupied_cpu_us/1e6/measured_events,
        sampled_native_debt_peak=max(debt,default=0),sampled_native_debt_at_intake_end=debt[-1] if debt else 0,
        final_native_debt=run['final']['native_event_backlog'],
        sampled_debt_scope='AFTER_ADMITTED_BATCH_WITH_LATEST_COMPLETED_READER_SNAPSHOT_NOT_CONTINUOUS_MAX',
        admission_progress=progress,
        warmup_processing_included_in_cpu_and_observation_rate=True,
        provider_requests=0,financial_authority=False)


def benchmark(parcel,directory,*,profile='representative',batch=64,rate=2000,seconds=120):
    from meme_machine.runtime.evidence_worker import owner_thread_fairness
    pipeline.limits(batch,rate,seconds)
    original.need(profile in PROFILES,'owner_pipeline_profile')
    directory=Path(directory).absolute()
    original.need(directory.parent.resolve(strict=True)==directory.parent and not directory.exists(),
                  'new_output_required')
    records,batches,_=pipeline.freeze(parcel,batch)
    at=max(row['first_seen'] for row in parcel.inputs)
    directory.mkdir(mode=0o700); previous_umask=os.umask(0o077)
    workload=OwnerWorkload(profile=profile,clock=at,seconds=seconds)
    try:
        # Same source-defined operational family pause as the funding-closed
        # diagnostic. Neither quotes, old ACKs nor financial permissions exist.
        with original.no_network(), owner_thread_fairness(), evidence_clock(at), patch.dict(os.environ,
                MM_OPERATIONAL_PHASE='OBSERVATION',MM_SOLANA_HISTORY_SEPARATED='1',
                MM_OPERATION_COST_DIAGNOSTICS='1'), workload.physical_probe():
            run=asyncio.run(pipeline.run_arm(parcel,records,batches,directory/'pipeline',
                concurrent=True,rate=rate,seconds=seconds,owner_workload=workload))
        parcel.unchanged()
        original.need(run['final']['native_event_backlog']==0 and
            run['reader_restart_verified'] and run['owner_actor_restart_verified'],
            'owner_pipeline_recovery_equivalence')
        return dict(schema=SCHEMA,engineering_validation_passed=True,source=parcel.manifest['source'],
            source_manifest_sha256=parcel.manifest_fingerprint[1],input_parcel_sha256=parcel.fingerprint[1],
            selected_events=len(parcel.measured),input_events=len(parcel.inputs),
            input_provenance='public_fixture' if 'fixture' in parcel.manifest['source'] else 'authenticated_original_parcel',
            consumer_source_sha256=original.sha(Path(__file__).read_bytes()),
            concurrent_consumer_sha256=original.sha(Path(pipeline.__file__).read_bytes()),
            run=run,metrics=metrics(run,len(parcel.measured)),
            schedule=dict(batch=batch,offered_events_per_second=rate,seconds=seconds,
                arrival_queue_batches=pipeline.ARRIVAL_BATCHES,checkpoint_interval_seconds=1,
                fixed_availability_and_decision_clock=at,planner_profile=profile),
            original_inputs_unchanged=True,context_rows_imported_as_state=0,
            native_acquisition_join_repair_exercised=False,pons_wire_processing_exercised=False,
            full_strategy_equivalence_proven=False,throughput_readiness_proven=False,
            financial_authority=False,provider_requests=0)
    finally:os.umask(previous_umask)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    inputs=parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--parcel',type=Path);inputs.add_argument('--public-fixture',action='store_true')
    parser.add_argument('--manifest-sha256');parser.add_argument('--new-output-directory',required=True,type=Path)
    parser.add_argument('--profile',choices=tuple(PROFILES),default='representative')
    parser.add_argument('--batch',type=int,default=64);parser.add_argument('--rate',type=float,default=2000)
    parser.add_argument('--seconds',type=float,default=120);parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args();pipeline.limits(args.batch,args.rate,args.seconds)
    original.need(os.geteuid()!=0,'unprivileged_consumer_required')
    original.need(bool(args.parcel)==bool(args.manifest_sha256),'concurrent_manifest_pin')
    if not args.worker:
        from meme_machine.operational.artifact_storage import Scratch
        output=args.new_output_directory.absolute()
        original.need(output.parent.resolve(strict=True)==output.parent and not output.exists(),'new_output_required')
        with Scratch() as scratch:
            target=scratch.path/'owner-pipeline'
            command=[sys.executable,'-m','engineering.diagnostics.replay_owner_pipeline','--worker',
                '--new-output-directory',str(target),'--profile',args.profile,'--batch',str(args.batch),
                '--rate',str(args.rate),'--seconds',str(args.seconds)]
            command+=(['--parcel',str(args.parcel.absolute()),'--manifest-sha256',args.manifest_sha256]
                if args.parcel else ['--public-fixture'])
            child=subprocess.Popen(command,start_new_session=True,stdout=subprocess.DEVNULL)
            try:
                until=time.monotonic()+2*args.seconds
                while child.poll() is None:
                    scratch.check();original.need(time.monotonic()<until,'owner_pipeline_worker_deadline');time.sleep(.25)
                original.need(child.returncode==0,'owner_pipeline_worker_failed_retained_scratch')
                scratch.check()
                fd=os.open(target/'report.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
                with os.fdopen(fd,'rb') as stream:raw=stream.read(32*1024**2+1)
                original.need(len(raw)<=32*1024**2,'report_bound')
                result=original.loads(raw);original.need(result['schema']==SCHEMA,'owner_pipeline_report_binding')
                output.mkdir(mode=0o700);original._report(output/'report.json',raw);scratch.success=True
            finally:
                if child.poll() is None:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
    else:
        if args.public_fixture:
            from tests.test_original_pump_window_replay import CapturedParcel
            parcel=CapturedParcel()
        else:parcel=original.Parcel(args.parcel,args.manifest_sha256)
        result=benchmark(parcel,args.new_output_directory,profile=args.profile,
            batch=args.batch,rate=args.rate,seconds=args.seconds)
        original._report(args.new_output_directory/'report.json',original.canonical(result)+b'\n')
    print(json.dumps(dict(schema=SCHEMA,engineering_validation_passed=True,
        selected_events=result['selected_events'],financial_authority=False),sort_keys=True))
    return 0


if __name__=='__main__':raise SystemExit(main())
