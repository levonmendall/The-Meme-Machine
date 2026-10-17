"""Recovered economics never retroactively ACK a failed native source drain.

Disposable real canonical owner, archive-page producer and FULL CandidateHistory
consumer only. Fixed production identity pins are asserted before substituting
the genuine offline producer's identities. No provider or readiness claim.
"""
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import unittest
import zlib
from unittest.mock import patch

from meme_machine import solana_source_drain as drain
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_history_delivery import capture, deliver, acknowledge
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import commit_candidate_batch, commit_control
from tests.test_candidate_commit_batches import frame
from tests import test_contained_source_observation as contained_fixture
from tests import test_program_gap_observation as program_fixture
from tests.test_solana_selective_evidence import FIXTURE


LOWER=457828555
UPPER=457828563
SESSION='7d1d60314f4c4f018738ef154437e2c8'
SESSION_AT=1792195108.9972048
REAL_FUNDING_GUARD=drain._require_observation_funding_closed
encode=program_fixture.encode
checksum=program_fixture.checksum
PRODUCTION_PINS=dict(
    ECONOMIC_REPLAY_OBSERVATION_SHA256='f76e9e06964eb64dd04aefd698780a95bb98af4a852c783a8e1192c0000ca49e',
    ECONOMIC_REPLAY_SESSION_SHA256='f10da79b22abdb7342ada4373ab74a235f66cc0e63ac1e8ba356ee20582cb6ac',
    ECONOMIC_REPLAY_JOBS={
        'pump':(8,'ea47c379a25a70e6f34492bfcc7a592b76767a07fc6c5d9bc4733b4662958ead',
            '1dff470ee9f02e0162a43be234c8897558c22095e6964ef70d05c35b8e3d7870'),
        'pumpswap':(1,'dd220350327c4f9cf999ae355c517171b6b67c1cc71171e1f208c24ad1850955',
            '9d4886040b969985256b66010c0b593077a83fe0c5168f63b49ffbfd88303538')},
    ECONOMIC_REPLAY_NATIVE_HASH='DLLkFkP5LgYop8GpGKkrcmGoFpjRnCQDMbBRJP675rTh',
    ECONOMIC_REPLAY_NATIVE_CENSUS={
        'pump':'ff3fa590721311a276b5368983b65179dcdcb9663e7fe00ab1c71d022e356d8c',
        'pumpswap':'355d87eca99a64a3d7306b31ea42d8e99d13e9d2c8302a69b43c76062fda7b93'})


class ArchiveRecoveredSessionTests(unittest.TestCase):
    def setUp(self):
        self.production_pins={key:getattr(drain,key) for key in PRODUCTION_PINS}
        # Composition reuses the historical incident fixture without inheriting
        # its tests or allowing its mocked funding predicate into these tests.
        self.incident=program_fixture.ProgramGapObservationTests('runTest')
        self.incident.setUp();self.addCleanup(self.incident.doCleanups)
        self.state=self.incident.state;self.history=self.incident.history
        self.db=self.incident.db;self.root=self.incident.root
        self.old_program_raw=self.incident.failed_raw
        self.old_handler_raw=self.incident.handler_raw
        self.old_source_raw=self.incident.old_raw
        self.old_pending=self.db.execute('SELECT * FROM candidate_pending_proofs').fetchall()
        self.put(drain.OBSERVATION_DRAIN_KEY+'_preserved.'+checksum(self.old_program_raw),self.old_program_raw)
        self.funding=contained_fixture.ObservationFundingClosureTests('runTest')
        self.funding.setUp();self.addCleanup(self.funding.doCleanups)
        self.enterContext(patch.object(drain,'_require_observation_funding_closed',REAL_FUNDING_GUARD))
        self.at=1792202012.5271285
        self.history.clock=self.history.lifecycle.clock=lambda:self.at
        self.state.writer.clock=lambda:self.at
        self.cache=self.root/'solana-candidate-history.sqlite'
        self.enterContext(patch.dict(os.environ,MM_SOLANA_HISTORY_SEPARATED='1',
            MM_SOLANA_CANDIDATE_HISTORY_DB=str(self.cache)))
        self.life=self.history.lifecycle;self.life.delivery_separated=True;self.life.path=self.cache
        self.history.startup.begin()
        value=self.native_frame(LOWER)
        commit_candidate_batch(self.state,[value],
            {PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')},SESSION,publish=False)
        for slot in range(LOWER,UPPER+2):commit_control(self.state,self.native_frame(slot))
        self.session=dict(plane='rolling',session=SESSION,drained=False,accepted_pending=8,
            accepted_pending_bytes=2946755,completed=UPPER,pending_slots=1,pending_bytes=5086,
            early_log_min_slot=UPPER+1,early_log_max_slot=457828663,
            early_log_count=10717,early_log_bytes=32637725,filtered_from_slot=457828373,
            oldest_slot=UPPER+1,oldest_statuses=51,oldest_bodies=0,oldest_missing_logs=0,
            replay_from_slot=457828373,replay_prefix_bytes=577257,handler_dispositions=[],
            recovery_obligations=[dict(scope=program_scope(f),lower_slot=457828373,upper_slot=None)
                for f in ('pump','pumpswap')],complete_history_claim=False)
        self.session_raw=encode(self.session)
        self.db.execute("INSERT INTO acquisition_observations(id,job,kind,at,body) VALUES(232141,NULL,'source_session_drain',?,?)",
            (SESSION_AT,self.session_raw))
        self.db.executemany("INSERT INTO candidate_gaps(id,scope,lo,hi,created,repaired,reason) VALUES(?,?,457828373,NULL,?,NULL,'candidate_live_disconnect_or_filter_rebuild')",
            [(39941,program_scope('pump'),1792195108.9836082),
             (39942,program_scope('pumpswap'),1792195108.9970887)])
        self.failed=self.incident.marker(state='RECOVERY_REQUIRED',accepted_handlers=118783,
            settled_handlers=118783,pending_handlers=0,source_pid=150132,run_identity='f'*32,
            closed_sessions=2,preserved_partial_sessions=1,unpreserved_sessions=0,
            all_accepted_committed=False,control_pending_replay=dict(lower_slot=457828806,
                upper_slot=457828806,coverage_after_id=194116),
            queues={name:dict(accepted=a,committed=c,pending=a-c) for name,a,c in (
                ('control',782,782),('rolling',191,183),('scout',5594,5594),('candidate',0,0))})
        self.failed['handler_accounting'].update(run='f'*32,pid=150132,accepted=118783,
            returned=118783,active=0,recoverable=0,failed=0,unresolved=0,records=[])
        self.failed_raw=encode(self.failed)
        self.put(drain.OBSERVATION_DRAIN_KEY,self.failed_raw)
        self.put('provider',encode(dict(provider='alchemy_solana_mainnet',network='solana-mainnet',
            endpoint_identity=self.history.endpoint_identity)))
        self.jobs={};self.proofs={}
        # Genuine archive jobs and page receipts produce the interval proof;
        # only immutable fixture identity pins below are substituted.
        tx=deepcopy(FIXTURE['pump'][0]);tx.update(slot=LOWER+1,blockTime=int(self.at)-1,transactionIndex=0)
        for family in ('pump','pumpswap'):
            identity=self.history.request(family,PROGRAMS[family],LOWER,UPPER,priority=0,deadline=self.at+120)
            planned=self.history.plan();self.assertIsNotNone(planned)
            job,_config=planned;self.assertEqual(job['id'],identity)
            if family=='pump':
                from meme_machine.solana_program_decoders import pump_events
                self.mint=next(event['mint'] for event in pump_events(tx) if event['event_type']=='create')
                self.history.bind('pump',self.mint)
            self.history.commit_page(job,dict(data=[tx] if family=='pump' else []),finalized_through=UPPER,seen=self.at)
            self.jobs[family]=identity
            proof=self.db.execute('SELECT id FROM candidate_pending_proofs WHERE scope=? AND lo=? AND hi=?',
                (program_scope(family),LOWER,UPPER)).fetchone()
            self.assertIsNotNone(proof);self.proofs[family]=proof[0]
        self.proof_rows={f:self.db.execute('SELECT * FROM candidate_pending_proofs WHERE id=?',(p,)).fetchone()
            for f,p in self.proofs.items()}
        self.publish_real()
        native=self.db.execute('SELECT scope,hash,census_hash FROM candidate_blocks ORDER BY scope').fetchall()
        native={row[0]:(row[1],row[2]) for row in native}
        pins=dict(ECONOMIC_REPLAY_OBSERVATION_SHA256=checksum(self.failed_raw),
            ECONOMIC_REPLAY_SESSION_SHA256=checksum(self.session_raw),
            ECONOMIC_REPLAY_NATIVE_HASH=native[program_scope('pump')][0],
            ECONOMIC_REPLAY_NATIVE_CENSUS={f:native[program_scope(f)][1] for f in ('pump','pumpswap')},
            ECONOMIC_REPLAY_JOBS={f:(*self.db.execute('SELECT pages,lineage FROM acquisition_jobs WHERE id=?',
                (self.jobs[f],)).fetchone(),self.proofs[f]) for f in ('pump','pumpswap')})
        for key,value in pins.items():self.enterContext(patch.object(drain,key,value))
        self.preserved=self.history_facts()

    def native_frame(self,slot):
        value=replace(frame(slot,logs=False),seen=self.at)
        value.update.block.block_time.timestamp=int(self.at)-1
        return value

    def put(self,key,raw):self.incident.put(key,raw)
    def value(self,key):return self.incident.value(key)
    def facts(self):return self.incident.facts()

    def history_facts(self):
        return dict(source=self.value(drain.SOURCE_DRAIN_KEY),handler=self.value(drain.HANDLER_RECOVERY_KEY),
            old_observation=self.value(drain.OBSERVATION_DRAIN_KEY+'_preserved.'+checksum(self.old_program_raw)),
            old_pending=self.db.execute("SELECT * FROM candidate_pending_proofs WHERE id='old-proof'").fetchall(),
            old_gaps=self.db.execute('SELECT * FROM candidate_gaps WHERE id IN(39592,39593) ORDER BY id').fetchall())

    def publish_real(self,proof_ids=None):
        selected=tuple(self.proofs.values()) if proof_ids is None else tuple(proof_ids)
        for _ in range(4):
            batch=capture(self.life)
            if batch is None:break
            # The unrelated old fixture proof is intentionally unavailable.
            # Fixed recovery delivers only its own genuine current proofs.
            batch=dict(batch,proofs=[p for p in batch['proofs'] if p['identity'] in selected],
                publication_ids=[p for p in batch['publication_ids'] if p in selected])
            if not batch['rows'] and not batch['proofs']:break
            self.assertTrue(acknowledge(self.life,batch,deliver(batch)))
        self.life.publish(proof_ids=selected)
        self.assertTrue(self.cache.is_file())
        with closing(CandidateHistory(self.cache)) as consumer:
            self.assertEqual(consumer.db.execute('PRAGMA synchronous').fetchone()[0],2)
            self.assertTrue(consumer.events('pump',self.mint))
            self.assertTrue(all(consumer.db.execute('SELECT 1 FROM source_receipts WHERE id=?',
                ('coverage:'+proof,)).fetchone() for proof in selected))

    def recover_tail(self,lower,upper):
        # The real fixed-bound archive producer can legitimately recover a
        # later missing interval. Neither its deadline nor proof is invented.
        head=self.db.execute('SELECT MAX(slot) FROM stream_receipts WHERE scope=?',('control:solana',)).fetchone()[0]
        for slot in range(head+1,upper+2):commit_control(self.state,self.native_frame(slot))
        proofs=[]
        for family in ('pump','pumpswap'):
            identity=self.history.request(family,PROGRAMS[family],lower,upper,priority=0,deadline=self.at+120)
            job,_=self.history.plan();self.assertEqual(job['id'],identity)
            self.history.commit_page(job,dict(data=[]),finalized_through=upper,seen=self.at)
            proof=self.db.execute('SELECT id FROM candidate_pending_proofs WHERE scope=? AND lo=? AND hi=?',
                (program_scope(family),lower,upper)).fetchone()
            self.assertIsNotNone(proof);proofs.append(proof[0])
        self.publish_real(proofs)
        return proofs

    def refused(self):
        before=self.facts()
        with self.assertRaises(EvidenceUnavailable):drain.historical_observation_boundary(self.state)
        self.assertEqual(self.facts(),before)

    @contextmanager
    def changed_owner(self):
        self.db.execute('SAVEPOINT economic_fixture_mutation')
        try:yield
        finally:
            self.db.execute('ROLLBACK TO economic_fixture_mutation')
            self.db.execute('RELEASE economic_fixture_mutation')

    def begin(self):
        body=self.incident.current(state='RUNNING')
        body.update(historical_unknown_handlers=2,historical_source_drain_sha256=self.incident.old_hash,
            historical_recovery_verified=False)
        raw=drain.begin_source_observation(self.state,self.old_source_raw,body,handler_boundary=self.old_handler_raw)
        return body,raw

    def finish(self,body,raw,**changes):
        terminal=dict(body,state='DRAINED',terminal=True,terminal_at_monotonic=body['started_at_monotonic']+1)
        terminal.update(changes)
        drain.publish_source_drain(self.state,self.old_source_raw,terminal,handler_boundary=self.old_handler_raw,
            contained_observation=True,observation_boundary=raw)

    def test_exact_production_identity_pins_and_real_full_consumer_witnesses(self):
        self.assertEqual(self.production_pins,PRODUCTION_PINS)
        result=drain.historical_observation_boundary(self.state)
        self.assertEqual(result['current_observation_state'],'PRESERVED_ECONOMIC_REPLAY')
        self.assertTrue(result['economic_interval_recovered'])
        self.assertFalse(result['original_queue_acknowledgement_verified'])
        self.assertFalse(result['original_source_drain_pass'])
        self.assertEqual(result['economic_replay_lower_slot'],LOWER)
        self.assertEqual(result['economic_replay_upper_slot'],UPPER)
        self.assertEqual(result['economic_replay_proof_ids'],self.proofs)
        self.assertTrue(result['retained_economic_tail_unavailable'])
        self.assertFalse(result['economic_tail_recovered'])
        self.assertTrue(result['economic_tail_continuity_verified'])
        self.assertEqual((result['retained_economic_tail_lower_slot'],result['retained_economic_tail_upper_slot']),
            (UPPER+1,457828663))
        self.assertEqual(self.history_facts(),self.preserved)
        self.assertEqual((self.failed['queues']['rolling']['accepted'],self.failed['queues']['rolling']['committed']),(191,183))

    def test_only_real_funding_closed_contained_admission_can_use_recovered_boundary(self):
        before=self.funding.facts()
        self.assertEqual(drain.retained_source_drain(self.state,contained_observation=True),self.old_source_raw)
        self.assertEqual(self.funding.facts(),before)
        with self.assertRaises(EvidenceUnavailable):drain.retained_source_drain(self.state)
        with patch.dict(os.environ,MM_OPERATIONAL_PHASE='continuous'):
            with self.assertRaises(EvidenceUnavailable):drain.retained_source_drain(self.state,contained_observation=True)
        self.assertEqual(self.history_facts(),self.preserved)

    def test_begin_archives_failed_bytes_atomically_and_running_never_reuses_old_proof(self):
        body,raw=self.begin()
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY+'_preserved.'+checksum(self.failed_raw)),self.failed_raw)
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY),raw)
        self.assertEqual(json.loads(raw)['state'],'RUNNING')
        self.assertEqual(self.history_facts(),self.preserved)
        self.refused()
        self.finish(body,raw)
        result=drain.historical_observation_boundary(self.state)
        self.assertEqual(result['current_observation_state'],'DRAINED')
        self.assertTrue(result['economic_interval_recovered'])
        self.assertFalse(result['original_source_drain_pass'])
        with closing(sqlite3.connect(self.state.writer.path.as_uri()+'?mode=ro',uri=True)) as reader:
            reader.execute('PRAGMA query_only=ON')
            self.assertEqual(drain.historical_observation_boundary(reader),result)
        self.assertEqual(self.history_facts(),self.preserved)

    def test_missing_job_proof_page_and_incomplete_pagination_refuse(self):
        for family in ('pump','pumpswap'):
            cases=[('DELETE FROM acquisition_jobs WHERE id=?',(self.jobs[family],)),
                ("UPDATE acquisition_jobs SET status='pending' WHERE id=?",(self.jobs[family],)),
                ("UPDATE acquisition_jobs SET token='unfinished-page' WHERE id=?",(self.jobs[family],)),
                ("UPDATE acquisition_jobs SET pages=pages+1 WHERE id=?",(self.jobs[family],)),
                ("UPDATE acquisition_jobs SET lineage=? WHERE id=?",('b'*64,self.jobs[family])),
                ('DELETE FROM acquisition_page_receipts WHERE job=?',(self.jobs[family],)),
                ("UPDATE acquisition_page_receipts SET page=page+1 WHERE job=?",(self.jobs[family],)),
                ("UPDATE acquisition_page_receipts SET input_hash='invalid' WHERE job=?",(self.jobs[family],)),
                ("UPDATE acquisition_page_receipts SET result=? WHERE job=?",(encode(dict(complete=False,pages=1,records=0)),self.jobs[family])),
                ("INSERT INTO candidate_pending_proofs VALUES(?,?,?,?,?,?,?,?)",self.proof_rows[family])]
            for sql,args in cases:
                with self.subTest(family=family,mutation=sql),self.changed_owner():
                    self.db.execute(sql,args);self.refused()

    def test_changed_scopes_bounds_published_coverage_and_unconsumed_rows_refuse(self):
        for family in ('pump','pumpswap'):
            for sql,args in [
                ('UPDATE acquisition_jobs SET lo=lo+1 WHERE id=?',(self.jobs[family],)),
                ("UPDATE acquisition_jobs SET address='different-program' WHERE id=?",(self.jobs[family],)),
                ('DELETE FROM candidate_coverage WHERE scope=?',(program_scope(family),)),
                ("UPDATE candidate_coverage SET hash='invalid' WHERE scope=?",(program_scope(family),)),
                ('INSERT INTO candidate_gaps(scope,lo,hi,created,reason) VALUES(?,?,?,?,?)',
                    (program_scope(family),LOWER,UPPER,self.at,'explicit-unavailable-economic-interval'))]:
                with self.subTest(family=family,mutation=sql),self.changed_owner():
                    self.db.execute(sql,args);self.refused()
        with self.changed_owner():
            row=self.db.execute("SELECT id FROM candidate_history_outbox WHERE kind='canonical' AND family='pump' AND id<>'old-history' LIMIT 1").fetchone()
            self.assertIsNotNone(row)
            self.db.execute('UPDATE candidate_history_outbox SET consumed=NULL WHERE id=?',(row[0],))
            self.refused()

    def test_missing_or_self_consistent_tampered_consumer_receipt_refuses(self):
        with closing(sqlite3.connect(self.cache,isolation_level=None)) as consumer:
            for family in ('pump','pumpswap'):
                identity='coverage:'+self.proofs[family]
                original=consumer.execute('SELECT * FROM source_receipts WHERE id=?',(identity,)).fetchone()
                self.assertIsNotNone(original)
                for field,value in [('missing',None),('hash','b'*64),('scope',program_scope('pump' if family=='pumpswap' else 'pumpswap')),
                        ('family','different-family'),('endpoint','b'*64),('lo',LOWER-1),('hi',UPPER+1),
                        ('witness',dict(json.loads(original[5])['witness'],lineage_hash='b'*64))]:
                    with self.subTest(family=family,field=field):
                        try:
                            if field=='missing':consumer.execute('DELETE FROM source_receipts WHERE id=?',(identity,))
                            elif field=='hash':consumer.execute('UPDATE source_receipts SET hash=? WHERE id=?',(value,identity))
                            else:
                                body=json.loads(original[5]);body[field]=value;raw=encode(body)
                                consumer.execute('UPDATE source_receipts SET body=?,hash=? WHERE id=?',(raw,checksum(raw),identity))
                            self.refused()
                        finally:
                            consumer.execute('INSERT OR REPLACE INTO source_receipts VALUES(?,?,?,?,?,?,?)',original)

    def test_provider_native_head_and_exact_observation_session_bytes_remain_required(self):
        cases=[("UPDATE service_health SET value=? WHERE key='provider'",(encode(dict(provider='other',network='solana-mainnet',endpoint_identity='a'*64)),)),
            ("UPDATE service_health SET value=? WHERE key='provider'",(encode(dict(provider='alchemy_solana_mainnet',network='solana-mainnet',endpoint_identity='b'*64)),)),
            ("UPDATE candidate_blocks SET slot=slot+1 WHERE scope=?",(program_scope('pump'),)),
            ("UPDATE candidate_blocks SET census_hash=? WHERE scope=?",('b'*64,program_scope('pumpswap'))),
            ("UPDATE candidate_blocks SET session=? WHERE scope=?",('e'*32,program_scope('pump'))),
            ("UPDATE acquisition_observations SET body=body||' ' WHERE id=232141",()),
            ("UPDATE service_health SET value=value||' ' WHERE key=?",(drain.OBSERVATION_DRAIN_KEY,))]
        for sql,args in cases:
            with self.subTest(mutation=sql),self.changed_owner():self.db.execute(sql,args);self.refused()
        # Repinning synthetic raw identity cannot excuse a different census or
        # session meaning; the full contract still checks their contents.
        for change in (dict(all_accepted_committed=True),dict(accepted_handlers=118784,settled_handlers=118784),
                dict(state='DRAINED'),dict(run_identity='e'*32),dict(source_pid=150133)):
            body=deepcopy(self.failed);body.update(change);raw=encode(body)
            with self.subTest(census=change),self.changed_owner(),patch.object(drain,'ECONOMIC_REPLAY_OBSERVATION_SHA256',checksum(raw)):
                self.put(drain.OBSERVATION_DRAIN_KEY,raw);self.refused()
        for change in (dict(plane='candidate'),dict(accepted_pending=7),dict(completed=UPPER-1),
                dict(session='e'*32),dict(early_log_min_slot=UPPER+2),dict(recovery_obligations=self.session['recovery_obligations'][:1])):
            raw=encode(dict(self.session,**change))
            with self.subTest(session=change),self.changed_owner(),patch.object(drain,'ECONOMIC_REPLAY_SESSION_SHA256',checksum(raw)):
                self.db.execute('UPDATE acquisition_observations SET body=? WHERE id=232141',(raw,));self.refused()

    def test_new_failed_census_cannot_reuse_archived_economic_success(self):
        started,raw=self.begin()
        self.finish(started,raw,state='RECOVERY_REQUIRED',accepted_handlers=1,settled_handlers=0,pending_handlers=1)
        self.refused()
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY+'_preserved.'+checksum(self.failed_raw)),self.failed_raw)
        self.assertEqual(self.history_facts(),self.preserved)

    def test_drained_restart_revalidates_archive_and_original_unresolved_incidents(self):
        started,raw=self.begin();self.finish(started,raw)
        self.assertTrue(drain.historical_observation_boundary(self.state)['economic_interval_recovered'])
        for key in (drain.OBSERVATION_DRAIN_KEY,drain.HANDLER_RECOVERY_KEY,
                drain.OBSERVATION_DRAIN_KEY+'_preserved.'+checksum(self.failed_raw),
                drain.OBSERVATION_DRAIN_KEY+'_preserved.'+checksum(self.old_program_raw)):
            with self.subTest(key=key),self.changed_owner():
                self.db.execute('DELETE FROM service_health WHERE key=?',(key,));self.refused()
        with self.changed_owner():
            self.db.execute('DELETE FROM acquisition_jobs WHERE id=?',(self.jobs['pump'],));self.refused()

    def test_genuine_partial_and_full_tail_recovery_preserve_historical_failure(self):
        started,raw=self.begin();self.finish(started,raw)
        partial=self.recover_tail(UPPER+1,457828600)
        result=drain.historical_observation_boundary(self.state)
        self.assertTrue(result['retained_economic_tail_unavailable'])
        self.assertFalse(result['economic_tail_recovered'])
        self.assertTrue(result['economic_tail_continuity_verified'])
        self.assertEqual(self.history_facts(),self.preserved)
        # A false published coverage extent cannot replace the exact FULL
        # receipt which independently proves the newly recovered segment.
        with closing(sqlite3.connect(self.cache,isolation_level=None)) as consumer:
            original=consumer.execute('SELECT * FROM source_receipts WHERE id=?',('coverage:'+partial[0],)).fetchone()
            try:
                consumer.execute('DELETE FROM source_receipts WHERE id=?',(original[0],));self.refused()
            finally:consumer.execute('INSERT INTO source_receipts VALUES(?,?,?,?,?,?,?)',original)
        for mutation in ('delete','mark_repaired','false_extent'):
            with self.subTest(mutation=mutation),self.changed_owner():
                if mutation=='false_extent':
                    from meme_machine.solana_selective_history import coverage_points
                    row=self.db.execute('SELECT lo,points,hash FROM candidate_coverage WHERE scope=? AND hi=457828600',
                        (program_scope('pump'),)).fetchone()
                    self.assertIsNotNone(row)
                    points=coverage_points(row[1],row[2])
                    points=[[a,457828663 if b==457828600 else b,at] for a,b,at in points]
                    packed=zlib.compress(encode(points).encode(),1)
                    self.db.execute('UPDATE candidate_coverage SET hi=457828663,points=?,hash=? WHERE scope=? AND lo=?',
                        (packed,hashlib.sha256(packed).hexdigest(),program_scope('pump'),row[0]))
                    self.db.execute('UPDATE candidate_gaps SET repaired=? WHERE scope=? AND lo<=457828663 AND (hi IS NULL OR hi>=457828601)',
                        (self.at,program_scope('pump')))
                else:
                    sql=("DELETE FROM candidate_gaps WHERE scope=? AND lo=457828601 AND created=?" if mutation=='delete' else
                        "UPDATE candidate_gaps SET repaired=? WHERE scope=? AND lo=457828601 AND created=?")
                    args=(program_scope('pump'),1792195108.9836082)
                    if mutation=='mark_repaired':args=(self.at,*args)
                    self.db.execute(sql,args)
                self.refused()
        self.recover_tail(457828601,457828663)
        result=drain.historical_observation_boundary(self.state)
        self.assertFalse(result['retained_economic_tail_unavailable'])
        self.assertTrue(result['economic_tail_recovered'])
        self.assertTrue(result['economic_tail_continuity_verified'])
        self.assertFalse(result['original_queue_acknowledgement_verified'])
        self.assertFalse(result['original_source_drain_pass'])
        self.assertEqual(self.history_facts(),self.preserved)
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY+'_preserved.'+checksum(self.failed_raw)),self.failed_raw)

    def test_archive_and_running_publication_failures_roll_back_all_boundary_writes(self):
        original=self.facts()
        failure=sqlite3.OperationalError('fixture boundary commit failure')
        statement=self.state.writer._transaction_statement
        def fail_commit(sql,phase):
            if phase=='commit':raise failure
            return statement(sql,phase)
        with patch.object(self.state.writer,'_transaction_statement',side_effect=fail_commit):
            with self.assertRaises(sqlite3.OperationalError) as caught:self.begin()
        self.assertIs(caught.exception,failure);self.assertEqual(self.facts(),original)
        health=self.state.fence._health
        def fail_running(key,body):
            health(key,body)
            if key==drain.OBSERVATION_DRAIN_KEY:raise failure
        with patch.object(self.state.fence,'_health',side_effect=fail_running):
            with self.assertRaises(sqlite3.OperationalError) as caught:self.begin()
        self.assertIs(caught.exception,failure);self.assertEqual(self.facts(),original)
        # An archive INSERT failure must preserve the original failure and must
        # not publish RUNNING or alter either historical incident.
        with self.changed_owner():
            self.db.execute("CREATE TRIGGER refuse_boundary_archive BEFORE INSERT ON service_health WHEN NEW.key LIKE '%_preserved.%' BEGIN SELECT RAISE(ABORT,'fixture archive refusal'); END")
            before=self.facts()
            with self.assertRaisesRegex(sqlite3.IntegrityError,'fixture archive refusal'):self.begin()
            self.assertEqual(self.facts(),before)

