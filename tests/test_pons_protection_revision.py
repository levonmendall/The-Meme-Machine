"""Native protection survives peer writes, rollback and true owner reuse."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from meme_machine.runtime.robinhood.plane import Plane, canonical
from meme_machine.runtime.robinhood.pons import save_cohort_checkpoint


class PonsProtectionRevisionTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,dict(MM_MODE='PAPER',MM_OPERATIONAL_PHASE='OFFLINE_TEST'),clear=True))
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()));self.path=self.root/'plane.sqlite'
        self.now=200000.;self.serial=0;self.plane=Plane(self.path,clock=lambda:self.now)
        self.addCleanup(lambda:self.plane.close())

    def candidate(self,key,*,observed=None):
        self.serial+=1
        self.plane.observe(key,'pons',str(self.serial),dict(synthetic=True),ordering=(self.serial,),watermark=dict(block=self.serial),
            interpretation=dict(policy='offline'),observed=self.now-90000 if observed is None else observed,
            deadline=self.now+5,priority=3,needs_work=False)

    def cohort(self,*keys,padding=0,owner=None):
        (owner or self.plane).checkpoint('pons_cohort',dict(result=dict(
            qualifiers=[dict(curve=key) for key in keys],lifecycles=[],synthetic_padding='x'*padding)))

    def peer(self):
        peer=Plane(self.path,clock=lambda:self.now);self.addCleanup(peer.close);return peer

    def test_unrelated_peer_commit_reuses_only_compact_protection_and_covering_membership(self):
        self.candidate('protected');self.cohort('protected',padding=2*1024**2);self.plane.maintain()
        peer=self.peer();peer.checkpoint('unrelated_survivor_cursor',dict(sequence=1))
        statements=[];self.plane.db.set_trace_callback(statements.append)
        try:self.plane.maintain()
        finally:self.plane.db.set_trace_callback(None)
        self.assertIsNotNone(self.plane.get('protected'))
        self.assertFalse(any("OR key='pons_cohort'" in sql for sql in statements))
        self.assertFalse(any('SELECT * FROM candidates' in sql for sql in statements))
        self.assertTrue(any('candidate_retirement_membership' in sql for sql in statements))
        plan=self.plane.db.execute('EXPLAIN QUERY PLAN SELECT id FROM candidates INDEXED BY candidate_retirement_membership WHERE lane=? AND pending=0 AND claim IS NULL AND observed<?',('pons',self.now-86400)).fetchall()
        self.assertTrue(any('COVERING INDEX candidate_retirement_membership' in row[3] for row in plan))

    def test_peer_raw_update_replace_delete_and_key_move_invalidate(self):
        for method in ('update','replace','delete','move'):
            with self.subTest(method=method):
                for key in ('a','b'):self.candidate(key)
                self.cohort('a');self.plane.maintain()
                self.candidate('b')
                with closing(sqlite3.connect(self.path)) as db,db:
                    if method=='delete':db.execute("DELETE FROM runtime WHERE key='pons_cohort'")
                    elif method=='move':db.execute("UPDATE runtime SET key='not_a_cohort' WHERE key='pons_cohort'")
                    elif method=='replace':db.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)',
                        ('pons_cohort',canonical(dict(result=dict(qualifiers=[dict(curve='b')])))))
                    else:db.execute('UPDATE runtime SET body=? WHERE key=?',
                        (canonical(dict(result=dict(qualifiers=[dict(curve='b')]))),'pons_cohort'))
                self.plane.maintain()
                self.assertIsNone(self.plane.get('a'))
                self.assertEqual(self.plane.get('b') is not None,method in ('update','replace'))

    def test_old_plain_sqlite_writer_process_obeys_persistent_revision(self):
        self.candidate('a');self.candidate('b');self.cohort('a');self.plane.maintain();self.candidate('b')
        code="import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute('UPDATE runtime SET body=? WHERE key=?',(sys.argv[2],'pons_cohort')); db.commit(); db.close()"
        subprocess.run([sys.executable,'-I','-B','-c',code,str(self.path),canonical(dict(result=dict(qualifiers=[dict(curve='b')])))] ,check=True,timeout=5)
        self.plane.maintain();self.assertIsNone(self.plane.get('a'));self.assertIsNotNone(self.plane.get('b'))

    def test_native_position_changes_protect_then_release_and_delete_on_same_snapshot(self):
        self.candidate('held');self.cohort()
        self.plane.checkpoint('native_position:pons:held',dict(candidate='held',position=dict(status='filled')))
        self.plane.maintain();self.assertIsNotNone(self.plane.get('held'))
        peer=self.peer();peer.checkpoint('native_position:pons:held',dict(candidate='held',position=dict(status='settled')))
        self.plane.maintain();self.assertIsNone(self.plane.get('held'))
        self.assertIsNone(self.plane.checkpoint_read('native_position:pons:held'))
        self.assertTrue(self.plane._protection_cache is None
            or self.plane._protection_cache[0]<self.plane._protection_generation())

    def test_actual_age_boundary_and_unconsumed_generation_remain_fresh(self):
        self.candidate('young',observed=self.now);self.cohort()
        self.plane.maintain();self.assertIsNotNone(self.plane.get('young'))
        self.now+=86401;self.plane.maintain();self.assertIsNone(self.plane.get('young'))
        self.plane.observe('decision','pons','event',dict(synthetic=True),ordering=(2,),watermark={},
            interpretation={},observed=self.now,deadline=self.now+5,priority=3)
        work=self.plane.claim(lane='pons');self.assertTrue(self.plane.finish(work,result=dict(synthetic=True)))
        self.now+=86401;self.plane.maintain();self.assertIsNotNone(self.plane.get('decision'))
        self.plane.consume('decision',work['generation']);self.plane.maintain()
        self.assertIsNone(self.plane.get('decision'))

    def test_paused_candidate_and_native_namespace_stay_preserved(self):
        self.candidate('active');self.cohort()
        with self.plane.transaction():
            self.plane.db.execute("INSERT INTO candidates SELECT 'paused','ramses',generation,interpretation,latest_id,observed,ordering,desired,completed,payload,state,reason,pending,priority,rank,deadline,queued,claim,owner,claim_generation,claim_until,result FROM candidates WHERE id='active'")
            self.plane.db.execute('INSERT INTO runtime VALUES(?,?)',('native_position:ramses:paused',canonical(dict(candidate='paused',position=dict(status='settled')))))
        self.plane.maintain();self.assertIsNone(self.plane.get('active'))
        self.assertIsNotNone(self.plane.get('paused'));self.assertIsNotNone(self.plane.checkpoint_read('native_position:ramses:paused'))

    def test_rollback_does_not_publish_uncommitted_revision_reused_by_later_write(self):
        for key in ('a','b','c'):self.candidate(key)
        self.cohort('a');self.plane.maintain()
        for key in ('b','c'):self.candidate(key)
        prior=self.plane._protection_cache;original=self.plane.transaction
        @contextmanager
        def failing():
            with original():
                self.plane.db.execute('UPDATE runtime SET body=? WHERE key=?',
                    (canonical(dict(result=dict(qualifiers=[dict(curve='b')]))),'pons_cohort'))
                yield
                raise RuntimeError('injected_before_original_commit')
        with patch.object(self.plane,'transaction',failing):
            with self.assertRaisesRegex(RuntimeError,'injected_before_original_commit'):self.plane.maintain()
        self.assertIs(self.plane._protection_cache,prior)
        self.cohort('c',owner=self.peer());self.plane.maintain()
        self.assertIsNone(self.plane.get('a'));self.assertIsNone(self.plane.get('b'));self.assertIsNotNone(self.plane.get('c'))

    def test_failed_commit_publishes_no_new_cache_or_retirement(self):
        self.candidate('a');self.cohort('a');self.plane.maintain();old=self.plane._protection_cache
        self.cohort('a',owner=self.peer());self.candidate('unprotected')
        original=self.plane.db
        class FailingCommit:
            def __getattr__(self,name):return getattr(original,name)
            def execute(self,sql,*args):
                if sql=='COMMIT':raise sqlite3.OperationalError('injected_commit_failure')
                return original.execute(sql,*args)
        with patch.object(self.plane,'db',FailingCommit()):
            with self.assertRaises(sqlite3.OperationalError):self.plane.maintain()
        self.assertIs(self.plane._protection_cache,old);self.assertIsNotNone(self.plane.get('unprotected'))

    def test_counter_reset_delete_replace_and_schema_tampering_fail_closed(self):
        self.candidate('a');self.cohort('a');self.plane.maintain()
        for sql in ('UPDATE candidate_protection_revision SET generation=generation',
                'UPDATE candidate_protection_revision SET generation=0',
                'DELETE FROM candidate_protection_revision',
                'INSERT OR REPLACE INTO candidate_protection_revision VALUES(1,0)'):
            with self.assertRaises(sqlite3.IntegrityError):self.plane.db.execute(sql)
        self.plane.db.execute('DROP TRIGGER candidate_protection_runtime_update')
        self.plane.db.execute("UPDATE runtime SET body='{}' WHERE key='pons_cohort'")
        with self.assertRaisesRegex(ValueError,'candidate_protection_schema'):self.plane.maintain()
        self.assertIsNotNone(self.plane.get('a'))

    def test_needed_branch_malformed_body_and_reopened_owner_never_reuse_old_cache(self):
        self.candidate('a');self.cohort('a');self.plane.maintain();self.plane.close()
        self.plane=Plane(self.path,clock=lambda:self.now)
        self.assertIsNone(self.plane._protection_cache)
        self.plane.db.execute("UPDATE runtime SET body='not json' WHERE key='pons_cohort'")
        with self.assertRaises(json.JSONDecodeError):self.plane.maintain()
        self.assertIsNotNone(self.plane.get('a'))

    def test_concurrent_peer_write_after_read_cannot_reuse_obsolete_protection(self):
        for key in ('a','b'):self.candidate(key)
        self.cohort('a');peer=self.peer();started=threading.Event();done=threading.Event()
        original=self.plane._protection_facts
        def gated(generation):
            value=original(generation);started.set()
            self.assertFalse(done.wait(.02));return value
        def write():
            self.assertTrue(started.wait(2));self.cohort('b',owner=peer);done.set()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(write)
            with patch.object(self.plane,'_protection_facts',gated):self.plane.maintain()
            future.result(2)
        self.candidate('b');self.plane.maintain()
        self.assertIsNone(self.plane.get('a'));self.assertIsNotNone(self.plane.get('b'))

    def test_scope_change_rechecks_compact_protection_without_a_runtime_write(self):
        self.candidate('held',observed=self.now)
        self.plane.db.execute('INSERT INTO runtime VALUES(?,?)',('native_position:ramses:held',canonical(dict(candidate='held',position=dict(status='filled')))))
        generation=self.plane._protection_generation()
        self.plane._protection_cache=self.plane._protection_facts(generation)
        self.assertNotIn('held',self.plane._protection_cache[1])
        self.plane.maintain();self.now+=86401
        with patch.dict(os.environ,dict(MM_MODE='PAPER'),clear=True):
            self.plane.maintain()
            self.assertIsNotNone(self.plane.get('held'))
            self.assertIn('held',self.plane._protection_cache[1])

    def test_same_clock_scope_change_invalidates_the_maintenance_skip(self):
        self.candidate('held')
        self.plane.db.execute('INSERT INTO runtime VALUES(?,?)',('native_position:ramses:held',canonical(dict(candidate='held',position=dict(status='filled')))))
        with patch.dict(os.environ,dict(MM_MODE='PAPER'),clear=True):
            self.plane.maintain();self.assertIsNotNone(self.plane.get('held'))
        self.plane.maintain()
        self.assertIsNone(self.plane.get('held'))
        self.assertIsNotNone(self.plane.checkpoint_read('native_position:ramses:held'))

    def test_exact_4d_adapter_transition_keeps_prior_decision_and_fences_old_reply(self):
        from meme_machine.runtime.robinhood.pons import Broker
        from meme_machine.runtime.robinhood.plane import digest
        from meme_machine.lanes.pons.abi import topic
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        from tests.lanes.pons.test_pons_candidate_plane import event
        path=self.root/'adapter.sqlite';value=event()
        value['topics']=[topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)')]
        with closing(Broker(path,POLICY_HASH,clock=lambda:self.now)) as broker:
            broker.enqueue(value);scheduled=broker.pop();key=scheduled['key']
            self.assertTrue(broker.plane.finish(scheduled['work'],result=dict(qualified=False,reason='synthetic_prior_rejection')))
            broker.plane.consume(key,scheduled['work']['generation'])
            broker.plane.decision(key,scheduled['work']['generation'],'strategy_rejected','synthetic_prior_rejection')
            # Exact pons.py bytes at deployed 4d255c12, not a forged successor hash.
            old=dict(broker.policy,adapter_source='52defbb90f754e7b2ea88e4527bf7bdc30d6251854f89a37f52dabbb70a931f0')
            self.assertNotEqual(old['adapter_source'],broker.policy['adapter_source'])
            watch=json.loads(broker.plane.db.execute('SELECT body FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()[0])
            watch['interpretation']=old
            broker.plane.db.execute('UPDATE candidates SET interpretation=? WHERE id=?',(canonical(old),key))
            broker.plane.db.execute('UPDATE pons_current_watch SET body=?,hash=? WHERE candidate=?',(canonical(watch),digest(watch),key))
            prior=broker.plane.get(key)
        with closing(Broker(path,POLICY_HASH,clock=lambda:self.now)) as reopened:
            row=reopened.plane.get(key)
            self.assertEqual((row['observed'],row['ordering'],row['latest_id']),(prior['observed'],prior['ordering'],prior['latest_id']))
            self.assertGreater(row['generation'],prior['generation']);self.assertIsNone(row['result']);self.assertIsNone(row['completed'])
            self.assertFalse(reopened.plane.finish(scheduled['work'],result=dict(qualified=True)))
            audit=json.loads(reopened.plane.db.execute("SELECT details FROM transitions WHERE reason='pons_adapter_change_requires_fresh_canonical_state'").fetchone()[0])
            self.assertEqual(json.loads(audit['prior_candidate']['interpretation']),old)
            self.assertEqual(json.loads(audit['prior_candidate']['result'])['reason'],'synthetic_prior_rejection')

    def test_rolled_back_schema_token_cannot_authorize_reused_schema_version(self):
        self.candidate('a');self.cohort('a');self.plane.maintain()
        peer=self.peer()
        original=self.plane.db.execute("SELECT sql FROM sqlite_master WHERE name='candidate_protection_runtime_update'").fetchone()[0]
        before=self.plane._protection_schema_version
        with self.assertRaisesRegex(RuntimeError,'rollback_schema'):
            with self.plane.transaction():
                self.plane.db.execute('DROP TRIGGER candidate_protection_runtime_update')
                self.plane.db.execute(original)
                self.plane._protection_generation()
                raise RuntimeError('rollback_schema')
        self.assertEqual(self.plane._protection_schema_version,before)
        self.plane.db.execute('DROP TRIGGER candidate_protection_runtime_update')
        self.plane.db.execute(original.replace('generation=generation+1','generation=generation+0'))
        peer.checkpoint('unrelated',{})
        with self.assertRaisesRegex(ValueError,'candidate_protection_schema'):self.plane.maintain()
        self.assertIsNotNone(self.plane.get('a'))

    def test_borrow_recovers_expired_claim_and_failed_save_does_not_close_owner(self):
        self.plane.observe('pending','pons','event',{},ordering=(1,),watermark={},interpretation={},
            observed=self.now,deadline=self.now+5,priority=3)
        self.assertIsNotNone(self.plane.claim(lane='pons'))
        self.now+=6
        value=dict(candidate_plane_path=str(self.path),rows=[])
        save_cohort_checkpoint(value,1,'recovery',plane=self.plane)
        self.assertIsNone(self.plane.get('pending')['claim'])
        with patch.object(self.plane,'checkpoint',side_effect=RuntimeError('save_failure')):
            with self.assertRaisesRegex(RuntimeError,'save_failure'):save_cohort_checkpoint(value,2,'failed',plane=self.plane)
        self.assertFalse(self.plane._closed);self.assertIsNotNone(self.plane.get('pending'))

    def test_borrow_refuses_replaced_inode_and_reopen_keeps_integrity_check(self):
        old=self.root/'old.sqlite';self.path.rename(old)
        with closing(sqlite3.connect(self.path)) as db:db.execute('CREATE TABLE foreign_file(x)')
        value=dict(candidate_plane_path=str(self.path),rows=[])
        with self.assertRaisesRegex(ValueError,'candidate_checkpoint_inode'):save_cohort_checkpoint(value,1,'foreign',plane=self.plane)
        self.plane.close()
        bad=self.root/'corrupt.sqlite';bad.write_bytes(b'not a SQLite database'*100)
        with self.assertRaises(sqlite3.DatabaseError):Plane(bad)

    def test_owned_checkpoint_uses_actual_owner_without_constructor_and_preserves_ownership(self):
        value=dict(candidate_plane_path=str(self.path),rows=[],qualifiers=[],lifecycles=[])
        with patch.object(Plane,'__init__',side_effect=AssertionError('reopened_owner')):
            save_cohort_checkpoint(value,7,'native',plane=self.plane)
        self.assertEqual(self.plane.checkpoint_read('pons_cohort')['cursor'],7)
        self.assertFalse(self.plane._closed)
        default=dict(value);save_cohort_checkpoint(default,8,'default')
        self.assertEqual(self.plane.checkpoint_read('pons_cohort')['cursor'],8)

    def test_borrow_refuses_foreign_thread_closed_owner_active_transaction_and_wrong_path(self):
        value=dict(candidate_plane_path=str(self.path),rows=[])
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaisesRegex(ValueError,'candidate_checkpoint_owner'):
                pool.submit(save_cohort_checkpoint,value,1,'wrongthread',plane=self.plane).result(2)
        with self.plane.transaction():
            with self.assertRaisesRegex(ValueError,'candidate_checkpoint_owner'):
                save_cohort_checkpoint(value,1,'nested',plane=self.plane)
        with self.assertRaisesRegex(ValueError,'candidate_checkpoint_owner'):
            save_cohort_checkpoint(dict(value,candidate_plane_path=str(self.root/'other.sqlite')),1,'wrongpath',plane=self.plane)
        self.plane.close()
        with self.assertRaisesRegex(ValueError,'candidate_checkpoint_owner'):save_cohort_checkpoint(value,1,'closed',plane=self.plane)


if __name__=='__main__':unittest.main()
