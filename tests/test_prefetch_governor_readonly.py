"""Optional prefetch observation cannot create or mutate provider state."""
import hashlib,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.lanes.pump.solana_evidence_consumers import StreamEvidenceService

class PrefetchGovernorReadonlyTests(unittest.TestCase):
    def test_governor_removed_after_exists_check_is_not_recreated(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'missing-governor.sqlite'
            worker=StreamEvidenceService(None,lambda:None)
            with patch.dict(os.environ,{'MM_PROVIDER_GOVERNOR_DB':str(path)}),patch('meme_machine.lanes.pump.solana_evidence_consumers.os.path.exists',return_value=True):
                self.assertFalse(worker._shared_provider_idle())
            self.assertFalse(path.exists(),'a readonly optional observation recreated absent canonical provider state')

    def test_existing_idle_governor_is_observed_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'existing-governor.sqlite';db=sqlite3.connect(path)
            db.executescript("CREATE TABLE pressure(provider TEXT,next_at REAL,cooldown REAL); CREATE TABLE queue(provider TEXT); INSERT INTO pressure VALUES('solana',0,0);")
            db.commit();db.close();before=hashlib.sha256(path.read_bytes()).hexdigest()
            worker=StreamEvidenceService(None,lambda:None)
            with patch.dict(os.environ,{'MM_PROVIDER_GOVERNOR_DB':str(path)}):
                self.assertTrue(worker._shared_provider_idle())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
