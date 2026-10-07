"""Healthy gap-repair pagination is progression, not exponential retry failure."""
from pathlib import Path
import json,sqlite3,tempfile,unittest
from unittest.mock import patch
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_provider_config import AlchemyEndpoint
from meme_machine.solana_evidence_plane import EvidenceReader

class RepairPaginationTests(unittest.TestCase):
 @unittest.skip('MODEL A archived; bounded interval recovery is tested in Model B')
 def test_stage_costs_and_yields_survive_restart_without_exception_text(self):
  with tempfile.TemporaryDirectory() as td:
   config=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test');path=Path(td)/'db'
   state=ServiceState(path,config)
   def interrupted():raise sqlite3.OperationalError('interrupted')
   def failed():raise ValueError('fixture-private-message')
   with self.assertRaises(sqlite3.OperationalError):state._storage_stage('retention',interrupted)
   with self.assertRaises(ValueError):state._storage_stage('repair_apply',failed)
   self.assertEqual(state._storage_stage('archive_commit',lambda:7),7)
   with self.assertRaisesRegex(ValueError,'storage_stage_identity'):state._storage_stage('unbounded-dynamic-stage',lambda:0)
   expected=dict(state.storage_metrics);self.assertNotIn('fixture-private-message',json.dumps(expected));state.close()
   state=ServiceState(path,config)
   try:
    self.assertEqual(state.storage_metrics,expected)
    self.assertEqual(expected['retention.yielded'],1)
    self.assertEqual(expected['repair_apply.failed'],1)
    self.assertTrue(all(type(v) is int and v>=0 for v in expected.values()))
   finally:state.close()

 def state(self,path):
  state=ServiceState(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
  state.writer.gap('program:pump',10,20,'missing_filtered_block_receipt')
  state.writer.db.execute('INSERT INTO stream_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',('program:pump',21,20,'h21','h20',21,'[]','fixture',1000,0))
  return state
 @unittest.skip('MODEL A archived; bounded interval recovery is tested in Model B')
 def test_successful_pages_drain_without_failure_backoff_and_stay_fail_closed(self):
  with tempfile.TemporaryDirectory() as td:
   state=self.state(Path(td)/'db');reader=EvidenceReader(state.writer.path)
   try:
    for page in range(7):
     with patch('meme_machine.solana_evidence_service.time.time',return_value=1000+page):
      plan=state.repair_plan();self.assertIsNotNone(plan,'healthy pagination was delayed as if it were a provider failure')
      data=[dict(slot=10+page,transactionIndex=i,blockTime=10+page,transaction={'signatures':['p%d:%d'%(page,i)],'message':{'accountKeys':[]}},meta={'err':None,'logMessages':[]}) for i in range(100)]
      state.repair_apply(plan,dict(data=data,paginationToken='page%d'%page if page<6 else None))
      self.assertEqual(reader.covered('program:pump',10,20,as_of=1000+page),page==6)
    self.assertEqual(state.writer.db.execute('SELECT pages,attempts FROM gaps WHERE id=1').fetchone(),(7,14))
    self.assertEqual(dict(state.writer.db.execute('SELECT key,value FROM counters'))['gap_repair_retries'],0)
   finally:reader.close();state.close()
 @unittest.skip('MODEL A archived; bounded interval recovery is tested in Model B')
 def test_failed_provider_attempts_retain_bounded_backoff(self):
  with tempfile.TemporaryDirectory() as td:
   state=self.state(Path(td)/'db')
   try:
    with patch('meme_machine.solana_evidence_service.time.time',return_value=1000):self.assertIsNotNone(state.repair_plan())
    # No successful apply: this models a failed governed transport attempt.
    with patch('meme_machine.solana_evidence_service.time.time',return_value=1001):self.assertIsNotNone(state.repair_plan())
    with patch('meme_machine.solana_evidence_service.time.time',return_value=1002):self.assertIsNone(state.repair_plan())
    self.assertIsNone(state.writer.db.execute('SELECT repaired FROM gaps WHERE id=1').fetchone()[0])
   finally:state.close()

if __name__=='__main__':unittest.main()
