"""Restore real native journals and WAL data to disposable offline targets."""
from contextlib import closing
import fcntl
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from meme_machine.operational import backup
from meme_machine.operational.offline import open_native,open_position,close
from meme_machine.operational.supervisor import Supervisor
from meme_machine.portfolio_accounting import PortfolioAccounting,LANES
from meme_machine.runtime.portfolio import NativePortfolio

class BackupRestore(unittest.TestCase):
    def test_separate_epoch_selection_keeps_historical_500_root_out_of_restore_targets(self):
        new=self.base/'new-shared-1000'
        with patch.dict(os.environ,MM_STATE_ROOT=str(new)):
            for root in (new,new/'child',backup.PRODUCTION_ROOT,backup.PRODUCTION_ROOT/'child'):
                with self.subTest(root=root),self.assertRaisesRegex(ValueError,'restore_verification_requires_isolated_target'):
                    backup.require_isolated(root)
            self.assertEqual(backup.require_isolated(self.base/'isolated-copy'),self.base/'isolated-copy')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'source'
        self.supervisor=Supervisor(self.root,offline=True);self.supervisor.initialize()
        self.addCleanup(self.supervisor.lock.close)
        self.environment=patch.dict(os.environ,MM_PAPER_EPOCH=self.supervisor.epoch)
        self.environment.start();self.addCleanup(self.environment.stop)

    def test_all_lane_journals_survivor_and_pending_delivery_restore_idempotently(self):
        for lane in LANES:
            (self.root/lane).mkdir()
            book,_,_=open_native(self.root,lane,self.supervisor.epoch)
            original=book.portfolio.flush;calls=[0]
            def lost_ack():
                calls[0]+=1
                if calls[0]==2:raise RuntimeError('lost_native_ack')
                return original()
            with patch.object(book.portfolio,'flush',side_effect=lost_ack):
                with self.assertRaisesRegex(RuntimeError,'lost_native_ack'):
                    open_position(book,lane,self.supervisor.epoch,int(time.time()))
            close(book,lane)
        survivor=self.root/'pump'/'survivor.sqlite'
        with sqlite3.connect(survivor) as db:
            db.execute('CREATE TABLE fixture_survivor(lifecycle,state)')
            db.execute('INSERT INTO fixture_survivor VALUES(?,?)',('preserved','runner'))
        before=backup.state_identity(self.root)
        self.assertEqual(len(before['pending_deliveries']),4)
        self.assertEqual(len(before['replayed_state']['reservations']),4)
        copied=self.base/'restored';backup.copy_state(self.root,copied)
        self.assertTrue(backup.verify_copy(copied)['passed'])
        self.assertEqual(backup.state_identity(copied),before)
        self.assertTrue(backup.prove_replay(copied)['single_writer_fencing'])
        for lane in LANES:
            book,rows,_=open_native(copied,lane,self.supervisor.epoch)
            self.assertEqual(len(rows),1)
            book.portfolio.recover();book.portfolio.recover()
            close(book,lane)
        restored=backup.state_identity(copied)
        self.assertEqual(restored['epoch_id'],before['epoch_id'])
        self.assertEqual(len(restored['replayed_state']['positions']),4)
        self.assertFalse(restored['replayed_state']['reservations'])
        self.assertFalse(restored['pending_deliveries'])
        self.assertEqual(backup.state_identity(self.root),before)
        with closing(sqlite3.connect(copied/'pump'/'survivor.sqlite')) as db:
            self.assertEqual(db.execute('SELECT * FROM fixture_survivor').fetchall(),[('preserved','runner')])

    def test_wal_contents_and_realized_pnl_are_preserved(self):
        from meme_machine.portfolio_lane_integration import usd_evidence
        from meme_machine.portfolio_accounting import digest
        from meme_machine.runtime.usd_valuation import utc
        at=utc(time.time());until=utc(time.time()+120)
        client=NativePortfolio(self.root/'portfolio.sqlite','pump')
        def event(kind,data,key):
            return dict(event_key=key,journal_hash=digest([key,data]),kind=kind,at=at,data=data,
                value_evidence=usd_evidence('offline','e'*64,at,until) if kind!='reserve' else None)
        client.deliver('realized',**event('reserve',{'amount':'6.25'},'reserve'))
        client.deliver('realized',**event('enter',{'asset':'fixture','basis':'6.25','fee':'0','strategy_id':'pump'},'entry'))
        client.deliver('realized',**event('settle',{'gross_proceeds':'7.25','fee':'0','exit_reason':'fixture'},'settle'))
        extra=self.root/'wal.sqlite'
        db=sqlite3.connect(extra);self.addCleanup(db.close)
        db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE fixture(value)')
        db.execute('INSERT INTO fixture VALUES(73)');db.commit()
        target=self.base/'copy';backup.copy_state(self.root,target)
        self.assertFalse((target/'wal.sqlite-wal').exists())
        with closing(sqlite3.connect(target/'wal.sqlite')) as restored:
            self.assertEqual(restored.execute('SELECT value FROM fixture').fetchone(),(73,))
        self.assertEqual(backup.state_identity(self.root),backup.state_identity(target))
        self.assertEqual(backup.state_identity(target)['replayed_state']['positions']['pump:n1']['realized_pnl'],{'decimal':'1.00'})

    def test_failed_copy_cannot_be_used_as_restore(self):
        target=self.base/'interrupted'
        with self.assertRaises(TimeoutError):backup.copy_state(self.root,target,seconds=-1)
        self.assertFalse((target/'backup.json').exists())
        self.assertFalse(json.loads((target/'backup-failed.json').read_text())['usable'])

    def test_late_flush_failure_cannot_authorize_verification_replay_or_reuse(self):
        before=backup.state_identity(self.root)
        for number,error in enumerate((
            subprocess.TimeoutExpired(['sync'],5),
            subprocess.CalledProcessError(1,['sync']))):
            with self.subTest(error=type(error).__name__):
                target=self.base/('flush-failed-'+str(number))
                with patch.object(backup.subprocess,'run',side_effect=error) as flush:
                    with self.assertRaises(type(error)) as raised:
                        backup.copy_state(self.root,target)
                self.assertIs(raised.exception,error)
                flush.assert_called_once_with(['sync','-f',str(target)],check=True,timeout=5)
                # The manifest existed before the final flush failed. Its
                # presence must not turn a failed point into restore authority.
                self.assertTrue((target/'backup.json').exists())
                self.assertFalse(json.loads((target/'backup-failed.json').read_text())['usable'])
                self.assertEqual(backup.state_identity(self.root),before)
                self.assertIsNone(backup.reusable_point(self.root,target))
                for verify in (backup.verify_copy,backup.prove_replay):
                    with self.assertRaisesRegex(RuntimeError,'backup_point_incomplete_or_failed'):
                        verify(target)

    def test_failed_or_incomplete_point_is_rejected_before_database_open(self):
        for name in ('backup-incomplete.json','backup-failed.json'):
            with self.subTest(marker=name):
                target=self.base/name.replace('.json','');target.mkdir()
                (target/name).write_text('{"usable":false}')
                with patch.object(backup.sqlite3,'connect',side_effect=AssertionError('invalid point opened')):
                    for verify in (backup.verify_copy,backup.prove_replay):
                        with self.assertRaisesRegex(RuntimeError,'backup_point_incomplete_or_failed'):
                            verify(target)

    def test_verified_exact_snapshot_reuse_makes_no_new_copy(self):
        point=self.base/'point';backup.copy_state(self.root,point)
        target=self.base/'unnecessary-copy'
        with patch('meme_machine.operational.artifact_storage.admit_snapshot',side_effect=AssertionError('new copy admission')):
            row=backup.copy_state(self.root,target,reuse=point)
        self.assertTrue(row['reused']);self.assertEqual(row['directory'],str(point))
        self.assertFalse(target.exists())

    def test_same_portfolio_does_not_allow_reuse_after_native_cursor_changes(self):
        extra=self.root/'native-cursor.txt';extra.write_text('original cursor')
        point=self.base/'point';backup.copy_state(self.root,point)
        extra.write_text('advanced native cursor')
        self.assertIsNone(backup.reusable_point(self.root,point))
        extra.write_text('original cursor');(point/'native-cursor.txt').write_text('corrupt survivor')
        self.assertIsNone(backup.reusable_point(self.root,point))

    def test_disk_rejection_precedes_partial_copy_and_does_not_change_source(self):
        from meme_machine.operational.artifact_storage import ArtifactStorageFull
        target=self.base/'rejected';source=(self.root/'portfolio.sqlite').read_bytes()
        with patch('meme_machine.operational.artifact_storage.admit_snapshot',side_effect=ArtifactStorageFull('root_headroom')):
            with self.assertRaises(ArtifactStorageFull):backup.copy_state(self.root,target)
        self.assertFalse(target.exists());self.assertEqual((self.root/'portfolio.sqlite').read_bytes(),source)

    def test_space_loss_during_copy_retains_partial_failure_without_restore_authority(self):
        from meme_machine.operational.artifact_storage import ArtifactStorageFull
        target=self.base/'partial';before=backup.state_identity(self.root)
        error=ArtifactStorageFull('destination_copy_reserve_required',admission=dict(
            estimated_bytes=100,free_bytes=105,reserve_bytes=10))
        with patch('meme_machine.operational.artifact_storage.headroom',side_effect=[{},error]):
            with self.assertRaises(ArtifactStorageFull) as caught:backup.copy_state(self.root,target)
        self.assertIs(caught.exception,error)
        self.assertFalse((target/'backup.json').exists())
        self.assertTrue((target/'backup-incomplete.json').exists())
        failure=json.loads((target/'backup-failed.json').read_text())
        self.assertFalse(failure['usable'])
        self.assertEqual(failure['storage_admission'],dict(reason='destination_copy_reserve_required',
            estimated_bytes=100,free_bytes=105,reserve_bytes=10))
        self.assertEqual(backup.state_identity(self.root),before)

    def test_verify_refuses_authoritative_target(self):
        with patch.dict(os.environ,MM_STATE_ROOT=str(self.root)):
            with self.assertRaisesRegex(ValueError,'isolated_target'):backup.verify_copy(self.root)
            with self.assertRaisesRegex(ValueError,'isolated_target'):backup.prove_replay(self.root)

    def test_copy_never_overwrites_existing_target(self):
        with self.assertRaisesRegex(ValueError,'new_isolated'):backup.copy_state(self.root,self.root)
        sentinel=self.base/'existing';sentinel.mkdir();(sentinel/'sentinel').write_text('keep')
        with self.assertRaisesRegex(ValueError,'new_isolated'):backup.copy_state(self.root,sentinel)
        self.assertEqual((sentinel/'sentinel').read_text(),'keep')

    def test_cleanup_of_inactive_or_already_thawed_unit_is_successful(self):
        with patch.object(backup.subprocess,'check_output',return_value='running\n'), \
                patch.object(backup.subprocess,'run') as thaw:
            self.assertFalse(backup.thaw_if_needed()['thawed'])
        thaw.assert_not_called()

    def test_cleanup_of_frozen_unit_thaws_and_does_not_hide_failure(self):
        with patch.object(backup.subprocess,'check_output',return_value='frozen\n'), \
                patch.object(backup.subprocess,'run') as thaw:
            self.assertTrue(backup.thaw_if_needed()['thawed'])
        thaw.assert_called_once_with(['systemctl','thaw',backup.PAPER_UNIT],check=True,timeout=5)
        with patch.object(backup.subprocess,'check_output',return_value='frozen\n'), \
                patch.object(backup.subprocess,'run',side_effect=subprocess.CalledProcessError(1,'thaw')):
            with self.assertRaises(subprocess.CalledProcessError):backup.thaw_if_needed()

    def test_abandoned_copies_are_bounded_without_losing_successes_or_unrelated_work(self):
        from meme_machine.operational.digitalocean_backup import retain_local_points
        parent=self.base/'points';parent.mkdir()
        for number in range(6):
            for kind,marker in (('complete','backup.json'),('failed','backup-failed.json'),
                                ('killed','backup-incomplete.json')):
                folder=parent/f'meme-machine-paper-{kind}-{number}';folder.mkdir()
                (folder/marker).write_text('{}')
                os.utime(folder,(number,number))
        unrelated=parent/'other-project';unrelated.mkdir();(unrelated/'keep').write_text('preserve')
        unknown=parent/'meme-machine-paper-unknown';unknown.mkdir();(unknown/'keep').write_text('preserve')
        link=parent/'meme-machine-paper-link';link.symlink_to(unrelated,target_is_directory=True)
        retain_local_points(parent,'meme-machine-paper-',3)
        complete=[p for p in parent.iterdir() if (p/'backup.json').is_file()]
        partial=[p for p in parent.iterdir() if (p/'backup-failed.json').is_file() or (p/'backup-incomplete.json').is_file()]
        self.assertEqual(len(complete),3);self.assertEqual(len(partial),3)
        self.assertTrue((parent/'meme-machine-paper-complete-5'/'backup.json').is_file())
        self.assertEqual((unrelated/'keep').read_text(),'preserve')
        self.assertEqual((unknown/'keep').read_text(),'preserve');self.assertTrue(link.is_symlink())


class BackupAdmissionReporting(unittest.TestCase):
    def error(self):
        from meme_machine.operational.artifact_storage import ArtifactStorageFull
        return ArtifactStorageFull('destination_copy_reserve_required',admission=dict(
            estimated_bytes=200,free_bytes=205,reserve_bytes=10))

    def test_scheduled_pre_copy_rejection_retains_reason_and_original_exception(self):
        from meme_machine.operational import digitalocean_backup as scheduled
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);root=base/'source';root.mkdir();parent=base/'points';parent.mkdir()
            config=base/'config.json';config.write_text(json.dumps(dict(point_parent=str(parent),
                volume_id='fixture-volume',droplet_id=7,region='fixture',snapshot_prefix='meme-machine-paper-',
                retained_snapshots=3)))
            error=self.error();volume=dict(volume=dict(droplet_ids=[7],region=dict(slug='fixture')))
            with patch.dict(os.environ,MM_STATE_ROOT=str(root)), \
                    patch.object(scheduled,'verify_storage',return_value=dict(mount_target=str(base),epoch_id='fixture-epoch')), \
                    patch.object(scheduled,'request',return_value=(200,volume)) as request, \
                    patch.object(scheduled,'prepare',side_effect=error) as prepare:
                with self.assertRaises(type(error)) as caught:scheduled.execute(config,base/'output')
            self.assertIs(caught.exception,error)
            request.assert_called_once_with('GET','/v2/volumes/fixture-volume')
            self.assertFalse(prepare.call_args.kwargs['nonessential'])
            self.assertFalse(list(parent.glob('meme-machine-paper-*')))
            result=json.loads((base/'output'/'latest.json').read_text())
            self.assertEqual((result['status'],result['error_type'],result['snapshot_id']),('FAIL','ArtifactStorageFull',None))
            self.assertEqual(result['storage_admission'],dict(reason='destination_copy_reserve_required',
                estimated_bytes=200,free_bytes=205,reserve_bytes=10))

    def test_backup_and_scheduled_cli_keep_bounded_admission_facts_without_paths(self):
        from meme_machine.operational import digitalocean_backup as scheduled
        error=self.error()
        with patch('sys.argv',['backup','prepare','/SECRET-target','--state-root','/SECRET-source']), \
                patch.object(backup,'prepare',side_effect=error),patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(backup.main(),1)
        result=json.loads(output.getvalue())
        self.assertFalse(result['passed']);self.assertEqual(result['error_type'],'ArtifactStorageFull')
        self.assertEqual(result['storage_admission']['estimated_bytes'],200)
        self.assertNotIn('SECRET',output.getvalue())
        with patch.object(scheduled,'execute',side_effect=error),patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(scheduled.main(),1)
        self.assertEqual(json.loads(output.getvalue())['storage_admission'],result['storage_admission'])
        self.assertLess(len(output.getvalue()),512)

    def test_unrelated_failure_keeps_existing_error_type_without_text(self):
        from meme_machine.operational import digitalocean_backup as scheduled
        with patch.object(scheduled,'execute',side_effect=RuntimeError('SECRET')), \
                patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(scheduled.main(),1)
        self.assertEqual(json.loads(output.getvalue()),dict(status='FAIL',error_type='RuntimeError'))

if __name__=='__main__':unittest.main()
