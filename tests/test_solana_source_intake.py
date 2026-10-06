"""Offline source selection, process-boundary and canonical-equivalence proofs."""
import asyncio
import concurrent.futures
import copy
import gzip
import json
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import patch

from meme_machine import solana_evidence_service as service
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_source_intake import SelectedFrame,select_frame


def frame(txs,slot=300):
    return dict(method='blockNotification',params=dict(subscription=1,result=dict(value=dict(
        slot=slot,err=None,block=dict(parentSlot=slot-1,blockhash='h'+str(slot),
            previousBlockhash='h'+str(slot-1),blockTime=1790438999,transactions=txs)))))


def encode(value):return json.dumps(value,separators=(',',':')).encode()


def unrelated(marker='UNRELATED_PRIVATE_TO_INTAKE'):
    return dict(transaction=dict(signatures=['unrelated'],message=dict(
        accountKeys=['unrelated'],instructions=[dict(data=marker)])),
        meta=dict(err=None,logMessages=[marker],innerInstructions=[dict(data=marker)],
                  preTokenBalances=[dict(debug=marker)],postTokenBalances=[dict(debug=marker)]))


class SourceIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).parent/'fixtures/solana_evidence_plane/run380-production-templates.json.gz'
        cls.templates=json.loads(gzip.decompress(path.read_bytes()))['templates']
        cls.subs=[s for s in service.program_subscriptions() if s.evidence_class!='logs']
        cls.targets=tuple(sorted({s.address for s in cls.subs}))
        cls.transaction_targets=tuple(sorted(
            {s.address for s in cls.subs if s.evidence_class=='transactions'}))

    def select(self,value,*,bound=service.STREAM_MAX_MESSAGE_BYTES):
        # Match production source routing: Pump/PumpSwap keep only canonical
        # log/census fields; only Meteora receives the economic transaction vector.
        return select_frame(encode(value),'',self.targets,max_bytes=bound,
                            full_transaction_addresses=self.transaction_targets)

    def parity(self,value):
        selected=self.select(value)
        prepared,total,retained=service.prepare_selected_source(selected,'a'*64,2000000000.)
        self.assertEqual(total,len(value['params']['result']['value']['block']['transactions']))
        self.assertEqual(retained,len(selected.normalized_keys))
        for sub in self.subs:
            # Pump/PumpSwap remain byte-equivalent to the original broad source.
            # Meteora intentionally consumes the narrow economic projection, so
            # compare the canonical decoder against that projected source instead.
            expected_source=(
                selected.message if sub.evidence_class=='transactions' else value)
            expected=service.prepare_block_scope(sub,expected_source,2000000000.,'a'*64,
                service.program_decoders(),include_logs=True,budget=[16*1024*1024])
            self.assertEqual(prepared.scopes[sub.scope],expected)
        transferred=pickle.loads(pickle.dumps(selected))
        repeated,_,_=service.prepare_selected_source(transferred,'a'*64,2000000000.)
        self.assertEqual(repeated.scopes,prepared.scopes)
        return selected,prepared

    def test_each_program_and_multiple_transactions_preserve_canonical_records(self):
        for family,templates in self.templates.items():
            with self.subTest(family=family):
                txs=[unrelated()]+copy.deepcopy(templates[:4])+[unrelated()]
                selected,_=self.parity(frame(txs))
                self.assertEqual(selected.retained_transactions,4)

    def test_mixed_scopes_order_and_cross_program_transaction(self):
        txs=[copy.deepcopy(self.templates[k][0]) for k in ('pump','meteora','pumpswap')]
        cross=copy.deepcopy(txs[2]);cross['transaction']['signatures']=['cross']
        cross['transaction']['message']['accountKeys']+=list(self.targets)
        selected,_=self.parity(frame(txs+[unrelated(),cross]))
        self.assertEqual(selected.retained_transactions,4)
        bodies=selected.message['params']['result']['value']['block']['transactions']
        self.assertEqual([b['transaction']['signatures'][0] for b in bodies],
                         [t['transaction']['signatures'][0] for t in txs]+['cross'])
        self.assertTrue(all(3 in selected.members[address] for address in self.targets))

    def test_log_and_economic_projection_keep_required_records_without_full_bodies(self):
        txs=[copy.deepcopy(self.templates[k][0]) for k in ('pump','pumpswap','meteora')]
        cross=copy.deepcopy(txs[2]);cross['transaction']['signatures']=['cross']
        cross['transaction']['message']['accountKeys']+=list(self.targets)
        value=frame(txs+[unrelated(),cross])
        full_targets=tuple(s.address for s in self.subs if s.evidence_class=='transactions')
        selected=select_frame(encode(value),'',self.targets,max_bytes=service.STREAM_MAX_MESSAGE_BYTES,
                              full_transaction_addresses=full_targets)
        prepared,_,_=service.prepare_selected_source(selected,'a'*64,2000000000.)
        for sub in self.subs:
            expected_source=(
                selected.message if sub.evidence_class=='transactions' else value)
            expected=service.prepare_block_scope(sub,expected_source,2000000000.,'a'*64,
                service.program_decoders(),include_logs=True,budget=[16*1024*1024])
            self.assertEqual(prepared.scopes[sub.scope],expected)
        bodies=selected.message['params']['result']['value']['block']['transactions']
        self.assertEqual(set(bodies[0]['meta']),{'err','logMessages'})
        originals={
            tx['transaction']['signatures'][0]:tx
            for tx in txs+[cross]
        }
        for body in bodies[2:]:
            self.assertEqual(set(body['transaction']['message']),{'accountKeys','instructions'})
            self.assertEqual(set(body['meta']),
                {'err','logMessages','innerInstructions','preTokenBalances','postTokenBalances'})
            self.assertNotIn('preBalances',body['meta'])
            self.assertNotIn('postBalances',body['meta'])
            original=originals[body['transaction']['signatures'][0]]
            if original.get('transactionIndex') is not None:
                self.assertEqual(body.get('transactionIndex'),original['transactionIndex'])
        self.assertEqual(
            (selected.full_body_transactions,selected.log_projection_transactions,
             selected.economic_projection_transactions),(0,2,2))
        self.assertEqual(service.prepare_selected_source(pickle.loads(pickle.dumps(selected)),'a'*64,2000000000.)[0].scopes,prepared.scopes)

    def test_loaded_addresses_and_account_objects_are_not_omitted(self):
        for side in ('readonly','writable'):
            tx=copy.deepcopy(self.templates['pump'][0])
            keys=tx['transaction']['message']['accountKeys'];tx['transaction']['message']['accountKeys']=[]
            tx['meta']['loadedAddresses']={side:keys}
            self.assertEqual(self.parity(frame([unrelated(),tx]))[0].retained_transactions,1)
        tx=copy.deepcopy(self.templates['pump'][0])
        tx['transaction']['message']['accountKeys']=[dict(pubkey=k,writable=True) for k in tx['transaction']['message']['accountKeys']]
        self.assertEqual(self.parity(frame([tx]))[0].retained_transactions,1)

    def test_unrelated_bodies_never_get_canonical_work_or_ipc(self):
        marker='UNRELATED_PRIVATE_TO_INTAKE'*1000
        with patch.object(service,'digest',side_effect=AssertionError('unrelated hash')),patch(
            'meme_machine.solana_evidence_plane.prepare_record',side_effect=AssertionError('unrelated storage')),patch(
            'meme_machine.solana_program_decoders.pump_events',side_effect=AssertionError('unrelated decode')),patch(
            'meme_machine.solana_evidence_storage.zlib.compress',side_effect=AssertionError('unrelated compression')):
            selected=self.select(frame([unrelated(marker)]))
            prepared,total,retained=service.prepare_selected_source(selected,'a'*64,2000000000.)
        self.assertEqual((total,retained),(1,0))
        self.assertNotIn(marker.encode(),pickle.dumps(selected))
        self.assertNotIn(marker.encode(),pickle.dumps(prepared))
        self.assertTrue(all(not v['batches'] and not v['deliveries'] for v in prepared.scopes.values()))
        self.assertEqual(selected.counters()['materialized_transactions'],0)

    def test_header_projection_never_visits_excluded_transaction_subtree(self):
        from meme_machine.solana_source_intake import _except
        class NativeRoute:
            # Match the binding's eager items/values API. The excluded subtree
            # is inaccessible to the projection even though its name is known.
            def keys(self):return ('parentSlot','transactions')
            def __getitem__(self,key):
                if key=='transactions':raise AssertionError('unrelated bodies materialized')
                return 300
            def items(self):raise AssertionError('eager native items traversal')
            def values(self):raise AssertionError('eager native values traversal')
        self.assertEqual(_except(NativeRoute(),'transactions'),{'parentSlot':300})

    def test_failed_relevant_transactions_remain_in_census(self):
        tx=copy.deepcopy(self.templates['pump'][0]);tx['meta']['err']={'InstructionError':[0,'Custom']}
        selected,_=self.parity(frame([tx,unrelated()]))
        self.assertEqual(selected.retained_transactions,1)
        self.assertEqual(selected.message['params']['result']['value']['block']['transactions'][0]['meta']['err'],tx['meta']['err'])

    def test_duplicate_delivery_is_not_reinterpreted_by_selection(self):
        tx=copy.deepcopy(self.templates['pump'][0]);value=frame([tx,copy.deepcopy(tx)])
        selected,_=self.parity(value)
        self.assertEqual(selected.retained_transactions,2)

    def test_empty_block_preserves_native_continuity_not_inferred_coverage(self):
        value=frame([],slot=305);value['params']['result']['value']['block']['parentSlot']=300
        value['params']['result']['value']['block']['previousBlockhash']='h300'
        selected,prepared=self.parity(value)
        self.assertEqual(selected.message,value)
        self.assertTrue(all(not scope['signatures'] for scope in prepared.scopes.values()))
        self.assertNotIn('complete',selected.message)

    def test_truncated_relevant_logs_still_fail_closed(self):
        tx=copy.deepcopy(self.templates['pump'][0]);tx['meta']['logMessages']=['Log truncated']
        selected=self.select(frame([tx]))
        with self.assertRaises(EvidenceUnavailable):
            service.prepare_selected_source(selected,'a'*64,2000000000.)

    def test_damaged_json_and_partial_transaction_are_not_empty_intervals(self):
        for raw in (b'{"method":"blockNotification",',b'[]',b'{"method":"blockNotification","params":{}}'):
            with self.subTest(raw=raw),self.assertRaises(EvidenceUnavailable):
                select_frame(raw,'',self.targets,max_bytes=1024)
        value=frame([dict(transaction=dict(message=dict(accountKeys=[])))])
        with self.assertRaises(EvidenceUnavailable):self.select(value)

    def test_duplicate_membership_fields_cannot_hide_target(self):
        value=frame([unrelated()]);raw=encode(value)
        replacement=b'"accountKeys":["unrelated"],"accountKeys":'+encode([self.targets[0]])
        raw=raw.replace(b'"accountKeys":["unrelated"]',replacement)
        with self.assertRaises(EvidenceUnavailable):
            select_frame(raw,'',self.targets,max_bytes=1024*1024)

    def test_invalid_loaded_address_shape_is_explicit_failure(self):
        for loaded in ({'readonly':'not-an-array'},{'writable':[False]},['bad']):
            tx=unrelated();tx['meta']['loadedAddresses']=loaded
            with self.subTest(loaded=loaded),self.assertRaises(EvidenceUnavailable):self.select(frame([tx]))

    def test_credentials_and_utf8_byte_bound_fail_before_preparation(self):
        raw=encode(frame([unrelated('credential-secret')]))
        with self.assertRaisesRegex(ValueError,'credential_publication_rejected'):
            select_frame(raw,'credential-secret',self.targets,max_bytes=len(raw))
        with self.assertRaises(EvidenceUnavailable):
            select_frame(raw,'',self.targets,max_bytes=len(raw)-1)
        raw=json.dumps({'method':'unrelated','x':'é'*100},ensure_ascii=False)
        with self.assertRaises(EvidenceUnavailable):
            select_frame(raw,'',self.targets,max_bytes=len(raw))

    def test_native_u64_and_escaped_keys_preserve_exact_values(self):
        tx=copy.deepcopy(self.templates['meteora'][0]);tx['meta']['preBalances']=[2**64-1]
        selected,_=self.parity(frame([tx]))
        projected=selected.message['params']['result']['value']['block']['transactions'][0]
        self.assertNotIn('preBalances',projected['meta'])
        tx=copy.deepcopy(self.templates['pump'][0]);raw=encode(frame([tx]))
        target=self.targets[0];escaped=''.join('\\u%04x'%ord(c) for c in target)
        raw=raw.replace(target.encode(),escaped.encode())
        selected=select_frame(raw,'',self.targets,max_bytes=len(raw)+1,
                              full_transaction_addresses=self.transaction_targets)
        self.assertEqual(selected.retained_transactions,1)

    def test_no_native_proxy_or_parser_state_escapes_concurrent_calls(self):
        value=frame([copy.deepcopy(self.templates['pump'][0]),unrelated()])
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            selected=list(pool.map(lambda _:self.select(value),range(16)))
        for item in selected:
            self.assertEqual(pickle.loads(pickle.dumps(item)),item)
        with self.assertRaises(EvidenceUnavailable):
            select_frame(b'{','',self.targets,max_bytes=1024)
        self.assertEqual(self.select(value).retained_transactions,1)

    def test_control_and_account_messages_preserve_content(self):
        for value in (dict(jsonrpc='2.0',id=1,result=10),dict(method='accountNotification',
            params=dict(subscription=1,result=dict(context=dict(slot=10),value=dict(data=['abc','base64']))))):
            selected=self.select(value)
            self.assertEqual(selected.message,value)
            self.assertEqual((selected.source_transactions,selected.retained_transactions),(0,0))


class LiveIntakeBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_dispatch_never_submits_raw_unrelated_body_to_process_pool(self):
        from tests.test_run372_large_frame_runtime import LargeFrameSocket,local_server,frame as wire_frame,observe
        real_factory=concurrent.futures.ProcessPoolExecutor;submissions=[]
        marker='UNRELATED_INTAKE_ONLY'*100000
        def factory(*args,**kwargs):
            pool=real_factory(*args,**kwargs);original=pool.submit
            def submit(function,*arguments,**keywords):
                if function is service.prepare_selected_source:
                    self.assertIsInstance(arguments[0],SelectedFrame)
                    self.assertNotIn(marker.encode(),pickle.dumps(arguments))
                    submissions.append(arguments[0].counters())
                return original(function,*arguments,**keywords)
            pool.submit=submit
            return pool
        with tempfile.TemporaryDirectory() as temp,patch('websockets.asyncio.client.connect',return_value=
            LargeFrameSocket([wire_frame(slot,[],marker) for slot in (300,301)])),patch(
            'asyncio.start_unix_server',side_effect=local_server),patch(
            'concurrent.futures.ProcessPoolExecutor',side_effect=factory),patch(
            'meme_machine.solana_evidence_service.time.time',return_value=2000000000.):
            path=Path(temp)/'db';stop=asyncio.Event()
            runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
            try:
                for _ in range(1000):
                    if runner.done():raise runner.exception() or AssertionError('service stopped')
                    if len(submissions)==2:
                        telemetry=await observe(path)
                        if (telemetry['service_health'].get('ipc') or {}).get('stream.intake_discarded_transactions')==2:
                            break
                    await asyncio.sleep(.01)
                else:self.fail('live intake boundary did not publish telemetry')
                self.assertEqual(len(submissions),2)
                self.assertTrue(all(row['materialized_transactions']==1 and row['discarded_transactions']==1 for row in submissions))
            finally:
                stop.set();await asyncio.wait_for(runner,20)


if __name__=='__main__':unittest.main()
