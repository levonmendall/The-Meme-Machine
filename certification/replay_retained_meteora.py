"""Offline native-ledger regression. Run from the prepared Meteora worktree.

This command never invokes resume_meteora, discovery, or market certification.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zlib

class RetainedMeteoraRecovery(unittest.TestCase):
    fixture=None
    def setUp(self):
        from meme_machine.dlmm_independent_accounting import PaperBook
        from tests import solana_dlmm_independent_v1 as native
        self.native=native;self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'ledger.sqlite'
        fixture=json.loads(self.fixture.read_text())
        raw=zlib.decompress(base64.b64decode(fixture['rows']))
        self.assertEqual(hashlib.sha256(raw).hexdigest(),fixture['raw_journal_sha256'])
        rows=json.loads(raw)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE events(seq INTEGER PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL)')
            db.executemany('INSERT INTO events VALUES(?,?,?)',rows)
        genesis=json.loads(rows[0][1])['data']
        self.book=PaperBook(self.path,run_id=genesis['run_id'],policy_hash=genesis['policy_hash'],capital=genesis['capital'])
        self.network=patch('socket.socket.connect',side_effect=AssertionError('network_forbidden'));self.network.start()
    def tearDown(self):self.network.stop();self.temp.cleanup()
    def recover(self):
        from certification.position_continuation import restore_meteora_strategy
        return restore_meteora_strategy(self.book,self.native)
    def test_retained_entry_economic_replay_and_restart(self):
        before=self.book.reconcile();self.assertEqual(before['open_positions'],1)
        self.assertEqual(before['settled'],0);self.assertEqual(before['journal_events'],3)
        result=self.book.replay_economics(self.native._build_position,self.native._advance_position,self.native._mark)
        self.assertTrue(result['verified'])
        first=self.recover();second=self.recover()
        self.assertEqual(first,second);self.assertEqual(self.book.reconcile(),before)
        self.assertIsNone(first['restored_exit'])
    def test_report_failure_does_not_lose_real_run_368_position(self):
        from meme_machine.durable_publication import publish_report
        before=self.book.reconcile();state=self.recover()
        with patch('meme_machine.durable_publication.os.replace',side_effect=OSError('publisher_interrupted')):
            self.assertFalse(publish_report(Path(self.temp.name)/'report.json',state)['published'])
        self.assertEqual(self.recover(),state);self.assertEqual(self.book.reconcile(),before)
    def test_real_resumed_monitor_crash_does_not_append_duplicate_entry(self):
        before=self.book.reconcile();state=self.recover()
        for boundary in ('evidence','consumer','lifecycle','publisher'):
            with patch.object(self.native,'_rotate',side_effect=lambda a,*args:a),patch.object(self.native,'_recover_position_observation',side_effect=KeyboardInterrupt(boundary)):
                with self.assertRaises(KeyboardInterrupt):
                    self.native._position_lifecycle(None,state['entry']['pool'],state['entry'],state['features'],
                        state['policy'],None,[],book=self.book,identity=state['identity'],recovered=state)
            self.assertEqual(self.book.reconcile(),before)
            self.assertEqual(self.recover(),state)

    def test_foreign_policy_cannot_recover_retained_position(self):
        from meme_machine.dlmm_independent_accounting import PaperBook
        with self.assertRaisesRegex(ValueError,'genesis_mismatch'):
            PaperBook(self.path,run_id=self.book.run_id,policy_hash='invalid',capital=1_000_000_000)
        self.assertEqual(self.book.reconcile()['open_positions'],1)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--fixture',type=Path,required=True)
    args=parser.parse_args();RetainedMeteoraRecovery.fixture=args.fixture.resolve()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RetainedMeteoraRecovery))
    raise SystemExit(0 if result.wasSuccessful() else 1)

if __name__=='__main__':main()
