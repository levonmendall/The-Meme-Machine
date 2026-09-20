import tempfile
from pathlib import Path
import unittest
from certification.cu import estimate
from certification.capabilities import probe

class CuTests(unittest.TestCase):
    def test_batched_members_are_not_discounted(self):
        r=estimate({'eth_call':10,'eth_chainId':2,'eth_getLogs':1})
        self.assertEqual(r['estimated_cu'],320);self.assertEqual(r['logical_calls'],13)
    def test_unknown_cost_is_unknown_not_free(self):
        r=estimate({'unknown':1,'eth_call':1});self.assertIsNone(r['estimated_cu']);self.assertEqual(r['known_estimated_cu'],26)
    def test_capability_probe_fallback_and_census_identity(self):
        from unittest.mock import patch
        import sys,types
        class BoundaryError(Exception):pass
        class Rpc:
            def verify_chain(self):pass
            def telemetry(self):return {}
            def call(self,m,p,scope):
                if m=='eth_getBlockByNumber':return dict(number='0x1',hash='h',timestamp='0x2',transactions=['t'])
                if m in ('eth_getCode','eth_call'):return '0x'
                if m=='eth_callMany':raise BoundaryError('provider_rpc_-32601')
                return [dict(transactionHash='t',blockHash='h')]
        with patch.dict(sys.modules,{'robinhood_research':types.SimpleNamespace(BoundaryError=BoundaryError)}):r=probe(Rpc())
        self.assertFalse(r['methods']['eth_callMany']['supported']);self.assertTrue(r['methods']['eth_getBlockReceipts']['supported'])

    def test_cu_efficiency_keeps_missing_denominators_unknown(self):
        from certification.report import provider_efficiency
        result=dict(lanes={'pons':{'funnel':{'evaluated':10,'complete_evidence_vectors':2}},'ramses':{'funnel':{}}},
            shared_provider={'robinhood':{'lanes':{'pons':{'estimated_cu':100,'requests':3,'logical_calls':8}}}})
        provider_efficiency(result)
        self.assertEqual(result['lanes']['pons']['rpc_efficiency']['cu_per_complete_vector'],50)
        self.assertEqual(result['lanes']['pons']['rpc_efficiency']['cu_per_evaluated'],10)
        self.assertIsNone(result['lanes']['ramses']['rpc_efficiency']['cu_per_scan'])
        self.assertIsNone(result['lanes']['ramses']['rpc_efficiency']['estimated_cu'])
    def test_reuse_snapshot_is_incremental_not_double_counted(self):
        import sqlite3
        from certification.pressure import ReuseView
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'cache.sqlite';db=sqlite3.connect(p)
            db.executescript('CREATE TABLE reuse_events(sequence INTEGER PRIMARY KEY,lane TEXT,method TEXT,outcome TEXT); CREATE TABLE flights(key TEXT); CREATE TABLE evidence(key TEXT);')
            db.executemany('INSERT INTO reuse_events(lane,method,outcome) VALUES(?,?,?)',[('pons','eth_call','miss'),('pons','eth_call','hit'),('ramses','eth_call','coalesced')]);db.commit();db.close()
            view=ReuseView(p)
            for _ in range(2):
                s=view.snapshot();self.assertEqual(s['lanes']['pons']['hits']['eth_call'],1)
                self.assertEqual(s['lanes']['ramses']['coalesced']['eth_call'],1)
                self.assertEqual(s['inflight_jobs'],0)
    def test_reduced_spend_with_reduced_coverage_is_not_success(self):
        from certification.compare_cu import compare
        from copy import deepcopy
        lane=dict(estimated_cu=100,logical_rpc_by_method={'eth_call':4},estimated_cu_by_method={'eth_call':104},
            evaluated_candidates=10,complete_evidence_candidates=5,stale_after_complete_fraction=.2)
        before=dict(run_id=1,totals={'estimated_cu':200},lanes={'pons':lane,'ramses':lane})
        after=deepcopy(before);after['run_id']=2;after['totals']['estimated_cu']=80
        after['lanes']['pons']['evaluated_candidates']=4
        result=compare(before,after)
        self.assertTrue(result['measured_checks']['estimated_cu_reduction_at_least_40pct'])
        self.assertFalse(result['measured_checks']['evaluated_volume_not_lower'])
        self.assertEqual(result['acceptance'],'NOT_ESTABLISHED')

    def test_pons_vector_denominator_uses_its_actual_native_complete_stage(self):
        from certification.report import summarize
        row=summarize('pons',{'summary':{'enrolled':5},'opportunity_coverage':{'stages':{'evidence_complete':3,'economic_vector':0}}})
        self.assertEqual(row['funnel']['complete_evidence_vectors'],3)
