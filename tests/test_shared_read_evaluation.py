"""One detached head for native sizing, never a financial writer cache."""
from contextlib import ExitStack,closing
from contextvars import copy_context
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.shared_capital import runtime
from meme_machine.shared_capital.model import CapitalError,digest
from meme_machine.runtime.directional_sleeve import open_sleeve
from meme_machine.runtime.usd_valuation import USDValue,ValuationUnavailable
from meme_machine.lanes.pons import pons_selective_cohort as cohort
from tests import test_pump_pons_capital_preparation as fixtures


def original_current():
    """Exact predecessor sizing workflow, with the same live native helpers."""
    sleeve=open_sleeve('pons',cohort.STRATEGY_CAPITAL_QUOTE)
    if sleeve is None:return cohort.STRATEGY_CAPITAL_QUOTE
    try:return max(0,sleeve.sizing_basis(500)['realized_equity'])
    finally:sleeve.close()


class SharedReadEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.RuntimeIntegrationTests();self.addCleanup(self.fixture.doCleanups)
        self.root,self.authority,self.now,self.plan=self.fixture.fixture(owners=False,new_epoch=True)
        self.portfolio=self.root/'portfolio.sqlite';self.shared=self.root/'shared-capital.sqlite'
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,
            MM_DIRECTIONAL_SLEEVE_DB=str(self.root/'pons/directional-sleeve.sqlite')))
        self.cached=runtime.connection(self.shared)
        self.addCleanup(self.close_pool)

    def close_pool(self):
        pool=getattr(runtime._LOCAL,'pool',{})
        for key,(_,value) in list(pool.items()):
            if Path(key).is_relative_to(self.root):
                value.close();del pool[key]

    def snapshot(self):
        return self.authority.ledger()

    def test_actual_current_result_and_original_usd_calls_match_with_one_warm_projection_read(self):
        before=self.snapshot();expected=original_current();shapes=[];opens=[];calls=[]
        original=sqlite3.connect
        def connect(path,*args,**kwargs):
            opens.append(str(path));db=original(path,*args,**kwargs)
            db.set_trace_callback(shapes.append)
            return db
        self.cached.db.set_trace_callback(shapes.append)
        value=USDValue('offline-native',3,Decimal('1'),self.now-1,self.now+100000,'offline-usd','e'*64)
        def reader(at):calls.append(at);return value
        with patch('sqlite3.connect',connect),\
                patch('meme_machine.runtime.usd_valuation.native_reader',return_value=reader),\
                patch.object(self.cached,'_read',wraps=self.cached._read) as read,\
                patch.object(self.cached,'_reconcile',wraps=self.cached._reconcile) as reconcile:
            actual=cohort._current_pons_realized_equity()
        self.cached.db.set_trace_callback(None)
        self.assertEqual(actual,expected);self.assertEqual(len(calls),2)
        self.assertEqual(read.call_count,1);self.assertEqual(reconcile.call_count,1)
        self.assertEqual(shapes.count('SELECT body,hash FROM shared_capital_projection WHERE id=1'),1)
        self.assertEqual(shapes.count('SELECT state_hash FROM shared_capital_events ORDER BY sequence DESC LIMIT 1'),1)
        self.assertEqual(shapes.count('SELECT body FROM portfolio_funding_authority WHERE id=1'),1)
        self.assertFalse(any(str(self.shared) in path for path in opens))
        self.assertEqual(self.snapshot(),before)
        self.assertTrue(self.authority.verify_replay()['conservation'])

    def test_cold_evaluation_retains_original_authenticated_constructor_and_full_replay(self):
        expected=original_current();before=self.snapshot();self.close_pool()
        replay=runtime.RuntimeCapital.verify_replay
        with patch.object(runtime.RuntimeCapital,'verify_replay',autospec=True,side_effect=replay) as verified:
            self.assertEqual(cohort._current_pons_realized_equity(),expected)
        self.assertEqual(verified.call_count,1)
        self.cached=runtime.connection(self.shared)
        self.assertEqual(self.snapshot(),before)
        self.assertTrue(self.cached.verify_replay()['conservation'])

    def test_view_is_detached_caller_mutation_cannot_change_it_and_shared_writes_are_refused(self):
        before=self.snapshot();sequence=self.authority.db.execute('SELECT MAX(sequence) FROM shared_capital_events').fetchone()
        with runtime._native_read_evaluation(self.portfolio):
            retained_context=copy_context()
            self.assertFalse(self.cached.db.in_transaction)
            first=self.cached.ledger();first['cash']='0'
            self.assertEqual(self.cached.ledger(),before)
            self.assertEqual(runtime.selected(self.portfolio),self.shared)
            with self.assertRaisesRegex(CapitalError,'authority_changed'):self.authority.ledger()
            with self.assertRaisesRegex(CapitalError,'is_readonly'):
                self.authority.command('offline-forbidden-write','runtime_publish',{},self.now)
            with patch('meme_machine.operational.admission.available',side_effect=AssertionError('live admission touched')),\
                    patch('meme_machine.operational.admission.require_normal',side_effect=AssertionError('startup admission touched')):
                for action,data in (('runtime_allocate',{}),('runtime_admission',dict(mode='NORMAL'))):
                    with self.assertRaisesRegex(CapitalError,'is_readonly'):
                        self.authority.command('offline-forbidden-precheck',action,data,self.now)
            with self.assertRaisesRegex(CapitalError,'is_readonly'):
                self.authority.require_obligation(operation_id='offline-forbidden-obligation',
                    obligation_id='offline-forbidden-obligation',regime_name='pons_current',
                    amount_usd='1',at=self.now,proof_sha256='a'*64)
            with self.assertRaisesRegex(CapitalError,'nested'):
                with runtime._native_read_evaluation(self.portfolio):pass
            with self.assertRaisesRegex(CapitalError,'authority_changed'):
                runtime.selected(self.root/'foreign-portfolio.sqlite')
        self.assertEqual(self.authority.db.execute('SELECT MAX(sequence) FROM shared_capital_events').fetchone(),sequence)
        self.assertEqual(self.snapshot(),before);self.assertIsNone(runtime._read_evaluation())
        with self.assertRaisesRegex(CapitalError,'owner_or_inode_changed'):
            retained_context.run(self.cached.ledger)
        self.authority.command('offline-after-evaluation','runtime_publish',{},self.now)
        self.assertGreater(self.authority.db.execute('SELECT MAX(sequence) FROM shared_capital_events').fetchone(),sequence)
        self.assertTrue(self.authority.verify_replay()['conservation'])

    def test_concurrent_native_writer_advances_during_usd_without_pinning_wal_and_next_call_is_fresh(self):
        entered=threading.Event();release=threading.Event();result=[];errors=[];views=[]
        initial=self.snapshot();calls=[]
        value=USDValue('offline-native',3,Decimal('1'),self.now-1,self.now+100000,'offline-usd','e'*64)
        def reader(at):
            calls.append(at)
            if len(calls)==1:
                owner=runtime.connection(self.shared)
                views.append(owner.ledger());self.assertFalse(owner.db.in_transaction)
                entered.set()
                if not release.wait(5):raise RuntimeError('offline USD release missing')
                views.append(owner.ledger())
            return value
        def sizing():
            try:result.append(cohort._current_pons_realized_equity())
            except BaseException as error:errors.append(error)
            finally:
                try:self.close_pool()
                except BaseException as error:errors.append(error)
        with patch('meme_machine.runtime.usd_valuation.native_reader',return_value=reader):
            thread=threading.Thread(target=sizing);thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.authority.require_obligation(operation_id='offline-required',obligation_id='offline-required',
                    regime_name='pons_current',amount_usd='1',at=self.now,proof_sha256='a'*64)
                self.authority.discharge_obligation(operation_id='offline-paid',obligation_id='offline-required',
                    paid='1',at=self.now,proof_sha256='b'*64)
                self.authority.db.execute('PRAGMA busy_timeout=0')
                self.assertEqual(self.authority.db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone(),(0,0,0))
            finally:release.set();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertFalse(errors)
        self.assertEqual(views,[initial,initial]);self.assertEqual(len(calls),2)
        self.assertEqual(result,[1000000])
        self.assertEqual(cohort._current_pons_realized_equity(),999000)
        self.assertEqual(self.snapshot()['cash'],'999.00')
        self.close_pool();self.cached=runtime.connection(self.shared)
        self.assertEqual(cohort._current_pons_realized_equity(),999000)
        self.assertTrue(self.authority.verify_replay()['conservation'])

    def test_copied_context_refuses_foreign_thread_and_replaced_inode(self):
        errors=[]
        with runtime._native_read_evaluation(self.portfolio):
            context=copy_context()
            def foreign():
                try:context.run(self.cached.ledger)
                except BaseException as error:errors.append(error)
            thread=threading.Thread(target=foreign);thread.start();thread.join(3)
            self.assertEqual(len(errors),1)
            self.assertIsInstance(errors[0],CapitalError)
            self.assertIn('owner_or_inode_changed',str(errors[0]))
            old=self.portfolio.with_suffix('.retained')
            self.portfolio.rename(old)
            try:
                self.portfolio.write_bytes(b'new untrusted inode')
                with self.assertRaisesRegex(CapitalError,'owner_or_inode_changed'):self.cached.ledger()
            finally:self.portfolio.unlink();old.rename(self.portfolio)
        self.assertIsNone(runtime._read_evaluation())

    def test_original_selection_and_projection_negatives_stay_exact_and_cold_auth_precedes_constructor(self):
        with closing(sqlite3.connect(self.portfolio)) as db:
            raw=db.execute('SELECT body FROM portfolio_funding_authority WHERE id=1').fetchone()[0]
        for key,value in (('epoch_id','foreign-epoch'),('inception_sha256','0'*64),('policy_sha256','0'*64),('state','INCOMPLETE')):
            with self.subTest(key=key):
                changed=dict(json.loads(raw),**{key:value})
                with closing(sqlite3.connect(self.portfolio)) as db:
                    db.execute('UPDATE portfolio_funding_authority SET body=? WHERE id=1',(json.dumps(changed),));db.commit()
                try:
                    with self.assertRaises(CapitalError) as old:original_current()
                    with self.assertRaises(CapitalError) as new:cohort._current_pons_realized_equity()
                    self.assertEqual(str(new.exception),str(old.exception))
                    self.close_pool()
                    with patch.object(runtime,'RuntimeCapital',side_effect=AssertionError('unauthenticated constructor')):
                        with self.assertRaises(CapitalError) as cold:cohort._current_pons_realized_equity()
                    self.assertEqual(str(cold.exception),str(old.exception))
                finally:
                    with closing(sqlite3.connect(self.portfolio)) as db:
                        db.execute('UPDATE portfolio_funding_authority SET body=? WHERE id=1',(raw,));db.commit()
                self.cached=runtime.connection(self.shared)
        projection=self.cached.db.execute('SELECT body,hash FROM shared_capital_projection WHERE id=1').fetchone()
        for invalid in ('checksum','missing','head'):
            with self.subTest(invalid=invalid):
                if invalid=='missing':self.cached.db.execute('DELETE FROM shared_capital_projection WHERE id=1')
                elif invalid=='checksum':self.cached.db.execute('UPDATE shared_capital_projection SET hash=? WHERE id=1',('0'*64,))
                else:
                    changed=dict(json.loads(projection[0]),at=self.now+1)
                    self.cached.db.execute('UPDATE shared_capital_projection SET body=?,hash=? WHERE id=1',(json.dumps(changed),digest(changed)))
                try:
                    with self.assertRaises(CapitalError) as old:original_current()
                    with self.assertRaises(CapitalError) as new:cohort._current_pons_realized_equity()
                    self.assertEqual(str(new.exception),str(old.exception))
                finally:self.cached.db.execute('INSERT OR REPLACE INTO shared_capital_projection VALUES(1,?,?)',projection)
        self.assertTrue(self.authority.verify_replay()['conservation'])

    def test_native_usd_missing_stale_and_second_read_failure_keep_original_refusals(self):
        for mode in ('missing','stale','second'):
            failures=[];counts=[]
            for call in (original_current,cohort._current_pons_realized_equity):
                reads=[]
                def reader(at):
                    reads.append(at)
                    if mode=='missing' or mode=='second' and len(reads)==2:
                        raise ValuationUnavailable('offline-native-unavailable')
                    return USDValue('offline-native',3,Decimal('1'),self.now-10,
                        self.now-1 if mode=='stale' else self.now+100000,'offline-usd','e'*64)
                with patch('meme_machine.runtime.usd_valuation.native_reader',return_value=reader):
                    with self.assertRaises(ValuationUnavailable) as error:call()
                failures.append((type(error.exception),str(error.exception)));counts.append(len(reads))
                self.assertIsNone(runtime._read_evaluation())
            self.assertEqual(failures[0],failures[1]);self.assertEqual(counts[0],counts[1])

    def test_original_missing_native_configuration_and_standalone_fallback_precede_shared_reads(self):
        for values in (dict(MM_DIRECTIONAL_SLEEVE_DB='',MM_DIRECTIONAL_COMPOSITE_REQUIRED='0'),
                dict(MM_DIRECTIONAL_SLEEVE_DB='',MM_DIRECTIONAL_COMPOSITE_REQUIRED='1'),
                dict(MM_DIRECTIONAL_COHORT_ID='')):
            with self.subTest(values=values),patch.dict(os.environ,values),\
                    patch.object(runtime,'_selection_record',side_effect=AssertionError('premature shared read')):
                outcomes=[]
                for call in (original_current,cohort._current_pons_realized_equity):
                    try:outcomes.append(('value',call()))
                    except ValueError as error:outcomes.append((type(error),str(error)))
                self.assertEqual(outcomes[0],outcomes[1])

    def test_same_fixture_warm_comparison_reduces_projection_reads_without_economic_changes(self):
        # Paired on one bounded genuine fixture; no repeat of the 15,857-event
        # broad probe and no attribution to AWS's unexplained146GB population.
        original_current();cohort._current_pons_realized_equity();before=self.snapshot()
        connect=sqlite3.connect;active=[];results=[]
        def observed(path,*args,**kwargs):
            db=connect(path,*args,**kwargs);db.set_trace_callback(active.append)
            return db
        self.cached.db.set_trace_callback(active.append)
        try:
            with patch('sqlite3.connect',observed):
                for name,call in (('original',original_current),('one_evaluation',cohort._current_pons_realized_equity)):
                    active.clear();values=[];wall=time.monotonic();cpu=time.thread_time()
                    for _ in range(8):values.append(call())
                    results.append(dict(path=name,calls=8,wall_seconds=time.monotonic()-wall,
                        cpu_seconds=time.thread_time()-cpu,
                        projection_reads=active.count('SELECT body,hash FROM shared_capital_projection WHERE id=1'),
                        journal_head_reads=active.count('SELECT state_hash FROM shared_capital_events ORDER BY sequence DESC LIMIT 1')))
                    self.assertEqual(values,[1000000]*8)
        finally:self.cached.db.set_trace_callback(None)
        self.assertEqual(results[0]['projection_reads'],72)
        self.assertEqual(results[0]['journal_head_reads'],40)
        self.assertEqual(results[1]['projection_reads'],8)
        self.assertEqual(results[1]['journal_head_reads'],8)
        self.assertEqual(self.snapshot(),before)
        print(json.dumps(dict(schema='paired-native-sizing-read-fixture-v1',
            scope='SAME_BOUNDED_SYNTHETIC_FIXTURE_NOT_AWS_IO_OR_MARKET_CAPACITY',
            projection_bytes=self.authority.db.execute('SELECT length(body) FROM shared_capital_projection WHERE id=1').fetchone()[0],
            measurements=results,financial_projection_unchanged=True,provider_requests=0),sort_keys=True))


if __name__=='__main__':unittest.main()
