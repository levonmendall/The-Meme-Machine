"""Short deterministic carrier/safety gates. No pressure workload or provider calls."""
import asyncio,copy,gzip,json,sqlite3,tempfile,threading,unittest
from concurrent.futures import Future,ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from meme_machine import solana_evidence_service as service
from meme_machine.solana_evidence_plane import EvidenceUnavailable,EvidenceWriter
from meme_machine.solana_maintenance_runtime import ArchiveFlight
from meme_machine.solana_bounded_overlap import (prepare_and_write_archive,deep_bytes,
    ENCODED_CAP,BODY_CAP,FILE_CAP,fraction,select)
from tests.test_production_maintenance_arbiter import native_runtime,finalized_frontier
from tests.maintenance_production_harness import seed_book,rows,ingest,SCOPES,run_case,NativeCompletionPool

def count(state,key='archived_records'):
    row=state.writer.db.execute('SELECT value FROM counters WHERE key=?',(key,)).fetchone()
    return row[0] if row else 0

def step(runtime,flight):
    return runtime.turn(flight,runtime.monotonic())

def launch(state,runtime,flight):
    slot=flight.launch_slot()
    assert slot is not None
    future=Future()
    result=prepare_and_write_archive(state.writer.path,copy.deepcopy(slot.prepared))
    future.set_result(result);slot.attach(future,runtime.monotonic(),runtime.generation)
    return slot,result

def initial(state,runtime,clock,n=1200):
    seed_book(state,clock,hot=(n,0,0))
    flight=ArchiveFlight()
    for _ in range(8):
        step(runtime,flight)
        if flight.prepared is not None:return flight
    raise AssertionError('native arbiter did not select archive preparation')

class Focused(unittest.TestCase):
    def test_A_worker_executes_while_current_receipt_drains(self):
        with native_runtime() as (state,runtime,clock):
            flight=initial(state,runtime,clock)
            launch(state,runtime,flight)
            step(runtime,flight)  # commits 512 and selects disjoint lookahead
            self.assertEqual(count(state),512)
            self.assertIsNotNone(flight.pending);self.assertIsNotNone(flight.lookahead)
            entered=threading.Event();release=threading.Event()
            slot=flight.launch_slot();snapshot=copy.deepcopy(slot.prepared)
            native_rows=EvidenceWriter._archive_rows
            def bounded_rows(*args,**kwargs):
                for item in native_rows(*args,**kwargs):
                    if not entered.is_set():
                        # Real hash-checked preparation has begun inside the
                        # immutable worker, while the current SQL receipt exists.
                        entered.set()
                        if not release.wait(2):raise TimeoutError('unit barrier')
                    yield item
            def worker():
                with patch.object(EvidenceWriter,'_archive_rows',bounded_rows):
                    return prepare_and_write_archive(state.writer.path,snapshot)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(worker)
                slot.attach(future,clock.monotonic(),runtime.generation)
                self.assertTrue(entered.wait(1))
                try:
                    for _ in range(4):
                        step(runtime,flight)
                        if count(state)==750:break
                    self.assertEqual(count(state),750)
                    self.assertFalse(future.done())
                    self.assertIs(flight.future,future)
                    self.assertIsNone(flight.pending)
                    self.assertTrue(any(e['event']=='lookahead_promoted' and not e['commit_authoritative'] for e in flight.events))
                finally:release.set()
                future.result(2)
            step(runtime,flight)
            self.assertEqual(flight.peaks['executing_preparations'],1)

    def test_B_membership_and_committed_identities_are_exact_and_disjoint(self):
        with native_runtime() as (state,runtime,clock):
            flight=initial(state,runtime,clock)
            current=set(flight.membership)
            _,first=launch(state,runtime,flight)
            step(runtime,flight)
            lookahead=set(flight.lookahead.membership)
            self.assertFalse({i for i,h in current}&{i for i,h in lookahead})
            self.assertEqual(set((r['identity'],r['hash']) for r in first[0]),current)
            second_slot,second=launch(state,runtime,flight)
            expected=current|lookahead
            for _ in range(8):
                step(runtime,flight)
                if count(state)>=len(expected):break
                if flight.launch_slot() is not None:launch(state,runtime,flight)
            published=set()
            for receipt in (first[1],second[1]):
                path=state.writer.path.parent/(state.writer.path.name+'.archive')/receipt['name']
                for line in gzip.decompress(path.read_bytes()).splitlines():
                    row=json.loads(line);published.add((row['identity'],row['hash']))
            self.assertEqual(published,expected)
            self.assertGreaterEqual(count(state),len(expected))
            self.assertEqual(state.writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))

    def test_C_slot_record_worker_and_transaction_bounds(self):
        with native_runtime() as (state,runtime,clock):
            flight=initial(state,runtime,clock)
            self.assertEqual(flight.reservation,750)
            launch(state,runtime,flight)
            slices=[]
            native=state.writer.commit_archive
            def committed(plan,receipt):
                slices.append(len(plan));return native(plan,receipt)
            with patch.object(state.writer,'commit_archive',committed):
                step(runtime,flight)
                launch(state,runtime,flight)
                for _ in range(6):
                    step(runtime,flight)
                    if flight.launch_slot() is not None:launch(state,runtime,flight)
            self.assertTrue(slices);self.assertLessEqual(max(slices),512)
            self.assertLessEqual(flight.peaks['reserved_records'],1000)
            self.assertLessEqual(flight.peaks['slots'],2)
            self.assertLessEqual(flight.peaks['executing_preparations'],1)
            self.assertLessEqual(flight.peaks['parent_retained_bytes'],ENCODED_CAP)
            self.assertLessEqual(flight.peaks['serialized_arguments_reserved_bytes'],ENCODED_CAP)
            flight.lookahead=ArchiveFlight();flight.lookahead.lookahead=ArchiveFlight()
            with self.assertRaisesRegex(EvidenceUnavailable,'third_slot'):flight.check()

    def test_C_retained_full_plan_is_charged_after_partial_commit(self):
        with native_runtime() as (state,runtime,clock):
            flight=initial(state,runtime,clock)
            launch(state,runtime,flight);step(runtime,flight)
            self.assertEqual(len(flight.pending[0]),238)
            self.assertEqual(len(flight.full_plan),750)
            self.assertEqual(len(flight.membership),750)
            self.assertEqual(flight.check()['reserved_records'],1000)

    def test_C_oversized_snapshot_is_rejected_before_attachment(self):
        slot=ArchiveFlight(reservation=250)
        snapshot=dict(rows=[dict(identity='x',hash='h',encoded='x'*(6*1024*1024))],
                      chunks={},encoded_bytes=6*1024*1024)
        with self.assertRaisesRegex(EvidenceUnavailable,'encoded_reservation'):slot.hold(snapshot,'g',0)
        self.assertIsNone(slot.prepared);self.assertIsNone(slot.future)

    def test_D_stale_generation_cannot_commit_current_or_lookahead(self):
        with native_runtime() as (state,runtime,clock):
            flight=initial(state,runtime,clock);launch(state,runtime,flight);step(runtime,flight)
            before=count(state)
            state.fence.session='stale-generation'
            with self.assertRaisesRegex(EvidenceUnavailable,'generation_changed'):step(runtime,flight)
            self.assertEqual(count(state),before)

    def test_D_changed_pin_and_gap_are_rechecked_at_mutation(self):
        for mode in ('pin','gap'):
            with self.subTest(mode=mode),native_runtime() as (state,runtime,clock):
                flight=initial(state,runtime,clock,n=750);launch(state,runtime,flight)
                if mode=='pin':state.writer.interest('late',SCOPES[0],lower_slot=1000,priority=0,lifecycle='open')
                else:state.writer.gap(SCOPES[0],1000,2000,'injected_gap')
                for _ in range(4):step(runtime,flight)
                self.assertEqual(count(state),0)
                self.assertFalse(any(sum(e.get('durable_records',{}).values()) for e in runtime.ring))

    def test_D_worker_error_and_cancellation_do_not_create_progress(self):
        for cancelled in (False,True):
            with self.subTest(cancelled=cancelled),native_runtime() as (state,runtime,clock):
                flight=initial(state,runtime,clock,n=750)
                future=Future()
                if cancelled:future.cancel()
                else:future.set_exception(RuntimeError('injected worker failure'))
                flight.attach(future,clock.monotonic(),runtime.generation)
                with self.assertRaises(BaseException):step(runtime,flight)
                self.assertEqual(count(state),0);self.assertTrue(runtime.failure)
                self.assertEqual(runtime.arbiter.max_gap['archive'],0)

    def test_E_partial_commit_retry_and_duplicate_receipt_are_idempotent(self):
        with native_runtime() as (state,runtime,clock):
            flight=initial(state,runtime,clock)
            _,(plan,receipt)=launch(state,runtime,flight)
            duplicate=copy.deepcopy(plan)
            native=state.archive_commit_slice;once=[False]
            def interrupted(p,r):
                value=native(p,r)
                if not once[0]:
                    once[0]=True;raise EvidenceUnavailable('evidence_background_yield')
                return value
            with patch.object(state,'archive_commit_slice',interrupted):
                with self.assertRaisesRegex(EvidenceUnavailable,'background_yield'):step(runtime,flight)
                self.assertEqual(count(state),512)
                step(runtime,flight)
            for _ in range(8):
                step(runtime,flight)
                if count(state)==750:break
                if flight.launch_slot() is not None:launch(state,runtime,flight)
            before=count(state)
            for part in (duplicate[:512],duplicate[512:]):state.writer.commit_archive(part,receipt)
            self.assertEqual(count(state),before)
            self.assertEqual(sum(sum(e.get('durable_records',{}).values()) for e in runtime.ring),before)
            self.assertFalse(runtime.failure)

    def test_F_promotion_keeps_submission_and_original_recovery_clocks(self):
        with native_runtime() as (state,runtime,clock):
            flight=initial(state,runtime,clock,n=2200)
            episodes=dict(runtime.episodes)
            launch(state,runtime,flight);step(runtime,flight)
            look,_=launch(state,runtime,flight);submitted=look.submitted
            for _ in range(4):
                step(runtime,flight)
                if flight.reservation==250:break
            self.assertEqual(flight.submitted,submitted)
            for key,prior in episodes.items():
                if key in runtime.episodes:self.assertEqual(runtime.episodes[key],prior)
            self.assertEqual(runtime.leases.owner,3)
            self.assertEqual(runtime.leases.execution,3)
            self.assertEqual(runtime.leases.worker,15)

    def test_F_unfinished_lookahead_expires_from_original_submit(self):
        with native_runtime() as (state,runtime,clock):
            flight=initial(state,runtime,clock);launch(state,runtime,flight);step(runtime,flight)
            slot=flight.launch_slot();future=Future()
            slot.attach(future,clock.monotonic(),runtime.generation)
            clock.advance(16)
            with self.assertRaisesRegex(EvidenceUnavailable,'worker_lease_exceeded'):step(runtime,flight)
            self.assertEqual(count(state),512);self.assertTrue(runtime.failure)

    def test_G_restart_keeps_durable_commits_and_original_episodes(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db'
            with native_runtime(path=path) as (state,runtime,clock):
                flight=initial(state,runtime,clock,n=2200)
                launch(state,runtime,flight);step(runtime,flight)
                before=count(state);episodes=dict(runtime.episodes)
                receipts=list(state.writer.db.execute('SELECT * FROM archives'))
                self.assertEqual(before,512)
            with native_runtime(clock=clock,path=path) as (state,runtime,clock):
                self.assertEqual(count(state),before)
                self.assertEqual(runtime.episodes,episodes)
                self.assertEqual(list(state.writer.db.execute('SELECT * FROM archives')),receipts)
                self.assertEqual(state.writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))

    def test_H_native_arbiter_controls_retirement_and_source_frontiers(self):
        with native_runtime() as (state,runtime,clock):
            seed_book(state,clock,hot=(1200,0,0),retired=(1200,0,0))
            flight=ArchiveFlight()
            for i in range(18):
                finalized_frontier(state,clock,SCOPES[0],slot=2_000_000+i)
                step(runtime,flight)
                if flight.launch_slot() is not None:launch(state,runtime,flight)
            self.assertGreater(count(state),1200)
            self.assertGreater(count(state,'compacted_records'),0)
            self.assertIsNone(runtime.arbiter.pending)
            frontier=json.loads(state.writer.db.execute('SELECT value FROM service_health WHERE key=?',('finalized_frontier:'+SCOPES[0],)).fetchone()[0])
            self.assertGreater(frontier['slot'],2_000_000)
            self.assertTrue(any(e['selected']=='retirement' for e in runtime.ring))
            self.assertTrue(any(e['selected']=='archive' for e in runtime.ring))

class ServeShutdown(unittest.IsolatedAsyncioTestCase):
    async def test_G_actual_serve_shutdown_joins_jobs_and_keeps_durable_manifests(self):
        class Pool(NativeCompletionPool):
            def submit(self,fn,*args,**kwargs):
                # A process-like private argument copy: native preparation and
                # immutable publication still execute; only completion is deterministic.
                if fn.__name__=='prepare_and_write_archive':
                    args=(args[0],copy.deepcopy(args[1]))
                return super().submit(fn,*args,**kwargs)
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(1200,0,0)),
                           turns=10,pool_class=Pool)
        self.assertFalse(box['errors'],[str(e) for e in box['errors']])
        self.assertEqual(box['integrity'],'ok')
        self.assertGreater(box['counters'].get('archived_records',0),0)
        self.assertTrue(box['owner'].closed)
        self.assertFalse(box['owner'].thread.is_alive())
        self.assertIsNone(box['runtime'].arbiter.pending)

if __name__=='__main__':unittest.main()
