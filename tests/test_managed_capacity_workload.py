import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from meme_machine.operational import managed_capacity_workload as workload
from meme_machine.operational.managed_capacity_evidence import canonical


def _accepted_decoder_fixture(directory):
    """A spawn worker with accepted work held until its coordinator stops."""
    root = Path(directory)
    (root / 'decoder-ready').write_text(str(os.getpid()))
    deadline = time.monotonic() + 10
    while not (root / 'decoder-release').exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('offline_decoder_not_released')
        time.sleep(.005)
    (root / 'decoder-committed').write_text('accepted-native-work')
    return 'accepted-native-work'


class ManagedWorkload(unittest.TestCase):
    def test_source_drain_and_provider_free_replay_have_separate_bounded_leases(self):
        from meme_machine.operational.managed_capacity_evidence import atomic_json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'pump').mkdir(mode=0o700)
            child = SimpleNamespace(poll=lambda: None, wait=Mock())
            elapsed = [100.]
            def sleep(seconds): elapsed[0] += seconds
            with patch.object(workload, 'SHUTDOWN_SECONDS', 1):
                result = workload._wait_children({'pump': child}, root, 'a'*32,
                    clock=lambda: elapsed[0], sleeper=sleep)
            self.assertEqual(result, 'native_shutdown_deadline')
            child.wait.assert_not_called()
            self.assertLess(elapsed[0], 101.2)
            atomic_json(root/'pump/drained.json', dict(generation='a'*32,
                                                     native_provider_work_drained=True))
            self.assertIsNone(workload._wait_children({'pump': child}, root, 'a'*32,
                clock=lambda: elapsed[0], sleeper=sleep))
            self.assertAlmostEqual(child.wait.call_args.kwargs['timeout'], workload.REPLAY_SECONDS)

    def test_lane_environment_never_inherits_financial_or_other_provider_secrets(self):
        env = dict(MM_SOLANA_READ_RPC_URL='solana-private-fixture',
            MM_SOLANA_YELLOWSTONE_TOKEN='yellowstone-private-fixture',
            MM_ROBINHOOD_READ_RPC_URL='robinhood-private-fixture',
            MM_SHARED_CAPITAL_DB='/old/financial.sqlite', AWS_SECRET_ACCESS_KEY='aws-private-fixture')
        with patch.dict(os.environ, env, clear=True):
            pump = workload._environment('pump', Path('/fresh'), 'a' * 40)
            pons = workload._environment('pons', Path('/fresh'), 'a' * 40)
        self.assertNotIn('MM_ROBINHOOD_READ_RPC_URL', pump)
        self.assertNotIn('MM_SOLANA_READ_RPC_URL', pons)
        self.assertNotIn('MM_SOLANA_YELLOWSTONE_TOKEN', pons)
        for child in (pump, pons):
            self.assertNotIn('MM_SHARED_CAPITAL_DB', child)
            self.assertNotIn('AWS_SECRET_ACCESS_KEY', child)
            self.assertEqual(child['MM_CAPACITY_USAGE_DB'], '/fresh/provider-usage.sqlite')

    def test_dead_leader_still_has_its_owned_process_group_stopped(self):
        child = SimpleNamespace(pid=12345, poll=lambda: 2)
        with patch.object(workload.os, 'killpg') as kill:
            workload._signal_children({'pump': child}, signal.SIGTERM)
        kill.assert_called_once_with(12345, signal.SIGTERM)

    def test_graceful_stop_only_signals_living_lane_coordinator(self):
        child = SimpleNamespace(pid=12345, poll=lambda: None, send_signal=Mock())
        with patch.object(workload.os, 'killpg') as kill:
            workload._signal_children({'pump': child}, signal.SIGTERM)
        child.send_signal.assert_called_once_with(signal.SIGTERM)
        kill.assert_not_called()

    def test_forced_stop_still_reaches_living_lane_descendants(self):
        child = SimpleNamespace(pid=12345, poll=lambda: None, send_signal=Mock())
        with patch.object(workload.os, 'killpg') as kill:
            workload._signal_children({'pump': child}, signal.SIGKILL)
        kill.assert_called_once_with(12345, signal.SIGKILL)
        child.send_signal.assert_not_called()

    def test_graceful_lane_stop_preserves_actual_spawn_decoder_until_commit(self):
        # Production serve owns a spawn ProcessPool in the lane's process
        # group. Group-wide TERM kills that accepted worker before its owner
        # can drain it, even though the lane itself handles TERM gracefully.
        source = str(Path(__file__).resolve().parents[1])
        script = '''
import multiprocessing, signal, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tests.test_managed_capacity_workload import _accepted_decoder_fixture
root = Path(sys.argv[2])
signal.signal(signal.SIGTERM, lambda *_: (root / 'decoder-release').write_text('stop'))
with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
    future = pool.submit(_accepted_decoder_fixture, str(root))
    assert future.result(timeout=12) == 'accepted-native-work'
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = subprocess.Popen([sys.executable, '-I', '-B', '-c', script, source, tmp],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                start_new_session=True)
            try:
                deadline = time.monotonic() + 8
                while not (root / 'decoder-ready').exists() and child.poll() is None:
                    self.assertLess(time.monotonic(), deadline, 'spawn decoder readiness deadline')
                    time.sleep(.005)
                self.assertIsNone(child.poll(), 'lane exited before accepted decode')
                decoder_pid = int((root / 'decoder-ready').read_text())
                self.assertEqual(os.getpgid(decoder_pid), child.pid)
                workload._signal_children({'pump': child}, signal.SIGTERM)
                _, error = child.communicate(timeout=12)
                self.assertEqual(child.returncode, 0, error.decode(errors='replace'))
                self.assertEqual((root / 'decoder-committed').read_text(), 'accepted-native-work')
            finally:
                workload._signal_children({'pump': child}, signal.SIGKILL)
                child.wait(timeout=5)
                if child.stderr is not None:
                    child.stderr.close()

    def test_readiness_requires_native_durability_not_provider_calls(self):
        self.assertFalse(workload._active('pump', dict(provider_requests=100)))
        self.assertFalse(workload._active('pons', dict(provider_requests=100)))
        self.assertFalse(workload._active('pons', dict(durable_blocks=0)))
        self.assertTrue(workload._active('pump', dict(canonical=dict(sealed_finalized_blocks=1))))
        self.assertTrue(workload._active('pons', dict(durable_blocks=1)))

    def test_growing_native_coverage_is_not_duplicated_into_sample_payloads(self):
        row = dict(generation='a' * 32, observed_at=10,
            canonical=dict(sealed_finalized_blocks=10, finalized_blocks=11,
                latest_sealed_slot=30, latest_finalized_slot=31,
                coverage=[['scope'+str(n), 1, n, n] for n in range(10000)],
                unresolved_gaps=[], outbox=[['event', 10, 10]]),
            source_frames=dict(accepted_handlers=100, settled_handlers=99,
                queues=dict(control=dict(accepted=10, committed=10, pending=0))),
            history=dict(events=20, canonical_event_refs=30))
        small = workload.sample_projection('pump', row)
        self.assertEqual(small['coverage_scopes'], 10000)
        self.assertEqual(small['source_queues']['control']['committed'], 10)
        self.assertNotIn('coverage', small['canonical'])
        self.assertLess(len(canonical(small)) * (3600 // 5 + 1), 1024**2)
        self.assertEqual(small['history']['events'], 20)

    def test_qualification_projection_retains_actual_native_arrival_and_cursor_fields(self):
        native = dict(incoming_native_events=128, durably_observed_native_events=64,
            native_event_backlog=64, latest_source_sequence=140, durable_sequence=70,
            stages={'creation_observed': 64}, full_qualifications=0,
            decision_target_available=False, full_qualification_proven=False)
        small = workload.sample_projection('pump', dict(qualification_worker=native))
        for key, value in native.items():
            self.assertEqual(small['qualification_worker'][key], value)
        self.assertNotIn('source_native_events', small['qualification_worker'])

    def test_pons_child_binds_exact_state_and_preserves_blocked_result(self):
        from meme_machine.operational import managed_native_pons
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'pons').mkdir(mode=0o700)
            env = dict(MM_ROBINHOOD_READ_RPC_URL='private-provider-fixture',
                MM_CAPACITY_SOURCE_COMMIT='a' * 40,
                MM_CAPACITY_PROVIDER_PROFILE=str(root / 'profile.json'),
                MM_CAPACITY_USAGE_DB=str(root / 'provider-usage.sqlite'))
            seen = {}
            def blocked(*args, **kwargs):
                seen.update(os.environ)
                return dict(error=dict(reason='provider_http_429'), verdict='BLOCKED')
            args = SimpleNamespace(root=str(root), lane='pons', generation='a' * 32,
                                   duration_seconds=120, request_id='ec2-100-1')
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(managed_native_pons, 'run_pons', blocked), \
                 patch.object(workload.signal, 'signal'):
                self.assertEqual(workload._child(args), 2)
            self.assertEqual(seen['MM_ROBINHOOD_STATE_DIR'], str(root / 'pons'))
            self.assertEqual(seen['MM_PROVIDER_DB'], str(root / 'pons/provider.sqlite'))
            self.assertEqual(seen['MM_RPC_CACHE_DB'], str(root / 'pons/evidence.sqlite'))
            self.assertEqual(seen['MM_PONS_OBSERVATION_ROUTE'], 'canonical_primary')
            self.assertEqual(seen['MM_RUNTIME_LANE'], 'pons')
            saved = json.loads((root / 'pons/result.json').read_text())
            self.assertEqual(saved['state'], 'NATIVE_FAILED')
            self.assertFalse(saved['financial_authority'])

    def test_protected_request_identity_requires_both_run_and_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            for request_id in ('ec2-100', 'ec2-100-0', 'ec2-0-1', 'arbitrary-shell'):
                with self.assertRaisesRegex(ValueError, 'capacity_request_id'):
                    workload.parameters(Path(tmp), 120, 'a' * 32, request_id)

    def test_pump_child_retains_native_first_error_without_credential_message(self):
        from meme_machine.operational import managed_native_pump
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        import sqlite3
        failures = [EvidenceUnavailable('writer_failed'),
                    RuntimeError('secret-provider-credential-do-not-export'),
                    sqlite3.OperationalError('secret-provider-credential-do-not-export')]
        failures[-1].sqlite_errorcode = sqlite3.SQLITE_BUSY
        failures[-1].sqlite_errorname = 'SQLITE_BUSY'
        for error in failures:
            with self.subTest(kind=type(error).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); (root / 'pump').mkdir(mode=0o700)
                env = dict(MM_SOLANA_READ_RPC_URL='https://solana-mainnet.g.alchemy.com/v2/offline-fixture',
                    MM_CAPACITY_SOURCE_COMMIT='a' * 40,
                    MM_CAPACITY_PROVIDER_PROFILE=str(root / 'profile.json'),
                    MM_CAPACITY_USAGE_DB=str(root / 'provider-usage.sqlite'))
                async def failed(*args, **kwargs):
                    raise error
                args = SimpleNamespace(root=str(root), lane='pump', generation='a' * 32,
                                       duration_seconds=120, request_id='ec2-100-1')
                with patch.dict(os.environ, env, clear=True), \
                     patch.object(managed_native_pump, 'run_pump', failed), \
                     patch.object(workload.signal, 'signal'):
                    self.assertEqual(workload._child(args), 2)
                raw = (root / 'pump/result.json').read_text()
                self.assertNotIn('secret-provider-credential', raw)
                native = json.loads(raw)['native_failure']
                if isinstance(error, EvidenceUnavailable):
                    self.assertIn('writer_failed', native)
                if isinstance(error, sqlite3.Error):
                    self.assertIn('SQLITE_BUSY', native)
