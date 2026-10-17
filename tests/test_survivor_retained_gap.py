"""A retained Survivor prefix must not conceal a later canonical gap.

All source records/receipts and provider clocks below are synthetic and local.
The fixture uses the real candidate reader, FULL consumer publication, Survivor
history/checkpoint and reconstruction paths. It grants no funding authority.
"""
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
from meme_machine.lanes.pump.pumpswap_survivor import POLICY_HASH, STRATEGY_ID
from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime
from meme_machine.lanes.pump.solana_evidence_runtime import RuntimeEvidence
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime.directional_sleeve import policies
from meme_machine.runtime.sleeve_reservations import SleeveReservations
from meme_machine.runtime.directional_continuation import native_sync
from meme_machine.runtime.survivor_commit import restore_risk
from meme_machine.runtime.survivor_history import History
from meme_machine.runtime.survivor_paper_book import PaperBook
from meme_machine.solana_evidence_plane import (
    EvidenceReader, EvidenceUnavailable, FinalizedRecord, IntervalProof, digest,
)
from meme_machine.solana_evidence_runtime import SWAP_SCOPE
from meme_machine.solana_native_evidence import NativeFrame
from meme_machine.solana_history_delivery import capture, deliver, acknowledge
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import CandidateReader, PROGRAMS
from meme_machine.solana_selective_source import block_message, commit_control
from meme_machine.solana_evidence_transport import Subscription
from meme_machine.yellowstone import geyser_pb2 as pb
from tests.test_solana_closure import state_at
from tests.lanes.pump import test_postgrad as postgrad_fixture
from tests.shared_rally_support import observe_survivor


class SurvivorRetainedGapTests(unittest.TestCase):
    def setUp(self):
        network = patch('socket.socket.connect', side_effect=AssertionError('network_forbidden'))
        network.start()
        self.addCleanup(network.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict('os.environ', MM_SOLANA_HISTORY_SEPARATED='0',
            MM_PORTFOLIO_ACCOUNTING_DB='',
            MM_SOLANA_CANDIDATE_HISTORY_DB=str(self.root/'candidate-history.sqlite'))
        env.start()
        self.addCleanup(env.stop)
        self.now = 104
        self.path = self.root/'canonical.sqlite'
        self.state, self.canonical = state_at(self.path, lambda: self.now)
        self.addCleanup(self.state.writer.close)
        self.mint = postgrad_fixture.MINT
        self.pool = postgrad_fixture.pumpswap_pool(self.mint)
        self.scope = self.canonical.bind('pumpswap', self.pool)
        for slot in range(70, 105):
            update = pb.SubscribeUpdate()
            block = update.block
            block.slot, block.parent_slot = slot, slot-1
            block.blockhash, block.parent_blockhash = 'block-'+str(slot), 'block-'+str(slot-1)
            block.block_time.timestamp = slot
            commit_control(self.state, NativeFrame(update, update.ByteSize(), self.now))
        records = []
        for slot in (70, 75, 80, 85, 90, 95, 100):
            event = dict(pool=self.pool, mint=self.mint, wallet='buyer-'+str(slot),
                buy=True, amount=1000, tokens=10, pool_quote_reserve=100+slot,
                pool_base_reserve=1, market_time=slot, slot=slot, index=0)
            records.append(FinalizedRecord('survivor-event-'+str(slot), SWAP_SCOPE,
                slot, 'signature-'+str(slot), PROGRAMS['pumpswap'],
                (self.pool, self.mint, event['wallet']), slot, dict(event=event),
                'alchemy_finalized_stream', 'a'*64, self.now, transaction_index=0))
        self.canonical.ingest(records)
        scope = program_scope('pumpswap')
        self.canonical.lifecycle.defer_proof(IntervalProof(scope, 70, 103,
            'alchemy_finalized_stream', 'a'*64,
            dict(finalized=True, complete=True, scope=scope, lower_slot=70,
                upper_slot=103, lineage_hash=digest(['offline-prefix', scope, 70, 103])),
            self.now))
        while self.canonical.lifecycle.flush():
            pass
        self.canonical.lifecycle.publish()
        self.assertIsNone(self.canonical.lifecycle.unconsumed(scope))
        self.assertIsNone(self.state.writer.db.execute(
            'SELECT 1 FROM candidate_pending_proofs LIMIT 1').fetchone())
        self.reader = EvidenceReader(self.path)
        self.addCleanup(self.reader.close)
        self.candidate = CandidateReader(self.reader, 'pumpswap', self.pool)
        self.assertTrue(self.candidate.covered(self.scope, 70, 100, as_of=self.now))
        self.history_path = self.root/'survivor-history.sqlite'
        self.history = History(self.history_path, policy=POLICY_HASH)
        self.addCleanup(lambda: self.history.close())
        self.history.graduate(self.mint, dict(at=70, slot=70, pool=self.pool,
            mint=self.mint, quote_amount=100, mint_amount=1, identity='migration-fixture'))
        self.history.append(self.mint, through=70, events=[], points=[(70, '100')], complete=True)
        self.plane = RuntimeEvidence(self.path, owner='pump:survivor',
            clock=lambda: self.now, command=self.state.fence.command)
        self.addCleanup(self.plane.close)
        self.runtime = object.__new__(Runtime)
        self.runtime.history = self.history
        self.runtime.plane = self.plane
        self.runtime.confirmations = ConfirmationBook({}, 60)
        self.runtime.candidate_history = None
        self.runtime.now = lambda: 100
        self.runtime._increment(self.history.get(self.mint), 90, 90)
        self.assertEqual(self.history.get(self.mint)['through'], 90)
        self.assertTrue(self.history.get(self.mint)['complete'])
        # Reopen the actual FULL-synchronous history, rather than trusting an
        # in-memory complete flag supplied by the fixture.
        self.history.close()
        self.history = History(self.history_path, policy=POLICY_HASH)
        self.runtime.history = self.history

    def retained(self):
        return {table: self.history.db.execute(
            'SELECT * FROM '+table+' ORDER BY rowid').fetchall()
            for table in ('events', 'points')}

    def gap(self, lo, hi):
        self.canonical.gap(program_scope('pumpswap'), lo, hi,
            'offline_later_retained_source_gap')
        return self.state.writer.db.execute('SELECT * FROM candidate_gaps ORDER BY id').fetchall()

    def test_new_gap_in_retained_prefix_blocks_continuity_after_restart(self):
        retained = self.retained()
        gaps = self.gap(78, 82)
        self.assertFalse(self.candidate.covered(self.scope, 70, 100, as_of=self.now))
        with self.assertRaisesRegex(EvidenceUnavailable, 'unresolved_evidence_gap'):
            self.candidate.window(self.scope, 70, 100, as_of=self.now, address=self.pool)
        self.assertTrue(self.candidate.covered(self.scope, 90, 100, as_of=self.now))
        self.runtime.current = self.history.get(self.mint)
        state = dict(market_time=100, slot=100, creator='creator', available_time=100,
            state=dict(quote_reserve=200, base_reserve=1, mayhem_mode=False,
                raw_quote_reserve=200))
        try:
            facts = self.runtime.reconstruct(state, None, maintenance=True)
        except EvidenceUnavailable:
            # Rejecting the demanded historical interval is also fail-closed.
            return
        finally:
            after = self.retained()
            for table, rows in retained.items():
                self.assertTrue(all(row in after[table] for row in rows), table)
            self.assertEqual(self.state.writer.db.execute(
                'SELECT * FROM candidate_gaps ORDER BY id').fetchall(), gaps)
        self.assertFalse(facts['continuity_complete'],
            'Survivor reported complete continuity after checking only its covered '
            '90..100 delta while its retained 70..90 history overlaps gap 78..82')

    def test_gap_in_new_delta_already_blocks_actual_increment(self):
        retained = self.retained()
        gaps = self.gap(94, 96)
        self.assertFalse(self.candidate.covered(self.scope, 90, 100, as_of=self.now))
        with self.assertRaisesRegex(EvidenceUnavailable, 'unresolved_evidence_gap'):
            self.runtime._increment(self.history.get(self.mint), 100, 100)
        self.assertEqual(self.retained(), retained)
        self.assertEqual(self.history.get(self.mint)['through'], 90)
        self.assertEqual(self.state.writer.db.execute(
            'SELECT * FROM candidate_gaps ORDER BY id').fetchall(), gaps)

    def test_same_saved_checkpoint_revalidates_prefix_before_any_ack(self):
        retained = self.retained()
        row = self.history.get(self.mint)
        gaps = self.gap(78, 82)
        with patch.object(self.plane, '_command', wraps=self.plane._command) as command:
            with self.assertRaisesRegex(EvidenceUnavailable, 'unresolved_evidence_gap'):
                self.runtime._increment(row, 90, 90)
            command.assert_not_called()
        self.assertEqual(self.history.get(self.mint), row)
        self.assertEqual(self.retained(), retained)
        self.assertEqual(self.state.writer.db.execute(
            'SELECT * FROM candidate_gaps ORDER BY id').fetchall(), gaps)

    def test_independent_candidate_proof_full_consumer_ack_restores_exact_interval(self):
        gaps = self.gap(78, 82)
        self.assertFalse(self.candidate.covered(self.scope, 70, 100, as_of=self.now))
        life = self.canonical.lifecycle
        life.delivery_separated = True
        witness = dict(finalized=True, complete=True, scope=self.scope,
            lower_slot=78, upper_slot=82, lineage_hash=digest(['offline-independent', self.scope, 78, 82]))
        proof_id = digest([self.scope, 78, 82, witness])
        life.defer_proof(IntervalProof(self.scope, 78, 82, 'alchemy_finalized_repair',
            'a'*64, witness, self.now))
        snapshot = capture(life)
        self.assertIsNotNone(snapshot)
        result = deliver(snapshot)
        self.assertFalse(self.candidate.covered(self.scope, 70, 100, as_of=self.now))
        acknowledge(life, snapshot, result)
        self.assertFalse(self.candidate.covered(self.scope, 70, 100, as_of=self.now))
        life.publish(proof_ids=[proof_id])
        with closing(CandidateHistory(life.path)) as shared:
            self.assertEqual(shared.db.execute('PRAGMA synchronous').fetchone()[0], 2)
            receipt = shared.db.execute('SELECT body,hash FROM source_receipts WHERE id=?',
                ('coverage:'+proof_id,)).fetchone()
            self.assertIsNotNone(receipt)
            import hashlib
            self.assertEqual(hashlib.sha256(receipt[0].encode()).hexdigest(), receipt[1])
        self.assertIsNone(self.state.writer.db.execute(
            'SELECT 1 FROM candidate_pending_proofs WHERE id=?', (proof_id,)).fetchone())
        self.assertTrue(self.candidate.covered(self.scope, 70, 100, as_of=self.now))
        self.runtime._increment(self.history.get(self.mint), 100, 100)
        self.assertEqual(self.history.get(self.mint)['through'], 100)
        self.assertTrue(self.history.get(self.mint)['complete'])
        # Genuine independent candidate coverage does not relabel the source's
        # original program-wide outage or claim that every pool recovered.
        self.assertEqual(self.state.writer.db.execute(
            'SELECT * FROM candidate_gaps ORDER BY id').fetchall(), gaps)

    def test_unrelated_gap_does_not_block_a_complete_required_window(self):
        gaps = self.gap(60, 65)
        self.assertTrue(self.candidate.covered(self.scope, 70, 100, as_of=self.now))
        self.runtime._increment(self.history.get(self.mint), 100, 100)
        self.assertEqual(self.history.get(self.mint)['through'], 100)
        self.assertEqual(self.state.writer.db.execute(
            'SELECT * FROM candidate_gaps ORDER BY id').fetchall(), gaps)

    def test_compacted_history_uses_retained_graduation_slot_after_old_receipts_retire(self):
        from meme_machine.lanes.pump.pumpswap_survivor import reduce_reset_history
        from meme_machine.runtime.survivor_history import compact_restored_history
        self.now = 90002
        for slot, market_time in ((105, 90000), (106, 90001), (107, 90002)):
            update = pb.SubscribeUpdate()
            block = update.block
            block.slot, block.parent_slot = slot, slot-1
            block.blockhash, block.parent_blockhash = 'block-'+str(slot), 'block-'+str(slot-1)
            block.block_time.timestamp = market_time
            frame = NativeFrame(update, update.ByteSize(), self.now)
            commit_control(self.state, frame)
            # The real linked-child producer also establishes the global
            # source frontier required by the unchanged consumer ACK fence.
            self.state.fence.block(Subscription('offline', SWAP_SCOPE,
                PROGRAMS['pumpswap'], 'census', 4), block_message(frame), self.now)
        scope = program_scope('pumpswap')
        self.canonical.lifecycle.defer_proof(IntervalProof(scope, 104, 106,
            'alchemy_finalized_stream', 'a'*64,
            dict(finalized=True, complete=True, scope=scope, lower_slot=104,
                upper_slot=106, lineage_hash=digest(['offline-later', scope, 104, 106])), self.now))
        while self.canonical.lifecycle.flush():
            pass
        self.canonical.lifecycle.publish()
        self.runtime._increment(self.history.get(self.mint), 90000, 105)
        self.history.close()
        self.history = History(self.history_path, policy=POLICY_HASH)
        self.runtime.history = self.history
        old_points = self.history.db.execute('SELECT count(*) FROM points').fetchone()[0]
        compact_restored_history(self.history, lane='pump', reducer=reduce_reset_history)
        self.assertIsNotNone(self.history.get_meta('archive_prefix:'+self.mint))
        self.assertLess(self.history.db.execute('SELECT count(*) FROM points').fetchone()[0], old_points)
        coverage = self.state.writer.db.execute(
            'SELECT * FROM candidate_coverage ORDER BY scope,lo').fetchall()
        # Model normal retirement of only disposable old CONTROL time locators.
        # The canonical candidate proofs and authenticated graduation slot stay.
        with self.state.writer.transaction():
            self.state.writer.db.execute(
                "DELETE FROM stream_receipts WHERE scope='control:solana' AND slot<90")
        self.assertTrue(self.candidate.covered(self.scope, 70, 106, as_of=self.now))
        self.runtime._increment(self.history.get(self.mint), 90001, 106)
        self.assertEqual(self.history.get(self.mint)['through'], 90001)
        self.assertTrue(self.history.get(self.mint)['complete'])
        self.assertEqual(self.state.writer.db.execute(
            'SELECT * FROM candidate_coverage ORDER BY scope,lo').fetchall(), coverage)

    def held(self):
        runtime = self.runtime
        capital, basis, quantity = 1_000_000_000, 200_000_000, 1_000_000_000_000
        sleeve = SleeveReservations(self.root/'sleeve.sqlite', lane='pump', capital=capital,
            policies=policies('pump'), cohort='offline-retained-gap')
        self.addCleanup(sleeve.close)
        book = PaperBook(self.root/'paper.sqlite', run_id='gap', lane=STRATEGY_ID,
            policy_hash=POLICY_HASH, initial=capital)
        self.addCleanup(lambda: runtime.book.close())
        observed = observe_survivor(sleeve, STRATEGY_ID, self.mint, 90)
        identity = 'gap:one'
        sleeve.reserve(identity, strategy=STRATEGY_ID, amount=basis, at=90,
            candidate=self.mint, generation=observed['generation'], regime=observed['regime'])
        book.reserve(identity, basis, 90, dict(candidate=self.mint, synthetic_offline_fixture=True))
        with sleeve.commit_fence(identity):
            book.transition(identity, 'filled', 90, amount=basis, tokens=quantity,
                evidence=dict(synthetic_offline_fixture=True))
        native_sync(book, sleeve, identity)
        row = self.history.get(self.mint)
        row.update(position=identity, state='filled', generation=observed['generation'],
            regime=observed['regime'])
        self.history.save(row)
        runtime.book, runtime.sleeve = book, sleeve
        self.held_at = 100
        self.held_quote = 50_000_000_000
        runtime.now = lambda: self.held_at
        runtime._provider = lambda priority: None
        def fresh_state(candidate, **kwargs):
            self.assertEqual(candidate, self.mint)
            return postgrad_fixture.pumpswap_snapshot(kind='real', now=self.held_at,
                slot=self.held_at, quote=self.held_quote)
        runtime.fresh_state = fresh_state
        return identity

    def test_executable_hard_stop_survives_invalid_qualification_prefix(self):
        identity = self.held()
        retained = self.retained()
        gaps = self.gap(78, 82)
        with patch('meme_machine.lanes.pump.pumpswap_survivor_runtime.scale',
                side_effect=AssertionError('incomplete_history_cannot_scale')):
            self.runtime._position(self.history.get(self.mint))
        self.assertEqual(self.runtime.book._load(identity)['status'], 'settled')
        self.assertEqual(restore_risk(self.runtime.book, identity)['last_action']['reason'], 'hard_stop')
        self.assertTrue(self.runtime.book.replay()['verified'])
        self.assertEqual(self.runtime.sleeve.reconcile()['reserved'], 0)
        safety = self.history.get(self.mint)['position_safety']
        self.assertFalse(safety['evidence_current'])
        self.assertTrue(safety['exit_quote_available'])
        self.assertEqual(self.retained(), retained)
        self.assertEqual(self.state.writer.db.execute(
            'SELECT * FROM candidate_gaps ORDER BY id').fetchall(), gaps)

    def test_pending_hard_stop_reopens_then_settles_on_rebound_with_same_gap(self):
        identity = self.held()
        gaps = self.gap(78, 82)
        actual_quote = self.runtime.exit_quote
        def valuation_only(quantity, *, state=None):
            return None if state is None else actual_quote(quantity, state=state)
        with patch.object(self.runtime, 'exit_quote', side_effect=valuation_only):
            self.runtime._position(self.history.get(self.mint))
        self.assertEqual(self.runtime.book._load(identity)['status'], 'open')
        self.assertEqual(restore_risk(self.runtime.book, identity)['last_action'],
            dict(action='full_exit', reason='hard_stop'))
        self.assertTrue(self.history.get(self.mint)['position_safety']['pending_exit'])
        self.runtime.book.close()
        self.runtime.book = PaperBook(self.root/'paper.sqlite', run_id='gap', lane=STRATEGY_ID,
            policy_hash=POLICY_HASH, initial=1_000_000_000)
        self.held_at, self.held_quote = 101, 200_000_000_000
        with patch('meme_machine.lanes.pump.pumpswap_survivor_runtime.scale',
                side_effect=AssertionError('pending_exit_cannot_scale')):
            self.runtime._position(self.history.get(self.mint))
        self.assertEqual(self.runtime.book._load(identity)['status'], 'settled')
        self.assertEqual(restore_risk(self.runtime.book, identity)['last_action']['reason'], 'hard_stop')
        self.assertTrue(self.runtime.book.replay()['verified'])
        self.assertEqual(self.state.writer.db.execute(
            'SELECT * FROM candidate_gaps ORDER BY id').fetchall(), gaps)
