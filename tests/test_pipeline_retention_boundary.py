"""Real old-schema pipeline history crosses retention without a foreign table."""
import importlib,tempfile,unittest
from pathlib import Path
from tests import test_solana_prewarm_startup as startup_fixture

class PipelineRetentionBoundaryTests(unittest.TestCase):
    def test_all_four_lanes_cross_retention_and_restart_with_monotone_sequence(self):
        for lane in ('pump','meteora','pons','ramses'):
            with self.subTest(lane=lane),tempfile.TemporaryDirectory() as td:
                Pipeline=importlib.import_module('meme_machine.lanes.'+lane+'.pipeline').Pipeline
                path=Path(td)/'pipeline.sqlite';pipeline=Pipeline(path,lane,'fixed-policy')
                pipeline.db.executemany('INSERT INTO progress(sequence,lane,policy_hash,candidate,stage,reason,classification,at,monotonic,details) VALUES(?,?,?,?,?,?,?,?,?,?)',[(i,lane,'fixed-policy','candidate:'+str(i),'observed',None,None,100,100,'{}') for i in range(1,8192)])
                pipeline.db.commit();pipeline.close()
                pipeline=Pipeline(path,lane,'fixed-policy')
                try:
                    pipeline.record('boundary','rejected','observed-rejection','strategy_rejection')
                    self.assertEqual(pipeline.db.execute('SELECT COUNT(*) FROM progress').fetchone()[0],4096)
                    self.assertEqual(pipeline.db.execute('SELECT MAX(sequence) FROM progress').fetchone()[0],8192)
                    pipeline.record('next','observed')
                    self.assertEqual(pipeline.db.execute('SELECT MAX(sequence) FROM progress').fetchone()[0],8193)
                    self.assertEqual(pipeline.snapshot()['unique_classes']['strategy_rejection'],1)
                finally:pipeline.close()
                pipeline=Pipeline(path,lane,'fixed-policy')
                try:
                    self.assertEqual(pipeline.snapshot()['raw_records'],4097)
                    self.assertEqual(pipeline.snapshot()['unique_classes']['strategy_rejection'],1)
                    pipeline.record('restart','observed')
                    self.assertEqual(pipeline.db.execute('SELECT MAX(sequence) FROM progress').fetchone()[0],8194)
                finally:pipeline.close()


class ControlMembershipRetentionTests(unittest.TestCase):
    setUp=startup_fixture.StartupTests.setUp
    tearDown=startup_fixture.StartupTests.tearDown
    begin=startup_fixture.StartupTests.begin
    current_tail=startup_fixture.StartupTests.current_tail

    def seed_control(self,slots):
        """Disposable native schema rows; no market replay/capacity claim."""
        from meme_machine.solana_selective_runtime import CONTROL
        slots=list(slots);db=self.h.db;writer=self.state.writer
        with writer.transaction():
            for slot in slots:
                db.execute('INSERT INTO stream_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (CONTROL,slot,slot-1,'hash:'+str(slot),'hash:'+str(slot-1),
                     int(self.now[0]-1000+slot),'[]','retention-fixture',self.now[0]-1000,1))
                for signature in ('first','second'):
                    db.execute('INSERT INTO stream_deliveries VALUES(?,?,?,?,?)',
                        (CONTROL,slot,signature,'hash:'+str(slot),self.now[0]-1000))
                    db.execute('INSERT INTO stream_order VALUES(?,?,?,?,?)',
                        (CONTROL,slot,signature,0,'hash:'+str(slot)))
            top=max(slots)
            db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',(CONTROL,top,self.now[0]))
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('retention_floor:'+CONTROL,str(top+1)))

    def defer(self,lo,hi=None):
        from meme_machine.solana_rolling_history import program_scope
        self.h.lifecycle.defer_proof(startup_fixture.proof(program_scope('pump'),lo,lo if hi is None else hi))

    def retire(self,limit=256):
        self.state.writer.retain(self.now[0]-180,max_records=limit,archive_first=False,checkpoint=False)
        return self.state.writer.last_retention_progress.snapshot()

    def control_slots(self,table='stream_receipts'):
        from meme_machine.solana_selective_runtime import CONTROL
        return {row[0] for row in self.h.db.execute('SELECT slot FROM '+table+' WHERE scope=?',(CONTROL,))}

    def test_dense_exact_pins_are_paged_before_filtering_and_later_work_is_retired(self):
        from meme_machine.solana_maintenance_state import DebtAgeAdapter
        from meme_machine.solana_selective_runtime import CONTROL
        self.seed_control(range(640))
        for slot in range(512):self.defer(slot)
        pending=self.h.db.execute('SELECT * FROM candidate_pending_proofs ORDER BY id').fetchall()
        before=self.h.db.total_changes;statements=[]
        self.h.db.set_trace_callback(statements.append)
        try:outcome=self.retire()
        finally:self.h.db.set_trace_callback(None)
        # A fully protected first page is neither retirement nor an idle proof.
        self.assertFalse(outcome.made_progress)
        self.assertIsNone(outcome.pending)
        self.assertEqual(self.h.db.total_changes,before)
        self.assertEqual(self.control_slots(),set(range(640)))
        validations=[sql for sql in statements if 'candidate_pending_proofs p' in sql]
        self.assertEqual(len(validations),3,'validate one bounded key page per continuity table, not each record')
        pages=[sql for sql in statements if sql.startswith('SELECT rowid,slot')]
        self.assertEqual(len(pages),3)
        self.assertTrue(all('LIMIT 257' in sql and ' ORDER BY slot' in sql for sql in pages),pages)
        # Two signatures per slot force the real composite-PK pages to advance
        # within a slot, rather than skipping its second native delivery/order.
        for _ in range(5):self.retire()
        for table in ('stream_receipts','stream_deliveries','stream_order'):
            self.assertEqual(self.control_slots(table),set(range(512)),table)
        observation=DebtAgeAdapter(self.state.writer,wall=lambda:self.now[0]).observe('retention-pins')
        control=next(row for row in observation.scopes if row.scope==CONTROL)
        self.assertEqual(control.continuity,0)
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_pending_proofs ORDER BY id').fetchall(),pending)

    def test_zero_lower_and_skipped_upper_keep_only_exact_boundaries_then_publish_releases_them(self):
        from meme_machine.solana_history_delivery import proof_receipt
        self.seed_control((0,10,20,30,40))
        self.defer(0,25);self.defer(28,29)
        plan=self.h.db.execute('EXPLAIN QUERY PLAN SELECT 1 FROM candidate_pending_proofs WHERE hi>=? AND hi<? LIMIT 1',(20,30)).fetchall()
        self.assertTrue(any('candidate_proof_end' in row[3] for row in plan),plan)
        rows=self.h.db.execute('SELECT rowid,* FROM candidate_pending_proofs ORDER BY lo').fetchall()
        before=[proof_receipt(self.h.lifecycle,row) for row in rows]
        self.assertIsNone(before[1]['lower_identity'])
        self.assertEqual([row['upper_identity'][0] for row in before],[20,20])
        self.retire()
        for table in ('stream_receipts','stream_deliveries','stream_order'):
            self.assertEqual(self.control_slots(table),{0,20},table)
        self.assertEqual([proof_receipt(self.h.lifecycle,row) for row in rows],before)
        self.h.lifecycle.publish()
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0],0)
        self.retire()
        for table in ('stream_receipts','stream_deliveries','stream_order'):
            self.assertEqual(self.control_slots(table),set(),table)

    def test_failed_delete_does_not_advance_page_or_commit_progress_and_restart_rescans_safely(self):
        import sqlite3
        self.seed_control(range(640))
        for slot in range(256):self.defer(slot)
        self.retire()
        writer=self.state.writer;db=self.h.db
        hints=dict(writer._retention_continuity_pages)
        pending=db.execute('SELECT * FROM candidate_pending_proofs ORDER BY id').fetchall()
        db.execute("CREATE TRIGGER fail_retention BEFORE DELETE ON stream_receipts WHEN OLD.slot=300 BEGIN SELECT RAISE(ABORT,'retention-fixture-rollback'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError,'retention-fixture-rollback'):self.retire()
        self.assertEqual(writer._retention_continuity_pages,hints)
        self.assertEqual(writer.last_retention_progress.snapshot().committed_slices,0)
        self.assertEqual(self.control_slots(),set(range(640)))
        self.assertFalse(db.in_transaction)
        db.execute('DROP TRIGGER fail_retention')
        self.retire()
        self.assertTrue(set(range(256)).issubset(self.control_slots()))
        writer.close();self.state,self.h=startup_fixture.state_at(self.path,lambda:self.now[0])
        self.assertFalse(hasattr(self.state.writer,'_retention_continuity_pages'))
        for _ in range(5):self.retire()
        for table in ('stream_receipts','stream_deliveries','stream_order'):
            self.assertEqual(self.control_slots(table),set(range(256)),table)
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_pending_proofs ORDER BY id').fetchall(),pending)

    def test_fixed_horizon_wraps_to_new_behind_cursor_work_despite_a_growing_tail(self):
        self.seed_control(range(0,1200,2))
        for slot in range(0,512,2):self.defer(slot)
        self.retire(64)
        self.seed_control((3,2000))
        for index in range(24):
            self.seed_control((2001+index,))
            self.retire(64)
        self.assertNotIn(3,self.control_slots())
        self.assertFalse(set(range(512,1200,2)) & self.control_slots())
        for table in ('stream_receipts','stream_deliveries','stream_order'):
            self.assertTrue(set(range(0,512,2)).issubset(self.control_slots(table)),table)

    def test_missing_current_startup_child_preserves_recovery_tail_until_child_advances(self):
        from meme_machine.solana_rolling_history import program_scope
        from meme_machine.solana_selective_runtime import CONTROL
        self.seed_control(range(90,111));self.begin()
        self.retire()
        self.assertEqual(self.control_slots(),set(range(100,111)))
        # Existing child publication, not time or a buffer, releases old tail.
        with self.state.writer.transaction():
            for family in ('pump','pumpswap'):
                self.h.db.execute('INSERT OR REPLACE INTO candidate_blocks '
                    '(scope,slot,parent,hash,previous_hash,market_time,seen,session,census_hash) VALUES(?,?,?,?,?,?,?,?,?)',
                    (program_scope(family),108,107,'hash:108','hash:107',int(self.now[0]),self.now[0],'native-session','fixture-census'))
        self.retire()
        self.assertEqual(self.control_slots(),{108,109,110})
        self.assertEqual(self.h.db.execute('SELECT value FROM meta WHERE key=?',('retention_floor:'+CONTROL,)).fetchone()[0],'111')

    def test_cancellation_of_protected_page_preserves_pending_work_and_can_resume(self):
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        self.seed_control(range(640))
        for slot in range(256):self.defer(slot)
        writer=self.state.writer;db=self.h.db
        pending=db.execute('SELECT * FROM candidate_pending_proofs ORDER BY id').fetchall()
        writer._retention_yield_requested=lambda:'urgent'
        with self.assertRaisesRegex(EvidenceUnavailable,'evidence_background_yield'):self.retire()
        outcome=writer.last_retention_progress.snapshot()
        self.assertTrue(outcome.interrupted)
        self.assertEqual(outcome.committed_slices,0)
        self.assertFalse(outcome.made_progress)
        self.assertEqual(self.control_slots(),set(range(640)))
        self.assertEqual(db.execute('SELECT * FROM candidate_pending_proofs ORDER BY id').fetchall(),pending)
        writer._retention_yield_requested=None
        for _ in range(5):self.retire()
        for table in ('stream_receipts','stream_deliveries','stream_order'):
            self.assertEqual(self.control_slots(table),set(range(256)),table)

    def test_legacy_adapter_without_new_proof_end_index_keeps_exact_receipt_dependencies(self):
        self.seed_control((0,10,20,30));self.defer(0,25)
        self.h.db.execute('DROP INDEX candidate_proof_end')
        self.retire()
        self.assertEqual(self.control_slots(),{0,20})

    def test_retirement_preserves_control_membership_for_current_child_and_pending_proof(self):
        """Synthetic lifecycle regression, not attribution of a retained absence."""
        from dataclasses import replace
        import json
        from meme_machine.solana_evidence_plane import IntervalProof,digest
        from meme_machine.solana_maintenance_state import PRESERVATION_SECONDS
        from meme_machine.solana_prewarm_startup import published_program_frontiers
        from meme_machine.solana_rolling_history import program_scope
        from meme_machine.solana_selective_runtime import CONTROL
        from meme_machine.solana_selective_source import commit_control
        from tests.test_candidate_commit_batches import frame

        self.current_tail()
        db=self.h.db;writer=self.state.writer
        scope=program_scope('pump')
        self.h.lifecycle.defer_proof(IntervalProof(scope,101,102,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=101,upper_slot=102,
                 lineage_hash=digest(['pending-retention-witness',101,102])),self.now[0]))
        pending=db.execute('SELECT * FROM candidate_pending_proofs ORDER BY id').fetchall()
        blocks=db.execute('SELECT * FROM candidate_blocks ORDER BY scope').fetchall()
        # A closed old unresolved gap keeps the global prefix floor low. The
        # real suffix selector may still retire expired continuity above it.
        writer.gap(CONTROL,90,90,'retained_old_control_gap')
        self.now[0]+=600
        # CONTROL advances naturally while the candidate's last linked child
        # remains103; preserve each original block time and availability.
        for slot in (105,106):
            update=frame(slot,logs=False)
            update.update.block.block_time.timestamp=int(self.now[0])
            commit_control(self.state,replace(update,seen=self.now[0]))
        before=published_program_frontiers(db,now=self.now[0])
        self.assertEqual(len(before),2)
        self.assertEqual({row['linked_child_slot'] for row in before},{103})
        required={slot:db.execute('SELECT parent,hash,previous_hash,sealed FROM stream_receipts '
            'WHERE scope=? AND slot=?',(CONTROL,slot)).fetchone() for slot in (101,102,103)}
        self.assertTrue(all(value is not None and value[3]==1 for value in required.values()))
        cutoff=self.now[0]-PRESERVATION_SECONDS
        self.assertEqual(db.execute('SELECT MAX(hi) FROM coverage WHERE scope=?',(CONTROL,)).fetchone()[0],105)
        writer.retain(cutoff,max_records=256,archive_first=False,checkpoint=False)
        after=published_program_frontiers(db,now=self.now[0])
        retained={slot:db.execute('SELECT parent,hash,previous_hash,sealed FROM stream_receipts '
            'WHERE scope=? AND slot=?',(CONTROL,slot)).fetchone() for slot in required}
        print('CONTROL_MEMBERSHIP_RETIREMENT '+json.dumps(dict(
            required_slots=list(required),retained_slots=[slot for slot,value in retained.items() if value is not None],
            publication_rows_before=len(before),publication_rows_after=len(after),
            continuity_rows=writer.last_retention_progress.continuity_rows),sort_keys=True))
        self.assertGreater(writer.last_retention_progress.continuity_rows,0)
        self.assertIsNone(db.execute('SELECT 1 FROM stream_receipts WHERE scope=? AND slot=100',(CONTROL,)).fetchone(),
            'unreferenced expired CONTROL continuity should still be eligible for retirement')
        self.assertEqual(db.execute('SELECT * FROM candidate_blocks ORDER BY scope').fetchall(),blocks)
        self.assertEqual(db.execute('SELECT * FROM candidate_pending_proofs ORDER BY id').fetchall(),pending)
        self.assertEqual(retained,required,
            'retirement removed CONTROL membership still required by the current child or pending proof')
        self.assertEqual(after,before,'retirement made an already proved candidate tail unpublishable')
