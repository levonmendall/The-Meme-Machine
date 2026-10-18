"""Stage completion requires exact independently sealed native work membership."""
import unittest
from unittest.mock import patch

from meme_machine.runtime.economic_cohort import checksum
from meme_machine.runtime.native_work_cohort import NativeWorkCohorts


class NativeWorkCohortTests(unittest.TestCase):
    def meter(self,stage='NATIVE_EVALUATION'):
        return NativeWorkCohorts(dict(owner_pid=123,owner_instance='a'*32,regime='current'),stage)

    def begin(self,meter,rows):
        cid=checksum('cohort');meter.begin(cid,checksum('native-frontier'))
        meter.expect(cid,rows);return cid

    def seal(self,meter,cid,rows):
        meter.seal_expected(cid,len(rows),checksum(tuple(sorted(rows))),checksum('original-complete-traversal'))

    def test_actual_outcomes_need_complete_seal_and_native_receipt(self):
        meter=self.meter();rows=((checksum('request'),checksum('actual-input')),)
        cid=self.begin(meter,rows)
        meter.observe(cid,((*rows[0],'DECISION_COMMITTED',checksum('actual-decision-id'),None),))
        self.assertEqual(meter.snapshot()['completed_cohorts'],0)
        self.seal(meter,cid,rows);result=meter.snapshot()
        self.assertEqual(result['completed_cohorts'],1)
        self.assertEqual(result['closed'][0]['committed_units'],1)
        self.assertEqual(result['closed'][0]['expected_sha256'],checksum(rows))
        self.assertFalse(result['readiness_authority']);self.assertFalse(result['funding_authority'])

    def test_missing_whole_expectation_and_receipt_cannot_close_smaller_census(self):
        rows=((checksum('request'),checksum('input')),)
        for missing in ('expect','receipt'):
            meter=self.meter();cid=checksum('cohort');meter.begin(cid,checksum('frontier'))
            if missing!='expect':meter.expect(cid,rows)
            if missing=='receipt':meter.observe(cid,((*rows[0],'DECISION_COMMITTED',None,None),))
            self.seal(meter,cid,rows)
            self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
            self.assertEqual(meter.snapshot()['completed_cohorts'],0)

    def test_deferred_or_incomplete_work_remains_pending_until_actual_retry_completion(self):
        for disposition,due in (('DEFERRED',12345),('INCOMPLETE',None),('MISSING_HISTORY',None)):
            meter=self.meter();rows=((checksum('request'),checksum('input')),)
            cid=self.begin(meter,rows);self.seal(meter,cid,rows)
            meter.observe(cid,((*rows[0],disposition,None,due),))
            self.assertEqual(meter.snapshot()['pending_units'],1)
            self.assertEqual(meter.snapshot()['completed_cohorts'],0)
            meter.observe(cid,((*rows[0],'DECISION_COMMITTED',checksum('real-receipt'),None),))
            self.assertEqual(meter.snapshot()['completed_cohorts'],1)

    def test_policy_coalescing_has_explicit_due_clock_and_never_counts_as_evaluation(self):
        meter=self.meter('DISCOVERY_INPUT');rows=((checksum('input-id'),checksum('content')),)
        cid=self.begin(meter,rows);self.seal(meter,cid,rows)
        meter.observe(cid,((*rows[0],'COALESCED_NOT_DUE',None,5005),))
        result=meter.snapshot();self.assertEqual(result['completed_cohorts'],1)
        self.assertEqual(result['closed'][0]['committed_units'],0)
        self.assertEqual(result['closed'][0]['dispositions'],{'COALESCED_NOT_DUE':1})
        wrong=self.meter();cid=self.begin(wrong,rows)
        wrong.observe(cid,((*rows[0],'COALESCED_NOT_DUE',None,5005),))
        self.assertEqual(wrong.snapshot()['state'],'UNKNOWN')

    def test_sealed_expected_population_cannot_expand_while_commit_is_pending(self):
        meter=self.meter();rows=((checksum('A'),checksum('input-A')),)
        cid=self.begin(meter,rows);self.seal(meter,cid,rows)
        meter.expect(cid,((checksum('B'),checksum('input-B')),))
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
        self.assertEqual(meter.snapshot()['expected_units'],1)
        self.assertEqual(meter.snapshot()['completed_cohorts'],0)

    def test_exact_duplicates_are_idempotent_but_crossed_input_or_receipt_refuses(self):
        rows=((checksum('request'),checksum('input')),)
        meter=self.meter();cid=self.begin(meter,rows);meter.expect(cid,rows)
        outcome=(*rows[0],'DECISION_COMMITTED',checksum('receipt'),None)
        meter.observe(cid,(outcome,));meter.observe(cid,(outcome,))
        self.assertEqual(meter.snapshot()['expected_units'],1)
        meter.observe(cid,((rows[0][0],checksum('other'),'DECISION_COMMITTED',checksum('receipt'),None),))
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')

    def test_explicit_zero_complete_native_traversal_is_stage_only_not_empty_market(self):
        meter=self.meter('DISCOVERY_INPUT');cid=self.begin(meter,())
        self.assertEqual(meter.snapshot()['completed_cohorts'],0)
        self.seal(meter,cid,());result=meter.snapshot()
        self.assertEqual(result['completed_cohorts'],1)
        self.assertIn('NOT_SOURCE_OR_ALL_CONSUMER',result['contract'])
        self.assertIn('UNKNOWN',result['full_market_rate'])

    def test_bounds_bad_container_contention_and_clock_failure_are_unknown(self):
        meter=self.meter();rows=((checksum('request'),checksum('input')),)
        cid=self.begin(meter,rows)
        with patch('meme_machine.runtime.native_work_cohort.MAX_UNITS',1):
            meter.expect(cid,((checksum('next'),checksum('content')),))
        self.assertEqual(meter.snapshot()['reason'],'BOUND')
        meter=self.meter();cid=checksum('cohort');meter.begin(cid,checksum('frontier'))
        meter.expect(cid,iter(rows));self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
        meter=self.meter();meter.lock.acquire()
        try:meter.begin(cid,checksum('frontier'))
        finally:meter.lock.release()
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
        meter=NativeWorkCohorts(dict(owner_pid=123),'NATIVE_EVALUATION',clock=lambda:float('nan'))
        meter.begin(cid,checksum('frontier'));self.assertEqual(meter.snapshot()['state'],'UNKNOWN')

    def test_snapshot_is_detached_and_foreign_cohort_or_reopen_refuses(self):
        meter=self.meter();rows=((checksum('request'),checksum('input')),)
        cid=self.begin(meter,rows);self.seal(meter,cid,rows)
        meter.observe(cid,((*rows[0],'DECISION_COMMITTED',checksum('receipt'),None),))
        result=meter.snapshot();result['closed'][0]['dispositions'].clear()
        self.assertEqual(meter.snapshot()['closed'][0]['dispositions'],{'DECISION_COMMITTED':1})
        meter.begin(cid,checksum('native-frontier'));self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
