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
    def test_cold_history_slice_with_independent_boundary_and_reorg_witness_advances(self):
        self.runtime.history.set_meta('discovery_block',99)
        self.runtime.history.set_meta('discovery_block_hash',block_header(99)['hash'])
        def responses(calls,scope):
            return [([] if method=='eth_getLogs' else block_header(int(params[0],16))) for method,params in calls]
        with patch(MODULE+'._latest_header',return_value=block_header(200)), patch.object(self.runtime.rpc,'batch',side_effect=responses):
            self.runtime.discover()
        self.assertEqual(self.runtime.history.get_meta('discovery_block'),139)
        self.assertEqual(self.runtime.history.get_meta('discovery_block_hash'),block_header(139)['hash'])

    def test_missing_log_result_still_fails_closed_without_advancing(self):
        self.runtime.history.set_meta('discovery_block',99)
        with patch(MODULE+'._latest_header',return_value=block_header(200)), patch.object(self.runtime.rpc,'batch',return_value=[[],[],[],block_header(139)]):
            with self.assertRaisesRegex(Exception,'survivor_graduation_range_incomplete'): self.runtime.discover()
        self.assertEqual(self.runtime.history.get_meta('discovery_block'),99)


class ProviderBandwidthAuditTests(unittest.TestCase):
    """Real frozen envelopes plus explicitly synthetic contradiction probes."""
    def records(self):
        from engineering.solana_capacity.offline_replay import frames
        return list(frames(Path(__file__).parent/'fixtures/pump_bandwidth/provider.frames.zlib'))

    def audit(self,records=None,**kwargs):
        from engineering.solana_capacity.bandwidth_audit import audit_records
        return audit_records(self.records() if records is None else records,**kwargs)

    def test_authentic_envelopes_keep_all_source_successes_and_failure_identities(self):
        import hashlib
        root=Path(__file__).parent/'fixtures/pump_bandwidth'
        manifest=json.loads((root/'manifest.json').read_text())
        self.assertEqual(hashlib.sha256((root/'provider.frames.zlib').read_bytes()).hexdigest(),manifest['subset_tape_sha256'])
        records=self.records()
        self.assertEqual([hashlib.sha256(raw).hexdigest() for _,raw in records],
                         [row['raw_sha256'] for row in manifest['records']])
        result=self.audit(records)
        self.assertEqual(result['decoded_complete_source_success_population'],{'pump:trade':1,'pumpswap:trade':1})
        for family in ('pump','pumpswap'):
            matches=result['log_native_identity_comparison'][family]
            self.assertEqual(matches['failed_with_matching_native_status'],1)
            self.assertEqual(matches['successful_with_matching_native_status'],1)
        self.assertEqual(result['actual_provider_savings_verified_bytes'],0)

    def test_failed_log_omission_is_a_hypothesis_and_native_negative_witness_stays(self):
        records=[(m,raw) for m,raw in self.records() if not (m['kind']=='delivery' and m['transport']=='websocket'
                 and 'params' in json.loads(raw) and json.loads(raw)['params']['result']['value']['err'] is not None)]
        result=self.audit(records)
        self.assertEqual(result['decoded_complete_source_success_population'],self.audit()['decoded_complete_source_success_population'])
        self.assertEqual(result['components']['pump:transaction_status']['failed_messages'],2)
        self.assertEqual(result['actual_provider_savings_verified_bytes'],0)

    def test_high_volume_failed_delivery_is_counted_even_when_duplicate_or_locally_unused(self):
        records=self.records()
        failed=next((m,raw) for m,raw in records if m['kind']=='delivery' and m['transport']=='websocket'
                    and 'params' in json.loads(raw) and json.loads(raw)['params']['result']['value']['err'] is not None)
        result=self.audit(records+[failed]*2000)
        self.assertEqual(result['captured_delivery']['source_delivered_bytes'],
                         self.audit()['captured_delivery']['source_delivered_bytes']+2000*len(failed[1]))
        self.assertEqual(result['actual_provider_savings_verified_bytes'],0)

    def test_late_status_is_matched_but_absent_native_witness_remains_incomplete(self):
        from meme_machine.yellowstone import geyser_pb2 as pb
        records=self.records()
        native=[(m,raw) for m,raw in records if m['kind']=='delivery' and m['transport']=='yellowstone'
                and pb.SubscribeUpdate.FromString(raw).WhichOneof('update_oneof')=='transaction_status']
        other=[r for r in records if r not in native]
        self.assertEqual(self.audit(other+native)['log_native_identity_comparison'],self.audit()['log_native_identity_comparison'])
        result=self.audit(other)
        for family in ('pump','pumpswap'):
            self.assertEqual(result['log_native_identity_comparison'][family]['failed_without_native_status'],1)
            self.assertEqual(result['log_native_identity_comparison'][family]['successful_without_native_status'],1)

    def test_success_misclassified_as_failure_and_conflicting_true_index_fail_closed(self):
        from meme_machine.yellowstone import geyser_pb2 as pb
        import struct
        records=self.records()
        for n,(meta,raw) in enumerate(records):
            if meta['kind']=='delivery' and meta['transport']=='yellowstone':
                u=pb.SubscribeUpdate.FromString(raw)
                if u.WhichOneof('update_oneof')=='transaction_status' and not u.transaction_status.HasField('err'):
                    u.transaction_status.err.err=struct.pack('<I',7)
                    changed=u.SerializeToString();m=dict(meta,bytes=len(changed))
                    with self.assertRaisesRegex(ValueError,'bandwidth_ws_native_status_contradiction'):
                        self.audit(records[:n]+[(m,changed)]+records[n+1:])
                    u=pb.SubscribeUpdate.FromString(raw);u.transaction_status.index+=1
                    changed=u.SerializeToString();m=dict(meta,bytes=len(changed))
                    with self.assertRaisesRegex(ValueError,'bandwidth_native_witness_contradiction'):
                        self.audit(records+[(m,changed)])
                    break
        else:self.fail('authentic successful native status required')

    def test_no_field_projection_or_failed_filter_is_invented_and_connections_are_not_opened(self):
        from engineering.solana_capacity.bandwidth_audit import capability_request
        from meme_machine.solana_selective_history import PROGRAMS
        from meme_machine.yellowstone import geyser_pb2 as pb
        request=capability_request(100)
        self.assertEqual(request.commitment,pb.FINALIZED)
        self.assertEqual(request.from_slot,100)
        self.assertEqual(len(request.transactions),1)
        content=request.transactions['t']
        self.assertTrue(content.HasField('failed'));self.assertFalse(content.failed)
        self.assertFalse(content.vote)
        self.assertEqual(list(content.account_include),[PROGRAMS['pumpswap']])
        for status in request.transactions_status.values():
            self.assertFalse(status.HasField('failed'));self.assertFalse(status.vote)
            self.assertFalse(status.account_exclude);self.assertFalse(status.account_required)
        self.assertEqual(len(request.transactions_status)+len(request.transactions)+len(request.blocks_meta)+len(request.slots),5)
        self.assertEqual(len(request.accounts_data_slice),0)
        for family,alternative in self.audit()['alternatives'].items():
            self.assertEqual(alternative['provider_savings'],'UNVERIFIED')
            self.assertEqual(alternative['missing_full_transaction_and_envelope_bytes'],'UNMEASURED')

    def test_observation_bounds_and_uncaptured_charged_tail_are_explicit(self):
        result=self.audit()
        source=result['captured_delivery']['source_delivered_bytes']
        self.assertEqual(self.audit(charged_bytes=source+915)['charged_but_uncaptured_bytes'],915)
        with self.assertRaisesRegex(ValueError,'bandwidth_charged_less_than_capture'):
            self.audit(charged_bytes=source-1)
        with patch('engineering.solana_capacity.bandwidth_audit.MAX_RECORDS',1):
            with self.assertRaisesRegex(ValueError,'bandwidth_capture_record_budget'):self.audit()
        with patch('engineering.solana_capacity.bandwidth_audit.MAX_SOURCE_BYTES',1):
            with self.assertRaisesRegex(ValueError,'bandwidth_capture_byte_budget'):self.audit()

    def test_older_scoped_position_subscription_still_counts_physical_delivery(self):
        records=[(dict(m,addresses=['historical-position-interest']*len(m['addresses'])) if m['kind']=='websocket_open' else m,raw)
                 for m,raw in self.records()]
        result=self.audit(records)
        self.assertEqual(result['captured_delivery']['websocket_bytes'],self.audit()['captured_delivery']['websocket_bytes'])
        self.assertGreater(result['components']['scoped_other_successful']['bytes'],0)
        self.assertEqual(result['decoded_complete_source_success_population'],self.audit()['decoded_complete_source_success_population'])

    def test_cost_model_uses_solana_specific_tariff_and_keeps_rpc_and_grpc_separate(self):
        from decimal import Decimal
        from engineering.solana_capacity.bandwidth_cost import cost
        # One decimal TB WS: 200 million CU, $105 at published PAYG rate.
        # Native is directly byte-priced; 20,000 HTTP transactions cost 800k CU.
        result=cost(10**12,10**12,{'getTransaction':20000})
        self.assertEqual(result['ws_usd'],Decimal(105))
        self.assertEqual(result['yellowstone_usd'],Decimal(75))
        self.assertEqual(result['rpc_usd'],Decimal('.42'))
        self.assertEqual(result['total_usage_usd'],Decimal('180.42'))
        self.assertEqual(result['http_request_elements'],20000)
        with self.assertRaisesRegex(ValueError,'negative_cost_workload'):cost(-1,0,{})
