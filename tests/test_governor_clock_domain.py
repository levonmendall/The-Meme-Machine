import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime.governor import Governor
from meme_machine.runtime.provider_clock import ProviderClockError


def domain(boot='11111111-1111-4111-8111-111111111111'):
    return json.dumps(dict(version=1,boot_id=boot,
        time_namespace_device=4,time_namespace_inode=42),
        sort_keys=True,separators=(',',':'))


class GovernorClockDomainTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'governor.sqlite'
        self.now=[100.]
        for mock in (patch('meme_machine.runtime.provider_clock.current_identity',return_value=domain()),
                     patch('meme_machine.runtime.governor.time.monotonic',side_effect=lambda:self.now[0]),
                     patch('meme_machine.operational.position_continuation.provider_interval',return_value=.5),
                     patch('meme_machine.runtime.governor._stop_sleep',side_effect=self.sleep)):
            mock.start();self.addCleanup(mock.stop)

    def sleep(self,seconds):self.now[0]+=seconds

    def legacy(self,*,global_cooldown=0.,method_cooldown=0.):
        with sqlite3.connect(self.path,isolation_level=None) as db:
            db.execute('BEGIN IMMEDIATE');Governor._schema(db);db.execute('COMMIT')
            db.execute('INSERT INTO pressure VALUES(?,?,?,?,?)',('solana',1158270.3,global_cooldown,71,13))
            db.execute('INSERT INTO method_pressure VALUES(?,?,?,?,?,?)',
                ('solana','getSignaturesForAddress',method_cooldown,9,1,3))
            db.execute('INSERT INTO method_pressure VALUES(?,?,?,?,?,?)',
                ('solana','getBlock',0.,4,0,0))
            db.execute('INSERT INTO queue VALUES(?,?,?,?,?,?)',
                ('orphan-ticket','solana','pump',10,1000000.,1000003.))
            db.execute('INSERT INTO grants VALUES(?,?,?,?,?,?,?,?,?)',
                (1,'solana','pump',10,1000000.,1000001.,1.,1,'granted'))

    def policies(self):
        with sqlite3.connect(self.path) as db:
            return {table:db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
                    for table in ('pressure','method_pressure','queue','grants')}

    def adopt(self):
        return Governor.adopt_legacy_clock(self.path,audit_identity='run-aws-recovery',
                                          clock=lambda:self.now[0])

    def test_observed_restored_clock_cannot_silently_bootstrap(self):
        self.legacy();before=self.policies()
        with self.assertRaisesRegex(ProviderClockError,'provider_clock_legacy_unbound'):
            Governor(self.path)
        self.assertEqual(self.policies(),before)

    def test_adoption_preserves_counters_grants_and_exact_orphan_evidence(self):
        self.legacy();before=self.policies();receipt=self.adopt()
        after=self.policies()
        self.assertEqual(after['pressure'][0],('solana',100.5,0.,71,13))
        self.assertEqual(after['method_pressure'],before['method_pressure'])
        self.assertEqual(after['grants'],before['grants'])
        self.assertEqual(after['queue'],[])
        self.assertEqual(receipt['quiet_until'],100.5)
        with sqlite3.connect(self.path) as db:
            archive=json.loads(db.execute('SELECT body FROM provider_clock_history').fetchone()[0])['archive']
        for table,rows in before.items():
            if table=='grants':continue
            self.assertEqual(archive[table]['rows'],[list(row) for row in rows])
        self.assertEqual(archive['grants']['row_count'],1)
        self.assertEqual(archive['grants']['first_id'],1)
        self.assertEqual(archive['grants']['last_id'],1)
        self.assertEqual(len(archive['grants']['sha256']),64)
        self.assertTrue(archive['grants']['retained_in_place'])

    def test_healthy_restored_physical_clock_waits_original_spacing_not_new_global_backoff(self):
        self.legacy();self.adopt();governor=Governor(self.path)
        wait=governor.acquire('solana','pump',priority=0,deadline_seconds=3,methods=['getBlock'])
        self.assertGreaterEqual(wait,.5);self.assertLess(wait,.56)
        row=governor.status()['providers'][0]
        self.assertEqual(row['grants'],72)
        self.assertEqual(row['cooldown'],0.)

    def test_positive_method_debt_is_full_policy_max_and_remains_method_scoped(self):
        self.legacy(method_cooldown=900000.);self.adopt()
        with sqlite3.connect(self.path) as db:
            method=db.execute("SELECT cooldown,rate_errors,rate_streak,success_streak "
                "FROM method_pressure WHERE method='getSignaturesForAddress'").fetchone()
            provider=db.execute('SELECT cooldown FROM pressure').fetchone()[0]
        self.assertEqual(method,(160.,9,1,3));self.assertEqual(provider,0.)
        governor=Governor(self.path)
        wait=governor.acquire('solana','pump',priority=0,deadline_seconds=3,methods=['getBlock'])
        self.assertLess(wait,.56)
        started=self.now[0]
        with self.assertRaisesRegex(TimeoutError,'operational_provider_queue_deadline'):
            governor.acquire('solana','pump',priority=0,deadline_seconds=3,
                             methods=['getSignaturesForAddress'])
        self.assertGreaterEqual(self.now[0]-started,3.)
        self.assertLess(self.now[0]-started,3.1)

    def test_recorded_global_debt_is_full_original_eight_seconds(self):
        self.legacy(global_cooldown=900000.);receipt=self.adopt()
        self.assertEqual(receipt['quiet_until'],108.)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT next_at,cooldown FROM pressure').fetchone(),(100.5,108.))
        governor=Governor(self.path)
        with self.assertRaisesRegex(TimeoutError,'operational_provider_queue_deadline'):
            governor.acquire('solana','pump',priority=0,deadline_seconds=3,methods=['getBlock'])

    def test_same_domain_restart_and_read_only_status_preserve_policy_rows(self):
        self.legacy(global_cooldown=900000.,method_cooldown=900000.)
        first=self.adopt();before=self.policies();self.now[0]=101.
        governor=Governor(self.path)
        self.assertEqual(self.policies(),before)
        with sqlite3.connect(self.path) as db:full_before=list(db.iterdump())
        self.assertEqual(governor.status()['clock_domain']['state'],'BOUND')
        with sqlite3.connect(self.path) as db:self.assertEqual(list(db.iterdump()),full_before)
        second=self.adopt()
        self.assertEqual(second['transition_id'],first['transition_id'])
        self.assertEqual(second['quiet_until'],first['quiet_until'])
        self.assertEqual(self.policies(),before)

    def test_new_boot_automatically_archives_once_even_with_higher_numeric_time(self):
        self.legacy();self.adopt();before=self.policies();self.now[0]=2000000.
        with patch('meme_machine.runtime.provider_clock.current_identity',
                   return_value=domain('22222222-2222-4222-8222-222222222222')):
            Governor(self.path);Governor(self.path)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM provider_clock_history').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT next_at FROM pressure').fetchone()[0],2000000.5)
        self.assertEqual(self.policies()['grants'],before['grants'])

    def test_status_uses_readers_final_clock_sample_after_concurrent_admission(self):
        from meme_machine.runtime import provider_clock
        governor=Governor(self.path);original=provider_clock._metadata
        def advancing_reader(db,component):
            self.now[0]=105.
            db.execute('UPDATE provider_clock_domain SET last_observed=105')
            return original(db,component)
        with patch.object(provider_clock,'_metadata',side_effect=advancing_reader):
            status=governor.status()
        self.assertEqual(status['clock_domain']['state'],'BOUND')
        self.assertEqual(status['clock_domain']['now'],105.)

    def test_same_domain_regression_and_malformed_timer_do_not_repair_themselves(self):
        self.legacy();self.adopt();before=self.policies();self.now[0]=99.
        with self.assertRaisesRegex(ProviderClockError,'provider_clock_regression'):
            Governor(self.path)
        self.assertEqual(self.policies(),before)
        self.now[0]=101.
        with sqlite3.connect(self.path) as db:db.execute('UPDATE pressure SET next_at=-1')
        with self.assertRaisesRegex(ProviderClockError,'provider_clock_timer_invalid'):
            Governor(self.path)

    def test_transition_failure_rolls_back_every_timer_ticket_and_history_row(self):
        self.legacy(global_cooldown=900000.,method_cooldown=900000.)
        before=self.policies();original=Governor._rebase_clock
        def fault(governor,db,now,quiet):
            original(governor,db,now,quiet)
            raise RuntimeError('offline_clock_transition_fault')
        with patch.object(Governor,'_rebase_clock',fault):
            with self.assertRaisesRegex(RuntimeError,'offline_clock_transition_fault'):
                self.adopt()
        self.assertEqual(self.policies(),before)
        with sqlite3.connect(self.path) as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='provider_clock_domain'").fetchone())

    def test_adoption_requires_existing_store_and_valid_audit_identity(self):
        with self.assertRaises(sqlite3.OperationalError):self.adopt()
        self.assertFalse(self.path.exists())
        self.legacy()
        with self.assertRaisesRegex(ProviderClockError,'provider_clock_adoption_identity_invalid'):
            Governor.adopt_legacy_clock(self.path,audit_identity='unsafe token',clock=lambda:100.)


if __name__=='__main__':unittest.main()
