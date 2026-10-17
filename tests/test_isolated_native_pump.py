"""Offline public provenance projection; never a market-capacity proof."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational.isolated_native_pump import PumpNativeProjection, SOURCE
from meme_machine.solana_program_decoders import pump_events, pumpswap_trade_events

FIXTURE = json.loads((Path(__file__).parent/'fixtures/solana_selective_cohort.json').read_text())
NOW = 1792000000


def block_for(original):
    tx = copy.deepcopy(original)
    tx.pop('transactionIndex', None)
    return dict(blockTime=tx['blockTime'], blockhash='offline-block-'+str(tx['slot']),
                parentSlot=tx['slot']-1, previousBlockhash='offline-parent', transactions=[tx])


class IsolatedNativePumpTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.projection = PumpNativeProjection(self.root)
        self.addCleanup(self.projection.close)

    def test_actual_pump_decoders_FULL_candidate_commit_and_real_restoration(self):
        tx = FIXTURE['pump'][0]
        expected = sorted(pump_events(tx), key=lambda row: row['index'])
        self.assertTrue(any(row['event_type']=='create' for row in expected))
        result = self.projection.consume(tx['slot'], block_for(tx), observed_at=NOW)
        self.assertEqual(result['decoded_events'], len(expected))
        candidate = expected[0]['mint']
        rows = self.projection.history.events('pump', candidate)
        self.assertEqual([row['payload'] for row in rows], expected)
        self.assertTrue(all(row['transaction_index']==0 for row in rows))
        before = self.projection.snapshot()
        restored = self.projection.reopen(now=NOW)
        self.assertEqual(restored['restored_created_candidates'], 1)
        self.assertEqual(restored['authenticated_history_events'], len(expected))
        self.assertTrue(restored['economic_history_unchanged'])
        after = self.projection.snapshot()
        self.assertEqual(before['logical_sha256'], after['logical_sha256'])
        self.assertEqual(after['sqlite_synchronous'], 2)
        self.assertEqual(after['sqlite_journal_mode'], 'wal')
        self.assertFalse(after['canonical_completeness'])
        self.assertFalse(after['funding_authority'])
        self.assertEqual(after['source'], SOURCE)
        self.assertTrue(all(after['counts'][key]==0 for key in
            ('funding','decisions','canonical_event_refs','history_coverage')))
        self.assertFalse(any((self.root/name).exists() for name in
            ('portfolio.sqlite','shared-capital.sqlite','native-genesis.json')))

    def test_swap_only_candidates_persist_and_are_excluded_from_Pump_creation_restore(self):
        tx = FIXTURE['pumpswap'][0]
        expected = sorted(pumpswap_trade_events(tx), key=lambda row: row['index'])
        self.assertTrue(expected)
        result = self.projection.consume(tx['slot'], block_for(tx), observed_at=NOW)
        self.assertEqual(result['events_by_family']['pumpswap'], len(expected))
        self.assertEqual(result['events_by_family']['pump'], 0)
        restored = self.projection.reopen(now=NOW)
        self.assertEqual(restored['restored_created_candidates'], 0)
        self.assertEqual(restored['authenticated_history_events'], len(expected))

    def test_identical_replay_is_idempotent_and_conflicting_block_is_refused(self):
        tx = FIXTURE['pump'][0]
        block = block_for(tx)
        self.projection.consume(tx['slot'], block, observed_at=NOW)
        before = self.projection.snapshot()
        replay = self.projection.consume(tx['slot'], block, observed_at=NOW+1)
        self.assertTrue(replay['duplicate'])
        self.assertEqual(before, self.projection.snapshot())
        changed = dict(block, blockhash='changed')
        with self.assertRaisesRegex(ValueError, 'block_replay_conflict'):
            self.projection.consume(tx['slot'], changed, observed_at=NOW)
        self.assertEqual(before, self.projection.snapshot())

    def test_missing_or_truncated_economic_logs_do_not_commit_partial_block(self):
        tx = FIXTURE['pump'][0]
        before = self.projection.snapshot()
        for logs in (None, ['Log truncated']):
            block = block_for(tx)
            block['transactions'][0]['meta']['logMessages'] = logs
            with self.assertRaisesRegex(ValueError, 'complete_logs_required'):
                self.projection.consume(tx['slot'], block, observed_at=NOW)
            self.assertEqual(before, self.projection.snapshot())

    def test_full_block_native_order_cannot_be_replaced_with_filtered_rank(self):
        tx = FIXTURE['pump'][0]
        block = block_for(tx)
        block['transactions'][0]['transactionIndex'] = 7
        with self.assertRaisesRegex(ValueError, 'transaction_order'):
            self.projection.consume(tx['slot'], block, observed_at=NOW)
        self.assertEqual(self.projection.snapshot()['blocks'], 0)

    def test_failed_transactions_have_no_committed_economics(self):
        tx = FIXTURE['pump'][0]
        block = block_for(tx)
        block['transactions'][0]['meta']['err'] = {'InstructionError':[0,'offline_failure']}
        block['transactions'][0]['meta']['logMessages'] = None
        result = self.projection.consume(tx['slot'], block, observed_at=NOW)
        self.assertEqual(result['decoded_events'], 0)
        self.assertEqual(self.projection.snapshot()['counts']['events'], 0)

    def test_future_block_and_inherited_production_configuration_are_refused(self):
        tx = FIXTURE['pump'][0]
        with self.assertRaisesRegex(ValueError, 'block_time'):
            self.projection.consume(tx['slot'], block_for(tx), observed_at=tx['blockTime']-1)
        with patch.dict(os.environ, MM_STATE_ROOT='/authoritative/production'):
            with self.assertRaisesRegex(ValueError, 'production_environment_refused'):
                self.projection.consume(tx['slot'], block_for(tx), observed_at=NOW)
        self.assertEqual(self.projection.snapshot()['blocks'], 0)

    def test_existing_or_linked_destination_is_refused(self):
        with self.assertRaises(FileExistsError):
            PumpNativeProjection(self.root)
        linked = self.root/'linked'
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'private_root_required'):
            PumpNativeProjection(linked)


if __name__ == '__main__':
    unittest.main()
