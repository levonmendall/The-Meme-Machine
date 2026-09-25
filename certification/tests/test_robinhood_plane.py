import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from certification.robinhood.plane import Plane, canonical


class PlaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'plane.sqlite'
        self.now=100.;self.p=Plane(self.path,clock=lambda:self.now)
    def tearDown(self):self.p.close();self.tmp.cleanup()
    def observe(self,n=1,**kw):
        args=dict(ordering=(n,),watermark={'block':n,'hash':str(n)},interpretation={'policy':'frozen'},observed=self.now,deadline=self.now+5,priority=2)
        args.update(kw)
        return self.p.observe('curve','pons',str(n),{'n':n},**args)
    def test_identical_duplicate_never_refreshes_clock(self):
        self.observe();self.now+=3;self.assertEqual(self.observe(),'duplicate')
        self.assertEqual(self.p.get('curve')['deadline'],105)
    def test_conflict_is_durable_and_fails_closed(self):
        self.observe();self.p.observe('curve','pons','1',{'n':2},ordering=(1,),watermark={},interpretation={'policy':'frozen'},observed=100,deadline=105,priority=2)
        self.assertIsNone(self.p.claim());self.observe(2);self.assertIsNone(self.p.claim())
        self.assertEqual(self.p.get('curve')['reason'],'conflicting_observation')
    def test_ten_queued_updates_create_one_work(self):
        for n in range(1,12):self.observe(n)
        work=self.p.claim();self.assertEqual(work['generation'],11)
        self.assertIsNone(self.p.claim());self.assertEqual(self.p.snapshot()['unique_candidates'],1)
    def test_old_completion_cannot_update_new_generation(self):
        self.observe();old=self.p.claim();self.observe(2)
        self.assertFalse(self.p.finish(old,result={'qualified':True}))
        self.assertIsNone(self.p.get('curve')['completed'])
        new=self.p.claim();self.assertTrue(self.p.finish(new,result={'qualified':False}))
    def test_no_lock_across_external_work(self):
        self.observe();work=self.p.claim();other=Plane(self.path,clock=lambda:self.now)
        try:
            other.observe('curve','pons','2',{'n':2},ordering=(2,),watermark={'block':2},interpretation={'policy':'frozen'},observed=100,deadline=105,priority=2)
            self.assertFalse(self.p.current(work))
        finally:other.close()
    def test_live_claim_not_stolen_by_second_connection(self):
        self.observe();work=self.p.claim();other=Plane(self.path,clock=lambda:self.now)
        try:self.assertIsNone(other.claim());self.assertTrue(self.p.current(work))
        finally:other.close()
    def test_expired_claim_fences_provider_still_in_flight(self):
        self.observe();work=self.p.claim();self.now=106;self.observe(2)
        newer=self.p.claim();self.assertIsNotNone(newer)
        self.assertFalse(self.p.finish(work,result={}))
        self.assertTrue(self.p.current(newer))
    def test_restart_after_discovery_and_duplicate_redelivery(self):
        self.observe();self.p.close();self.p=Plane(self.path,clock=lambda:self.now)
        self.assertEqual(self.observe(),'duplicate');self.assertEqual(self.p.claim()['generation'],1)
    def test_commit_before_evaluation_survives_restart(self):
        self.observe();work=self.p.claim();self.p.finish(work,result={'decision':'reject'})
        self.p.close();self.p=Plane(self.path,clock=lambda:self.now)
        row=self.p.get('curve');self.assertEqual(json.loads(row['result']),{'decision':'reject'})
        self.assertTrue(self.p.decision('curve',1,'strategy_rejected','frozen_gate'))
        self.assertIsNone(self.p.claim())
    def test_decision_fence_after_new_observation(self):
        self.observe();self.p.finish(self.p.claim(),result={});self.observe(2)
        self.assertFalse(self.p.decision('curve',1,'qualified'))
    def test_capacity_defer_keeps_candidate_in_denominator(self):
        self.observe();self.assertIsNone(self.p.claim(estimate_seconds=6))
        self.assertEqual(self.p.snapshot()['candidate_states'],{'provider_capacity_defer':1})
        self.observe(2);self.assertIsNotNone(self.p.claim())
    def test_deadline_censoring_is_not_strategy_rejection(self):
        self.observe();self.now=106;self.assertIsNone(self.p.claim())
        self.assertEqual(self.p.get('curve')['state'],'freshness_deadline_censored')
    def test_complete_after_expiry_cannot_qualify(self):
        self.observe();work=self.p.claim();self.now=105
        self.assertFalse(self.p.finish(work,result={'qualified':True}))
        self.assertFalse(self.p.decision('curve',1,'qualified'))
    def test_policy_drift_fails_closed_even_duplicate(self):
        self.observe()
        with self.assertRaisesRegex(ValueError,'interpretation'):self.observe(interpretation={'policy':'changed'})
    def test_out_of_order_does_not_regress(self):
        self.observe(2);self.assertEqual(self.observe(1),'older');self.assertEqual(self.p.get('curve')['generation'],1)
    def test_safety_priority_survives_restart(self):
        self.observe()
        self.p.observe('position','ramses','safety',{},ordering=(1,),watermark={},interpretation={},observed=100,deadline=310,priority=0)
        self.p.close();self.p=Plane(self.path,clock=lambda:self.now)
        self.assertEqual(self.p.claim()['id'],'position')
    def test_fairness_never_overtakes_safety_or_entry(self):
        self.observe(priority=5,observed=1,deadline=105)
        self.p.observe('entry','pons','1',{},ordering=(1,),watermark={},interpretation={},observed=100,deadline=104,priority=1)
        self.assertEqual(self.p.claim()['id'],'entry')
    def test_concurrent_claims_exactly_one_winner(self):
        self.observe();barrier=threading.Barrier(2);out=[]
        def run():
            other=Plane(self.path,clock=lambda:self.now)
            try:barrier.wait();out.append(other.claim())
            finally:other.close()
        threads=[threading.Thread(target=run) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sum(x is not None for x in out),1)
    def test_authenticated_cache_conflict_and_block_isolation(self):
        self.p.put('canonical','blockA',{'value':1},{'authority':'alchemy'})
        self.assertIsNone(self.p.evidence('canonical','blockB'))
        with self.assertRaisesRegex(ValueError,'conflict'):self.p.put('canonical','blockA',{'value':2},{'authority':'alchemy'})
    def test_bounded_incremental_rolling_and_duplicate(self):
        proof={'authority':'authenticated_receipt_header','hash':'a'}
        for n in range(101):self.p.rolling_put('curve',str(n),n,n,{'event_at':n},proof)
        self.assertEqual(self.p.db.execute('SELECT COUNT(*) FROM rolling').fetchone()[0],61)
        self.p.rolling_put('curve','100',100,100,{'event_at':100},proof)
        self.assertEqual(self.p.rolling_get('curve','100',proof),{'event_at':100})
    def test_public_observation_cannot_enter_rolling_authority(self):
        with self.assertRaisesRegex(ValueError,'authority'):self.p.rolling_put('x','x',1,1,{}, {'authority':'public'})
    def test_audit_history_immutable(self):
        self.observe()
        with self.assertRaises(sqlite3.IntegrityError):self.p.db.execute('DELETE FROM transitions')
    def test_corrupt_store_fails_closed(self):
        path=Path(self.tmp.name)/'broken';path.write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError):Plane(path)
    def test_real_process_death_recovers_wal_and_work(self):
        script='''from certification.robinhood.plane import Plane
import os,sys
p=Plane(sys.argv[1],clock=lambda:100)
p.observe('curve','pons','1',{'n':1},ordering=(1,),watermark={'block':1,'hash':'1'},interpretation={'policy':'frozen'},observed=100,deadline=105,priority=2)
p.claim()
os._exit(0)
'''
        subprocess.run([sys.executable,'-c',script,str(self.path)],check=True)
        self.p.recover();self.assertIsNotNone(self.p.claim())
    def test_failed_transaction_does_not_half_commit(self):
        self.observe()
        with self.assertRaises(ValueError):self.observe(2,interpretation={'policy':'changed'})
        self.assertEqual(self.p.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],1)

    def test_outbox_consumption_idempotent_after_restart(self):
        self.observe();self.p.finish(self.p.claim(),result={'decision':'rejected'})
        self.assertEqual(len(self.p.unconsumed('pons')),1)
        self.p.consume('curve',1);self.p.consume('curve',1)
        self.p.close();self.p=Plane(self.path,clock=lambda:self.now)
        self.assertEqual(self.p.unconsumed('pons'),[])
        self.assertEqual(self.p.db.execute('SELECT COUNT(*) FROM result_consumption').fetchone()[0],1)

    def test_new_generation_cannot_consume_old_result(self):
        self.observe();self.p.finish(self.p.claim(),result={});self.observe(2)
        self.assertFalse(self.p.consume('curve',1))
        self.assertEqual(self.p.unconsumed('pons'),[])

    def test_lane_metrics_do_not_count_other_lane_events(self):
        self.observe()
        self.p.observe('pool','ramses','1',{},ordering=(1,),watermark={},interpretation={},observed=100,deadline=None,priority=3)
        self.assertEqual(self.p.snapshot('pons')['unique_candidates'],1)
        self.assertEqual(self.p.snapshot('pons')['observation_events'],1)

    def test_native_exit_survives_new_candidate_generation(self):
        from certification.robinhood.plane import project_native_position
        self.observe()
        kwargs=dict(ledger_path='native.sqlite',policy='frozen')
        position=dict(id='native',version=1,status='open')
        project_native_position(self.path,'pons','curve',position,**kwargs)
        project_native_position(self.path,'pons','curve',position,**kwargs)
        self.observe(2)
        project_native_position(self.path,'pons','curve',dict(position,version=2,status='settled'),**kwargs)
        value=self.p.checkpoint_read('native_position:pons:native')
        self.assertEqual(value['position']['status'],'settled')
        self.assertIsNone(value['priority'])
        self.assertEqual(self.p.get('curve')['generation'],2)
        self.assertEqual(self.p.get('curve')['pending'],1)
        self.assertEqual(self.p.snapshot()['transition_events']['entry_filled'],1)

    def test_native_position_projection_conflict_fails_closed(self):
        from certification.robinhood.plane import project_native_position
        self.observe();kwargs=dict(ledger_path='native.sqlite',policy='frozen')
        project_native_position(self.path,'pons','curve',dict(id='n',version=1,status='open'),**kwargs)
        with self.assertRaisesRegex(ValueError,'conflict'):
            project_native_position(self.path,'pons','curve',dict(id='n',version=1,status='settled'),**kwargs)

    def test_native_open_priority_restored_without_new_genesis(self):
        from certification.robinhood.plane import project_native_position
        self.observe()
        project_native_position(self.path,'pons','curve',dict(id='n',version=1,status='open'),ledger_path='native.sqlite',policy='frozen')
        self.p.close();self.p=Plane(self.path,clock=lambda:self.now)
        self.assertEqual(self.p.checkpoint_read('native_position:pons:n')['priority'],0)

    def test_completed_candidate_does_not_keep_lifetime_queue_age(self):
        self.observe();self.p.finish(self.p.claim(),result={})
        self.now=1000;self.observe(2)
        self.assertEqual(self.p.get('curve')['queued'],1000)

    def test_no_deadline_pool_ages_without_overtaking_safety(self):
        self.p.observe('pool','ramses','1',{},ordering=(1,),watermark={},interpretation={},observed=90,deadline=None,priority=3)
        self.observe(priority=2)
        self.assertEqual(self.p.claim()['id'],'pool')

if __name__=='__main__':unittest.main()
