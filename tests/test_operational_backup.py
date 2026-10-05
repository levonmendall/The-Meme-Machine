"""Restore real native journals and WAL data to disposable offline targets."""
from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import sqlite3
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

    def test_verify_refuses_authoritative_target(self):
        with patch.dict(os.environ,MM_STATE_ROOT=str(self.root)):
            with self.assertRaisesRegex(ValueError,'isolated_target'):backup.verify_copy(self.root)
            with self.assertRaisesRegex(ValueError,'isolated_target'):backup.prove_replay(self.root)

    def test_copy_never_overwrites_existing_target(self):
        with self.assertRaisesRegex(ValueError,'new_isolated'):backup.copy_state(self.root,self.root)
        sentinel=self.base/'existing';sentinel.mkdir();(sentinel/'sentinel').write_text('keep')
        with self.assertRaisesRegex(ValueError,'new_isolated'):backup.copy_state(self.root,sentinel)
        self.assertEqual((sentinel/'sentinel').read_text(),'keep')

if __name__=='__main__':unittest.main()
