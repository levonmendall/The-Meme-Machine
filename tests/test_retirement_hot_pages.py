"""Disposable archival-page mechanics; never market or capacity evidence."""
from contextlib import closing
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime.stop import Shutdown
from meme_machine.solana_evidence_plane import FinalizedRecord,canonical,decode_body,digest
from meme_machine.solana_history_archive import apply,prepare
from meme_machine.solana_scoped_retirement import ScopedRetirement
from meme_machine.solana_selective_history import PROGRAMS,coverage_scope
from tests import test_solana_closure as closure_fixture
from tests import test_solana_history_separation as history_fixture

NOW=closure_fixture.NOW


class RetirementHotPageTests(unittest.TestCase):
    setUp=closure_fixture.ClosureTests.setUp
    tearDown=closure_fixture.ClosureTests.tearDown
    restart=closure_fixture.ClosureTests.restart
    drain=closure_fixture.ClosureTests.drain
    pump=history_fixture.HistorySeparationTests.pump
    seal=history_fixture.HistorySeparationTests.seal

    def cursors(self):
        return self.h.db.execute("SELECT key,value FROM meta WHERE key LIKE 'scoped_retirement_hot_%' ORDER BY key").fetchall()

    def pending(self):
        return {table:self.h.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
                for table in ('candidate_history_outbox','candidate_pending_proofs','acquisition_jobs')}

    def economics(self):
        return self.h.db.execute('SELECT identity,body,hash,first_seen,archive FROM canonical_evidence ORDER BY identity').fetchall()

    def ready(self):
        mint,events=self.pump();self.drain()
        # Real, unrelated incomplete acquisition/outbox obligations must survive
        # preparation, cancellation and archive-pointer commits unchanged.
        self.h.observe('pumpswap','pending-only',slot=100,signature='offline-pending',
                       fields=dict(pool='pending-only',activity=False),seen=NOW)
        self.h.bind('pumpswap','pending-only')
        self.h.request('pumpswap','pending-only',100,110,priority=3,deadline=NOW+150)
        self.assertTrue(self.h.db.execute('SELECT 1 FROM candidate_history_outbox WHERE consumed IS NULL LIMIT 1').fetchone())
        retirement=ScopedRetirement(self.h)
        plan=retirement.retire(limit=64,measure_hot_bytes=False,plan_only=True)
        self.assertTrue(plan['selected'])
        return mint,events,retirement,plan

    def metadata(self,indices,*,address='dense',prefix='dense',padding=80):
        """Valid-format synthetic rows, pinned and never qualification proof.

        Bulk insertion avoids pretending source-ingestion speed is measured.
        Equal-width identities/signatures/slots isolate the exact index suffix.
        """
        rows=[];addresses=[]
        for number in indices:
            identity=prefix+'-'+f'{number:06d}'
            record=FinalizedRecord(identity,'program:pump',100000+number,
                'offline-'+f'{number:06d}',PROGRAMS['pump'],(address,),int(NOW),
                dict(event=dict(event_type='trade',mint=address,market_time=int(NOW)),
                     fixture_padding='x'*padding),'alchemy_finalized_stream','a'*64,NOW,
                transaction_index=0,event_index=0)
            raw=canonical(record.body())
            rows.append((identity,record.scope,record.slot,record.signature,record.program,
                record.market_time,record.event_index,record.transaction_index,record.kind,
                raw,digest(record.body()),NOW,None))
            addresses.append((identity,address))
        with self.state.writer.transaction():
            self.h.db.executemany('INSERT INTO rolling_economic_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',rows)
            self.h.db.executemany('INSERT INTO rolling_economic_addresses VALUES(?,?)',addresses)
        return {row[0] for row in rows}

    def pinned_dense(self):
        retirement=ScopedRetirement(self.h)
        self.h.bind('pump','dense')
        self.life.pin(coverage_scope('pump','dense'),'fixture-held','position',0)
        with closing(CandidateHistory(self.life.path,clock=lambda:NOW)):pass
        return retirement

    def test_dense_equal_length_suffix_has_bounded_metadata_and_vm_work(self):
        retirement=self.pinned_dense()
        self.metadata(range(16320,16384))
        initial=retirement.retire(limit=16,measure_hot_bytes=False,plan_only=True)
        self.assertEqual(apply(self.h,initial,prepare(initial))['retired_records'],0)
        # The persisted cursor is already near the end. Grow only the equal-
        # length prefix behind it; that prefix must not be rescanned to seek.
        self.metadata(range(0,4032))
        observations=[];outputs=[]
        for population in (4096,16384):
            if population==16384:self.metadata(range(4032,16320))
            self.assertEqual(self.h.db.execute('SELECT COUNT(DISTINCT length(CAST(body AS BLOB))) FROM rolling_economic_events').fetchone()[0],1)
            old_steps=[0]
            def old_tick():old_steps[0]+=1;return 0
            self.h.db.set_progress_handler(old_tick,1)
            try:old_ids=retirement._oldest_hot_identities('pump','dense',64)
            finally:self.h.db.set_progress_handler(None,0)
            self.assertEqual(len(old_ids),64)
            steps=[0];queries=[]
            def tick():steps[0]+=1;return 0
            self.h.db.set_progress_handler(tick,1);self.h.db.set_trace_callback(queries.append)
            try:plan=retirement.retire(limit=64,measure_hot_bytes=False,plan_only=True)
            finally:self.h.db.set_progress_handler(None,0);self.h.db.set_trace_callback(None)
            self.assertLessEqual(plan['selection']['metadata_rows'],64)
            self.assertEqual(plan['selection']['metadata_row_bound'],64)
            self.assertEqual(plan['selected'],{})
            self.assertFalse(any(query.startswith('SELECT * FROM canonical_evidence') for query in queries))
            observations.append(dict(population=population,vm_steps=steps[0],
                original_candidate_selection_vm_steps=old_steps[0],metadata_rows=plan['selection']['metadata_rows']))
            outputs.append((set(plan['pinned']),plan['hot_cursors']))
        self.assertEqual(outputs[0],outputs[1])
        self.assertEqual(len(outputs[0][0]),48)
        self.assertLessEqual(observations[1]['vm_steps'],observations[0]['vm_steps']+256)
        self.assertGreater(observations[1]['original_candidate_selection_vm_steps'],
            2*observations[0]['original_candidate_selection_vm_steps'])
        print('RETIREMENT_HOT_PAGE_VM '+json.dumps(observations,sort_keys=True),flush=True)

    def test_fixed_cycle_wrap_revisits_new_small_rows_despite_new_tail(self):
        retirement=self.pinned_dense();self.metadata(range(192))
        first=retirement.retire(limit=64,measure_hot_bytes=False,plan_only=True)
        apply(self.h,first,prepare(first))
        behind=self.metadata([900000],prefix='behind',padding=0)
        tail=self.metadata([900001],prefix='tail',padding=160)
        seen=set()
        for turn in range(10):
            # New rows keep extending the tail beyond the first cycle. This
            # must not indefinitely postpone the inserted smaller row.
            self.metadata([910000+turn],prefix='growing-tail',padding=200+turn)
            plan=retirement.retire(limit=64,measure_hot_bytes=False,plan_only=True)
            self.assertLessEqual(plan['selection']['metadata_rows'],64)
            seen.update(plan['pinned']);apply(self.h,plan,prepare(plan))
            if (behind|tail)<=seen:break
        self.assertTrue((behind|tail)<=seen)

    def test_canonical_cold_shadow_is_not_replaced_by_hot_legacy_copy(self):
        retirement=self.pinned_dense();identity=next(iter(self.metadata([0])))
        row=self.h.db.execute('SELECT * FROM rolling_economic_events WHERE identity=?',(identity,)).fetchone()
        with self.state.writer.transaction():
            self.h.db.execute('INSERT INTO shared_history_cache VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',row)
            self.h.db.execute('INSERT INTO cached_addresses VALUES(?,?)',(identity,'dense'))
            self.h.db.execute('UPDATE rolling_economic_events SET body=NULL,archive=? WHERE identity=?',('fixture-cold',identity))
        before=self.economics()
        plan=retirement.retire(limit=64,measure_hot_bytes=False,plan_only=True)
        self.assertNotIn(identity,plan['selected']);self.assertNotIn(identity,plan['pinned'])
        self.assertEqual(apply(self.h,plan,prepare(plan))['retired_records'],0)
        self.assertEqual(self.economics(),before)

    def test_shared_owner_fanout_and_unbound_rows_stay_hot_without_body_expansion(self):
        mint,events,retirement,_=self.ready()
        for number in range(70):self.h.bind('pump','shared-view-'+str(number),market_address=mint)
        unbound=self.metadata([0],address='unbound',prefix='unbound')
        before=self.economics();pending=self.pending();queries=[]
        self.h.db.set_trace_callback(queries.append)
        try:
            with patch('meme_machine.solana_scoped_retirement.decode_body',side_effect=AssertionError('no pinned body expansion')):
                plan=retirement.retire(limit=64,measure_hot_bytes=False,plan_only=True)
        finally:self.h.db.set_trace_callback(None)
        owned={row.identity for row in events if mint in row.addresses}
        self.assertTrue(owned);self.assertTrue(owned.isdisjoint(plan['selected']))
        self.assertTrue(unbound.isdisjoint(plan['selected']))
        self.assertEqual(plan['oldest']['reason'],'shared_binding_bound')
        self.assertFalse(any(query.startswith('SELECT * FROM canonical_evidence') for query in queries))
        self.assertEqual(apply(self.h,plan,prepare(plan))['retired_records'],0)
        self.assertEqual(self.economics(),before);self.assertEqual(self.pending(),pending)

    def test_new_pin_or_lost_owner_refuses_prepared_archive(self):
        mint,_,_,plan=self.ready();prepared=prepare(plan)
        before=self.economics();pending=self.pending();cursors=self.cursors()
        self.life.pin(coverage_scope('pump',mint),'new-held-owner','position',0)
        self.assertFalse(apply(self.h,plan,prepared))
        self.life.unpin(coverage_scope('pump',mint),'new-held-owner','position')
        with self.state.writer.transaction():self.h.db.execute('DELETE FROM evidence_bindings')
        self.assertFalse(apply(self.h,plan,prepared))
        self.assertEqual(self.economics(),before);self.assertEqual(self.pending(),pending)
        self.assertEqual(self.cursors(),cursors)

    def test_stale_cursor_and_source_generation_refuse_without_completion(self):
        _,_,_,plan=self.ready();prepared=prepare(plan)
        stale=copy.deepcopy(plan)
        key=next(iter(stale['hot_cursor_before']))
        stale['hot_cursor_before'][key]='stale-offline-cursor-token'
        before=self.economics();pending=self.pending();cursors=self.cursors()
        self.assertFalse(apply(self.h,stale,prepared))
        self.assertEqual(self.economics(),before);self.assertEqual(self.pending(),pending)
        self.assertEqual(self.cursors(),cursors)
        self.h.startup.begin()
        pending=self.pending()
        self.assertFalse(apply(self.h,plan,prepared))
        self.assertEqual(self.economics(),before);self.assertEqual(self.pending(),pending)
        self.assertEqual(self.cursors(),cursors)

    def test_failed_pointer_cursor_transaction_rolls_back_and_restart_keeps_work(self):
        _,_,_,plan=self.ready();prepared=prepare(plan)
        before=self.economics();pending=self.pending();cursors=self.cursors()
        self.h.db.execute("CREATE TRIGGER offline_retirement_failure BEFORE INSERT ON scoped_retirement_observations BEGIN SELECT RAISE(ABORT,'offline_atomic_failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError,'offline_atomic_failure'):apply(self.h,plan,prepared)
        self.assertEqual(self.economics(),before);self.assertEqual(self.pending(),pending)
        self.assertEqual(self.cursors(),cursors)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM scoped_cold_manifests').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM scoped_cold_records').fetchone()[0],0)
        self.h.db.execute('DROP TRIGGER offline_retirement_failure')
        self.restart()
        self.h.startup.begin()
        self.assertEqual(self.economics(),before);self.assertEqual(self.cursors(),cursors)
        for table,rows in pending.items():
            self.assertTrue(set(rows).issubset(set(self.pending()[table])))
        self.assertFalse(apply(self.h,plan,prepared))

    def test_cancelled_or_completed_unapplied_preparation_preserves_pending(self):
        _,_,_,plan=self.ready()
        before=self.economics();pending=self.pending();cursors=self.cursors()
        original=Shutdown()
        with patch('meme_machine.solana_history_archive.zlib.compress',side_effect=original):
            with self.assertRaises(Shutdown) as caught:prepare(plan)
        self.assertIs(caught.exception,original)
        self.assertEqual(self.economics(),before);self.assertEqual(self.pending(),pending)
        self.assertEqual(self.cursors(),cursors)
        result=prepare(plan);self.assertTrue(result['receipt'])
        self.assertEqual(self.economics(),before);self.assertEqual(self.pending(),pending)
        self.assertEqual(self.cursors(),cursors)

    def test_oversized_hot_representation_is_rejected_before_body_materialization(self):
        _,_,retirement,initial=self.ready()
        identity,row=next(iter(initial['selected'].items()))
        # JSON whitespace leaves the authenticated canonical object/hash exact
        # while exercising the physical preparation-input length guard.
        body=canonical(decode_body(row[9],self.h.db))+' '*(16*1024*1024+1)
        with self.state.writer.transaction():
            self.h.db.execute('UPDATE rolling_economic_events SET body=? WHERE identity=?',(body,identity))
        pending=self.pending();queries=[]
        self.h.db.set_trace_callback(queries.append)
        try:plan=retirement.retire(limit=64,measure_hot_bytes=False,plan_only=True)
        finally:self.h.db.set_trace_callback(None)
        self.assertNotIn(identity,plan['selected'])
        self.assertLessEqual(plan['selection']['preparation_bytes'],16*1024*1024)
        self.assertFalse(any(query.startswith('SELECT * FROM canonical_evidence') and identity in query
                             for query in queries))
        self.assertEqual(self.pending(),pending)

    def test_valid_archive_restores_exact_economics_and_original_availability(self):
        mint,events,retirement,plan=self.ready()
        originals={identity:(decode_body(row[9],self.h.db),row[10],row[11])
                   for identity,row in plan['selected'].items()}
        pending=self.pending();result=prepare(plan);status=apply(self.h,plan,result)
        self.assertEqual(status['retired_records'],len(originals))
        self.assertTrue(status['canonical_generation_revalidated'])
        self.assertEqual(status['oldest_unretired_scope_domain'],'examined hot page only')
        self.assertEqual(self.pending(),pending);self.assertTrue(self.cursors())
        for identity,(body,checksum,available) in originals.items():
            self.assertEqual(retirement.body(identity),body)
            self.assertEqual(self.h.db.execute('SELECT hash,first_seen FROM canonical_evidence WHERE identity=?',(identity,)).fetchone(),(checksum,available))
        self.assertEqual(retirement.restore('pump',mint),len(originals))
        for identity,(body,checksum,available) in originals.items():
            raw,actual_hash,actual_available=self.h.db.execute('SELECT body,hash,first_seen FROM canonical_evidence WHERE identity=?',(identity,)).fetchone()
            self.assertEqual(decode_body(raw,self.h.db),body)
            self.assertEqual((actual_hash,actual_available),(checksum,available))
