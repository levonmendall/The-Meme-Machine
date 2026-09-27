"""Age monitoring must retain exact semantics without payload-table read load."""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from certification.run381_pressure import oldest_retained_time
from meme_machine.solana_evidence_plane import SCHEMA


def requested_read_bytes():
    # Linux read accounting counts requested bytes even with a warm OS cache.
    # This regression is independent of machine speed and storage latency.
    return dict(line.split(':',1) for line in
        Path('/proc/self/io').read_text().splitlines())['rchar']


class PressureObserverTests(unittest.TestCase):
    def test_exact_age_includes_archived_rows_null_clocks_and_empty_database(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.executescript(SCHEMA)
        self.assertIsNone(oldest_retained_time(db))
        for i,(market,seen,body,archive) in enumerate([
            (50,1,'hot',None), (None,7,'hot',None),
            (3,99,None,'archive-a'), (None,2,None,'archive-b'),
        ]):
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (str(i),'scope-'+str(i%2),i,str(i),'program',market,0,
                 None,'event',body,'hash',seen,archive))
            expected=db.execute('SELECT MIN(COALESCE(market_time,first_seen)) FROM records').fetchone()[0]
            self.assertEqual(oldest_retained_time(db),expected)
        self.assertEqual(oldest_retained_time(db),2)

    def test_mature_observer_io_is_independent_of_hot_payload_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'mature.db'
            db=sqlite3.connect(path);db.executescript(SCHEMA)
            db.executemany('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ((str(i),'scope-'+str(i%3),i,str(i),'program',
                  None if i%23==0 else 2000+i,0,None,'event',
                  'x'*3500 if i%5 else None,'hash',1000+i,
                  None if i%5 else 'archive') for i in range(12000)))
            db.commit();db.close()
            # Match the actual observer's new connection on each snapshot.
            db=sqlite3.connect(path)
            try:
                before=int(requested_read_bytes())
                self.assertEqual(oldest_retained_time(db),1000)
                read_bytes=int(requested_read_bytes())-before
            finally:db.close()
            self.assertLess(read_bytes,path.stat().st_size//5,
                'age observation reread hot payload pages and competed with production persistence')


if __name__=='__main__':unittest.main()
