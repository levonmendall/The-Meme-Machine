"""Original canonical economics, bounded FIFO batching and durable failure."""
import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import based58

from meme_machine.solana_candidate_join import YellowstoneTransactionFrame
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import (
    CandidateCommitQueue,SelectiveSource,commit_candidates,commit_candidate_batch,
    CANDIDATE_COMMIT_BATCH,CANDIDATE_COMMIT_BYTES,
)
from meme_machine.yellowstone import geyser_pb2 as pb
from tests.test_solana_closure import NOW,state_at
from tests.test_solana_selective_evidence import FIXTURE


def frame(slot,*,logs=True):
    u=pb.SubscribeUpdate();b=u.block;b.slot=slot;b.parent_slot=slot-1
    b.blockhash=str(slot);b.parent_blockhash=str(slot-1);b.block_time.timestamp=int(NOW)
    if not logs:return YellowstoneTransactionFrame(u,100,NOW,replay_from_slot=100)
    tx=copy.deepcopy(FIXTURE['pump'][0]);sig=based58.b58encode(slot.to_bytes(64,'little')).decode()
    tx['transaction']['signatures']=[sig];tx['slot']=slot;tx['transactionIndex']=0;tx['blockTime']=int(NOW)
    return YellowstoneTransactionFrame(u,100,NOW,replay_from_slot=100,
        log_transactions=(tx,),candidate_statuses=((sig,0,(program_scope('pump'),),None,NOW),))


class CandidateCommitBatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state,self.h=state_at(Path(self.tmp.name)/'canonical.sqlite')
        self.addCleanup(self.state.writer.close)
        self.addresses={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}

    def snapshot(self,h):
        tables=('rolling_economic_events','rolling_economic_addresses','candidate_blocks',
            'candidate_pending_proofs','candidate_coverage','candidate_history_outbox')
        return {t:h.db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in tables}

    async def test_batch_retains_original_economics_order_proofs_and_restart(self):
        other,h=state_at(Path(self.tmp.name)/'original.sqlite')
        try:
            frames=[frame(n) for n in range(100,108)]
            for f in frames:commit_candidates(other,f,self.addresses,'session',publish=False)
            statements=[];self.h.db.set_trace_callback(statements.append)
            commit_candidate_batch(self.state,frames,self.addresses,'session',publish=False)
            self.assertEqual(self.snapshot(self.h),self.snapshot(h))
            self.assertEqual(sum(sql=='COMMIT' for sql in statements),1)
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
            before=self.snapshot(self.h);self.state.writer.close()
            self.state,self.h=state_at(self.state.writer.path)
            self.assertEqual(self.snapshot(self.h),before)
            self.h.lifecycle.publish();h.lifecycle.publish()
            self.assertEqual(self.snapshot(self.h),self.snapshot(h))
        finally:other.writer.close()

    async def test_failed_batch_rolls_back_economics_and_keeps_a_durable_gap(self):
        frames=[frame(n) for n in range(100,104)]
        frames[2].update.block.parent_slot=99
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_native_parent_gap'):
            commit_candidate_batch(self.state,frames,self.addresses,'session')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_blocks').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        self.assertFalse(self.h.db.in_transaction)
        self.state.writer.close();self.state,self.h=state_at(self.state.writer.path)
        self.assertEqual(self.h.db.execute("SELECT scope,lo,hi FROM candidate_gaps WHERE reason='candidate_native_batch_failed' ORDER BY scope").fetchall(),
            [(scope,100,103) for scope in sorted(self.addresses.values())])

    async def test_restart_replay_reconstructs_linkage_and_repairs_only_real_coverage(self):
        frames=[frame(n) for n in range(100,104)]
        commit_candidate_batch(self.state,frames,self.addresses,'old-session')
        before=self.h.db.execute('SELECT identity,first_seen,hash FROM rolling_economic_events ORDER BY identity').fetchall()
        for scope in self.addresses.values():self.h.gap(scope,100,102,'ordinary_disconnect')
        commit_candidate_batch(self.state,[frames[0]],self.addresses,'reconnected')
        self.assertEqual({r[0] for r in self.h.db.execute('SELECT slot FROM candidate_blocks')},{100})
        self.assertEqual(self.h.rolling.missing('pump',program_scope('pump'),100,102),[(100,102)])
        commit_candidate_batch(self.state,frames[1:],self.addresses,'reconnected')
        self.assertEqual(self.h.rolling.missing('pump',program_scope('pump'),100,102),[])
        self.assertEqual(self.h.db.execute('SELECT identity,first_seen,hash FROM rolling_economic_events ORDER BY identity').fetchall(),before)
        self.assertEqual({r[0] for r in self.h.db.execute('SELECT slot FROM candidate_blocks')},{103})
        # Cached block identity is not permission to accept a conflicting replay.
        changed=copy.deepcopy(frames[-1]);changed.update.block.blockhash='other-bank'
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_replay_receipt_conflict'):
            commit_candidate_batch(self.state,[changed],self.addresses,'third-session')

    async def test_ready_burst_commits_once_and_quiet_frame_is_immediate(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),None)
        source.batched=True # The actual shared service owns its separate publisher.
        source.stop=asyncio.Event();q=CandidateCommitQueue();calls=[];statements=[]
        self.h.db.set_trace_callback(statements.append)
        async def work(fn,priority,**kw):
            calls.append(priority);result=fn(self.state);source.stop.set();return result
        source.work=work
        for slot in range(100,108):await q.put(frame(slot))
        await asyncio.wait_for(source.candidate_commits(q,self.addresses,'session',priority=0),.5)
        self.assertEqual(calls,[0]);self.assertEqual(q.count,0);self.assertEqual(q.bytes,0)
        self.assertEqual(sum(sql=='COMMIT' for sql in statements),1)
        self.assertEqual(self.h.db.execute('SELECT COUNT(DISTINCT signature) FROM rolling_economic_events').fetchone()[0],8)
        source.stop.clear();await q.put(frame(108))
        await asyncio.wait_for(source.candidate_commits(q,self.addresses,'session',priority=0),.1)
        self.assertEqual(calls,[0,0]);self.assertEqual(q.count,0)

    async def test_owner_held_frames_keep_count_and_byte_capacity_reserved(self):
        q=CandidateCommitQueue()
        for slot in range(100,100+CANDIDATE_COMMIT_BATCH):await q.put(frame(slot,logs=False))
        rows=await q.batch()
        waiting=asyncio.create_task(q.put(frame(200,logs=False)))
        await asyncio.sleep(0);self.assertFalse(waiting.done())
        self.assertEqual(q.count,CANDIDATE_COMMIT_BATCH)
        q.done(rows);await waiting;self.assertEqual(q.count,1)
        remaining=await q.batch();q.done(remaining);await q.join()
        self.assertEqual(q.bytes,0)
        f=frame(300,logs=False)
        f=YellowstoneTransactionFrame(f.update,CANDIDATE_COMMIT_BYTES,NOW)
        await q.put(f);rows=await q.batch()
        waiting=asyncio.create_task(q.put(frame(301,logs=False)))
        await asyncio.sleep(0);self.assertFalse(waiting.done())
        q.done(rows);await waiting;q.done(await q.batch())
        oversized=YellowstoneTransactionFrame(f.update,CANDIDATE_COMMIT_BYTES+1,NOW)
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_commit_batch_bound'):await q.put(oversized)


if __name__=='__main__':unittest.main()
