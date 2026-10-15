"""Actual owner/data/collector equivalence, using only disposable fixtures."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime import operation_costs as costs
from meme_machine.solana_economic_preparation import prepare_candidate_frames
from meme_machine.solana_selective_source import commit_candidate_batch
from tests.test_solana_closure import state_at, NOW
from tests.test_solana_selective_evidence import FIXTURE
from tests.test_solana_history_refinement import frame


class OwnerOperationCostsTests(unittest.TestCase):
    def test_opt_in_preserves_actual_economic_order_receipts_outbox_and_sql(self):
        with tempfile.TemporaryDirectory() as td:
            original, a = state_at(Path(td) / 'original.sqlite')
            measured, b = state_at(Path(td) / 'measured.sqlite')
            traces = [[], []]
            try:
                from meme_machine.solana_selective_history import PROGRAMS
                from meme_machine.solana_rolling_history import program_scope
                f = frame(copy.deepcopy(FIXTURE['pump'][0]), 'pump')
                addresses = {PROGRAMS['pump']: program_scope('pump')}
                prepared, _ = prepare_candidate_frames((f,), addresses, 'operation-equivalence', 'a' * 64)
                for n, state in enumerate((original, measured)):
                    # Compare verbs, not random nested-savepoint names.
                    state.writer.db.set_trace_callback(lambda sql, n=n: traces[n].append(sql.lstrip().split(None, 1)[0]))
                    with patch.dict(os.environ, MM_OPERATION_COST_DIAGNOSTICS=str(n)):
                        commit_candidate_batch(state, (f,), addresses, 'operation-equivalence',
                                               publish=False, prepared=prepared)
                self.assertEqual(traces[0], traces[1])
                for table, order in (('rolling_economic_events', 'identity'),
                        ('rolling_economic_addresses', 'identity,address'),
                        ('candidate_content_receipts', 'identity'), ('rolling_event_lineage', 'identity'),
                        ('candidate_lifecycle', 'family,address'), ('candidate_history_outbox', 'id'),
                        ('candidate_outbox', 'sequence'), ('native_order_attestations', 'scope,slot,signature'),
                        ('candidate_blocks', 'scope')):
                    self.assertEqual(a.db.execute('SELECT * FROM ' + table + ' ORDER BY ' + order).fetchall(),
                                     b.db.execute('SELECT * FROM ' + table + ' ORDER BY ' + order).fetchall(), table)
                snapshot = costs.snapshot()
                # Fresh bulk attestation stays in store_many; it must not be
                # reintroduced through the scalar attest_order method to make
                # a diagnostic counter appear exercised.
                for name in ('owner.economic_ingest', 'owner.rolling_store', 'owner.history_outbox'):
                    self.assertGreater(snapshot['rows'][name]['calls'], 0, name)
                sql = snapshot['rows']['owner.rolling_store']['sql']
                self.assertGreater(sql['statement']['calls'], 0)
            finally:
                original.writer.close(); measured.writer.close()

    def test_promotion_and_demotion_keep_original_pending_obligation(self):
        from meme_machine.solana_history_work import HistoricalTasks
        with tempfile.TemporaryDirectory() as td:
            state, h = state_at(Path(td) / 'canonical.sqlite')
            try:
                h.historical_tasks = HistoricalTasks(h)
                h.observe('pump', 'operation-fixture', slot=10, signature='fixture-scout', fields={})
                with patch.dict(os.environ, MM_OPERATION_COST_DIAGNOSTICS='1'):
                    promotion = h.lifecycle.promote('pump', 'operation-fixture', deadline=NOW + 150, lower_slot=0)
                    h.lifecycle.demote('pump', 'operation-fixture', reason='offline_fault_boundary')
                self.assertIsNotNone(promotion)
                self.assertEqual(h.db.execute('SELECT state,deadline FROM candidate_lifecycle WHERE address=?',
                                             ('operation-fixture',)).fetchone(), ('demoted', NOW + 150))
                self.assertIsNone(h.db.execute('SELECT consumed FROM candidate_history_outbox WHERE id=?',
                                              (promotion,)).fetchone()[0])
                rows = costs.snapshot()['rows']
                self.assertGreater(rows['owner.reactivation_promote']['sql']['statement']['calls'], 0)
                self.assertGreater(rows['owner.reactivation_demote']['sql']['statement']['calls'], 0)
            finally:state.writer.close()
