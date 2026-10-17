"""Real spawn-pool preparation survives source-parent cooperative shutdown.

These are disposable subprocess/SQLite fixtures, not providers or a PAPER run.
The regression executes the original Supervisor.run() source-stop call site.
Native lane group TERM and bounded group KILL remain independently exercised.
"""
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import closing
import json
import multiprocessing
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational import supervisor as supervisor_module
from meme_machine.operational.supervisor import Supervisor


ROOT = Path(__file__).resolve().parents[1]
MODULE = 'tests.test_source_pool_cooperative_stop'


def _write(path,value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def _wait_json(path,seconds=15):
    deadline = time.monotonic()+seconds
    while time.monotonic()<deadline:
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError,json.JSONDecodeError):
            time.sleep(.02)
    raise AssertionError('offline_process_fixture_marker_timeout:'+path.name)


def _process_fields(pid):
    try:
        text = Path('/proc')/str(pid)/'stat'
        return text.read_text().rsplit(')',1)[1].split()
    except FileNotFoundError:
        return None


def _live_group(pgid):
    result = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = _process_fields(int(entry.name))
        except (ProcessLookupError,PermissionError):
            continue
        if fields is not None and fields[0]!='Z' and int(fields[2])==pgid:
            result.append(int(entry.name))
    return result


def _wait_group_gone(pgid,seconds=5):
    deadline = time.monotonic()+seconds
    while time.monotonic()<deadline:
        if not _live_group(pgid):
            return
        time.sleep(.02)
    raise AssertionError('offline_process_group_still_live:'+repr(_live_group(pgid)))


def _prepare_accepted(root):
    from operational.tests import network_guard
    network_guard()
    # A spawned service worker keeps the normal TERM disposition. It must not
    # inherit the source parent's cooperative signal handler.
    signal.signal(signal.SIGTERM,signal.SIG_DFL)
    root = Path(root)
    _write(root/'accepted.json',dict(pid=os.getpid(),parent=os.getppid(),
        process_group=os.getpgrp(),session=os.getsid(0)))
    print('OFFLINE_PREPARATION_ACCEPTED',flush=True)
    while not (root/'release').exists():
        time.sleep(.01)
    # Separate acceptance from actual preparation deterministically. Group TERM
    # kills this real worker before a parent can race its release token.
    time.sleep(.1)
    from meme_machine.solana_economic_preparation import prepare_candidate_frames
    from meme_machine.solana_rolling_history import program_scope
    from meme_machine.solana_selective_history import PROGRAMS
    from tests.test_candidate_commit_batches import frame
    frames = [frame(100),frame(101)]
    addresses = {PROGRAMS[family]:program_scope(family) for family in ('pump','pumpswap')}
    return prepare_candidate_frames(frames,addresses,'offline-source-drain','a'*64)


def _orphan_fixture(root):
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    _write(Path(root)/'orphan.json',dict(pid=os.getpid(),process_group=os.getpgrp()))
    while True:
        time.sleep(1)


def _source_fixture(root,mode):
    from operational.tests import network_guard
    network_guard()
    root = Path(root)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopped.set())
    executor = ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'))
    future = executor.submit(_prepare_accepted,str(root))
    accepted = _wait_json(root/'accepted.json')
    orphan = None
    if mode=='orphan':
        orphan = subprocess.Popen([sys.executable,'-m',MODULE,'--orphan-fixture',str(root)],
            cwd=ROOT,env=os.environ.copy())
        _wait_json(root/'orphan.json')
    from multiprocessing import resource_tracker
    _write(root/'ready.json',dict(parent=os.getpid(),worker=accepted['pid'],
        process_group=os.getpgrp(),session=os.getsid(0),
        resource_tracker=resource_tracker._resource_tracker._pid,
        orphan=None if orphan is None else orphan.pid))
    print('OFFLINE_SOURCE_READY',flush=True)
    if mode=='early-exit':
        os._exit(0)
    while not stopped.is_set():
        time.sleep(.01)
    if mode=='hung':
        while True:
            time.sleep(1)
    (root/'release').touch()
    result = dict(state='UNFINISHED',provider_requests=0)
    try:
        prepared,metrics = future.result(timeout=10)
        from meme_machine.solana_rolling_history import program_scope
        from meme_machine.solana_selective_history import PROGRAMS
        from meme_machine.solana_selective_source import commit_candidate_batch
        from tests.test_candidate_commit_batches import frame
        from tests.test_solana_closure import state_at
        state,history = state_at(root/'canonical.sqlite')
        try:
            addresses = {PROGRAMS[family]:program_scope(family) for family in ('pump','pumpswap')}
            commit_candidate_batch(state,[frame(100),frame(101)],addresses,
                'offline-source-drain',prepared=prepared,publish=False)
            count = history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0]
            result.update(state='PREPARED_AND_COMMITTED',prepared_records=metrics['records'],
                durable_records=count,future_done=future.done(),owner_transaction_open=history.db.in_transaction)
        finally:
            state.writer.close()
    except BrokenProcessPool:
        result.update(state='BROKEN_PROCESS_POOL',future_done=future.done())
    except BaseException as exc:
        result.update(state='FAILED',error_type=type(exc).__name__,error=str(exc))
    finally:
        executor.shutdown(wait=True,cancel_futures=True)
    _write(root/'result.json',result)


class SourcePoolCooperativeStopTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def launch(self,mode='drain'):
        folder = self.root/(mode+'-'+str(time.monotonic_ns()))
        folder.mkdir()
        log = (folder/'child.log').open('w')
        self.addCleanup(log.close)
        env = dict(PATH=os.environ.get('PATH',''),PYTHONPATH=str(ROOT),MM_MODE='PAPER',PYTHONUNBUFFERED='1')
        proc = subprocess.Popen([sys.executable,'-m',MODULE,'--source-fixture',str(folder),mode],
            cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
        # Independent /proc sampling makes the actual-call-site regression run
        # on the unchanged predecessor too; that code simply ignores this field.
        fields = _process_fields(proc.pid)
        self.assertIsNotNone(fields)
        self.assertEqual((int(fields[2]),int(fields[3])),(proc.pid,proc.pid))
        proc._mm_source_start_ticks = int(fields[19])

        def cleanup():
            # Fixture cleanup also works on the unchanged predecessor. Check
            # the registered leader before touching only this owned session.
            current = _process_fields(proc.pid)
            if current is not None and (int(current[19])!=proc._mm_source_start_ticks
                    or (int(current[2]),int(current[3]))!=(proc.pid,proc.pid)):
                raise AssertionError('offline_fixture_source_identity_changed')
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            if proc.poll() is None:
                proc.wait(timeout=5)
            _wait_group_gone(proc.pid)
        self.addCleanup(cleanup)
        try:
            ready = _wait_json(folder/'ready.json')
        except BaseException as exc:
            raise AssertionError((folder/'child.log').read_text()) from exc
        self.assertEqual((ready['process_group'],ready['session']),(proc.pid,proc.pid))
        accepted = _wait_json(folder/'accepted.json')
        self.assertEqual((accepted['process_group'],accepted['session']),(proc.pid,proc.pid))
        self.assertNotEqual(ready['worker'],proc.pid)
        return proc,folder,ready

    def test_actual_supervisor_source_stop_finishes_accepted_spawn_preparation_and_native_commit(self):
        proc,folder,ready = self.launch('orphan')
        members = _live_group(proc.pid)
        self.assertIn(ready['worker'],members)
        self.assertIn(ready['orphan'],members)
        if ready['resource_tracker'] is not None:
            self.assertIn(ready['resource_tracker'],members)

        class SourceOnlySupervisor(Supervisor):
            def initialize(self):pass
            def start_services(self):self.evidence=proc
            def runtime_lanes(self):return ()
            def stop_lanes(self):pass
            def publish(self,**kwargs):pass

        service = SourceOnlySupervisor(folder,offline=True)
        with patch.object(service,'stop_process',wraps=service.stop_process) as stop:
            service.run(seconds=0)
        result = _wait_json(folder/'result.json')
        self.assertEqual(result['state'],'PREPARED_AND_COMMITTED',
            dict(result=result,log=(folder/'child.log').read_text()))
        self.assertEqual(proc.returncode,0)
        self.assertEqual(stop.call_args.args,(proc,45))
        self.assertTrue(stop.call_args.kwargs['cooperative_parent'])
        self.assertGreater(result['prepared_records'],0)
        self.assertEqual(result['durable_records'],result['prepared_records'])
        self.assertTrue(result['future_done'])
        self.assertFalse(result['owner_transaction_open'])
        self.assertEqual(result['provider_requests'],0)
        with closing(sqlite3.connect(folder/'canonical.sqlite')) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('SELECT DISTINCT slot FROM candidate_blocks').fetchall(),[(101,)])
            self.assertGreater(db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],0)
        self.assertIsNotNone(ready['orphan'])
        _wait_group_gone(proc.pid)

    def test_native_lane_default_group_term_still_breaks_a_pending_spawn_worker(self):
        proc,folder,_ = self.launch()
        service = Supervisor(folder,offline=True)
        service.processes={'pump':proc}
        service.stop_lanes()
        result = _wait_json(folder/'result.json')
        self.assertEqual(result['state'],'BROKEN_PROCESS_POOL',
            dict(result=result,log=(folder/'child.log').read_text()))
        self.assertTrue(result['future_done'])
        self.assertFalse((folder/'canonical.sqlite').exists())
        self.assertEqual([row['signal'] for row in service.native_shutdown
            if row['operation']=='signal_sent'],[int(signal.SIGTERM)])
        _wait_group_gone(proc.pid)

    def test_stuck_source_keeps_bounded_wait_then_kills_entire_spawn_group(self):
        proc,folder,ready = self.launch('hung')
        observations = []
        started = time.monotonic()
        Supervisor.stop_process(proc,.2,cooperative_parent=True,observe=observations.append)
        self.assertLess(time.monotonic()-started,6)
        self.assertEqual(proc.returncode,-signal.SIGKILL)
        self.assertEqual([row['timeout_seconds'] for row in observations
            if row['operation']=='wait_timeout'],[.2])
        self.assertEqual([row['signal'] for row in observations if row['operation']=='signal_sent'],
            [int(signal.SIGTERM),int(signal.SIGKILL)])
        self.assertFalse((folder/'result.json').exists())
        self.assertIn(ready['worker'],[row['pid'] for row in [_wait_json(folder/'accepted.json')]])
        _wait_group_gone(proc.pid)

    def test_already_exited_registered_source_cleans_leftover_real_spawn_group(self):
        proc,folder,ready = self.launch('early-exit')
        self.assertEqual(proc.wait(timeout=5),0)
        self.assertIn(ready['worker'],_live_group(proc.pid))
        observations = []
        Supervisor.stop_process(proc,cooperative_parent=True,observe=observations.append)
        self.assertTrue(any(row['operation']=='already_exited' for row in observations))
        self.assertTrue(any(row['operation']=='descendant_cleanup_requested' for row in observations))
        self.assertFalse((folder/'release').exists())
        _wait_group_gone(proc.pid)

    def test_evidence_recovery_cleans_crashed_pool_group_before_actual_replacement(self):
        proc,folder,ready = self.launch()
        proc.kill()
        self.assertEqual(proc.wait(timeout=5),-signal.SIGKILL)
        self.assertIn(ready['worker'],_live_group(proc.pid))
        service = Supervisor(folder,offline=True)
        service.evidence=proc
        service.reported_evidence_failure=proc.pid
        service.next_evidence_retry=0
        service.provider_budget=SimpleNamespace(continuous=True,snapshot=lambda:dict(backoff_until=0),
            provider_error=lambda _:self.fail('unchanged failure must not reset retry clock'))
        replacements = []
        native_killpg = os.killpg

        def replace_source():
            self.assertIn((proc.pid,signal.SIGKILL),[call.args for call in sent.call_args_list])
            _wait_group_gone(proc.pid)
            replacement = subprocess.Popen([sys.executable,'-c','pass'],cwd=ROOT,
                start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            replacements.append(replacement)
            service.evidence=replacement

        with patch.object(supervisor_module.os,'killpg',wraps=native_killpg) as sent, \
                patch.object(service,'start_services',side_effect=replace_source):
            service.recover_evidence()
        self.assertEqual(len(replacements),1)
        self.assertNotEqual(replacements[0].pid,proc.pid)
        self.assertEqual(replacements[0].wait(timeout=5),0)

    def test_recovery_cooldown_and_final_stop_do_not_reuse_closed_group_authority(self):
        proc,folder,ready = self.launch()
        proc.kill()
        self.assertEqual(proc.wait(timeout=5),-signal.SIGKILL)
        self.assertIn(ready['worker'],_live_group(proc.pid))

        class SourceOnlySupervisor(Supervisor):
            def initialize(self):pass
            def start_services(self):raise AssertionError('cooldown must not replace source')
            def runtime_lanes(self):return ()
            def stop_lanes(self):pass
            def publish(self,**kwargs):pass

        service = SourceOnlySupervisor(folder,offline=True)
        service.evidence=proc
        service.run_id='offline-closed-source-group'
        service.reported_evidence_failure=proc.pid
        retry = time.time()+3600
        service.next_evidence_retry=retry
        readiness = []
        service.provider_budget=SimpleNamespace(continuous=True,
            snapshot=lambda:dict(backoff_until=retry),
            provider_error=lambda _:self.fail('unchanged failure must not reset retry clock'),
            publish_readiness=lambda *args,**kwargs:readiness.append((args,kwargs)))
        native_killpg = os.killpg
        with patch.object(supervisor_module.os,'killpg',wraps=native_killpg) as sent:
            service.recover_evidence()
            self.assertTrue(proc._mm_source_group_closed)
            _wait_group_gone(proc.pid)
            self.assertEqual(service.next_evidence_retry,retry)
            # Once this group is closed, even inspecting a numerically reused
            # leader would claim authority the supervisor no longer owns.
            with patch.object(Supervisor,'_source_start_ticks',
                    side_effect=AssertionError('closed group identity must not be read')) as identity:
                service.recover_evidence()
                service.stop_requested=True
                service.run(seconds=0)
                identity.assert_not_called()
            self.assertEqual([call.args for call in sent.call_args_list],
                [(proc.pid,signal.SIGKILL)])
        self.assertEqual(service.next_evidence_retry,retry)
        self.assertEqual(len(readiness),1)
        self.assertFalse(readiness[0][0][0])
        self.assertFalse((folder/'release').exists())
        self.assertFalse((folder/'canonical.sqlite').exists())
        _wait_group_gone(proc.pid)

    def test_reused_leader_identity_refuses_group_signal_without_touching_old_workers(self):
        proc,_,ready = self.launch()
        proc.kill()
        proc.wait(timeout=5)
        expected = proc._mm_source_start_ticks
        native_killpg = os.killpg
        with patch.object(Supervisor,'_source_start_ticks',return_value=expected+1), \
                patch.object(supervisor_module.os,'killpg',wraps=native_killpg) as sent:
            with self.assertRaisesRegex(RuntimeError,'source_process_identity_changed'):
                Supervisor.stop_process(proc,cooperative_parent=True)
            sent.assert_not_called()
        self.assertIn(ready['worker'],_live_group(proc.pid))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--source-fixture':
        _source_fixture(sys.argv[2],sys.argv[3])
    elif len(sys.argv)>1 and sys.argv[1]=='--orphan-fixture':
        _orphan_fixture(sys.argv[2])
    else:
        unittest.main()
