"""The real Pump startup must release its old-epoch reader on every path."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from meme_machine.lanes.pump import runner


class PumpRestartConnectionTests(unittest.TestCase):
    def check_restart(self, *, mismatch=False, malformed=False):
        original = sqlite3.connect
        opened, closed = [], []

        class Tracked(sqlite3.Connection):
            def close(self):
                closed.append(threading.get_ident())
                return super().close()

        def connect(*args, **kwargs):
            db = original(*args, **kwargs, factory=Tracked)
            opened.append(db)
            return db

        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'pump.json'
            path = report.with_suffix('.accounting.sqlite3')
            db = original(path)
            db.execute('CREATE TABLE genesis(body TEXT)')
            db.execute('INSERT INTO genesis VALUES(?)', (
                'invalid-json' if malformed else json.dumps({'run_id': 'preserved-epoch'}),))
            db.commit()
            db.close()
            before = path.read_bytes()
            try:
                with patch.object(runner, 'REPORT', report), patch.dict(
                        os.environ, {'MM_PAPER_EPOCH': 'other-epoch' if mismatch else 'preserved-epoch'}), \
                        patch('sqlite3.connect', side_effect=connect), \
                        patch('meme_machine.lanes.pump.paper_accounting.PaperBook',
                              side_effect=RuntimeError('stop-after-old-epoch-read')) as book:
                    if malformed:
                        with self.assertRaises(json.JSONDecodeError):
                            runner.main()
                    else:
                        expected = 'paper_recovery_run_identity_mismatch' if mismatch else 'stop-after-old-epoch-read'
                        with self.assertRaisesRegex(RuntimeError, expected):
                            runner.main()
                    if not mismatch and not malformed:
                        self.assertEqual(book.call_args.kwargs['run_id'], 'preserved-epoch')
                    else:
                        book.assert_not_called()
                self.assertEqual(len(opened), 1)
                self.assertEqual(closed, [threading.get_ident()])
                with self.assertRaises(sqlite3.ProgrammingError):
                    opened[0].execute('SELECT 1')
                self.assertEqual(path.read_bytes(), before)
            finally:
                for connection in opened:
                    connection.close()

    def test_existing_epoch_reader_closed_before_native_book(self):
        self.check_restart()

    def test_epoch_mismatch_closes_reader_without_replacement(self):
        self.check_restart(mismatch=True)

    def test_invalid_old_genesis_closes_reader_and_fails_closed(self):
        self.check_restart(malformed=True)
