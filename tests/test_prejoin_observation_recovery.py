"""Exact pre-join containment preserves the failed census and callback.

Disposable canonical state composes the original incident fixtures with genuine
archive-page producers, FULL consumer receipts and ACKs. Production pins are
asserted before substituting only this fixture's raw hashes and native heads.
No fixture result proves disposition of a production callback.
"""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import sqlite3
import unittest
from unittest.mock import patch

from meme_machine import solana_source_drain as drain
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import commit_candidate_batch, commit_control
from tests import test_session_economic_recovery as session_fixture


FAMILIES = ('pump', 'pumpswap')
LOWER, HEAD, EARLY, UPPER = 457897559, 457898776, 457898777, 457898887
SESSION = 'ebecc1ae6ab740f79d686d6a16d60360'
SESSION_AT = 1792210462.9994469
ORIGINS = {'pump': (40641, 1792210462.8379683),
           'pumpswap': (40642, 1792210462.9979148)}
PRODUCTION_PINS = dict(
    PREJOIN_OBSERVATION_SHA256='cb34e4084a55d9bd1cd700919f70b30649b21b75b205a00401226adf2a7dca1d',
    PREJOIN_HANDLER_SHA256='3d49d46228d8b2448eed3cbdff75faabfdf33e73a4acb218c0c0dd5a4c867016',
    PREJOIN_SESSION_SHA256='58e02ef83e3e135ca38a0ed302e117633f917448b2d831c412632d4bf03bea0e')


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def checksum(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class PrejoinObservationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.production_pins = {key: getattr(drain, key) for key in PRODUCTION_PINS}
        self.production_heads = deepcopy(drain.PREJOIN_NATIVE_HEADS)
        # Composition avoids discovering the imported fixture's test methods.
        self.prior = session_fixture.SessionEconomicRecoveryTests('runTest')
        self.prior.setUp()
        self.addCleanup(self.prior.doCleanups)
        self.state, self.history, self.db = self.prior.state, self.prior.history, self.prior.db
        self.life, self.cache = self.prior.life, self.prior.cache
        self.reference = self.prior.preserve()
        self.prior.recover()
        self.prior.clean_session()
        self.prior.base.at = 1792210456.0801315
        control = self.db.execute("SELECT MAX(slot) FROM stream_receipts WHERE scope='control:solana'").fetchone()[0]
        bridge = self.prior.native_frame(HEAD-1, parent=control)
        bridge.update.block.parent_blockhash = self.db.execute(
            "SELECT hash FROM stream_receipts WHERE scope='control:solana' AND slot=?", (control,)).fetchone()[0]
        commit_control(self.state, bridge)
        commit_control(self.state, self.prior.native_frame(HEAD))
        commit_candidate_batch(self.state, [self.prior.native_frame(HEAD)],
            {PROGRAMS[family]: program_scope(family) for family in FAMILIES}, SESSION, publish=False)
        fields = ('scope', 'slot', 'parent', 'hash', 'previous_hash', 'market_time', 'seen', 'session', 'census_hash')
        self.heads = {family: dict(zip(fields, self.db.execute(
            'SELECT scope,slot,parent,hash,previous_hash,market_time,seen,session,census_hash '
            'FROM candidate_blocks WHERE scope=?', (program_scope(family),)).fetchone()))
            for family in FAMILIES}
        self.record = dict(id=403802, run='b'*32, source_pid=181456,
            native_thread_id=181456, stream='offline-prejoin-rolling', session=SESSION,
            transport='websocket', family='candidate_logs', kind='log_or_ack',
            slot=UPPER, identity='offline-prejoin-log', seen=SESSION_AT-.2,
            started_monotonic=110.0, phase='LOG_BUFFER_WAIT', state='RECOVERABLE',
            failure_state='INTERRUPTED', error_type='CancelledError', scope_count=1,
            scope_hash=drain.HandlerLedger.scope_hash((program_scope('pumpswap'),)),
            recovery=dict(kind='CANDIDATE_GAPS', gap_ids=[40642]))
        old = json.loads(self.value(drain.HANDLER_RECOVERY_KEY))['records']
        self.handler_raw = encode(dict(version=1, records=old+[self.record]))
        self.failed = self.prior.base.incident.marker(state='RECOVERY_REQUIRED',
            run_identity=self.record['run'], source_pid=self.record['source_pid'],
            accepted_handlers=403936, settled_handlers=403935, pending_handlers=1,
            closed_sessions=2, preserved_partial_sessions=1, unpreserved_sessions=0,
            all_accepted_committed=True, terminal_record_unavailable=True,
            unexpected_cancellation=True, queues={name:dict(accepted=count, committed=count, pending=0)
                for name,count in (('control',2521),('rolling',1218),('scout',17019),('candidate',0))})
        self.failed['handler_accounting'] = dict(version=1, valid=True,
            run=self.record['run'], pid=self.record['source_pid'], native_thread_id=181456,
            accepted=403936, returned=403935, active=0, recoverable=1,
            failed=0, unresolved=0, records=[deepcopy(self.record)])
        self.failed_raw = encode(self.failed)
        self.session = dict(plane='rolling', session=SESSION, drained=False,
            accepted_pending=0, accepted_pending_bytes=0, completed=HEAD,
            pending_slots=1, pending_bytes=11512, oldest_slot=EARLY,
            oldest_statuses=117, oldest_bodies=0, oldest_meta=False, oldest_missing_logs=0,
            early_log_count=14329, early_log_bytes=33553707,
            early_log_min_slot=EARLY, early_log_max_slot=UPPER,
            filtered_from_slot=LOWER, replay_from_slot=LOWER, replay_prefix_bytes=394582,
            handler_dispositions=[deepcopy(self.record)], complete_history_claim=False,
            recovery_obligations=[dict(scope=program_scope(family),lower_slot=LOWER,upper_slot=None)
                for family in FAMILIES])
        self.session_raw = encode(self.session)
        self.put(drain.HANDLER_RECOVERY_KEY, self.handler_raw)
        self.put(drain.OBSERVATION_DRAIN_KEY, self.failed_raw)
        self.db.execute("INSERT INTO acquisition_observations(id,job,kind,at,body) "
            "VALUES(234592,NULL,'source_session_drain',?,?)", (SESSION_AT,self.session_raw))
        self.db.executemany("INSERT INTO candidate_gaps(id,scope,lo,hi,created,repaired,reason) "
            "VALUES(?,?,?,NULL,?,NULL,'candidate_live_disconnect_or_filter_rebuild')",
            [(identity,program_scope(family),LOWER,created) for family,(identity,created) in ORIGINS.items()])
        for key,raw in (('PREJOIN_OBSERVATION_SHA256',self.failed_raw),
                ('PREJOIN_HANDLER_SHA256',self.handler_raw),('PREJOIN_SESSION_SHA256',self.session_raw)):
            self.enterContext(patch.object(drain,key,checksum(raw)))
        self.enterContext(patch.object(drain,'PREJOIN_NATIVE_HEADS',self.heads))
        self.fixed_reference = dict(observation_sha256=checksum(self.failed_raw),
            handler_sha256=checksum(self.handler_raw), session_observation_id=234592,
            session_sha256=checksum(self.session_raw))
        self.financial_before = self.prior.base.funding.facts()

    def put(self,key,raw):
        return self.prior.put(key,raw)

    def value(self,key):
        return self.prior.value(key)

    def facts(self):
        return self.prior.facts()

    def refused(self):
        before = self.facts()
        with self.assertRaises(EvidenceUnavailable):
            drain.historical_observation_boundary(self.state)
        self.assertEqual(self.facts(),before)

    def assert_preserved(self):
        self.assertEqual(self.value(drain.SOURCE_DRAIN_KEY),self.prior.old_source)
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY),self.handler_raw)
        self.assertEqual(self.prior.base.funding.facts(),self.financial_before)
        self.prior.assert_original_evidence()

    def recover_partition(self,lower,upper):
        control = self.db.execute("SELECT MAX(slot) FROM stream_receipts WHERE scope='control:solana'").fetchone()[0]
        for slot in range(control+1,upper+2):
            commit_control(self.state,self.prior.native_frame(slot))
        proofs = {}
        for family in FAMILIES:
            identity = self.history.request(family,PROGRAMS[family],lower,upper,
                priority=0,deadline=self.prior.base.at+120)
            job,_ = self.history.plan()
            self.assertEqual(job['id'],identity)
            self.history.commit_page(job,dict(data=[]),finalized_through=upper,seen=self.prior.base.at)
            row = self.db.execute('SELECT id FROM candidate_pending_proofs WHERE scope=? AND lo=? AND hi=?',
                (program_scope(family),lower,upper)).fetchone()
            self.assertIsNotNone(row)
            proofs[family] = row[0]
        self.prior.publish(tuple(proofs.values()))
        return proofs

    def begin(self):
        body = self.prior.base.incident.current(state='RUNNING')
        body.update(historical_unknown_handlers=2,
            historical_source_drain_sha256=self.prior.base.incident.old_hash,
            historical_recovery_verified=False)
        raw = drain.begin_source_observation(self.state,self.prior.old_source,body,
            handler_boundary=self.handler_raw)
        return json.loads(raw),raw

    def finish(self,body,raw):
        terminal = dict(body,state='DRAINED',terminal=True,
            terminal_at_monotonic=body['started_at_monotonic']+1)
        drain.publish_source_drain(self.state,self.prior.old_source,terminal,
            handler_boundary=self.handler_raw,contained_observation=True,observation_boundary=raw)

    def test_production_pins_and_whole_missing_partition_are_pure_and_explicit(self):
        self.assertEqual(self.production_pins,PRODUCTION_PINS)
        for family,head in self.production_heads.items():
            self.assertEqual(head['scope'],program_scope(family))
            self.assertEqual((head['slot'],head['parent']),(HEAD,HEAD-1))
            self.assertEqual(head['session'],SESSION)
            self.assertEqual(head['hash'],'7BV9uAWoc8F1bwf4a4uLHzJRD3p57ZE5M6XysTXrCsVf')
        before,changes = self.facts(),self.db.total_changes
        result = drain.historical_observation_boundary(self.state)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['current_observation_state'],'PRESERVED_PREJOIN_OBSERVATION')
        self.assertTrue(result['prejoin_observation_retained'])
        self.assertEqual(result['prejoin_unreturned_observations'],1)
        self.assertEqual(result['preserved_prejoin_observation_sha256'],checksum(self.failed_raw))
        self.assertEqual(result['preserved_prejoin_handler_sha256'],checksum(self.handler_raw))
        self.assertEqual(result['preserved_prejoin_session_sha256'],checksum(self.session_raw))
        self.assertEqual((result['prejoin_partition_lower_slot'],result['prejoin_partition_upper_slot']),(LOWER,UPPER))
        self.assertTrue(result['prejoin_partition_continuity_verified'])
        self.assertTrue(result['prejoin_unavailable'])
        self.assertFalse(result['prejoin_recovered'])
        self.assertEqual(result['prejoin_unsealed_native_slot'],HEAD)
        self.assertTrue(result['prejoin_unsealed_slot_unavailable'])
        self.assertFalse(result['prejoin_callback_completion_demonstrated'])
        self.assertFalse(result['prejoin_original_source_drain_pass'])
        self.assertTrue(result['session_economic_recovery_verified'])
        self.assertEqual(self.db.total_changes,changes)
        self.assertEqual(self.facts(),before)
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY),self.failed_raw)
        with closing(sqlite3.connect(self.state.writer.path.as_uri()+'?mode=ro',uri=True)) as reader:
            reader.execute('PRAGMA query_only=ON')
            self.assertEqual(drain.historical_observation_boundary(reader),result)
        self.assertTrue(json.loads(self.failed_raw)['terminal_record_unavailable'])
        self.assertTrue(json.loads(self.failed_raw)['unexpected_cancellation'])
        self.assert_preserved()

    def test_genuine_prefix_full_ack_preserves_unsealed_head_and_log_tail_as_missing(self):
        proofs = self.recover_partition(LOWER,HEAD-1)
        result = drain.historical_observation_boundary(self.state)
        self.assertTrue(result['eligible'])
        self.assertTrue(result['prejoin_unavailable'])
        self.assertFalse(result['prejoin_recovered'])
        self.assertTrue(result['prejoin_unsealed_slot_unavailable'])
        for family,(identity,created) in ORIGINS.items():
            self.assertIsNotNone(self.db.execute('SELECT repaired FROM candidate_gaps WHERE id=?',(identity,)).fetchone()[0])
            self.assertEqual(self.db.execute('SELECT lo,hi FROM candidate_gaps WHERE scope=? AND created=? AND repaired IS NULL',
                (program_scope(family),created)).fetchall(),[(HEAD,None)])
            self.assertIsNone(self.life.unconsumed(program_scope(family)))
        with closing(sqlite3.connect(self.cache)) as consumer:
            self.assertEqual(consumer.execute('PRAGMA synchronous').fetchone()[0],2)
            for proof in proofs.values():
                self.assertIsNotNone(consumer.execute('SELECT 1 FROM source_receipts WHERE id=?',('coverage:'+proof,)).fetchone())
        self.assert_preserved()

    def test_entire_partition_genuinely_recovered_does_not_return_historical_callback(self):
        self.recover_partition(LOWER,UPPER)
        result = drain.historical_observation_boundary(self.state)
        self.assertTrue(result['prejoin_partition_continuity_verified'])
        self.assertFalse(result['prejoin_unavailable'])
        self.assertTrue(result['prejoin_recovered'])
        self.assertFalse(result['prejoin_unsealed_slot_unavailable'])
        self.assertFalse(result['prejoin_callback_completion_demonstrated'])
        self.assertFalse(result['prejoin_original_source_drain_pass'])
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY),self.failed_raw)
        self.assert_preserved()

    def test_covered_piece_without_original_full_consumer_receipt_is_refused(self):
        proofs = self.recover_partition(LOWER,HEAD-1)
        canonical_before = self.facts()
        with closing(sqlite3.connect(self.cache,isolation_level=None)) as consumer:
            receipts_before = consumer.execute('SELECT * FROM source_receipts ORDER BY id').fetchall()
            for family,proof in proofs.items():
                with self.subTest(family=family):
                    identity = 'coverage:'+proof
                    original = consumer.execute('SELECT * FROM source_receipts WHERE id=?',(identity,)).fetchone()
                    self.assertIsNotNone(original)
                    # Commit the external fault: the verifier deliberately
                    # opens its own read-only snapshot of this consumer DB.
                    consumer.execute('DELETE FROM source_receipts WHERE id=?',(identity,))
                    self.assertFalse(consumer.in_transaction)
                    try:
                        with closing(sqlite3.connect(self.cache.as_uri()+'?mode=ro',uri=True)) as reader:
                            reader.execute('PRAGMA query_only=ON')
                            self.assertIsNone(reader.execute('SELECT 1 FROM source_receipts WHERE id=?',
                                (identity,)).fetchone())
                        self.refused()
                    finally:
                        consumer.execute('INSERT INTO source_receipts VALUES('+','.join('?' for _ in original)+')',original)
                    self.assertFalse(consumer.in_transaction)
                    self.assertEqual(consumer.execute('SELECT * FROM source_receipts WHERE id=?',
                        (identity,)).fetchone(),original)
                    self.assertEqual(consumer.execute('SELECT * FROM source_receipts ORDER BY id').fetchall(),receipts_before)
                    self.assertTrue(drain.historical_observation_boundary(self.state)['eligible'])
                    self.assertEqual(self.facts(),canonical_before)

    def test_unsealed_head_hole_changed_origin_and_checkpoint_cannot_fill_partition(self):
        self.recover_partition(LOWER,HEAD-1)
        for family,(identity,created) in ORIGINS.items():
            scope = program_scope(family)
            cases = [
                ('UPDATE candidate_gaps SET lo=? WHERE scope=? AND created=? AND repaired IS NULL',(EARLY,scope,created)),
                ('UPDATE candidate_gaps SET created=created+1 WHERE scope=? AND created=?',(scope,created)),
                ('DELETE FROM candidate_gaps WHERE id=?',(identity,)),
            ]
            for sql,args in cases:
                with self.subTest(family=family,sql=sql),self.prior.changed_owner():
                    self.db.execute(sql,args)
                    self.db.execute('INSERT OR REPLACE INTO candidate_checkpoints VALUES(?,?,?,?)',
                        (scope,UPPER,'checkpoint-is-not-a-proof',SESSION_AT))
                    self.refused()

    def test_normal_and_funding_open_contexts_remain_refused_without_mutation(self):
        before = self.facts()
        with self.assertRaises(EvidenceUnavailable):
            drain.retained_source_drain(self.state)
        self.assertEqual(drain.retained_source_drain(self.state,contained_observation=True),self.prior.old_source)
        for changes in (dict(MM_MODE='LIVE'),dict(MM_OPERATIONAL_PHASE='continuous')):
            with self.subTest(changes=changes),patch.dict('os.environ',changes):
                with self.assertRaises(EvidenceUnavailable):
                    drain.retained_source_drain(self.state,contained_observation=True)
        self.assertEqual(self.facts(),before)
        self.assert_preserved()

    def test_begin_archives_exact_bytes_and_running_refuses_until_real_current_drain(self):
        body,raw = self.begin()
        self.assertEqual(body['prejoin_observation_reference'],self.fixed_reference)
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY+'_preserved.'+checksum(self.failed_raw)),self.failed_raw)
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY+'_preserved.'+checksum(self.handler_raw)),self.handler_raw)
        self.refused()
        self.finish(body,raw)
        current = json.loads(self.value(drain.OBSERVATION_DRAIN_KEY))
        self.assertEqual(current['prejoin_observation_reference'],self.fixed_reference)
        self.assertEqual(current['state'],'DRAINED')
        advanced = UPPER+2
        commit_candidate_batch(self.state,[self.prior.native_frame(advanced)],
            {PROGRAMS[family]:program_scope(family) for family in FAMILIES},'c'*32,publish=False)
        result = drain.historical_observation_boundary(self.state)
        self.assertEqual(result['current_observation_state'],'DRAINED')
        self.assertTrue(result['prejoin_observation_retained'])
        self.assertFalse(result['prejoin_callback_completion_demonstrated'])
        self.assert_preserved()

    def test_drained_marker_cannot_erase_fixed_session_anchor_or_required_archives(self):
        body,raw = self.begin()
        self.finish(body,raw)
        for key in (drain.OBSERVATION_DRAIN_KEY+'_preserved.'+checksum(self.failed_raw),
                    drain.HANDLER_RECOVERY_KEY+'_preserved.'+checksum(self.handler_raw)):
            with self.subTest(key=key),self.prior.changed_owner():
                self.db.execute('DELETE FROM service_health WHERE key=?',(key,))
                self.refused()
        with self.prior.changed_owner():
            self.db.execute('DELETE FROM acquisition_observations WHERE id=234592')
            self.refused()
        with self.prior.changed_owner():
            marker = json.loads(self.value(drain.OBSERVATION_DRAIN_KEY))
            marker.pop('prejoin_observation_reference')
            self.put(drain.OBSERVATION_DRAIN_KEY,encode(marker))
            self.refused()

    def test_changed_raw_session_ledger_or_new_handler_has_no_silent_fallback(self):
        for key,raw in ((drain.OBSERVATION_DRAIN_KEY,self.failed_raw),
                        (drain.HANDLER_RECOVERY_KEY,self.handler_raw)):
            with self.subTest(key=key),self.prior.changed_owner():
                self.put(key,raw+' ')
                self.refused()
        with self.prior.changed_owner():
            self.db.execute('UPDATE acquisition_observations SET body=? WHERE id=234592',(self.session_raw+' ',))
            self.refused()
        with self.prior.changed_owner():
            ledger = json.loads(self.handler_raw)
            ledger['records'].append(dict(self.record,id=403803))
            self.put(drain.HANDLER_RECOVERY_KEY,encode(ledger))
            self.refused()
        body,raw = self.begin()
        failed = dict(body,state='RECOVERY_REQUIRED',terminal=True,terminal_at_monotonic=120,
            accepted_handlers=1,settled_handlers=0,pending_handlers=1)
        drain.publish_source_drain(self.state,self.prior.old_source,failed,
            handler_boundary=self.handler_raw,contained_observation=True,observation_boundary=raw)
        self.refused()

    def test_archive_collision_and_running_write_failure_roll_back_begin_atomically(self):
        key = drain.OBSERVATION_DRAIN_KEY+'_preserved.'+checksum(self.failed_raw)
        with self.prior.changed_owner():
            self.put(key,'conflicting exact-byte archive')
            before = self.facts()
            with self.assertRaises(EvidenceUnavailable):
                self.begin()
            self.assertEqual(self.facts(),before)
        before = self.facts()
        native_health = self.state.fence._health

        def fail_after_current_write(key,body):
            native_health(key,body)
            if key==drain.OBSERVATION_DRAIN_KEY:
                raise RuntimeError('fixture current publication rollback')

        with patch.object(self.state.fence,'_health',side_effect=fail_after_current_write):
            with self.assertRaisesRegex(RuntimeError,'fixture current publication rollback'):
                self.begin()
        self.assertEqual(self.facts(),before)
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY),self.failed_raw)
        self.assert_preserved()
