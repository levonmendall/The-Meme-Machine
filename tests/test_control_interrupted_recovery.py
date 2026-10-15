"""Disposable CONTROL receipts: reauthentication is not historical completion.

These are fault-injected correctness fixtures, not provider capability tests,
production recovery, authentic market replay, or throughput measurements.
"""
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_plane import EvidenceConflict,EvidenceUnavailable,EvidenceWriter,IntervalProof,digest
from meme_machine.solana_evidence_service import FinalizedFence,STREAM_CONTROL_REAUTH_MAX_RECEIPTS
from meme_machine.solana_evidence_transport import Subscription
from meme_machine.solana_selective_runtime import CONTROL
from meme_machine.solana_source_drain import CONTROL_RECOVERY_KEY,preserve_control_recovery,complete_control_recovery,control_recovery


class InterruptedControlRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=1000.;self.path=Path(self.tmp.name)/'canonical.sqlite'
        self.state=None;self.open()
        self.addCleanup(lambda:self.state.writer.close())

    def open(self):
        writer=EvidenceWriter(self.path,clock=lambda:self.now)
        self.state=SimpleNamespace(writer=writer,fence=FinalizedFence(writer,endpoint_identity='a'*64))

    def restart(self):
        self.state.writer.close();self.now+=1;self.open()

    def message(self,slot,*,parent=None,previous_hash=None,blockhash=None,market_time=900):
        parent=slot-1 if parent is None else parent
        return dict(method='blockNotification',params=dict(result=dict(value=dict(slot=slot,err=None,
            block=dict(parentSlot=parent,blockhash=blockhash or 'block-'+str(slot),
                previousBlockhash=previous_hash or 'block-'+str(parent),blockTime=market_time,transactions=[])))))

    def commit(self,slot,*,message=None,signatures=()):
        message=self.message(slot) if message is None else message
        prepared=dict(endpoint_identity=self.state.fence.endpoint_identity,observed_at=self.now,
            slot=slot,signatures=list(signatures),batches=[],deliveries=[])
        with self.state.writer.source_frame():
            self.state.fence.block(Subscription('source',CONTROL,'control','census',2),message,self.now,prepared=prepared)

    def retain_unsealed(self,*slots):
        # Reproduce the persisted header / not-yet-sealed lifecycle boundary.
        # Receipt insertion, immutable checks and transaction ownership stay real.
        with patch.object(self.state.fence,'seal',return_value=None):
            for slot in slots:self.commit(slot)

    def immutable(self):
        return self.state.writer.db.execute('''SELECT scope,slot,parent,hash,previous_hash,
            market_time,census,session,seen FROM stream_receipts ORDER BY scope,slot''').fetchall()

    def coverage(self):
        return self.state.writer.db.execute('SELECT lo,hi FROM coverage WHERE scope=? ORDER BY id',(CONTROL,)).fetchall()

    def required(self):
        row=self.state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(CONTROL_RECOVERY_KEY,)).fetchone()
        return control_recovery(None if row is None else row[0])

    def test_identical_replay_reauthenticates_both_old_receipts_without_rewriting_origin(self):
        self.retain_unsealed(100,101);original=self.immutable();old_session=self.state.fence.session
        self.restart();current=self.state.fence.session
        self.assertNotEqual(current,old_session)
        self.commit(100)
        self.assertEqual(self.coverage(),[])
        self.assertEqual(self.state.writer.db.execute('SELECT slot,sealed FROM stream_receipts ORDER BY slot').fetchall(),[(100,0),(101,0)])
        self.now+=1;self.commit(101)
        self.assertEqual(self.coverage(),[(100,100)])
        self.assertEqual(self.immutable(),original)
        raw,available=self.state.writer.db.execute('SELECT proof,available FROM coverage').fetchone()
        proof=json.loads(raw);witness=proof['witness']
        self.assertEqual((proof['source'],proof['endpoint_identity']),('alchemy_finalized_stream','a'*64))
        self.assertEqual((witness['parent_blockhash'],witness['child_blockhash'],witness['child_slot']),('block-100','block-101',101))
        self.assertEqual(witness['replayed_receipts'],dict(authenticated_session=current,
            parent_session=old_session,child_session=old_session,parent_observed_at=1001.,child_observed_at=1002.))
        self.assertEqual(available,1002.)
        self.assertEqual(self.state.writer.db.execute('SELECT slot,sealed FROM stream_receipts ORDER BY slot').fetchall(),[(100,1),(101,0)])

    def test_fresh_child_cannot_seal_unreplayed_old_parent(self):
        self.retain_unsealed(100);original=self.immutable()
        self.restart();self.commit(101)
        self.assertEqual(self.coverage(),[])
        self.commit(100)
        self.assertEqual(self.coverage(),[(100,100)])
        self.assertEqual(self.immutable()[0],original[0])

    def test_replayed_child_before_parent_requires_exact_current_parent_authentication(self):
        self.retain_unsealed(100,101);self.restart()
        self.commit(101);self.assertEqual(self.coverage(),[])
        self.commit(100);self.assertEqual(self.coverage(),[(100,100)])

    def test_disconnect_discards_ephemeral_eligibility_and_requires_both_receipts_again(self):
        self.retain_unsealed(100,101);self.restart();self.commit(100)
        prior=self.state.fence.session;self.state.fence.disconnect('offline_transport_replacement')
        self.assertNotEqual(self.state.fence.session,prior)
        self.commit(101);self.assertEqual(self.coverage(),[])
        self.commit(100);self.assertEqual(self.coverage(),[(100,100)])

    def test_every_immutable_receipt_field_still_conflicts_before_eligibility(self):
        for field,value in (('parentSlot',98),('blockhash','different'),
                ('previousBlockhash','different'),('blockTime',899),('census',['unexpected'])):
            with self.subTest(field=field):
                self.state.writer.close();self.path=Path(self.tmp.name)/(field+'.sqlite');self.open()
                self.retain_unsealed(100,101);original=self.immutable();self.restart()
                message=self.message(100);signatures=()
                if field=='census':signatures=value
                else:message['params']['result']['value']['block'][field]=value
                with self.assertRaisesRegex(EvidenceConflict,'conflicting_finalized_block_receipt'):
                    self.commit(100,message=message,signatures=signatures)
                self.assertEqual(self.immutable(),original)
                self.assertEqual(self.coverage(),[])
                self.assertEqual(self.state.fence._control_reauthenticated,{})

    def test_old_coverage_and_future_head_do_not_clear_marker_but_new_contiguous_proofs_do(self):
        self.retain_unsealed(100,101,102)
        witness=dict(finalized=True,complete=True,scope=CONTROL,lower_slot=100,upper_slot=101,
            lineage_hash=digest(['retained-proof',100,101]))
        self.state.writer.ingest([],proof=IntervalProof(CONTROL,100,101,'alchemy_finalized_stream','a'*64,witness,self.now))
        required=preserve_control_recovery(self.state,100,101)
        self.assertEqual(required['coverage_after_id'],1)
        self.restart();self.assertEqual(complete_control_recovery(self.state,CONTROL),required)
        self.commit(1500);self.commit(1501)
        self.assertEqual(complete_control_recovery(self.state,CONTROL),required)
        self.commit(100);self.assertEqual(complete_control_recovery(self.state,CONTROL),required)
        self.commit(101)
        partial=complete_control_recovery(self.state,CONTROL)
        self.assertEqual(partial,dict(required,lower_slot=101))
        self.commit(102)
        self.assertIsNone(complete_control_recovery(self.state,CONTROL))
        self.assertIsNone(self.required())
        # A new proof of 100..101 does not claim the intervening 103..1499 gap.
        self.assertIsNotNone(self.state.writer.db.execute('SELECT 1 FROM gaps WHERE scope=? AND repaired IS NULL',(CONTROL,)).fetchone())

    def test_interrupted_canonical_commit_rolls_back_proof_seal_and_marker_then_restart_reauthenticates(self):
        self.retain_unsealed(100,101);required=preserve_control_recovery(self.state,100,100)
        original=self.immutable();self.restart();self.commit(100)
        with self.assertRaisesRegex(sqlite3.OperationalError,'original_commit_interruption'):
            with self.state.writer.transaction():
                self.commit(101)
                complete_control_recovery(self.state,CONTROL)
                raise sqlite3.OperationalError('original_commit_interruption')
        self.assertEqual(self.coverage(),[])
        self.assertEqual(self.required(),required)
        self.assertEqual(self.immutable(),original)
        self.assertEqual(self.state.writer.db.execute('SELECT sealed FROM stream_receipts ORDER BY slot').fetchall(),[(0,),(0,)])
        self.restart();self.commit(101)
        self.assertEqual(self.coverage(),[]);self.assertEqual(self.required(),required)
        self.commit(100);self.assertIsNone(complete_control_recovery(self.state,CONTROL))

    def test_parent_hash_mismatch_remains_a_conflict_and_does_not_clear_recovery(self):
        self.retain_unsealed(100)
        with patch.object(self.state.fence,'seal',return_value=None):
            self.commit(101,message=self.message(101,previous_hash='other-parent'))
        required=preserve_control_recovery(self.state,100,100);self.restart();self.commit(100)
        with self.assertRaisesRegex(EvidenceConflict,'finalized_parent_hash_mismatch'):
            self.commit(101,message=self.message(101,previous_hash='other-parent'))
        self.assertEqual(self.coverage(),[]);self.assertEqual(self.required(),required)

    def test_actual_sqlite_proof_failure_preserves_original_error_and_exact_pending_marker(self):
        self.retain_unsealed(100,101);original=self.immutable()
        required=preserve_control_recovery(self.state,100,100);self.restart();self.commit(100)
        self.state.writer.db.execute('''CREATE TEMP TRIGGER reject_control_proof BEFORE INSERT ON coverage
            WHEN NEW.scope='control:solana' BEGIN SELECT RAISE(ABORT,'original_control_proof_write_failure'); END''')
        with self.assertRaisesRegex(sqlite3.IntegrityError,'original_control_proof_write_failure'):
            self.commit(101)
        self.assertEqual(self.immutable(),original);self.assertEqual(self.coverage(),[])
        self.assertEqual(self.required(),required)
        self.assertEqual(self.state.writer.db.execute('SELECT sealed FROM stream_receipts ORDER BY slot').fetchall(),[(0,),(0,)])
        self.state.writer.db.execute('DROP TRIGGER reject_control_proof')
        self.commit(101)
        self.assertIsNone(complete_control_recovery(self.state,CONTROL))

    def test_capacity_fails_closed_without_expiring_receipts_or_coverage(self):
        from meme_machine.solana_selective_source import REPLAY_SLOTS,CONTROL_OVERLAP
        self.assertEqual(STREAM_CONTROL_REAUTH_MAX_RECEIPTS,REPLAY_SLOTS+CONTROL_OVERLAP+1)
        self.retain_unsealed(100,101);original=self.immutable()
        required=preserve_control_recovery(self.state,100,100);self.restart()
        with patch('meme_machine.solana_evidence_service.STREAM_CONTROL_REAUTH_MAX_RECEIPTS',1):
            self.commit(100)
            with self.assertRaisesRegex(EvidenceUnavailable,'control_reauthentication_capacity'):self.commit(101)
        self.assertEqual(self.immutable(),original);self.assertEqual(self.coverage(),[])
        self.assertEqual(self.required(),required)

    def test_reauthentication_does_not_extend_to_economic_program_receipt_sessions(self):
        sub=Subscription('source','program:pump','program','census',2)
        for slot in (100,101):
            with patch.object(self.state.fence,'seal',return_value=None):
                self.state.fence.block(sub,self.message(slot),self.now)
        self.restart()
        for slot in (100,101):self.state.fence.block(sub,self.message(slot),self.now)
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM coverage').fetchone()[0],0)
        self.assertEqual(self.state.fence._control_reauthenticated,{})
