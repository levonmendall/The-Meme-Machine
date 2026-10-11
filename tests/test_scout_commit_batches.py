"""Offline locator bursts retain the original facts and durable wakeups."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine import pump
from meme_machine.solana_selective_source import (
    SelectiveSource,SCOUT_COMMIT_BATCH,commit_scout,commit_scout_batch,scout_fact,
)
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.yellowstone import geyser_pb2 as pb
from tests.test_solana_closure import NOW,state_at


def update(n):
    u=pb.SubscribeUpdate(filters=['p']);item=u.account
    item.slot=100+n;item.is_startup=False
    item.account.pubkey=n.to_bytes(32,'little');item.account.owner=pump.un58(PROGRAMS['pump'])
    item.account.txn_signature=n.to_bytes(64,'little')
    raw=bytearray(49);raw[24:32]=(100-n).to_bytes(8,'little');raw[40:48]=(100).to_bytes(8,'little')
    item.account.data=bytes(raw);return u


class ScoutCommitBatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state,self.history=state_at(Path(self.tmp.name)/'canonical.sqlite')
        self.addCleanup(self.state.writer.close)

    def snapshot(self):
        tables=('market_observations','candidate_lifecycle','candidate_activity_receipts','candidate_history_outbox')
        return {t:self.history.db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in tables}

    async def test_batch_and_original_retention_wakeups_are_identical_after_reopen(self):
        original,h=state_at(Path(self.tmp.name)/'original.sqlite')
        try:
            rows=[update(n) for n in range(1,65)]+[update(12),update(2)]
            for u in rows:commit_scout(original,u,NOW+u.account.slot)
            for lo in range(0,len(rows),SCOUT_COMMIT_BATCH):
                commit_scout_batch(self.state,[scout_fact(u,NOW+u.account.slot) for u in rows[lo:lo+SCOUT_COMMIT_BATCH]])
            for table,values in self.snapshot().items():
                # Outbox IDs are stable content hashes, not fresh UUIDs.
                self.assertEqual(values,h.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall(),table)
            self.state.writer.close();self.state,self.history=state_at(self.state.writer.path)
            self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0],64)
            self.assertEqual(self.history.db.execute("SELECT COUNT(*) FROM coverage WHERE scope LIKE 'program:%'").fetchone()[0],0)
        finally:original.writer.close()

    async def test_atomic_failure_retains_no_partial_batch_or_checkpoint(self):
        facts=[scout_fact(update(n),NOW) for n in range(1,5)]
        before=self.snapshot();real=self.history.observe;count=0
        def failing(**fact):
            nonlocal count
            count+=1
            if count==3:raise EvidenceUnavailable('offline_writer_fault')
            real(**fact)
        with patch.object(self.history,'observe',side_effect=failing):
            with self.assertRaisesRegex(EvidenceUnavailable,'offline_writer_fault'):
                commit_scout_batch(self.state,facts)
        self.assertEqual(self.snapshot(),before)
        self.assertFalse(self.history.db.in_transaction)
        commit_scout_batch(self.state,facts)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0],4)

    async def test_ready_burst_uses_one_fsync_without_waiting_for_quiet_stream(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
        q=asyncio.Queue(maxsize=SCOUT_COMMIT_BATCH);calls=[];statements=[]
        self.history.db.set_trace_callback(statements.append)
        async def work(fn,priority,**kw):
            calls.append(priority);result=fn(self.state);source.stop.set();return result
        source.work=work
        for n in range(1,65):q.put_nowait(scout_fact(update(n),NOW))
        await asyncio.wait_for(source.scout_commits(q),.5)
        self.assertEqual(calls,[5]);self.assertEqual(q.qsize(),0)
        self.assertEqual(sum(sql=='COMMIT' for sql in statements),1)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0],64)
        # A single quiet locator commits immediately; no minimum batch size.
        source.stop.clear();q.put_nowait(scout_fact(update(65),NOW))
        await asyncio.wait_for(source.scout_commits(q),.1)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0],65)

    async def test_queue_is_bounded_and_never_retains_the_native_protobuf(self):
        q=asyncio.Queue(maxsize=SCOUT_COMMIT_BATCH)
        u=update(1);fact=scout_fact(u,NOW);q.put_nowait(fact)
        u.account.account.data=b'changed';u.account.slot=999
        self.assertEqual(fact['slot'],101);self.assertEqual(fact['fields']['real_token_reserves'],99)
        self.assertFalse(fact['fields']['economic_event']);self.assertFalse(fact['fields']['history_complete'])
        for _ in range(63):q.put_nowait(fact)
        blocked=asyncio.create_task(q.put(fact));await asyncio.sleep(0)
        self.assertFalse(blocked.done());q.get_nowait();await blocked
        self.assertEqual(q.qsize(),64)
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_scout_fields_missing'):
            scout_fact(u,NOW)

    async def test_rolling_waits_for_durable_control_catchup_without_granting_economic_coverage(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
        source.control_bootstrap_tip=1000
        waiting=asyncio.create_task(source.wait_current_control())
        await asyncio.sleep(.01);self.assertFalse(waiting.done())
        source.control_committed_slot=999
        await asyncio.sleep(.06);self.assertFalse(waiting.done())
        source.control_committed_slot=1000
        await asyncio.wait_for(waiting,.1)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)

    async def test_stop_during_control_catchup_does_not_open_a_replacement_feed(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
        source.control_bootstrap_tip=1000
        waiting=asyncio.create_task(source.wait_current_control())
        await asyncio.sleep(0);source.stop.set()
        with self.assertRaises(asyncio.CancelledError):await waiting


if __name__=='__main__':unittest.main()
