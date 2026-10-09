from io import BytesIO
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error

from meme_machine.runtime.provider_purchases import ProviderPurchases,provider_work,ledger,OPERATIONS
from operational.provider_cost_attribution import attribute
from meme_machine.lanes.pump.solana_read_rpc import ReadOnlyFailoverRPC,SolanaReadPacer
from meme_machine.lanes.pons.provider import Rpc


class OfflineSnapshotTests(unittest.TestCase):
    def test_cumulative_and_ring_counts_are_not_added_or_secret_identified(self):
        import hashlib,sqlite3
        from engineering.proven_efficiency.provider_snapshot import read_report
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'offline.sqlite'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE limits(endpoint,interval)')
                db.execute("INSERT INTO limits VALUES('secret-provider-endpoint',0.5)")
                db.execute('CREATE TABLE provider_usage(endpoint,lane,metric,value)')
                for metric,value in dict(physical_http_requests=3,completed_transport_attempts=2,
                        logical_rpc_calls=3,**{'method:eth_call':2,'method:eth_getBlockReceipts':1}).items():
                    db.execute('INSERT INTO provider_usage VALUES(?,?,?,?)',('secret-provider-endpoint','pons',metric,value))
                db.execute('CREATE TABLE transport_starts(seq INTEGER PRIMARY KEY,body)')
                db.execute('INSERT INTO transport_starts(body) VALUES(?)',(json.dumps(dict(
                    lane='pons',scope='position_monitor',endpoint_fingerprint='secret-provider-endpoint',
                    methods=['eth_call'],physical_requests=1)),))
            before=hashlib.sha256(path.read_bytes()).hexdigest();report=read_report(path)
            self.assertEqual(report['total_observed_physical_starts'],3)
            self.assertEqual(report['audit_rings']['transport_starts']['pons_held_protection']['records'],1)
            self.assertEqual(report['lanes']['pons']['unresolved_counter_difference'],1)
            self.assertEqual(report['total_known_estimated_billed_cu'],72)
            self.assertEqual(report['lanes']['pons']['estimated_throughput_cu'],552)
            self.assertIsNone(report['lanes']['pons']['delivered_bytes'])
            self.assertIsNone(report['verified_billed_cu']);self.assertIsNone(report['charged_failures'])
            self.assertNotIn('secret-provider-endpoint',json.dumps(report))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_other_database_schema_is_refused_without_mutation(self):
        import sqlite3
        from engineering.proven_efficiency.provider_snapshot import read_report
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'wrong.sqlite'
            with sqlite3.connect(path) as db:db.execute('CREATE TABLE unrelated(value)')
            before=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'offline_snapshot_schema'):read_report(path)
            self.assertEqual(path.read_bytes(),before)


class PurchaseAttributionTests(unittest.TestCase):
    def test_unknown_payload_and_request_sizes_remain_unmeasured(self):
        report=attribute([dict(purchase_id='unknown-bytes',methods=['eth_call'],
            request_bytes=None,delivered_payload_bytes=None,billed_cu=None)])
        self.assertEqual(report['unique_physical_purchases'],1)
        self.assertEqual(report['purchases_without_request_byte_measurement'],1)
        self.assertEqual(report['purchases_without_payload_byte_measurement'],1)
        self.assertIsNone(report['total_measured_billed_cu'])

    def test_native_evidence_consumer_deadline_join_bills_shared_purchase_once(self):
        from operational.provider_cost_attribution import join_native_decisions
        purchased=[dict(purchase_id='physical',completed=True,failed=False)]
        evidence=[dict(evidence_id='native-quote',purchase_ids=['physical'],canonical_hash='h',
            authenticated_by_native_validator=True)]
        consumers=[dict(decision_id='decision-'+c,evidence_ids=['native-quote'],consumer=c,
            canonical_hash='h',original_deadline=103,decided_at=102,native_decision={'action':'hold'})
            for c in ('current','survivor')]
        result=join_native_decisions(purchased,evidence,consumers)
        self.assertEqual(result['unique_physical_purchases'],1)
        self.assertEqual(result['linked_physical_purchases'],1)
        self.assertEqual(len(result['links']),2)
        self.assertEqual(result['provider_purchases_added'],0)
        consumers[1]['canonical_hash']='fork'
        with self.assertRaisesRegex(ValueError,'canonical'):join_native_decisions(purchased,evidence,consumers)
        consumers[1]['canonical_hash']='h';consumers[1]['decided_at']=104
        self.assertEqual(join_native_decisions(purchased,evidence,consumers)['late_consumer_links'],1)
        evidence[0]['authenticated_by_native_validator']=False
        self.assertEqual(join_native_decisions(purchased,evidence,consumers)['missing_or_unauthenticated_evidence_links'],2)

    def test_billed_weights_throughput_and_stream_redelivery_are_distinct(self):
        purchases=ProviderPurchases()
        with provider_work('history_receipt',family='pons',consumer='shared'):
            from meme_machine.runtime.provider_purchases import work_label
            label=work_label();purchases.started(label,['eth_getBlockReceipts'],100)
            purchases.completed(label,1000)
        report=purchases.snapshot()['totals']
        self.assertEqual(report['estimated_cu'],20);self.assertEqual(report['estimated_throughput_cu'],500)
        with provider_work('pump_discovery'):
            purchases.stream('solana_grpc',100,family='pump',redelivery=False)
            purchases.stream('solana_grpc',100,family='pump',redelivery=True)
        report=purchases.snapshot()['totals']
        self.assertIsNone(report['estimated_cu']);self.assertEqual(report['stream_redeliveries'],1)
        self.assertEqual(report['physical_requests'],1);self.assertEqual(report['delivered_payload_bytes'],1200)

    def pump(self,pacer=None):
        rpc=ReadOnlyFailoverRPC('https://solana-mainnet.g.alchemy.com/v2/offline-purchase-secret',pacer=pacer)
        rpc._pace=lambda *args,**kwargs:None;rpc.sleep=lambda *args:None
        return rpc

    def wire(self,request,*args,**kwargs):
        body=json.loads(request.data)
        if isinstance(body,list):return BytesIO(json.dumps([dict(jsonrpc='2.0',id=r['id'],result={'ok':True}) for r in body]).encode())
        return BytesIO(json.dumps(dict(jsonrpc='2.0',id=body['id'],result={'ok':True})).encode())

    def test_pump_native_boundary_records_one_purchase_and_two_logical_consumers(self):
        rpc=self.pump()
        with patch('urllib.request.urlopen',side_effect=self.wire) as transport:
            with provider_work('pump_current_qualification'):
                a=rpc.call('getMultipleAccounts',[['a'],{}])
            with provider_work('pump_held_protection',consumer='survivor'):
                b=rpc.call('getMultipleAccounts',[['a'],{}])
        self.assertEqual(a,b);self.assertEqual(transport.call_count,1)
        report=ledger(rpc).snapshot();self.assertEqual(report['totals']['physical_requests'],1)
        self.assertEqual(report['totals']['logical_consumers'],2);self.assertEqual(report['totals']['cache_hits'],1)
        self.assertEqual(report['totals']['known_estimated_cu'],20)
        self.assertGreater(report['totals']['delivered_payload_bytes'],0)
        self.assertNotIn('offline-purchase-secret',json.dumps(report))

    def test_pump_sessions_share_accounting_but_each_physical_attempt_is_charged(self):
        pacer=SolanaReadPacer();a=self.pump(pacer);b=self.pump(pacer)
        with patch('urllib.request.urlopen',side_effect=self.wire):
            a.call('getMultipleAccounts',[['a'],{}]);b.call('getMultipleAccounts',[['b'],{}])
        self.assertIs(ledger(a),ledger(b));self.assertEqual(ledger(a).snapshot()['totals']['physical_requests'],2)

    def test_retry_failure_and_bytes_are_subsets_of_the_original_operation(self):
        rpc=self.pump();calls=[]
        def wire(request,*args,**kwargs):
            calls.append(1)
            if len(calls)==1:raise urllib.error.URLError('offline failure containing secret')
            return self.wire(request)
        with patch('urllib.request.urlopen',side_effect=wire),provider_work('scaling_requalification',family='pump',consumer='survivor'):
            self.assertEqual(rpc.call('getMultipleAccounts',[['a'],{}]),{'ok':True})
        row=ledger(rpc).snapshot()['operations'][0]
        self.assertEqual((row['physical_requests'],row['retry_requests'],row['failed_requests']),(2,1,1))
        self.assertEqual(row['known_estimated_cu'],40)

    def test_pons_batch_counts_one_physical_request_and_each_purchased_method(self):
        rpc=Rpc('https://offline.invalid/private-secret',retries=0)
        with patch('meme_machine.lanes.pons.provider.urlopen',side_effect=self.wire),provider_work('pons_survivor_qualification'):
            result=rpc.batch([('eth_gasPrice',[]),('eth_getCode',['0x0','latest'])])
        self.assertEqual(result,[{'ok':True},{'ok':True}]);r=ledger(rpc).snapshot()
        self.assertEqual((r['totals']['physical_requests'],r['totals']['logical_consumers']),(1,2))
        self.assertEqual(r['totals']['known_estimated_cu'],40)
        self.assertNotIn('private-secret',json.dumps(r))

    def test_deadline_and_offline_injected_transport_do_not_invent_purchases(self):
        rpc=Rpc('https://offline.invalid/key',retries=0);rpc.evidence_deadline=time.monotonic()-1
        with patch('meme_machine.lanes.pons.provider.urlopen') as wire:
            with self.assertRaises(ValueError):rpc.call('eth_gasPrice',[])
            self.assertEqual(wire.call_count,0)
        self.assertEqual(ledger(rpc).snapshot()['totals'].get('physical_requests',0),0)
        rpc=Rpc('https://offline.invalid/key',transport=lambda method,params:'0x1')
        self.assertEqual(rpc.call('eth_gasPrice',[]),'0x1')
        self.assertEqual(ledger(rpc).snapshot()['totals'].get('physical_requests',0),0)

    def test_shared_purchase_records_bill_once_and_unknown_prices_remain_unknown(self):
        purchase=dict(purchase_id='receipt:1',methods=['eth_getTransactionReceipt'],billed_cu='20',
            delivered_payload_bytes=100,operation='pons_current_qualification',family='pons',consumer='current')
        shared=dict(purchase,operation='pons_survivor_qualification',consumer='survivor')
        report=attribute([purchase,shared])
        self.assertEqual(report['unique_physical_purchases'],1);self.assertEqual(report['shared_logical_consumers'],1)
        self.assertEqual(report['totals']['known_estimated_cu'],20);self.assertEqual(report['total_measured_billed_cu'],'20')
        shared['delivered_payload_bytes']=99
        with self.assertRaisesRegex(ValueError,'evidence_conflict'):attribute([purchase,shared])
        report=attribute([dict(purchase,purchase_id='unknown',methods=['unknown_provider_method'],billed_cu=None)])
        self.assertIsNone(report['totals']['estimated_cu']);self.assertIsNone(report['total_measured_billed_cu'])

    def test_all_required_categories_bounded_labels_and_unpriced_stream_bytes(self):
        self.assertEqual(len(OPERATIONS),13)
        records=[dict(kind='stream',stream_type='solana_grpc',delivered_payload_bytes=1234,
            operation='pump_discovery',family='pump',consumer='shared')]
        report=attribute(records);self.assertEqual(report['totals']['delivered_payload_bytes'],1234)
        self.assertIsNone(report['totals']['estimated_cu'])
        with self.assertRaisesRegex(ValueError,'operation'):
            with provider_work('secret-as-high-cardinality-label'):pass

    def test_nested_history_keeps_initiating_operation_and_memory_row_bound(self):
        from meme_machine.runtime.provider_purchases import work_label
        accounting=ProviderPurchases(max_rows=2)
        with provider_work('scaling_requalification',family='pons',consumer='survivor'):
            with provider_work('history_receipt'):
                accounting.started(work_label(),['eth_getTransactionReceipt'],1)
        first=accounting.snapshot()['operations'][0]
        self.assertEqual((first['operation'],first['origin_operation']),('history_receipt','scaling_requalification'))
        for operation in OPERATIONS:
            with provider_work(operation):accounting.started(work_label(),['eth_call'],1)
        self.assertEqual(len(accounting.rows),2)
        self.assertEqual(accounting.snapshot()['totals']['physical_requests'],14)

    def test_durable_pons_accounting_preserves_operation_across_reopen(self):
        from meme_machine.lanes.pons.provider_admission import Admission
        from meme_machine.runtime.robinhood.provider_usage import http_started,http_received,snapshot
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'usage';admission=Admission(path,'https://offline.invalid/key',lane='pons')
            def purchased():http_started(10);http_received(20);return 'result'
            with provider_work('pons_held_protection',consumer='survivor'):
                self.assertEqual(admission.invoke(purchased,['eth_call'],'exit'), 'result')
            result=snapshot(path,admission.endpoint)
            self.assertEqual(result['operation_purchases']['pons_held_protection']['physical_http_requests'],1)
            self.assertEqual(result['operation_purchases']['pons_held_protection']['delivered_payload_bytes'],20)
            self.assertEqual(result['physical_http_requests'],1)
            work=result['purchase_work'][0]
            self.assertEqual((work['family'],work['consumer'],work['purpose']),('pons','survivor','held_protection'))
            # Reopening/exporting cannot charge the same durable attempt again.
            self.assertEqual(snapshot(path,admission.endpoint)['purchase_work'],result['purchase_work'])
