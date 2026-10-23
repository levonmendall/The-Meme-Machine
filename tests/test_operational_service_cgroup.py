"""Measure the actual fixed service; another unit's limits cannot grant readiness."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational.supervisor import Supervisor
from tests.test_operational_cpu_capacity import profiles


class ServiceCgroupTests(unittest.TestCase):
    def sample(self, membership, *, measured='meme-machine-pons-pilot.service'):
        service = Supervisor.__new__(Supervisor)
        service.provider_budget = SimpleNamespace(envelope=profiles()[0][1])
        service.runtime_lanes = lambda: ('pons',)
        service.providers_for_sample = lambda sample: sample
        service.shared_capital = SimpleNamespace(ledger=lambda: dict(positions={}))
        service.last_native_health = dict(pons=dict(progress_at=1000., reconciled=True))
        resources = {'memory.current': '1024', 'cpu.stat': 'usage_usec 2000000\n',
            'cpu.max': '180000 100000', 'memory.high': str(6*1024**3),
            'memory.max': str(7*1024**3)}
        reads = []

        def read(path, *args, **kwargs):
            if path == Path('/proc/self/cgroup'):
                return membership
            reads.append(str(path))
            if path.parent != Path('/sys/fs/cgroup/system.slice')/measured:
                # The old hardcoded unit exists but is unbounded. Its counters
                # must never be substituted for this pilot process's limits.
                return 'max' if path.name.startswith('memory.') else 'max 100000'
            return resources[path.name]

        with patch('meme_machine.operational.position_continuation.os.cpu_count', return_value=2), \
                patch('meme_machine.operational.position_continuation.os.sched_getaffinity', return_value={0, 1}), \
                patch('meme_machine.operational.supervisor.time.time', return_value=1000.), \
                patch.object(Path, 'read_text', read):
            service.continuation_health(provider_sample=dict(robinhood=dict(
                state='CURRENT', queue_depth=0, oldest_wait_seconds=0)))
        return service, reads

    def test_pilot_uses_its_own_enforced_limits_while_original_unit_is_unbounded(self):
        service, reads = self.sample('0::/system.slice/meme-machine-pons-pilot.service\n')
        self.assertTrue(service.resource_measurement.get('limits_verified'))
        self.assertIsNone(service.current_readiness_failure)
        self.assertEqual(len(reads), 5)
        self.assertTrue(all('/meme-machine-pons-pilot.service/' in path for path in reads))

    def test_original_unit_keeps_its_original_limits(self):
        service, reads = self.sample('0::/system.slice/meme-machine-paper.service\n',
                                     measured='meme-machine-paper.service')
        self.assertTrue(service.resource_measurement.get('limits_verified'))
        self.assertTrue(all('/meme-machine-paper.service/' in path for path in reads))

    def test_foreign_ambiguous_malformed_or_oversized_membership_never_reads_limits(self):
        for membership in ('', '0::/\n', '0::/system.slice/foreign.service\n',
                '0::/system.slice/../meme-machine-paper.service\n',
                '0::/system.slice/meme-machine-paper.service\n0::/system.slice/meme-machine-pons-pilot.service\n',
                '1:cpu:/system.slice/meme-machine-paper.service\n', 'x'*4097):
            with self.subTest(membership=membership[:80]):
                service, reads = self.sample(membership)
                self.assertIsNot(service.resource_measurement.get('limits_verified'), True)
                self.assertIsNotNone(service.current_readiness_failure)
                self.assertEqual(reads, [])
