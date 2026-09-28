"""The new recovery gate rejects debt growth even when old cohorts disappear."""
from copy import deepcopy
import unittest
from certification.cleanup_recovery import recovery_assessment, frozen_inputs, sql_phase


def samples():
    rows=[]
    for second in range(180,1201,5):
        debt=128; cohorts={}
        for burst in (216,378):
            if burst+10<=second<burst+40:debt=2000-(second-burst-10)*30
            if second>=burst+10:
                cohorts[str(burst)]=dict(initial=1024,source_frames=int((burst+10)/.27),
                    captured_at=burst+10,cutoff_slot=int((burst+10)/.27)+1000,
                    remaining=1024 if second<burst+40 else 0)
        rows.append(dict(source_frames=int(second/.27),source_seconds=second,
            active_pins=0,unresolved_gaps=0,cohorts=cohorts,
            scopes={'program:meteora':dict(archived_pending=debt)}))
    return rows


class CleanupRecoveryTests(unittest.TestCase):
    def test_frozen_original_and_combined_workload_bytes(self):
        self.assertTrue(frozen_inputs())

    def test_actual_clearance_and_stable_tail_pass(self):
        row=recovery_assessment(samples())
        self.assertTrue(row['passed'],row)
        self.assertTrue(all(e['source_frames_during_clearance']>0 for e in row['episodes']))

    def test_cohort_clearance_does_not_hide_growing_aggregate_debt(self):
        rows=samples()
        for r in rows:
            if r['source_seconds']>245:r['scopes']['program:meteora']['archived_pending']=int((r['source_seconds']-245)*50)
        row=recovery_assessment(rows)
        self.assertFalse(row['passed'])
        self.assertIn('cleanup_did_not_recover:216',row['failures'])

    def test_late_debt_growth_fails_even_after_both_bursts_recovered(self):
        rows=samples()
        for r in rows:
            if r['source_seconds']>960:r['scopes']['program:meteora']['archived_pending']=int((r['source_seconds']-960)*10)
        row=recovery_assessment(rows)
        self.assertFalse(row['passed'])
        self.assertIn('sustained_cleanup_debt_growth_or_missing_tail',row['failures'])

    def test_never_cleared_cohort_fails(self):
        rows=samples()
        for r in rows:
            for c in r['cohorts'].values():c['remaining']=1
        self.assertFalse(recovery_assessment(rows)['passed'])

    def test_source_stop_and_missing_observations_cannot_prove_recovery(self):
        rows=samples()
        for r in rows:
            if r['source_seconds']>390:r['source_frames']=int(390/.27)
        self.assertFalse(recovery_assessment(rows)['passed'])
        self.assertFalse(recovery_assessment(samples()[:50])['passed'])
        self.assertFalse(recovery_assessment(samples(),['reader_failed'])['passed'])

    def test_cohort_refill_and_source_regression_fail(self):
        rows=samples(); key='216'
        row=next(r for r in rows if r['source_seconds']>=280)
        row['cohorts'][key]['remaining']=100
        self.assertFalse(recovery_assessment(rows)['passed'])
        rows=samples(); rows[20]['source_frames']=0
        self.assertFalse(recovery_assessment(rows)['passed'])

    def test_phase_classifier_preserves_commit_and_does_not_log_values(self):
        native=lambda sql:'commit' if sql=='COMMIT' else None
        self.assertEqual(sql_phase('COMMIT',native),'commit')
        self.assertEqual(sql_phase('SELECT MIN(slot) FROM records WHERE scope=? AND body IS NOT NULL',native),'retention_hot_boundary')
        self.assertEqual(sql_phase('DELETE FROM records WHERE identity IN (?)',native),'retention_records')
        self.assertIsNone(sql_phase('INSERT INTO records VALUES(secret)',native))


if __name__=='__main__':unittest.main()
