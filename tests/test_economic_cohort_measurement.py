"""Diagnostic metadata: missing source/COMMIT/FULLACK never earns closure."""
from contextlib import closing
from copy import deepcopy
import json
import os
import re
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import based58

from meme_machine.runtime.economic_cohort import EconomicCohorts,checksum
from meme_machine.runtime.pump_economic_cohort import PumpEconomicCohorts
from meme_machine.solana_candidate_join import CandidateTransactionJoin,scope_labels
from meme_machine.solana_economic_preparation import prepare_candidate_frames
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_history_delivery import capture,deliver,acknowledge
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import commit_candidate_batch,commit_control
from meme_machine.yellowstone import geyser_pb2 as pb
from tests.test_solana_closure import NOW,state_at
from tests.test_solana_selective_evidence import FIXTURE



def joined_frames(addresses,*,with_economics=True):
    """Genuine original native status/log/metadata/finality parser join."""
    join=CandidateTransactionJoin(addresses,set(),clock=lambda:NOW,filtered_from_slot=100)
    label=scope_labels(addresses).get(program_scope('pump'));result=[]
    for slot in range(100,109):
        if with_economics:
            tx=deepcopy(FIXTURE['pump'][0]);rawsig=slot.to_bytes(64,'little');sig=based58.b58encode(rawsig).decode()
            join.feed_log(slot,sig,tx['meta']['logMessages'],None,NOW)
            status=pb.SubscribeUpdate(filters=[label]);status.transaction_status.slot=slot
            status.transaction_status.signature=rawsig;status.transaction_status.index=0
            self_result=join.feed(status,status.ByteSize(),NOW)
            assert self_result is None
        meta=pb.SubscribeUpdate(filters=['b']);block=meta.block_meta
        block.slot=slot;block.parent_slot=slot-1;block.blockhash=str(slot);block.parent_blockhash=str(slot-1)
        block.executed_transaction_count=int(with_economics);block.block_time.timestamp=int(NOW)
        assert join.feed(meta,meta.ByteSize(),NOW) is None
        final=pb.SubscribeUpdate(filters=['f']);final.slot.slot=slot;final.slot.parent=slot-1
        final.slot.status=pb.SLOT_FINALIZED
        frame=join.feed(final,final.ByteSize(),NOW);assert frame is not None
        result.append(frame)
    return result


class NativePumpEconomicCohortTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.state,self.history=state_at(self.root/'canonical.sqlite')
        self.addCleanup(self.state.writer.close)
        self.history.lifecycle.path=self.root/'consumer.sqlite';self.history.lifecycle.delivery_separated=True
        self.history.startup.begin()
        self.addresses={PROGRAMS[family]:program_scope(family) for family in ('pump','pumpswap')}
        self.frames=joined_frames(self.addresses)
        self.measurement=PumpEconomicCohorts('a'*32,'a'*64)
        self.measurement.session('b'*32,100,self.addresses)
        self.state.writer._economic_cohort_meter=self.measurement

    def commit(self,frames):
        products,_=prepare_candidate_frames(frames,self.addresses,'b'*32,'a'*64)
        self.measurement.prepared('b'*32,frames,products)
        for frame in frames:commit_control(self.state,frame)
        commit_candidate_batch(self.state,frames,self.addresses,'b'*32,publish=False,
            prepared=products,measurement=self.measurement)

    def test_original_join_decoder_canonical_and_full_ack_complete_actual_economic_window(self):
        self.commit(self.frames[:8]);self.commit(self.frames[8:])
        before=self.measurement.snapshot();self.assertIsNone(before['reason'])
        self.assertEqual(before['completed_cohorts'],0)
        self.assertGreater(before['active_identities'],0);self.assertGreater(before['active_fanout'],0)
        source_changes=self.state.writer.db.total_changes
        for _ in range(20):
            snapshot=capture(self.history.lifecycle)
            if snapshot is None:break
            result=deliver(snapshot)
            self.assertEqual(self.measurement.snapshot()['completed_cohorts'],0)
            self.assertTrue(acknowledge(self.history.lifecycle,snapshot,result))
            if self.measurement.snapshot()['completed_cohorts']:break
        after=self.measurement.snapshot();self.assertIsNone(after['reason'])
        self.assertEqual(after['completed_cohorts'],1)
        row=after['closed'][0];self.assertEqual((row['lower'],row['upper']),(100,107))
        self.assertGreater(row['unique_economics'],0);self.assertEqual(row['unique_economics'],row['new_canonical'])
        self.assertEqual(row['fanout_obligations'],row['verified_full_acks'])
        self.assertGreater(row['fanout_obligations'],0)
        self.assertGreater(self.state.writer.db.total_changes,source_changes)
        with closing(sqlite3.connect(self.history.lifecycle.path)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertGreater(db.execute('SELECT COUNT(*) FROM source_receipts').fetchone()[0],0)
        self.assertFalse(after['funding_authority']);self.assertFalse(after['historical_completion'])

    def test_outer_commit_failure_cannot_publish_canonical_or_cohort_progress(self):
        products,_=prepare_candidate_frames(self.frames[:1],self.addresses,'b'*32,'a'*64)
        self.measurement.prepared('b'*32,self.frames[:1],products)
        original=self.state.writer._transaction_statement;failed=[]
        def commit_failure(sql,stage):
            if stage=='commit' and not failed:
                failed.append(True);raise sqlite3.OperationalError('original_commit_failure')
            return original(sql,stage)
        with patch.object(self.state.writer,'_transaction_statement',side_effect=commit_failure):
            with self.assertRaisesRegex(sqlite3.OperationalError,'original_commit_failure'):
                commit_candidate_batch(self.state,self.frames[:1],self.addresses,'b'*32,publish=False,
                    prepared=products,measurement=self.measurement)
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        result=self.measurement.snapshot();self.assertEqual(result['state'],'UNKNOWN')
        self.assertEqual(result['completed_cohorts'],0)

    def test_opt_in_preserves_all_original_sql_and_economic_outbox_proof_bytes(self):
        baseline,history=state_at(self.root/'baseline.sqlite');self.addCleanup(baseline.writer.close)
        history.lifecycle.delivery_separated=True;history.startup.begin()
        products,_=prepare_candidate_frames(self.frames[:8],self.addresses,'b'*32,'a'*64)
        measured=[];original=[]
        baseline.writer.db.set_trace_callback(original.append)
        commit_candidate_batch(baseline,self.frames[:8],self.addresses,'b'*32,publish=False,prepared=products)
        baseline.writer.db.set_trace_callback(None)
        self.measurement.prepared('b'*32,self.frames[:8],products)
        self.state.writer.db.set_trace_callback(measured.append)
        commit_candidate_batch(self.state,self.frames[:8],self.addresses,'b'*32,publish=False,
            prepared=products,measurement=self.measurement)
        self.state.writer.db.set_trace_callback(None)
        normalize=lambda rows:[re.sub(r'nested_[0-9a-f]{32}','nested_SAVEPOINT',row) for row in rows]
        self.assertEqual(normalize(measured),normalize(original))
        tables=('rolling_economic_events','rolling_economic_addresses','candidate_content_receipts',
            'native_order_attestations','rolling_event_lineage','cursors','candidate_blocks',
            'candidate_pending_proofs','candidate_coverage','candidate_history_outbox','evidence_bindings')
        for table in tables:
            with self.subTest(table=table):
                actual=self.state.writer.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
                expected=baseline.writer.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
                self.assertEqual(actual,expected)

    def test_missing_acquisition_or_fanout_hooks_cannot_publish_a_complete_empty_census(self):
        from meme_machine.runtime.pump_economic_cohort import _Stage
        for boundary in ('arrivals','obligation','fanout_complete'):
            with self.subTest(boundary=boundary):
                root=self.root/boundary;root.mkdir()
                state,history=state_at(root/'source.sqlite')
                try:
                    history.lifecycle.delivery_separated=True;history.startup.begin()
                    measurement=PumpEconomicCohorts('a'*32,'a'*64);measurement.session('b'*32,100,self.addresses)
                    state.writer._economic_cohort_meter=measurement
                    target=measurement.meter if boundary=='arrivals' else _Stage
                    with patch.object(target,boundary,return_value=None):
                        for start in (0,8):
                            frames=self.frames[start:start+8]
                            prepared,_=prepare_candidate_frames(frames,self.addresses,'b'*32,'a'*64)
                            measurement.prepared('b'*32,frames,prepared)
                            commit_candidate_batch(state,frames,self.addresses,'b'*32,publish=False,
                                prepared=prepared,measurement=measurement)
                    result=measurement.snapshot()
                    self.assertEqual(result['state'],'UNKNOWN');self.assertEqual(result['completed_cohorts'],0)
                    self.assertGreater(state.writer.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
                finally:state.writer.close()

    def test_original_ack_refuses_forged_receipt_before_cohort_completion(self):
        self.commit(self.frames[:8]);self.commit(self.frames[8:])
        snapshot=capture(self.history.lifecycle);result=deliver(snapshot)
        identity=snapshot['rows'][0][0]
        with closing(sqlite3.connect(self.history.lifecycle.path)) as db:
            db.execute("UPDATE source_receipts SET body='{}' WHERE id=?",(identity,));db.commit()
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_delivery_receipt_missing_or_corrupt'):
            acknowledge(self.history.lifecycle,snapshot,result)
        self.assertEqual(self.measurement.snapshot()['completed_cohorts'],0)
        self.assertEqual(self.state.writer.db.execute('SELECT consumed FROM candidate_history_outbox WHERE id=?',(identity,)).fetchone(),(None,))

    def test_actual_joined_empty_interval_needs_explicit_zero_decoder_census(self):
        self.frames=joined_frames(self.addresses,with_economics=False)
        self.commit(self.frames[:8]);self.commit(self.frames[8:])
        result=self.measurement.snapshot();self.assertIsNone(result['reason'])
        self.assertEqual(result['completed_cohorts'],1)
        self.assertEqual(result['closed'][0]['unique_economics'],0)
        self.assertEqual(result['closed'][0]['verified_full_acks'],0)
        self.assertIn('UNKNOWN',result['full_market_rate'])

    def test_authenticated_control_header_clocks_expose_staleness_and_wall_jump_without_claiming_tip(self):
        control=joined_frames({},with_economics=False)
        with patch('meme_machine.runtime.pump_economic_cohort.time.time',return_value=NOW+1),patch(
                'meme_machine.runtime.pump_economic_cohort.time.monotonic',return_value=10):
            self.measurement.control_head(control[0])
            self.assertIsNone(self.measurement.snapshot()['observed_finalized_head'])
            self.measurement.control_head(control[1])
        with patch('meme_machine.runtime.pump_economic_cohort.time.time',return_value=NOW+15),patch(
                'meme_machine.runtime.pump_economic_cohort.time.monotonic',return_value=20):
            result=self.measurement.snapshot()
        head=result['observed_finalized_head']
        self.assertEqual(head['slot'],100);self.assertEqual(head['observation_age_seconds'],10)
        self.assertEqual(head['market_age_seconds'],15);self.assertEqual(head['wall_monotonic_delta_seconds'],4)
        self.assertIn('NOT_DURABLE_CONTROL_OR_UNSEEN_TIP',result['head_contract'])
        self.assertEqual(head['linked_child_slot'],101)
        self.assertIn('UNKNOWN',result['full_market_rate'])

    def test_fixed_projection_preserves_complete_digests_and_refuses_private_or_inconsistent_claims(self):
        from meme_machine.runtime.pump_economic_cohort import projection
        self.commit(self.frames[:8]);self.commit(self.frames[8:])
        for _ in range(20):
            pending=capture(self.history.lifecycle)
            if pending is None:break
            self.assertTrue(acknowledge(self.history.lifecycle,pending,deliver(pending)))
            if self.measurement.snapshot()['completed_cohorts']:break
        actual=self.measurement.snapshot();public=projection(actual)
        self.assertEqual(public,actual)
        actual['source_closed'][0]['lower']=999
        self.assertEqual(self.measurement.snapshot()['source_closed'][0]['lower'],100)
        source=self.measurement.snapshot();source['private_provider']='https://private.invalid/never-expose'
        self.assertNotIn('never-expose',json.dumps(projection(source)))
        for corrupt in ('authority','membership','oversized'):
            row=deepcopy(self.measurement.snapshot())
            if corrupt=='authority':row['funding_authority']=True
            elif corrupt=='membership':row['closed'][0]['verified_full_acks']+=1
            else:row['closed']*=17
            result=projection(row);self.assertEqual(result['state'],'UNKNOWN')
            self.assertFalse(result['funding_authority'])
        wide=deepcopy(self.measurement.snapshot())
        closed=wide['closed'][0];active=wide['active'][0];source=wide['source_closed'][0]
        wide['closed']=[dict(closed,cohort_sha256=checksum(['closed',i])) for i in range(16)]
        wide['active']=[dict(active,cohort_sha256=checksum(['active',i])) for i in range(8)]
        wide['source_closed']=[dict(source,cohort_sha256=checksum(['source',i])) for i in range(16)]
        wide['completed_cohorts']=16;wide['active_cohorts']=8
        wide['active_identities']=sum(r['unique_economics'] for r in wide['active'])
        projected=projection(wide)
        self.assertEqual(projected.get('completed_cohorts'),16)
        self.assertLessEqual(len(json.dumps(projected).encode()),24*1024)

    def test_existing_fixed_health_read_retains_cohort_schema_without_an_extra_query(self):
        from engineering.diagnostics.current_combined_observation_20261014 import pipeline_sample
        root=self.root/'collector';state,history=state_at(root/'shared'/'solana-evidence.sqlite')
        try:
            from meme_machine.solana_history_work import HistoricalTasks
            HistoricalTasks(history)
            with state.writer.transaction():
                state.fence._health('pid',os.getpid())
                state.fence._health('native_streams',dict(economic_cohorts=self.measurement.snapshot()))
            before=state.writer.db.total_changes
            queries=[];connect=sqlite3.connect
            def traced(*args,**kwargs):
                db=connect(*args,**kwargs);db.set_trace_callback(queries.append);return db
            with patch('engineering.diagnostics.current_combined_observation_20261014.sqlite3.connect',side_effect=traced):
                sample=pipeline_sample(root,os.getpid())
            self.assertTrue(sample['available'],sample);self.assertIn('economic_cohorts',sample)
            self.assertEqual(sample['economic_cohorts'],self.measurement.snapshot())
            self.assertEqual(state.writer.db.total_changes,before)
            with state.writer.transaction():state.fence._health('native_streams',{})
            measured=list(queries);queries.clear()
            with patch('engineering.diagnostics.current_combined_observation_20261014.sqlite3.connect',side_effect=traced):
                baseline=pipeline_sample(root,os.getpid())
            self.assertTrue(baseline['available'],baseline);self.assertNotIn('economic_cohorts',baseline)
            self.assertEqual(measured,queries)
            foreign=pipeline_sample(root,os.getpid()+1)
            self.assertFalse(foreign['available']);self.assertNotIn('economic_cohorts',foreign)
        finally:state.writer.close()

    def test_optional_observer_failure_cannot_replace_real_canonical_commit(self):
        from meme_machine.runtime.pump_economic_cohort import _Stage
        with patch.object(_Stage,'canonical',side_effect=RuntimeError('private-provider-URL-never-export')):
            self.commit(self.frames[:8])
        self.assertGreater(self.state.writer.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)
        result=self.measurement.snapshot();self.assertEqual(result['state'],'UNKNOWN')
        self.assertNotIn('private-provider',json.dumps(result))

    def test_reconnect_and_missing_blocktime_refuse_continuous_census_without_changing_source(self):
        self.measurement.session('c'*32,100,self.addresses)
        self.assertEqual(self.measurement.snapshot()['reason'],'GAP')
        other=PumpEconomicCohorts('a'*32,'a'*64);other.session('b'*32,100,self.addresses)
        frame=deepcopy(self.frames[0]);frame.update.block.ClearField('block_time')
        products,_=prepare_candidate_frames(self.frames[:1],self.addresses,'b'*32,'a'*64)
        other.prepared('b'*32,[frame],products)
        self.assertEqual(other.snapshot()['reason'],'SOURCE_CLOSURE_UNAVAILABLE')


class EconomicDiagnosticEnvironmentTests(unittest.TestCase):
    def test_exact_flag_only_preserves_original_worker_configuration_and_closed_funding(self):
        from meme_machine.operational.supervisor import Supervisor
        from meme_machine.runtime.operating_families import PausedFamily
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            service=Supervisor(Path(tmp),offline=False,admission='OBSERVATION');service.epoch='synthetic-epoch'
            baseline={lane:service.environment(lane) for lane in ('pump','pons','solana')}
            for value in ('1','01','true','0','1 '):
                os.environ['MM_ECONOMIC_COHORT_DIAGNOSTICS']=value
                for lane,original in baseline.items():
                    actual=service.environment(lane)
                    self.assertEqual(actual.pop('MM_ECONOMIC_COHORT_DIAGNOSTICS'),'1' if value=='1' else '0')
                    self.assertEqual(actual,{k:v for k,v in original.items() if k!='MM_ECONOMIC_COHORT_DIAGNOSTICS'})
                    self.assertEqual(actual['MM_MODE'],'PAPER')
                for family in ('meteora','ramses'):
                    with self.assertRaises(PausedFamily):service.environment(family)
            self.assertFalse(Path(tmp,'portfolio.sqlite').exists())
