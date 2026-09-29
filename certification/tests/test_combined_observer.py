"""A real held SQLite snapshot, not a batch-start marker, defines overlap."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from meme_machine.solana_evidence_plane import EvidenceWriter
from certification.combined_observer import observe_window,verified,REVISION,Interaction
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
        row['combined_load'].pop('observation_revision',None)
        self.assertFalse(verified(row,'sha'))
        row['combined_load']['observation_revision']=REVISION
        for sample in row['combined_load']['burst_evidence']:
            sample.update(observation_revision=REVISION,cleanup_window_status='serviced',
                          eligible_at_reader_start=True,eligible_at_reader_end=False)
        self.assertTrue(verified(row,'sha'))
        row['combined_load']['burst_evidence'][0]['reader_compaction_advance']=0
        self.assertFalse(verified(row,'sha'))

    def test_late_start_phase_callback_cannot_double_count_durable_sample(self):
        control=Interaction();control.reader_phase=1
        sample=dict(source_frames_while_reader=4,reader_source_advance=4)
        control.metrics['burst_evidence']=[sample]
        control.source_completed(1,4)
        self.assertEqual(sample['source_frames_while_reader'],4)
        self.assertEqual(sample['legacy_start_phase_frames'],4)
        control.reader_phase=0
        control.source_completed(1,4)
        self.assertEqual(sample['legacy_start_phase_frames'],4)

    def test_original_workload_is_still_frozen(self):
        from certification.cleanup_recovery import frozen_inputs
        self.assertTrue(frozen_inputs())


class NativeCommitOverlapTests(unittest.TestCase):
    def test_preexisting_source_batch_and_real_retirement_overlap_snapshot(self):
        from dataclasses import replace
        import threading
        import time
        from meme_machine.solana_evidence_control import PriorityOwner
        from meme_machine.solana_evidence_service import ServiceState
        from meme_machine.solana_provider_config import AlchemyEndpoint
        from tests.test_run381_retention_progress import record
        from tests.test_run380_atomic_frame import frame
        config=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db';control=Interaction()
            entered=threading.Event();release=threading.Event()
            owner=PriorityOwner(lambda:ServiceState(path,config))
            try:
                owner.ready.result(5)
                def seed(state):
                    state.writer.ingest([replace(record(),identity='old:%04d'%i,
                        signature='old:%04d'%i,scope='program:meteora') for i in range(256)])
                    self.assertEqual(state.writer.archive(time.time()-180),256)
                owner.submit(seed,priority=4).result(5)
                items=[frame(1000+i) for i in range(4)]
                def source(state):
                    token=control.source_started(4)  # starts BEFORE read snapshot
                    entered.set()
                    if not release.wait(5):raise TimeoutError('test_reader_not_started')
                    count=state.source_batch(items)
                    control.source_completed(token,count)
                    return count
                pending=owner.submit(source,priority=2)
                self.assertTrue(entered.wait(5))
                with closing(sqlite3.connect(path,isolation_level=None)) as reader:
                    reader.execute('BEGIN')
                    before=dict(reader.execute('SELECT key,value FROM counters'))
                    old_count=reader.execute("SELECT COUNT(*) FROM records WHERE identity LIKE 'old:%'").fetchone()[0]
                    sample=dict(eligible_at_reader_start=False,source_frames_while_reader=0)
                    control.metrics['burst_evidence']=[sample];control.reader_phase=1
                    release.set();self.assertEqual(pending.result(5),4)
                    owner.submit(lambda state:state.writer.retain(time.time()-180,
                        max_records=256,archive_first=False,checkpoint=False),priority=4).result(5)
                    observe_window(reader,path,before,sample)
                    self.assertEqual(old_count,256)
                    self.assertEqual(reader.execute("SELECT COUNT(*) FROM records WHERE identity LIKE 'old:%'").fetchone()[0],256)
                    self.assertEqual(sample['legacy_start_phase_frames'],0)
                    self.assertEqual(sample['reader_source_advance'],4)
                    self.assertEqual(sample['reader_compaction_advance'],256)
                    self.assertEqual(sample['cleanup_window_status'],'serviced')
                    reader.execute('ROLLBACK');control.reader_phase=0
                count=owner.submit(lambda state:state.writer.db.execute(
                    "SELECT COUNT(*) FROM records WHERE identity LIKE 'old:%'").fetchone()[0],priority=0).result(5)
                self.assertEqual(count,0)
            finally:
                release.set();owner.close()

if __name__=='__main__':unittest.main()
