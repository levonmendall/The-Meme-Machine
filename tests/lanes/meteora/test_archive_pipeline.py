"""Successor archive selection cannot add another source-sized queue delay."""
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from meme_machine.lanes.meteora.solana_evidence_control import PriorityOwner
from meme_machine.lanes.meteora.solana_evidence_plane import EvidenceUnavailable
from meme_machine.lanes.meteora.solana_evidence_service import ServiceState, ARCHIVE_COMMIT_SLICE_RECORDS
from meme_machine.lanes.meteora.solana_provider_config import AlchemyEndpoint
from tests.lanes.meteora.test_run381_retention_progress import record

CONFIG=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')


def seed(state, count=1020):
    state.writer.ingest([replace(record(),identity='pipeline:%04d'%i,
        signature='pipeline:%04d'%i,market_time=10,slot=100+i) for i in range(count)])
    snapshot=state.writer.archive_snapshot(1000,max_records=1000)
    plan,receipt=state.writer.prepare_and_write_archive(state.writer.path,snapshot)
    assert len(plan)==1000
    return plan,receipt


class ArchivePipelineTests(unittest.TestCase):
    def test_one_bounded_slice_and_exact_successor_without_extra_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            state=ServiceState(Path(td)/'db',CONFIG)
            try:
                plan,receipt=seed(state)
                before=state.writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NULL').fetchone()[0]
                remaining,snapshot=state.archive_commit_slice_and_plan(plan,receipt)
                self.assertEqual(len(remaining),1000-ARCHIVE_COMMIT_SLICE_RECORDS)
                self.assertIsNone(snapshot)
                after=state.writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NULL').fetchone()[0]
                self.assertEqual(after-before,512)
                remaining,snapshot=state.archive_commit_slice_and_plan(remaining,receipt)
                self.assertEqual(remaining,[])
                self.assertEqual(len(snapshot['rows']),20)
                self.assertEqual({r['identity'] for r in snapshot['rows']},
                                 {'pipeline:%04d'%i for i in range(1000,1020)})
                self.assertEqual(state.writer.db.execute('SELECT records FROM archives').fetchone(),(1000,))
                self.assertEqual(state.writer.db.execute('PRAGMA synchronous').fetchone(),(2,))
                self.assertEqual(state.writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
                self.assertFalse(state.writer.db.in_transaction)
            finally:state.close()

    def test_yield_after_last_commit_reuses_receipt_and_keeps_successor_exact(self):
        with tempfile.TemporaryDirectory() as td:
            state=ServiceState(Path(td)/'db',CONFIG)
            try:
                plan,receipt=seed(state)
                remaining,_=state.archive_commit_slice_and_plan(plan,receipt)
                native=state.archive_plan
                with patch.object(state,'archive_plan',side_effect=EvidenceUnavailable('evidence_background_yield')):
                    with self.assertRaisesRegex(EvidenceUnavailable,'evidence_background_yield'):
                        state.archive_commit_slice_and_plan(remaining,receipt)
                remaining,snapshot=state.archive_commit_slice_and_plan(remaining,receipt)
                self.assertEqual(remaining,[]);self.assertEqual(len(snapshot['rows']),20)
                self.assertEqual(state.writer.db.execute("SELECT value FROM counters WHERE key='archived_records'").fetchone(),(1000,))
                self.assertEqual(state.storage_metrics['archive_worker.records.total'],1000)
                self.assertEqual(len(list((Path(td)/'db.archive').glob('*.gz'))),1)
                self.assertEqual(state.writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            finally:state.close()

    def test_new_pin_during_worker_keeps_its_record_hot_in_both_slices(self):
        with tempfile.TemporaryDirectory() as td:
            state=ServiceState(Path(td)/'db',CONFIG)
            try:
                plan,receipt=seed(state)
                # Pin the final portion after publication but before commit.
                state.writer.interest('position','pump',lower_slot=1095,priority=0,lifecycle='open')
                remaining,_=state.archive_commit_slice_and_plan(plan,receipt)
                remaining,snapshot=state.archive_commit_slice_and_plan(remaining,receipt)
                self.assertEqual(remaining,[]);self.assertIsNone(snapshot)
                self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NULL').fetchone(),(995,))
                self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone(),(25,))
                self.assertEqual(state.writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            finally:state.close()

    def test_successor_selection_does_not_wait_behind_next_source_admission(self):
        with tempfile.TemporaryDirectory() as td:
            owner=PriorityOwner(lambda:ServiceState(Path(td)/'db',CONFIG))
            entered=threading.Event();release=threading.Event();order=[]
            try:
                owner.ready.result(2)
                plan,receipt=owner.submit(seed,priority=4).result(5)
                remaining,_=owner.submit(lambda s:s.archive_commit_slice_and_plan(plan,receipt),priority=4).result(2)
                def finish(state):
                    entered.set()
                    if not release.wait(2):raise TimeoutError('test_owner_release')
                    value=state.archive_commit_slice_and_plan(remaining,receipt)
                    order.append('successor-selected')
                    return value
                archive=owner.submit(finish,priority=4)
                self.assertTrue(entered.wait(2))
                source=owner.submit(lambda s:order.append('next-source'),priority=2)
                release.set()
                _,snapshot=archive.result(2);source.result(2)
                self.assertEqual(len(snapshot['rows']),20)
                self.assertEqual(order,['successor-selected','next-source'])
            finally:release.set();owner.close()


if __name__=='__main__':unittest.main()
