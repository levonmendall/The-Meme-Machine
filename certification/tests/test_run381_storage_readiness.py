"""Preserved Run 381 aggregate evidence is not a healthy Meteora decision path."""
import unittest
from certification.controls import evidence_continuity

class StorageReadinessTests(unittest.TestCase):
 def test_capacity_stop_before_local_read_cannot_report_no_censoring(self):
  shared={'counters':{'capacity_stops':3,'archived_records':11041,'compacted_records':0},'unresolved_gaps':20}
  row={'funnel':{'unique_reconstruction_incomplete':162},'evidence_service_health':{'failure':'evidence_service_unavailable'}}
  result=evidence_continuity(row,'meteora',shared)
  self.assertEqual(result['classification'],'infrastructure_censored')
  self.assertEqual(result['complete_local_reads'],0)
  self.assertEqual(result['storage_capacity_stops'],3)
  self.assertIn('meteora:storage_capacity_censored_evidence',result['failures'])

 def test_zero_activity_without_capacity_failure_remains_allowed(self):
  result=evidence_continuity({'funnel':{}},'meteora',{'counters':{},'unresolved_gaps':0})
  self.assertEqual(result['failures'],[])
