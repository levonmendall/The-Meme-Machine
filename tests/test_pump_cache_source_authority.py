"""A durable Pump cache retains current canonical and source-receipt authority.

All stores are disposable. Native frames and the real separated consumer create
the positive witnesses; corruptions below change only those disposable copies.
No provider, historical recovery or sustained-operation claim is made here.
"""
from contextlib import closing
import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.lanes.pump import solana_evidence_runtime as lane_runtime
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.solana_evidence_plane import EvidenceReader, EvidenceUnavailable, EvidenceWriter
from meme_machine.solana_evidence_service import FinalizedFence, program_decoders
from meme_machine.solana_evidence_transport import Subscription
from meme_machine.solana_history_delivery import capture, deliver, acknowledge, generation
from meme_machine.solana_program_decoders import pump_events
from meme_machine.solana_provider_config import AlchemyEndpoint
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import CandidateReader, PROGRAMS
from meme_machine.solana_selective_source import SelectiveSource, commit_candidate_batch, commit_control
from tests.test_candidate_commit_batches import frame
from tests.test_solana_closure import state_at
from tests.test_solana_selective_evidence import FIXTURE


class PumpCacheSourceAuthorityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache_path = self.root / 'candidate-history.sqlite'
        self.endpoint = AlchemyEndpoint.parse(
            'https://solana-mainnet.g.alchemy.com/v2/offline-cache-fixture')
        self.enterContext(patch.dict(os.environ, dict(
            MM_SOLANA_CANDIDATE_HISTORY_DB=str(self.cache_path),
            MM_SOLANA_READ_RPC_URL=self.endpoint.http_url,
            MM_SOLANA_HISTORY_SEPARATED='1')))
        creation = next(event for event in pump_events(FIXTURE['pump'][0])
            if event['event_type'] == 'create')
        self.mint = creation['mint']
        self.trade_tx = next(tx for tx in FIXTURE['pump']
            if any(event['event_type'] == 'trade' and event['mint'] == self.mint
                for event in pump_events(tx)))
        self.at = max(event['market_time'] for event in pump_events(self.trade_tx)
            if event['event_type'] == 'trade' and event['mint'] == self.mint)
        self.creation_at = creation['market_time']
        self.scope = lane_runtime.PUMP_SCOPE
        self.seen = self.at + 2

    def native_frame(self, slot, at, transaction=None):
        value = replace(frame(slot, logs=transaction is not None), seen=self.seen)
        value.update.block.block_time.timestamp = int(at)
        if transaction is not None:
            tx = copy.deepcopy(transaction)
            signature = value.log_transactions[0]['transaction']['signatures'][0]
            tx.update(slot=slot, blockTime=int(at), transactionIndex=0)
            tx['transaction']['signatures'] = [signature]
            value = replace(value, log_transactions=(tx,), candidate_statuses=(
                (signature, 0, (program_scope('pump'),), None, self.seen),))
        return value

    def selective_fixture(self,canonical_path=None):
        state, history = state_at(canonical_path or self.root / 'canonical.sqlite', lambda: self.seen)
        self.addCleanup(state.writer.close)
        state.fence.endpoint_identity = history.endpoint_identity = self.endpoint.identity
        history.lifecycle.delivery_separated = True
        history.startup.begin()
        values = [self.native_frame(100, self.at - 60),
            self.native_frame(101, self.creation_at, FIXTURE['pump'][0]),
            self.native_frame(102, self.at, self.trade_tx),
            self.native_frame(103, self.at + 1)]
        commit_candidate_batch(state, values,
            {PROGRAMS['pump']: program_scope('pump')}, 'offline-cache-session', publish=False)
        for value in values:
            commit_control(state, value)
        life = history.lifecycle
        first = capture(life)
        self.assertTrue(first['rows'])
        self.assertTrue(acknowledge(life, first, deliver(first)))
        proofs = capture(life)
        self.assertTrue(proofs['proofs'])
        self.assertTrue(acknowledge(life, proofs, deliver(proofs)))
        life.publish(proof_ids=tuple(proofs['publication_ids']))
        self.assertIsNone(life.unconsumed(program_scope('pump'), through=102))
        self.assertEqual(history.rolling.missing('pump', history.scope_for('pump', self.mint),
            100, 102, as_of=self.seen), [])
        # A real contained-session marker activates strict current generation
        # matching. Its disposable presence grants no native recovery authority.
        source = SelectiveSource(SimpleNamespace(credential='offline',
            identity=self.endpoint.identity), None)
        state.fence.health('source_drain_observation', source.drain_snapshot())
        original = EvidenceReader(state.writer.path)
        self.addCleanup(original.close)
        candidate = CandidateReader(original, 'pump', self.mint)
        self.assertTrue(candidate.covered(candidate.scope, 100, 102, as_of=self.seen))
        plane = lane_runtime.RuntimeEvidence(state.writer.path, owner='offline-pump-cache',
            clock=lambda: self.seen, command=lambda _request: None)
        self.addCleanup(plane.close)
        actual_events = plane.pump_events
        actual = actual_events(self.scope, self.mint, self.at - 60, self.at, upper_slot=102)
        self.assertTrue(any(event.get('event_type') == 'trade' for event in actual))
        # The preserved lane namespace has its own error class. Translate only
        # that outer facade. Inject a refusal only AFTER a successful genuine
        # canonical read; all health, bounds, coverage and payload reads still
        # run. CandidateHistory's canonical references stay intact throughout.
        def events(*args, **kwargs):
            try:
                actual_events(*args, **kwargs)
            except EvidenceUnavailable as error:
                raise lane_runtime.EvidenceUnavailable(str(error)) from error
            raise lane_runtime.EvidenceUnavailable('offline_controlled_cache_read_refusal')
        plane.pump_events = events
        with self.assertRaisesRegex(lane_runtime.EvidenceUnavailable,
                'offline_controlled_cache_read_refusal'):
            plane.pump_events(self.scope, self.mint, self.at - 60, self.at, upper_slot=102)
        authority = dict(candidate_scope=candidate.scope, program_scope=program_scope('pump'),
            endpoint=self.endpoint.identity, generation=generation(life))
        with closing(CandidateHistory(self.cache_path, clock=lambda: self.seen)) as cache:
            expected = cache.covered_events('pump', self.mint, self.scope,
                self.at - 60, self.at, upper_slot=102, source_authority=authority)
            self.assertTrue(any(event.get('event_type') == 'trade' for event in expected))
        return state, history, plane, expected

    def window(self, plane):
        return lane_runtime.LocalPumpTape(plane).window(self.mint, self.at, max_slot=102)

    def test_real_separated_delivery_ack_publication_allows_current_cache_fallback(self):
        state, history, plane, expected = self.selective_fixture()
        before = state.writer.db.total_changes
        self.assertEqual(self.window(plane),
            [event for event in expected if event.get('event_type') not in ('create', 'migration')])
        self.assertEqual(state.writer.db.total_changes, before)
        self.assertFalse(plane.reader.db.in_transaction)
        self.assertIsNone(history.lifecycle.unconsumed(program_scope('pump'), through=102))

    def test_missing_malformed_and_hash_tampered_source_receipts_fail_closed(self):
        _state, _history, plane, _expected = self.selective_fixture()
        with closing(CandidateHistory(self.cache_path, clock=lambda: self.seen)) as cache:
            original = cache.db.execute("SELECT * FROM source_receipts "
                "WHERE kind='coverage' ORDER BY id LIMIT 1").fetchone()
            identity, raw, checksum = original[0], original[5], original[6]
            for corruption in ('missing', 'malformed', 'hash_tampered'):
                with self.subTest(corruption=corruption):
                    if corruption == 'missing':
                        cache.db.execute('DELETE FROM source_receipts WHERE id=?', (identity,))
                    else:
                        body = '{' if corruption == 'malformed' else raw + ' '
                        stored_hash = hashlib.sha256(body.encode()).hexdigest() if corruption == 'malformed' else checksum
                        cache.db.execute('UPDATE source_receipts SET body=?,hash=? WHERE id=?',
                            (body, stored_hash, identity))
                    with self.assertRaises(lane_runtime.EvidenceUnavailable):
                        self.window(plane)
                    self.assertFalse(plane.reader.db.in_transaction)
                    if corruption == 'missing':
                        # Restore the exact genuine row between independent
                        # corruptions; no replacement proof is invented.
                        cache.db.execute("INSERT INTO source_receipts VALUES(?,?,?,?,?,?,?)",
                            original)
                    else:
                        cache.db.execute('UPDATE source_receipts SET body=?,hash=? WHERE id=?',
                            (raw, checksum, identity))

    def test_self_consistent_receipts_cannot_change_scope_endpoint_family_or_generation(self):
        _state, _history, plane, _expected = self.selective_fixture()
        with closing(CandidateHistory(self.cache_path, clock=lambda: self.seen)) as cache:
            identity, raw, checksum = cache.db.execute("SELECT id,body,hash FROM source_receipts "
                "WHERE kind='coverage' ORDER BY id LIMIT 1").fetchone()
            for field, value in (('scope', 'candidate:pump:another-market'),
                    ('endpoint', 'b' * 64), ('family', 'pumpswap'),
                    ('generation', [['different-current-session'], self.endpoint.identity, 0, 0])):
                with self.subTest(field=field):
                    wrong = dict(json.loads(raw), **{field: value})
                    altered = json.dumps(wrong, sort_keys=True, separators=(',', ':'))
                    cache.db.execute('UPDATE source_receipts SET body=?,hash=? WHERE id=?',
                        (altered, hashlib.sha256(altered.encode()).hexdigest(), identity))
                    with self.assertRaisesRegex(lane_runtime.EvidenceUnavailable,
                            'candidate_history_source_'):
                        self.window(plane)
                    cache.db.execute('UPDATE source_receipts SET body=?,hash=? WHERE id=?',
                        (raw, checksum, identity))

    def test_hash_valid_receipt_with_changed_witness_cannot_reuse_original_identity(self):
        _state, _history, plane, _expected = self.selective_fixture()
        with closing(CandidateHistory(self.cache_path, clock=lambda: self.seen)) as cache:
            identity, raw = cache.db.execute("SELECT id,body FROM source_receipts "
                "WHERE kind='coverage' ORDER BY id LIMIT 1").fetchone()
            wrong = json.loads(raw)
            wrong['witness']['lineage_hash'] = 'b' * 64
            altered = json.dumps(wrong, sort_keys=True, separators=(',', ':'))
            cache.db.execute('UPDATE source_receipts SET body=?,hash=? WHERE id=?',
                (altered, hashlib.sha256(altered.encode()).hexdigest(), identity))
        with self.assertRaisesRegex(lane_runtime.EvidenceUnavailable,
                'candidate_history_source_proof_mismatch'):
            self.window(plane)

    def test_actual_failed_health_cannot_be_overridden_by_valid_cache(self):
        state, _history, plane, _expected = self.selective_fixture()
        state.fence.health('phase', 'FAILED')
        self.assertFalse(plane.health(self.scope)['usable'])
        with self.assertRaisesRegex(lane_runtime.EvidenceUnavailable, 'evidence_service_unavailable'):
            self.window(plane)

    def test_new_current_canonical_gap_invalidates_previously_durable_cache(self):
        _state, history, plane, _expected = self.selective_fixture()
        history.gap(program_scope('pump'), 102, 102, 'offline_new_current_gap')
        candidate = CandidateReader(plane.reader.original, 'pump', self.mint)
        self.assertFalse(candidate.covered(candidate.scope, 100, 102, as_of=self.seen))
        with self.assertRaisesRegex(lane_runtime.EvidenceUnavailable, 'unresolved_evidence_gap'):
            self.window(plane)

    def test_canonical_read_transaction_spans_cache_consumption_and_is_released(self):
        state, _history, plane, _expected = self.selective_fixture()
        actual = CandidateHistory.covered_events
        calls = []
        def read(cache, *args, **kwargs):
            canonical = plane.reader.original.db
            self.assertTrue(canonical.in_transaction)
            # The writer may commit a later gap in WAL while this decision's
            # original canonical snapshot stays fixed through cache consumption.
            before = canonical.execute('SELECT COUNT(*) FROM candidate_gaps').fetchone()
            state.selective.gap(program_scope('pump'), 102, 102, 'offline_concurrent_gap')
            self.assertEqual(canonical.execute('SELECT COUNT(*) FROM candidate_gaps').fetchone(), before)
            calls.append(kwargs['source_authority'])
            return actual(cache, *args, **kwargs)
        with patch.object(CandidateHistory, 'covered_events', read):
            self.assertTrue(self.window(plane))
        self.assertEqual(len(calls), 1)
        self.assertFalse(plane.reader.db.in_transaction)
        # A later decision must observe the newly committed gap.
        with self.assertRaisesRegex(lane_runtime.EvidenceUnavailable, 'unresolved_evidence_gap'):
            self.window(plane)

    def test_real_legacy_fence_consumer_cache_remains_usable_without_selective_receipts(self):
        tx = copy.deepcopy(self.trade_tx)
        slot, now = tx['slot'], tx['blockTime']
        seen = now + 2
        writer = EvidenceWriter(self.root / 'legacy.sqlite', clock=lambda: seen)
        self.addCleanup(writer.close)
        fence = FinalizedFence(writer, endpoint_identity=self.endpoint.identity, decoders=program_decoders())
        sub = Subscription('offline-legacy-source', self.scope, PROGRAMS['pump'], 'census', 4)
        for current, at, transactions in ((slot - 1, now - 60, []),
                (slot, now, [tx]), (slot + 1, now + 1, [])):
            fence.block(sub, dict(params=dict(result=dict(value=dict(slot=current, err=None,
                block=dict(parentSlot=current - 1, blockhash=str(current),
                    previousBlockhash=str(current - 1), blockTime=at,
                    transactions=transactions))))), seen, include_logs=True)
        fence.health('phase', 'ACTIVE')
        fence.health('heartbeat', seen)
        original = EvidenceReader(writer.path)
        self.addCleanup(original.close)
        acknowledgements = []
        plane = SimpleNamespace(reader=original, clock=lambda: seen, frontier=lambda _scope: slot,
            owner='offline-legacy-pump', command=lambda **request: acknowledgements.append(request))
        events, _ = lane_runtime.LocalPumpTape(plane).events_since(0)
        self.assertTrue(events)
        self.assertEqual(acknowledgements, [dict(op='ack', owner=plane.owner, scope=self.scope, slot=slot)])
        with closing(CandidateHistory(self.cache_path, clock=lambda: seen)) as cache:
            self.assertIsNone(cache.db.execute("SELECT 1 FROM sqlite_master WHERE name='source_receipts'").fetchone())
            expected = cache.covered_events('pump', self.mint, self.scope,
                now - 60, now, upper_slot=slot)
        # The real canonical view requires offline restoration once hot bodies
        # are unavailable; its gap-free interval still permits the durable cache.
        writer.db.execute('UPDATE records SET body=NULL,archive=NULL')
        view = lane_runtime.PumpEvidenceView(original, self.scope)
        def events(requested_scope, mint, lower_time, upper_time, *, upper_slot):
            lower, upper = lane_runtime.BaseRuntimeEvidence.bounds(plane, requested_scope,
                lower_time, upper_time, upper_slot=upper_slot)
            try:
                return view.events(mint, lower_slot=lower, upper_slot=upper,
                    lower_time=lower_time, upper_time=upper_time, as_of=seen)
            except EvidenceUnavailable as error:
                raise lane_runtime.EvidenceUnavailable(str(error)) from error
        plane.pump_events = events
        self.assertEqual(lane_runtime.LocalPumpTape(plane).window(self.mint, now, max_slot=slot),
            [event for event in expected if event.get('event_type') not in ('create', 'migration')])
        self.assertFalse(original.db.in_transaction)


if __name__ == '__main__':
    unittest.main()
