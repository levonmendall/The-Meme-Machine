"""Bound observational evidence without changing economic state or claiming gaps."""
import json,sqlite3,unittest
from unittest.mock import patch
from tests.test_opportunity_telemetry import OpportunityTelemetryTests
from meme_machine.runtime import opportunity_telemetry as telemetry

class OpportunityRetentionTests(OpportunityTelemetryTests):
    # Reuse the native fixtures; the original eight cases remain in their gate.
    def test_prefix_preserves_counts_hash_restart_and_native_state(self):
        before=self.financial()
        with patch.object(telemetry,'MAX_JOURNAL_ROWS',16):
            for at in range(100,180):self.reject(at=at)
            proof=telemetry.verify(self.sleeve.db)
            self.assertEqual(proof['receipts'],80)
            self.assertEqual(self.sleeve.db.execute('SELECT COUNT(*) FROM opportunity_journal_v1').fetchone()[0],16)
            self.sleeve.close();self.sleeve=self.open()
            self.assertEqual(telemetry.verify(self.sleeve.db),proof)
        self.assertEqual(self.financial(),before)
        with self.assertRaises(sqlite3.IntegrityError):self.sleeve.db.execute('DELETE FROM opportunity_journal_v1')

    def test_lost_evidence_never_claims_complete_outcomes_or_winner_returns(self):
        self.reject()
        with patch.object(telemetry,'MAX_JOURNAL_ROWS',4),self.sleeve.transaction():
            telemetry.observe_prices(self.sleeve.db,'pons','pons:token',
                [dict(at=at,price=at*10**18) for at in range(101,121)],source_hash='persisted')
            telemetry.enrich(self.sleeve.db,now=400)
        body=self.bodies('outcome')[-1]
        self.assertEqual(body['observability'],'RETAINED_EVIDENCE_INCOMPLETE')
        self.assertFalse(body['evidence_retention_complete'])
        for key in ('maximum_favorable_excursion_bps','maximum_adverse_excursion_bps','terminal_or_last_observable_return_bps'):
            self.assertIsNone(body[key])
        self.assertFalse(body['qualification_authority']);self.assertFalse(body['order_authority'])
        self.assertIsNone(body['survivor_fill_committed'])

    def test_production_limit_retains_chain_counts_after_old_state_drain(self):
        before=self.financial()
        with patch.object(telemetry,'retain'),self.sleeve.transaction():
            for at in range(6000):
                telemetry.append(self.sleeve.db,'old:'+str(at),'link','pons:old',at,
                    dict(regime='current',status='rejected',qualification_authority=False,order_authority=False))
        proof=telemetry.verify(self.sleeve.db)
        for _ in range(8):
            with self.sleeve.transaction():telemetry.retain(self.sleeve.db)
        self.assertEqual(self.sleeve.db.execute('SELECT COUNT(*) FROM opportunity_journal_v1').fetchone()[0],4096)
        self.assertEqual(proof,telemetry.verify(self.sleeve.db));self.assertEqual(before,self.financial())

    def test_target_and_orphan_scan_population_is_bounded_with_explicit_loss(self):
        with patch.object(telemetry,'MAX_OUTCOME_TARGETS',4):
            for at in range(100,130):self.reject(at=at)
            self.assertEqual(self.sleeve.db.execute('SELECT COUNT(*) FROM opportunity_targets_v1').fetchone()[0],4)
            self.assertEqual(int(self.sleeve.db.execute("SELECT value FROM opportunity_meta_v1 WHERE key='unobserved_retired_targets'").fetchone()[0]),26)
            with self.sleeve.transaction():
                self.sleeve.db.execute('INSERT INTO opportunity_scans_v1 VALUES(?,?)',(json.dumps(['retired',0]),'{}'))
                telemetry.retain(self.sleeve.db)
            self.assertEqual(self.sleeve.db.execute('SELECT COUNT(*) FROM opportunity_scans_v1').fetchone()[0],0)

    def test_interrupted_delete_rolls_back_prefix_rows_and_immutable_trigger(self):
        with patch.object(telemetry,'retain'):
            for at in range(100,110):self.reject(at=at)
        proof=telemetry.verify(self.sleeve.db);before=self.financial();db=self.sleeve.db
        class Interrupted:
            in_transaction=True
            def execute(self,sql,*args):
                if sql.startswith('DELETE FROM opportunity_journal_v1'):raise SystemExit('retention interruption')
                return db.execute(sql,*args)
        with patch.object(telemetry,'MAX_JOURNAL_ROWS',4),self.assertRaises(SystemExit),self.sleeve.transaction():
            telemetry.retain(Interrupted())
        self.assertEqual(proof,telemetry.verify(db));self.assertEqual(before,self.financial())
        with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM opportunity_journal_v1')

    def test_old_large_journal_converges_in_bounded_restart_slices(self):
        with patch.object(telemetry,'retain'):
            for at in range(100,300):self.reject(at=at)
        proof=telemetry.verify(self.sleeve.db);before=self.financial()
        with patch.object(telemetry,'MAX_JOURNAL_ROWS',16),patch.object(telemetry,'MAX_RETIRE_SLICE',32):
            previous=self.sleeve.db.execute('SELECT COUNT(*) FROM opportunity_journal_v1').fetchone()[0]
            for _ in range(20):
                self.sleeve.close();self.sleeve=self.open()
                current=self.sleeve.db.execute('SELECT COUNT(*) FROM opportunity_journal_v1').fetchone()[0]
                self.assertLessEqual(previous-current,32);self.assertLessEqual(current,previous)
                self.assertEqual(telemetry.verify(self.sleeve.db),proof)
                self.assertEqual(before,self.financial());previous=current
                if current==16:break
            self.assertEqual(current,16)
        raw=self.sleeve.db.execute("SELECT value FROM opportunity_meta_v1 WHERE key='journal_prefix'").fetchone()[0]
        value=json.loads(raw);value['maximum_at']=9999
        self.sleeve.db.execute("UPDATE opportunity_meta_v1 SET value=? WHERE key='journal_prefix'",(json.dumps(value),))
        with self.assertRaisesRegex(ValueError,'prefix_corruption'):telemetry.verify(self.sleeve.db)

# Avoid duplicate collection of the imported fixture class and inherited tests.
for _name in tuple(vars(OpportunityTelemetryTests)):
    if _name.startswith('test_'):setattr(OpportunityRetentionTests,_name,None)
del OpportunityTelemetryTests
