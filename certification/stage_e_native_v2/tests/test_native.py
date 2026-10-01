import copy
from pathlib import Path
import tempfile
import unittest

from certification.stage_e_native_v2.native import transitions,native_state,snapshot,TransactionTrace
from certification.stage_e_native_v2.clock import DeterministicClock
from certification.stage_e_native_v2.restart import records,check_generations,check_restart
from certification.stage_e_native_v2.verify import native_witness


class NativeWitnessTests(unittest.TestCase):
    def test_actual_committed_archive_retirement_and_native_lane_selection(self):
        with tempfile.TemporaryDirectory() as td:
            proof=transitions(td)
            self.assertTrue(native_witness(proof,proof['generation'],False))
            self.assertTrue(proof['selection']['pump']['selected_events'])
            self.assertTrue(proof['selection']['meteora']['selected_transactions'])
            self.assertTrue(proof['retention_outcome']['retired_records'])
    def test_held_snapshot_is_read_before_writer_commit_and_checkpoint_finishes_after_release(self):
        with tempfile.TemporaryDirectory() as td:
            proof=transitions(td,held=True)
            self.assertTrue(native_witness(proof,proof['generation'],True))
            self.assertTrue(proof['held_reader']['snapshot_query'].startswith('SELECT'))
    def test_attempts_rollback_and_cross_generation_never_qualify(self):
        with tempfile.TemporaryDirectory() as td:
            proof=transitions(td)
            wrong=copy.deepcopy(proof);wrong['archive_transactions'][0]['committed']=False
            with self.assertRaisesRegex(ValueError,'attempt'):native_witness(wrong,proof['generation'],False)
            with self.assertRaisesRegex(ValueError,'cross_generation'):native_witness(proof,'foreign-generation',False)
            wrong=copy.deepcopy(proof);wrong['selection']['pump']['generation']='foreign'
            with self.assertRaisesRegex(ValueError,'selection_identity'):native_witness(wrong,proof['generation'],False)
    def test_native_rollbacks_do_not_earn_archive_or_progress_ledger_credit(self):
        from meme_machine.solana_evidence_plane import EvidenceWriter
        clock=DeterministicClock();clock.begin()
        with tempfile.TemporaryDirectory() as td,native_state(Path(td)/'db',clock) as state:
            state.writer.ingest(records(clock,'program:meteora',3,'rollback'))
            plan,receipt=EvidenceWriter.prepare_and_write_archive(state.writer.path,state.archive_plan())
            before=snapshot(state.writer.path);trace=TransactionTrace(state.writer,state.fence.session,'db')
            with self.assertRaisesRegex(RuntimeError,'rollback'):
                with state.writer.transaction():
                    state.writer.commit_archive(plan,receipt)
                    raise RuntimeError('rollback injected')
            after=snapshot(state.writer.path);trace.close()
            self.assertEqual(before['progress'],after['progress'])
            self.assertEqual(before['records'],after['records'])
            self.assertEqual(trace.commits,[])
            self.assertTrue(trace.attempts and trace.attempts[-1]['committed'] is False)
    def test_stale_decision_worker_and_receipt_rejected_by_production(self):
        with tempfile.TemporaryDirectory() as td:
            proof=check_generations(td);self.assertEqual(len(proof['rejected']),3)
            self.assertEqual(proof['stale_records_committed'],0)
    def test_native_stale_economic_event_in_fresh_source_block_cannot_qualify(self):
        import json
        from certification.stage_e_native_v2.fixtures import build_frame,timed_transaction
        from certification.stage_e_native_v2.native import source
        from certification.stage_e_native_v2.clock import validate_clock_samples
        from certification.stage_e_native_v2.fixtures import spec
        clock=DeterministicClock()
        frame=json.loads(build_frame('run380',0,bounded=True))
        block=frame['params']['result']['value']['block']
        block['transactions']=[timed_transaction(tx,clock.wall_epoch-241,'stale-native:'+str(i)) for i,tx in enumerate(block['transactions'])]
        raw=json.dumps(frame,separators=(',',':')).encode()
        with tempfile.TemporaryDirectory() as td,native_state(Path(td)/'db',clock) as state:
            clock.begin();source(state,raw,clock);durable=snapshot(state.writer.path)
            rows=[r for r in durable['records'] if r['scope']=='program:pump']
            self.assertTrue(rows);self.assertTrue(all(r['event_at']==clock.wall_epoch-241 for r in rows))
            sample=dict(wall=clock.time(),monotonic=clock.monotonic(),source=block['blockTime'],
                economic_now=clock.time(),residence_now=clock.time(),records=[dict(identity=r['identity'],event_at=r['event_at']) for r in rows])
            with self.assertRaisesRegex(ValueError,'stale_economic'):validate_clock_samples([sample],spec('run380')['clock'])
    def test_restart_recovers_native_ledger_receipt_retirement_and_original_episode(self):
        with tempfile.TemporaryDirectory() as td:
            proof=check_restart(td)
            self.assertEqual(proof['episode_before'],proof['episode_after'])
            self.assertEqual(proof['committed_service_before'],proof['reconstructed_ledger'])
            self.assertTrue(proof['no_duplicate_completion'] and proof['no_lost_completion'])
    def test_run379_native_setup_does_not_age_and_original_availability_survives_schedule(self):
        from certification.stage_e_native_v2.run379 import bounded_setup_witness
        with tempfile.TemporaryDirectory() as td:
            proof=bounded_setup_witness(td)
            self.assertEqual(proof['setup_elapsed_us'],0)
            self.assertEqual(proof['native_hot_debt'],200)
            self.assertTrue(proof['original_availability_preserved'])
            self.assertFalse(proof['full_shape_executed'])


if __name__=='__main__':unittest.main()
