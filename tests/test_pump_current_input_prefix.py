"""Fixed-cut exact tuple accounting; private producer/native wiring is separate."""
import unittest
import sqlite3
import threading
from copy import deepcopy
import json

from meme_machine.runtime.pump_current_input_prefix import (
    CurrentInputPrefixes, InheritedKeyCensus, SCOPES, advance, empty_prefix,
    project_input_context,
)


def census(rows):
    value = empty_prefix()
    for row in rows: value = advance(value, row)
    return value


def row(number, *, available=100):
    # Global sequence gaps from other source programs are intentional.
    # Original _queue_events reads first_seen back from SQLite's REAL column
    # before building its exact pending tuple. Its chain therefore uses floats.
    return (2**62 + number * 3, 'native-event:' + str(number), 'program:pump', number, float(available))


def publication(inherited, fresh):
    programs = {scope: empty_prefix() for scope in SCOPES}
    programs['program:pump'] = census(fresh)
    return dict(schema='normal-source-publication-frontier-v1',
        identity_sha256='a' * 64, generation='b' * 32,
        active_programs=['program:pump', 'program:pumpswap'],
        initial_program_outbox_sequence={scope: inherited['last_sequence']
            if scope == 'program:pump' else None for scope in SCOPES},
        economic=dict(all=dict(programs['program:pump']), programs=programs))


class CurrentInputPrefixTests(unittest.TestCase):
    def meter(self, inherited):
        return CurrentInputPrefixes('c' * 64, census(inherited), 'a' * 64, 'b' * 32)

    def apply(self, meter, rows, metadata, *, commit=True, first=None):
        ticket = meter.capture(meter.cursor if first is None else first, rows, metadata, as_of=100)
        self.assertIsNotNone(ticket)
        if commit: meter.committed(ticket)
        return ticket

    def test_inherited_population_over_5000_requires_all_original_pages(self):
        inherited = [row(i) for i in range(1, 10002)]
        meter = self.meter(inherited); metadata = publication(census(inherited), [])
        for page in (inherited[:5000], inherited[5000:10000]):
            self.apply(meter, page, metadata)
            self.assertFalse(meter.snapshot()['inherited_prefix_retained'])
        ticket = self.apply(meter, inherited[10000:], metadata, commit=False)
        self.assertEqual(meter.snapshot()['inherited_retained']['records'], 10000)
        self.assertEqual(meter.snapshot()['state'], 'INCOMPLETE')
        meter.committed(ticket); view = meter.snapshot()
        self.assertEqual(view['inherited_retained'], census(inherited))
        self.assertTrue(view['inherited_prefix_retained'])
        self.assertTrue(view['source_issuance_prefix_retained'])
        self.assertEqual(view['state'], 'OBSERVED')
        self.assertFalse(view['readiness_authority'])

    def test_source_and_consumer_partitions_and_other_program_gaps_do_not_change_chain(self):
        inherited = [row(i) for i in range(1, 12)]
        fresh = [row(i) for i in range(12, 34)]
        metadata = publication(census(inherited), fresh)
        for pages in ((inherited + fresh,), ((inherited + fresh)[:17], (inherited + fresh)[17:])):
            meter = self.meter(inherited)
            for page in pages: self.apply(meter, page, metadata)
            self.assertEqual(meter.snapshot()['source_retained'], census(fresh))
            self.assertEqual(meter.snapshot()['inherited_retained'], census(inherited))
            self.assertEqual(meter.snapshot()['state'], 'OBSERVED')

    def test_missing_metadata_or_future_visibility_is_not_smaller_empty_population(self):
        inherited = [row(1), row(2, available=101)]
        meter = self.meter(inherited)
        self.apply(meter, inherited[:1], None)
        self.apply(meter, [], None)
        view = meter.snapshot()
        self.assertEqual(view['state'], 'INCOMPLETE')
        self.assertFalse(view['inherited_prefix_retained'])
        self.assertEqual(view['inherited_expected']['records'], 2)
        self.assertEqual(view['inherited_retained']['records'], 1)
        self.assertIsNone(meter.capture(meter.cursor, inherited[1:],
            publication(census(inherited), []), as_of=100))
        self.assertEqual(meter.snapshot()['state'], 'UNKNOWN')

    def test_failed_or_cancelled_retention_does_not_publish_staged_progress(self):
        inherited = [row(1), row(2)]
        meter = self.meter(inherited)
        self.apply(meter, inherited, publication(census(inherited), []), commit=False)
        view = meter.snapshot()
        self.assertEqual(view['inherited_retained']['records'], 0)
        self.assertTrue(view['capture_pending'])
        self.assertFalse(view['inherited_prefix_retained'])
        self.assertEqual(view['state'], 'INCOMPLETE')

    def test_exact_last_batch_replay_is_physical_work_not_new_economics(self):
        inherited = [row(1), row(2)]; meter = self.meter(inherited)
        metadata = publication(census(inherited), [])
        self.apply(meter, inherited, metadata)
        self.apply(meter, inherited, metadata, first=0)
        view = meter.snapshot()
        self.assertEqual(view['inherited_retained']['records'], 2)
        self.assertEqual(view['physical_replay_rows'], 2)
        changed = [row(1), (*row(2)[:3], 99, 100)]
        self.assertIsNone(meter.capture(0, changed, metadata, as_of=100))
        self.assertEqual(meter.snapshot()['state'], 'UNKNOWN')

    def test_crossed_source_cut_or_generation_cannot_authenticate_new_prefix(self):
        inherited = [row(1)]; metadata = publication(census(inherited), [row(2)])
        for field in ('cut', 'generation', 'digest'):
            with self.subTest(field=field):
                value = publication(census(inherited), [row(2)])
                if field == 'cut': value['initial_program_outbox_sequence']['program:pump'] += 1
                elif field == 'generation': value['generation'] = 'd' * 32
                else: value['economic']['programs']['program:pump']['prefix_sha256'] = 'e' * 64
                meter = self.meter(inherited)
                self.assertIsNone(meter.capture(0, inherited + [row(2)], value, as_of=100))
                self.assertEqual(meter.snapshot()['state'], 'UNKNOWN')
                self.assertEqual(meter.snapshot()['inherited_retained']['records'], 0)

    def test_advancing_source_frontier_and_missing_latest_metadata_preserve_old_counts(self):
        inherited = [row(1)]; fresh = [row(2), row(3)]
        meter = self.meter(inherited)
        self.apply(meter, inherited + fresh[:1], publication(census(inherited), fresh[:1]))
        self.assertEqual(meter.snapshot()['state'], 'OBSERVED')
        self.apply(meter, [], publication(census(inherited), fresh))
        self.assertEqual(meter.snapshot()['state'], 'INCOMPLETE')
        self.apply(meter, fresh[1:], publication(census(inherited), fresh))
        self.assertEqual(meter.snapshot()['state'], 'OBSERVED')
        self.apply(meter, [], None)
        view = meter.snapshot()
        self.assertEqual(view['source_retained'], census(fresh))
        self.assertEqual(view['source_expected'], census(fresh))
        self.assertEqual(view['state'], 'INCOMPLETE')
        self.assertFalse(view['source_issuance_prefix_retained'])


class InheritedKeyCensusTests(unittest.TestCase):
    def database(self, rows):
        db=sqlite3.connect(':memory:',isolation_level=None)
        self.addCleanup(db.close)
        db.executescript('''CREATE TABLE candidate_outbox(
            sequence INTEGER PRIMARY KEY,identity TEXT NOT NULL UNIQUE,scope TEXT NOT NULL,
            slot INTEGER NOT NULL,first_seen REAL NOT NULL);
            CREATE INDEX candidate_outbox_scope ON candidate_outbox(scope,sequence);''')
        db.executemany('INSERT INTO candidate_outbox VALUES(?,?,?,?,?)',rows)
        return db

    def capture(self, meter, db, *, validate=lambda:True, cancelled=lambda:False, commit=True):
        db.execute('BEGIN')
        try:ticket=meter.capture(db,validate=validate,cancelled=cancelled)
        finally:db.execute('ROLLBACK')
        self.assertFalse(db.in_transaction)
        if commit and ticket is not None:meter.committed(ticket)
        return ticket

    def test_real_indexed_5001_key_population_requires_lookahead_then_genuine_eof(self):
        rows=[row(i) for i in range(1,5002)];db=self.database(rows)
        original_progress=[]
        db.set_progress_handler(lambda:original_progress.append(1) or 0,1000)
        meter=InheritedKeyCensus(rows[-1][0],100,clock=lambda:0)
        first=self.capture(meter,db)
        self.assertEqual(first.rows,5000);self.assertFalse(meter.complete)
        self.assertEqual(meter.snapshot()['population']['records'],5000)
        self.assertTrue(original_progress)
        self.capture(meter,db)
        self.assertTrue(meter.complete);self.assertEqual(meter.prefix,census(rows))
        self.assertIn('NOT_DB_ENFORCED',meter.snapshot()['contract'])
        plan=' '.join(str(item) for item in db.execute('EXPLAIN QUERY PLAN SELECT sequence '
            "FROM candidate_outbox INDEXED BY candidate_outbox_scope WHERE scope='program:pump' "
            'AND sequence>? AND sequence<=? ORDER BY sequence LIMIT 5001',(0,rows[-1][0])))
        self.assertIn('candidate_outbox_scope',plan)
        previous=len(original_progress)
        db.execute('SELECT SUM(slot) FROM candidate_outbox').fetchone()
        self.assertGreater(len(original_progress),previous)

    def test_expired_metadata_prefix_is_retained_only_after_snapshot_close_then_resumed(self):
        rows=[row(i) for i in range(1,8)];db=self.database(rows);ticks=[0.0];closed=[]
        class Cursor:
            def __init__(self,original):self.original=original
            def fetchone(self):
                value=self.original.fetchone();ticks[0]+=.01;return value
            def close(self):closed.append(True);self.original.close()
        class DB:
            @property
            def in_transaction(self):return db.in_transaction
            def execute(self,*args):return Cursor(db.execute(*args))
        meter=InheritedKeyCensus(rows[-1][0],100,clock=lambda:ticks[0])
        while not meter.complete:
            db.execute('BEGIN')
            try:ticket=meter.capture(DB(),validate=lambda:True,cancelled=lambda:False)
            finally:db.execute('ROLLBACK')
            self.assertIsNotNone(ticket);self.assertTrue(closed)
            before=meter.prefix['records'];self.assertLessEqual(ticket.rows,3)
            self.assertEqual(meter.prefix['records'],before)
            meter.committed(ticket)
        self.assertEqual(meter.prefix,census(rows));self.assertGreater(meter.expired,0)

    def test_original_cancellation_closes_sql_cursor_and_never_claims_eof(self):
        from meme_machine.runtime.stop import Shutdown
        rows=[row(i) for i in range(1,5)];db=self.database(rows);stop=threading.Event();closed=[]
        class Cursor:
            def __init__(self,original):self.original=original
            def fetchone(self):
                value=self.original.fetchone();stop.set();return value
            def close(self):closed.append(True);self.original.close()
        class DB:
            @property
            def in_transaction(self):return db.in_transaction
            def execute(self,*args):return Cursor(db.execute(*args))
        meter=InheritedKeyCensus(rows[-1][0],100,clock=lambda:0)
        db.execute('BEGIN')
        try:
            with self.assertRaises(Shutdown):
                meter.capture(DB(),validate=lambda:True,cancelled=stop.is_set)
        finally:db.execute('ROLLBACK')
        self.assertTrue(closed);self.assertFalse(meter.complete)
        self.assertEqual(meter.prefix['records'],0);self.assertIsNone(meter.staged)

    def test_fixed_cut_ignores_new_appends_but_keeps_future_old_keys_in_expected_population(self):
        rows=[row(1),row(2,available=101)];db=self.database(rows)
        meter=InheritedKeyCensus(rows[-1][0],100,clock=lambda:0)
        db.execute('INSERT INTO candidate_outbox VALUES(?,?,?,?,?)',row(3))
        self.capture(meter,db)
        self.assertTrue(meter.complete);self.assertEqual(meter.prefix,census(rows))
        self.assertEqual(meter.future_rows,1)
        native=CurrentInputPrefixes('c'*64,None,'a'*64,'b'*32,inherited_upper=rows[-1][0])
        ticket=native.capture(0,rows[:1],publication(census(rows),[]),as_of=100)
        native.committed(ticket);native.census_sealed(meter.prefix)
        self.assertEqual(native.snapshot()['state'],'INCOMPLETE')
        self.assertFalse(native.snapshot()['inherited_prefix_retained'])
        self.assertEqual(native.snapshot()['inherited_expected']['records'],2)
        self.assertIn('NOT_CLOSED',native.snapshot()['queued_native_work'])

    def test_changed_owner_schema_or_missing_support_tail_refuses_without_fake_eof(self):
        rows=[row(1),row(2)];db=self.database(rows)
        meter=InheritedKeyCensus(rows[-1][0],100,clock=lambda:0)
        self.assertIsNone(self.capture(meter,db,validate=lambda:False))
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN');self.assertFalse(meter.complete)
        # A missing tail contradicts the authentic cut even under the stated
        # trusted-writer premise. This is a negative corruption fixture, not an
        # assertion of arbitrary malicious-peer mutation defense.
        db.execute('DELETE FROM candidate_outbox WHERE sequence=?',(rows[-1][0],))
        missing=InheritedKeyCensus(rows[-1][0],100,clock=lambda:0)
        self.capture(missing,db)
        self.assertEqual(missing.snapshot()['state'],'UNKNOWN');self.assertFalse(missing.complete)
        db.execute('DROP INDEX candidate_outbox_scope')
        schema=InheritedKeyCensus(rows[0][0],100,clock=lambda:0)
        self.assertIsNone(self.capture(schema,db))
        self.assertEqual(schema.snapshot()['state'],'UNKNOWN')


class InputProjectionTests(unittest.TestCase):
    def complete(self):
        # A public shape fixture is not a private support issuer or a runtime
        # success witness. Exercise the exact pure reducers to build its fields.
        db=sqlite3.connect(':memory:',isolation_level=None);self.addCleanup(db.close)
        db.executescript('CREATE TABLE candidate_outbox(sequence,identity,scope,slot,first_seen);'
            'CREATE INDEX candidate_outbox_scope ON candidate_outbox(scope,sequence);')
        key=InheritedKeyCensus(None,100,clock=lambda:0)
        db.execute('BEGIN')
        try:ticket=key.capture(db,validate=lambda:True,cancelled=lambda:False)
        finally:db.execute('ROLLBACK')
        key.committed(ticket)
        meter=CurrentInputPrefixes('c'*64,None,'a'*64,'b'*32)
        capture=meter.capture(0,[],publication(empty_prefix(),[]),as_of=100)
        meter.census_sealed(key.prefix);meter.committed(capture)
        return dict(schema='pump-current-input-context-v1',state='OBSERVED',
            support_identity_sha256='c'*64,private_owner_sha256='d'*64,
            key_census=key.snapshot(),retained_prefix=meter.snapshot())

    def test_projection_requires_real_eof_and_exact_retained_census_and_drops_private_content(self):
        value=self.complete();value['private_provider']='never export'
        view=project_input_context(value)
        self.assertEqual(view['state'],'OBSERVED');self.assertEqual(project_input_context(view),view)
        self.assertNotIn('never export',json.dumps(view));self.assertLessEqual(len(json.dumps(view).encode()),4096)
        for kind in ('lookahead','pending','different_count','different_hash','source_mismatch'):
            with self.subTest(kind=kind):
                bad=deepcopy(value)
                if kind=='lookahead':bad['key_census']['state']='INCOMPLETE'
                elif kind=='pending':bad['key_census']['capture_pending']=True
                elif kind=='different_count':bad['retained_prefix']['inherited_expected']=census([row(1)])
                elif kind=='different_hash':bad['retained_prefix']['inherited_expected']['prefix_sha256']='f'*64
                else:bad['retained_prefix']['source_expected']=census([row(1)])
                self.assertEqual(project_input_context(bad)['state'],'UNKNOWN')

    def test_original_current_envelope_retains_dense_cumulative_stage_counts_and_prefix(self):
        from meme_machine.runtime.native_work_cohort import NativeWorkCohorts
        from meme_machine.runtime.pump_current_work import PumpCurrentWork,project_current_work
        from meme_machine.runtime.economic_cohort import checksum
        value=PumpCurrentWork('/tmp/measurement-shape-only.sqlite','shape-epoch','a'*64).snapshot()
        for field,stage in (('discovery','DISCOVERY_INPUT'),('evaluation','NATIVE_EVALUATION')):
            meter=NativeWorkCohorts(dict(owner_pid=123,regime=field),stage)
            for number in range(24):
                cid=checksum([field,number]);pairs=((checksum(['key',number]),checksum('input')),)
                meter.begin(cid,checksum(['frontier',number]));meter.expect(cid,pairs)
                meter.seal_expected(cid,1,checksum(pairs),checksum(['traversal',number]))
                if number<16:
                    status='POLICY_FILTERED' if stage=='DISCOVERY_INPUT' else 'DECISION_COMMITTED'
                    receipt=None if stage=='DISCOVERY_INPUT' else checksum(['receipt',number])
                else:status,receipt='MISSING_HISTORY',None
                meter.observe(cid,((*pairs[0],status,receipt,None),))
            value[field]=meter.snapshot()
        value['native_input_prefix']=self.complete()
        view=project_current_work(value)
        self.assertEqual(view['native_input_prefix']['state'],'OBSERVED')
        for field in ('discovery','evaluation'):
            self.assertEqual(view[field]['completed_cohorts'],16)
            self.assertEqual(view[field]['active_cohorts'],8)
            self.assertEqual(view[field]['pending_units'],8)
            self.assertEqual(view[field]['cumulative_summary_sha256'],value[field]['cumulative_summary_sha256'])
        self.assertLessEqual(len(json.dumps(view).encode()),16384)
        self.assertEqual(project_current_work(view),view)

