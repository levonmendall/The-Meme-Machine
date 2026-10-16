"""An old full-program cache cannot cover a newer gapped Pump decision window.

The first case exercises stale boundaries. The second is an independent
fail-closed regression for current legacy source coverage invalidated by a
canonical gap; it does not establish separated candidate-receipt provenance.
"""
from contextlib import closing
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.lanes.pump import solana_evidence_runtime as lane_runtime
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.solana_evidence_plane import (
    EvidenceReader, EvidenceUnavailable, EvidenceWriter, IntervalProof, digest,
)
from meme_machine.solana_evidence_queries import PumpEvidenceView
from meme_machine.solana_evidence_service import FinalizedFence, program_decoders
from meme_machine.solana_evidence_transport import Subscription
from meme_machine.solana_program_decoders import pump_events
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import CandidateReader, PROGRAMS, economic_records
from tests.test_solana_closure import state_at
from tests.test_solana_selective_evidence import FIXTURE


class StalePumpCacheBoundaryTests(unittest.TestCase):
    def test_real_partial_window_attempts_but_cannot_extend_old_full_program_cache(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        cache_path = root / 'candidate-history.sqlite'
        scope = lane_runtime.PUMP_SCOPE
        endpoint = 'a' * 64
        old_end_time = max(tx['blockTime'] for tx in FIXTURE['pump']) + 1
        old_seen = old_end_time + 1
        rows = [row for tx in FIXTURE['pump'] for row in economic_records(
            'pump', PROGRAMS['pump'], tx, endpoint_identity=endpoint,
            seen=old_seen, source='alchemy_finalized_stream')]
        latest_trade = max((row for row in rows
            if row.payload['event']['event_type'] == 'trade'),
            key=lambda row: (row.market_time, row.slot, row.event_index))
        mint = latest_trade.payload['event']['mint']
        old_lower_slot = min(row.slot for row in rows)
        old_upper_slot = max(row.slot for row in rows)
        old_start_time = min(row.market_time for row in rows) - 60
        self.assertGreater(old_upper_slot, old_lower_slot)

        # Populate genuine legacy full-program cache through the real lane
        # consumer, including its proof check, normalized commit and source ACK.
        old_writer = EvidenceWriter(root / 'old-full-source.sqlite', clock=lambda: old_seen)
        self.addCleanup(old_writer.close)
        old_writer.ingest(rows, proof=IntervalProof(scope, old_lower_slot,
            old_upper_slot, 'alchemy_finalized_stream', endpoint,
            dict(finalized=True, complete=True, scope=scope,
                lower_slot=old_lower_slot, upper_slot=old_upper_slot,
                lineage_hash=digest([scope, old_lower_slot, old_upper_slot])), old_seen))
        old_writer.db.execute('CREATE TABLE stream_receipts(scope TEXT,slot INTEGER,market_time INTEGER)')
        old_writer.db.executemany('INSERT INTO stream_receipts VALUES(?,?,?)',
            [(scope, old_lower_slot, old_start_time), (scope, old_upper_slot, old_end_time)])
        old_reader = EvidenceReader(old_writer.path)
        self.addCleanup(old_reader.close)
        acknowledgements = []
        old_plane = SimpleNamespace(reader=old_reader, clock=lambda: old_seen,
            frontier=lambda _scope: old_upper_slot, owner='offline-legacy-pump',
            command=lambda **request: acknowledgements.append(request))
        with patch.dict(os.environ, MM_SOLANA_CANDIDATE_HISTORY_DB=str(cache_path)):
            discovered, sequence = lane_runtime.LocalPumpTape(old_plane).events_since(0)
        self.assertTrue(discovered)
        self.assertGreater(sequence, 0)
        self.assertEqual(acknowledgements,
            [dict(op='ack', owner=old_plane.owner, scope=scope, slot=old_upper_slot)])

        current_time = old_end_time + 90
        current_lower_slot = old_upper_slot + 100
        current_upper_slot = current_lower_slot + 3
        with closing(CandidateHistory(cache_path, clock=lambda: current_time)) as cache:
            cached = cache.covered_events('pump', mint, scope,
                old_end_time - 60, old_end_time, upper_slot=old_upper_slot)
            self.assertTrue(cached)
            coverage_before = cache.db.execute(
                'SELECT scope,lower_slot,upper_slot,lower_time,upper_time,body,hash '
                'FROM history_coverage ORDER BY id').fetchall()
            events_before = cache.db.execute('SELECT * FROM events ORDER BY identity').fetchall()
            self.assertEqual({row[0] for row in coverage_before}, {scope})
            # Each independent boundary is actually checked by CandidateHistory.
            with self.assertRaisesRegex(ValueError, 'candidate_history_continuity_missing'):
                cache.covered_events('pump', mint, scope, old_end_time - 60,
                    old_end_time, upper_slot=current_upper_slot)
            with self.assertRaisesRegex(ValueError, 'candidate_history_continuity_missing'):
                cache.covered_events('pump', mint, scope, current_time - 60,
                    current_time, upper_slot=old_upper_slot)

        # Current canonical history contains a real branch-local partial-prefix
        # gap inside an otherwise proved interval. The reader must consult it.
        state, history = state_at(root / 'current-canonical.sqlite', lambda: current_time)
        self.addCleanup(state.writer.close)
        candidate_scope = history.bind('pump', mint)
        full_scope = program_scope('pump')
        history.lifecycle.defer_proof(IntervalProof(full_scope, current_lower_slot,
            current_upper_slot, 'alchemy_finalized_stream', endpoint,
            dict(finalized=True, complete=True, scope=full_scope,
                lower_slot=current_lower_slot, upper_slot=current_upper_slot,
                lineage_hash=digest([full_scope, current_lower_slot, current_upper_slot])), current_time))
        while history.lifecycle.flush():
            pass
        history.lifecycle.publish()
        history.gap(full_scope, current_lower_slot, current_lower_slot + 1,
            'rolling_partial_subscription_prefix')
        self.assertEqual(history.rolling.missing('pump', candidate_scope,
            current_lower_slot, current_upper_slot, as_of=current_time),
            [(current_lower_slot, current_lower_slot + 1)])
        current_reader = EvidenceReader(state.writer.path)
        self.addCleanup(current_reader.close)
        candidate = CandidateReader(current_reader, 'pump', mint)
        view = PumpEvidenceView(candidate, candidate.scope)
        with self.assertRaisesRegex(EvidenceUnavailable, 'unresolved_evidence_gap'):
            view.events(mint, lower_slot=current_lower_slot, upper_slot=current_upper_slot,
                lower_time=current_time - 60, upper_time=current_time, as_of=current_time)

        requests = []
        def current_events(requested_scope, address, lower_time, upper_time, *, upper_slot):
            requests.append((requested_scope, address, lower_time, upper_time, upper_slot))
            # Only the outer fixed-boundary facade is a double. Real candidate
            # coverage and the real view produce the refusal, not an injected error.
            try:
                return view.events(address, lower_slot=current_lower_slot,
                    upper_slot=upper_slot, lower_time=lower_time,
                    upper_time=upper_time, as_of=current_time)
            except EvidenceUnavailable as error:
                # The preserved lane module has its own imported error class.
                raise lane_runtime.EvidenceUnavailable(str(error)) from error

        fallback_calls = []
        original_covered_events = CandidateHistory.covered_events
        def record_cache_attempt(cache, *args, **kwargs):
            fallback_calls.append((args, kwargs))
            return original_covered_events(cache, *args, **kwargs)

        tape = lane_runtime.LocalPumpTape(SimpleNamespace(pump_events=current_events,
            reader=current_reader,clock=lambda:current_time))
        with patch.dict(os.environ, MM_SOLANA_CANDIDATE_HISTORY_DB=str(cache_path)), \
                patch.object(CandidateHistory, 'covered_events', record_cache_attempt):
            with self.assertRaises(lane_runtime.EvidenceUnavailable):
                tape.window(mint, current_time, max_slot=current_upper_slot)
        self.assertEqual(requests,
            [(scope, mint, current_time - 60, current_time, current_upper_slot)])
        self.assertEqual(fallback_calls, [])
        self.assertEqual(view.blocked_by_gaps, 2)
        self.assertFalse(current_reader.db.in_transaction)
        with closing(CandidateHistory(cache_path, clock=lambda: current_time)) as cache:
            self.assertEqual(cache.db.execute(
                'SELECT scope,lower_slot,upper_slot,lower_time,upper_time,body,hash '
                'FROM history_coverage ORDER BY id').fetchall(), coverage_before)
            self.assertEqual(cache.db.execute('SELECT * FROM events ORDER BY identity').fetchall(), events_before)

    def test_current_hash_valid_legacy_cache_cannot_override_same_window_canonical_gap(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        cache_path = root / 'candidate-history.sqlite'
        scope = lane_runtime.PUMP_SCOPE
        tx = copy.deepcopy(next(tx for tx in FIXTURE['pump']
            if any(event['event_type'] == 'trade' for event in pump_events(tx))))
        mint = next(event['mint'] for event in pump_events(tx) if event['event_type'] == 'trade')
        upper_slot = tx['slot']
        now = tx['blockTime']
        seen = now + 2
        writer = EvidenceWriter(root / 'current-full-source.sqlite', clock=lambda: seen)
        self.addCleanup(writer.close)
        fence = FinalizedFence(writer, endpoint_identity='a' * 64, decoders=program_decoders())
        subscription = Subscription('offline-full-source', scope, PROGRAMS['pump'], 'census', 4)
        # Real fence production creates linked receipt/coverage witnesses and
        # decodes captured logs. No cache coverage or source receipt is inserted.
        for slot, at, transactions in ((upper_slot - 1, now - 60, []),
                (upper_slot, now, [tx]), (upper_slot + 1, now + 1, [])):
            fence.block(subscription, dict(params=dict(result=dict(value=dict(
                slot=slot, err=None, block=dict(parentSlot=slot - 1,
                    blockhash='offline-block-' + str(slot),
                    previousBlockhash='offline-block-' + str(slot - 1),
                    blockTime=at, transactions=transactions))))), seen, include_logs=True)
        reader = EvidenceReader(writer.path)
        self.addCleanup(reader.close)
        self.assertTrue(reader.covered(scope, upper_slot - 1, upper_slot, as_of=seen))
        receipts_before = writer.db.execute(
            'SELECT * FROM stream_receipts WHERE scope=? ORDER BY slot', (scope,)).fetchall()
        witnesses_before = writer.db.execute(
            'SELECT lo,hi,proof FROM coverage WHERE scope=? AND available<=? ORDER BY lo,hi',
            (scope, seen)).fetchall()
        acknowledgements = []
        plane = SimpleNamespace(reader=reader, clock=lambda: seen,
            frontier=lambda _scope: upper_slot, owner='offline-current-full-source',
            command=lambda **request: acknowledgements.append(request))
        with patch.dict(os.environ, MM_SOLANA_CANDIDATE_HISTORY_DB=str(cache_path)):
            events, _ = lane_runtime.LocalPumpTape(plane).events_since(0)
        self.assertTrue(events)
        self.assertEqual(acknowledgements,
            [dict(op='ack', owner=plane.owner, scope=scope, slot=upper_slot)])
        with closing(CandidateHistory(cache_path, clock=lambda: seen)) as cache:
            cached = cache.covered_events('pump', mint, scope, now - 60, now, upper_slot=upper_slot)
            self.assertTrue(cached)
            coverage_before = cache.db.execute('SELECT body,hash FROM history_coverage ORDER BY id').fetchall()
            self.assertEqual(len(coverage_before), 1)
            raw, checksum = coverage_before[0]
            body = json.loads(raw)
            self.assertEqual(digest(body), checksum)
            from meme_machine.runtime.journal import digest as journal_digest
            self.assertEqual(body['proof_hash'], journal_digest(witnesses_before))
            self.assertEqual((body['lower_slot'], body['upper_slot'],
                body['lower_time'], body['upper_time']), (upper_slot - 1, upper_slot, now - 60, now))
            # This is genuine legacy full-program cache production plus its
            # source ACK. It is not separated candidate source_receipts/ACK proof.
            self.assertIsNone(cache.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_receipts'").fetchone())

        # A later canonical invalidation overlaps exactly the cached window;
        # neither the immutable cache body hash nor its old witness digest changes.
        writer.gap(scope, upper_slot, upper_slot, reason='offline_reorganization_after_cache_commit')
        self.assertFalse(reader.covered(scope, upper_slot - 1, upper_slot, as_of=seen))
        view = PumpEvidenceView(reader, scope)
        with self.assertRaisesRegex(EvidenceUnavailable, 'unresolved_evidence_gap'):
            view.events(mint, lower_slot=upper_slot - 1, upper_slot=upper_slot,
                lower_time=now - 60, upper_time=now, as_of=seen)
        with closing(CandidateHistory(cache_path, clock=lambda: seen)) as cache:
            self.assertEqual(cache.covered_events('pump', mint, scope,
                now - 60, now, upper_slot=upper_slot), cached)
            self.assertEqual(cache.db.execute('SELECT body,hash FROM history_coverage ORDER BY id').fetchall(), coverage_before)

        def current_events(requested_scope, address, lower_time, upper_time, *, upper_slot):
            lower, upper = lane_runtime.BaseRuntimeEvidence.bounds(plane,
                requested_scope, lower_time, upper_time, upper_slot=upper_slot)
            try:
                return view.events(address, lower_slot=lower, upper_slot=upper,
                    lower_time=lower_time, upper_time=upper_time, as_of=seen)
            except EvidenceUnavailable as error:
                raise lane_runtime.EvidenceUnavailable(str(error)) from error
        plane.pump_events = current_events
        self.assertEqual(writer.db.execute(
            'SELECT * FROM stream_receipts WHERE scope=? ORDER BY slot', (scope,)).fetchall(), receipts_before)
        self.assertEqual(writer.db.execute(
            'SELECT lo,hi,proof FROM coverage WHERE scope=? AND available<=? ORDER BY lo,hi',
            (scope, seen)).fetchall(), witnesses_before)
        # Preserve a failing safety expectation if the cache silently overrides
        # the real canonical refusal. Do not bless fallback or mark expectedFailure.
        with patch.dict(os.environ, MM_SOLANA_CANDIDATE_HISTORY_DB=str(cache_path)):
            with self.assertRaises(lane_runtime.EvidenceUnavailable):
                lane_runtime.LocalPumpTape(plane).window(mint, now, max_slot=upper_slot)


if __name__ == '__main__':
    unittest.main()
