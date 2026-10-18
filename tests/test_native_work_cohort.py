"""Stage completion requires exact independently sealed native work membership."""
import unittest
from unittest.mock import patch

from meme_machine.runtime.economic_cohort import checksum
from meme_machine.runtime.native_work_cohort import NativeWorkCohorts, project_native_work


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

    def test_incomplete_outcomes_do_not_rehash_full_census_but_closure_verifies_it(self):
        from meme_machine.runtime import native_work_cohort as module
        meter=self.meter('DISCOVERY_INPUT')
        rows=tuple(sorted((checksum(['key',n]),checksum(['input',n])) for n in range(128)))
        cid=self.begin(meter,rows);self.seal(meter,cid,rows)
        census_hashes=[];original=module.checksum
        def hashed(value):
            if value==rows:census_hashes.append(True)
            return original(value)
        with patch.object(module,'checksum',side_effect=hashed):
            for item in rows[:-1]:meter.observe(cid,((*item,'POLICY_FILTERED',None,None),))
            self.assertEqual(census_hashes,[])
            self.assertEqual(meter.completed,0)
            meter.observe(cid,((*rows[-1],'POLICY_FILTERED',None,None),))
        self.assertTrue(census_hashes)
        self.assertEqual(meter.snapshot()['completed_cohorts'],1)
        # Fault injection in retained internal memory must still fail final
        # membership verification, even when its member count is unchanged.
        other=self.meter('DISCOVERY_INPUT');cid=self.begin(other,rows);self.seal(other,cid,rows)
        key=rows[0][0];other.active[cid]['expected'][key]=checksum('changed-retained-input')
        changed=tuple(sorted(other.active[cid]['expected'].items()))
        other.observe(cid,tuple((*item,'POLICY_FILTERED',None,None) for item in changed))
        self.assertEqual(other.snapshot()['state'],'UNKNOWN')
        self.assertEqual(other.snapshot()['completed_cohorts'],0)

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
        clocks=iter((10,9))
        meter=NativeWorkCohorts(dict(owner_pid=123),'NATIVE_EVALUATION',clock=lambda:next(clocks))
        cid=self.begin(meter,rows)
        meter.observe(cid,((*rows[0],'DECISION_COMMITTED',checksum('receipt'),None),))
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')

    def test_snapshot_is_detached_and_foreign_cohort_or_reopen_refuses(self):
        meter=self.meter();rows=((checksum('request'),checksum('input')),)
        cid=self.begin(meter,rows);self.seal(meter,cid,rows)
        meter.observe(cid,((*rows[0],'DECISION_COMMITTED',checksum('receipt'),None),))
        result=meter.snapshot();result['closed'][0]['dispositions'].clear()
        self.assertEqual(meter.snapshot()['closed'][0]['dispositions'],{'DECISION_COMMITTED':1})
        meter.begin(cid,checksum('native-frontier'));self.assertEqual(meter.snapshot()['state'],'UNKNOWN')

    def test_fixed_projection_keeps_complete_counts_chain_and_explicit_sample_omissions(self):
        meter=self.meter()
        for number in range(10):
            cid=checksum(['cohort',number]);rows=((checksum(['request',number]),checksum('input')),)
            meter.begin(cid,checksum(['frontier',number]));meter.expect(cid,rows)
            self.seal(meter,cid,rows)
            meter.observe(cid,((*rows[0],'DECISION_COMMITTED',checksum(['receipt',number]),None),))
        raw=meter.snapshot();raw['private_provider']='https://private.invalid/token'
        result=project_native_work(raw)
        self.assertEqual(result['completed_cohorts'],10)
        self.assertEqual(result['cumulative_summary_sha256'],raw['cumulative_summary_sha256'])
        self.assertEqual(len(result['closed']),4);self.assertEqual(result['closed_samples_omitted'],6)
        self.assertNotIn('private',str(result));self.assertEqual(project_native_work(result),result)
        closed=raw['closed'][0];original=dict(closed['dispositions']);committed=closed['committed_units']
        for pending in ('INCOMPLETE','DEFERRED','MISSING_HISTORY'):
            closed['dispositions']={pending:1};closed['committed_units']=0
            self.assertEqual(project_native_work(raw)['state'],'UNKNOWN')
        closed['dispositions']=original;closed['committed_units']=committed
        raw['closed'][0]['expected_units']=99
        self.assertEqual(project_native_work(raw)['state'],'UNKNOWN')
