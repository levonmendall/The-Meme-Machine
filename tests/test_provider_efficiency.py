"""Offline regressions for measured intake and repeated acquisition work."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meme_machine.solana_evidence_plane import EvidenceUnavailable
from tests.test_solana_closure import state_at, NOW
from tests.lanes.pons.test_pons_finalization import RuntimeCase, MODULE, block_header
from meme_machine.solana_source_intake import candidate_log_message


class LogIntakeTests(unittest.TestCase):
    def notification(self,err=None):
        return dict(jsonrpc='2.0',method='logsNotification',params=dict(subscription=7,
            result=dict(context=dict(slot=123),value=dict(signature='immutable-signature',err=err,
            logs=['Program X invoke [1]','Program data: AAAAAAAA','Program X success']))))

    def test_success_preserves_all_log_lines_indices_and_notification_fields(self):
        value=self.notification();raw=json.dumps(value).encode()
        self.assertEqual(candidate_log_message(raw,max_bytes=4096),value)
        self.assertEqual(candidate_log_message(raw.decode(),max_bytes=4096),value)

    def test_failed_attempt_retains_identity_and_error_without_python_logs(self):
        value=self.notification(dict(InstructionError=[0,dict(Custom=1)]));expected=json.loads(json.dumps(value))
        del expected['params']['result']['value']['logs']
        self.assertEqual(candidate_log_message(json.dumps(value),max_bytes=4096),expected)

    def test_complete_json_is_validated_even_for_unused_failed_logs(self):
        raw=json.dumps(self.notification(dict(InstructionError=[0,'Custom']))).replace('"Program X success"','INVALID')
        with self.assertRaises(EvidenceUnavailable):candidate_log_message(raw,max_bytes=4096)
        with self.assertRaises(EvidenceUnavailable):candidate_log_message(b'{}',max_bytes=1)

    def test_ack_and_rejection_are_preserved_and_ambiguous_routing_fails_closed(self):
        for value in (dict(jsonrpc='2.0',id=1,result=7),dict(jsonrpc='2.0',id=1,error=dict(code=-1))):
            self.assertEqual(candidate_log_message(json.dumps(value),max_bytes=4096),value)
        with self.assertRaises(EvidenceUnavailable):candidate_log_message('{"params":{},"params":{}}',max_bytes=4096)


class ProofTimingTests(unittest.TestCase):
    def test_corrupt_capture_bounds_and_truncated_stream_fail_closed(self):
        import struct,zlib
        from engineering.solana_capacity.offline_replay import frames
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'frames.zlib'
            for payload in (struct.pack('!II',65537,0),struct.pack('!II',0,16*1024*1024+1)):
                path.write_bytes(zlib.compress(payload))
                with self.assertRaisesRegex(ValueError,'capture_record_bound'):list(frames(path))
            path.write_bytes(zlib.compress(b'')[:-1])
            with self.assertRaisesRegex(ValueError,'capture_incomplete'):list(frames(path))

    def test_observer_projects_only_routing_metadata_and_preserves_raw_frame(self):
        from engineering.solana_capacity.transport_meter import TransportMeter,websocket_metadata
        from engineering.solana_capacity.offline_replay import frames
        value=LogIntakeTests().notification();raw=json.dumps(value).encode()
        self.assertEqual(websocket_metadata(raw),dict(message='logsNotification',slot=123,signature='immutable-signature'))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'frames.zlib';meter=TransportMeter(path)
            meter('delivery',dict(stream_id='one',family='candidate_logs',transport='websocket',raw=raw,seen=123));meter.close()
            rows=list(frames(path));self.assertEqual(rows[0][1],raw)
            self.assertEqual(rows[0][0]['signature'],'immutable-signature')

    def test_stopping_frame_is_charged_and_captured_without_suppressing_ceiling(self):
        from engineering.solana_capacity.pump_pons_proof import Budget,CeilingReached,observe_budgeted
        limits={key:1 for key in ('wall_seconds','solana_rpc_requests','robinhood_rpc_requests',
            'estimated_rpc_cu','native_delivery_bytes','estimated_native_delivery_cu','storage_bytes','native_errors','steady_seconds')}
        budget=Budget(limits,Path('/unused'));captured=[];value=dict(raw=b'physically_received')
        with self.assertRaises(CeilingReached):
            observe_budgeted(budget,lambda kind,v:captured.append((kind,v)), 'delivery',value)
        self.assertEqual(captured,[('delivery',value)])
        self.assertEqual(budget.native_bytes,len(value['raw']))
        self.assertTrue(budget.stop.is_set())

    def test_publication_timing_is_recorded_without_a_transport_identity(self):
        from engineering.solana_capacity.transport_meter import TransportMeter
        with tempfile.TemporaryDirectory() as tmp:
            meter=TransportMeter(Path(tmp)/'frames.zlib')
            meter('publication_timing',dict(work_ready_monotonic=1,publication_finished_monotonic=2))
            self.assertEqual(meter.evidence_timings[0]['kind'],'publication_timing');meter.close()

    def test_skipped_or_failed_work_cannot_count_as_qualified_evidence(self):
        from engineering.solana_capacity.pump_candidates import completed_observation
        for row in ({},{'full_hydration':False},{'full_hydration':True,'error':'provider_failure'}):
            self.assertNotIn('qualification_ready',completed_observation(row,123))
            self.assertEqual(row['disposition_finished'],123)
        self.assertEqual(completed_observation(dict(full_hydration=True,qualification=dict(qualified=False)),123)['qualification_ready'],123)

    def test_created_timestamp_age_is_separate_from_network_latency(self):
        from engineering.solana_capacity.transport_meter import TransportMeter
        from meme_machine.yellowstone import geyser_pb2 as pb
        with tempfile.TemporaryDirectory() as tmp:
            meter=TransportMeter(Path(tmp)/'frames.zlib')
            u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=3;u.created_at.seconds=100
            meter('delivery',dict(stream_id='one',transport='yellowstone',family='shared',raw=u.SerializeToString(),seen=137))
            self.assertEqual(meter.latencies['shared_created_at_age'],[37])
            self.assertNotIn('shared_delivery',meter.latencies);meter.close()


class RequestIdempotenceTests(unittest.TestCase):
    def test_unchanged_request_writes_nothing_and_never_renews_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, history = state_at(Path(tmp)/'canonical.sqlite')
            try:
                for n in range(10): history.request('pump',str(n),1,20,priority=3,deadline=NOW+150)
                before = state.writer.db.total_changes
                identity = history.request('pump','9',1,20,priority=4,deadline=NOW+300)
                self.assertEqual(state.writer.db.total_changes,before)
                self.assertEqual(state.writer.db.execute('SELECT priority,deadline FROM acquisition_jobs WHERE id=?',(identity,)).fetchone(),(3,NOW+150))
                history.request('pump','9',1,20,priority=1,deadline=NOW+100)
                self.assertEqual(state.writer.db.execute('SELECT priority,deadline FROM acquisition_jobs WHERE id=?',(identity,)).fetchone(),(1,NOW+100))
                history.plan()
                self.assertEqual(state.writer.db.execute('SELECT pages,status FROM acquisition_jobs WHERE id=?',(identity,)).fetchone(),(0,'pending'))
            finally: state.writer.close()


class SurvivorWitnessCountTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        from engineering.pons_history.fixtures import Tape
        self.tape=Tape(candidates=0);self.tape.top=self.tape.grad-1
        self.runtime.rpc=self.tape;self.runtime.now=lambda:int(self.tape.header(self.tape.top)['timestamp'],16)
        self.runtime.discover()

    def test_forward_slice_with_independent_boundary_and_reorg_witness_advances(self):
        previous=self.tape.top;self.tape.top+=100
        self.runtime.discover()
        self.assertEqual(self.runtime.history.get_meta('discovery_block'),previous+40)
        self.assertEqual(self.runtime.history.get_meta('discovery_block_hash'),self.tape.header(previous+40)['hash'])
        queries=[params[0] for method,params in self.tape.request_log if method=='eth_getLogs']
        self.assertTrue(all(int(q['toBlock'],16)-int(q['fromBlock'],16)<10 for q in queries))

    def test_missing_log_result_still_fails_closed_without_advancing(self):
        previous=self.tape.top;self.tape.top+=100
        original=self.tape.batch
        def incomplete(calls,**kwargs):
            if any(m=='eth_getLogs' for m,p in calls):return [[],[],[],self.tape.header(previous+40)]
            return original(calls,**kwargs)
        with patch.object(self.tape,'batch',side_effect=incomplete):
            with self.assertRaisesRegex(Exception,'historical_batch_incomplete'):self.runtime.discover()
        self.assertEqual(self.runtime.history.get_meta('discovery_block'),previous)
