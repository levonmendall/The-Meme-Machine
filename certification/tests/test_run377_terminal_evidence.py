"""Shared-plane audit and production-length durable drain boundaries."""
import io,subprocess,tempfile,unittest
from unittest.mock import patch
from certification.controls import evidence_continuity,smoke_engineering
from certification.evidence_supervisor import EvidenceProcess

class Run377TerminalEvidenceTests(unittest.TestCase):
 def test_legacy_meteora_frontier_cannot_mask_shared_capacity_censoring(self):
  shared=dict(counters={'disconnect:local_receive_backpressure_ping_timeout':8,
      'meteora.gap_blocked_reconstructions':2,'meteora.incomplete_local_reads':2},
      unresolved_gaps=11,service_health={'ipc':{'stream.outstanding_frames_peak':64}})
  row=dict(stream_state=dict(connected=True,covered=True,gaps=0,last_slot=450781799))
  result=evidence_continuity(row,'meteora',shared)
  self.assertEqual(result['classification'],'infrastructure_censored')
  self.assertIn('meteora:capacity_censored_local_evidence',result['failures'])
 def test_forced_service_kill_cannot_be_clean_smoke(self):
  from certification.tests.test_controls import ControlsTests
  result=ControlsTests().smoke();result['evidence_service_shutdown']=dict(clean=False,forced=True,exit_code=-9)
  self.assertIn('solana:evidence_service_drain_incomplete',smoke_engineering(result)['failures'])
 def test_supervisor_allows_observed_twelve_second_admitted_drain(self):
  class Process:
   pid=123456;returncode=None
   def poll(self):return self.returncode
   def terminate(self):pass
   def wait(self,timeout):
    if timeout<12:raise subprocess.TimeoutExpired('fixture',timeout)
    self.returncode=0;return 0
  with tempfile.TemporaryDirectory() as td,patch('certification.evidence_supervisor.os.killpg') as kill:
   service=EvidenceProcess(td,td,{},wait_ready=False);service.proc=Process();service.file=io.BytesIO()
   self.assertTrue(service.close()['clean']);kill.assert_not_called()
