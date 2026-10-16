"""Fresh publication retains old obligations and uses original consumer ACKs.

Disposable production-path correctness proof only; no providers, protected
state, historical handler disposition or operating-capacity claim.
"""
from contextlib import closing
import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.solana_history_delivery import capture, deliver, acknowledge
from meme_machine.solana_prewarm_startup import candidate_release, published_program_frontiers
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS, economic_records
from meme_machine.solana_selective_source import commit_candidate_batch, commit_control
from tests.test_candidate_commit_batches import frame
from tests.test_solana_closure import NOW, state_at
from tests.test_solana_selective_evidence import FIXTURE


class ProspectivePrewarmConsumptionTests(unittest.TestCase):
    def test_old_canonical_row_blocks_fresh_release_until_original_consumer_ack_and_publication(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
                os.environ, MM_SOLANA_HISTORY_SEPARATED='1'):
            path = Path(temporary) / 'canonical.sqlite'
            now = [NOW]
            state, history = state_at(path, lambda: now[0])
            try:
                life = history.lifecycle
                self.assertTrue(life.delivery_separated)
                # Use an actual decoded retained Pump event, not an invented
                # outbox row that the real external consumer cannot commit.
                records = economic_records('pump', PROGRAMS['pump'],
                    copy.deepcopy(FIXTURE['pump'][0]), endpoint_identity='a' * 64,
                    seen=now[0], source='alchemy_finalized_stream')
                old = next(row for row in records if row.kind == 'event')
                # A retained mint already has its real consumer binding. A
                # decoded trade alone does not invent a discovery/create event.
                history.bind('pump', old.payload['event']['mint'])
                history.ingest([old])
                pending = history.db.execute('''SELECT id,body,hash FROM candidate_history_outbox
                    WHERE family='pump' AND kind='canonical' AND consumed IS NULL
                    AND json_extract(body,'$.record.identity')=?''', (old.identity,)).fetchall()
                self.assertEqual(len(pending), 1)
                old_id, original_body, original_hash = pending[0]
                original_record = history.db.execute(
                    'SELECT body,hash,first_seen FROM canonical_evidence WHERE identity=?',
                    (old.identity,)).fetchone()

                lower = old.slot + 100
                for family in ('pump', 'pumpswap'):
                    history.gap(program_scope(family), old.slot - 10,
                        old.slot - 10, 'retained_disjoint_history_fixture')
                old_gaps = history.db.execute('SELECT * FROM candidate_gaps ORDER BY id').fetchall()
                now[0] += 1
                history.startup.begin()
                for family in ('pump', 'pumpswap'):
                    history.startup.feed_ack(family, lower, lower + 1)
                history.startup.native(('pump', 'pumpswap'))
                addresses = {PROGRAMS[family]: program_scope(family)
                    for family in ('pump', 'pumpswap')}

                def current_frame(slot):
                    value = replace(frame(slot, logs=False), seen=now[0])
                    value.update.block.block_time.timestamp = int(now[0])
                    return value

                commit_candidate_batch(state,
                    [current_frame(slot) for slot in range(lower, lower + 4)],
                    addresses, 'fresh-prospective-fixture', publish=False)
                for slot in range(lower, lower + 5):
                    commit_control(state, current_frame(slot))

                scope = program_scope('pump')
                self.assertLess(old.slot, lower)
                self.assertIsNotNone(life.unconsumed(scope, through=lower + 2))
                blocked = history.startup.advance()
                self.assertEqual(blocked['phase'], 'WAIT_FOR_DURABLE_PUBLICATION')
                self.assertFalse(blocked['released'])
                self.assertFalse(candidate_release(path))
                self.assertEqual(published_program_frontiers(history.db, now=now[0]), [])

                event_batch = capture(life)
                self.assertIsNotNone(event_batch)
                self.assertIn(old_id, [row[0] for row in event_batch['rows']])
                # The pending old canonical row suppresses Pump proof delivery,
                # even though this startup's native interval is much newer.
                self.assertFalse(any(row['family'] == 'pump' for row in event_batch['proofs']))
                delivered = deliver(event_batch)
                with closing(sqlite3.connect(life.path)) as consumer:
                    receipt = consumer.execute('SELECT body,hash FROM source_receipts WHERE id=?',
                        (old_id,)).fetchone()
                self.assertIsNotNone(receipt)
                self.assertEqual(json.loads(receipt[0])['canonical_identity'], old.identity)
                # External durability alone does not consume the owner queue.
                self.assertEqual(history.db.execute('SELECT body,hash,consumed FROM '
                    'candidate_history_outbox WHERE id=?', (old_id,)).fetchone(),
                    (original_body, original_hash, None))
                self.assertFalse(history.startup.advance()['released'])
                self.assertTrue(acknowledge(life, event_batch, delivered))
                consumed = history.db.execute('SELECT body,consumed FROM candidate_history_outbox '
                    'WHERE id=?', (old_id,)).fetchone()
                self.assertIsNotNone(consumed[1])
                compact = json.loads(consumed[0])
                self.assertEqual(compact['source_hash'], original_hash)
                self.assertEqual(compact['record'], dict(identity=old.identity, slot=old.slot))
                self.assertIsNone(life.unconsumed(scope, through=lower + 2))
                # Receipt ACK still is not canonical proof publication.
                self.assertFalse(history.startup.advance()['released'])

                proof_batch = capture(life)
                self.assertIsNotNone(proof_batch)
                self.assertTrue(any(row['family'] == 'pump' for row in proof_batch['proofs']))
                self.assertTrue(acknowledge(life, proof_batch, deliver(proof_batch)))
                self.assertFalse(history.startup.advance()['released'])
                life.publish(proof_ids=tuple(proof_batch['publication_ids']))
                self.assertTrue(history.startup.advance()['released'])
                self.assertTrue(candidate_release(path))
                frontiers = published_program_frontiers(history.db, now=now[0])
                self.assertEqual({row['scope'] for row in frontiers},
                    {program_scope('pump'), program_scope('pumpswap')})
                self.assertEqual({row['slot'] for row in frontiers}, {lower + 2})
                self.assertEqual({row['linked_child_slot'] for row in frontiers}, {lower + 3})

                self.assertEqual(history.db.execute('SELECT * FROM candidate_gaps ORDER BY id').fetchall(), old_gaps)
                for family in ('pump', 'pumpswap'):
                    self.assertEqual(history.rolling.missing(family, program_scope(family),
                        old.slot - 10, old.slot - 10), [(old.slot - 10, old.slot - 10)])
                self.assertEqual(history.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone(), (0,))
                self.assertEqual(history.db.execute('SELECT body,hash,first_seen FROM '
                    'canonical_evidence WHERE identity=?', (old.identity,)).fetchone(), original_record)
            finally:
                state.writer.close()


if __name__ == '__main__':
    unittest.main()
