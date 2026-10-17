"""Six fixed batch-write spans preserve native SQL, rollback and ownership."""
from contextlib import ExitStack
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.runtime import operation_costs as costs
from meme_machine.solana_economic_preparation import prepare_economic_record
from meme_machine.solana_evidence_control import PriorityOwner
from tests import test_rolling_ingest_serialization as fixtures
from tests.test_solana_closure import state_at


WRITE_NAMES=('owner.rolling_events_write','owner.rolling_addresses_write',
    'owner.rolling_receipts_write','owner.rolling_order_write',
    'owner.rolling_lineage_write','owner.rolling_cursors_write')


class RollingWriteCostsTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,MM_OPERATION_COST_DIAGNOSTICS='0'))
        for name,value in (('_rows',costs._new_rows()),('_active',{}),('_sequence',0),
                ('_recorder_valid',True),('_recording_lost_calls',0),('_active_overflow_calls',0)):
            self.stack.enter_context(patch.object(costs,name,value))
        self.fixture=fixtures.RollingBulkStoreTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.products=self.fixture.products()
        self.inputs=self.fixture.inputs(self.products)

    def bulk(self,history):
        with history.writer.transaction():
            self.assertTrue(history.rolling.store_many(self.inputs,self.products))

    def test_opt_in_preserves_full_sql_trace_final_bytes_and_original_durability(self):
        histories=[self.fixture.history(),self.fixture.history()];traces=[[],[]]
        for index,history in enumerate(histories):
            self.assertEqual(history.db.execute('PRAGMA synchronous').fetchone(),(2,))
            self.assertEqual(history.db.execute('PRAGMA journal_mode').fetchone(),('wal',))
            history.db.set_trace_callback(traces[index].append)
            with patch.dict(os.environ,MM_OPERATION_COST_DIAGNOSTICS=str(index)):
                self.bulk(history)
            history.db.set_trace_callback(None)
        self.assertEqual(traces[0],traces[1]) # SQL and parameters, not just verbs.
        self.assertEqual(self.fixture.snapshot(histories[0]),self.fixture.snapshot(histories[1]))
        self.assertEqual(traces[1][0],'BEGIN IMMEDIATE')
        self.assertEqual(traces[1][-1],'COMMIT')
        rows=costs.snapshot()['rows']
        for name in WRITE_NAMES:
            row=rows[name]
            self.assertEqual((row['calls'],row['failed_calls']),(1,0),name)
            self.assertEqual(row['sql']['statement_many']['calls'],1,name)
            self.assertEqual(row['sql']['transaction']['calls'],0,name)
            self.assertEqual(row['runnable_measured_calls'],0,name)
            self.assertEqual(row['runnable_unavailable_calls'],1,name)
        self.assertEqual(rows['owner.rolling_store']['child_calls'],6)
        self.assertEqual(rows['owner.rolling_store']['sql']['statement_many']['calls'],0)

    def test_opt_out_has_no_recorder_clocks_proc_reads_or_new_rows(self):
        history=self.fixture.history()
        with patch.object(costs,'_sample',side_effect=AssertionError('unexpected recorder')) as sampled:
            self.bulk(history)
        sampled.assert_not_called()
        self.assertEqual(costs.snapshot()['rows'],{})

    def test_write_failure_retains_exact_exception_atomic_rollback_and_executed_prefix_only(self):
        history=self.fixture.history();before=self.fixture.snapshot(history);db=history.db
        original=sqlite3.OperationalError('fixed_offline_receipt_write_failure')
        class FailedReceipt:
            def __getattr__(self,name):return getattr(db,name)
            def executemany(self,sql,parameters):
                if sql.startswith('INSERT OR IGNORE INTO candidate_content_receipts'):
                    db.executemany(sql,list(parameters)[:1])
                    raise original
                return db.executemany(sql,parameters)
        history.rolling.db=FailedReceipt()
        try:
            with patch.dict(os.environ,MM_OPERATION_COST_DIAGNOSTICS='1'):
                with self.assertRaises(sqlite3.OperationalError) as caught:self.bulk(history)
            self.assertIs(caught.exception,original)
        finally:history.rolling.db=db
        self.assertFalse(db.in_transaction)
        self.assertEqual(self.fixture.snapshot(history),before)
        rows=costs.snapshot()['rows']
        self.assertEqual(rows[WRITE_NAMES[2]]['failed_calls'],1)
        self.assertTrue(all(name in rows for name in WRITE_NAMES[:3]))
        self.assertTrue(all(name not in rows for name in WRITE_NAMES[3:]))
        self.assertIsNone(costs._current_operation());self.assertEqual(costs._active,{})
        self.bulk(history) # Unchanged input can still take the fresh path.

    def test_recorder_sampling_failure_cannot_mask_original_write_exception(self):
        history=self.fixture.history();original=RuntimeError('fixed_original_write_failure')
        db=history.db
        class FailedWrite:
            def __getattr__(self,name):return getattr(db,name)
            def executemany(self,*args):raise original
        history.rolling.db=FailedWrite()
        try:
            with patch.dict(os.environ,MM_OPERATION_COST_DIAGNOSTICS='1'),\
                    patch.object(costs,'_sample',side_effect=RuntimeError('fixed_clock_failure')):
                with self.assertRaises(RuntimeError) as caught:self.bulk(history)
            self.assertIs(caught.exception,original)
        finally:history.rolling.db=db
        self.assertFalse(db.in_transaction)
        self.assertEqual(history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone(),(0,))
        self.assertIsNone(costs._current_operation());self.assertEqual(costs._active,{})

    def test_concurrent_consumers_keep_all_six_writes_on_one_real_owner_without_extra_proc_probes(self):
        observed=[];jobs=[];errors=[];gate=threading.Barrier(3)
        batches=[tuple(prepare_economic_record(replace(product.record,
            identity=product.record.identity+':consumer-'+str(index))) for product in self.products)
            for index in range(2)]
        def factory():
            state,history=state_at(Path(self.fixture.tmp.name)/'owned.sqlite')
            db=history.rolling.db
            class Observed:
                def __getattr__(self,name):return getattr(db,name)
                def executemany(self,sql,parameters):
                    observed.append((threading.get_ident(),costs._current_operation()))
                    return db.executemany(sql,parameters)
            history.rolling.db=Observed()
            return SimpleNamespace(writer=state.writer,history=history,close=state.writer.close)
        owner=PriorityOwner(factory);owner.ready.result(3)
        try:
            def consumer(products):
                try:
                    gate.wait(3)
                    def store(state):
                        with state.writer.transaction():
                            return state.history.rolling.store_many(tuple(p.record for p in products),products)
                    jobs.append(owner.submit(store,priority=2))
                except BaseException as error:errors.append(error)
            with patch.dict(os.environ,MM_OPERATION_COST_DIAGNOSTICS='1'),\
                    patch.object(costs,'runnable_snapshot',return_value=None) as runnable:
                threads=[threading.Thread(target=consumer,args=(batch,)) for batch in batches]
                for thread in threads:thread.start()
                gate.wait(3)
                for thread in threads:thread.join(3)
                self.assertFalse(any(thread.is_alive() for thread in threads));self.assertFalse(errors)
                self.assertEqual(len(jobs),2)
                self.assertTrue(all(job.result(3) for job in jobs))
                self.assertEqual(runnable.call_count,4) # Only outer rolling_store start/end.
            self.assertEqual(len(observed),12)
            self.assertTrue(all(tid==owner.thread.ident for tid,_ in observed))
            self.assertEqual([name for _,name in observed],list(WRITE_NAMES)*2)
            rows=costs.snapshot()['rows']
            for name in WRITE_NAMES:
                self.assertEqual(rows[name]['calls'],2)
                self.assertEqual(rows[name]['sql']['statement_many']['calls'],2)
            self.assertNotIn('consumer-',json.dumps(costs.snapshot()))
        finally:owner.close()
        self.assertFalse(owner.thread.is_alive())


if __name__=='__main__':unittest.main()
