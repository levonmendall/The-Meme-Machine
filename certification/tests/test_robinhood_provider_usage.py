import sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

from certification.robinhood import provider_usage


class ProviderUsageWalRaceTests(unittest.TestCase):
    def test_snapshot_treats_checkpointed_away_wal_as_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'shared-robinhood-admission.sqlite'
            db=sqlite3.connect(path)
            try:
                db.execute('CREATE TABLE provider_usage(endpoint TEXT,lane TEXT,metric TEXT,value REAL,PRIMARY KEY(endpoint,lane,metric))')
                db.execute('CREATE TABLE queue(endpoint TEXT,priority INTEGER)')
                db.execute('CREATE TABLE limits(endpoint TEXT PRIMARY KEY,interval REAL,cooldown REAL)')
                db.execute('INSERT INTO limits VALUES(?,?,?)',('ep',0.5,0.0))
                db.commit()
            finally:
                db.close()

            real_stat=Path.stat
            def checkpoint_race(self,*args,**kwargs):
                if str(self).endswith('-wal'):
                    raise FileNotFoundError(str(self))
                return real_stat(self,*args,**kwargs)

            with patch.object(Path,'stat',checkpoint_race):
                row=provider_usage.snapshot(path,'ep')
            self.assertEqual(row['health']['wal_bytes'],0)
            self.assertGreater(row['health']['database_bytes'],0)


if __name__=='__main__':
    unittest.main()
