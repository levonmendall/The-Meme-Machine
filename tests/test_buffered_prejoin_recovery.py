"""Committed native frames do not return an interrupted WebSocket callback.

The producer uses the real join, commit FIFO, writer and handler ledger. Only
the transient log-buffer allocation bound is reduced. Archive pages, FULL
consumer commits, ACKs and restart verification use their production paths.
All provider data, financial state and databases are disposable and offline.
"""
import asyncio
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import based58

from meme_machine import solana_source_drain as drain
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.solana_candidate_join import CandidateTransactionJoin
from meme_machine.solana_evidence_plane import EvidenceUnavailable, canonical
from meme_machine.solana_history_delivery import capture, deliver, acknowledge
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import (
    CandidateCommitQueue, SelectiveSource, commit_control,
    preserve_subscription_handoff, wait_candidate_log_space,
)
from meme_machine.yellowstone import geyser_pb2 as pb
from tests import test_archive_recovered_session as archive_fixture
from tests import test_session_economic_recovery as session_fixture


FAMILIES = ('pump', 'pumpswap')
SCOPES = tuple(program_scope(family) for family in FAMILIES)
HEAD = 457949453
FLOOR, UPPER = HEAD-2, HEAD+3


class BufferedPrejoinRecoveryTests(unittest.TestCase):
    facts = session_fixture.SessionEconomicRecoveryTests.facts
    value = session_fixture.SessionEconomicRecoveryTests.value
    put = session_fixture.SessionEconomicRecoveryTests.put
    changed_owner = session_fixture.SessionEconomicRecoveryTests.changed_owner
    native_frame = session_fixture.SessionEconomicRecoveryTests.native_frame
    descriptor = session_fixture.SessionEconomicRecoveryTests.descriptor
    preserve = session_fixture.SessionEconomicRecoveryTests.preserve
    verify = session_fixture.SessionEconomicRecoveryTests.verify
    publish = session_fixture.SessionEconomicRecoveryTests.publish
    recover = session_fixture.SessionEconomicRecoveryTests.recover
    refused = session_fixture.SessionEconomicRecoveryTests.refused
    clean_session = session_fixture.SessionEconomicRecoveryTests.clean_session
    assert_original_evidence = session_fixture.SessionEconomicRecoveryTests.assert_original_evidence

    def setUp(self):
        self.base = archive_fixture.ArchiveRecoveredSessionTests('runTest')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.state, self.history, self.db = self.base.state, self.base.history, self.base.db
        self.cache, self.life = self.base.cache, self.history.lifecycle
        self.old_source, self.old_handler = self.base.old_source_raw, self.base.old_handler_raw
        self.old_handler_record = json.loads(self.old_handler)['records'][0]
        self.old_pending = self.db.execute(
            "SELECT * FROM candidate_pending_proofs WHERE id='old-proof'").fetchall()
        self.old_gaps = self.db.execute(
            'SELECT * FROM candidate_gaps WHERE id IN (39592,39593) ORDER BY id').fetchall()
        self.financial_before = self.base.funding.facts()
        self.base.at += 10
        self.incident = self.interrupt_buffered_log()

    def interrupt_buffered_log(self, head=HEAD):
        floor, upper = head-2, head+3
        source = SelectiveSource(SimpleNamespace(credential='offline', identity='a'*64), None)
        source.contained_observation = True
        source.stop = asyncio.Event()
        source.batched = True
        session = uuid.uuid4().hex
        started = source.drain_snapshot()
        started.update(historical_unknown_handlers=2,
            historical_source_drain_sha256=self.base.incident.old_hash,
            historical_recovery_verified=False)
        boundary = drain.begin_source_observation(self.state, self.old_source, started,
            handler_boundary=self.value(drain.HANDLER_RECOVERY_KEY))
        control = self.db.execute(
            "SELECT MAX(slot) FROM stream_receipts WHERE scope='control:solana'").fetchone()[0]
        bridge = self.native_frame(head-1, parent=control)
        bridge.update.block.parent_blockhash = self.db.execute(
            "SELECT hash FROM stream_receipts WHERE scope='control:solana' AND slot=?",
            (control,)).fetchone()[0]
        commit_control(self.state, bridge)
        commit_control(self.state, self.native_frame(head))
        addresses = {PROGRAMS[family]: program_scope(family) for family in FAMILIES}
        join = CandidateTransactionJoin(addresses, set(), filtered_from_slot=floor,
            clock=lambda: self.base.at)
        queue = CandidateCommitQueue(lambda accepted, committed:
            source.frame_census('rolling', accepted, committed))

        async def owner(fn, priority, **options):
            return fn(self.state)
        source.work = owner

        async def native(update, size, seen):
            source.handlers.phase('CANDIDATE_JOIN')
            frame = join.feed(update, size, seen)
            if frame is not None:
                source.handlers.phase('CANDIDATE_QUEUE')
                await queue.put(frame)
        native.source_session, native.source_scopes = session, SCOPES

        async def produce():
            meta = pb.SubscribeUpdate(filters=['b'])
            meta.block_meta.slot, meta.block_meta.parent_slot = head, head-1
            meta.block_meta.blockhash = session_fixture.blockhash(head)
            meta.block_meta.parent_blockhash = session_fixture.blockhash(head-1)
            meta.block_meta.block_time.timestamp = int(self.base.at)-1
            await source.handle_native(native, meta, meta.ByteSize(), self.base.at,
                'offline-buffered-native', 'pump')
            final = pb.SubscribeUpdate(filters=['f'])
            final.slot.slot, final.slot.parent = head, head-1
            final.slot.status = pb.SLOT_FINALIZED
            await source.handle_native(native, final, final.ByteSize(), self.base.at,
                'offline-buffered-native', 'pump')
            self.assertEqual((join.completed, queue.count), (head, 1))
            done = asyncio.Event()
            done.set()
            await source.candidate_commits(queue, addresses, session,
                rolling=True, priority=0, producer_done=done)
            self.assertEqual((queue.count, queue.bytes), (0, 0))
            self.assertEqual(source.drain_snapshot()['queues']['rolling'],
                dict(accepted=1, committed=1, pending=0))
            logs = ['x'*2044]
            bound = 2*len(str(logs).encode())
            with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES', bound), \
                    patch('meme_machine.solana_selective_source.MAX_PENDING_BYTES', bound):
                for slot in (head+1, head+2):
                    signature = based58.b58encode(slot.to_bytes(64, 'little')).decode()
                    self.assertIsNone(join.feed_log(slot, signature, logs, None, self.base.at))
                self.assertEqual(join.early_log_bytes, bound)
                entered = asyncio.Event()

                async def websocket_callback():
                    signature = based58.b58encode(upper.to_bytes(64, 'little')).decode()
                    number = source.handlers.accept('offline-buffered-websocket', session,
                        'websocket', 'candidate_logs', 'log_or_ack', self.base.at,
                        slot=upper, identity=signature, scopes=(program_scope('pumpswap'),))
                    try:
                        source.handlers.phase('LOG_BUFFER_WAIT')
                        entered.set()
                        await wait_candidate_log_space(join, asyncio.Event(), source.stop,
                            asyncio.Event(), upper, signature, ['held'])
                        source.handlers.phase('LOG_JOIN')
                        join.feed_log(upper, signature, ['held'], None, self.base.at)
                    except BaseException as exc:
                        source.handlers.fail(number, exc)
                        raise
                    else:
                        source.handlers.finish(number)

                task = asyncio.create_task(websocket_callback())
                await entered.wait()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertNotIn((upper, based58.b58encode(
                    upper.to_bytes(64, 'little')).decode()), join.early_logs)

        asyncio.run(produce())
        join_body = dict(plane='rolling', session=session, **join.diagnostic(),
            accepted_pending=queue.count, accepted_pending_bytes=queue.bytes, drained=False)
        source.retain_join_state('rolling', session, join_body, queue, state='CLOSED', monotonic=1.)
        source.diagnostic('native_join_closed', join_body)
        observed = dict(join_body, replay_from_slot=floor, recovery_obligations=[],
            handler_dispositions=[], complete_history_claim=False)
        gaps = []
        with self.state.writer.transaction():
            for scope in SCOPES:
                self.history.gap(scope, floor, None, 'candidate_live_disconnect_or_filter_rebuild')
                gaps.append(self.db.execute('SELECT last_insert_rowid()').fetchone()[0])
                observed['recovery_obligations'].append(
                    dict(scope=scope, lower_slot=floor, upper_slot=None))
            retained = drain.preserve_handlers(self.state, source.handlers,
                source.handlers.pending(session), dict(kind='CANDIDATE_GAPS', gap_ids=gaps[1:]))
            source.handlers.preserved(retained)
            observed['handler_dispositions'] = retained
            self.history._observation(None, 'source_session_drain', observed)
            observation = self.db.execute('SELECT last_insert_rowid()').fetchone()[0]
        # The pending diagnostic is genuinely flushed after the owner receipt,
        # just as it may be during ordinary session teardown.
        asyncio.run(source.flush_diagnostics())
        joined = self.db.execute("SELECT id,body FROM acquisition_observations "
            "WHERE kind='native_join_closed' ORDER BY id DESC LIMIT 1").fetchone()
        source.source_drain.update(state='RECOVERY_REQUIRED', terminal=True,
            terminal_at_monotonic=started['started_at_monotonic']+1,
            closed_sessions=2, preserved_partial_sessions=1, unpreserved_sessions=0)
        failed = source.drain_snapshot()
        failed.update(historical_unknown_handlers=2,
            historical_source_drain_sha256=self.base.incident.old_hash,
            historical_recovery_verified=False)
        drain.publish_source_drain(self.state, self.old_source, failed,
            handler_boundary=self.old_handler, contained_observation=True,
            observation_boundary=boundary)
        return dict(head=head, upper=upper, run=source.handlers.run, session=session,
            source=source, observation_id=observation, observed=observed, gaps=gaps,
            join_id=joined[0], join_raw=joined[1],
            failed=json.loads(self.value(drain.OBSERVATION_DRAIN_KEY)),
            failed_raw=self.value(drain.OBSERVATION_DRAIN_KEY),
            handler_raw=self.value(drain.HANDLER_RECOVERY_KEY))

    def assert_incident_preserved(self):
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY), self.incident['failed_raw'])
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY), self.incident['handler_raw'])
        self.assertEqual(self.db.execute('SELECT body FROM acquisition_observations WHERE id=?',
            (self.incident['observation_id'],)).fetchone()[0], canonical(self.incident['observed']))
        self.assert_original_evidence()

    def recover_partition(self, lower, upper):
        control = self.db.execute(
            "SELECT MAX(slot) FROM stream_receipts WHERE scope='control:solana'").fetchone()[0]
        for slot in range(control+1, upper+2):
            commit_control(self.state, self.native_frame(slot))
        proofs = {}
        for family in FAMILIES:
            identity = self.history.request(family, PROGRAMS[family], lower, upper,
                priority=0, deadline=self.base.at+120)
            job, _ = self.history.plan()
            self.assertEqual(job['id'], identity)
            self.history.commit_page(job, dict(data=[]), finalized_through=upper, seen=self.base.at)
            proofs[family] = self.db.execute('SELECT id FROM candidate_pending_proofs '
                'WHERE scope=? AND lo=? AND hi=?',
                (program_scope(family), lower, upper)).fetchone()[0]
        self.publish(tuple(proofs.values()))
        return proofs

    def test_real_committed_queue_and_interrupted_log_produce_pure_complete_bounds(self):
        before, changes = self.facts(), self.db.total_changes
        descriptor = self.descriptor()
        self.assertEqual(descriptor['input_class'], 'COMMITTED_BUFFERED_LOGS')
        self.assertEqual((descriptor['lower_slot'], descriptor['upper_slot']), (HEAD, UPPER))
        self.assertEqual((descriptor['prefix_lower_slot'], descriptor['prefix_upper_slot']),
            (FLOOR, HEAD-1))
        self.assertEqual(descriptor['accepted_pending'], 0)
        self.assertEqual((descriptor['tail_lower_slot'], descriptor['tail_upper_slot']), (None, None))
        self.assertEqual(descriptor['closed_join_observation_id'], self.incident['join_id'])
        self.assertEqual(descriptor['closed_join_sha256'],
            hashlib.sha256(self.incident['join_raw'].encode()).hexdigest())
        self.assertEqual([row['slot'] for row in descriptor['handler_records']], [UPPER])
        self.assertEqual(descriptor['native_heads']['pump']['slot'], HEAD)
        self.assertEqual(self.incident['failed']['handler_accounting']['recoverable'], 1)
        self.assertTrue(self.incident['failed']['all_accepted_committed'])
        self.assertEqual(self.db.total_changes, changes)
        self.assertEqual(self.facts(), before)
        reference = self.preserve(descriptor)
        self.refused(reference)
        self.assert_incident_preserved()

    def test_archive_full_ack_recovers_both_families_without_returning_callback(self):
        reference = self.preserve()
        _, proofs = self.recover()
        self.assertEqual(self.descriptor(), reference['descriptor'])
        result = self.verify(reference)
        self.assertEqual(result['proof_ids'], proofs)
        self.assertEqual(result['input_class'], 'COMMITTED_BUFFERED_LOGS')
        self.assertEqual(result['scope'], 'OBSERVED_BUFFERED_INTERVAL_ONLY')
        self.assertEqual(result['economic_tail_scope'], 'OBSERVED_INTERVAL_AFTER_ARCHIVE_UPPER_ONLY')
        self.assertFalse(result['full_subscription_completeness_claim'])
        self.assertEqual(result['retained_partitions'], {family: dict(
            prefix_lower_slot=FLOOR, prefix_upper_slot=HEAD-1,
            prefix_unavailable=True, prefix_missing_intervals=1,
            future_lower_slot=UPPER+1, future_upper_slot=None,
            future_open_tail=True, future_unavailable=True, future_missing_intervals=1)
            for family in FAMILIES})
        self.assertTrue(result['economic_interval_recovered'])
        self.assertTrue(result['economic_tail_continuity_verified'])
        self.assertFalse(result['callback_completion_demonstrated'])
        self.assertFalse(result['original_queue_acknowledgement_verified'])
        self.assertFalse(result['original_source_drain_pass'])
        self.assertTrue(drain.historical_observation_boundary(self.state)['session_economic_recovery_verified'])
        with closing(CandidateHistory(self.cache)) as consumer:
            self.assertEqual(consumer.db.execute('PRAGMA synchronous').fetchone()[0], 2)
            self.assertTrue(consumer.events('pump', self.base.mint))
            for proof in proofs.values():
                self.assertIsNotNone(consumer.db.execute(
                    'SELECT 1 FROM source_receipts WHERE id=?', ('coverage:'+proof,)).fetchone())
        self.assertEqual(self.db.execute('SELECT DISTINCT slot FROM candidate_blocks').fetchall(), [(HEAD,)])
        self.assert_incident_preserved()

    def test_unacknowledged_or_partially_published_archive_is_not_recovery(self):
        reference = self.preserve()
        _, proofs = self.recover(acknowledge_rows=False)
        self.refused(reference)
        # ACK genuine event rows first; that production notification makes
        # both now-unblocked proofs eligible for the next capture. Preserve
        # that actual producer snapshot before splitting its delivery, rather
        # than expecting a filtered ACK to rewind the scheduler's fair scan.
        events = capture(self.life)
        self.assertIsNotNone(events)
        self.assertTrue(events['rows'])
        rows_only = dict(events, proofs=[], publication_ids=[])
        self.assertTrue(acknowledge(self.life, rows_only, deliver(rows_only)))
        original = capture(self.life)
        self.assertIsNotNone(original)
        captured = {row['identity']: row for row in original['proofs']}
        self.assertTrue(set(proofs.values()).issubset(captured))
        batches = {family: dict(original, proofs=[captured[proof]],
            publication_ids=[proof]) for family, proof in proofs.items()}
        for family in FAMILIES:
            batch = batches[family]
            self.assertTrue(acknowledge(self.life, batch, deliver(batch)))
            self.life.publish(proof_ids=(proofs[family],))
            if family == 'pump':
                self.refused(reference)
        self.assertTrue(self.verify(reference)['economic_interval_recovered'])
        with closing(sqlite3.connect(self.cache, isolation_level=None)) as consumer:
            for family, proof in proofs.items():
                identity = 'coverage:'+proof
                self.assertIsNotNone(consumer.execute(
                    'SELECT 1 FROM source_receipts WHERE id=?', (identity,)).fetchone())
                consumer.execute('DELETE FROM source_receipts WHERE id=?', (identity,))
                try:
                    self.refused(reference)
                finally:
                    batch = batches[family]
                    self.assertTrue(acknowledge(self.life, batch, deliver(batch)))
                    self.life.publish(proof_ids=(proof,))
                self.assertTrue(self.verify(reference)['economic_interval_recovered'])
        self.assert_incident_preserved()

    def test_census_flags_queue_and_handler_authority_cannot_borrow_this_class(self):
        failed = self.incident['failed']
        for change in (dict(terminal=False), dict(all_accepted_committed=False),
                dict(unpreserved_sessions=1), dict(terminal_record_unavailable=True),
                dict(unexpected_cancellation=True)):
            with self.subTest(census=change), self.changed_owner():
                self.put(drain.OBSERVATION_DRAIN_KEY, canonical(dict(failed, **change)))
                with self.assertRaises(EvidenceUnavailable):
                    self.descriptor()
        for change in (dict(valid=False), dict(active=1), dict(failed=1),
                dict(unresolved=1), dict(recoverable=0)):
            with self.subTest(accounting=change), self.changed_owner():
                body = deepcopy(failed)
                body['handler_accounting'].update(change)
                self.put(drain.OBSERVATION_DRAIN_KEY, canonical(body))
                with self.assertRaises(EvidenceUnavailable):
                    self.descriptor()
        with self.changed_owner():
            body = deepcopy(failed)
            body['queues']['rolling'] = dict(accepted=2, committed=1, pending=1)
            self.put(drain.OBSERVATION_DRAIN_KEY, canonical(body))
            with self.assertRaises(EvidenceUnavailable):
                self.descriptor()
        for change in (dict(phase='LOG_JOIN'), dict(transport='yellowstone'),
                dict(session='a'*32), dict(slot=HEAD), dict(scope_hash='a'*64),
                dict(recovery=dict(kind='CANDIDATE_GAPS', gap_ids=self.incident['gaps']))):
            with self.subTest(handler=change), self.changed_owner():
                body = json.loads(self.incident['handler_raw'])
                for record in body['records']:
                    if record['run'] == self.incident['run']:
                        record.update(change)
                self.put(drain.HANDLER_RECOVERY_KEY, canonical(body))
                with self.assertRaises(EvidenceUnavailable):
                    self.descriptor()
        self.assert_incident_preserved()

    def test_session_closed_receipt_native_head_and_origin_ambiguity_refuse(self):
        for change in (dict(accepted_pending=1), dict(accepted_pending_bytes=1),
                dict(drained=True), dict(completed=HEAD+1), dict(session='a'*32),
                dict(handler_dispositions=[]), dict(early_log_count=0),
                dict(early_log_min_slot=HEAD), dict(complete_history_claim=True)):
            with self.subTest(session=change), self.changed_owner():
                self.db.execute('UPDATE acquisition_observations SET body=? WHERE id=?',
                    (canonical(dict(self.incident['observed'], **change)), self.incident['observation_id']))
                with self.assertRaises(EvidenceUnavailable):
                    self.descriptor()
        mutations = [
            ('DELETE FROM acquisition_observations WHERE id=?', (self.incident['join_id'],)),
            ("UPDATE acquisition_observations SET kind='other' WHERE id=?", (self.incident['join_id'],)),
            ('UPDATE candidate_blocks SET slot=slot+1 WHERE scope=?', (SCOPES[0],)),
            ('UPDATE candidate_blocks SET session=? WHERE scope=?', ('a'*32, SCOPES[1])),
            ('DELETE FROM candidate_gaps WHERE id=?', (self.incident['gaps'][0],)),
            ('UPDATE candidate_gaps SET lo=lo+1 WHERE id=?', (self.incident['gaps'][1],)),
            ("UPDATE candidate_gaps SET reason='other' WHERE id=?", (self.incident['gaps'][0],)),
        ]
        for sql, args in mutations:
            with self.subTest(mutation=sql), self.changed_owner():
                self.db.execute(sql, args)
                with self.assertRaises(EvidenceUnavailable):
                    self.descriptor()
        for kind, raw in (('source_session_drain', canonical(self.incident['observed'])),
                ('native_join_closed', self.incident['join_raw'])):
            with self.subTest(duplicate=kind), self.changed_owner():
                self.db.execute('INSERT INTO acquisition_observations(job,kind,at,body) VALUES(NULL,?,?,?)',
                    (kind, self.base.at, raw))
                with self.assertRaises(EvidenceUnavailable):
                    self.descriptor()
        self.assert_incident_preserved()

    def test_prefix_and_future_segments_need_real_gaps_or_full_published_proofs(self):
        reference = self.preserve()
        self.recover()
        self.assertTrue(self.verify(reference)['economic_interval_recovered'])
        self.assertEqual(self.descriptor(), reference['descriptor'])
        for family, scope in zip(FAMILIES, SCOPES):
            origin = reference['descriptor']['gap_origins'][family]
            for lower in (FLOOR, UPPER+1):
                with self.subTest(scope=scope, missing_segment=lower), self.changed_owner():
                    select = ('SELECT id FROM candidate_gaps WHERE scope=? AND lo=? '
                        'AND created=? AND reason=? AND id>=? AND repaired IS NULL')
                    args = (scope, lower, origin['created'], origin['reason'], origin['id'])
                    rows = self.db.execute(select, args).fetchall()
                    self.assertEqual(len(rows), 1)
                    self.db.execute('DELETE FROM candidate_gaps WHERE id=?', (rows[0][0],))
                    self.assertEqual(self.db.execute(select, args).fetchall(), [])
                    self.refused(reference)
        prefix_proofs = self.recover_partition(FLOOR, HEAD-1)
        result = self.verify(reference)
        self.assertTrue(result['economic_interval_recovered'])
        for family in FAMILIES:
            self.assertFalse(result['retained_partitions'][family]['prefix_unavailable'])
            self.assertEqual(result['retained_partitions'][family]['prefix_missing_intervals'], 0)
            self.assertTrue(result['retained_partitions'][family]['future_open_tail'])
            self.assertTrue(result['retained_partitions'][family]['future_unavailable'])
        self.assertEqual(self.descriptor(), reference['descriptor'])
        with closing(sqlite3.connect(self.cache, isolation_level=None)) as consumer:
            identity = 'coverage:'+prefix_proofs['pump']
            original = consumer.execute('SELECT * FROM source_receipts WHERE id=?', (identity,)).fetchone()
            consumer.execute('DELETE FROM source_receipts WHERE id=?', (identity,))
            try:
                self.refused(reference)
            finally:
                consumer.execute('INSERT INTO source_receipts VALUES ('+
                    ','.join('?' for _ in original)+')', original)
        self.assert_incident_preserved()

    def test_descriptor_tamper_and_failed_commit_preserve_all_state(self):
        descriptor = self.descriptor()
        for change in (dict(lower_slot=HEAD+1), dict(upper_slot=UPPER-1),
                dict(prefix_lower_slot=FLOOR+1), dict(closed_join_sha256='a'*64)):
            with self.subTest(descriptor=change):
                before = self.facts()
                with self.assertRaises(EvidenceUnavailable):
                    self.preserve(dict(descriptor, **change))
                self.assertEqual(self.facts(), before)
        before = self.facts()
        statement = self.state.writer._transaction_statement

        def fail_commit(sql, phase):
            if phase == 'commit':
                raise sqlite3.OperationalError('offline-buffered-descriptor-commit-failure')
            return statement(sql, phase)

        with patch.object(self.state.writer, '_transaction_statement', side_effect=fail_commit):
            with self.assertRaises(sqlite3.OperationalError):
                self.preserve(descriptor)
        self.assertEqual(self.facts(), before)
        reference = self.preserve(descriptor)
        self.recover()
        with self.changed_owner():
            self.db.execute('UPDATE acquisition_observations SET body=body || ? WHERE id=?',
                (' ', reference['observation_id']))
            self.refused(reference)
        self.assert_incident_preserved()

    def test_restart_and_real_handoff_preserve_failed_incident_and_finances(self):
        reference = self.preserve()
        self.recover()
        self.clean_session()
        failed_key = drain.OBSERVATION_DRAIN_KEY+'_preserved.'+reference['descriptor']['failed_census_sha256']
        ledger_key = drain.HANDLER_RECOVERY_KEY+'_preserved.'+reference['descriptor']['handler_ledger_sha256']
        self.assertEqual(self.value(failed_key), self.incident['failed_raw'])
        self.assertEqual(self.value(ledger_key), self.incident['handler_raw'])
        result = drain.historical_observation_boundary(self.state)
        self.assertEqual(result['current_observation_state'], 'DRAINED')
        with closing(sqlite3.connect(self.state.writer.path.as_uri()+'?mode=ro', uri=True)) as reader:
            reader.execute('PRAGMA query_only=ON')
            self.assertEqual(drain.historical_observation_boundary(reader), result)
        desired = [dict(family=family, scope=program_scope(family), rolling=True) for family in FAMILIES]
        preserve_subscription_handoff(self.state, desired, UPPER+8)
        result = self.verify(reference)
        self.assertTrue(result['economic_interval_recovered'])
        self.assertFalse(result['full_subscription_completeness_claim'])
        for family in FAMILIES:
            partition = result['retained_partitions'][family]
            self.assertEqual(partition['future_upper_slot'], UPPER+8)
            self.assertFalse(partition['future_open_tail'])
            self.assertTrue(partition['future_unavailable'])
            self.assertEqual(partition['future_missing_intervals'], 1)
        self.recover_partition(UPPER+1, UPPER+8)
        result = self.verify(reference)
        self.assertFalse(result['full_subscription_completeness_claim'])
        for family in FAMILIES:
            partition = result['retained_partitions'][family]
            self.assertFalse(partition['future_unavailable'])
            self.assertEqual(partition['future_missing_intervals'], 0)
            self.assertFalse(partition['future_open_tail'])
            self.assertTrue(partition['prefix_unavailable'])
        # A real subscription handoff may bound an open unavailable gap. It
        # changes no other historical identity/content and invents no coverage.
        bounded = self.db.execute(
            'SELECT * FROM candidate_gaps WHERE id IN (39592,39593) ORDER BY id').fetchall()
        for before, after in zip(self.old_gaps, bounded):
            self.assertEqual(before[:3], after[:3])
            self.assertEqual(before[4:], after[4:])
            self.assertEqual(after[3], UPPER+8 if before[3] is None else before[3])
        self.old_gaps = bounded
        self.assertEqual(self.value(failed_key), self.incident['failed_raw'])
        self.assertEqual(self.value(ledger_key), self.incident['handler_raw'])
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY), self.incident['handler_raw'])
        retained = json.loads(self.incident['handler_raw'])['records']
        self.assertEqual([row['state'] for row in retained if row['run'] == self.incident['run']], ['RECOVERABLE'])
        self.assert_original_evidence()

    def test_later_session_appends_ledger_but_revalidates_exact_archived_original(self):
        first = self.incident
        first_reference = self.preserve()
        self.recover()
        self.clean_session()
        first_ledger_key = drain.HANDLER_RECOVERY_KEY+'_preserved.'+first_reference['descriptor']['handler_ledger_sha256']
        self.assertEqual(self.value(first_ledger_key), first['handler_raw'])
        self.base.at += 10
        self.incident = self.interrupt_buffered_log(HEAD+16)
        self.assertNotEqual(self.incident['session'], first['session'])
        self.assertNotEqual(self.incident['handler_raw'], first['handler_raw'])
        second_reference = self.preserve()
        self.recover()
        self.assertTrue(self.verify(first_reference)['economic_interval_recovered'])
        self.assertTrue(self.verify(second_reference)['economic_interval_recovered'])
        result = drain.historical_observation_boundary(self.state)
        self.assertEqual(len(result['session_economic_recoveries']), 2)
        self.assertTrue(all(not row['callback_completion_demonstrated'] and
            not row['original_source_drain_pass'] for row in result['session_economic_recoveries']))
        with self.changed_owner():
            self.put(first_ledger_key, self.incident['handler_raw'])
            self.refused(first_reference)
        self.assertEqual(self.value(first_ledger_key), first['handler_raw'])
        self.clean_session()
        result = drain.historical_observation_boundary(self.state)
        with closing(sqlite3.connect(self.state.writer.path.as_uri()+'?mode=ro', uri=True)) as reader:
            reader.execute('PRAGMA query_only=ON')
            self.assertEqual(drain.historical_observation_boundary(reader), result)
        self.assert_original_evidence()


if __name__ == '__main__':
    unittest.main()
