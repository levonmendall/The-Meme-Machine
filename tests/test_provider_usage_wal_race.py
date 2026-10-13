import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meme_machine.runtime.robinhood.provider_usage import snapshot


class ProviderUsageWalRaceTests(unittest.TestCase):
    def test_demand_writer_does_not_upgrade_a_deferred_read_transaction(self):
        import json
        from meme_machine.runtime.robinhood import provider_usage
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'provider.sqlite'
            db=sqlite3.connect(path);db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE logical_demand(endpoint TEXT,method TEXT,n INTEGER,PRIMARY KEY(endpoint,method))')
            db.commit();db.close()
            connect=sqlite3.connect;injected=[]
            class ConcurrentDDL(sqlite3.Connection):
                def execute(self,statement,*args,**kwargs):
                    value=super().execute(statement,*args,**kwargs)
                    if statement.startswith('CREATE TABLE IF NOT EXISTS logical_demand'):
                        # Reproduce a completion committed after schema read and
                        # before demand insertion. A deferred BEGIN upgrades its
                        # obsolete snapshot and raises SQLITE_BUSY immediately.
                        other=connect(path);other.execute('INSERT INTO logical_demand VALUES(?,?,?)',('other','eth_call',1));other.commit();other.close()
                        injected.append(True)
                    return value
            def opened(*args,**kwargs):return connect(*args,factory=ConcurrentDDL,**kwargs)
            with patch.object(provider_usage.sqlite3,'connect',opened):provider_usage.demand(path,'endpoint',['eth_call'])
            self.assertEqual(injected,[True])
            db=connect(path)
            try:self.assertEqual(db.execute("SELECT n FROM logical_demand WHERE endpoint='endpoint'").fetchone()[0],1)
            finally:db.close()

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
