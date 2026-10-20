import json
import os
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational import managed_capacity_workload as workload
from meme_machine.operational.managed_capacity_evidence import canonical


class ManagedWorkload(unittest.TestCase):
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
