import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from certification.robinhood.provider_usage import snapshot


class ProviderUsageWalRaceTests(unittest.TestCase):
    def test_checkpointed_wal_disappearing_during_snapshot_is_zero_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'shared-robinhood-admission.sqlite'
            db=sqlite3.connect(path)
            db.executescript("""
                CREATE TABLE provider_usage(
                    endpoint TEXT,lane TEXT,metric TEXT,value REAL,
                    PRIMARY KEY(endpoint,lane,metric));
                CREATE TABLE queue(
                    id TEXT,endpoint TEXT,priority INTEGER,created REAL,deadline REAL);
                CREATE TABLE limits(
                    endpoint TEXT PRIMARY KEY,next_at REAL,cooldown REAL,interval REAL);
                INSERT INTO limits VALUES('endpoint',0,0,0.5);
            """)
            db.commit();db.close()

            original_exists=Path.exists
            original_stat=Path.stat
            def raced_exists(value):
                if str(value).endswith('-wal'):
                    return True
                return original_exists(value)
            def raced_stat(value,*args,**kwargs):
                if str(value).endswith('-wal'):
                    raise FileNotFoundError(str(value))
                return original_stat(value,*args,**kwargs)

            # Reproduces Run 375 deterministically: the old snapshot observed the
            # WAL, SQLite checkpointed/unlinked it, then stat() killed Pons.
            with patch.object(Path,'exists',raced_exists),patch.object(Path,'stat',raced_stat):
                result=snapshot(path,'endpoint')

            self.assertEqual(result['health']['wal_bytes'],0)
            self.assertGreater(result['health']['database_bytes'],0)


if __name__=='__main__':
    unittest.main()
