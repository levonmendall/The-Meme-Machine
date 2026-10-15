"""Disposable real-owner callback/recovery contracts; no provider or market replay.

A returned transport callback, a durable joined frame and a preserved replay
obligation are intentionally separate assertions throughout these fixtures.
"""
import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import based58

from meme_machine.solana_candidate_join import CandidateTransactionJoin,CONTINUITY,MAX_PENDING_SLOTS
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_selective_source import SelectiveSource
from meme_machine.solana_selective_runtime import CONTROL
from meme_machine.solana_source_drain import (
    AcceptedQueue,CONTROL_RECOVERY_KEY,HANDLER_RECOVERY_KEY,HandlerLedger,
    preserve_control_recovery,preserve_handlers,
)
from meme_machine.yellowstone import geyser_pb2 as pb
from tests.test_solana_closure import NOW,state_at


class SourceHandlerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'canonical.sqlite'
        self.state,self.history=state_at(self.path)
        self.addCleanup(lambda:self.state.writer.close())
        self.source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64),None)
        self.source.stop=asyncio.Event()

    def marker(self,key=HANDLER_RECOVERY_KEY):
        row=self.state.writer.db.execute('SELECT value FROM service_health WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None

    def no_coverage(self):
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM coverage').fetchone()[0],0)
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)

    def gap(self,lo,hi=None,scope='candidate:pump:fixture'):
        self.history.gap(scope,lo,hi,'interrupted_source_fixture')
        identity=self.state.writer.db.execute('SELECT MAX(id) FROM candidate_gaps').fetchone()[0]
        return dict(kind='CANDIDATE_GAPS',gap_ids=[identity])

    def interrupted(self,*,ledger=None,session='session-one',slot=123,error=None,
            scopes=('candidate:pump:fixture',)):
        ledger=ledger or self.source.handlers
        number=ledger.accept('stream-one',session,'yellowstone','pump','transaction_status',NOW,
            slot=slot,identity='canonical-signature',scopes=scopes)
        ledger.phase('CANDIDATE_JOIN')
        ledger.fail(number,error or asyncio.CancelledError())
        return number,ledger.pending(session)

    def status(self,slot=123):
        update=pb.SubscribeUpdate(filters=['0'])
        update.transaction_status.slot=slot
        update.transaction_status.signature=bytes(range(64))
        return update

    async def test_returned_native_callback_is_not_a_durable_queue_or_coverage_receipt(self):
        update=self.status();seen=[]
        async def handler(value,size,at):
            self.source.handlers.phase('CANDIDATE_JOIN')
            seen.append((value,size,at))
        handler.source_session='session-returned'
        await self.source.handle_native(handler,update,update.ByteSize(),NOW,'stream-returned','pump')
        census=self.source.drain_snapshot();ledger=census['handler_accounting']
        self.assertEqual(seen,[(update,update.ByteSize(),NOW)])
        self.assertEqual((ledger['accepted'],ledger['returned'],ledger['active']),(1,1,0))
        self.assertEqual(ledger['records'],[])
        self.assertEqual(census['queues']['candidate'],dict(accepted=0,committed=0,pending=0))
        self.assertIsNone(self.marker());self.no_coverage()

    async def test_actual_join_bound_retains_exact_failing_native_handler_and_original_error(self):
        join=CandidateTransactionJoin({},set(),filtered_from_slot=1,clock=lambda:1)
        original=[]
        async def handler(update,size,seen):
            self.source.handlers.phase('CANDIDATE_JOIN')
            try:join.feed(update,size,seen)
            except EvidenceUnavailable as exc:original.append(exc);raise
        handler.source_session='bounded-join-session'
        handler.source_scopes=('candidate:pump:fixture',)
        for slot in range(1,MAX_PENDING_SLOTS+1):
            update=pb.SubscribeUpdate(filters=[CONTINUITY]);update.block_meta.slot=slot
            await self.source.handle_native(handler,update,update.ByteSize(),NOW,'bounded-join-stream','pump')
        update=pb.SubscribeUpdate(filters=[CONTINUITY]);update.block_meta.slot=MAX_PENDING_SLOTS+1
        with self.assertRaisesRegex(EvidenceUnavailable,'yellowstone_census_buffer_bound') as caught:
            await self.source.handle_native(handler,update,update.ByteSize(),NOW,'bounded-join-stream','pump')
        self.assertIs(caught.exception,original[0])
        pending=self.source.handlers.pending('bounded-join-session')
        self.assertEqual(len(pending),1)
        row=pending[0]
        self.assertEqual((row['stream'],row['session'],row['kind'],row['slot'],row['phase'],row['state']),
            ('bounded-join-stream','bounded-join-session','block_meta',MAX_PENDING_SLOTS+1,'CANDIDATE_JOIN','FAILED'))
        self.assertEqual(self.source.handlers.snapshot()['returned'],MAX_PENDING_SLOTS)
        retained=preserve_handlers(self.state,self.source.handlers,pending,self.gap(1))
        self.source.handlers.preserved(retained)
        census=self.source.drain_snapshot()
        self.assertEqual(census['handler_accounting']['recoverable'],1)
        self.assertEqual(census['pending_handlers'],1)
        self.assertEqual(census['settled_handlers'],MAX_PENDING_SLOTS)
        self.assertNotEqual(census['state'],'DRAINED');self.no_coverage()

    async def test_cancel_after_accept_while_queue_full_preserves_exact_identity_without_fake_commit(self):
        queue=AcceptedQueue(1,lambda a,c:self.source.frame_census('control',a,c))
        await queue.put('accepted-first-frame');entered=asyncio.Event()
        async def handler(update,size,seen):
            self.source.handlers.phase('CONTROL_QUEUE');entered.set()
            await queue.put('blocked-second-frame')
        handler.source_session='capacity-session';handler.source_scopes=(CONTROL,);update=self.status()
        task=asyncio.create_task(self.source.handle_native(handler,update,update.ByteSize(),NOW,'capacity-stream','shared'))
        await asyncio.wait_for(entered.wait(),.5);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        row=self.source.handlers.pending('capacity-session')[0]
        self.assertEqual((row['slot'],row['identity'],row['phase'],row['state']),
            (123,based58.b58encode(bytes(range(64))).decode(),'CONTROL_QUEUE','INTERRUPTED'))
        self.assertEqual(self.source.drain_snapshot()['queues']['control'],dict(accepted=1,committed=0,pending=1))
        obligation=preserve_control_recovery(self.state,123,123)
        retained=preserve_handlers(self.state,self.source.handlers,[row],dict(kind='CONTROL_REPLAY',**obligation))
        self.source.handlers.preserved(retained)
        census=self.source.drain_snapshot()
        self.assertFalse(census['all_accepted_committed'])
        self.assertEqual((census['settled_handlers'],census['handler_accounting']['recoverable']),(0,1))
        self.assertEqual(queue.get_nowait(),'accepted-first-frame');self.no_coverage()

    async def test_concurrent_handlers_keep_their_actual_task_owner_and_original_failure(self):
        entered=[asyncio.Event(),asyncio.Event()];release=[asyncio.Event(),asyncio.Event()]
        original=sqlite3.OperationalError('api_key=never-publish-this-error-text')
        async def first(update,size,seen):
            self.source.handlers.phase('CONTROL_JOIN');entered[0].set();await release[0].wait()
        async def second(update,size,seen):
            self.source.handlers.phase('CONTROL_QUEUE');entered[1].set();await release[1].wait();raise original
        first.source_session='owner-one';second.source_session='owner-two'
        u=self.status(123);v=self.status(124)
        tasks=[asyncio.create_task(self.source.handle_native(first,u,u.ByteSize(),NOW,'stream-one','shared')),
            asyncio.create_task(self.source.handle_native(second,v,v.ByteSize(),NOW,'stream-two','shared'))]
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)),.5)
            records=self.source.handlers.snapshot()['records']
            self.assertEqual({(r['stream'],r['session'],r['slot'],r['phase']) for r in records},
                {('stream-one','owner-one',123,'CONTROL_JOIN'),('stream-two','owner-two',124,'CONTROL_QUEUE')})
            release[0].set();await tasks[0]
            release[1].set()
            with self.assertRaises(sqlite3.OperationalError) as caught:await tasks[1]
            self.assertIs(caught.exception,original)
            snapshot=self.source.handlers.snapshot()
            self.assertEqual((snapshot['accepted'],snapshot['returned'],snapshot['failed']),(2,1,1))
            self.assertEqual(snapshot['records'][0]['session'],'owner-two')
            self.assertNotIn('never-publish',json.dumps(snapshot))
            self.assertNotIn('api_key',json.dumps(snapshot))
        finally:
            for task in tasks:
                if not task.done():task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)

    async def test_fabricated_or_noncovering_candidate_gap_cannot_claim_recoverability(self):
        _,pending=self.interrupted(slot=123)
        for recovery in ({},dict(kind='CANDIDATE_GAPS',gap_ids=[]),
                dict(kind='CANDIDATE_GAPS',gap_ids=[999999]),self.gap(124,130),
                self.gap(123,123,scope='candidate:pumpswap:wrong-owner')):
            with self.subTest(recovery=recovery):
                with self.assertRaisesRegex(EvidenceUnavailable,'source_handler_recovery_unverified'):
                    preserve_handlers(self.state,self.source.handlers,pending,recovery)
                self.assertIsNone(self.marker())
        self.assertEqual(self.source.handlers.snapshot()['recoverable'],0);self.no_coverage()

    async def test_control_recovery_must_match_actual_persisted_boundary_and_cover_handler(self):
        _,pending=self.interrupted(slot=123,scopes=(CONTROL,))
        obligation=preserve_control_recovery(self.state,123,124)
        for altered in (dict(obligation,coverage_after_id=obligation['coverage_after_id']+1),
                dict(obligation,lower_slot=122),dict(lower_slot=124,upper_slot=124,coverage_after_id=0)):
            with self.subTest(altered=altered):
                with self.assertRaisesRegex(EvidenceUnavailable,'source_handler_recovery_unverified'):
                    preserve_handlers(self.state,self.source.handlers,pending,dict(kind='CONTROL_REPLAY',**altered))
                self.assertIsNone(self.marker())
        wrong_ledger=HandlerLedger('wrong-control-scope')
        _,wrong_scope=self.interrupted(ledger=wrong_ledger,slot=123)
        with self.assertRaisesRegex(EvidenceUnavailable,'source_handler_recovery_unverified'):
            preserve_handlers(self.state,wrong_ledger,wrong_scope,dict(kind='CONTROL_REPLAY',**obligation))
        self.assertIsNone(self.marker())
        retained=preserve_handlers(self.state,self.source.handlers,pending,dict(kind='CONTROL_REPLAY',**obligation))
        self.source.handlers.preserved(retained)
        self.assertEqual(self.marker(CONTROL_RECOVERY_KEY),obligation)
        self.assertEqual(self.marker()['records'][0]['recovery'],dict(kind='CONTROL_REPLAY',**obligation))
        self.assertEqual(self.source.handlers.snapshot()['returned'],0);self.no_coverage()

    async def test_multi_scope_handler_requires_the_complete_original_scope_set(self):
        scopes=('candidate:pump:fixture','candidate:pumpswap:fixture')
        _,pending=self.interrupted(slot=123,scopes=scopes)
        first=self.gap(123,124,scope=scopes[0]);second=self.gap(123,124,scope=scopes[1])
        with self.assertRaisesRegex(EvidenceUnavailable,'source_handler_recovery_unverified'):
            preserve_handlers(self.state,self.source.handlers,pending,first)
        self.assertIsNone(self.marker())
        recovery=dict(kind='CANDIDATE_GAPS',gap_ids=first['gap_ids']+second['gap_ids'])
        retained=preserve_handlers(self.state,self.source.handlers,pending,recovery)
        self.source.handlers.preserved(retained)
        row=self.marker()['records'][0]
        self.assertEqual((row['scope_count'],row['scope_hash']),(2,HandlerLedger.scope_hash(scopes)))
        self.assertEqual(row['state'],'RECOVERABLE')
        self.assertEqual(self.source.handlers.snapshot()['returned'],0);self.no_coverage()

    async def test_unlocated_interrupted_handler_is_retained_unresolved_without_invented_slot(self):
        _,pending=self.interrupted(slot=None)
        retained=preserve_handlers(self.state,self.source.handlers,pending,None)
        self.source.handlers.preserved(retained)
        persisted=self.marker()['records'][0]
        self.assertIsNone(persisted['slot']);self.assertIsNone(persisted['recovery'])
        self.assertEqual(persisted['state'],'INTERRUPTED')
        snapshot=self.source.handlers.snapshot()
        self.assertEqual((snapshot['recoverable'],snapshot['unresolved'],snapshot['returned']),(0,1,0))
        self.no_coverage()

    async def test_outer_rollback_cannot_publish_handler_recovery_or_gap(self):
        _,pending=self.interrupted();original=RuntimeError('injected-after-handler-preservation')
        with self.assertRaises(RuntimeError) as caught:
            with self.state.writer.transaction():
                recovery=self.gap(123)
                retained=preserve_handlers(self.state,self.source.handlers,pending,recovery)
                self.assertEqual(retained[0]['state'],'RECOVERABLE')
                raise original
        self.assertIs(caught.exception,original)
        self.assertIsNone(self.marker())
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM candidate_gaps').fetchone()[0],0)
        self.assertFalse(self.state.writer.db.in_transaction)
        self.assertEqual(self.source.handlers.snapshot()['unresolved'],1)
        self.assertEqual(self.source.handlers.snapshot()['recoverable'],0);self.no_coverage()

    async def test_commit_failure_keeps_original_error_and_no_false_durable_disposition(self):
        _,pending=self.interrupted();recovery=self.gap(123)
        original=sqlite3.OperationalError('original-handler-recovery-commit-failure')
        execute=self.state.writer._transaction_statement
        def fail_commit(sql,phase):
            if phase=='commit':raise original
            return execute(sql,phase)
        with patch.object(self.state.writer,'_transaction_statement',side_effect=fail_commit):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                preserve_handlers(self.state,self.source.handlers,pending,recovery)
        self.assertIs(caught.exception,original)
        self.assertIsNone(self.marker());self.assertFalse(self.state.writer.db.in_transaction)
        self.assertEqual(self.source.handlers.snapshot()['recoverable'],0)
        self.assertEqual(self.source.handlers.snapshot()['returned'],0);self.no_coverage()

    async def test_restart_preserves_old_run_identity_and_does_not_erase_pending_on_new_head(self):
        _,pending=self.interrupted();recovery=self.gap(123)
        retained=preserve_handlers(self.state,self.source.handlers,pending,recovery)
        self.source.handlers.preserved(retained);before=self.marker()
        self.state.writer.close();self.state,self.history=state_at(self.path)
        self.assertEqual(self.marker(),before)
        new=HandlerLedger('successor-run');_,other=self.interrupted(ledger=new,session='successor-session',slot=124)
        later=preserve_handlers(self.state,new,other,self.gap(124))
        new.preserved(later)
        with self.state.writer.transaction():
            self.state.writer.db.execute('INSERT OR REPLACE INTO cursors(scope,slot,updated) VALUES(?,?,?)',
                ('control:solana',999999,NOW+100))
        records=self.marker()['records']
        self.assertEqual(records[0],before['records'][0])
        self.assertEqual({(r['run'],r['id']) for r in records},
            {(self.source.handlers.run,1),('successor-run',1)})
        self.assertEqual(new.snapshot()['returned'],0)
        self.assertEqual(new.snapshot()['recoverable'],1);self.no_coverage()

    async def test_retained_handler_bound_fails_closed_without_overwriting_earlier_identity(self):
        ledger=HandlerLedger('bounded-run')
        for slot in range(1,ledger.maximum_records+1):
            number=ledger.accept('stream','session','yellowstone','pump','block_meta',NOW,slot=slot)
            ledger.fail(number,asyncio.CancelledError())
        before=ledger.snapshot()
        with self.assertRaisesRegex(EvidenceUnavailable,'source_handler_record_bound'):
            ledger.accept('stream','session','yellowstone','pump','block_meta',NOW,slot=999999)
        after=ledger.snapshot()
        self.assertFalse(after['valid'])
        self.assertEqual(after['accepted'],before['accepted'])
        self.assertEqual(after['records'],before['records'])
        self.assertEqual(len(after['records']),ledger.maximum_records)

    async def test_handler_metadata_byte_bound_and_phase_allowlist_exclude_arbitrary_text(self):
        ledger=HandlerLedger('private-metadata-bound')
        number=ledger.accept('stream','session','yellowstone','shared','slot',NOW,slot=123)
        with self.assertRaises(ValueError):
            ledger.phase('CONTROL_JOIN',expanded_sql='api_key=never-publish-frame-local')
        self.assertNotIn('never-publish',json.dumps(ledger.snapshot()))
        ledger.fail(number,RuntimeError('api_key=never-publish-exception'))
        self.assertNotIn('never-publish',json.dumps(ledger.snapshot()))
        with self.assertRaisesRegex(EvidenceUnavailable,'source_handler_record_bound'):
            ledger.accept('stream','session','yellowstone','shared','slot',NOW,slot=123,
                identity='x'*(ledger.maximum_bytes+1))
        snapshot=ledger.snapshot()
        self.assertFalse(snapshot['valid'])
        self.assertLessEqual(len(json.dumps(snapshot)),ledger.maximum_bytes+4096)


if __name__=='__main__':unittest.main()
