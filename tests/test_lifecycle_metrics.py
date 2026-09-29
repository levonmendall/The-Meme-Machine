"""Useful work is recorded by scope only after the real durable boundary."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_provider_config import AlchemyEndpoint
from tests.test_run381_retention_progress import record

CONFIG=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
SUB=SimpleNamespace(evidence_class='blocks')

def rec(identity,scope='program:meteora'):
    return replace(record(),identity=identity,signature=identity,scope=scope,slot=10,
                   market_time=10,observed_at=1000)

class LifecycleMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.state=ServiceState(Path(self.tmp.name)/'db',CONFIG)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.state.close)

    def source(self,*names,bad=None):
        def ingest(sub,name,seen,size):
            self.state.writer.ingest([rec(name)])
            if name==bad:raise ValueError('test_bad_frame')
        with patch.object(self.state,'_source_locked',side_effect=ingest):
            return self.state.source_batch([(SUB,name,0,1) for name in names])

    def test_source_counts_committed_unique_rows_not_duplicate_frames(self):
        self.source('a','b');self.source('a')
        metrics=self.state.storage_metrics
        self.assertEqual(metrics['lifecycle.source.meteora.records'],2)
        self.assertEqual(metrics['lifecycle.source.committed_frames'],3)
        self.assertIsNone(self.state.writer._source_stage_progress)

    def test_partial_failure_counts_valid_prefix_not_rolled_back_frame(self):
        with self.assertRaisesRegex(ValueError,'test_bad_frame'):
            self.source('a','b',bad='b')
        self.assertEqual(self.state.storage_metrics['lifecycle.source.meteora.records'],1)
        self.assertEqual(self.state.storage_metrics['lifecycle.source.committed_frames'],1)
        self.assertEqual(self.state.writer.db.execute('SELECT identity FROM records').fetchall(),[('a',)])
        self.assertIsNone(self.state.writer._source_stage_progress)

    def test_first_frame_failure_does_not_invent_useful_rows(self):
        with self.assertRaises(ValueError):self.source('b',bad='b')
        self.assertEqual(self.state.storage_metrics.get('lifecycle.source.meteora.records',0),0)
        self.assertEqual(self.state.storage_metrics['lifecycle.source.committed_frames'],0)

    def test_archive_retry_and_pin_count_only_actual_committed_changes(self):
        self.state.writer.ingest([rec('a'),rec('b','program:pump')])
        snapshot=self.state.writer.archive_snapshot(900)
        plan,receipt=self.state.writer.prepare_and_write_archive(self.state.writer.path,snapshot)
        self.state.writer.interest('position','program:pump',lower_slot=10,priority=0,lifecycle='open')
        self.state.archive_commit(plan,receipt,retain=False)
        self.state.archive_commit(plan,receipt,retain=False)
        self.assertEqual(self.state.storage_metrics['lifecycle.archive.meteora.records'],1)
        self.assertEqual(self.state.storage_metrics.get('lifecycle.archive.pump.records',0),0)
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NULL').fetchone()[0],1)

    def test_retention_scopes_match_actual_durable_retirement(self):
        self.state.writer.ingest([rec('a'),rec('b','program:pump')])
        self.state.writer.archive(900)
        with patch('meme_machine.solana_evidence_service.time.time',return_value=1000):
            outcome=self.state.retention()
        self.assertEqual(outcome.retired_records,2)
        self.assertEqual({s.scope:s.retired_records for s in outcome.scopes},
                         {'program:meteora':1,'program:pump':1})
        self.assertEqual(self.state.storage_metrics['lifecycle.retention.meteora.retired_records'],1)
        self.assertEqual(self.state.storage_metrics['lifecycle.retention.pump.retired_records'],1)

    def test_account_metric_cardinality_is_bounded(self):
        for n in range(300):self.state._scope_metric('source','account:'+str(n),'records',1)
        self.assertEqual(self.state.storage_metrics['lifecycle.source.other.records'],300)
        self.assertFalse(any('account:' in key for key in self.state.storage_metrics))

    def test_outer_transaction_cannot_publish_undurable_source_or_archive_metrics(self):
        with self.state.writer.transaction():
            with self.assertRaisesRegex(EvidenceUnavailable,'source_batch_inside_transaction'):
                self.source('a')
            with self.assertRaisesRegex(EvidenceUnavailable,'archive_inside_source_transaction'):
                self.state.archive_commit([],None)
