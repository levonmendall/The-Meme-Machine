"""A genuine failed preparation batch needs original archive/FULL ACK recovery.

The process-pool failure, joins, queue census, native writer, archive pages and
consumer are real disposable paths. No recovery or financial verdict is mocked.
"""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import based58

from meme_machine import solana_source_drain as drain
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.solana_candidate_join import CandidateTransactionJoin
from meme_machine.solana_evidence_plane import EvidenceUnavailable,canonical,digest
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS,economic_records
from meme_machine.solana_selective_source import (
    CandidateCommitQueue,SelectiveSource,commit_candidate_batch,commit_control,preserve_subscription_handoff)
from meme_machine.yellowstone import geyser_pb2 as pb
from tests import test_archive_recovered_session as archive_fixture
from tests import test_session_economic_recovery as session_fixture
from tests.test_solana_selective_evidence import FIXTURE


HEAD=457925003
FAMILIES=('pump','pumpswap')
SCOPES=tuple(program_scope(family) for family in FAMILIES)
PIN_NAMES=('PREPARATION_RECOVERY_CENSUS','PREPARATION_RECOVERY_LEDGER','PREPARATION_RECOVERY_SESSION',
    'PREPARATION_RECOVERY_OBSERVATIONS','PREPARATION_RECOVERY_HEADS','PREPARATION_RECOVERY_GAPS')


class PreparationFailedRecoveryTests(unittest.TestCase):
    facts=session_fixture.SessionEconomicRecoveryTests.facts
    value=session_fixture.SessionEconomicRecoveryTests.value
    put=session_fixture.SessionEconomicRecoveryTests.put
    changed_owner=session_fixture.SessionEconomicRecoveryTests.changed_owner
    descriptor=session_fixture.SessionEconomicRecoveryTests.descriptor
    preserve=session_fixture.SessionEconomicRecoveryTests.preserve
    verify=session_fixture.SessionEconomicRecoveryTests.verify
    publish=session_fixture.SessionEconomicRecoveryTests.publish
    recover=session_fixture.SessionEconomicRecoveryTests.recover
    refused=session_fixture.SessionEconomicRecoveryTests.refused
    clean_session=session_fixture.SessionEconomicRecoveryTests.clean_session
    assert_original_evidence=session_fixture.SessionEconomicRecoveryTests.assert_original_evidence

    def native_frame(self,slot,*,parent=None):
        value=session_fixture.SessionEconomicRecoveryTests.native_frame(self,slot,parent=parent)
        pinned=self.production_pins['PREPARATION_RECOVERY_HEADS']['pump']
        if slot==HEAD:
            value.update.block.blockhash=pinned['hash']
            value.update.block.parent_blockhash=pinned['previous_hash']
        elif (slot-1 if parent is None else parent)==HEAD:
            value.update.block.parent_blockhash=pinned['hash']
        return value

    def setUp(self):
        self.production_pins={name:deepcopy(getattr(drain,name)) for name in PIN_NAMES}
        self.base=archive_fixture.ArchiveRecoveredSessionTests('runTest')
        self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.state,self.history,self.db=self.base.state,self.base.history,self.base.db
        self.cache=self.base.cache;self.life=self.history.lifecycle
        self.old_source=self.base.old_source_raw;self.old_handler=self.base.old_handler_raw
        self.old_handler_record=json.loads(self.old_handler)['records'][0]
        self.old_pending=self.db.execute("SELECT * FROM candidate_pending_proofs WHERE id='old-proof'").fetchall()
        self.old_gaps=self.db.execute('SELECT * FROM candidate_gaps WHERE id IN (39592,39593) ORDER BY id').fetchall()
        self.financial_before=self.base.funding.facts()
        self.base.at=1792216120.
        self.incident=self.prepare_failed_batch()
        self.fixture_pins=dict(PREPARATION_RECOVERY_CENSUS=hashlib.sha256(self.incident['failed_raw'].encode()).hexdigest(),
            PREPARATION_RECOVERY_LEDGER=hashlib.sha256(self.incident['handler_raw'].encode()).hexdigest(),
            PREPARATION_RECOVERY_OBSERVATIONS=self.incident['observations'],
            PREPARATION_RECOVERY_HEADS=self.incident['heads'],PREPARATION_RECOVERY_GAPS=self.incident['gap_pins'])
        for name,value in self.fixture_pins.items():self.enterContext(patch.object(drain,name,value))

    def prepare_failed_batch(self):
        source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64),None)
        source.contained_observation=True
        source.stop=asyncio.Event();source.batched=True;source.history_separated=True
        started=source.drain_snapshot()
        started.update(historical_unknown_handlers=2,historical_source_drain_sha256=self.base.incident.old_hash,
            historical_recovery_verified=False)
        boundary=drain.begin_source_observation(self.state,self.old_source,started,
            handler_boundary=self.value(drain.HANDLER_RECOVERY_KEY))
        session=drain.PREPARATION_RECOVERY_SESSION
        addresses={PROGRAMS[family]:program_scope(family) for family in FAMILIES}
        # A genuine linked fixture bridge avoids materializing 96,000 blocks.
        old_control=self.db.execute("SELECT MAX(slot) FROM stream_receipts WHERE scope='control:solana'").fetchone()[0]
        bridge=self.native_frame(HEAD-1,parent=old_control)
        bridge.update.block.parent_blockhash=self.db.execute("SELECT hash FROM stream_receipts WHERE scope='control:solana' AND slot=?",(old_control,)).fetchone()[0]
        bridge.update.block.blockhash=drain.PREPARATION_RECOVERY_HEADS['pump']['previous_hash']
        commit_control(self.state,bridge)
        head=replace(self.native_frame(HEAD),seen=1792216116.314142)
        head.update.block.blockhash=drain.PREPARATION_RECOVERY_HEADS['pump']['hash']
        head.update.block.parent_blockhash=drain.PREPARATION_RECOVERY_HEADS['pump']['previous_hash']
        head.update.block.block_time.timestamp=1792215913
        commit_control(self.state,head)
        commit_candidate_batch(self.state,[head],addresses,session,publish=False)
        join=CandidateTransactionJoin(addresses,set(),filtered_from_slot=457923754,
            clock=lambda:self.base.at)
        queue=CandidateCommitQueue(lambda accepted,committed:source.frame_census('rolling',accepted,committed))
        async def native(update,size,seen):
            source.handlers.phase('CANDIDATE_JOIN')
            frame=join.feed(update,size,seen)
            if frame is not None:
                source.handlers.phase('CANDIDATE_QUEUE');await queue.put(frame)
        native.source_session=session;native.source_scopes=SCOPES
        async def owner(fn,priority,**options):return fn(self.state)
        source.work=owner
        async def produce():
            for slot in range(HEAD+1,HEAD+7):
                meta=pb.SubscribeUpdate(filters=['b']);block=meta.block_meta
                block.slot,block.parent_slot=slot,slot-1
                block.blockhash,block.parent_blockhash=str(slot),str(slot-1)
                block.block_time.timestamp=int(self.base.at)-1
                await source.handle_native(native,meta,meta.ByteSize(),self.base.at,'fixture-native','pump')
                final=pb.SubscribeUpdate(filters=['f']);final.slot.slot=slot;final.slot.parent=slot-1
                final.slot.status=pb.SLOT_FINALIZED
                await source.handle_native(native,final,final.ByteSize(),self.base.at,'fixture-native','pump')
            self.assertEqual((join.completed,queue.count),(HEAD+6,6))
            self.assertEqual(source.handlers.snapshot()['returned'],source.handlers.snapshot()['accepted'])
            for slot in (HEAD+7,HEAD+124):
                sig=based58.b58encode(slot.to_bytes(64,'little')).decode()
                self.assertIsNone(join.feed_log(slot,sig,[],None,self.base.at))
            # Kill only this owned disposable worker. Its real broken executor
            # rejects the original preparation submission with BrokenProcessPool.
            with ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('fork')) as executor:
                with self.assertRaises(BrokenProcessPool):executor.submit(os._exit,7).result(timeout=5)
                source.preparation_executor=executor;source.preparation_lock=asyncio.Lock()
                with self.assertRaises(BrokenProcessPool):
                    await source.candidate_commits(queue,addresses,session,rolling=True,priority=0)
            self.assertEqual(queue.count,6)
        asyncio.run(produce())
        failure=self.db.execute("SELECT id,kind,body,at FROM acquisition_observations WHERE kind='candidate_economic_preparation_failed' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(json.loads(failure[2]),dict(error='evidence_worker_failed:BrokenProcessPool',checkpoint_advanced=False))
        join_body=dict(plane='rolling',session=session,**join.diagnostic(),accepted_pending=queue.count,
            accepted_pending_bytes=queue.bytes,drained=False)
        source.retain_join_state('rolling',session,join_body,queue,state='CLOSED',monotonic=1.)
        observed=dict(join_body,replay_from_slot=457923754,recovery_obligations=[],
            handler_dispositions=[],complete_history_claim=False)
        with self.state.writer.transaction():
            for scope in SCOPES:
                self.history.gap(scope,457923754,None,'candidate_live_disconnect_or_filter_rebuild')
                observed['recovery_obligations'].append(dict(scope=scope,lower_slot=457923754,upper_slot=None))
            self.history._observation(None,'source_session_drain',observed)
        closed=self.db.execute("SELECT id,kind,body,at FROM acquisition_observations WHERE kind='source_session_drain' ORDER BY id DESC LIMIT 1").fetchone()
        source.diagnostic('native_join_closed',join_body)
        asyncio.run(source.flush_diagnostics())
        joined=self.db.execute("SELECT id,kind,body,at FROM acquisition_observations WHERE kind='native_join_closed' ORDER BY id DESC LIMIT 1").fetchone()
        source.source_drain.update(state='RECOVERY_REQUIRED',terminal=True,terminal_record_unavailable=True,
            terminal_at_monotonic=started['started_at_monotonic']+1,closed_sessions=2,
            preserved_partial_sessions=1,unpreserved_sessions=0)
        failed=source.drain_snapshot()
        failed.update(historical_unknown_handlers=2,historical_source_drain_sha256=self.base.incident.old_hash,
            historical_recovery_verified=False)
        drain.publish_source_drain(self.state,self.old_source,failed,handler_boundary=self.old_handler,
            contained_observation=True,observation_boundary=boundary)
        observations={name:(row[0],hashlib.sha256(row[2].encode()).hexdigest(),len(row[2].encode()),row[3])
            for name,row in (('failure',failure),('closed',closed),('join',joined))}
        fields=('scope','slot','parent','hash','previous_hash','market_time','seen','session','census_hash')
        heads={family:dict(zip(fields,self.db.execute('SELECT scope,slot,parent,hash,previous_hash,market_time,seen,session,census_hash FROM candidate_blocks WHERE scope=?',
            (program_scope(family),)).fetchone())) for family in FAMILIES}
        gap_pins={};origins=[]
        for family in FAMILIES:
            selected=[]
            for reason in ('candidate_economic_preparation_failed','candidate_live_disconnect_or_filter_rebuild'):
                row=self.db.execute('SELECT id,lo,hi,created FROM candidate_gaps WHERE scope=? AND reason=? ORDER BY id DESC LIMIT 1',
                    (program_scope(family),reason)).fetchone()
                selected.append(row)
            gap_pins[family]=tuple(selected);origins.append(selected[1][0])
        return dict(head=HEAD,upper=HEAD+6,run=source.handlers.run,session=session,source=source,
            observation_id=closed[0],observed=observed,failed=json.loads(self.value(drain.OBSERVATION_DRAIN_KEY)),
            failed_raw=self.value(drain.OBSERVATION_DRAIN_KEY),handler_raw=self.value(drain.HANDLER_RECOVERY_KEY),
            gaps=origins,observations=observations,heads=heads,gap_pins=gap_pins)

    def test_production_pins_and_generic_rejection_remain_intact(self):
        pins=self.production_pins
        self.assertEqual(pins['PREPARATION_RECOVERY_CENSUS'],'07c27ae3ee01dc53b204e01ed145c27f8ee2cbb43f502ed4e5eee99de1bbd197')
        self.assertEqual(pins['PREPARATION_RECOVERY_LEDGER'],'3d49d46228d8b2448eed3cbdff75faabfdf33e73a4acb218c0c0dd5a4c867016')
        self.assertEqual(pins['PREPARATION_RECOVERY_SESSION'],'fad3c95d2dc54de4aa7594635d06b8d2')
        self.assertEqual(pins['PREPARATION_RECOVERY_OBSERVATIONS']['failure'],(235833,'bcf9f65c3f82b1b7181539ecae63272ecdbcd9fecf1b076d1f11bb0e0462b453',80,1792216119.3346004))
        self.assertEqual(pins['PREPARATION_RECOVERY_OBSERVATIONS']['closed'],(235834,'b53e22e8bf2bbe28ff2ec57ed4382d544aa07bfadd7da8527fdff2aed7155ddb',846,1792216119.6502507))
        self.assertEqual(pins['PREPARATION_RECOVERY_OBSERVATIONS']['join'],(235839,'a10221f228bd218f501cb59c90c53a3d492de00efdd059c009a668461cbd3390',507,1792216119.6681688))
        self.assertEqual([pins['PREPARATION_RECOVERY_HEADS'][f]['slot'] for f in FAMILIES],[HEAD,HEAD])
        with self.assertRaises(EvidenceUnavailable):
            drain._economic_failed_inputs(self.db,self.incident['failed_raw'],self.incident['handler_raw'],self.incident['observation_id'])

    def test_genuine_failed_pool_batch_descriptor_is_pure_and_not_recovery(self):
        before=self.facts();changes=self.db.total_changes
        self.db.execute('PRAGMA query_only=ON')
        try:descriptor=self.descriptor()
        finally:self.db.execute('PRAGMA query_only=OFF')
        self.assertEqual((descriptor['lower_slot'],descriptor['upper_slot'],descriptor['accepted_pending']),(HEAD,HEAD+6,6))
        self.assertEqual((descriptor['tail_lower_slot'],descriptor['tail_upper_slot']),(HEAD+7,HEAD+124))
        self.assertEqual(descriptor['handler_records'],[])
        self.assertEqual(self.db.total_changes,changes);self.assertEqual(self.facts(),before)
        reference=self.preserve(descriptor);self.assertEqual(self.preserve(descriptor),reference)
        self.refused(reference);self.refused();self.assert_original_evidence()

    def test_original_archive_full_consumer_ack_and_unavailable_tail_are_required(self):
        reference=self.preserve();_,proofs=self.recover(acknowledge_rows=False)
        self.refused(reference);self.refused()
        self.publish(tuple(proofs.values()));result=self.verify(reference)
        self.assertTrue(result['economic_interval_recovered']);self.assertTrue(result['economic_tail_continuity_verified'])
        self.assertFalse(result['economic_tail_recovered']);self.assertTrue(result['retained_economic_tail_unavailable'])
        for key in ('original_queue_acknowledgement_verified','original_source_drain_pass','callback_completion_demonstrated'):
            self.assertFalse(result[key])
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY),self.incident['failed_raw'])
        self.assertTrue(json.loads(self.value(drain.OBSERVATION_DRAIN_KEY))['terminal_record_unavailable'])
        self.assertEqual(self.db.execute('SELECT DISTINCT slot FROM candidate_blocks').fetchall(),[(HEAD,)])
        self.assert_original_evidence()

    def test_wrong_hash_slot_scope_time_receipt_or_failure_is_refused(self):
        mutations=[("UPDATE service_health SET value=value||' ' WHERE key=?",(drain.OBSERVATION_DRAIN_KEY,)),
            ("UPDATE service_health SET value=value||' ' WHERE key=?",(drain.HANDLER_RECOVERY_KEY,)),
            ('UPDATE candidate_blocks SET slot=slot+1 WHERE scope=?',(SCOPES[0],)),
            ("UPDATE candidate_blocks SET session='foreign' WHERE scope=?",(SCOPES[1],))]
        for name,(identity,checksum,size,at) in self.incident['observations'].items():
            mutations.extend([('UPDATE acquisition_observations SET body=body||\' \' WHERE id=?',(identity,)),
                ('UPDATE acquisition_observations SET at=at+1 WHERE id=?',(identity,)),
                ('DELETE FROM acquisition_observations WHERE id=?',(identity,))])
        for rows in self.incident['gap_pins'].values():
            for row in rows:
                mutations.extend([('UPDATE candidate_gaps SET lo=lo+1 WHERE id=?',(row[0],)),
                    ("UPDATE candidate_gaps SET scope='foreign' WHERE id=?",(row[0],)),
                    ("UPDATE candidate_gaps SET reason='foreign' WHERE id=?",(row[0],))])
        for sql,args in mutations:
            with self.subTest(sql=sql,args=args),self.changed_owner():
                self.db.execute(sql,args)
                with self.assertRaises(EvidenceUnavailable):self.descriptor()
        self.assert_original_evidence()

    def test_rehashed_semantic_mismatch_cannot_borrow_the_fixed_case(self):
        for change in (dict(terminal_record_unavailable=False),dict(unexpected_cancellation=True),
                dict(unpreserved_sessions=1),dict(pending_handlers=1),dict(all_accepted_committed=True)):
            with self.subTest(change=change),self.changed_owner():
                changed=dict(self.incident['failed'],**change);self.put(drain.OBSERVATION_DRAIN_KEY,canonical(changed))
                with patch.object(drain,'PREPARATION_RECOVERY_CENSUS',digest(changed)):
                    with self.assertRaises(EvidenceUnavailable):self.descriptor()

    def test_live_pending_canonical_event_and_wrong_consumer_file_block_verification(self):
        reference=self.preserve();self.recover();self.assertTrue(self.verify(reference)['economic_interval_recovered'])
        with patch.dict(os.environ,MM_SOLANA_CANDIDATE_HISTORY_DB=str(self.cache.with_name('foreign.sqlite'))):
            self.refused(reference)
        with self.changed_owner():
            tx=deepcopy(FIXTURE['pump'][0]);tx.update(slot=HEAD+2,blockTime=int(self.base.at)-1,transactionIndex=0)
            tx['transaction']['signatures']=[based58.b58encode(b'different-current-source-event'.ljust(64,b'0')).decode()]
            self.history.ingest(economic_records('pump',PROGRAMS['pump'],tx,
                endpoint_identity=self.history.endpoint_identity,seen=self.base.at,source='alchemy_finalized_repair'))
            self.assertIsNotNone(self.life.unconsumed(program_scope('pump')))
            self.refused(reference)

    def test_rehashed_closed_receipt_still_needs_zero_pending_joins_and_exact_session(self):
        identity,checksum,size,at=self.incident['observations']['closed']
        for change in (dict(accepted_pending=5),dict(pending_slots=1),dict(session='b'*32),
                dict(drained=True),dict(complete_history_claim=True),dict(completed=HEAD+5)):
            with self.subTest(change=change),self.changed_owner():
                raw=canonical(dict(self.incident['observed'],**change))
                self.db.execute('UPDATE acquisition_observations SET body=? WHERE id=?',(raw,identity))
                pins=dict(self.incident['observations'],closed=(identity,hashlib.sha256(raw.encode()).hexdigest(),len(raw.encode()),at))
                with patch.object(drain,'PREPARATION_RECOVERY_OBSERVATIONS',pins):
                    with self.assertRaises(EvidenceUnavailable):self.descriptor()

    def test_new_session_preserves_failed_receipts_and_reverifies_after_native_handoff(self):
        reference=self.preserve();_,proofs=self.recover()
        before={name:self.db.execute('SELECT kind,body,at FROM acquisition_observations WHERE id=?',(row[0],)).fetchone()
            for name,row in self.incident['observations'].items()}
        self.assertEqual(self.clean_session()['state'],'DRAINED')
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY+'_preserved.'+drain.PREPARATION_RECOVERY_CENSUS),self.incident['failed_raw'])
        desired=[dict(family=family,scope=program_scope(family),rolling=True) for family in FAMILIES]
        with self.changed_owner():
            preserve_subscription_handoff(self.state,desired,HEAD+7)
            self.refused(reference)
        self.assert_original_evidence()
        self.assertTrue(all(row[3] is None for row in self.old_gaps))
        bounded_old_gaps=[row[:3]+(HEAD+128,)+row[4:] for row in self.old_gaps]
        preserve_subscription_handoff(self.state,desired,HEAD+128,rolling_floor=HEAD+129)
        result=self.verify(reference);self.assertEqual(result['proof_ids'],proofs)
        self.assertTrue(result['retained_economic_tail_unavailable'])
        self.assertEqual({name:self.db.execute('SELECT kind,body,at FROM acquisition_observations WHERE id=?',(row[0],)).fetchone()
            for name,row in self.incident['observations'].items()},before)
        self.assertEqual(self.clean_session()['state'],'DRAINED')
        self.assertEqual(self.db.execute('SELECT * FROM candidate_gaps WHERE id IN (39592,39593) ORDER BY id').fetchall(),
            bounded_old_gaps)
        self.assertEqual(self.value(drain.SOURCE_DRAIN_KEY),self.old_source)
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY),self.incident['handler_raw'])
        self.assertEqual(self.db.execute("SELECT * FROM candidate_pending_proofs WHERE id='old-proof'").fetchall(),self.old_pending)
        self.assertEqual(self.base.funding.facts(),self.financial_before)
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY+'_preserved.'+drain.PREPARATION_RECOVERY_CENSUS),self.incident['failed_raw'])
