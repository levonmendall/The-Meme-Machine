import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.runtime.provider_clock import (
    ProviderClockError,bind_clock_domain,current_identity,inspect_clock_domain,validate_timer)


def identity(boot='11111111-1111-4111-8111-111111111111',namespace=42):
    return json.dumps(dict(version=1,boot_id=boot,
        time_namespace_device=4,time_namespace_inode=namespace),
        sort_keys=True,separators=(',',':'))


class ProviderClockDomainTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'provider.sqlite'
        self.db=sqlite3.connect(self.path,isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE leases(id TEXT PRIMARY KEY,next_at REAL)')

    @staticmethod
    def snapshot(db):
        rows=db.execute('SELECT * FROM leases ORDER BY id').fetchall()
        for _,value in rows:validate_timer(value)
        return bool(rows),dict(leases=rows)

    @staticmethod
    def rebase(db,now,quiet_until):
        db.execute('UPDATE leases SET next_at=?',(quiet_until,))

    def bind(self,*,now=100.,domain=None,adoption=None,db=None,rebase=None):
        connection=db or self.db
        connection.execute('BEGIN IMMEDIATE')
        try:
            with patch('meme_machine.runtime.provider_clock.current_identity',
                       return_value=domain or identity()):
                result=bind_clock_domain(connection,component='source_governor',
                    clock=lambda:now,quiet_seconds=60.,snapshot=self.snapshot,
                    rebase=rebase or self.rebase,adoption_identity=adoption)
            connection.execute('COMMIT')
            return result
        except BaseException:
            connection.execute('ROLLBACK');raise

    def test_empty_bootstrap_and_same_domain_do_not_rebase_policy(self):
        self.assertEqual(self.bind()['transition'],'bootstrap')
        self.db.execute("INSERT INTO leases VALUES('solana',117)")
        self.bind(now=101.)
        self.assertEqual(self.db.execute('SELECT next_at FROM leases').fetchone()[0],117.)
        self.assertEqual(self.db.execute('SELECT count(*) FROM provider_clock_history').fetchone()[0],0)

    def test_legacy_both_above_and_below_current_time_fail_closed(self):
        for old in (1.,1000000.):
            self.db.execute('DELETE FROM leases')
            self.db.execute("INSERT INTO leases VALUES('solana',?)",(old,))
            with self.assertRaisesRegex(ProviderClockError,'provider_clock_legacy_unbound'):
                self.bind()
            self.assertEqual(self.db.execute('SELECT next_at FROM leases').fetchone()[0],old)
            self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='provider_clock_domain'").fetchone())

    def test_explicit_adoption_archives_original_rows_once_and_is_idempotent(self):
        self.db.execute("INSERT INTO leases VALUES('solana',1000000)")
        first=self.bind(adoption='run-123')
        self.assertEqual(first['quiet_until'],160.)
        second=self.bind(now=103.,adoption='run-124')
        self.assertEqual(second['quiet_until'],160.)
        self.assertEqual(second['transition_id'],first['transition_id'])
        row=json.loads(self.db.execute('SELECT body FROM provider_clock_history').fetchone()[0])
        self.assertEqual(row['archive']['leases'],[['solana',1000000.]])
        self.assertEqual(row['adoption_identity'],'run-123')
        with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):
            self.db.execute('DELETE FROM provider_clock_history')

    def test_failed_transition_rolls_back_policy_history_and_binding(self):
        self.db.execute("INSERT INTO leases VALUES('solana',900000)")
        def failure(db,now,quiet):
            db.execute('UPDATE leases SET next_at=?',(quiet,))
            raise RuntimeError('offline_transition_fault')
        with self.assertRaisesRegex(RuntimeError,'offline_transition_fault'):
            self.bind(adoption='run-fault',rebase=failure)
        self.assertEqual(self.db.execute('SELECT next_at FROM leases').fetchone()[0],900000.)
        self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='provider_clock_history'").fetchone())
        self.assertEqual(self.bind(adoption='run-retry')['transition_id'],1)

    def test_new_boot_rebases_even_when_numeric_clock_is_higher(self):
        self.bind()
        self.db.execute("INSERT INTO leases VALUES('solana',117)")
        second=identity('22222222-2222-4222-8222-222222222222')
        result=self.bind(now=1000.,domain=second)
        self.assertEqual(result['transition'],'domain_changed')
        self.assertEqual(self.db.execute('SELECT next_at FROM leases').fetchone()[0],1060.)

    def test_same_boot_other_namespace_requires_exclusive_adoption(self):
        self.bind()
        self.db.execute("INSERT INTO leases VALUES('solana',117)")
        with self.assertRaisesRegex(ProviderClockError,'provider_clock_namespace_changed'):
            self.bind(domain=identity(namespace=43))
        result=self.bind(domain=identity(namespace=43),adoption='run-namespace')
        self.assertEqual(result['transition'],'domain_changed')

    def test_regression_bad_identity_and_invalid_timers_are_contained(self):
        self.bind()
        with self.assertRaisesRegex(ProviderClockError,'provider_clock_regression'):
            self.bind(now=99.)
        for value in (-1.,float('inf'),float('nan'),True,'100'):
            with self.assertRaisesRegex(ProviderClockError,'provider_clock_timer_invalid'):
                validate_timer(value)
        with self.assertRaisesRegex(ProviderClockError,'provider_clock_identity_invalid'):
            self.bind(domain='{}')

    def test_read_only_inspection_does_not_adopt_or_refresh_binding(self):
        self.bind()
        before=list(self.db.iterdump())
        with patch('meme_machine.runtime.provider_clock.current_identity',return_value=identity()):
            row=inspect_clock_domain(self.db,component='source_governor',clock=lambda:101.)
        self.assertEqual(row['state'],'BOUND')
        self.assertEqual(list(self.db.iterdump()),before)

    def test_reader_samples_after_concurrent_writer_metadata_observation(self):
        from meme_machine.runtime import provider_clock
        self.bind();now=[100.];original=provider_clock._metadata
        def advancing_reader(db,component):
            now[0]=105.
            db.execute('UPDATE provider_clock_domain SET last_observed=105')
            return original(db,component)
        with patch.object(provider_clock,'current_identity',return_value=identity()), \
                patch.object(provider_clock,'_metadata',side_effect=advancing_reader):
            observed=inspect_clock_domain(self.db,component='source_governor',clock=lambda:now[0])
        self.assertEqual(observed['state'],'BOUND')
        self.assertEqual(observed['now'],105.)

    def test_concurrent_adopters_commit_one_archive_and_one_quiet_period(self):
        self.db.execute("INSERT INTO leases VALUES('solana',900000)")
        gate=threading.Barrier(3);errors=[];results=[]
        def adopt(index):
            db=sqlite3.connect(self.path,isolation_level=None,timeout=10)
            try:
                gate.wait();db.execute('BEGIN IMMEDIATE')
                result=bind_clock_domain(db,component='source_governor',clock=lambda:100.,
                    quiet_seconds=60.,snapshot=self.snapshot,rebase=self.rebase,
                    adoption_identity='run-'+str(index))
                db.execute('COMMIT');results.append(result)
            except BaseException as error:errors.append(error)
            finally:db.close()
        with patch('meme_machine.runtime.provider_clock.current_identity',return_value=identity()):
            threads=[threading.Thread(target=adopt,args=(index,)) for index in range(2)]
            for thread in threads:thread.start()
            gate.wait()
            for thread in threads:thread.join(15)
        self.assertEqual(errors,[])
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual([r['quiet_until'] for r in results],[160.,160.])
        self.assertEqual(self.db.execute('SELECT count(*) FROM provider_clock_history').fetchone()[0],1)

    def test_binding_requires_existing_write_transaction(self):
        with self.assertRaisesRegex(ProviderClockError,'provider_clock_write_transaction_required'):
            bind_clock_domain(self.db,component='source_governor',clock=lambda:100.,
                quiet_seconds=60.,snapshot=self.snapshot,rebase=self.rebase)

    def test_actual_identity_requires_both_kernel_boot_and_time_namespace(self):
        with patch('meme_machine.runtime.provider_clock.Path.read_text',
                   return_value='11111111-1111-4111-8111-111111111111\n'), \
                patch('meme_machine.runtime.provider_clock.os.stat',
                      return_value=SimpleNamespace(st_dev=4,st_ino=42)):
            self.assertEqual(current_identity(),identity())
        for failure in (FileNotFoundError(),PermissionError()):
            with patch('meme_machine.runtime.provider_clock.Path.read_text',
                       return_value='11111111-1111-4111-8111-111111111111\n'), \
                    patch('meme_machine.runtime.provider_clock.os.stat',side_effect=failure):
                with self.assertRaisesRegex(ProviderClockError,'provider_clock_identity_unavailable'):
                    current_identity()

    def test_malformed_kernel_identity_cannot_be_replaced_by_numeric_inference(self):
        with patch('meme_machine.runtime.provider_clock.Path.read_text',return_value='unknown'), \
                patch('meme_machine.runtime.provider_clock.os.stat',
                      return_value=SimpleNamespace(st_dev=4,st_ino=42)):
            with self.assertRaisesRegex(ProviderClockError,'provider_clock_identity_invalid'):
                current_identity()


if __name__=='__main__':unittest.main()
