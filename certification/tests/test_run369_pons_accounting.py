"""Minimized Run 369 accounting regressions; no provider transports."""
import unittest
from certification.causal import transition

class CausalGenerationTests(unittest.TestCase):
    def state(self):return dict(status='observed',evidence='not_yet_required',required=False)
    def test_rejection_then_new_discovery_is_current_observation(self):
        state=transition(self.state(),'rejected','frozen_gate','strategy_rejection',{'candidate_generation':1})
        state=transition(state,'discovered',None,None,{'candidate_generation':2})
        self.assertEqual(state['status'],'observed')
    def test_rejection_then_new_queue_is_unresolved(self):
        state=transition(self.state(),'rejected','frozen_gate','strategy_rejection',{})
        state=transition(state,'current_state_queued',None,None,{})
        self.assertEqual(state['status'],'observed')

    def test_same_generation_redelivery_does_not_erase_its_decision(self):
        s=transition(self.state(),'rejected','frozen_gate','strategy_rejection',{'candidate_generation':1})
        s=transition(s,'discovered',None,None,{'candidate_generation':1})
        self.assertEqual(s['status'],'valid_early_rejection')

    def test_new_generation_complete_then_rejected_and_old_result_fenced(self):
        s=transition(self.state(),'rejected','first','strategy_rejection',{'candidate_generation':1})
        s=transition(s,'evidence_complete',None,None,{'candidate_generation':2})
        self.assertEqual(s['status'],'evidence_completed')
        s=transition(s,'rejected','last','strategy_rejection',{'candidate_generation':2})
        self.assertEqual(s['last_reason'],'last')
        old=transition(s,'evidence_complete',None,None,{'candidate_generation':1})
        self.assertEqual(old['status'],'valid_early_rejection')
        self.assertEqual(old['last_reason'],'last')

    def test_explicit_authenticated_immutable_exclusion_survives(self):
        proof=fixture()['deferrals'][1]['immutable_proof']
        s=transition(self.state(),'rejected','non_native_quote','structural_ineligible',{'authenticated_evidence':proof,'candidate_generation':1})
        s=transition(s,'discovered',None,None,{'candidate_generation':2})
        self.assertEqual(s['status'],'structural_exclusion')
        # A generic structural reason is not a durable proof of immutability.
        s=transition(self.state(),'rejected','temporary_scope','structural_ineligible',{})
        s=transition(s,'discovered',None,None,{})
        self.assertEqual(s['status'],'observed')

    def test_ramses_strategy_rejection_and_native_lifecycle_stay_distinct(self):
        s=self.state()
        for stage,classification in [('discovered',None),('evidence_complete',None),('rejected','strategy_rejection')]:
            s=transition(s,stage,'frozen_ramses_gate',classification,{})
        self.assertEqual(s['status'],'valid_early_rejection')
        self.assertEqual(s['evidence'],'evidence_completed')
        s=transition(s,'entry_filled',None,None,{})
        s=transition(s,'discovered',None,None,{'candidate_generation':2})
        self.assertEqual(s['status'],'entry_filled')

import json
from pathlib import Path
import sqlite3
import tempfile
from certification.robinhood.accounting import classify, consistency
from certification.robinhood.plane import Plane
from certification.causal import reconcile
from certification.market_assurance import pipeline, lane_report, native_positions


def fixture():
    return json.loads(Path(__file__).resolve().parents[1].joinpath('evidence/run369-pons-accounting.json').read_text())


class AssuranceAccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.plane=Plane(self.root/'plane.sqlite',clock=lambda:100.)
        self.addCleanup(self.plane.close)
        self.path=self.root/'opportunity-pipeline.sqlite'
        self.db=sqlite3.connect(self.path);self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE progress(sequence INTEGER PRIMARY KEY,lane TEXT,candidate TEXT,stage TEXT,reason TEXT,classification TEXT,at REAL,details TEXT)')
    def observe(self,key='candidate',generation=1,lane='pons'):
        for n in range(generation):
            self.plane.observe(key,lane,str(n),{},ordering=(n,),watermark={'n':n},interpretation={},observed=100,deadline=105,priority=4)
    def record(self,key,stage,classification=None,details=None):
        with self.db:self.db.execute('INSERT INTO progress(lane,candidate,stage,classification,at,details) VALUES(?,?,?,?,?,?)',('pons',key,stage,classification,100,json.dumps(details or {})))
    def test_all_outcomes_use_distinct_authoritative_classes(self):
        expected={'provider_capacity_defer':'capacity_censored','freshness_deadline_censored':'consumer_deadline',
            'authoritative_evidence_failure':'provider_failed','strategy_rejected':'strategy_rejection',
            'structural_excluded':'structural_ineligible','transient_defer':'unresolved_transient',
            'superseded':'superseded_generation','canonical_evidence_complete':'canonical_completion'}
        self.assertEqual({k:classify(k)[1] for k in expected},expected)
        self.assertEqual(classify('position_safety'),('forward_observation',None))
        with self.assertRaisesRegex(ValueError,'unclassified'):classify('unknown')
    def test_three_retained_capacity_deferrals_cannot_disappear(self):
        for r in fixture()['deferrals']:
            self.observe(r['candidate'],r['generation'])
            self.plane.claim(key=r['candidate'],estimate_seconds=6)
            self.record(r['candidate'],'discovered')
        before=consistency(self.plane.path,self.path,'pons',reported_classes={'capacity_censored':0})
        self.assertEqual(before['expected_unique_classes'],{'capacity_censored':3})
        self.assertEqual(before['missing_memberships'],{'capacity_censored':3})
        self.assertEqual(before['status'],'fail')
        for r in fixture()['deferrals']:self.record(r['candidate'],'terminal','capacity_censored')
        after=consistency(self.plane.path,self.path,'pons',reported_classes={'capacity_censored':3})
        self.assertEqual(after['status'],'pass')
        # Even a correctly populated pipeline cannot justify a contradictory report.
        self.assertEqual(consistency(self.plane.path,self.path,'pons',reported_classes={})['status'],'fail')
    def test_deadline_and_provider_failures_fail_certification_independently(self):
        for kind in ('freshness_deadline_censored','authoritative_evidence_failure'):
            self.observe(kind);work=self.plane.claim(key=kind)
            self.plane.finish(work,state=kind,reason='fixture')
            self.record(kind,'rejected','strategy_rejection')
        pipe=pipeline(self.root,candidate_plane=self.plane.path,lane='pons')
        native=native_positions(self.root,'pons')
        report=lane_report('pons',{},native,{'status':'pass'},pipe,{'verified':True},100)
        self.assertIn('candidate_plane_accounting_contradiction',report['admission_failures'])
        self.assertEqual(report['economic_admission'],'invalid')
        for kind in ('freshness_deadline_censored','authoritative_evidence_failure'):
            self.record(kind,'terminal',classify(kind)[1])
        self.assertEqual(consistency(self.plane.path,self.path,'pons')['status'],'pass')
    def test_wrong_candidate_or_other_lane_cannot_cover_missing_membership(self):
        self.observe();self.plane.claim(estimate_seconds=6)
        self.record('different_candidate','terminal','capacity_censored')
        self.assertEqual(consistency(self.plane.path,self.path,'pons')['status'],'fail')
        self.assertEqual(consistency(self.plane.path,self.path,'ramses')['status'],'pass')
    def test_reconciliation_preserves_both_historical_decisions(self):
        for stage,classification,generation in [('discovered',None,1),('rejected','strategy_rejection',1),
            ('discovered',None,2),('evidence_complete',None,2),('rejected','strategy_rejection',2)]:
            self.record('candidate',stage,classification,{'candidate_generation':generation})
        before=self.db.execute('SELECT * FROM progress').fetchall()
        result=reconcile(self.path)
        self.assertEqual(result['terminal_counts']['valid_early_rejection'],1)
        self.assertEqual(self.db.execute('SELECT * FROM progress').fetchall(),before)
        self.assertEqual(sum(r[3]=='rejected' for r in before),2)
    def test_obsolete_completion_is_history_and_new_valid_generation_completes(self):
        self.observe();old=self.plane.claim();self.observe(generation=2)
        self.assertFalse(self.plane.finish(old,result={}))
        newer=self.plane.claim();self.assertTrue(self.plane.finish(newer,result={}))
        self.assertEqual(self.plane.snapshot()['obsolete_completions_fenced'],1)
        self.assertEqual(self.plane.snapshot()['complete_canonical_decisions'],1)
        self.assertEqual(consistency(self.plane.path,self.path,'pons')['expected_unique_classes'],{})
