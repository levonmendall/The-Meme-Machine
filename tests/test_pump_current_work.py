"""Real canonical discovery and native decision COMMIT stage observations."""
from contextlib import closing, ExitStack
from copy import deepcopy
import json
import os
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.lanes.pump import runner
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime.economic_cohort import checksum
from meme_machine.runtime.pump_current_work import PumpCurrentWork, create_current_work
from meme_machine.solana_evidence_plane import EvidenceReader, decode_body
from meme_machine.solana_selective_history import ConsumerReader
from meme_machine.solana_selective_runtime import consume_pump_discovery
from tests import test_canonical_cold_archive_cohort as native
from tests.test_solana_closure import NOW


class PumpCurrentWorkTests(unittest.TestCase):
    def setUp(self):
        # Compose, never inherit, the original real startup/coverage/FULL ACK/
        # archive/move fixture. Its financial and source guards stay genuine.
        self.fixture = native.CanonicalColdArchiveCohortTests('runTest')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,
            MM_SOLANA_CANDIDATE_HISTORY_DB=str(self.fixture.consumer)))
        self.shared = self.stack.enter_context(closing(CandidateHistory(self.fixture.consumer)))
        self.work = PumpCurrentWork(self.shared.path, 'native-test-epoch', runner.policy_hash())
        self.source = self.stack.enter_context(closing(EvidenceReader(self.fixture.source)))
        reader = ConsumerReader(self.source)
        self.tape = SimpleNamespace(native_work=self.work,
            plane=SimpleNamespace(_selective_reader=lambda:reader, clock=lambda:NOW))

    def consume(self):
        events, sequence = consume_pump_discovery(self.tape, 0)
        self.assertTrue(events)
        return events, sequence

    def disposition_all(self, events):
        for event in events: self.work.disposition(event, 'POLICY_FILTERED')
        self.work.finish()

    def attempt(self, event, *, stage='full_point_in_time'):
        signal = runner.SignalVector(mint=event['mint'], observed_at=int(NOW),
            surface='pump.fun', phase=runner.MODE_LATE_CURVE)
        qualification = runner.qualify(signal)
        report = dict(attempts=[], full_evidence_candidates=[])
        with patch.object(runner,'CANDIDATE_HISTORY',self.shared), \
                patch.object(runner,'ACCOUNTING',None), patch.object(runner,'PIPELINE',None), \
                patch('meme_machine.runtime.directional_sleeve.open_sleeve',return_value=None):
            return runner._record_attempt(report,signal,qualification,stage), report

    def attach(self): self.shared._native_current_work = self.work

    def test_actual_complete_discovery_prefix_and_real_decision_outer_commit(self):
        events, sequence = self.consume(); self.attach()
        event = events[0]
        self.work.request(event, int(NOW), runner.MODE_LATE_CURVE)
        self.assertEqual(self.work.snapshot()['evaluation']['completed_cohorts'], 0)
        row, _ = self.attempt(event)
        self.assertFalse(self.shared.db.in_transaction)
        stored = self.shared.db.execute('SELECT hash FROM decisions WHERE id=?', (row['decision_id'],)).fetchone()
        self.assertIsNotNone(stored)
        for later in events[1:]: self.work.disposition(later,'COALESCED_NOT_DUE',int(NOW)+5)
        self.work.finish(); view = self.work.snapshot()
        self.assertEqual(view['discovery']['completed_cohorts'], 1)
        self.assertEqual(view['evaluation']['completed_cohorts'], 1)
        self.assertEqual(view['evaluation']['closed'][0]['dispositions'], {'DECISION_COMMITTED':1})
        self.assertEqual(view['actual_decision_stages'],dict(optimistic_preflight=0,full_point_in_time=1))
        self.assertEqual(view['discovery']['closed'][0]['expected_units'],len(self.tape.candidate_history_rows))
        self.assertFalse(view['source_generation_bound'])
        self.assertIn('UNKNOWN',view['full_market_rate']); self.assertFalse(view['funding_authority'])
        self.assertEqual(sequence,self.fixture.expected_discovery[-1][0])
        self.assertNotIn(event['mint'],json.dumps(view))

    def test_default_and_instrumented_discovery_sql_events_cursor_and_native_rows_match(self):
        traces=[]; results=[]
        original_open = __import__('meme_machine.runtime.candidate_history',fromlist=['open_candidate_history']).open_candidate_history
        for work in (None,self.work):
            trace=[]; self.source.db.set_trace_callback(trace.append)
            def opened():
                value=original_open(); value.db.set_trace_callback(trace.append); return value
            self.tape.native_work=work
            with patch('meme_machine.runtime.candidate_history.open_candidate_history',side_effect=opened):
                results.append(consume_pump_discovery(self.tape,0))
            traces.append(trace)
        self.assertEqual(results[0],results[1]);self.assertEqual(traces[0],traces[1])
        self.assertEqual(len(self.tape.candidate_history_rows),len(self.fixture.expected_discovery))
        self.disposition_all(results[1][0])
        self.assertEqual(self.work.snapshot()['discovery']['completed_cohorts'],1)
        evaluation=self.work.snapshot()['evaluation']
        self.assertEqual(evaluation['completed_cohorts'],1)
        self.assertEqual(evaluation['closed'][0]['expected_units'],0)
        self.assertEqual(evaluation['closed'][0]['committed_units'],0)

    def test_optimistic_rejection_is_actual_durable_decision_not_full_evidence_credit(self):
        events,_=self.consume();self.attach()
        self.work.request(events[0],int(NOW),runner.MODE_LATE_CURVE)
        row,_=self.attempt(events[0],stage='optimistic_preflight')
        self.assertFalse(row['qualified']);self.assertEqual(row['stage'],'optimistic_preflight')
        for event in events[1:]:self.work.disposition(event,'POLICY_FILTERED')
        self.work.finish()
        self.assertEqual(self.work.snapshot()['evaluation']['completed_cohorts'],1)
        self.assertEqual(self.shared.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],1)

    def test_original_commit_failure_propagates_and_cannot_publish_measurement(self):
        events,_=self.consume();self.attach();self.work.request(events[0],int(NOW),runner.MODE_LATE_CURVE)
        original=self.shared.db
        class FailedCommit:
            def __getattr__(self,name):return getattr(original,name)
            def execute(self,sql,*args):
                if sql=='COMMIT':raise sqlite3.OperationalError('actual-native-commit-failure')
                return original.execute(sql,*args)
        self.shared.db=FailedCommit()
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError,'actual-native-commit-failure'):
                self.attempt(events[0])
        finally:self.shared.db=original
        self.assertFalse(original.in_transaction)
        self.assertEqual(original.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],0)
        self.work.finish();view=self.work.snapshot()['evaluation']
        self.assertEqual(view['completed_cohorts'],0);self.assertEqual(view['pending_units'],1)
        self.assertEqual(view['active'][0]['dispositions'],{'INCOMPLETE':1})

    def test_uncommitted_nested_decision_never_counts_and_original_rollback_remains(self):
        events,_=self.consume();self.attach();self.work.request(events[0],int(NOW),runner.MODE_LATE_CURVE)
        self.shared.db.execute('BEGIN IMMEDIATE')
        try:
            row,_=self.attempt(events[0])
            self.assertIsNotNone(self.shared.db.execute('SELECT id FROM decisions WHERE id=?',(row['decision_id'],)).fetchone())
            self.assertEqual(self.work.snapshot()['evaluation']['completed_cohorts'],0)
            self.assertEqual(self.work.snapshot()['evaluation']['state'],'UNKNOWN')
        finally:self.shared.db.execute('ROLLBACK')
        self.assertEqual(self.shared.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],0)

    def test_omitted_history_or_request_hook_cannot_close_smaller_population(self):
        events,_=self.consume();self.attach()
        self.attempt(events[0])
        self.assertEqual(self.work.snapshot()['evaluation']['state'],'UNKNOWN')
        # An independently selected prefix without real history publication
        # cannot be relabeled as a genuine zero-demand native traversal.
        other=PumpCurrentWork(self.shared.path,'native-test-epoch',runner.policy_hash())
        selected=ConsumerReader(self.source).discovery(0,as_of=NOW)
        records=[decode_body(row[1],self.source.db) for row in selected]
        all_events=[dict(record['payload']['event']) for record in records]
        other.capture(0,selected,records,all_events)
        other.disposition(all_events[0],'NATIVE_FILTERED');other.finish()
        self.assertEqual(other.snapshot()['discovery']['state'],'UNKNOWN')
        self.assertEqual(other.snapshot()['discovery']['completed_cohorts'],0)

    def test_incomplete_and_five_second_coalescing_are_distinct_from_evaluation(self):
        events,_=self.consume()
        self.work.disposition(events[0],'MISSING_CREATION')
        for event in events[1:]:self.work.disposition(event,'COALESCED_NOT_DUE',int(NOW)+5)
        self.work.finish(); view=self.work.snapshot()
        self.assertEqual(view['discovery']['pending_units'],1)
        self.assertEqual(view['discovery']['completed_cohorts'],0)
        self.assertEqual(view['evaluation']['completed_cohorts'],0)
        self.assertEqual(view['evaluation']['expected_units'],0)

    def test_empty_repeated_cursor_has_no_fabricated_work_or_reopen_failure(self):
        events,sequence=self.consume();self.disposition_all(events)
        for _ in range(3):
            self.assertEqual(consume_pump_discovery(self.tape,sequence),([],sequence));self.work.finish()
        self.assertEqual(self.work.snapshot()['discovery']['completed_cohorts'],1)
        self.assertEqual(self.work.snapshot()['discovery']['state'],'MEASURING')

    def test_empty_cursor_does_not_erase_prior_work_or_allow_late_normal_rebinding(self):
        events,sequence=self.consume();self.disposition_all(events)
        before=self.work.snapshot()['discovery']
        self.assertEqual(consume_pump_discovery(self.tape,sequence),([],sequence));self.work.finish()
        provenance=dict(identity_sha256='a'*64,source_pid=123,source_start_ticks=456,
            generation='b'*32,instance_sha256='c'*64,epoch_sha256=checksum('native-test-epoch'))
        self.work.source_observation(provenance);view=self.work.snapshot()
        self.assertEqual(view['discovery']['state'],'UNKNOWN')
        self.assertFalse(view['source_generation_bound'])
        self.assertEqual(view['discovery']['completed_cohorts'],before['completed_cohorts'])
        self.assertEqual(view['discovery']['cumulative_summary_sha256'],before['cumulative_summary_sha256'])

    def test_unknown_source_rebinding_and_epoch_crossing_are_not_normal_provenance(self):
        provenance=dict(identity_sha256='a'*64,source_pid=123,source_start_ticks=456,
            generation='b'*32,instance_sha256='c'*64,epoch_sha256=checksum('native-test-epoch'))
        self.work.source_observation(provenance)
        self.assertTrue(self.work.snapshot()['source_generation_bound'])
        crossed=dict(provenance,identity_sha256='d'*64)
        self.work.source_observation(crossed)
        self.assertEqual(self.work.snapshot()['discovery']['state'],'UNKNOWN')
        other=PumpCurrentWork(self.shared.path,'other-epoch',runner.policy_hash())
        other.source_observation(provenance)
        self.assertEqual(other.snapshot()['discovery']['state'],'UNKNOWN')
        other.source_observation(dict(provenance,epoch_sha256=checksum('other-epoch')))
        self.assertEqual(other.snapshot()['discovery']['state'],'UNKNOWN')
        missing=PumpCurrentWork(self.shared.path,'native-test-epoch',runner.policy_hash())
        missing.source_observation(provenance);missing.source_observation(None)
        self.assertEqual(missing.snapshot()['discovery']['state'],'UNKNOWN')

    def test_opt_out_adds_no_observer_or_provider_work(self):
        with patch.dict(os.environ,MM_ECONOMIC_COHORT_DIAGNOSTICS='0'), \
                patch('meme_machine.runtime.pump_current_work.PumpCurrentWork',side_effect=AssertionError):
            self.assertIsNone(create_current_work(self.shared,'native-test-epoch',runner.policy_hash()))

    def test_partial_retention_cannot_filter_complete_expected_input_population(self):
        reader=ConsumerReader(self.source);selected=reader.discovery(0,as_of=NOW)
        records=[decode_body(row[1],reader.db) for row in selected]
        events=[dict(record['payload']['event']) for record in records]
        batch=self.work.capture(0,selected,records,events)
        self.work.retained(batch,self.shared,len(selected)-1)
        self.work.finish();view=self.work.snapshot()['discovery']
        self.assertEqual(view['state'],'UNKNOWN');self.assertEqual(view['completed_cohorts'],0)

    def test_actual_collector_roundtrip_keeps_hashes_stage_clocks_and_explicit_owner_limit(self):
        from engineering.diagnostics.current_combined_observation_20261014 import current_work_observation
        events,_=self.consume();self.disposition_all(events)
        view=self.work.snapshot()
        result=current_work_observation({'pump':{'native_current_work':view,'private_token':'never-copy'}})
        self.assertEqual(result,view)
        self.assertIn('UNBOUND',result['owner']['private_owner_binding'])
        self.assertNotIn('private_token',json.dumps(result))
        self.assertLessEqual(len(json.dumps(result).encode()),16384)
        self.assertIsNone(current_work_observation({'pump':{'ordinary_status':True}}))


if __name__=='__main__':unittest.main()
