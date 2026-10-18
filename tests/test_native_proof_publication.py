"""Actual native proof publication is separate from verified event FULL ACK."""
from copy import deepcopy
import json
import re
import sqlite3
import unittest
from unittest.mock import patch

import tests.test_economic_cohort_measurement as fixture
from meme_machine.runtime.economic_cohort import checksum
from meme_machine.runtime.native_proof_publication import NativeProofPublications,projection
from meme_machine.runtime.pump_economic_cohort import _Stage
from meme_machine.solana_history_delivery import capture,deliver,acknowledge
from tests.test_solana_closure import state_at


class NativeProofPublicationTests(unittest.TestCase):
    setUp=fixture.NativePumpEconomicCohortTests.setUp
    commit=fixture.NativePumpEconomicCohortTests.commit

    def consume(self):
        ids=[]
        for _ in range(24):
            snapshot=capture(self.history.lifecycle)
            if snapshot is None:break
            ids.extend(p['identity'] for p in snapshot['proofs'])
            self.assertTrue(acknowledge(self.history.lifecycle,snapshot,deliver(snapshot)))
        return tuple(dict.fromkeys(ids))

    def test_actual_complete_linked_proofs_publish_only_after_source_outer_commit(self):
        self.commit(self.frames[:8]);self.commit(self.frames[8:])
        before=self.measurement.snapshot()['proof_publication']
        self.assertEqual(before['active_windows'],1);self.assertEqual(before['completed_windows'],0)
        self.assertGreater(before['active'][0][5],0)
        ids=self.consume();self.assertTrue(ids)
        # FULL ACK and consumer proof receipt COMMIT do not publish source proofs.
        source=self.measurement.snapshot();self.assertEqual(source['completed_cohorts'],1)
        self.assertEqual(source['proof_publication']['completed_windows'],0)
        calls=[];original=self.measurement.published_proofs
        def observed(rows):
            self.assertFalse(self.state.writer.db.in_transaction)
            for identity,_ in rows:
                self.assertIsNone(self.history.db.execute('SELECT id FROM candidate_pending_proofs WHERE id=?',(identity,)).fetchone())
            calls.append(rows);return original(rows)
        with patch.object(self.measurement,'published_proofs',side_effect=observed):
            self.history.lifecycle.publish(proof_ids=ids)
        result=self.measurement.snapshot()['proof_publication']
        self.assertEqual(result['completed_windows'],1);self.assertEqual(result['active_windows'],0)
        self.assertTrue(calls);self.assertTrue(all(len(rows)<=64 for rows in calls))
        self.assertEqual(result['closed'][0][3:5],[100,107])
        self.assertEqual(result['closed'][0][5],before['active'][0][5])
        self.assertEqual(projection(result,self.measurement.meter.binding_hash),result)
        # All original maximum-sized source/history fields still fit the old
        # envelope. Proof samples may be explicitly omitted, never their full
        # population counts/digests or the original cohort observations.
        from meme_machine.runtime.pump_economic_cohort import projection as combined_projection
        wide=deepcopy(self.measurement.snapshot())
        wide['closed']=[dict(wide['closed'][0],cohort_sha256=checksum(i)) for i in range(16)]
        wide['source_closed']=[dict(wide['source_closed'][0],cohort_sha256=checksum(i)) for i in range(16)]
        wide['active']=[dict(wide['active'][0],cohort_sha256=checksum(i)) for i in range(8)]
        wide['completed_cohorts']=16;wide['active_cohorts']=8
        wide['active_identities']=sum(row['unique_economics'] for row in wide['active'])
        projected=combined_projection(wide)
        self.assertEqual(projected['completed_cohorts'],16)
        self.assertEqual(projected['proof_publication']['completed_windows'],1)
        self.assertEqual(projected['proof_publication']['closed_sha256'],result['closed_sha256'])
        self.assertEqual(len(projected['proof_publication']['closed'])+projected['proof_publication']['closed_omitted'],1)
        self.assertLessEqual(len(json.dumps(projected).encode()),24*1024)

    def test_original_publication_rollback_or_commit_failure_preserves_exact_pending_ids(self):
        self.commit(self.frames[:8]);self.commit(self.frames[8:]);ids=self.consume()
        pending=self.history.db.execute('SELECT * FROM candidate_pending_proofs ORDER BY id').fetchall()
        for boundary in ('body','commit'):
            with self.subTest(boundary=boundary):
                if boundary=='body':
                    original=self.history.prove;count=[]
                    def failing(proof):
                        count.append(True)
                        if len(count)==2:raise RuntimeError('native_publication_failure')
                        return original(proof)
                    target=patch.object(self.history,'prove',side_effect=failing)
                else:
                    original=self.state.writer._transaction_statement
                    def failing(sql,stage):
                        if stage=='commit':raise sqlite3.OperationalError('native_publication_failure')
                        return original(sql,stage)
                    target=patch.object(self.state.writer,'_transaction_statement',side_effect=failing)
                with target,self.assertRaisesRegex((RuntimeError,sqlite3.OperationalError),'native_publication_failure'):
                    self.history.lifecycle.publish(proof_ids=ids)
                self.assertEqual(self.history.db.execute('SELECT * FROM candidate_pending_proofs ORDER BY id').fetchall(),pending)
                self.assertEqual(self.measurement.snapshot()['proof_publication']['completed_windows'],0)
        self.history.lifecycle.publish(proof_ids=ids)
        self.assertEqual(self.measurement.snapshot()['proof_publication']['completed_windows'],1)

    def test_missing_defer_or_publication_hook_never_becomes_zero_demand(self):
        with patch.object(_Stage,'proof',return_value=None):
            self.commit(self.frames[:8]);self.commit(self.frames[8:])
        self.assertGreater(self.history.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0],0)
        ids=self.consume();self.history.lifecycle.publish(proof_ids=ids)
        self.assertEqual(self.measurement.snapshot()['proof_publication']['completed_windows'],0)
        # A genuine expected population with an omitted publication observation
        # remains pending even though native publication itself succeeded.
        ledger=NativeProofPublications('a'*64);ledger.register('b'*64,'c'*64)
        ledger.expect('native-window',1,2,'d'*64,('b'*64,))
        self.assertEqual(ledger.snapshot()['completed_windows'],0)
        self.assertEqual(ledger.snapshot()['active'][0][5:], [1,0])

    def test_original_sql_bytes_and_publication_returns_match_uninstrumented_path(self):
        baseline,history=state_at(self.root/'baseline.sqlite');self.addCleanup(baseline.writer.close)
        history.lifecycle.path=self.root/'baseline-consumer.sqlite';history.lifecycle.delivery_separated=True
        history.startup.begin()
        from meme_machine.solana_economic_preparation import prepare_candidate_frames
        from meme_machine.solana_selective_source import commit_candidate_batch,commit_control
        for frames in (self.frames[:8],self.frames[8:]):
            products,_=prepare_candidate_frames(frames,self.addresses,'b'*32,'a'*64)
            for frame in frames:commit_control(baseline,frame)
            commit_candidate_batch(baseline,frames,self.addresses,'b'*32,publish=False,prepared=products)
        self.commit(self.frames[:8]);self.commit(self.frames[8:]);self.consume()
        for _ in range(24):
            snapshot=capture(history.lifecycle)
            if snapshot is None:break
            self.assertTrue(acknowledge(history.lifecycle,snapshot,deliver(snapshot)))
        actual=[];expected=[]
        self.history.db.set_trace_callback(actual.append);history.db.set_trace_callback(expected.append)
        self.assertIsNone(self.history.lifecycle.publish());self.assertIsNone(history.lifecycle.publish())
        self.history.db.set_trace_callback(None);history.db.set_trace_callback(None)
        normalize=lambda rows:[re.sub(r'nested_[0-9a-f]{32}','nested_SAVEPOINT',row) for row in rows]
        self.assertEqual(normalize(actual),normalize(expected))
        for table in ('candidate_pending_proofs','candidate_coverage','candidate_checkpoints','candidate_history_outbox'):
            with self.subTest(table=table):
                self.assertEqual(self.history.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall(),
                    history.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall())

    def test_early_outcomes_are_retained_and_foreign_unknown_or_nested_inputs_cannot_close(self):
        ledger=NativeProofPublications('a'*64);ledger.register('b'*64,'c'*64)
        ledger.published((('b'*64,'c'*64),))
        ledger.retain({'b'*64});ledger.expect('native-window',1,2,'d'*64,('b'*64,))
        self.assertEqual(ledger.snapshot()['completed_windows'],1)
        ledger.retain(set());self.assertEqual(ledger.snapshot()['known_proofs'],0)
        missing=NativeProofPublications('a'*64)
        missing.published((('b'*64,'c'*64),));missing.expect('native-window',1,2,'d'*64,('b'*64,))
        self.assertEqual(missing.snapshot()['state'],'UNKNOWN')
        self.assertEqual(missing.snapshot()['completed_windows'],0)
        self.commit(self.frames[:8]);self.commit(self.frames[8:]);self.consume()
        with self.state.writer.transaction():
            from meme_machine.solana_evidence_plane import EvidenceUnavailable
            with self.assertRaisesRegex(EvidenceUnavailable,'candidate_consumer_before_canonical_commit'):
                self.history.lifecycle.publish()
        self.assertEqual(self.measurement.snapshot()['proof_publication']['completed_windows'],0)

    def test_fixed_projection_rejects_forgery_bounds_and_private_metadata(self):
        ledger=NativeProofPublications('a'*64)
        for i in range(20):
            key=checksum(['proof',i]);ledger.register(key,'b'*64)
            ledger.expect(str(i),i,i,'c'*64,(key,));ledger.published(((key,'b'*64),));ledger.retain(set())
        value=ledger.snapshot();self.assertEqual(value['completed_windows'],20)
        self.assertEqual(value['summary_evictions'],4);self.assertEqual(value['closed_omitted'],12)
        self.assertEqual(projection(value,'a'*64),value)
        value['closed'][0][5]=0;value['private']='https://private.invalid/never-expose'
        result=projection(value,'a'*64)
        self.assertEqual(result['state'],'UNKNOWN');self.assertNotIn('private.invalid',str(result))
        ledger=NativeProofPublications('a'*64)
        for i in range(513):ledger.register(checksum(i),'b'*64)
        self.assertEqual(ledger.snapshot()['known_proofs'],512)
        self.assertEqual(ledger.snapshot()['state'],'UNKNOWN')
