"""A real held SQLite snapshot, not a batch-start marker, defines overlap."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from meme_machine.solana_evidence_plane import EvidenceWriter
from certification.combined_observer import observe_window,verified,REVISION
from certification.tests.test_combined_pressure import valid_report


class OverlapObservationTests(unittest.TestCase):
    def test_batch_started_before_reader_but_committed_inside_is_counted(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db';writer=EvidenceWriter(path)
            try:
                with writer.transaction():
                    writer._count('stream_accepted_messages',100)
                    writer._count('compacted_records',100)
                with closing(sqlite3.connect(path,isolation_level=None)) as reader:
                    reader.execute('BEGIN')
                    before=dict(reader.execute('SELECT key,value FROM counters'))
                    sample=dict(eligible_at_reader_start=False,source_frames_while_reader=0)
                    with writer.transaction():
                        writer._count('stream_accepted_messages',4)
                        writer._count('compacted_records',256)
                    observe_window(reader,path,before,sample)
                    self.assertEqual(sample['legacy_start_phase_frames'],0)
                    self.assertEqual(sample['source_frames_while_reader'],4)
                    self.assertEqual(sample['reader_compaction_advance'],256)
                    self.assertEqual(sample['cleanup_window_status'],'serviced')
                    reader.execute('ROLLBACK')
            finally:
                writer.close()

    def test_work_after_reader_close_cannot_be_counted(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db';writer=EvidenceWriter(path)
            try:
                with closing(sqlite3.connect(path,isolation_level=None)) as reader:
                    reader.execute('BEGIN');before=dict(reader.execute('SELECT key,value FROM counters'))
                    reader.execute('ROLLBACK')
                    with writer.transaction():
                        writer._count('stream_accepted_messages',4)
                    with self.assertRaisesRegex(AssertionError,'reader_not_held'):
                        observe_window(reader,path,before,dict(eligible_at_reader_start=False))
            finally:
                writer.close()

    def test_missing_cleanup_is_classified_but_never_passed(self):
        for initial,status in ((False,'no_eligible_witness'),(True,'eligible_not_serviced')):
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)/'db';writer=EvidenceWriter(path)
                try:
                    with closing(sqlite3.connect(path,isolation_level=None)) as reader:
                        reader.execute('BEGIN');before=dict(reader.execute('SELECT key,value FROM counters'))
                        sample=dict(eligible_at_reader_start=initial)
                        observe_window(reader,path,before,sample)
                        self.assertEqual(sample['cleanup_window_status'],status)
                        self.assertEqual(sample['reader_compaction_advance'],0)
                        reader.execute('ROLLBACK')
                finally:
                    writer.close()
        row=valid_report()
        self.assertFalse(verified(row,'sha'))
        row['combined_load']['observation_revision']=REVISION
        for sample in row['combined_load']['burst_evidence']:
            sample.update(observation_revision=REVISION,cleanup_window_status='serviced',
                          eligible_at_reader_start=True,eligible_at_reader_end=False)
        self.assertTrue(verified(row,'sha'))
        row['combined_load']['burst_evidence'][0]['reader_compaction_advance']=0
        self.assertFalse(verified(row,'sha'))

    def test_original_workload_is_still_frozen(self):
        from certification.cleanup_recovery import frozen_inputs
        self.assertTrue(frozen_inputs())


if __name__=='__main__':
    unittest.main()
