"""Diagnostic timing work must not scale with every record mutation."""
import sqlite3
import unittest
from certification.pressure_diagnostics import SQLTimings

class PressureDiagnosticsTests(unittest.TestCase):
    def test_record_volume_does_not_create_per_record_clock_measurements(self):
        timings=SQLTimings()
        with timings.enabled():
            db=sqlite3.connect(':memory:',isolation_level=None)
            try:
                db.execute('CREATE TABLE example(value TEXT)')
                db.execute('BEGIN')
                for _ in range(1000):db.execute('INSERT INTO example VALUES(?)',('private-example',))
                db.execute('COMMIT')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM example').fetchone()[0],1000)
            finally:db.close()
        rows=timings.snapshot()
        self.assertEqual(sum(row['calls'] for row in rows.values()),1,
                         'instrumentation itself adds per-record pressure')
        self.assertEqual(rows['commit']['calls'],1)
        self.assertNotIn('private-example',str(rows))

if __name__=='__main__':unittest.main()
