"""Offline locator bursts retain the original facts and durable wakeups."""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine import pump
from meme_machine.solana_selective_source import (
    SelectiveSource,SCOUT_COMMIT_BATCH,commit_scout,commit_scout_batch,scout_fact,
)
from meme_machine.solana_evidence_plane import EvidenceUnavailable,IntervalProof,digest
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

    async def test_same_command_selection_preserves_order_merges_activity_and_priority(self):
        original,h=state_at(Path(self.tmp.name)/'ordered-original.sqlite')
        try:
            for target in (h,self.history):
                for name in ('active','demoted','pinned','quiet'):
                    target.observe('pump',name,slot=99,seen=NOW,signature='initial',fields=dict(retained=True))
                target.db.execute("UPDATE candidate_lifecycle SET state='active' WHERE address='active'")
                target.db.execute("UPDATE candidate_lifecycle SET state='demoted' WHERE address='demoted'")
                target.writer.interest('position','program:pump',lower_slot=90,priority=1)
                target.db.execute('INSERT INTO service_interests VALUES(?,?,?,?)',('position','program:pump','pinned','account'))
            facts=[]
            for slot,seen in ((100,NOW+2),(100,NOW+1),(101,NOW+3),(101,NOW+3),(102,NOW+2)):
                for name in ('active','demoted','pinned','quiet'):
                    facts.append(dict(family='pump',address=name,slot=slot,seen=seen,
                        signature='activity-'+str(slot),fields=dict(activity=True,new=slot)))
            for fact in facts:h.observe(**fact)
            commit_scout_batch(self.state,[None,*facts])
            for table,values in self.snapshot().items():
                self.assertEqual(values,h.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall(),table)
            self.assertEqual(self.history.db.execute("SELECT priority FROM candidate_history_outbox WHERE address='pinned' AND kind='activity' ORDER BY rowid DESC LIMIT 1").fetchone(),(2,))
            # A later owner command observes a changed policy/interest state,
            # never the previous command's selection view.
            self.history.db.execute("UPDATE candidate_lifecycle SET state='active' WHERE address='quiet'")
            commit_scout_batch(self.state,[dict(facts[-1],slot=103,signature='next')])
            self.assertEqual(self.history.db.execute("SELECT priority FROM candidate_history_outbox WHERE address='quiet' ORDER BY rowid DESC LIMIT 1").fetchone(),(2,))
        finally:original.writer.close()

    async def test_selection_reads_are_bounded_per_command_and_no_nested_transactions(self):
        facts=[scout_fact(update(n),NOW+n) for n in range(1,65)]
        statements=[];self.history.db.set_trace_callback(statements.append)
        commit_scout_batch(self.state,facts)
        self.history.db.set_trace_callback(None)
        selects=[s for s in statements if s.lstrip().upper().startswith(('SELECT','WITH REQUESTED'))]
        self.assertEqual(len([s for s in selects if s.startswith('WITH requested')]),3)
        self.assertFalse(any('SELECT state,epoch,last_slot' in s or 'SELECT last_slot,last_seen,fields' in s for s in selects))
        self.assertEqual(sum(s=='COMMIT' for s in statements),1)
        self.assertFalse(any(s.startswith('SAVEPOINT') for s in statements))

    async def test_invalid_older_json_still_fails_and_cannot_leave_a_batch_view(self):
        fact=scout_fact(update(1),NOW)
        commit_scout_batch(self.state,[fact]);before=self.snapshot()
        invalid=dict(fact,slot=fact['slot']-1,fields=dict(invalid=float('nan')))
        for batch in (False,True):
            with self.subTest(batch=batch),self.assertRaises(ValueError):
                if batch:commit_scout_batch(self.state,[scout_fact(update(2),NOW),invalid])
                else:self.history.observe(**invalid)
            self.assertEqual(self.snapshot(),before)

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

    async def test_development_slices_retain_all_candidates_and_rollback_cursors(self):
        from meme_machine.solana_selective_source import DEVELOPMENT_BATCH
        from meme_machine.solana_selective_runtime import CONTROL
        h=self.history;db=h.db
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        ScopedRetirement(h)
        self.state.writer.ingest([],proof=IntervalProof(CONTROL,100,110,
            'alchemy_finalized_stream','a'*64,dict(finalized=True,complete=True,
                scope=CONTROL,lower_slot=100,upper_slot=110,lineage_hash=digest([CONTROL,100,110])),NOW))
        for n in range(50):
            h.observe('pump','candidate-'+str(n),slot=100,signature=str(n),seen=NOW,
                fields=dict(activity=True))
        h.observe('pump','quiet',slot=100,signature='quiet',seen=NOW,
            fields=dict(complete=False,development_upper_bps=0))
        source=SelectiveSource(SimpleNamespace(credential='offline'),None)
        source.stop=asyncio.Event();source.batched=True;slices=[]
        async def work(fn,priority,**kwargs):
            before=db.execute("SELECT COUNT(*) FROM candidate_lifecycle WHERE state='queued'").fetchone()[0]
            result=fn(self.state)
            after=db.execute("SELECT COUNT(*) FROM candidate_lifecycle WHERE state='queued'").fetchone()[0]
            slices.append(after-before)
            if after==50:source.stop.set()
            return result
        source.work=work
        with patch.object(h.startup,'snapshot',return_value=dict(released=True)),patch.object(h,'plan',return_value=None),patch('meme_machine.solana_selective_source.time.time',return_value=NOW):
            with patch.object(h.rolling,'resume_publication',side_effect=EvidenceUnavailable('offline_slice_fault')):
                with self.assertRaisesRegex(EvidenceUnavailable,'offline_slice_fault'):
                    await source.acquire()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM evidence_bindings').fetchone()[0],0)
            self.assertFalse(hasattr(self.state,'development_cursors'))
            self.assertFalse(hasattr(self.state,'development_poll_at'))
            await asyncio.wait_for(source.acquire(),2)
        self.assertTrue(all(0<count<=DEVELOPMENT_BATCH for count in slices),slices)
        self.assertEqual(sum(slices),50)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM candidate_lifecycle WHERE state='queued' AND deadline=?",(NOW+150,)).fetchone()[0],50)
        self.assertIsNone(db.execute("SELECT 1 FROM evidence_bindings WHERE address='quiet'").fetchone())
        self.assertEqual(db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)

    async def test_rolling_waits_for_durable_control_catchup_without_granting_economic_coverage(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
        source.control_bootstrap_tip=1000
        waiting=asyncio.create_task(source.wait_current_control())
        await asyncio.sleep(.01);self.assertFalse(waiting.done())
        source.control_committed_slot=999
        await asyncio.sleep(.06);self.assertFalse(waiting.done())
        source.control_committed_slot=1000
        # A replay reaching the process's old bootstrap tip is not current.
        source.control_committed_market_time=time.time()-136
        await asyncio.sleep(.06);self.assertFalse(waiting.done())
        source.control_committed_market_time=time.time()
        await asyncio.wait_for(waiting,.1)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)

    async def test_recent_but_unpublished_or_future_control_never_opens_logs(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
        source.control_bootstrap_tip=1000;source.control_committed_slot=1000
        waiting=asyncio.create_task(source.wait_current_control())
        await asyncio.sleep(.06);self.assertFalse(waiting.done())
        source.control_committed_market_time=time.time()+60
        await asyncio.sleep(.06);self.assertFalse(waiting.done())
        source.control_committed_market_time=time.time()
        source.control_committed_slot=999
        await asyncio.sleep(.06);self.assertFalse(waiting.done())
        source.control_committed_slot=1001
        await asyncio.wait_for(waiting,.1)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)

    async def test_stop_during_control_catchup_does_not_open_a_replacement_feed(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
        source.control_bootstrap_tip=1000
        waiting=asyncio.create_task(source.wait_current_control())
        await asyncio.sleep(0);source.stop.set()
        with self.assertRaises(asyncio.CancelledError):await waiting

    async def test_control_commit_gate_reads_sealed_receipt_not_later_unsealed_tip(self):
        from meme_machine.solana_selective_runtime import CONTROL
        source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
        with self.state.writer.transaction():
            for slot,sealed in ((999,1),(1000,0)):
                self.history.db.execute('INSERT INTO stream_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (CONTROL,slot,slot-1,'offline-hash-'+str(slot),'offline-parent',
                     int(NOW),'{"offline":true}','offline-session',NOW,sealed))
        async def work(fn,priority,**kwargs):
            result=fn(self.state);source.stop.set();return result
        source.work=work;q=asyncio.Queue();q.put_nowait(object())
        # Native membership sealing is covered by the existing fence tests;
        # isolate the consumer's choice between sealed and unsealed receipts.
        with patch('meme_machine.solana_selective_source.commit_control'):
            await source.control_commits(q)
        self.assertEqual(source.control_committed_slot,999)
        self.assertEqual(source.control_committed_market_time,int(NOW))
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)


if __name__=='__main__':unittest.main()
