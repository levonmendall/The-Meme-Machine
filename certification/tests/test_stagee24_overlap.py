"""Real source/retirement commits across a held snapshot, with a pre-window batch."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from certification.combined_observer import Interaction,observe_window,verified,REVISION
from certification.tests.test_combined_pressure import valid_report
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_evidence_transport import Subscription
from tests.test_retention_outcomes import CONFIG,seed
from tests.test_run376_dispatch_pressure import account_frame


class RealOverlapTests(unittest.TestCase):
    def test_pre_snapshot_batch_four_source_commits_and_real_retirement(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'db'
            owner=PriorityOwner(lambda:ServiceState(path,CONFIG));owner.ready.result(5)
            entered=threading.Event();release=threading.Event();control=Interaction()
            sample=dict(eligible_at_reader_start=False,source_frames_while_reader=0)
            control.metrics['burst_evidence']=[sample]
            sub=Subscription('observer','account:overlap','overlap','account',0)
            def item(slot):
                raw=account_frame(slot)
                return (sub,json.loads(raw),1000,len(raw))
            try:
                owner.submit(lambda s:seed(s,256),priority=4).result(5)
                def first(state):
                    token=control.source_started(1)
                    original=state._source_locked
                    def held(*args):
                        self.assertTrue(state.writer.db.in_transaction)
                        entered.set()
                        if not release.wait(5):raise TimeoutError('reader_barrier')
                        return original(*args)
                    with patch.object(state,'_source_locked',side_effect=held):
                        result=state.source_batch((item(100),))
                    control.source_completed(token,1)
                    return result
                pending=owner.submit(first,priority=2)
                self.assertTrue(entered.wait(5))
                with closing(sqlite3.connect(path,isolation_level=None)) as reader:
                    reader.execute('BEGIN')
                    before=dict(reader.execute('SELECT key,value FROM counters'))
                    control.reader_phase=1
                    release.set();self.assertEqual(pending.result(5),1)
                    # Three more real, separately committed source batches. No
                    # artificial increment of either authoritative counter.
                    for slot in (101,102,103):
                        owner.submit(lambda s,slot=slot:s.source_batch((item(slot),)),priority=2).result(5)
                    outcome=owner.submit(lambda s:s.retention(),priority=4).result(5)
                    self.assertEqual(outcome.retired_records,256)
                    observe_window(reader,path,before,sample)
                    self.assertEqual(sample['source_frames_while_reader'],4)
                    self.assertEqual(sample['reader_compaction_advance'],256)
                    self.assertEqual(sample['legacy_start_phase_frames'],0)
                    self.assertEqual(sample['cleanup_window_status'],'serviced')
                    self.assertEqual(dict(reader.execute('SELECT key,value FROM counters')),before)
                    self.assertEqual(reader.execute("SELECT COUNT(*) FROM records WHERE scope='program:meteora'").fetchone()[0],256)
                    with closing(sqlite3.connect(path)) as current:
                        self.assertEqual(current.execute("SELECT COUNT(*) FROM records WHERE scope='program:meteora'").fetchone()[0],0)
                    reader.execute('ROLLBACK')
            finally:
                release.set();owner.close()

    def test_exact_retention_boundary_is_failure_not_a_rounding_waiver(self):
        for field in ('oldest_hot_age_peak','oldest_retained_age_peak'):
            row=valid_report()
            row['combined_load']['observation_revision']=REVISION
            for sample in row['combined_load']['burst_evidence']:sample['observation_revision']=REVISION
            self.assertTrue(verified(row,'sha'))
            row[field]=240
            self.assertFalse(verified(row,'sha'))


if __name__=='__main__':unittest.main()
