"""Actual semaphore-free spawned workers; no provider or financial state."""
from concurrent.futures.process import BrokenProcessPool
import multiprocessing.synchronize
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.runtime.isolated_native_executor import (
    IsolatedSpawnExecutor, NativeExecutorCapacityError,
)
from meme_machine.runtime.isolated_native_execution import install_isolated_native_execution


def no_semaphores(*args, **kwargs):
    raise AssertionError('named semaphore forbidden')


def guarded_initializer():
    install_isolated_native_execution()
    multiprocessing.synchronize.SemLock.__init__ = no_semaphores


def probe(value=1, seconds=0):
    from meme_machine.runtime.isolated_native_execution import financial_writes_denied
    time.sleep(seconds)
    return os.getpid(), financial_writes_denied(), value


def crash():
    os._exit(7)


def native_failure():
    from meme_machine.solana_evidence_plane import EvidenceUnavailable
    raise EvidenceUnavailable('original-native-failure')


def echo(value):
    return value


def oversized_product():
    from meme_machine.runtime.isolated_native_executor import MAX_FRAME_BYTES
    return b'x'*(MAX_FRAME_BYTES+1)


def gated_initializer():
    """A real spawn initializer held by a disposable test file, never a lock."""
    guarded_initializer()
    until=time.monotonic()+5
    while not Path(os.environ['MM_OFFLINE_EXECUTOR_RELEASE']).exists():
        if time.monotonic()>=until:raise RuntimeError('offline initializer release missing')
        time.sleep(.005)


def _signal_child():
    import json
    stopped=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopped.set())
    decoder=IsolatedSpawnExecutor(max_workers=2,initializer=guarded_initializer,role='decoder')
    history=IsolatedSpawnExecutor(max_workers=1,initializer=guarded_initializer,role='history')
    futures=[decoder.submit(probe,index,.2) for index in range(2)]
    futures.append(history.submit(probe,3,.2))
    until=time.monotonic()+5
    while not all(f.running() for f in futures) and time.monotonic()<until:time.sleep(.005)
    if not all(f.running() for f in futures):raise RuntimeError('workers not dispatched')
    print('ready',flush=True)
    if not stopped.wait(5):raise RuntimeError('missing test SIGTERM')
    decoder.shutdown(wait=True,cancel_futures=True)
    history.shutdown(wait=True,cancel_futures=True)
    print(json.dumps(dict(joined=all(not p.is_alive() for pool in (decoder,history)
        for p in pool._processes.values()),completed=sum(f.done() for f in futures))),flush=True)


class PipeExecutorTests(unittest.TestCase):
    def pool(self, role='history'):
        pool = IsolatedSpawnExecutor(max_workers=2 if role=='decoder' else 1,
            initializer=guarded_initializer, role=role)
        self.addCleanup(pool.shutdown, wait=True, cancel_futures=True)
        return pool

    def test_constructor_is_inert_and_first_submit_failure_keeps_owned_threads(self):
        with patch('multiprocessing.get_context',side_effect=AssertionError('eager child setup')):
            pool=self.pool('decoder')
        self.assertEqual(pool._processes,{})
        self.assertEqual(pool._threads,[])
        original=threading.Thread.start
        started=0
        def second_owner_fails(thread):
            nonlocal started
            if thread.name.startswith('isolated-native-result-'):
                started+=1
                if started==2:raise RuntimeError('offline owner start failure')
            return original(thread)
        with patch.object(threading.Thread,'start',second_owner_fails):
            with self.assertRaisesRegex(BrokenProcessPool,'worker_start_failed'):
                pool.submit(probe)
        self.assertTrue(pool._broken)
        self.assertEqual(len(pool._processes),2)
        self.assertEqual(len(pool._items),0) # No Future was accepted then lost.
        pool.shutdown(wait=True,cancel_futures=True)
        self.assertTrue(all(not p.is_alive() for p in pool._processes.values()))
        self.assertTrue(all(not t.is_alive() for t in pool._threads))

    def test_partial_start_denied_terminate_keeps_references_for_outer_drain(self):
        from multiprocessing.process import BaseProcess
        with tempfile.TemporaryDirectory() as tmp:
            release=Path(tmp)/'release'
            with patch.dict(os.environ,MM_OFFLINE_EXECUTOR_RELEASE=str(release)):
                pool=IsolatedSpawnExecutor(max_workers=2,initializer=gated_initializer,role='decoder')
                self.addCleanup(pool.shutdown,wait=True,cancel_futures=True)
                original=threading.Thread.start;started=0
                def second_owner_fails(thread):
                    nonlocal started
                    if thread.name.startswith('isolated-native-result-'):
                        started+=1
                        if started==2:raise RuntimeError('offline owner start failure')
                    return original(thread)
                try:
                    with patch.object(threading.Thread,'start',second_owner_fails),\
                            patch.object(BaseProcess,'terminate',side_effect=PermissionError('denied')):
                        with self.assertRaises(BrokenProcessPool):pool.submit(probe)
                    self.assertTrue(pool._termination_failed)
                    self.assertTrue(any(p.is_alive() for p in pool._processes.values()))
                    self.assertEqual(len(pool._items),0)
                finally:release.touch()
                pool.shutdown(wait=True,cancel_futures=True)
                self.assertTrue(all(not p.is_alive() for p in pool._processes.values()))
                self.assertTrue(all(not t.is_alive() for t in pool._threads))

    def test_real_two_spawn_workers_without_any_semlock_and_deny_context(self):
        with patch.object(multiprocessing.synchronize.SemLock, '__init__', no_semaphores):
            pool=self.pool('decoder')
            jobs=[pool.submit(probe,index,.05) for index in range(2)]
            rows=[job.result(5) for job in jobs]
            self.assertEqual(len({row[0] for row in rows}),2)
            self.assertTrue(all(row[0]!=os.getpid() and row[1] for row in rows))
            self.assertEqual([row[2] for row in rows],[0,1])
            pool.shutdown()
            self.assertTrue(all(not process.is_alive() for process in pool._processes.values()))
            self.assertTrue(all(not thread.is_alive() for thread in pool._threads))

    def test_pending_cancel_and_running_completion_remain_distinct(self):
        pool=self.pool()
        first=pool.submit(probe,1,.3)
        until=time.monotonic()+5
        while not first.running() and time.monotonic()<until:time.sleep(.005)
        self.assertTrue(first.running())
        self.assertFalse(first.cancel())
        second=pool.submit(probe,2)
        self.assertTrue(second.cancel())
        third=pool.submit(probe,3)
        self.assertEqual(first.result(5)[2],1)
        self.assertEqual(third.result(5)[2],3)
        self.assertTrue(second.cancelled())

    def test_shutdown_cancels_queued_work_and_joins_accepted_task(self):
        pool=self.pool()
        first=pool.submit(probe,1,.15)
        until=time.monotonic()+5
        while not first.running() and time.monotonic()<until:time.sleep(.005)
        pending=pool.submit(probe,2)
        pool.shutdown(wait=True,cancel_futures=True)
        self.assertEqual(first.result()[2],1)
        self.assertTrue(pending.cancelled())
        with self.assertRaises(RuntimeError):pool.submit(probe)

    def test_native_exception_type_and_traceback_are_preserved_without_breaking_pool(self):
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        pool=self.pool()
        with self.assertRaisesRegex(EvidenceUnavailable,'original-native-failure') as caught:
            pool.submit(native_failure).result(5)
        self.assertIn('native_failure',str(caught.exception.__cause__))
        self.assertEqual(pool.submit(probe,9).result(5)[2],9)

    def test_worker_crash_breaks_all_work_and_history_owner_replaces_generation(self):
        from meme_machine.solana_history_work import HistoryExecutor
        with patch('meme_machine.runtime.isolated_native_resources.require_resources'):
            owner=HistoryExecutor(native_resources=object())
        self.addCleanup(owner.close)
        old_pid=owner.submit(probe).result(5)[0]
        with self.assertRaises(BrokenProcessPool):owner.submit(crash).result(5)
        new_pid=owner.submit(probe).result(5)[0]
        self.assertNotEqual(old_pid,new_pid)
        self.assertIsInstance(owner.pool,IsolatedSpawnExecutor)

    def test_idle_worker_death_is_detected_and_peer_is_stopped(self):
        pool=self.pool('decoder')
        rows=[pool.submit(probe,index,.02) for index in range(2)]
        for row in rows:row.result(5)
        next(iter(pool._processes.values())).terminate()
        until=time.monotonic()+5
        while not pool._broken and time.monotonic()<until:time.sleep(.005)
        self.assertTrue(pool._broken)
        with self.assertRaises(BrokenProcessPool):pool.submit(probe)
        pool.shutdown()
        self.assertTrue(all(not process.is_alive() for process in pool._processes.values()))

    def test_crash_cancellation_race_cannot_strand_other_future_or_owner(self):
        pool=self.pool('decoder')
        accepted=[pool.submit(probe,index,2) for index in range(2)]
        until=time.monotonic()+5
        while not all(f.running() for f in accepted) and time.monotonic()<until:time.sleep(.005)
        queued=pool.submit(probe,3)
        final=pool.submit(probe,4)
        original=queued.set_exception
        def cancel_wins(error):
            queued.cancel()
            return original(error)
        queued.set_exception=cancel_wins
        next(iter(pool._processes.values())).terminate()
        for future in (*accepted,final):
            with self.assertRaises(BrokenProcessPool):future.result(5)
        self.assertTrue(queued.cancelled())
        pool.shutdown()
        self.assertTrue(all(not thread.is_alive() for thread in pool._threads))

    def test_no_fd_or_socket_payload_starts_resource_sharer(self):
        import multiprocessing.connection
        pool=self.pool()
        left,right=socket.socketpair()
        reader,writer=multiprocessing.connection.Pipe(duplex=False)
        try:
            for payload in (left,reader):
                with patch('multiprocessing.resource_sharer._resource_sharer.register',
                           side_effect=AssertionError('resource-sharer forbidden')):
                    with self.assertRaisesRegex(NativeExecutorCapacityError,'capability_forbidden'):
                        pool.submit(echo,payload).result(5)
            self.assertEqual(pool.submit(probe,6).result(5)[2],6)
        finally:
            left.close();right.close();reader.close();writer.close()

    def test_denied_termination_still_completes_all_failed_futures_and_requires_join(self):
        pool=self.pool('decoder')
        accepted=[pool.submit(probe,index,.1) for index in range(2)]
        until=time.monotonic()+5
        while not all(f.running() for f in accepted) and time.monotonic()<until:time.sleep(.005)
        patches=[patch.object(process,'terminate',side_effect=PermissionError('signal denied'))
                 for process in pool._processes.values()]
        for controlled in patches:controlled.start()
        try:pool._break_pool()
        finally:
            for controlled in patches:controlled.stop()
        for future in accepted:
            with self.assertRaises(BrokenProcessPool):future.result(5)
        pool.shutdown()
        self.assertTrue(pool._termination_failed)
        self.assertTrue(all(not process.is_alive() for process in pool._processes.values()))

    def test_oversized_worker_product_is_explicit_error_without_favourable_publication(self):
        pool=self.pool()
        with self.assertRaisesRegex(NativeExecutorCapacityError,'frame_bound'):
            pool.submit(oversized_product).result(5)
        self.assertEqual(pool.submit(probe,8).result(5)[2],8)

    def test_actual_sigterm_cooperative_owner_drains_two_plus_one_workers(self):
        import json
        child=subprocess.Popen([sys.executable,'-c',
            'from tests.test_isolated_native_executor import _signal_child; _signal_child()'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            child.send_signal(signal.SIGTERM)
            output,error=child.communicate(timeout=8)
            self.assertEqual(child.returncode,0,error)
            self.assertEqual(json.loads(output),dict(joined=True,completed=3))
        finally:
            if child.poll() is None:child.kill();child.communicate(timeout=3)

    def test_actual_history_prepare_matches_original_readonly_snapshot_and_queries(self):
        from tests.test_solana_history_separation import HistorySeparationTests
        from meme_machine.solana_history_work import prepare_history
        fixture=HistorySeparationTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        mint,rows=fixture.pump();fixture.enable()
        fixture.request(mint,0,max(row.slot for row in rows),'pump')
        job=fixture.tasks.claim()
        expected=prepare_history(fixture.path,job)
        actual=self.pool().submit(prepare_history,fixture.path,job).result(5)
        for key in ('id','token','spec','snapshot','queries','result_hash'):
            self.assertEqual(actual[key],expected[key])
        self.assertFalse(actual.get('entry_authority',False))

    def test_wire_larger_than_pipe_capacity_roundtrips_without_shared_queue(self):
        pool=self.pool()
        body=b'canonical-economic-payload'*100000
        self.assertEqual(pool.submit(echo,body).result(5),body)

    def test_task_frame_and_task_count_bounds_fail_explicitly(self):
        pool=self.pool()
        first=pool.submit(probe,1,.2)
        until=time.monotonic()+5
        while not first.running() and time.monotonic()<until:time.sleep(.005)
        pending=[pool.submit(probe,index) for index in range(2)]
        with self.assertRaisesRegex(NativeExecutorCapacityError,'task_bound'):pool.submit(probe)
        first.result(5)
        for item in pending:item.result(5)
        with patch('meme_machine.runtime.isolated_native_executor.MAX_FRAME_BYTES',1024):
            with self.assertRaisesRegex(NativeExecutorCapacityError,'frame_bound'):
                pool.submit(echo,b'x'*2048).result(5)
        self.assertEqual(pool.submit(probe,3).result(5)[2],3)

    def test_actual_economic_preparation_matches_inline_and_full_sqlite_commit(self):
        from tests.test_candidate_commit_batches import frame
        from tests.test_solana_closure import state_at
        from meme_machine.solana_economic_preparation import prepare_candidate_frames
        from meme_machine.solana_selective_history import PROGRAMS
        from meme_machine.solana_rolling_history import program_scope
        from meme_machine.solana_selective_source import commit_candidate_batch
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge
        addresses={PROGRAMS[name]:program_scope(name) for name in ('pump','pumpswap')}
        frames=(frame(100),frame(101))
        expected,metrics=prepare_candidate_frames(frames,addresses,'same-session','a'*64)
        actual,timing=self.pool('decoder').submit(prepare_candidate_frames,
            frames,addresses,'same-session','a'*64).result(5)
        self.assertEqual(actual,expected)
        self.assertEqual((timing['prepared_bytes'],timing['records']),
            (metrics['prepared_bytes'],metrics['records']))
        with tempfile.TemporaryDirectory() as tmp:
            baseline,h=state_at(Path(tmp)/'inline.sqlite')
            isolated,g=state_at(Path(tmp)/'spawn.sqlite')
            h.lifecycle.delivery_separated=True
            g.lifecycle.delivery_separated=True
            try:
                commit_candidate_batch(baseline,frames,addresses,'same-session',publish=False,
                    prepared=expected)
                commit_candidate_batch(isolated,frames,addresses,'same-session',publish=False,
                    prepared=actual)
                for table in ('rolling_economic_events','candidate_blocks','candidate_coverage',
                              'candidate_history_outbox'):
                    self.assertEqual(h.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall(),
                        g.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall())
                self.assertEqual(g.db.execute('PRAGMA synchronous').fetchone()[0],2)
                snapshot=capture(g.lifecycle)
                self.assertTrue(snapshot['rows'])
                result=deliver(snapshot)
                self.assertGreater(g.db.execute('SELECT COUNT(*) FROM candidate_history_outbox '
                    'WHERE consumed IS NULL').fetchone()[0],0)
                self.assertTrue(acknowledge(g.lifecycle,snapshot,result))
                self.assertEqual(g.db.execute('SELECT COUNT(*) FROM candidate_history_outbox '
                    'WHERE consumed IS NULL').fetchone()[0],0)
            finally:
                baseline.writer.close();isolated.writer.close()

    def test_default_history_pool_remains_original_process_pool(self):
        from concurrent.futures import ProcessPoolExecutor
        from meme_machine.solana_history_work import HistoryExecutor
        owner=HistoryExecutor();self.addCleanup(owner.close)
        self.assertNotEqual(owner.submit(os.getpid).result(5),os.getpid())
        self.assertIsInstance(owner.pool,ProcessPoolExecutor)
