"""The measured pressure fixture must exercise the real bounded archive worker."""
import multiprocessing,tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from certification.run381_pressure import MeasuredProcessPool,ARCHIVE_SECONDS_PER_THOUSAND
from meme_machine.solana_evidence_plane import EvidenceWriter
from tests.test_run381_retention_progress import record

class MeasuredContentionTests(unittest.TestCase):
 def test_spawned_archive_profile_publishes_and_enforces_measured_floor(self):
  with tempfile.TemporaryDirectory() as td:
   writer=EvidenceWriter(Path(td)/'db',clock=lambda:1000)
   pool=MeasuredProcessPool(max_workers=2,mp_context=multiprocessing.get_context('spawn'))
   try:
    writer.ingest([replace(record(),identity='floor:'+str(i)) for i in range(1000)])
    snapshot=writer.archive_snapshot(1000);started=time.monotonic()
    plan,receipt=pool.submit(EvidenceWriter.prepare_and_write_archive,writer.path,snapshot).result(15)
    self.assertGreaterEqual(time.monotonic()-started,ARCHIVE_SECONDS_PER_THOUSAND)
    self.assertEqual(len(plan),1000)
    self.assertEqual(writer.commit_archive(plan,receipt),1000)
   finally:pool.shutdown(wait=True);writer.close()

if __name__=='__main__':unittest.main()
