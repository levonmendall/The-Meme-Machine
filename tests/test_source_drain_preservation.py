"""Preserve retained source failures through the real disposable canonical owner.

Handler locators are not handler recovery or coverage proof. No providers, PAPER
services, financial state, or production files participate in these fixtures.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from meme_machine import solana_source_drain as drain
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_selective_source import SelectiveSource
from tests.test_solana_closure import NOW, state_at


OLD_RUN = '85ce1aa8c9c54be0addd87a37e81784b'
OLD_PID = 3046583
NEW_RUN = 'd' * 32


class DrainFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state, self.history = state_at(Path(temporary.name) / 'canonical.sqlite')
        self.addCleanup(self.state.writer.close)
        self.db = self.state.writer.db
        self.db.execute("INSERT INTO candidate_checkpoints VALUES('candidate:pump:old',17,'old-receipt',1)")
        self.db.execute("""INSERT INTO candidate_history_outbox
            (id,family,address,kind,body,hash,created,consumed,priority)
            VALUES('old-history','pump','mint','canonical','{}','old-hash',1,NULL,4)""")
        self.db.execute("""INSERT INTO candidate_pending_proofs
            VALUES('old-proof','candidate:pump:old',1,2,'alchemy_finalized_stream',?,'{}',1)""",
            ('a' * 64,))
        self.history.gap('candidate:pump:old', 1, None, 'retained_source_gap')
        drain.preserve_control_recovery(self.state, 457279885, 457279885)

    def old_body(self, **changes):
        body = dict(state='RECOVERY_REQUIRED', terminal=True,
            run_identity=OLD_RUN, source_pid=OLD_PID,
            accepted_handlers=564488, settled_handlers=564486, pending_handlers=2,
            closed_sessions=2, preserved_partial_sessions=2, unpreserved_sessions=0,
            started_at_monotonic=10.0, terminal_at_monotonic=20.0,
            queues={name: dict(accepted=3, committed=3, pending=0)
                for name in ('control', 'scout', 'rolling', 'candidate')},
            all_accepted_committed=True, pending_history=1, pending_proofs=1,
            fixture_note='exact retained caf\u00e9 bytes')
        body.update(changes)
        return body

    def new_body(self):
        source = SelectiveSource(SimpleNamespace(credential='offline', identity='a' * 64), None)
        body = source.drain_snapshot()
        body.update(state='DRAINED', terminal=True, terminal_at_monotonic=30.0)
        return body

    def handler(self, identity, *, run=OLD_RUN, pid=OLD_PID, state='INTERRUPTED'):
        recovery = (dict(kind='CONTROL_REPLAY', lower_slot=457279885,
            upper_slot=457279885, coverage_after_id=0) if state == 'RECOVERABLE' else None)
        return dict(id=identity, run=run, source_pid=pid, native_thread_id=7,
            stream='retained-stream', session='retained-session',
            transport='yellowstone', family='shared', kind='block_meta',
            slot=457279885, identity=None, seen=NOW,
            scope_hash=drain.HandlerLedger.scope_hash(('control:solana',)), scope_count=1,
            started_monotonic=11.0, phase='CONTROL_QUEUE', state=state,
            failure_state='INTERRUPTED', error_type='CancelledError', recovery=recovery)

    def known_rows(self):
        # Callback completion can be out of order. Unique IDs within the old
        # accepted census locate these callbacks without inventing their fate.
        return [self.handler(17, state='RECOVERABLE'), self.handler(29)]

    @staticmethod
    def raw(body):
        # Deliberately noncanonical formatting and UTF-8 must survive archival.
        return json.dumps(body, ensure_ascii=False, indent=2) + ' \n'

    def put_raw(self, key, raw):
        self.db.execute('INSERT OR REPLACE INTO service_health VALUES(?,?)', (key, raw))

    def put_old(self, *, body=None, rows=None, ledger=True):
        raw = self.raw(self.old_body() if body is None else body)
        self.put_raw('source_drain', raw)
        handler_raw = None
        if ledger:
            handler_raw = self.raw(dict(version=1,
                records=self.known_rows() if rows is None else rows))
            self.put_raw(drain.HANDLER_RECOVERY_KEY, handler_raw)
        return raw, handler_raw

    def value(self, key):
        row = self.db.execute('SELECT value FROM service_health WHERE key=?', (key,)).fetchone()
        return None if row is None else row[0]

    def facts(self):
        names = [row[0] for row in self.db.execute("""SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name""")]
        return {name: self.db.execute('SELECT * FROM "' + name + '"').fetchall()
            for name in names}

    @staticmethod
    def archive_key(raw, *, handlers=False):
        prefix = 'source_handler_recovery_preserved.' if handlers else 'source_drain_preserved.'
        return prefix + hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def preserved_keys(self):
        return self.db.execute("""SELECT key FROM service_health
            WHERE key LIKE 'source_drain_preserved.%'
               OR key LIKE 'source_handler_recovery_preserved.%' ORDER BY key""").fetchall()


class SourceDrainPreservationTests(DrainFixture, unittest.TestCase):
    def test_no_prior_terminal_returns_none_and_never_creates_a_historical_archive(self):
        self.assertIsNone(drain.retained_source_drain(self.state))
        body = self.new_body()
        drain.publish_source_drain(self.state, None, body)
        self.assertEqual(json.loads(self.value('source_drain')), body)
        self.assertEqual(self.preserved_keys(), [])

    def test_malformed_handler_ledger_refuses_even_with_no_or_zero_pending_census(self):
        bad = ['{"version":1,"records":[null]}',
            '{"version":1,"records":[],"version":1}',
            self.raw(dict(version=1, records=[{}] * 65))]
        for no_census in (False, True):
            for raw in bad:
                with self.subTest(no_census=no_census, raw=raw[:48]):
                    self.put_old(body=self.old_body(state='DRAINED',
                        settled_handlers=564488, pending_handlers=0), ledger=False)
                    if no_census:
                        self.db.execute("DELETE FROM service_health WHERE key='source_drain'")
                    self.put_raw(drain.HANDLER_RECOVERY_KEY, raw)
                    original=self.facts()
                    with self.assertRaises(EvidenceUnavailable):
                        drain.retained_source_drain(self.state)
                    self.assertEqual(self.facts(), original)

    def test_historical_unknown_two_refuses_without_changing_any_canonical_state(self):
        raw, _ = self.put_old(ledger=False)
        original = self.facts()
        with self.assertRaisesRegex(EvidenceUnavailable, 'source_drain_historical_handlers_unlocated'):
            drain.retained_source_drain(self.state)
        self.assertEqual(self.value('source_drain'), raw)
        self.assertEqual(self.facts(), original)
        self.assertEqual(self.preserved_keys(), [])

    def test_equal_handler_count_from_another_run_or_pid_cannot_locate_the_old_census(self):
        cases = [
            [self.handler(17, run=NEW_RUN), self.handler(29, run=NEW_RUN)],
            [self.handler(17, pid=OLD_PID + 1), self.handler(29, pid=OLD_PID + 1)],
            [self.handler(17), self.handler(29, run=NEW_RUN)],
        ]
        for rows in cases:
            with self.subTest(rows=[(r['run'], r['source_pid']) for r in rows]):
                self.put_old(rows=rows)
                original = self.facts()
                with self.assertRaisesRegex(EvidenceUnavailable, 'source_drain_historical_handlers_unlocated'):
                    drain.retained_source_drain(self.state)
                self.assertEqual(self.facts(), original)
                self.assertEqual(self.preserved_keys(), [])

    def test_missing_partial_duplicate_or_outside_accepted_handler_ids_are_refused(self):
        cases = [[], [self.handler(17)],
            [self.handler(17), self.handler(17)],
            [self.handler(17), self.handler(0)],
            [self.handler(17), self.handler(True)],
            [self.handler(17), self.handler('29')],
            [self.handler(17), self.handler(564489)]]
        for rows in cases:
            with self.subTest(ids=[r['id'] for r in rows]):
                self.put_old(rows=rows)
                original = self.facts()
                with self.assertRaises(EvidenceUnavailable):
                    drain.retained_source_drain(self.state)
                self.assertEqual(self.facts(), original)

    def test_known_complete_locator_returns_exact_raw_without_claiming_recovery(self):
        raw, handler_raw = self.put_old()
        original = self.facts()
        self.assertEqual(drain.retained_source_drain(self.state), raw)
        self.assertEqual(self.facts(), original)
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY), handler_raw)
        self.assertEqual([r['state'] for r in json.loads(handler_raw)['records']],
            ['RECOVERABLE', 'INTERRUPTED'])
        self.assertEqual(json.loads(self.value('source_drain'))['state'], 'RECOVERY_REQUIRED')
        self.assertEqual(self.preserved_keys(), [])

    def test_drain_counters_must_be_strict_nonnegative_and_consistent(self):
        cases = [dict(accepted_handlers=True), dict(accepted_handlers='564488'),
            dict(accepted_handlers=564488.0), dict(accepted_handlers=-1),
            dict(settled_handlers=-1), dict(settled_handlers=564489),
            dict(settled_handlers=None), dict(pending_handlers=True),
            dict(pending_handlers=-1), dict(pending_handlers=1)]
        for changes in cases:
            with self.subTest(changes=changes):
                self.put_old(body=self.old_body(**changes))
                original = self.facts()
                with self.assertRaises(EvidenceUnavailable):
                    drain.retained_source_drain(self.state)
                self.assertEqual(self.facts(), original)

    def test_invalid_json_and_utf8_byte_bounds_refuse_without_mutation(self):
        for raw in ('{', 'null', '[]', '{}',
                self.raw(self.old_body(fixture_note='\u00e9' * (70 * 1024)))):
            with self.subTest(raw_prefix=raw[:24]):
                self.put_raw('source_drain', raw)
                original = self.facts()
                with self.assertRaises(EvidenceUnavailable):
                    drain.retained_source_drain(self.state)
                self.assertEqual(self.facts(), original)

    def test_existing_handler_ledger_bounds_and_shape_are_not_bypassed(self):
        oversized = self.known_rows()
        oversized[0]['fixture_note'] = '\u00e9' * (25 * 1024)
        cases = [dict(version=2, records=self.known_rows()),
            dict(version=1, records=None),
            dict(version=1, records=oversized),
            dict(version=1, records=[self.handler(i) for i in range(1, 66)])]
        for body in cases:
            with self.subTest(version=body['version'],
                    records=None if body['records'] is None else len(body['records'])):
                self.put_old()
                self.put_raw(drain.HANDLER_RECOVERY_KEY, self.raw(body))
                original = self.facts()
                with self.assertRaises(EvidenceUnavailable):
                    drain.retained_source_drain(self.state)
                self.assertEqual(self.facts(), original)

    def test_failed_terminal_and_original_handler_snapshot_are_archived_as_exact_bytes(self):
        raw, handler_raw = self.put_old()
        boundary = drain.retained_source_drain(self.state)
        body = self.new_body()
        original = self.facts()
        drain.publish_source_drain(self.state, boundary, body, handler_boundary=handler_raw)
        self.assertEqual(self.value(self.archive_key(raw)), raw)
        self.assertEqual(self.value(self.archive_key(handler_raw, handlers=True)), handler_raw)
        self.assertEqual(json.loads(self.value('source_drain')), body)
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY), handler_raw)
        after = self.facts()
        self.assertEqual({k: v for k, v in after.items() if k != 'service_health'},
            {k: v for k, v in original.items() if k != 'service_health'})

    def test_preexisting_identical_archives_are_idempotent_and_keep_original_rows(self):
        raw, handler_raw = self.put_old()
        for item, handlers in ((raw, False), (handler_raw, True)):
            self.put_raw(self.archive_key(item, handlers=handlers), item)
        archive_rows = self.db.execute("""SELECT rowid,key,value FROM service_health
            WHERE key LIKE '%_preserved.%' ORDER BY key""").fetchall()
        drain.publish_source_drain(self.state, drain.retained_source_drain(self.state),
            self.new_body(), handler_boundary=handler_raw)
        self.assertEqual(self.db.execute("""SELECT rowid,key,value FROM service_health
            WHERE key LIKE '%_preserved.%' ORDER BY key""").fetchall(), archive_rows)

    def test_archive_collision_refuses_both_new_terminal_and_any_other_archive(self):
        for handlers in (False, True):
            with self.subTest(handlers=handlers):
                raw, handler_raw = self.put_old()
                selected = handler_raw if handlers else raw
                key = self.archive_key(selected, handlers=handlers)
                self.put_raw(key, 'different immutable archive bytes')
                original = self.facts()
                with self.assertRaises(EvidenceUnavailable):
                    drain.publish_source_drain(self.state, raw, self.new_body(),
                        handler_boundary=handler_raw)
                self.assertEqual(self.facts(), original)
                self.db.execute('DELETE FROM service_health WHERE key=?', (key,))

    def test_semantically_identical_rewritten_drain_or_competing_terminal_cannot_cross_boundary(self):
        raw, handler_raw = self.put_old()
        boundary = drain.retained_source_drain(self.state)
        for competing in (raw + '\n', self.raw(self.new_body())):
            with self.subTest(kind='format' if competing.startswith(raw) else 'competing run'):
                self.put_raw('source_drain', competing)
                original = self.facts()
                with self.assertRaises(EvidenceUnavailable):
                    drain.assert_source_drain_boundary(self.state, boundary,
                        handler_boundary=handler_raw)
                with self.assertRaises(EvidenceUnavailable):
                    drain.publish_source_drain(self.state, boundary, self.new_body(),
                        handler_boundary=handler_raw)
                self.assertEqual(self.facts(), original)

    def test_old_handler_subset_may_be_reformatted_and_appended_but_not_rewritten(self):
        raw, handler_raw = self.put_old()
        appended = dict(version=1, records=[*reversed(self.known_rows()),
            self.handler(1, run=NEW_RUN, pid=OLD_PID + 1)])
        current = json.dumps(appended, sort_keys=True, separators=(',', ':'))
        self.put_raw(drain.HANDLER_RECOVERY_KEY, current)
        drain.assert_source_drain_boundary(self.state, raw, handler_boundary=handler_raw)
        drain.publish_source_drain(self.state, raw, self.new_body(), handler_boundary=handler_raw)
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY), current)
        self.assertEqual(self.value(self.archive_key(handler_raw, handlers=True)), handler_raw)

    def test_mutated_missing_or_duplicate_original_handler_rows_refuse_terminal_publication(self):
        cases = [self.known_rows()[:1],
            [dict(self.known_rows()[0], phase='DIFFERENT_PHASE'), self.known_rows()[1]],
            [*self.known_rows(), self.known_rows()[0]]]
        for rows in cases:
            with self.subTest(rows=len(rows), phase=rows[0]['phase']):
                raw, handler_raw = self.put_old()
                self.put_raw(drain.HANDLER_RECOVERY_KEY, self.raw(dict(version=1, records=rows)))
                original = self.facts()
                with self.assertRaises(EvidenceUnavailable):
                    drain.publish_source_drain(self.state, raw, self.new_body(),
                        handler_boundary=handler_raw)
                self.assertEqual(self.facts(), original)

    def test_handler_preservation_both_archives_and_new_terminal_rollback_together(self):
        raw, handler_raw = self.put_old()
        original = self.facts()
        ledger = drain.HandlerLedger(NEW_RUN)
        row = self.handler(1, run=NEW_RUN, pid=ledger.pid)
        row = {key: value for key, value in row.items()
            if key not in ('run', 'source_pid', 'native_thread_id', 'recovery')}
        row['slot'] = None
        error = RuntimeError('injected after terminal publication')
        with self.assertRaises(RuntimeError) as caught:
            with self.state.writer.transaction():
                drain.assert_source_drain_boundary(self.state, raw,
                    handler_boundary=handler_raw)
                drain.preserve_handlers(self.state, ledger, [row], None)
                drain.publish_source_drain(self.state, raw, self.new_body(),
                    handler_boundary=handler_raw)
                self.assertEqual(self.value(self.archive_key(raw)), raw)
                self.assertEqual(len(json.loads(self.value(drain.HANDLER_RECOVERY_KEY))['records']), 3)
                raise error
        self.assertIs(caught.exception, error)
        self.assertEqual(self.facts(), original)
        self.assertFalse(self.db.in_transaction)

    def test_original_commit_failure_rolls_back_archives_and_preserves_exception(self):
        raw, handler_raw = self.put_old()
        original = self.facts()
        error = sqlite3.OperationalError('injected terminal FULL commit failure')
        statement = self.state.writer._transaction_statement

        def fail_commit(sql, stage):
            if stage == 'commit':
                raise error
            return statement(sql, stage)

        with patch.object(self.state.writer, '_transaction_statement', side_effect=fail_commit):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                drain.publish_source_drain(self.state, raw, self.new_body(),
                    handler_boundary=handler_raw)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.facts(), original)
        self.assertFalse(self.db.in_transaction)


class SourceDrainStartupPreservationTests(DrainFixture, unittest.IsolatedAsyncioTestCase):
    async def test_actual_boot_rejects_unknown_old_handlers_before_install_startup_or_provider(self):
        raw, _ = self.put_old(ledger=False)
        original = self.facts()
        source = SelectiveSource(SimpleNamespace(credential='offline', identity='a' * 64), None)
        stop = asyncio.Event()
        calls = []

        async def work(function, priority=2, **options):
            calls.append(priority)
            return function(self.state)

        with patch('meme_machine.solana_selective_source.install') as install, \
                patch.object(self.history.startup, 'begin') as begin, \
                patch.object(source, 'measured_rpc', new_callable=AsyncMock) as rpc, \
                patch('meme_machine.solana_selective_source.grpc.aio.secure_channel') as channel:
            with self.assertRaisesRegex(EvidenceUnavailable,
                    'source_drain_historical_handlers_unlocated'):
                await asyncio.wait_for(source.run(work, stop), .5)
            install.assert_not_called()
            begin.assert_not_called()
            rpc.assert_not_awaited()
            channel.assert_not_called()
        self.assertEqual(calls, [0])
        self.assertEqual(self.value('source_drain'), raw)
        self.assertEqual(self.facts(), original)
        self.assertEqual(self.preserved_keys(), [])


if __name__ == '__main__':
    unittest.main()
