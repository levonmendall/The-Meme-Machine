"""Offline restored-clock regressions through the real shared Pons admission."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.provider_admission import Admission
from meme_machine.runtime.provider_clock import ProviderClockError


def identity(boot='11111111-1111-4111-8111-111111111111', namespace=8):
    return json.dumps(dict(version=1, boot_id=boot,
        time_namespace_device=4, time_namespace_inode=namespace),
        sort_keys=True, separators=(',', ':'))


class PonsProviderClockDomainTests(unittest.TestCase):
    endpoint = 'https://offline.invalid/public'
    canonical = 'https://offline.invalid/canonical'
    tables = ('limits', 'public_pacing', 'queue', 'queue_meta',
              'position_service', 'provider_usage', 'transport_starts',
              'admissions', 'transports')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'provider.sqlite'
        self.now = 100.0
        self.domain = identity()
        for context in (
                patch.dict(os.environ, {}, clear=True),
                patch('meme_machine.operational.position_continuation.provider_interval',
                      return_value=None),
                patch('meme_machine.runtime.provider_clock.current_identity',
                      side_effect=lambda: self.domain)):
            context.start()
            self.addCleanup(context.stop)

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def gate(self, endpoint=None):
        return Admission(self.path, endpoint or self.endpoint, lane='pons',
                         clock=self.clock, sleeper=self.sleep)

    def state(self):
        with sqlite3.connect(self.path) as db:
            return {table: db.execute('SELECT * FROM ' + table +
                                     ' ORDER BY 1,2').fetchall()
                    for table in self.tables}

    def seed_legacy(self, *, positive_cooldown=True):
        gate = self.gate()
        other = self.gate(self.canonical)
        gate.public_interval(1.25)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE limits SET next_at=?,cooldown=? WHERE endpoint=?',
                       (1076000., 996462. if positive_cooldown else 0., gate.endpoint))
            db.execute('UPDATE limits SET next_at=?,cooldown=0 WHERE endpoint=?',
                       (996000., other.endpoint))
            db.execute('UPDATE public_pacing SET last_dispatch=1076000')
            db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',
                       ('dead-ticket', gate.endpoint, 0, 996400., 996405.))
            db.execute('INSERT INTO queue_meta VALUES(?,?)', ('dead-ticket', 'pons'))
            db.execute('INSERT INTO position_service VALUES(?,?,?)',
                       (gate.endpoint, 'pons', 7))
            db.execute('INSERT INTO provider_usage VALUES(?,?,?,?)',
                       (gate.endpoint, 'pons', 'physical_http_requests', 321.))
            body = json.dumps(dict(endpoint_fingerprint=gate.endpoint,
                                   admitted_at=996400., original='retained'))
            for table in ('transport_starts', 'admissions', 'transports'):
                db.execute('INSERT INTO ' + table + '(seq,body) VALUES(11,?)', (body,))
            db.execute('DROP TABLE provider_clock_domain')
        return gate, other

    def adopt(self):
        return Admission.adopt_legacy_clock(self.path,
            audit_identity='offline-controlled-recovery-1', clock=self.clock)

    def history(self):
        with sqlite3.connect(self.path) as db:
            return [json.loads(body) for body, in db.execute(
                'SELECT body FROM provider_clock_history ORDER BY id')]

    def test_new_empty_bootstrap_has_no_artificial_quiet_period(self):
        gate = self.gate()
        self.assertEqual(gate.clock_domain['transition'], 'bootstrap')
        self.assertEqual(gate.clock_domain['quiet_until'], 0.)
        self.assertEqual(gate.acquire('paper_unwind')['wait_seconds'], 0.)
        self.assertEqual(self.history(), [])

    def test_legacy_constructor_contains_without_guessing_or_policy_changes(self):
        self.seed_legacy()
        before = self.state()
        with self.assertRaisesRegex(ProviderClockError, '^provider_clock_legacy_unbound$'):
            self.gate()
        self.assertEqual(self.state(), before)
        self.assertEqual(self.history(), [])
        # A numerically old timestamp is no more proof of a shared clock domain.
        self.now = 2000000.
        with self.assertRaisesRegex(ProviderClockError, '^provider_clock_legacy_unbound$'):
            self.gate()
        self.assertEqual(self.state(), before)

    def test_adoption_archives_exact_leases_preserves_history_counters_and_policy(self):
        gate, other = self.seed_legacy()
        before = self.state()
        result = self.adopt()
        self.assertEqual(result['transition'], 'legacy_adopted')
        self.assertEqual(result['quiet_until'], 108.)
        archive = self.history()[0]['archive']
        for table in ('limits', 'public_pacing', 'queue', 'queue_meta',
                      'position_service', 'provider_usage'):
            self.assertEqual(archive[table], [list(row) for row in before[table]])
        after = self.state()
        for table in ('provider_usage', 'position_service', 'transport_starts',
                      'admissions', 'transports'):
            self.assertEqual(after[table], before[table])
        self.assertEqual(after['queue'], [])
        self.assertEqual(after['queue_meta'], [])
        limits = {endpoint: (next_at, cooldown, interval)
                  for endpoint, next_at, cooldown, interval in after['limits']}
        self.assertEqual(limits[gate.endpoint], (101.25, 108., .5))
        self.assertEqual(limits[other.endpoint], (100.5, 0., .5))
        self.assertEqual(after['public_pacing'], [(gate.endpoint, 1.25, 100.)])
        for table in ('transport_starts', 'admissions', 'transports'):
            self.assertEqual(archive[table]['count'], 1)
            self.assertEqual(archive[table]['first_sequence'], 11)
            self.assertEqual(archive[table]['last_sequence'], 11)
            self.assertEqual(len(archive[table]['sha256']), 64)

    def test_zero_cooldown_receives_only_physical_and_adaptive_spacing(self):
        self.seed_legacy(positive_cooldown=False)
        result = self.adopt()
        self.assertEqual(result['quiet_until'], 101.25)
        gate = self.gate()
        admitted = gate.acquire('paper_unwind', deadline=103., public=True)
        self.assertGreaterEqual(admitted['admitted_at'], 101.25)
        self.assertLess(admitted['admitted_at'], 101.252)
        gate.public_dispatch(admitted, 'paper_unwind', ['eth_call'], final=True)
        second = self.gate().acquire('paper_unwind', deadline=105., public=True)
        self.assertGreaterEqual(second['admitted_at'] - admitted['admitted_at'], 1.25)

    def test_eight_second_debt_never_expands_original_protection_deadline(self):
        self.seed_legacy()
        self.adopt()
        calls = []
        gate = self.gate()
        with self.assertRaisesRegex(BoundaryError, 'provider_shared_admission_deadline'):
            gate.invoke(lambda: calls.append(self.now), ['eth_call'], 'paper_unwind',
                        deadline=103.)
        self.assertEqual(calls, [])
        self.assertLess(self.now, 103.051)
        with sqlite3.connect(self.path) as db:
            receipt = json.loads(db.execute(
                'SELECT body FROM admissions ORDER BY seq DESC LIMIT 1').fetchone()[0])
        self.assertEqual(receipt['deadline'], 103.)
        self.assertFalse(receipt['granted'])
        self.now = 108.
        admitted = gate.acquire('paper_unwind', deadline=111., public=True)
        gate.public_dispatch(admitted, 'paper_unwind', ['eth_call'], final=True)
        second = gate.acquire('paper_unwind', deadline=112., public=True)
        self.assertGreaterEqual(second['admitted_at'] - admitted['admitted_at'], 1.25)

    def test_healthy_canonical_endpoint_is_not_delayed_by_public_cooldown(self):
        self.seed_legacy()
        self.adopt()
        canonical = self.gate(self.canonical)
        admitted_at = canonical.acquire('paper_unwind', deadline=103.)['admitted_at']
        self.assertGreaterEqual(admitted_at, 100.5)
        self.assertLess(admitted_at, 100.502)

    def test_held_priority_and_bounded_queue_remain_after_adoption(self):
        self.seed_legacy()
        self.adopt()
        self.now = 108.
        gate = self.gate()
        with sqlite3.connect(self.path) as db:
            for n in range(256):
                ticket = 'waiting-' + str(n)
                db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',
                           (ticket, gate.endpoint, 50, 107., 130.))
                db.execute('INSERT INTO queue_meta VALUES(?,?)', (ticket, 'pons'))
        with self.assertRaisesRegex(BoundaryError, 'capacity'):
            gate.acquire('candidate', deadline=111.)
        self.assertEqual(gate.acquire('paper_unwind', deadline=111.)['admitted_at'], 108.)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM queue').fetchone()[0], 256)

    def test_same_domain_reopen_and_readoption_do_not_renew_debt(self):
        self.seed_legacy()
        self.adopt()
        before = self.state()
        self.now = 101.
        self.assertEqual(self.gate().clock_domain['transition'], 'same_domain')
        result = self.adopt()
        self.assertEqual(result['transition'], 'same_domain')
        self.assertEqual(result['transition_id'], 1)
        self.assertEqual(result['quiet_until'], 108.)
        self.assertEqual(self.state(), before)
        self.assertEqual(len(self.history()), 1)

    def test_genuine_new_boot_rebases_once_without_losing_adaptive_feedback(self):
        self.seed_legacy()
        self.adopt()
        before = self.state()
        self.domain = identity('22222222-2222-4222-8222-222222222222')
        self.now = 10.
        gate = self.gate()
        self.assertEqual(gate.clock_domain['transition'], 'domain_changed')
        self.assertEqual(gate.clock_domain['transition_id'], 2)
        after = self.state()
        self.assertEqual(after['public_pacing'], [(gate.endpoint, 1.25, 10.)])
        for table in ('provider_usage', 'position_service', 'transport_starts',
                      'admissions', 'transports'):
            self.assertEqual(after[table], before[table])
        self.now = 11.
        self.assertEqual(self.gate().clock_domain['transition'], 'same_domain')
        self.assertEqual(self.state(), after)
        self.assertEqual(len(self.history()), 2)

    def test_failed_rebase_rolls_back_archive_binding_and_all_lease_changes(self):
        self.seed_legacy()
        before = self.state()
        rebase = Admission._clock_rebase
        def fail(db, now, quiet_until):
            rebase(db, now, quiet_until)
            raise RuntimeError('offline-rebase-fault')
        with patch.object(Admission, '_clock_rebase', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'offline-rebase-fault'):
                self.adopt()
        self.assertEqual(self.state(), before)
        self.assertEqual(self.history(), [])
        with sqlite3.connect(self.path) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE "
                "name='provider_clock_domain'").fetchone())

    def test_invalid_legacy_timer_contains_without_partial_migration(self):
        gate, _ = self.seed_legacy()
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE public_pacing SET last_dispatch=-1 WHERE endpoint=?',
                       (gate.endpoint,))
        before = self.state()
        with self.assertRaisesRegex(ProviderClockError, 'provider_clock_timer_invalid'):
            self.adopt()
        self.assertEqual(self.state(), before)
        self.assertEqual(self.history(), [])

    def test_adoption_cannot_create_a_replacement_database(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.adopt()
        self.assertFalse(self.path.exists())
