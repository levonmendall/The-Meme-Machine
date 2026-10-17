"""Original Pump restore selection with real history and immutable references.

Only three disposable indexes are dropped for the reference comparison. The
query, corpus, source records, candidate observations and hashes stay identical.
VM instruction counts establish bounded offline work reduction, not live speed.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime.journal import canonical, digest
from meme_machine.runtime.stop import Shutdown


INDEX_COLUMNS = {
    'candidates_restore_order': ('candidates',('lane','first_observed','candidate')),
    'candidate_events_kind': ('events',('lane','candidate','kind')),
    'canonical_ref_kind': ('canonical_event_refs',('lane','candidate','kind')),
}
SELECTION = """SELECT body,hash FROM candidates AS c WHERE lane=? AND
    (EXISTS(SELECT 1 FROM events e WHERE e.lane=c.lane
        AND e.candidate=c.candidate AND e.kind GLOB ?)
    OR EXISTS(SELECT 1 FROM canonical_event_refs r WHERE r.lane=c.lane
        AND r.candidate=c.candidate AND r.kind GLOB ?))
    ORDER BY first_observed,lane,candidate"""
PARAMS = ('pump','pump_*','pump_*')


def normalized(sql):
    return ' '.join(sql.split())


class PumpRestoreSelectionIndexTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root/'candidate-history.sqlite'
        self.source = self.root/'solana-evidence.sqlite'
        self.now = 1000
        self.history = CandidateHistory(self.path,clock=lambda:self.now,worker_capacity=1)
        self.addCleanup(lambda:self.history.close())
        observations,events,refs = [],[],[]
        # Old Pump-lane candidates may have thousands of Swap-only records.
        # They must remain in history without expanding the Pump restore set.
        for index in range(64):
            name = f'old-swap-only-{index:03}'
            observations.append(('pump',name,10+index))
            for row in range(32):
                events.append(('pump',name,f'legacy-swap-{row:03}','pumpswap_trade'))
                refs.append(('pump',name,f'reference-swap-{row:03}','pumpswap_trade'))
        matches = []
        kinds = ('pump_create','pump_trade','pump_migration','pump_unusual')
        for index in range(16):
            name = f'pump-match-{index:03}'
            at = 100+index//2  # Ties retain original lane/candidate ordering.
            observations.append(('pump',name,at))
            target = refs if index%2 else events
            target.append(('pump',name,'qualifying-pump',kinds[index%len(kinds)]))
            events.append(('pump',name,'nonqualifying-legacy','pumpswap_trade'))
            refs.append(('pump',name,'nonqualifying-reference','pumpswap_trade'))
            matches.append((at,name))
        for index,kind in enumerate(('pumpXtrade','Pump_trade','pump','pumpswap_trade')):
            name = f'literal-prefix-excluded-{index}'
            observations.append(('pump',name,1))
            events.append(('pump',name,'literal-prefix-event',kind))
            refs.append(('pump',name,'literal-prefix-reference',kind))
        observations.extend((('pump','quiet-candidate',0),('pons','other-lane',0)))
        events.append(('pons','other-lane','other-lane-pump-event','pump_create'))
        self.expected_names = [name for _,name in sorted(matches)]
        records = {}
        with closing(sqlite3.connect(self.source)) as source:
            source.execute('CREATE TABLE canonical_evidence(identity TEXT PRIMARY KEY,body TEXT,hash TEXT,archive TEXT)')
            for index,(lane,name,identity,kind) in enumerate(refs):
                key = name+':'+identity
                record = dict(identity=key,kind='event',slot=1000+index,
                    transaction_index=0,event_index=0,market_time=1000,
                    payload=dict(event=dict(mint=name,event_type=kind)))
                records[key] = record
                source.execute('INSERT INTO canonical_evidence VALUES(?,?,?,NULL)',
                    (key,canonical(record),digest(record)))
            source.commit()
        # Every row uses the production observation/event/reference APIs. One
        # outer FULL transaction keeps fixture construction outside the probe.
        with self.history.transaction():
            for lane,name,at in observations:
                self.history.observe(lane,name,surface='pumpswap',observed_at=at,
                    decision_deadline=2000,metadata=dict(retained=True,name=name))
            for index,(lane,name,identity,kind) in enumerate(events):
                self.history.append_event(lane,name,identity=identity,slot=1000+index,
                    transaction_index=0,event_index=0,market_time=1000,
                    kind=kind,payload=dict(mint=name,event_type=kind))
            for lane,name,identity,kind in refs:
                record = records[name+':'+identity]
                self.history.append_reference(lane,name,record,path=self.source,
                    identity=identity,kind=kind)
        self.snapshot = self.rows()
        self.source_sha = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def rows(self):
        return {table:self.history.db.execute('SELECT * FROM '+table+
            ' ORDER BY lane,candidate'+(',identity' if table!='candidates' else '')).fetchall()
            for table in ('candidates','events','canonical_event_refs')}

    def drop_only_restore_indexes(self):
        for name in INDEX_COLUMNS:
            self.history.db.execute('DROP INDEX IF EXISTS '+name)

    def measure(self,operation):
        callbacks = [0]
        def progress():
            callbacks[0] += 1
            return 0
        self.history.db.set_progress_handler(progress,100)
        try:
            result = operation()
        finally:
            self.history.db.set_progress_handler(None,0)
        return result,callbacks[0]*100

    def query(self,*,limit=False):
        return self.history.db.execute(SELECTION+(' LIMIT 9' if limit else ''),PARAMS).fetchall()

    def api(self,**kwargs):
        return self.history.candidates(lane='pump',event_prefix='pump_',**kwargs)

    def assert_preserved(self):
        self.assertEqual(self.rows(),self.snapshot)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.source_sha)

    def test_actual_api_keeps_exact_query_population_order_and_candidate_hashes(self):
        self.drop_only_restore_indexes()
        before = self.api()
        original_rows,original_limit = self.query(),self.query(limit=True)
        self.history._install_schema()
        statements = []
        self.history.db.set_trace_callback(statements.append)
        try:
            after = self.api()
        finally:
            self.history.db.set_trace_callback(None)
        self.assertEqual(before,after)
        self.assertEqual([row['candidate'] for row in after],self.expected_names)
        self.assertEqual([json.loads(body) for body,_ in original_rows],after)
        self.assertEqual(self.query(),original_rows)
        self.assertEqual(self.query(limit=True),original_limit)
        selection = [sql for sql in statements if sql.startswith('SELECT body,hash FROM candidates AS c')]
        self.assertEqual(len(selection),1)
        original_sql = SELECTION.replace('lane=?',"lane='pump'",1)
        original_sql = original_sql.replace('GLOB ?',"GLOB 'pump_*'")
        self.assertEqual(normalized(selection[0]),normalized(original_sql))
        self.assertTrue(all(digest(json.loads(body))==checksum for body,checksum in original_rows))
        selected = self.expected_names[0]
        original_hash = self.history.db.execute('SELECT hash FROM candidates WHERE lane=? AND candidate=?',
            ('pump',selected)).fetchone()[0]
        self.history.db.execute('UPDATE candidates SET hash=? WHERE lane=? AND candidate=?',('f'*64,'pump',selected))
        try:
            with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):
                self.api()
        finally:
            self.history.db.execute('UPDATE candidates SET hash=? WHERE lane=? AND candidate=?',
                (original_hash,'pump',selected))
        self.assert_preserved()

    def test_full_and_limit_nine_queries_reduce_actual_sqlite_vm_work_on_same_corpus(self):
        self.drop_only_restore_indexes()
        old_full,old_full_steps = self.measure(self.api)
        old_limit,old_limit_steps = self.measure(lambda:self.query(limit=True))
        self.history._install_schema()
        new_full,new_full_steps = self.measure(self.api)
        new_limit,new_limit_steps = self.measure(lambda:self.query(limit=True))
        self.assertEqual(new_full,old_full)
        self.assertEqual(new_limit,old_limit)
        self.assertGreater(old_full_steps,0)
        self.assertGreater(old_limit_steps,0)
        self.assertGreater(new_full_steps,0)
        self.assertGreater(new_limit_steps,0)
        self.assertLess(new_full_steps*2,old_full_steps)
        self.assertLess(new_limit_steps*2,old_limit_steps)
        self.assert_preserved()
        print('PUMP_RESTORE_SELECTION_VM '+json.dumps(dict(
            old_full=old_full_steps,indexed_full=new_full_steps,
            old_limit9=old_limit_steps,indexed_limit9=new_limit_steps,
            selected=len(new_full),candidate_rows=len(self.snapshot['candidates']),
            event_rows=len(self.snapshot['events']),reference_rows=len(self.snapshot['canonical_event_refs']))),flush=True)

    def test_original_full_and_limit_nine_plans_use_covering_kind_and_restore_order_indexes(self):
        for limit in (False,True):
            with self.subTest(limit=limit):
                sql = SELECTION+(' LIMIT 9' if limit else '')
                details = [row[3] for row in self.history.db.execute('EXPLAIN QUERY PLAN '+sql,PARAMS)]
                self.assertTrue(any('candidates_restore_order' in detail for detail in details),details)
                self.assertTrue(any('COVERING INDEX candidate_events_kind' in detail for detail in details),details)
                self.assertTrue(any('COVERING INDEX canonical_ref_kind' in detail for detail in details),details)
                self.assertFalse(any('TEMP B-TREE' in detail for detail in details),details)
        self.assert_preserved()

    def test_schema_creation_is_idempotent_and_reopen_preserves_original_observations(self):
        original = self.api()
        for _ in range(2):
            self.history._install_schema()
        for name,(table,columns) in INDEX_COLUMNS.items():
            self.assertEqual(tuple(row[2] for row in self.history.db.execute('PRAGMA index_info('+name+')')),columns)
            self.assertEqual(self.history.db.execute('SELECT tbl_name FROM sqlite_master WHERE type=? AND name=?',
                ('index',name)).fetchone(),(table,))
        self.assert_preserved()
        self.history.close()
        self.history = CandidateHistory(self.path,clock=lambda:self.now,worker_capacity=1)
        self.assertEqual(self.api(),original)
        self.assert_preserved()
        ref_only = self.expected_names[1]
        self.assertTrue(self.history.events('pump',ref_only,kind_prefix='pump_'))
        self.assert_preserved()

    def test_original_startup_cancellation_interrupts_without_retiming_or_observation_loss(self):
        before = self.api()
        with patch.object(self.history,'clock',side_effect=AssertionError('startup_retiming_forbidden')):
            with self.assertRaises(Shutdown):
                self.api(cancelled=lambda:True)
            calls = [0]
            def cancelled():
                calls[0] += 1
                return calls[0]>=3
            with self.assertRaises(Shutdown):
                self.api(cancelled=cancelled)
            self.assertGreaterEqual(calls[0],3)
        self.assertFalse(self.history.db.in_transaction)
        self.assertEqual(self.api(),before)
        self.assert_preserved()
