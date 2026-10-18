"""Real native Pons decoders and SQLite publication; synthetic wire only.

These cases never construct a financial book or claim qualification, complete
pool coverage, native source FULL/ACK, capacity or PAPER readiness.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime.pons_economic_cohort import PonsEconomicCohorts
from meme_machine.runtime.robinhood.plane import Plane
from meme_machine.lanes.pons.pons_history import PonsHistory
from meme_machine.lanes.pons.pons_current_history import CurrentHistory
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
from meme_machine.lanes.pons import pons_selective_v4 as v4
from meme_machine.lanes.pons.pons_selective_acquisition import _authenticate_window
from meme_machine.lanes.pons.pons_current_window import canonical_window
from meme_machine.lanes.pons.pons import curve_abi
from meme_machine.lanes.pons.abi import signature,topic
from tests.test_pons_dense_v4_receipts import fixture,ENDPOINT
from tests.lanes.pons.test_pons_finalization import graduation,WindowContext,block_header,address


class PonsEconomicCohortTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.index=0

    def survivor(self,*,enabled=True,relevant=3,fork=False):
        tape,context,options=fixture(relevant=relevant,total=max(3,relevant),dense=False,fork=fork)
        meter=PonsEconomicCohorts('synthetic-native-cohort',ENDPOINT) if enabled else None
        self.index+=1
        history=PonsHistory(self.root/('history-'+str(self.index)+'.sqlite'),policy=POLICY_HASH,
            economic_cohorts=meter)
        self.addCleanup(history.close)
        anchor=options['start_block']-1
        evidence=graduation(1,at=int(tape.header(anchor)['timestamp'],16),block=anchor)
        evidence.update(block_hash=tape.header(anchor)['hash'],key=asdict(options['key']))
        evidence['transition']['market']=options['pool_id']
        history.graduate(options['token'],evidence)
        history.append_block(options['token'],block=anchor,header=tape.header(anchor),events=[],
            points=[(evidence['at'],str(10**18))])
        runtime=Runtime.__new__(Runtime)
        runtime.history=history;runtime.endpoint=ENDPOINT;runtime.rpc=tape
        runtime.position_evidence_context=context;runtime.economic_cohorts=meter
        return runtime,tape,context,options,meter

    def decoded(self,runtime,tape,options):
        with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=tape),\
                patch('time.monotonic',return_value=100):
            return v4.collect_v4_activity(ENDPOINT,**options,economic_cohorts=runtime.economic_cohorts)

    def append(self,runtime,tape,options,activity):
        row=runtime.history.get(options['token'])
        runtime._append_tape(row,options['end_block'],tape.header(options['end_block']),activity)

    def test_actual_survivor_acquisition_decoder_and_history_commit_preserve_default(self):
        outputs=[];methods=[];sql=[]
        for enabled in (False,True):
            runtime,tape,context,options,meter=self.survivor(enabled=enabled)
            trace=[];runtime.history.db.set_trace_callback(trace.append)
            with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=tape),\
                    patch('time.monotonic',return_value=100),patch('time.time',return_value=2000000000):
                runtime._increment(runtime.history.get(options['token']),options['end_block'])
            runtime.history.db.set_trace_callback(None)
            outputs.append(runtime.history.facts(options['token'],int(tape.header(options['end_block'])['timestamp'],16)))
            methods.append(dict(tape.methods));sql.append(trace)
            if enabled:
                snapshot=meter.snapshot();active=snapshot['active'][0]
                self.assertEqual((active['unique_economics'],active['canonical_publications'],active['native_new']),(3,3,3))
                self.assertEqual(snapshot['native_history_transactions']['survivor_v4_history'],1)
                self.assertFalse(active['source_complete']);self.assertIsNone(snapshot['pending_full_ack'])
                self.assertEqual(snapshot['completed_cohorts'],0)
        self.assertEqual(outputs[0],outputs[1]);self.assertEqual(methods[0],methods[1]);self.assertEqual(sql[0],sql[1])

    def test_real_nested_history_commit_waits_for_outer_commit(self):
        runtime,tape,_,options,meter=self.survivor();activity=self.decoded(runtime,tape,options)
        with runtime.history.transaction():
            self.append(runtime,tape,options,activity)
            self.assertEqual(meter.snapshot()['active'][0]['canonical_publications'],0)
            self.assertEqual(meter.snapshot()['native_history_transactions']['survivor_v4_history'],0)
        self.assertEqual(meter.snapshot()['active'][0]['canonical_publications'],3)

    def test_outer_rollback_discards_economic_publication(self):
        runtime,tape,_,options,meter=self.survivor();activity=self.decoded(runtime,tape,options)
        with self.assertRaisesRegex(RuntimeError,'original-failure'):
            with runtime.history.transaction():
                self.append(runtime,tape,options,activity)
                raise RuntimeError('original-failure')
        self.assertEqual(runtime.history.db.execute('SELECT count(*) FROM events').fetchone()[0],0)
        self.assertEqual(meter.snapshot()['active'][0]['canonical_publications'],0)
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')

    def test_inner_rollback_does_not_publish_when_outer_continues(self):
        runtime,tape,_,options,meter=self.survivor();activity=self.decoded(runtime,tape,options)
        with runtime.history.transaction():
            try:
                with runtime.history.transaction():
                    self.append(runtime,tape,options,activity)
                    raise ValueError('native-inner-rollback')
            except ValueError:pass
            runtime.history.set_meta('native-after-rollback',True)
        self.assertTrue(runtime.history.get_meta('native-after-rollback'))
        self.assertEqual(runtime.history.db.execute('SELECT count(*) FROM events').fetchone()[0],0)
        self.assertEqual(meter.snapshot()['active'][0]['canonical_publications'],0)

    def test_original_commit_failure_keeps_original_error_and_no_publication(self):
        runtime,tape,_,options,meter=self.survivor();activity=self.decoded(runtime,tape,options)
        runtime.history.db.set_authorizer(lambda action,a,b,c,d:
            sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_TRANSACTION and a=='COMMIT' else sqlite3.SQLITE_OK)
        try:
            with self.assertRaises(sqlite3.DatabaseError):self.append(runtime,tape,options,activity)
        finally:runtime.history.db.set_authorizer(None)
        self.assertFalse(runtime.history.db.in_transaction)
        self.assertEqual(runtime.history.db.execute('SELECT count(*) FROM events').fetchone()[0],0)
        self.assertEqual(meter.snapshot()['active'][0]['canonical_publications'],0)

    def test_postcommit_observer_failure_cannot_rollback_or_retry_native_work(self):
        runtime,tape,_,options,meter=self.survivor();activity=self.decoded(runtime,tape,options)
        trace=[];runtime.history.db.set_trace_callback(trace.append)
        with patch.object(meter.meter,'committed',side_effect=RuntimeError('observer-fault')):
            self.append(runtime,tape,options,activity)
        runtime.history.db.set_trace_callback(None)
        self.assertEqual(runtime.history.db.execute('SELECT count(*) FROM events').fetchone()[0],3)
        self.assertEqual(trace[-1],'COMMIT');self.assertEqual(meter.snapshot()['state'],'UNKNOWN')

    def test_replayed_existing_native_rows_are_not_new_insertions(self):
        runtime,tape,_,options,meter=self.survivor();activity=self.decoded(runtime,tape,options)
        anchor=runtime.history.get(options['token']);self.append(runtime,tape,options,activity)
        replay=PonsEconomicCohorts('synthetic-restart',ENDPOINT)
        runtime.economic_cohorts=replay;runtime.history.economic_cohorts=replay
        activity=self.decoded(runtime,tape,options)
        runtime._append_tape(anchor,options['end_block'],tape.header(options['end_block']),activity)
        active=replay.snapshot()['active'][0]
        self.assertEqual((active['canonical_publications'],active['native_new'],active['native_replay']),(3,0,3))

    def test_bound_does_not_change_native_economic_work(self):
        runtime,tape,_,options,meter=self.survivor()
        with patch('meme_machine.runtime.pons_economic_cohort.MAX_STAGE_ROWS',2):
            activity=self.decoded(runtime,tape,options);self.append(runtime,tape,options,activity)
        self.assertEqual(runtime.history.db.execute('SELECT count(*) FROM events').fetchone()[0],3)
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')

    def test_foreign_outer_transaction_is_unmeasured_not_falsely_committed(self):
        runtime,tape,_,options,meter=self.survivor();activity=self.decoded(runtime,tape,options)
        runtime.history.db.execute('BEGIN')
        try:
            self.append(runtime,tape,options,activity)
            self.assertTrue(runtime.history.db.in_transaction)
            self.assertEqual(meter.snapshot()['active'][0]['canonical_publications'],0)
            self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
        finally:runtime.history.db.execute('ROLLBACK')

    def test_original_reorganization_refusal_does_not_create_arrival_or_publication(self):
        runtime,tape,_,options,meter=self.survivor(fork=True)
        with self.assertRaisesRegex(Exception,'canonical_header_membership'):self.decoded(runtime,tape,options)
        self.assertEqual(meter.snapshot()['active_cohorts'],0)
        self.assertEqual(runtime.history.db.execute('SELECT count(*) FROM events').fetchone()[0],0)

    def current(self):
        curve=address(21);block=170;tx='0x'+'aa'*32;header=block_header(block)
        spec=next(x for x in curve_abi() if x.get('type')=='event' and x['name']=='CurveBuy')
        values=dict(buyer=address(22),recipient=address(23),quoteIn=100,tokensOut=1000)
        topics=[topic(signature(spec))];words=[]
        for field in spec['inputs']:
            value=values.get(field['name'],0);value=int(value,16) if isinstance(value,str) else value
            word=f'{value:064x}'
            (topics if field['indexed'] else words).append('0x'+word if field['indexed'] else word)
        event=dict(address=curve,blockNumber=hex(block),blockHash=header['hash'],transactionHash=tx,
            transactionIndex='0x0',logIndex='0x0',topics=topics,data='0x'+''.join(words),removed=False)
        receipt=dict(transactionHash=tx,blockHash=header['hash'],transactionIndex='0x0',status='0x1',logs=[event])
        class Context(WindowContext):
            completed_sessions=[];rpc=None
            def batch(self,calls,scope):
                result=[]
                for method,params in calls:
                    if method=='eth_getBlockByHash':result.append(block_header(int(params[0],16)))
                    elif method=='eth_getTransactionReceipt':result.append(receipt)
                    else:result.extend(super().batch([(method,params)],scope))
                return result
        context=Context([event]);candidate=dict(curve=curve,block=200,
            stamp=type('Stamp',(),dict(event_at=200))(),header=block_header(200))
        raw=canonical_window(context,candidate)
        rows,_=_authenticate_window(ENDPOINT,candidate,raw,evidence_context=context)
        plane=Plane(self.root/'current.sqlite');self.addCleanup(plane.close)
        history=CurrentHistory(plane,ENDPOINT);meter=PonsEconomicCohorts('synthetic-current',ENDPOINT)
        stage=meter.current(curve,candidate['header'],raw,rows,context.window_coverage,201.)
        return history,meter,stage,curve,candidate['header'],rows

    def test_original_curve_window_receipt_decoder_then_native_history_commit(self):
        history,meter,stage,curve,header,rows=self.current()
        self.assertEqual(rows[0]['side'],'buy');self.assertEqual(rows[0]['quote'],100)
        history.remember(curve,header,rows,from_time=140,measurement_stage=stage)
        self.assertEqual(history.facts(curve,header,60),rows)
        active=meter.snapshot()['active'][0]
        self.assertEqual((active['unique_economics'],active['canonical_publications'],active['native_new']),(1,1,1))
        self.assertFalse(active['source_complete']);self.assertEqual(meter.snapshot()['completed_cohorts'],0)

    def test_current_commit_failure_does_not_publish(self):
        history,meter,stage,curve,header,rows=self.current()
        history.plane.db.set_authorizer(lambda action,a,b,c,d:
            sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_TRANSACTION and a=='COMMIT' else sqlite3.SQLITE_OK)
        try:
            with self.assertRaises(sqlite3.DatabaseError):history.remember(curve,header,rows,from_time=140,measurement_stage=stage)
        finally:history.plane.db.set_authorizer(None)
        self.assertIsNone(history.get(curve));self.assertEqual(meter.snapshot()['active'][0]['canonical_publications'],0)

    def test_current_different_native_semantics_cannot_earn_matching_publication(self):
        history,meter,stage,curve,header,rows=self.current()
        changed=[dict(rows[0],quote=101)]
        history.remember(curve,header,changed,from_time=140,measurement_stage=stage)
        self.assertEqual(history.facts(curve,header,60),changed)
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
        self.assertEqual(meter.snapshot()['active'][0]['canonical_publications'],0)

    def test_current_postcommit_observer_failure_preserves_native_return_and_rows(self):
        history,meter,stage,curve,header,rows=self.current();trace=[]
        history.plane.db.set_trace_callback(trace.append)
        with patch.object(stage,'committed',side_effect=RuntimeError('postcommit-observer-fault')):
            result=history.remember(curve,header,rows,from_time=140,measurement_stage=stage)
        history.plane.db.set_trace_callback(None)
        self.assertEqual(result['block'],200);self.assertEqual(trace[-1],'COMMIT')
        self.assertEqual(history.facts(curve,header,60),rows)
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
